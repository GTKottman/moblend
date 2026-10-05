"""Demo: a MoGraph-style shot built only with MoBlend's API.

Run inside Blender's Python console / Text editor, or:
    blender --factory-startup -P examples/demo_scene.py            (opens it)
    blender -b --factory-startup -P examples/demo_scene.py -- out.png  (renders frame 40)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bpy  # noqa: E402
from moblend import api, commands  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.frame_start, sc.frame_end, sc.render.fps = 1, 120, 30

# A ring of cubes swept by a glowing effector sphere, plus noise wobble.
ring = api.create_cloner("radial", name="Ring", location=(0, 0, 0),
                         params={"Count": 24, "Radius": 5, "Plane": "XY"})
cube = ring["mb_clones"].objects[0]
cube.scale = (0.5, 0.5, 1.6)
push = api.add_effector("plain", name="Push", cloners=[ring.name], location=(5, 0, 0), size=3.0,
                        params={"Position": [0, 0, 1.5], "Uniform Scale": 0.5, "Rotation": [0, 0, 45],
                                "Color": "#ff5a1f", "Color Mix": 1.0, "Inner": 0.2})
api.add_effector("random", name="Jitter", cloners=[ring.name],
                 params={"Mode": "Noise", "Rotation": [8, 8, 0], "Position": [0, 0, 0.3]})
# Orbit the push effector around the ring.
push.location = (5, 0, 0)
for f, (x, y) in ((1, (5, 0)), (31, (0, 5)), (61, (-5, 0)), (91, (0, -5)), (121, (5, 0))):
    api.set_params(push, {"location": [x, y, 0]}, frame=f)

title = api.create_motext("MOBLEND", name="Title", location=(0, 0, 1.2),
                          params={"Size": 1.4, "Depth": 0.3})
api.add_effector("step", name="Rise", cloners=[title.name], falloff="Infinite",
                 params={"Position": [0, 0, 0.4], "Color": "#3fa9f5", "Color Mix": 1.0, "Local Space": False})

commands.add_primitive("plane", name="Floor", size=60, location=(0, 0, -1.2))
commands.set_material(["Floor"], color="#16181d", roughness=0.6)
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 3.0
sun.rotation_euler = (0.7, 0.2, 0.6)
sc.collection.objects.link(sun)
world = bpy.data.worlds.new("World")
world.use_nodes = True
next(n for n in world.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.02, 0.022, 0.03, 1)
sc.world = world
commands.frame_camera(direction=(0.0, -1.0, 0.45), lens=40)

if "--" in sys.argv:
    out = sys.argv[sys.argv.index("--") + 1]
    print(commands.render_preview(frame=40, width=1280, height=720, mode="camera", engine="BLENDER_EEVEE",
                                  path=os.path.abspath(out)))
