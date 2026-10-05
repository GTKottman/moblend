"""Shared look for the gallery renders: a seamless curved backdrop, soft area lights, a camera framed on the
subject, and one palette. Every scene function builds its subject with `moblend.api`, then calls shoot().
"""

import math

import bmesh
import bpy
from mathutils import Vector

from moblend import api

PALETTE = {
    "ink": "#0b0c10", "slate": "#262a33", "paper": "#efe9df", "sand": "#e6d5b8",
    "orange": "#ff5a1f", "blue": "#3fa9f5", "yellow": "#f5c83f", "green": "#7ad151", "pink": "#ff6f91",
    "violet": "#8b6cf6", "white": "#f7f5f0",
}
COLORS = [PALETTE[k] for k in ("orange", "blue", "yellow", "green", "pink", "violet")]


def material(color, roughness=0.35, metallic=0.0, emission=0.0, coat=0.25, name=None):
    mat = api.solid_material(PALETTE.get(color, color), metallic, roughness, emission, name)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Coat Weight"].default_value = coat
    return mat


def paint(objects, color, **kw):
    """Give objects (or a cloner's clones) a solid material."""
    api.assign_material(objects, material(color, **kw))


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 48
    scene.eevee.use_raytracing = True
    scene.eevee.use_shadows = True
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.fps = 24
    return scene


def _cyclorama(color):
    """Floor that curves up into a back wall (+Y), so the background has no horizon line."""
    me = bpy.data.meshes.new("Backdrop")
    bm = bmesh.new()
    profile = [(y, 0.0) for y in (-60, -10, 0)]
    profile += [(math.sin(a) * 12, 12 - math.cos(a) * 12) for a in [i * math.pi / 2 / 16 for i in range(1, 17)]]
    profile += [(12, 60)]
    rows = []
    for x in (-80, 80):
        rows.append([bm.verts.new((x, y, z)) for y, z in profile])
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new("Backdrop", me)
    bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(material(color, roughness=0.6, coat=0.0, name="Backdrop"))
    return o


def _corners(subjects):
    """World-space bounding-box corners of the subjects and everything they instance."""
    names = {o.name for o in subjects}
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for inst in dg.object_instances:
        owner = inst.parent.original.name if inst.is_instance and inst.parent else inst.object.original.name
        if owner not in names or inst.object.type not in ("MESH", "CURVE", "FONT", "POINTCLOUD"):
            continue
        pts += [inst.matrix_world @ Vector(c) for c in inst.object.bound_box]
    return pts


def _area_light(name, location, target, size, energy, color="#ffffff"):
    light = bpy.data.lights.new(name, "AREA")
    light.size, light.energy = size, energy
    light.color = api.parse_color(color)[:3]
    o = bpy.data.objects.new(name, light)
    bpy.context.scene.collection.objects.link(o)
    o.location = location
    o.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
    return o


def shoot(subjects, ground="ink", direction=(0.55, -1.0, 0.5), lens=50, margin=1.06, frame=None, key=1.0,
          warm=True):
    """Backdrop, lights and camera around `subjects`; returns the camera."""
    scene = bpy.context.scene
    if frame is not None:
        for f in range(scene.frame_start, frame + 1):  # simulations need every frame in order
            scene.frame_set(f)
    pts = _corners(subjects)
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 0.5)
    d = Vector(direction).normalized()
    flat = Vector((d.x, d.y, 0)).normalized()
    back = _cyclorama(ground)
    back.rotation_euler.z = math.atan2(flat.x, -flat.y)  # local +Y (the wall) points away from the camera
    back.location = center - flat * (radius * 1.6)
    back.location.z = lo.z - 0.001

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = api.parse_color(PALETTE.get(ground, ground))
    bg.inputs["Strength"].default_value = 0.35
    scene.world = world

    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.lens = lens
    rot = (-d).to_track_quat("-Z", "Y")
    cam.rotation_euler = rot.to_euler()
    # Back the camera off until every corner fits: |x| <= depth * tan(half fov) / margin, per axis.
    aspect = scene.render.resolution_x / scene.render.resolution_y
    tan_x = cam.data.sensor_width / (2 * lens)  # the sensor spans the wider (horizontal) side
    tan_y = tan_x / aspect
    right, up = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    dist = max(max(abs((p - center).dot(right)) * margin / tan_x, abs((p - center).dot(up)) * margin / tan_y)
               + (p - center).dot(d) for p in pts)
    cam.location = center + d * dist
    cam.data.clip_end = dist * 20

    side = flat.cross(Vector((0, 0, 1)))
    reach = radius * 3.0
    scale = reach * reach * key
    _area_light("Key", center + (-side * 0.9 + flat * 0.8 + Vector((0, 0, 1.3))) * reach, center, reach * 0.9,
                55 * scale, "#fff1e0" if warm else "#ffffff")
    _area_light("Rim", center + (side * 0.8 - flat * 1.2 + Vector((0, 0, 1.0))) * reach, center, reach * 0.6,
                40 * scale, "#e0ecff")
    _area_light("Top", center + Vector((0, 0, 1.6)) * reach, center, reach * 1.5, 18 * scale)
    return cam


def render(path):
    scene = bpy.context.scene
    scene.render.filepath = path
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    return path
