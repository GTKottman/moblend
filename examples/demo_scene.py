"""Demo: the MoBlend title shot, built only with MoBlend's API.

A wall of 1,900 cubes behind the title: a Noise-mode Random effector pushes it into relief and fifteen Plain
effectors paint drifting pools of color into it. In front, bevelled MoText with one palette color per letter
(Multi shader), a tilted ring of spheres orbiting it, and depth of field that softens the wall.

Run inside Blender's Python console / Text editor, or:
    blender --factory-startup -P examples/demo_scene.py            (opens it)
    blender -b --factory-startup -P examples/demo_scene.py -- out.png  (renders frame 40)
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
import bpy  # noqa: E402
from gallery.studio import COLORS, PALETTE, material  # noqa: E402
from moblend import api  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
api.register()
sc = bpy.context.scene
sc.frame_start, sc.frame_end, sc.render.fps = 1, 120, 30
sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples, sc.eevee.use_raytracing = 64, True
sc.render.resolution_x, sc.render.resolution_y = 1600, 900

# The wall: an upright grid of cubes (XZ plane) 6 m behind the title.
bpy.ops.mesh.primitive_cube_add(size=0.5)
brick = bpy.context.object
bpy.ops.object.modifier_add(type="BEVEL")
brick.modifiers[-1].width, brick.modifiers[-1].segments = 0.04, 2
wall = api.create_cloner("grid", objects=[brick], name="Wall", location=(0, 10, 4), params={
    "Count X": 64, "Count Y": 1, "Count Z": 30, "Spacing": [0.56, 0.56, 0.56]})
api.add_effector("plain", name="Base", cloners=[wall], falloff="Infinite",
                 params={"Position": [0, 0, 0], "Color": "#1a1340", "Color Mix": 1.0})  # deep indigo base
api.add_effector("random", name="Relief", cloners=[wall], params={
    "Mode": "Noise", "Position": [0, 1.6, 0], "Rotation": [0, 0, 0], "Uniform Scale": 0.25, "Local Space": False,
    "Noise Scale": 0.35})
# Pools sit above and beside the title, so the band right behind the letters stays dark.
pools = ((-14, 4, "orange"), (-10, 10, "violet"), (-5, 9, "yellow"), (0, 11.5, "pink"), (4.5, 9, "blue"),
         (9.5, 10.5, "orange"), (14, 5, "green"), (-16, -1, "blue"), (17, 0, "yellow"), (14.5, 12, "violet"),
         (-9, -1.5, "pink"), (-1, -2, "green"), (7, -1.5, "blue"), (-17, 9, "green"), (19, 8, "pink"))
for i, (x, z, color) in enumerate(pools):
    pool = api.add_effector("plain", name=f"Pool {i}", cloners=[wall], location=(x, 10, z), size=3.4, params={
        "Position": [0, -0.9, 0], "Uniform Scale": 0.15, "Color": PALETTE[color], "Color Mix": 1.0,
        "Inner": 0.0, "Local Space": False})
    for f, dx in ((1, 0.0), (61, 2.0 if i % 2 else -2.0), (121, 0.0)):  # the pools drift across the wall
        api.set_params(pool, {"location": [x + dx, 10, z]}, frame=f)
api.set_color_material([wall])

# The title: one palette color per letter (Multi shader by index).
title = api.create_motext("MOBLEND", name="Title", location=(0, 0, 3.2), params={
    "Size": 2.4, "Depth": 0.7, "Bevel": 0.05, "Bevel Segments": 3, "Character Spacing": 1.08})
api.add_effector("random", name="Tumble", cloners=[title], params={
    "Position": [0, 0.25, 0.2], "Rotation": [6, 0, 8], "Seed": 3})
api.multi_material([title], [PALETTE[k] for k in ("orange", "yellow", "green", "blue", "violet", "pink", "white")])

# A tilted ring of glossy spheres around the title, colored at random.
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.17, segments=32, ring_count=16)
bead = bpy.context.object
bpy.ops.object.shade_smooth()
ring = api.create_cloner("radial", objects=[bead], name="Orbit", location=(0, 0, 3.2),
                         params={"Count": 48, "Radius": 7.0, "Plane": "XZ"})
ring.rotation_euler = (math.radians(74), math.radians(-14), 0)
api.add_effector("random", name="Sizes", cloners=[ring], params={"Uniform Scale": 0.9, "Seed": 11})
api.multi_material([ring], COLORS, mode="Random")

# Floor that catches the color.
bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 0, -0.6))
floor = bpy.context.object
floor.data.materials.append(material("ink", roughness=0.18, coat=0.6, name="Floor"))

# Light: a soft warm key, a cool rim, glowing color from the wall.
for name, loc, energy, color, size in (("Key", (-7, -12, 12), 9000, "#fff1e0", 9),
                                       ("Rim", (10, 2, 10), 6000, "#d0e4ff", 6),
                                       ("Fill", (4, -14, 2), 2500, "#ffd6e6", 10)):
    light = bpy.data.objects.new(name, bpy.data.lights.new(name, "AREA"))
    light.data.energy, light.data.size, light.data.color = energy, size, api.parse_color(color)[:3]
    light.location = loc
    light.rotation_euler = (bpy.data.objects["Title"].location - light.location).to_track_quat("-Z", "Y").to_euler()
    sc.collection.objects.link(light)
world = bpy.data.worlds.new("World")
world.use_nodes = True
next(n for n in world.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = \
    api.parse_color(PALETTE["ink"])
sc.world = world

cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 42
cam.location = (0.8, -21, 4.9)
cam.rotation_euler = (math.radians(86), 0, math.radians(3))
cam.data.dof.use_dof, cam.data.dof.focus_object, cam.data.dof.aperture_fstop = True, title, 0.35  # wall goes soft

if "--" in sys.argv:
    sc.frame_set(40)
    sc.render.filepath = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
    bpy.ops.render.render(write_still=True)
