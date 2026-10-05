"""Bridge commands: JSON in, JSON out. Each runs on Blender's main thread.

Most commands are API functions registered with argument aliases (the MCP schema
says `type`/`object`; the API avoids shadowing those builtins). Results are made
JSON-safe in one place: Blender IDs become their names.
"""

import contextlib
import io
import json
import math
import os
import tempfile
import traceback
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

from . import api
from .catalog import KEY_TYPE, PRIMITIVES


@dataclass
class Command:
    fn: callable
    aliases: dict = field(default_factory=dict)  # JSON arg name -> function arg name
    describe: bool = False                       # return get_params() of the resulting object


COMMANDS = {}


def command(name=None, aliases=None, describe=False):
    def deco(fn):
        COMMANDS[name or fn.__name__] = Command(fn, aliases or {}, describe)
        return fn
    return deco


def register(name, fn, aliases=None, describe=False):
    command(name, aliases, describe)(fn)


# ---------------------------------------------------------------- API pass-throughs

OBJ = {"object": "ref"}
register("create_cloner", api.create_cloner, describe=True)
register("set_cloner_mode", api.set_cloner_mode, {"cloner": "ref"}, describe=True)
register("add_clone_objects", api.add_clone_objects, {"cloner": "ref"})
register("add_effector", api.add_effector, {"type": "effector_type"}, describe=True)
register("add_deformer", api.add_deformer, {"type": "deformer_type"}, describe=True)
register("attach_deformer", api.attach_deformer)
register("create_motext", api.create_motext, describe=True)
register("create_sweep", api.create_sweep, describe=True)
register("get_params", api.get_params, OBJ)
register("set_params", api.set_params, {**OBJ, "params": "values"})
register("set_color_material", api.set_color_material)
register("list_mograph", api.list_mograph)
register("stats", api.evaluated_stats, OBJ)


@command()
def ping():
    return {"blender": bpy.app.version_string, "file": bpy.data.filepath or "(unsaved)",
            "scene": bpy.context.scene.name}


@command()
def scene_info():
    """O(objects) plus one usage-index pass for the MoGraph summary."""
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    objs = []
    for o in sc.objects:
        item = {"name": o.name, "type": o.type, "location": [round(x, 3) for x in o.location]}
        if api.mb_kind(o):
            item["moblend"] = f"{api.mb_kind(o)}:{o.get(KEY_TYPE, '')}".rstrip(":")
        if o.name in vl.objects and o.hide_get():
            item["hidden"] = True
        objs.append(item)
    return {"scene": sc.name, "frame": sc.frame_current, "frame_range": [sc.frame_start, sc.frame_end],
            "fps": sc.render.fps, "camera": sc.camera.name if sc.camera else None,
            "render_engine": sc.render.engine, "objects": objs, "mograph": api.list_mograph()}


@command()
def link_effector(effector, target):
    api.link_effector(effector, target)
    return {"target": target, "effectors": api.effectors_of(target)}


@command()
def unlink_effector(effector, target):
    api.unlink_effector(effector, target)
    return {"target": target, "effectors": api.effectors_of(target)}


@command(aliases={"object": "ref"})
def add_generator(kind, ref, options=None):
    """fracture | tracer | lathe | extrude | symmetry | boole | subdivision on an object."""
    if kind not in api.GENERATORS:
        raise ValueError(f"kind must be one of {list(api.GENERATORS)}")
    o = api.GENERATORS[kind](ref, **(options or {}))
    return {"object": o.name, "modifiers": [m.name for m in o.modifiers]}


@command(aliases={"object": "ref"})
def keyframes(ref, frames, modifier=None):
    """frames: {frame_number: {param: value}}; sets and keys each frame in order. O(F log F + F x P)."""
    ordered = sorted((int(float(f)), v) for f, v in frames.items())
    for frame, values in ordered:
        api.set_params(ref, values, frame, modifier)
    return {"object": api.get_object(ref).name, "frames": [f for f, _ in ordered]}


@command()
def delete(objects):
    return {"deleted": [api.delete(o) for o in (objects if isinstance(objects, list) else [objects])]}


@command()
def set_material(objects, color="#cccccc", metallic=0.0, roughness=0.4, emission=0.0, name=None):
    """Simple Principled material assigned to objects (a cloner means its clones)."""
    mat = api.solid_material(color, metallic, roughness, emission, name)
    return {"material": mat.name, "objects": api.assign_material(objects, mat)}


# ---------------------------------------------------------------- primitives

def _spiral(size, name):
    cu = bpy.data.curves.new(name or "Spiral", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    n, turns = 200, 4
    sp.points.add(n - 1)
    for i, p in enumerate(sp.points):
        t = i / (n - 1)
        a = t * turns * 2 * math.pi
        p.co = (math.cos(a) * size / 2, math.sin(a) * size / 2, t * size * 2, 1)
    o = bpy.data.objects.new(cu.name, cu)
    (bpy.context.collection or bpy.context.scene.collection).objects.link(o)
    return o


def _op(fn, **kw):
    """Wrap a bpy.ops primitive so every builder is (size, name) -> object."""
    def make(size, name):
        fn(**{k: v(size) for k, v in kw.items()})
        return bpy.context.object
    return make


_PRIMS = {
    "cube": _op(bpy.ops.mesh.primitive_cube_add, size=lambda s: s),
    "sphere": _op(bpy.ops.mesh.primitive_uv_sphere_add, radius=lambda s: s / 2),
    "icosphere": _op(bpy.ops.mesh.primitive_ico_sphere_add, radius=lambda s: s / 2),
    "cylinder": _op(bpy.ops.mesh.primitive_cylinder_add, radius=lambda s: s / 2, depth=lambda s: s),
    "cone": _op(bpy.ops.mesh.primitive_cone_add, radius1=lambda s: s / 2, depth=lambda s: s),
    "torus": _op(bpy.ops.mesh.primitive_torus_add, major_radius=lambda s: s / 2, minor_radius=lambda s: s / 8),
    "plane": _op(bpy.ops.mesh.primitive_plane_add, size=lambda s: s),
    "monkey": _op(bpy.ops.mesh.primitive_monkey_add, size=lambda s: s),
    "circle_curve": _op(bpy.ops.curve.primitive_bezier_circle_add, radius=lambda s: s / 2),
    "bezier_curve": _op(bpy.ops.curve.primitive_bezier_curve_add, radius=lambda s: s / 2),
    "spiral_curve": _spiral,
}
assert set(_PRIMS) == set(PRIMITIVES), "catalog.PRIMITIVES and _PRIMS disagree"


@command()
def add_primitive(kind="cube", name=None, location=(0, 0, 0), size=1.0, rotation=(0, 0, 0)):
    if kind not in _PRIMS:
        raise ValueError(f"kind must be one of {list(PRIMITIVES)}")
    o = _PRIMS[kind](float(size), name)
    o.location = location
    o.rotation_euler = [math.radians(x) for x in rotation]
    if name:
        o.name = name
        o.data.name = name
    return {"object": o.name, "type": o.type}


# ---------------------------------------------------------------- scene, camera, render

@command()
def set_frame(frame=None, start=None, end=None, fps=None):
    sc = bpy.context.scene
    for attr, v in (("frame_start", start), ("frame_end", end)):
        if v is not None:
            setattr(sc, attr, int(v))
    if fps is not None:
        sc.render.fps = int(fps)
    if frame is not None:
        sc.frame_set(int(frame))
    return {"frame": sc.frame_current, "frame_range": [sc.frame_start, sc.frame_end], "fps": sc.render.fps}


def _scene_bounds():
    """Center and radius of everything visible. One streaming pass: O(instances), O(1) memory."""
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type not in ("MESH", "CURVE", "FONT") or not ob.visible_get():
            continue
        m = inst.matrix_world
        for corner in ob.bound_box:
            p = m @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    if lo.x == math.inf:
        return Vector((0, 0, 0)), 5.0
    return (lo + hi) / 2, max((hi - lo).length / 2, 0.5)


@command()
def frame_camera(direction=(1.0, -1.4, 0.8), lens=50.0):
    """Create/aim the scene camera so everything visible fits in the frame."""
    sc = bpy.context.scene
    cam = sc.camera
    if cam is None:
        cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        sc.collection.objects.link(cam)
        sc.camera = cam
    cam.data.lens = lens
    center, radius = _scene_bounds()
    fov = 2 * math.atan(cam.data.sensor_width / (2 * lens))
    aspect = sc.render.resolution_x / sc.render.resolution_y
    narrow_fov = fov if aspect >= 1 else 2 * math.atan(math.tan(fov / 2) * aspect)
    dist = radius / math.sin(narrow_fov / 2) * 1.05
    d = Vector(direction).normalized()
    cam.location = center + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = max(1000.0, dist * 4)
    return {"camera": cam.name, "location": [round(x, 3) for x in cam.location]}


@contextlib.contextmanager
def _temporarily(target, **attrs):
    """Set attributes for the duration of a block, then restore them."""
    saved = {k: getattr(target, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(target, k, v)
        yield target
    finally:
        for k, v in saved.items():
            setattr(target, k, v)


def _view3d():
    """(window, area, region) of the first 3D view, or None in background mode."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                return win, area, next(r for r in area.regions if r.type == "WINDOW")
    return None


_ENGINE_ALIASES = {"WORKBENCH": "BLENDER_WORKBENCH", "EEVEE": "BLENDER_EEVEE"}


@command()
def render_preview(frame=None, width=960, height=540, mode="auto", engine="BLENDER_WORKBENCH", path=None):
    """Render a still. viewport = what the 3D view shows; camera = scene camera (created and aimed if
    missing); auto = viewport when a 3D view exists."""
    sc = bpy.context.scene
    if frame is not None:
        sc.frame_set(int(frame))
    path = path or os.path.join(tempfile.gettempdir(), f"moblend_preview_{os.getpid()}.png")
    view = _view3d() if mode in ("auto", "viewport") else None
    r = sc.render
    with _temporarily(r, resolution_x=int(width), resolution_y=int(height), resolution_percentage=100,
                      filepath=path, engine=r.engine), _temporarily(r.image_settings, file_format="PNG"):
        if view:
            win, area, region = view
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.render.opengl(write_still=True, view_context=True)
            used = "viewport"
        else:
            if sc.camera is None:
                frame_camera()
            engine = _ENGINE_ALIASES.get(engine.upper(), engine.upper())
            try:
                r.engine = engine
            except TypeError as e:
                raise ValueError(f"engine: {e}") from None
            if engine == "BLENDER_WORKBENCH":
                sc.display.shading.light, sc.display.shading.color_type = "STUDIO", "MATERIAL"
            bpy.ops.render.render(write_still=True)
            used = "camera"
    return {"path": path, "mode": used, "frame": sc.frame_current}


@command()
def save_file(path=None):
    if path:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.expanduser(path))
    elif bpy.data.filepath:
        bpy.ops.wm.save_mainfile()
    else:
        raise ValueError("File was never saved; pass a path")
    return {"file": bpy.data.filepath}


@command()
def run_python(code):
    """Escape hatch: run Python with bpy and api (moblend.api) in scope; set `result` to return a value."""
    ns = {"bpy": bpy, "api": api, "math": math, "Vector": Vector}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(code, ns)
    return {"stdout": buf.getvalue()[-20000:], "result": ns.get("result")}


# ---------------------------------------------------------------- dispatch

def _jsonable(v):
    """Blender IDs -> names, recursively; anything else non-JSON -> repr. O(size of v)."""
    if isinstance(v, bpy.types.ID):
        return v.name
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    try:
        json.dumps(v)
        return v
    except TypeError:
        return repr(v)


def dispatch(cmd, args):
    c = COMMANDS.get(cmd)
    if c is None:
        raise ValueError(f"Unknown command {cmd!r}. Known: {sorted(COMMANDS)}")
    kwargs = {c.aliases.get(k, k): v for k, v in (args or {}).items()}
    try:
        res = c.fn(**kwargs)
    except TypeError as e:
        if "argument" in str(e):  # a bad argument name from the caller, not a bug inside the command
            raise ValueError(f"{cmd}: {e}") from None
        raise
    return _jsonable(api.get_params(res) if c.describe else res)


def safe_dispatch(cmd, args):
    try:
        return {"ok": True, "result": dispatch(cmd, args)}
    except Exception as e:  # report every failure back to the caller
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-3000:]}
