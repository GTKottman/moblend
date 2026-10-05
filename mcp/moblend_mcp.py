#!/usr/bin/env python3
"""MoBlend MCP server (stdio, no dependencies).

Forwards tool calls to the MoBlend add-on inside Blender over a Unix socket
(see moblend/catalog.py: $XDG_RUNTIME_DIR/moblend.sock, override MOBLEND_SOCKET).

Register with Claude Code:
    claude mcp add moblend -s user -- python3 /path/to/moblend/mcp/moblend_mcp.py
"""

import base64
import importlib.util
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import time


def _load_catalog():
    """moblend/catalog.py is plain Python; load it by path (the package itself needs bpy)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "moblend", "catalog.py")
    spec = importlib.util.spec_from_file_location("moblend_catalog", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load_catalog()
SOCK = C.socket_path()
CALL_TIMEOUT = 300                    # seconds a single command may take inside Blender
LAUNCH_TRIES, LAUNCH_POLL = 120, 0.5  # wait up to 60 s for a launched Blender's bridge
_ids = itertools.count(1)

# --------------------------------------------------------------------------- schema helpers

OBJ = {"type": "string", "description": "Object name"}
VEC = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
INT, NUM, STR = {"type": "integer"}, {"type": "number"}, {"type": "string"}
PARAMS = {"type": "object", "description": "Parameter name -> value. Names are case/space-insensitive "
          "(see get_params). Angles in degrees, colors '#rrggbb' or [r,g,b], objects by name.",
          "additionalProperties": True}


def enum(values):
    return {"type": "string", "enum": list(values)}


def names(desc=None):
    d = {"type": "array", "items": {"type": "string"}}
    if desc:
        d["description"] = desc
    return d


def tool(name, desc, props=None, required=(), cmd=None):
    """`cmd` is the bridge command; None means the tool is handled here (launch_blender)."""
    return {"name": name, "description": desc, "cmd": cmd if cmd is not None else name,
            "inputSchema": {"type": "object", "properties": props or {}, "required": list(required)}}


EFFECTOR_DOC = (
    "Effector types: plain (offset position/rotation/scale/color inside its falloff), random (per-clone "
    "random or smooth noise), step (ramps 0→1 across clone index), noise (plain with an animated noise "
    "field, like C4D Shader effector), wave (sine wave travelling through the clones), time (params "
    "per second, e.g. Rotation [0,0,90] spins 90°/s), target (clones' Z axis looks at the effector), "
    "delay (clones lag/spring behind the motion produced by effectors above it; needs playback from "
    "frame 1), inheritance (params Source = another cloner, Inherit Color: clones morph into the source's "
    "arrangement; animate Strength), sound (params Sound = sound name or audio file path, Mode Spread (each "
    "clone its own log-spaced band between Low and High Hz) or All, Gain, Time Offset). The effector "
    "object's scale is the falloff size. Common params: Strength, Position, Rotation, Scale (added, -1 = vanish), Uniform Scale, Color, Color Mix, Local Space, Falloff, Inner, Invert.")

TOOLS = [
    tool("status", "Check that Blender with MoBlend is reachable; returns Blender version and file.", cmd="ping"),
    tool("launch_blender", "Start Blender (GUI) with the MoBlend bridge and wait until it answers.",
         {"file": {"type": "string", "description": "Optional .blend to open"}}, cmd=""),
    tool("scene_info", "Objects in the scene, frame range, camera, and all MoBlend objects with their links."),
    tool("list_mograph", "List MoBlend cloners, effectors, deformers and generators and what they affect."),
    tool("create_cloner",
         "Create a Cloner (C4D-style). Children are cloned from the given objects (moved into a hidden "
         "source collection, like C4D children); a cube is used when none are given. Modes and params: "
         "linear (Count, Offset, Step Rotation, Step Scale); radial (Count, Radius, Plane XY/XZ/YZ, "
         "Start Angle, End Angle, Align); grid (Count X/Y/Z, Spacing, Shape Cube/Sphere/Cylinder, "
         "Honeycomb); object (Object, Distribution Vertices/Faces/Surface, Count, Align); spline (Curve, "
         "Count, Offset 0..1 animatable, Spread, Align). All: Order Iterate/Random, Seed.",
         {"mode": enum(C.CLONER_MODES), "objects": names("Objects to clone"), "name": STR, "params": PARAMS,
          "location": VEC}, ["mode"]),
    tool("set_cloner_mode", "Switch an existing cloner's mode.", {"cloner": OBJ, "mode": enum(C.CLONER_MODES)},
         ["cloner", "mode"]),
    tool("add_clone_objects", "Add more objects to a cloner's children (cycled through by Order).",
         {"cloner": OBJ, "objects": names()}, ["cloner", "objects"]),
    tool("add_effector", "Add an effector and link it to cloners/MoText/fractured objects. " + EFFECTOR_DOC,
         {"type": enum(C.EFFECTOR_TYPES), "cloners": names("Targets to affect"), "params": PARAMS,
          "location": VEC, "size": {"type": "number", "description": "Falloff radius (object scale)"},
          "falloff": enum(C.FALLOFF_SHAPES), "name": STR}, ["type"]),
    tool("link_effector", "Link an existing effector to another cloner/MoText/fracture (shared params).",
         {"effector": OBJ, "target": OBJ}, ["effector", "target"]),
    tool("unlink_effector", "Remove an effector from a target's effector list.",
         {"effector": OBJ, "target": OBJ}, ["effector", "target"]),
    tool("add_deformer",
         "Add a deformer (placed by an empty; its scale sizes the effect) to target objects. bend/twist "
         "(param Angle, degrees) and taper/stretch (Factor) use Blender Simple Deform along `axis`; wave "
         "(Amplitude, Wavelength, Speed, Radial), spherify (Radius), shear (Amount), bulge (Amount), "
         "displace (Amplitude, Noise Size, Speed) support falloffs like effectors. Deformers realize clones.",
         {"type": enum(C.DEFORMER_TYPES), "targets": names(), "params": PARAMS, "location": VEC, "size": NUM,
          "axis": enum(C.AXES), "name": STR}, ["type", "targets"]),
    tool("attach_deformer", "Make an existing deformer also deform another object.",
         {"deformer": OBJ, "target": OBJ}, ["deformer", "target"]),
    tool("create_motext",
         "Create MoText: upright 3D text split into pieces effectors can animate. Params: Text, Font (name or "
         ".ttf/.otf path), Size, Depth, Split Characters/Words/Lines/Whole, Align Left/Center/Right, "
         "Character Spacing, Word Spacing, Line Spacing, Upright, Material.",
         {"text": STR, "name": STR, "params": PARAMS, "location": VEC}, ["text"]),
    tool("create_sweep",
         "Sweep a profile along a path curve (circle profile by default). Params: Radius, Sides, Start, End "
         "(animate for growth), Twist, End Scale (taper), Path Resolution, Fill Caps, Material.",
         {"path": OBJ, "profile": OBJ, "name": STR, "params": PARAMS}, ["path"]),
    tool("add_generator",
         "Add a generator to an object: fracture (mode Islands|Polygons: pieces become effectable), voronoi "
         "(pieces, seed, gap 0..0.9: convex Voronoi chunks, inner faces get an Inside material; call again to "
         "re-fracture from the original), "
         "tracer (tube through a cloner's clones; then set_params 'MB Tracer/Radius'), lathe (angle, steps, "
         "axis), extrude (depth), symmetry (axis), boole (cutter, operation DIFFERENCE/UNION/INTERSECT), "
         "subdivision (levels).",
         {"kind": enum(C.GENERATOR_KINDS), "object": OBJ,
          "options": {"type": "object", "description": "Kind-specific options, e.g. {\"mode\": \"Polygons\"} "
                      "or {\"cutter\": \"Cube\"}"}}, ["kind", "object"]),
    tool("get_params", "Read every editable parameter of a MoBlend object with type, value and options.",
         {"object": OBJ, "modifier": {"type": "string", "description": "Only this modifier (e.g. Tracer)"}},
         ["object"]),
    tool("set_params",
         "Set parameters of a cloner/effector/deformer/generator. Extra keys: location, size (uniform scale "
         "= falloff size), object_rotation (deg), object_scale. Pass frame to keyframe the values.",
         {"object": OBJ, "params": PARAMS, "frame": INT, "modifier": STR}, ["object", "params"]),
    tool("keyframes",
         "Animate parameters: frames maps frame number -> {param: value}. Example: {\"1\": {\"Strength\": 0}, "
         "\"48\": {\"Strength\": 1}}.",
         {"object": OBJ, "frames": {"type": "object", "additionalProperties": PARAMS}, "modifier": STR},
         ["object", "frames"]),
    tool("set_color_material", "Give objects (or a cloner's clones / MoText) a material showing effector "
         "colors (Color + Color Mix).", {"objects": names()}, ["objects"]),
    tool("set_material", "Create a simple material and assign it to objects (a cloner means its clones).",
         {"objects": names(), "color": STR, "metallic": NUM, "roughness": NUM,
          "emission": {"type": "number", "description": "Emission strength (glow) in the same color"},
          "name": STR}, ["objects"]),
    tool("add_primitive", "Add a mesh or curve primitive (size in meters, rotation in degrees).",
         {"kind": enum(C.PRIMITIVES), "name": STR, "location": VEC, "size": NUM, "rotation": VEC}, ["kind"]),
    tool("delete", "Delete MoBlend objects cleanly (cloners return their children to the scene).",
         {"objects": names()}, ["objects"]),
    tool("stats", "Evaluated instance/vertex/face counts of an object (to verify results).",
         {"object": OBJ}, ["object"]),
    tool("set_frame", "Set current frame and/or frame range and fps.",
         {"frame": INT, "start": INT, "end": INT, "fps": INT}),
    tool("frame_camera", "Create or aim the scene camera so all visible objects are in shot.",
         {"direction": VEC, "lens": NUM}),
    tool("render_preview",
         "Render a still and return it as an image so you can see the result. mode viewport = what the "
         "user's 3D view shows; camera = scene camera (created and aimed if missing).",
         {"frame": INT, "width": INT, "height": INT, "mode": enum(("auto", "viewport", "camera")),
          "engine": {"type": "string", "description": "Camera mode engine: BLENDER_WORKBENCH (fast) or "
                     "BLENDER_EEVEE"}}),
    tool("save_file", "Save the .blend (path for Save As).", {"path": STR}),
    tool("run_python", "Run Python inside Blender (bpy and api=moblend.api in scope; set `result`).",
         {"code": STR}, ["code"]),
]
BY_NAME = {t["name"]: t for t in TOOLS}

# --------------------------------------------------------------------------- bridge


class BridgeDown(Exception):
    pass


def call(cmd, args, timeout=CALL_TIMEOUT):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout + 5)
    try:
        s.connect(SOCK)
    except OSError as e:
        raise BridgeDown(
            f"Blender with MoBlend isn't reachable at {SOCK} ({e.strerror}). Open Blender with the MoBlend "
            "add-on enabled (the bridge starts automatically) or call launch_blender.") from None
    with s:
        f = s.makefile("rwb")
        f.write((json.dumps({"id": next(_ids), "cmd": cmd, "args": args, "timeout": timeout}) + "\n").encode())
        f.flush()
        line = f.readline()
    if not line:
        raise BridgeDown("Blender closed the connection")
    return json.loads(line)


def _ping():
    try:
        return call("ping", {}, 10)["result"]
    except BridgeDown:
        return None


def launch_blender(file=None):
    running = _ping()
    if running:
        return {"already_running": running}
    exe = os.environ.get("MOBLEND_BLENDER") or shutil.which("blender") or "blender"
    argv = [exe] + ([os.path.expanduser(file)] if file else [])
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        # Open silently on a side workspace so it never lands over the user's terminal.
        ws = os.environ.get("MOBLEND_HYPR_WORKSPACE", "10")
        quoted = " ".join(f"'{a}'" for a in argv)
        subprocess.Popen(["hyprctl", "dispatch", "exec", f"[workspace {ws} silent] {quoted}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(LAUNCH_TRIES):
        time.sleep(LAUNCH_POLL)
        info = _ping()
        if info:
            return {"launched": info}
    raise BridgeDown("Blender started but the MoBlend bridge never answered. Is the add-on enabled, with "
                     "'Start MCP bridge with Blender' on in its preferences?")


def _text(obj):
    return {"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, indent=1)}


def run_tool(name, args):
    """-> (content list, is_error)."""
    t = BY_NAME.get(name)
    if t is None:
        return [_text(f"Unknown tool {name}")], True
    try:
        if not t["cmd"]:
            return [_text(launch_blender(**args))], False
        resp = call(t["cmd"], args)
    except BridgeDown as e:
        return [_text(str(e))], True
    if not resp.get("ok"):
        return [_text(resp.get("error", "error") + "\n\n" + resp.get("trace", ""))], True
    res = resp["result"]
    content = [_text(res)]
    if name == "render_preview" and os.path.exists(res.get("path", "")):
        with open(res["path"], "rb") as fh:
            content.append({"type": "image", "data": base64.b64encode(fh.read()).decode(), "mimeType": "image/png"})
    return content, False


# --------------------------------------------------------------------------- JSON-RPC over stdio

INSTRUCTIONS = ("MoBlend drives Cinema 4D-style MoGraph in the user's live Blender: cloners, effectors with "
                "falloff fields, MoText, sweep, fracture, deformers. Typical flow: create_cloner -> add_effector "
                "-> set_params/keyframes -> render_preview to look. Angles are degrees.")


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _reply(mid, result=None, error=None):
    send({"jsonrpc": "2.0", "id": mid, **({"error": error} if error else {"result": result})})


def _initialize(params):
    return {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
            "serverInfo": {"name": "moblend", "version": "0.1.0"}, "instructions": INSTRUCTIONS}


def _tools_list(params):
    return {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]}


def _tools_call(params):
    content, err = run_tool(params.get("name"), params.get("arguments") or {})
    return {"content": content, "isError": err}


HANDLERS = {"initialize": _initialize, "tools/list": _tools_list, "tools/call": _tools_call,
            "ping": lambda params: {}}


def handle(msg):
    mid = msg.get("id")
    if mid is None:
        return  # notification
    handler = HANDLERS.get(msg.get("method"))
    if handler is None:
        _reply(mid, error={"code": -32601, "message": f"Unknown method {msg.get('method')}"})
    else:
        _reply(mid, handler(msg.get("params") or {}))


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        try:
            handle(msg)
        except Exception as e:  # keep the server alive whatever a tool does
            if msg.get("id") is not None:
                _reply(msg["id"], error={"code": -32603, "message": str(e)})


if __name__ == "__main__":
    main()
