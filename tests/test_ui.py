"""Panel/menu draw code against a recording layout (no window needed).

Run: blender -b --factory-startup -P tests/test_ui.py
Checks every prop the panels draw resolves, and every operator id exists.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import bpy  # noqa: E402
import moblend  # noqa: E402
from moblend import api, ui  # noqa: E402


ICONS = {i.identifier for i in bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items}


def check_icon(k):
    icon = k.get("icon", "NONE")
    assert icon in ICONS, f"unknown icon {icon}"


class Rec:
    def __init__(self, log):
        self.log = log
        self.use_property_split = self.use_property_decorate = False

    def _child(self, *a, **k):
        return Rec(self.log)

    row = column = box = split = _child

    def prop(self, holder, attr, text=None, **k):
        if attr.startswith('["'):
            assert attr[2:-2] in holder, f"missing idprop {attr} on {holder}"
        else:
            assert hasattr(holder, attr), f"{holder} has no {attr}"
        self.log.append(("prop", text or attr))

    def label(self, text="", **k):
        check_icon(k)
        self.log.append(("label", text))

    def operator(self, idname, **k):
        check_icon(k)
        mod, op = idname.split(".")
        assert hasattr(getattr(bpy.ops, mod), op), f"no operator {idname}"
        self.log.append(("op", idname))
        return type("Props", (), {})()

    def menu(self, name, **k):
        check_icon(k)
        assert hasattr(bpy.types, name), f"no menu {name}"

    def separator(self, **k):
        pass


def _curve(z):
    bpy.ops.curve.primitive_bezier_circle_add(location=(0, 9, z))
    return bpy.context.object


def _cube():
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 6))
    return bpy.context.object


class Ctx:
    def __init__(self, o):
        self.active_object = o
        self.selected_objects = [o]
        self.scene = bpy.context.scene


def draw(panel, o):
    log = []
    self = type("P", (), {})()
    self.layout = Rec(log)
    for name in ("cloner", "effector", "deformer", "field", "falloff", "generic", "effector_list", "extra_modifiers"):
        setattr(self, name, getattr(ui.MB_PT_main, name).__get__(self))
    panel.draw(self, Ctx(o))
    return log


bpy.ops.wm.read_factory_settings(use_empty=True)
moblend.register()
fails = []
c = api.create_cloner("grid", name="G", location=(0, 0, 0))
api.add_tracer(c.name)
objs = {
    "cloner": c,
    "effector": api.add_effector("random", name="R", cloners=[c.name]),
    "deformer": api.add_deformer("wave", name="W", targets=[c.name]),
    "simple": api.add_deformer("bend", name="B"),
    "motext": api.create_motext("HI", name="T"),
    "voronoi": api.voronoi_fracture(api.get_object(c.name) and _cube(), pieces=4),
    "volume": api.create_volume_builder(add=[_cube()]),
    "loft": api.create_loft([_curve(0), _curve(2)]),
    "field": api.add_field("Box", effectors=["R"]),
}
api.add_effector("plain", name="P2", cloners=["T"])
expect = {"cloner": ["Count X", "Spacing", "Radius", "R"],
          "effector": ["Strength", "Falloff", "Seed", "Mode", "Select Every", "Fields (top to bottom)"],
          "deformer": ["Amplitude", "Falloff"], "simple": ["Angle"], "motext": ["Text", "Split", "P2"],
          "voronoi": ["Pieces", "Seed", "Gap", "Mode"],
          "volume": ["Voxel Size", "Smooth", "Add", "Subtract"],
          "loft": ["Points", "Rows", "Caps", "Profiles (in order)"],
          "field": ["Blend", "Opacity", "Falloff", "R"]}
for k, o in objs.items():
    try:
        log = draw(ui.MB_PT_main, o)
        shown = {t for _, t in log}
        missing = [e for e in expect[k] if e not in shown]
        assert not missing, f"{k}: not drawn {missing}; drew {sorted(shown)}"
        print("PASS panel", k, len(log), "items")
    except Exception:
        fails.append(k)
        traceback.print_exc()
for menu in (ui.MB_MT_add, ui.MB_MT_cloners, ui.MB_MT_effectors, ui.MB_MT_deformers, ui.MB_MT_generators):
    try:
        self = type("M", (), {})()
        self.layout = Rec([])
        menu.draw(self, Ctx(None))
        print("PASS menu", menu.__name__)
    except Exception:
        fails.append(menu.__name__)
        traceback.print_exc()
try:
    self = type("P", (), {})()
    self.layout = Rec([])
    ui.MB_PT_bridge.draw(self, Ctx(None))
    print("PASS bridge panel")
except Exception:
    fails.append("bridge")
    traceback.print_exc()

# Operators run for real.
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    bpy.ops.mesh.primitive_cube_add()
    assert bpy.ops.moblend.add_cloner(mode="radial") == {"FINISHED"}
    cl = bpy.context.active_object
    assert api.mb_kind(cl) == "cloner"
    assert bpy.ops.moblend.add_effector(type="plain") == {"FINISHED"}  # cloner selected -> linked
    assert len(api.effectors_of(cl)) == 1
    bpy.context.view_layer.objects.active = cl
    cl.select_set(True)
    assert bpy.ops.moblend.cloner_mode(mode="grid") == {"FINISHED"}
    assert bpy.ops.moblend.add_generator(kind="motext") == {"FINISHED"}
    bpy.ops.mesh.primitive_cube_add()
    assert bpy.ops.moblend.voronoi(pieces=5) == {"FINISHED"}
    assert bpy.context.active_object["Voronoi Pieces"] == 5
    assert bpy.ops.moblend.volume_builder() == {"FINISHED"}
    vb = bpy.context.active_object
    bpy.ops.mesh.primitive_cube_add(location=(0, 3, 0))
    vb.select_set(True)
    bpy.context.view_layer.objects.active = vb
    assert bpy.ops.moblend.volume_members(mode="subtract") == {"FINISHED"}
    assert len(vb["mb_volume_subtract"].objects) == 1
    print("PASS operators")
except Exception:
    fails.append("operators")
    traceback.print_exc()
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
