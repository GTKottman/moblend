"""Functional tests. Run: blender -b --factory-startup -P tests/test_api.py

Builds each MoBlend feature in an empty scene and checks the evaluated result.
Takes a few seconds.
"""

import math
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from moblend import api  # noqa: E402

FAILS = []


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def instances(o):
    dg = bpy.context.evaluated_depsgraph_get()
    return [inst.matrix_world.copy() for inst in dg.object_instances
            if inst.is_instance and inst.parent and inst.parent.original == o]


def case(fn):
    try:
        reset()
        fn()
        print("PASS", fn.__name__)
    except Exception:
        FAILS.append(fn.__name__)
        print("FAIL", fn.__name__)
        traceback.print_exc()
    return fn


def near(a, b, tol=1e-3):
    return (Vector(a) - Vector(b)).length < tol


@case
def catalog_matches_builders_and_all_groups_build():
    from moblend import catalog, nodes
    assert set(nodes.cloners.BUILDERS) == set(catalog.CLONER_MODES)
    assert set(nodes.effectors.BUILDERS) == set(catalog.EFFECTOR_TYPES)
    assert set(nodes.deformers.BUILDERS) == set(catalog.GN_DEFORMERS)
    assert set(api.GENERATORS) == set(catalog.GENERATOR_KINDS)
    groups = nodes.build_all()
    bad = [(g.name, link.from_socket.name) for g in groups for link in g.links if not link.is_valid]
    assert not bad, bad


@case
def effector_reorder_stays_below_cloner():
    c = api.create_cloner("linear", location=(0, 0, 0))
    a = api.add_effector("plain", name="A", cloners=[c.name])
    b = api.add_effector("plain", name="B", cloners=[c.name])
    assert [e["effector"] for e in api.effectors_of(c)] == ["A", "B"]
    assert api.move_effector(c, "MBE B", -1)
    assert [e["effector"] for e in api.effectors_of(c)] == ["B", "A"]
    assert not api.move_effector(c, "MBE B", -1)  # would pass the cloner modifier
    assert c.modifiers[0].name == "MB Cloner"
    api.add_tracer(c.name)
    api.add_effector("plain", name="C", cloners=[c.name])
    assert c.modifiers[-1].name == "MB Tracer"  # new effectors go above the tracer
    assert {i["name"]: i.get("affects") for i in api.list_mograph() if i["kind"] == "effector"} == \
        {"A": [c.name], "B": [c.name], "C": [c.name]}
    assert a and b


@case
def linear_cloner():
    c = api.create_cloner("linear", params={"Count": 4, "Offset": [2, 0, 0]}, location=(0, 0, 0))
    m = instances(c)
    assert len(m) == 4, len(m)
    xs = sorted(round(x.translation.x, 3) for x in m)
    assert xs == [0, 2, 4, 6], xs


@case
def clones_keep_child_rotation_and_scale():
    bpy.ops.mesh.primitive_cube_add(size=1, location=(7, 7, 7))
    cube = bpy.context.object
    cube.scale = (0.5, 0.5, 2.0)
    c = api.create_cloner("linear", objects=[cube.name], params={"Count": 2, "Offset": [3, 0, 0]},
                          location=(0, 0, 0))
    m = instances(c)
    assert sorted(round(x.translation.x, 3) for x in m) == [0, 3], [x.translation for x in m]
    assert all(near(x.to_scale(), (0.5, 0.5, 2.0)) for x in m), [x.to_scale() for x in m]


@case
def radial_cloner_and_menu():
    c = api.create_cloner("radial", params={"Count": 6, "Radius": 3, "Plane": "xz"}, location=(0, 0, 0))
    m = instances(c)
    assert len(m) == 6
    assert all(abs(x.translation.y) < 1e-4 and abs(x.translation.length - 3) < 1e-3 for x in m)
    assert api.get_params(c)["params"]["Plane"]["value"] == "XZ"


@case
def grid_sphere_shape():
    c = api.create_cloner("grid", params={"Count X": 5, "Count Y": 5, "Count Z": 5}, location=(0, 0, 0))
    assert len(instances(c)) == 125
    api.set_params(c, {"shape": "Sphere"})
    n = len(instances(c))
    assert 30 < n < 125, n


@case
def object_cloner():
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=2)
    ico = bpy.context.object
    c = api.create_cloner("object", params={"Object": ico.name, "Distribution": "Vertices"}, location=(0, 0, 0))
    assert len(instances(c)) == 12
    api.set_params(c, {"Distribution": "Surface", "Count": 40})
    n = len(instances(c))
    assert 20 < n < 60, n


@case
def spline_cloner():
    bpy.ops.curve.primitive_bezier_circle_add(radius=2, location=(0, 0, 0))
    crv = bpy.context.object
    c = api.create_cloner("spline", params={"Curve": crv.name, "Count": 10}, location=(0, 0, 0))
    m = instances(c)
    assert len(m) == 10
    assert all(abs(x.translation.length - 2) < 0.05 for x in m), [x.translation.length for x in m]


@case
def iterate_two_children():
    bpy.ops.mesh.primitive_cube_add(size=1)
    a = bpy.context.object
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5)
    s = bpy.context.object
    c = api.create_cloner("linear", objects=[a.name, s.name], params={"Count": 6}, location=(0, 0, 0))
    dg = bpy.context.evaluated_depsgraph_get()
    kinds = [inst.object.original.name for inst in dg.object_instances
             if inst.is_instance and inst.parent and inst.parent.original == c]
    assert len(kinds) == 6 and set(kinds) == {a.name, s.name}, kinds
    assert all(c.name == api.SOURCES or c.name.endswith(" Clones") for c in a.users_collection)


@case
def plain_effector_sphere_falloff():
    c = api.create_cloner("linear", params={"Count": 5, "Offset": [2, 0, 0]}, location=(0, 0, 0))
    e = api.add_effector("plain", cloners=[c.name], params={"Position": [0, 0, 3], "Local Space": False},
                         location=(0, 0, 0), size=1.0)
    zs = {round(x.translation.x): round(x.translation.z, 3) for x in instances(c)}
    assert zs[0] == 3.0 and zs[2] == 0.0, zs  # only the clone at the center is inside the sphere
    api.set_params(e, {"Falloff": "Infinite"})
    assert all(abs(x.translation.z - 3) < 1e-3 for x in instances(c))
    api.set_params(e, {"Strength": 0.5})
    assert all(abs(x.translation.z - 1.5) < 1e-3 for x in instances(c))


@case
def effector_shared_between_cloners():
    c1 = api.create_cloner("linear", params={"Count": 3}, location=(0, 0, 0))
    c2 = api.create_cloner("linear", params={"Count": 3}, location=(0, 5, 0))
    e = api.add_effector("plain", cloners=[c1.name, c2.name], falloff="Infinite",
                         params={"Uniform Scale": 1.0})
    for c in (c1, c2):
        assert all(abs(x.to_scale().x - 2.0) < 1e-3 for x in instances(c))
    api.set_params(e, {"Uniform Scale": -1.0})
    for c in (c1, c2):
        assert all(x.to_scale().x < 1e-4 for x in instances(c))


@case
def random_effector_deterministic():
    c = api.create_cloner("grid", location=(0, 0, 0))
    before = [x.translation.copy() for x in instances(c)]
    api.add_effector("random", cloners=[c.name], params={"Position": [1, 1, 1], "Seed": 3})
    after = [x.translation.copy() for x in instances(c)]
    moved = sum(1 for a, b in zip(before, after, strict=True) if (a - b).length > 1e-3)
    assert moved == 27, moved
    again = [x.translation.copy() for x in instances(c)]
    assert all(near(a, b) for a, b in zip(after, again, strict=True))


@case
def step_effector_ramp():
    c = api.create_cloner("linear", params={"Count": 5}, location=(0, 0, 0))
    api.add_effector("step", cloners=[c.name], params={"Position": [0, 0, 4], "Local Space": False})
    zs = sorted(round(x.translation.z, 3) for x in instances(c))
    assert zs == [0, 1, 2, 3, 4], zs


@case
def time_and_wave_effectors_animate():
    c = api.create_cloner("linear", params={"Count": 4}, location=(0, 0, 0))
    api.add_effector("time", cloners=[c.name], params={"Rotation": [0, 0, 90]})
    sc = bpy.context.scene
    sc.frame_set(1)
    r1 = instances(c)[0].to_euler().z
    sc.frame_set(sc.render.fps + 1)
    r2 = instances(c)[0].to_euler().z
    assert abs(math.degrees(r2 - r1) - 90) < 1.0, math.degrees(r2 - r1)


@case
def target_effector_faces_effector():
    c = api.create_cloner("linear", params={"Count": 3}, location=(0, 0, 0))
    api.add_effector("target", cloners=[c.name], location=(2.5, 0, 10))
    m = instances(c)
    for x in m:
        z_axis = x.to_3x3() @ Vector((0, 0, 1))
        to_t = (Vector((2.5, 0, 10)) - x.translation).normalized()
        assert z_axis.dot(to_t) > 0.999, z_axis.dot(to_t)


@case
def inheritance_effector_morphs_to_source():
    a = api.create_cloner("linear", name="A", params={"Count": 4, "Offset": [2, 0, 0]}, location=(0, 0, 0))
    b = api.create_cloner("linear", name="B", params={"Count": 4, "Offset": [0, 0, 3]}, location=(0, 0, 0))
    api.add_effector("plain", cloners=[b.name], falloff="Infinite", params={"Color": "#00ff00", "Color Mix": 1})
    e = api.add_effector("inheritance", cloners=[a.name], params={"Source": b.name})
    by_height = sorted(instances(a), key=lambda m: m.translation.z)
    assert all(near(x.translation, (0, 0, 3 * i)) for i, x in enumerate(by_height))
    api.set_params(e, {"Strength": 0.5})
    pts = sorted((x.translation for x in instances(a)), key=lambda v: v.z)
    assert all(near(p, (i, 0, 1.5 * i)) for i, p in enumerate(pts)), pts


def _tone(freq, seconds=3, rate=44100):
    import struct
    import tempfile
    import wave
    path = os.path.join(tempfile.gettempdir(), f"moblend_tone_{freq}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(20000 * math.sin(2 * math.pi * freq * i / rate)))
                               for i in range(rate * seconds)))
    return path


@case
def sound_effector_lifts_the_clone_hearing_the_tone():
    c = api.create_cloner("linear", params={"Count": 10}, location=(0, 0, 0))
    e = api.add_effector("sound", cloners=[c.name], params={"Sound": _tone(440), "Position": [0, 0, 2],
                                                             "Local Space": False})
    bpy.context.scene.frame_set(30)
    zs = [round(x.translation.z, 2) for x in sorted(instances(c), key=lambda m: m.translation.x)]
    assert zs[4] > 1.9 and max(zs[:4] + zs[5:]) < 0.1, zs  # log bands: clone 4 covers 392-693 Hz
    api.set_params(e, {"Mode": "All"})
    assert all(x.translation.z > 1.9 for x in instances(c))


@case
def delay_effector_lags():
    sc = bpy.context.scene
    sc.frame_set(1)
    c = api.create_cloner("linear", params={"Count": 2}, location=(0, 0, 0))
    plain = api.add_effector("plain", cloners=[c.name], falloff="Infinite", params={"Local Space": False})
    api.add_effector("delay", cloners=[c.name], params={"Mode": "Blend", "Blend": 0.5})
    for f in range(1, 4):
        sc.frame_set(f)
    api.set_params(plain, {"Position": [0, 0, 8]})
    sc.frame_set(4)
    z = instances(c)[0].translation.z
    assert 0.1 < z < 7.9, z  # chasing the target, not there yet
    for f in range(5, 30):
        sc.frame_set(f)
    z = instances(c)[0].translation.z
    assert abs(z - 8) < 0.05, z


@case
def color_effector_writes_attribute():
    c = api.create_cloner("linear", params={"Count": 2}, location=(0, 0, 0))
    api.add_effector("plain", cloners=[c.name], falloff="Infinite",
                     params={"Color": "#ff0000", "Color Mix": 1.0})
    ev = c.evaluated_get(bpy.context.evaluated_depsgraph_get())
    geo = ev.evaluated_geometry()
    inst = geo.instances_pointcloud()
    col = inst.attributes["mb_color"].data[0].color
    assert col[0] > 0.99 and col[1] < 0.01, tuple(col)


@case
def motext_splits_characters():
    t = api.create_motext("AB C", location=(0, 0, 0))
    n = len(instances(t))
    assert n == 3, n  # space has no geometry
    api.set_params(t, {"Split": "Words"})
    assert len(instances(t)) == 2
    e = api.add_effector("plain", cloners=[t.name], falloff="Infinite", params={"Rotation": [0, 0, 45]})
    assert e


@case
def fracture_islands_and_polygons():
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
    a = bpy.context.object
    bpy.ops.mesh.primitive_cube_add(size=2, location=(4, 0, 0))
    b = bpy.context.object
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.join()
    api.add_fracture(a.name)
    m = instances(a)
    assert len(m) == 2
    xs = sorted(round(x.translation.x, 3) for x in m)
    assert xs == [0, 4], xs  # pivots at piece centers
    api.set_params(a, {"Mode": "Polygons"})
    assert len(instances(a)) == 12


def _volume(o):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(o.data)
    v = bm.calc_volume()
    bm.free()
    return v


@case
def voronoi_fracture_conserves_volume_and_refractures():
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
    cube = bpy.context.object
    api.voronoi_fracture(cube, pieces=20, seed=1)
    assert len(instances(cube)) == 20, len(instances(cube))  # one effectable piece per cell
    assert abs(_volume(cube) - 8.0) < 0.01, _volume(cube)  # cells tile the cube exactly
    assert "MB Fracture Inside" in [m.name for m in cube.data.materials if m]
    api.voronoi_fracture(cube, pieces=7, seed=1, gap=0.2)  # re-fracture from the original, not the pieces
    assert len(instances(cube)) == 7
    assert 3.0 < _volume(cube) < 7.9, _volume(cube)
    assert cube["Voronoi Pieces"] == 7
    before = [x.translation.z for x in instances(cube)]
    e = api.add_effector("plain", cloners=[cube.name], falloff="Infinite", params={"Position": [0, 0, 1],
                                                                                   "Local Space": False})
    after = [x.translation.z for x in instances(cube)]
    assert all(abs(a - b - 1.0) < 1e-4 for a, b in zip(after, before, strict=True)) and e


@case
def sweep_grows():
    bpy.ops.curve.primitive_bezier_curve_add()
    path = bpy.context.object
    s = api.create_sweep(path.name, params={"Radius": 0.2})
    full = api.evaluated_stats(s)["vertices"]
    assert full > 100, full
    api.set_params(s, {"End": 0.5})
    assert api.evaluated_stats(s)["vertices"] > 0


@case
def tracer_adds_tube():
    c = api.create_cloner("linear", params={"Count": 4}, location=(0, 0, 0))
    api.add_tracer(c.name)
    ev = c.evaluated_get(bpy.context.evaluated_depsgraph_get())
    geo = ev.evaluated_geometry()
    assert len(geo.mesh.vertices) > 0
    assert len(instances(c)) == 4


@case
def deformers():
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, depth=4, location=(0, 0, 0))
    cyl = bpy.context.object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=10)
    bpy.ops.object.mode_set(mode="OBJECT")
    before = api.evaluated_stats(cyl)
    d = api.add_deformer("bend", targets=[cyl.name], params={"Angle": 90})
    bpy.context.view_layer.update()
    assert abs(cyl.modifiers[-1].angle - math.radians(90)) < 1e-4
    api.set_params(d, {"Angle": 45})
    bpy.context.view_layer.update()
    assert abs(cyl.modifiers[-1].angle - math.radians(45)) < 1e-4
    w = api.add_deformer("wave", targets=[cyl.name], params={"Amplitude": 0.5})
    ev = cyl.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert len(ev.data.vertices) == before["vertices"]
    api.add_deformer("spherify", targets=[cyl.name])
    assert api.get_params(w)["params"]["Amplitude"]["value"] == 0.5


@case
def keyframes_and_angles():
    c = api.create_cloner("radial", location=(0, 0, 0))
    api.set_params(c, {"End Angle": 180}, frame=1)
    api.set_params(c, {"End Angle": 360}, frame=20)
    assert abs(api.get_params(c)["params"]["End Angle"]["value"] - 360) < 1e-3
    bpy.context.scene.frame_set(1)
    assert abs(api.get_params(c)["params"]["End Angle"]["value"] - 180) < 1e-3
    e = api.add_effector("plain", cloners=[c.name])
    api.set_params(e, {"Strength": 0}, frame=1)
    api.set_params(e, {"Strength": 1, "location": [0, 0, 2]}, frame=10)
    assert e["mb_group"].animation_data and e["mb_group"].animation_data.action


@case
def delete_restores_sources():
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    c = api.create_cloner("linear", objects=[cube.name])
    e = api.add_effector("plain", cloners=[c.name])
    api.delete(e.name)
    assert not any(m.name.startswith("MBE") for m in c.modifiers)
    api.delete(c.name)
    assert cube.name in bpy.context.scene.objects


print("RESULT", "PASS" if not FAILS else f"FAIL {FAILS}")
