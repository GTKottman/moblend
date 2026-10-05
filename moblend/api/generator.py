"""Generators: MoText and Sweep objects, and generator modifiers added to existing objects."""

import math

import bpy

from ..catalog import AXES, KEY_KIND, KEY_VOLUME_SETS, Kind
from ..nodes import generators
from .material import mograph_material
from .objects import (add_nodes_modifier, choice, get_object, get_objects, move_to_collection, new_mesh_object,
                      select_only, sources_root, tag)
from .params import set_params


# Modifier name of each node-group generator.
MOD_NAMES = {"motext": "MB MoText", "sweep": "MB Sweep", "fracture": "MB Fracture", "tracer": "MB Tracer",
             "volume": "MB Volume Builder"}


def _add_generator_modifier(o, key, first=False):
    return add_nodes_modifier(o, MOD_NAMES[key], generators.BUILDERS[key](), first)


def _generator_object(name, kind, key, values, location=None):
    """New mesh object whose only modifier is generator `key`, configured with `values`."""
    o = tag(new_mesh_object(name, location), **{KEY_KIND: kind})
    _add_generator_modifier(o, key)
    set_params(o, values)
    select_only(o)
    return o


def create_motext(text="MOBLEND", name=None, params=None, location=None):
    font = bpy.data.fonts.load("<builtin>", check_existing=True)  # the group input needs a font
    values = {"Text": text, "Font": font.name, "Material": mograph_material().name, **(params or {})}
    return _generator_object(name or "MoText", Kind.MOTEXT, "motext", values, location)


def create_sweep(path, profile=None, name=None, params=None):
    p = get_object(path)
    values = {"Path": p.name}
    if profile:
        prof = get_object(profile)
        prof.hide_render = True
        values["Profile"] = prof.name
    o = _generator_object(name or "Sweep", Kind.SWEEP, "sweep", {**values, **(params or {})})
    o.matrix_world = p.matrix_world.copy()
    p.hide_render = True
    return o


def _hidden_collection(name):
    coll = bpy.data.collections.new(name)
    sources_root().children.link(coll)
    return coll


def create_volume_builder(add=None, subtract=None, name=None, params=None):
    """Mesh from the union of `add` minus `subtract` (C4D Volume Builder + Volume Mesher).

    The objects move into hidden collections, like a cloner's children, and keep their world positions.
    """
    o = tag(new_mesh_object(name or "Volume Builder", (0, 0, 0)), **{KEY_KIND: Kind.VOLUME})
    sets = {mode: _hidden_collection(f"{o.name} {mode.title()}") for mode in KEY_VOLUME_SETS}
    for mode, coll in sets.items():
        o[KEY_VOLUME_SETS[mode]] = coll
    _add_generator_modifier(o, "volume")
    set_params(o, {"Add": sets["add"].name, "Subtract": sets["subtract"].name, **(params or {})})
    add_volume_objects(o, add or (), "add")
    add_volume_objects(o, subtract or (), "subtract")
    select_only(o)
    return o


def add_volume_objects(ref, objects, mode="add"):
    """Move objects into a volume builder's Add or Subtract set. O(objects)."""
    o = get_object(ref)
    coll = o[KEY_VOLUME_SETS[choice(mode, tuple(KEY_VOLUME_SETS), "mode")]]
    move_to_collection(get_objects(objects), coll)
    o.update_tag()
    return {m: [x.name for x in o[k].objects] for m, k in KEY_VOLUME_SETS.items()}


def add_fracture(ref, mode="Islands"):
    """Split a mesh into pieces effectors can move (C4D Fracture). Goes first in the stack."""
    o = get_object(ref)
    _add_generator_modifier(o, "fracture", first=True)
    o[KEY_KIND] = o.get(KEY_KIND) or Kind.FRACTURE
    set_params(o, {"Mode": mode}, modifier=MOD_NAMES["fracture"])
    return o


def add_tracer(ref, params=None):
    o = get_object(ref)
    _add_generator_modifier(o, "tracer")
    if params:
        set_params(o, params, modifier=MOD_NAMES["tracer"])
    return o


def _modifier(ref, name, kind, **props):
    o = get_object(ref)
    m = o.modifiers.new(name, kind)
    for k, v in props.items():
        setattr(m, k, v)
    return o


def add_lathe(ref, angle=360.0, steps=32, axis="Z"):
    return _modifier(ref, "MB Lathe", "SCREW", angle=math.radians(angle), steps=steps, render_steps=steps,
                     axis=choice(axis, AXES, "axis"), use_merge_vertices=True)


def add_extrude(ref, depth=0.2):
    o = get_object(ref)
    if o.type in ("CURVE", "FONT"):
        o.data.extrude = depth
        return o
    return _modifier(o, "MB Extrude", "SOLIDIFY", thickness=depth, offset=0.0)


def add_symmetry(ref, axis="X"):
    return _modifier(ref, "MB Symmetry", "MIRROR", use_axis=[a in axis.upper() for a in AXES], use_clip=True)


def add_boole(ref, cutter, operation="DIFFERENCE"):
    c = get_object(cutter)
    c.display_type, c.hide_render = "WIRE", True
    op = choice(operation, ("DIFFERENCE", "UNION", "INTERSECT"), "operation")
    return _modifier(ref, f"MB Boole {c.name}", "BOOLEAN", object=c, operation=op)


def add_subdivision(ref, levels=2):
    return _modifier(ref, "MB Subdivision", "SUBSURF", levels=levels, render_levels=levels)

