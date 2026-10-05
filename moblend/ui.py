"""Operators, Add menu (Shift+A > MoBlend) and the sidebar panel (N > MoBlend)."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from . import api, bridge
from .catalog import (CLONER_MOD, CLONER_MODES, DEFORMER_TYPES, EFFECTOR_TYPES, FIELD_KINDS, GROUP_PREFIX,
                      KEY_CLONES,
                      KEY_PROFILES, KEY_TYPE, KEY_VERSION, KEY_VOLUME_SETS, Kind)
from .nodes import build_all
from .nodes.core import FALLOFF_NAMES, SELECTION_NAMES

CLONER_ICONS = {"linear": "IPO_LINEAR", "radial": "MESH_CIRCLE", "grid": "MESH_GRID", "honeycomb": "LIGHTPROBE_PLANE",
                "object": "MESH_ICOSPHERE", "spline": "CURVE_BEZCURVE"}
EFFECTOR_ICONS = {"plain": "EMPTY_AXIS", "random": "RNDCURVE", "step": "IPO_CONSTANT", "noise": "FORCE_TURBULENCE",
                  "wave": "FORCE_HARMONIC", "time": "TIME", "target": "TRACKER", "delay": "FORCE_DRAG",
                  "inheritance": "MOD_DATA_TRANSFER", "sound": "SPEAKER", "formula": "DRIVER_TRANSFORM",
                  "shader": "TEXTURE", "spline": "CURVE_BEZCURVE", "volume": "MESH_CUBE",
                  "push_apart": "FULLSCREEN_EXIT"}
DEFORMER_ICONS = {"bend": "MOD_SIMPLEDEFORM", "twist": "MOD_SCREW", "taper": "MOD_SIMPLEDEFORM",
                  "stretch": "MOD_SIMPLEDEFORM", "wave": "MOD_WAVE", "spherify": "MESH_UVSPHERE",
                  "shear": "MOD_LATTICE", "bulge": "MOD_CAST", "displace": "MOD_DISPLACE", "moextrude": "MOD_SOLIDIFY"}
# (kind, menu label, icon); None draws a separator. Kinds with their own operator are in GENERATOR_OPERATORS.
GENERATOR_MENU = (("motext", "MoText", "FONT_DATA"), ("sweep", "Sweep (active curve)", "CURVE_PATH"),
                  ("fracture", "Fracture (active)", "MOD_EDGESPLIT"),
                  ("voronoi", "Voronoi Fracture (active)", "MOD_EXPLODE"),
                  ("tracer", "Tracer (active cloner)", "CURVE_DATA"),
                  ("volume", "Volume Builder (selected)", "MOD_REMESH"),
                  ("loft", "Loft (selected curves)", "SURFACE_NSURFACE"),
                  ("fracture_objects", "Fracture (selected objects)", "OUTLINER_COLLECTION"),
                  ("moinstance", "MoInstance (active = source)", "TRACKING"),
                  ("mospline", "MoSpline", "CURVE_NCURVE"),
                  ("turtle", "MoSpline Turtle (L-system)", "OUTLINER_OB_FORCE_FIELD"),
                  ("spline_mask", "Spline Mask (selected curves)", "SELECT_INTERSECT"),
                  ("spline_wrap", "Spline Wrap (selected → active curve)", "MOD_CURVE"),
                  None,
                  ("lathe", "Lathe", "MOD_SCREW"), ("extrude", "Extrude", "MOD_SOLIDIFY"),
                  ("symmetry", "Symmetry", "MOD_MIRROR"), ("boole", "Boole (cut active)", "MOD_BOOLEAN"),
                  ("subdivision", "Subdivision", "MOD_SUBSURF"))
GENERATOR_OPERATORS = {"voronoi": "moblend.voronoi", "volume": "moblend.volume_builder", "loft": "moblend.loft",
                       **dict.fromkeys(("fracture_objects", "moinstance", "mospline", "turtle", "spline_mask",
                                        "spline_wrap"), "moblend.mograph_object")}
FIELD_ICONS = {"Infinite": "WORLD", "Solid": "WORLD", "Group": "OUTLINER_COLLECTION", "Sphere": "SPHERE",
               "Box": "CUBE", "Cylinder": "MESH_CYLINDER", "Cone": "MESH_CONE", "Capsule": "MESH_CAPSULE",
               "Torus": "MESH_TORUS", "Linear": "IPO_LINEAR", "Radial": "DRIVER_ROTATIONAL_DIFFERENCE",
               "Noise": "FORCE_TURBULENCE", "Random": "RNDCURVE", "Time": "TIME", "Step": "IPO_CONSTANT",
               "Object": "OBJECT_DATA", "Shader": "TEXTURE", "Sound": "SPEAKER", "Formula": "DRIVER_TRANSFORM",
               "Attribute": "GROUP_VERTEX"}
LAYERED = (Kind.EFFECTOR, Kind.DEFORMER)
EFFECTABLE = (Kind.CLONER, Kind.MOTEXT, Kind.FRACTURE)
OWNERS = (Kind.EFFECTOR, Kind.DEFORMER, Kind.SIMPLE_DEFORMER)


def _enum(names):
    return [(n, n.title(), "") for n in names]


def _effectable(o):
    return o is not None and api.mb_kind(o) in EFFECTABLE


class _MBOperator(bpy.types.Operator):
    """Base: run(ctx) returns truthy on success; API errors go to the status bar."""
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        try:
            return {"FINISHED"} if self.run(ctx) is not False else {"CANCELLED"}
        except Exception as e:  # surface API errors to the user instead of a console traceback
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

    def fail(self, msg):
        self.report({"ERROR"}, msg)
        return False


# ------------------------------------------------------------------ operators

class MB_OT_add_cloner(_MBOperator):
    """Clone the selected objects (a cube when nothing is selected). Object/Spline modes use the active
    mesh/curve as the surface/path"""
    bl_idname = "moblend.add_cloner"
    bl_label = "Add Cloner"
    mode: EnumProperty(items=_enum(CLONER_MODES))

    _SURFACE = {"object": ("MESH", "Object"), "spline": ("CURVE", "Curve")}  # mode -> (active type, param)

    def run(self, ctx):
        sel = [o for o in ctx.selected_objects if o.type in ("MESH", "CURVE", "FONT", "EMPTY")
               and not api.mb_kind(o)]
        act = ctx.active_object if ctx.active_object in sel else None
        params, location = {}, (None if sel else ctx.scene.cursor.location.copy())
        need = self._SURFACE.get(self.mode)
        if need and act and act.type == need[0]:
            params[need[1]] = act.name
            sel.remove(act)
            location = (0, 0, 0)  # surface/path positions are relative to the cloner
        return api.create_cloner(self.mode, sel, None, params, location)


class MB_OT_add_effector(_MBOperator):
    """Add an effector; it is linked to every selected cloner / MoText / fractured object"""
    bl_idname = "moblend.add_effector"
    bl_label = "Add Effector"
    type: EnumProperty(items=_enum(EFFECTOR_TYPES))

    def run(self, ctx):
        targets = [o for o in ctx.selected_objects if _effectable(o)]
        return api.add_effector(self.type, cloners=targets, location=ctx.scene.cursor.location.copy())


class MB_OT_add_deformer(_MBOperator):
    """Add a deformer to every selected object"""
    bl_idname = "moblend.add_deformer"
    bl_label = "Add Deformer"
    type: EnumProperty(items=_enum(DEFORMER_TYPES))

    def run(self, ctx):
        targets = [o for o in ctx.selected_objects if o.type == "MESH" and api.mb_kind(o) not in OWNERS]
        return api.add_deformer(self.type, targets)


class MB_OT_add_generator(_MBOperator):
    """Add a MoBlend generator"""
    bl_idname = "moblend.add_generator"
    bl_label = "Add Generator"
    kind: EnumProperty(items=[(g[0], g[1], "") for g in GENERATOR_MENU if g and g[0] not in GENERATOR_OPERATORS])

    def run(self, ctx):
        act = ctx.active_object
        others = [o for o in ctx.selected_objects if o != act]
        if self.kind == "motext":
            return api.create_motext(location=ctx.scene.cursor.location.copy())
        if self.kind == "sweep":
            if not act or act.type != "CURVE":
                return self.fail("Select the path curve (active), optionally a profile curve too")
            return api.create_sweep(act, next((o for o in others if o.type == "CURVE"), None))
        if not act:
            return self.fail("Select an object first")
        if self.kind == "boole":
            if not others:
                return self.fail("Select the cutter, then the object to cut (active)")
            for cutter in others:
                api.add_boole(act, cutter)
            return True
        return api.GENERATORS[self.kind](act)


class MB_OT_voronoi(_MBOperator):
    """Fracture the active mesh into Voronoi pieces that effectors can move. Settings then live in the
    sidebar and re-fracture automatically"""
    bl_idname = "moblend.voronoi"
    bl_label = "Voronoi Fracture"
    action: EnumProperty(items=[("FRACTURE", "Fracture", ""), ("REFRESH", "Re-fracture", ""),
                                ("RESTORE", "Restore Original", ""), ("DYNAMIC", "Make Dynamic", "")])
    breaking_threshold: bpy.props.FloatProperty(name="Breaking Threshold", default=10.0, min=0.0)

    def run(self, ctx):
        o = ctx.active_object
        if not o or o.type != "MESH":
            return self.fail("Select a mesh first")
        if self.action == "RESTORE":
            return api.restore_fracture(o)
        if self.action == "DYNAMIC":
            return api.make_dynamic(o, self.breaking_threshold)
        if self.action == "REFRESH" and api.is_voronoi(o):
            return api._voronoi.refresh(o)
        return api.voronoi_fracture(o)


def _selected_meshes(ctx, exclude=None):
    return [o for o in ctx.selected_objects if o.type == "MESH" and o != exclude and not api.mb_kind(o)]


class MB_OT_volume_builder(_MBOperator):
    """Merge the selected meshes into one smooth volume mesh (C4D Volume Builder)"""
    bl_idname = "moblend.volume_builder"
    bl_label = "Volume Builder"

    def run(self, ctx):
        return api.create_volume_builder(add=_selected_meshes(ctx))


class MB_OT_loft(_MBOperator):
    """Skin a surface through the selected curves, ordered along the axis they are spread out on"""
    bl_idname = "moblend.loft"
    bl_label = "Loft"

    def run(self, ctx):
        curves = [o for o in ctx.selected_objects if o.type == "CURVE"]
        if len(curves) < 2:
            return self.fail("Select at least two profile curves")
        return api.create_loft(api.sort_along_spread(curves))


class MB_OT_mograph_object(_MBOperator):
    """Add a MoGraph object from the selection"""
    bl_idname = "moblend.mograph_object"
    bl_label = "Add MoGraph Object"
    kind: EnumProperty(items=[(k, k.replace("_", " ").title(), "") for k in (
        "fracture_objects", "moinstance", "mospline", "turtle", "spline_mask", "spline_wrap")])

    def run(self, ctx):
        act, sel = ctx.active_object, list(ctx.selected_objects)
        cursor = ctx.scene.cursor.location.copy()
        if self.kind == "fracture_objects":
            return api.create_fracture_objects(_selected_meshes(ctx)) if sel else self.fail("Select objects")
        if self.kind == "moinstance":
            return api.create_moinstance(act, location=cursor) if act else self.fail("Select the source object")
        if self.kind == "mospline":
            return api.create_mospline(location=cursor)
        if self.kind == "turtle":
            return api.create_mospline_turtle(location=cursor)
        curves = [o for o in sel if o.type == "CURVE"]
        if self.kind == "spline_mask":
            return api.create_spline_mask(curves) if len(curves) >= 2 else self.fail("Select 2+ closed curves")
        if not act or act.type != "CURVE":
            return self.fail("Select the objects, then the curve last (active)")
        return api.add_spline_wrap([o for o in sel if o != act], act)


class MB_OT_volume_members(_MBOperator):
    """Move the selected meshes into the active Volume Builder's Add or Subtract set"""
    bl_idname = "moblend.volume_members"
    bl_label = "Add to Volume"
    mode: EnumProperty(items=_enum(KEY_VOLUME_SETS))

    def run(self, ctx):
        o = ctx.active_object
        objs = _selected_meshes(ctx, exclude=o)
        if not objs:
            return self.fail("Select meshes, then the Volume Builder last (active)")
        return api.add_volume_objects(o, objs, self.mode)


class MB_OT_add_field(_MBOperator):
    """Add a field; it joins the field list of every selected effector / GN deformer"""
    bl_idname = "moblend.add_field"
    bl_label = "Add Field"
    shape: EnumProperty(items=[(s, s, "") for s in FIELD_KINDS])

    def run(self, ctx):
        owners = [o for o in ctx.selected_objects if api.mb_kind(o) in LAYERED]
        return api.add_field(self.shape, owners, location=ctx.scene.cursor.location.copy())


class MB_OT_group_effector(_MBOperator):
    """Group the selected effectors under one Strength / falloff (C4D Group effector, ReEffector)"""
    bl_idname = "moblend.group_effector"
    bl_label = "Group Effector"

    def run(self, ctx):
        members = [o for o in ctx.selected_objects if api.mb_kind(o) == Kind.EFFECTOR]
        if not members:
            return self.fail("Select the effectors to group")
        return api.add_group_effector(members, location=ctx.scene.cursor.location.copy())


class MB_OT_link_field(_MBOperator):
    """Add selected fields to an effector's field list, or remove one"""
    bl_idname = "moblend.link_field"
    bl_label = "Link Field"
    owner: StringProperty()
    field: StringProperty()
    unlink: BoolProperty()

    def run(self, ctx):
        if self.unlink:
            return api.unlink_field(self.field, self.owner)
        for f in (o for o in ctx.selected_objects if api.mb_kind(o) == Kind.FIELD):
            api.link_field(f, self.owner)
        return True


class MB_OT_clones(_MBOperator):
    """MoGraph Selection tools for the active cloner"""
    bl_idname = "moblend.clones"
    bl_label = "MoGraph Selection"
    action: EnumProperty(items=[
        ("PICK", "Pick Clones", "One vertex per clone; select them in Edit Mode, then Store Selection"),
        ("STORE", "Store Selection", "Selected clone vertices become the MoGraph Selection"),
        ("HIDE", "Hide Selected", "A Plain effector that hides the selected clones"),
        ("SWAP", "Swap Cloner/Matrix", "Toggle between rendering clones and positions only")])

    def run(self, ctx):
        c = ctx.active_object
        if api.mb_kind(c) != Kind.CLONER:
            return self.fail("Select a cloner")
        if self.action == "PICK":
            api.sync_clone_points(c)
            return bpy.ops.object.mode_set(mode="EDIT")
        if self.action == "STORE":
            picked = api.selection_from_edit_mode(c)
            bpy.ops.object.mode_set(mode="OBJECT")
            self.report({"INFO"}, f"{len(picked)} clones selected")
            return True
        if self.action == "HIDE":
            return api.hide_selected_clones(c)
        return api.make_matrix(c, not api.is_matrix(c))


class MB_OT_add_matrix(_MBOperator):
    """Add a Matrix: cloner positions only (boxes in the viewport, nothing rendered)"""
    bl_idname = "moblend.add_matrix"
    bl_label = "Add Matrix"
    mode: EnumProperty(items=_enum(CLONER_MODES))

    def run(self, ctx):
        return api.create_matrix(self.mode, location=ctx.scene.cursor.location.copy())


class MB_OT_cloner_mode(_MBOperator):
    """Switch the cloner's mode"""
    bl_idname = "moblend.cloner_mode"
    bl_label = "Cloner Mode"
    mode: EnumProperty(items=_enum(CLONER_MODES))

    def run(self, ctx):
        return api.set_cloner_mode(ctx.active_object, self.mode)


class MB_OT_link(_MBOperator):
    """Link an effector to a target (or to every selected cloner), or unlink it"""
    bl_idname = "moblend.link"
    bl_label = "Link Effector"
    effector: StringProperty()
    target: StringProperty()
    unlink: BoolProperty()

    def run(self, ctx):
        fn = api.unlink_effector if self.unlink else api.link_effector
        targets = [self.target] if self.target else [o for o in ctx.selected_objects if _effectable(o)]
        for t in targets:
            fn(self.effector, t)
        return True


class MB_OT_move_effector(_MBOperator):
    """Reorder an effector in the list (they apply top to bottom)"""
    bl_idname = "moblend.move_effector"
    bl_label = "Move Effector"
    modifier: StringProperty()
    direction: IntProperty(default=-1)

    def run(self, ctx):
        return api.move_effector(ctx.active_object, self.modifier, self.direction)


class MB_OT_color_material(_MBOperator):
    """Give the selection a material that shows effector colors"""
    bl_idname = "moblend.color_material"
    bl_label = "MoGraph Color Material"

    def run(self, ctx):
        return api.set_color_material(ctx.selected_objects)


class MB_OT_materials(_MBOperator):
    """MoGraph shaders for the selection: MoGraph Color, Multi (a color per clone), Beat (pulse on the beat),
    and MoGraph Cache (bake simulations)"""
    bl_idname = "moblend.materials"
    bl_label = "MoGraph Shaders"
    action: EnumProperty(items=[("COLOR", "MoGraph Color", ""), ("MULTI", "Multi Shader", ""),
                                ("BEAT", "Beat Shader", ""), ("BAKE", "Bake Cache", "")])
    bpm: bpy.props.FloatProperty(name="BPM", default=120.0, min=1.0)

    def run(self, ctx):
        sel = list(ctx.selected_objects)
        if not sel:
            return self.fail("Select objects")
        if self.action == "COLOR":
            return api.set_color_material(sel)
        if self.action == "MULTI":
            return api.multi_material(sel, ["#ff5a1f", "#3fa9f5", "#f5d63f", "#7ad151"])
        if self.action == "BEAT":
            return api.beat_material(sel, bpm=self.bpm)
        for o in sel:
            api.bake_cache(o)
        return True


class MB_OT_bridge(_MBOperator):
    """Start or stop the MCP bridge"""
    bl_idname = "moblend.bridge"
    bl_label = "MCP Bridge"
    bl_options = set()
    action: EnumProperty(items=[("START", "Start", ""), ("STOP", "Stop", "")])

    def run(self, ctx):
        if self.action == "STOP":
            bridge.stop()
            return True
        return bridge.start() or self.fail("Bridge not started (another Blender owns it?); see console")


class MB_OT_rebuild(_MBOperator):
    """Rebuild MoBlend's node groups (after an add-on update)"""
    bl_idname = "moblend.rebuild"
    bl_label = "Rebuild Node Groups"

    def run(self, ctx):
        for ng in bpy.data.node_groups:
            if ng.name.startswith(GROUP_PREFIX) and KEY_VERSION in ng:
                ng[KEY_VERSION] = -1
        return build_all()


# ------------------------------------------------------------------ menus

def _operator_menu(idname, label, operator, prop, names, icons, extra=()):
    """Menu with one `operator` entry per name, setting `prop` to it, then `extra` (operator, text, icon)."""
    def draw(self, ctx):
        for n in names:
            setattr(self.layout.operator(operator, text=n.replace("_", " ").title(), icon=icons[n]), prop, n)
        if extra:
            self.layout.separator()
        for op, text, icon in extra:
            self.layout.operator(op, text=text, icon=icon)
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": label, "draw": draw})


MB_MT_cloners = _operator_menu("MB_MT_cloners", "Cloner", "moblend.add_cloner", "mode", CLONER_MODES, CLONER_ICONS,
                               [("moblend.add_matrix", "Matrix (grid)", "LIGHTPROBE_VOLUME")])
MB_MT_effectors = _operator_menu("MB_MT_effectors", "Effectors", "moblend.add_effector", "type", EFFECTOR_TYPES,
                                 EFFECTOR_ICONS, [("moblend.group_effector", "Group (selected effectors)",
                                                   "OUTLINER_COLLECTION")])
MB_MT_fields = _operator_menu("MB_MT_fields", "Fields", "moblend.add_field", "shape", FIELD_KINDS, FIELD_ICONS)
MB_MT_deformers = _operator_menu("MB_MT_deformers", "Deformers", "moblend.add_deformer", "type", DEFORMER_TYPES,
                                 DEFORMER_ICONS)


class MB_MT_generators(bpy.types.Menu):
    bl_idname = "MB_MT_generators"
    bl_label = "Generators"

    def draw(self, ctx):
        for entry in GENERATOR_MENU:
            if entry is None:
                self.layout.separator()
            elif entry[0] in GENERATOR_OPERATORS:
                op = self.layout.operator(GENERATOR_OPERATORS[entry[0]], text=entry[1], icon=entry[2])
                if GENERATOR_OPERATORS[entry[0]] == "moblend.mograph_object":
                    op.kind = entry[0]
            else:
                kind, label, icon = entry
                self.layout.operator("moblend.add_generator", text=label, icon=icon).kind = kind


SUBMENUS = (("MB_MT_cloners", "Cloner", "MOD_ARRAY"), ("MB_MT_effectors", "Effector", "FORCE_FORCE"),
            ("MB_MT_generators", "Generator", "MODIFIER"), ("MB_MT_deformers", "Deformer", "MOD_SIMPLEDEFORM"),
            ("MB_MT_fields", "Field", "SPHERE"))


class MB_MT_add(bpy.types.Menu):
    bl_idname = "MB_MT_add"
    bl_label = "MoBlend"

    def draw(self, ctx):
        for idname, _, icon in SUBMENUS:
            self.layout.menu(idname, icon=icon)


def add_menu(self, ctx):
    self.layout.menu("MB_MT_add", icon="MOD_ARRAY")


# ------------------------------------------------------------------ panel

def _draw_params(layout, params, only=None, skip=frozenset()):
    for p in params:
        if (only is None or p.name in only) and p.name not in skip:
            layout.prop(p.holder, p.attr, text=p.name)


def _op(layout, idname, icon, text="", **props):
    op = layout.operator(idname, text=text, icon=icon)
    for k, v in props.items():
        setattr(op, k, v)
    return op


def _header(layout, o, what, icon):
    box = layout.box()
    box.label(text=f"{o.name} · {o.get(KEY_TYPE, '').title()} {what}", icon=icon)
    return box


def _draw_users(layout, o, title, icon, unlink):
    """List objects an effector/deformer affects. O(N x M) per redraw (scan of all modifiers)."""
    col = layout.column(align=True)
    col.label(text=title, icon=icon)
    for t in api.users_of(o):
        row = col.row()
        row.label(text=t.name, icon="OBJECT_DATA")
        if unlink:
            _op(row, "moblend.link", "X", effector=o.name, target=t.name, unlink=True)


class MB_PT_main(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MoBlend"
    bl_label = "MoBlend"

    def draw(self, ctx):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = True
        for i in range(0, len(SUBMENUS), 2):
            row = layout.row(align=True)
            for idname, text, icon in SUBMENUS[i:i + 2]:
                row.menu(idname, text=text, icon=icon)
        o = ctx.active_object
        if o is None:
            return
        draw = {Kind.CLONER: self.cloner, Kind.EFFECTOR: self.effector, Kind.DEFORMER: self.deformer,
                Kind.SIMPLE_DEFORMER: self.deformer, Kind.FIELD: self.field}.get(api.mb_kind(o), self.generic)
        try:
            draw(layout, o)
        except Exception as e:  # a stale/renamed object must never break the whole panel
            layout.label(text=str(e), icon="ERROR")

    def cloner(self, layout, o):
        box = _header(layout, o, "Cloner", "MOD_ARRAY")
        row = box.row(align=True)
        for m in CLONER_MODES:
            row.operator("moblend.cloner_mode", text=m.title(), depress=o.get(KEY_TYPE) == m).mode = m
        _draw_params(box, api.list_params(o, CLONER_MOD))
        col = box.column(align=True)
        col.label(text="Clones")
        for s in o[KEY_CLONES].objects:
            col.label(text=s.name, icon="OBJECT_DATA")
        box = layout.box()
        box.label(text="MoGraph Selection" + (" · Matrix" if api.is_matrix(o) else ""), icon="RESTRICT_SELECT_OFF")
        row = box.row(align=True)
        for action, icon in (("PICK", "EDITMODE_HLT"), ("STORE", "CHECKMARK"), ("HIDE", "HIDE_ON"),
                             ("SWAP", "LIGHTPROBE_VOLUME")):
            _op(row, "moblend.clones", icon, action=action)
        self.effector_list(layout, o)
        self.extra_modifiers(layout, o, skip={CLONER_MOD})

    def effector_list(self, layout, o):
        box = layout.box()
        box.label(text="Effectors", icon="FORCE_FORCE")
        for item in api.effectors_of(o):
            m = o.modifiers[item["modifier"]]
            owner = bpy.data.objects.get(item["effector"] or "")
            row = box.row(align=True)
            row.prop(m, "show_viewport", text="", emboss=False)
            row.label(text=owner.name if owner else m.name,
                      icon=EFFECTOR_ICONS.get(owner.get(KEY_TYPE) if owner else "", "FORCE_FORCE"))
            _op(row, "moblend.move_effector", "TRIA_UP", modifier=m.name, direction=-1)
            _op(row, "moblend.move_effector", "TRIA_DOWN", modifier=m.name, direction=1)
            if owner:
                _op(row, "moblend.link", "X", effector=owner.name, target=o.name, unlink=True)

    def extra_modifiers(self, layout, o, skip=frozenset()):
        for m in o.modifiers:
            if m.type == "NODES" and m.name.startswith(GROUP_PREFIX) and m.name not in skip:
                box = layout.box()
                box.label(text=m.name[len(GROUP_PREFIX):], icon="MODIFIER")
                _draw_params(box, api.list_params(o, m.name))

    def effector(self, layout, o):
        params = api.list_params(o)
        _draw_params(_header(layout, o, "Effector", "FORCE_FORCE"), params, skip=FALLOFF_NAMES | SELECTION_NAMES)
        self.falloff(layout, o, params)
        box = layout.box()
        box.label(text="Selection", icon="RESTRICT_SELECT_OFF")
        _draw_params(box, params, only=SELECTION_NAMES)
        box = layout.box()
        _draw_users(box, o, "Affects", "LINKED", unlink=True)
        _op(box, "moblend.link", "ADD", text="Link to Selected", effector=o.name, target="", unlink=False)

    def falloff(self, layout, o, params):
        box = layout.box()
        box.label(text="Falloff (size = object scale)", icon="SPHERE")
        _draw_params(box, params, only=FALLOFF_NAMES)
        box.prop(o, "scale", text="Size")
        col = box.column(align=True)
        col.label(text="Fields (top to bottom)", icon="MOD_PHYSICS")
        for name in api.fields_of(o):
            row = col.row()
            row.label(text=name, icon=FIELD_ICONS.get(bpy.data.objects[name].get(KEY_TYPE, "").title(), "SPHERE"))
            _op(row, "moblend.link_field", "X", owner=o.name, field=name, unlink=True)
        _op(col, "moblend.link_field", "ADD", text="Add Selected Fields", owner=o.name, field="", unlink=False)

    def deformer(self, layout, o):
        params = api.list_params(o)
        box = _header(layout, o, "Deformer", "MOD_SIMPLEDEFORM")
        if api.mb_kind(o) == Kind.DEFORMER:
            _draw_params(box, params, skip=FALLOFF_NAMES)
            self.falloff(layout, o, params)
        else:
            _draw_params(box, params)
            box.prop(o, "scale", text="Size")
        _draw_users(layout.box(), o, "Deforms", "MODIFIER", unlink=False)

    def voronoi(self, layout, o):
        """Voronoi Fracture settings in Cinema 4D's tab order; changes re-fracture automatically."""
        settings = o.moblend_voronoi
        layout.label(text=f"{o.name} · Voronoi Fracture", icon="MOD_EXPLODE")
        for section, names in api.VORONOI_SECTIONS.items():
            box = layout.box()
            box.label(text=section)
            for name in names:
                box.prop(settings, name)
        row = layout.row(align=True)
        _op(row, "moblend.voronoi", "FILE_REFRESH", text="Re-fracture", action="REFRESH")
        _op(row, "moblend.voronoi", "LOOP_BACK", text="Restore", action="RESTORE")
        _op(layout, "moblend.voronoi", "RIGID_BODY", text="Make Dynamic (Connectors)", action="DYNAMIC")

    def field(self, layout, o):
        box = _header(layout, o, "Field", FIELD_ICONS.get(o.get(KEY_TYPE, "").title(), "SPHERE"))
        _draw_params(box, api.list_params(o))
        box.prop(o, "scale", text="Size")
        col = layout.box().column(align=True)
        col.label(text="In the field lists of", icon="LINKED")
        for owner in api.field_users(o):
            row = col.row()
            row.label(text=owner.name, icon="FORCE_FORCE")
            _op(row, "moblend.link_field", "X", owner=owner.name, field=o.name, unlink=True)

    def generic(self, layout, o):
        if api.is_voronoi(o):
            self.voronoi(layout, o)
        own = [p for p in api.list_params(o) if not p.group]  # settings stored on the object itself
        if own:
            box = _header(layout, o, "", "OUTLINER_OB_CURVE")
            _draw_params(box, own)
        self.extra_modifiers(layout, o)
        if api.mb_kind(o) == Kind.LOFT:
            col = layout.box().column(align=True)
            col.label(text="Profiles (in order)", icon="CURVE_DATA")
            for name in o.get(KEY_PROFILES, ()):
                col.label(text=name, icon="OBJECT_DATA")
        if api.mb_kind(o) == Kind.VOLUME:
            box = layout.box()
            for mode, key in KEY_VOLUME_SETS.items():
                col = box.column(align=True)
                col.label(text=mode.title(), icon="ADD" if mode == "add" else "REMOVE")
                for x in o[key].objects:
                    col.label(text=x.name, icon="OBJECT_DATA")
                _op(col, "moblend.volume_members", "IMPORT", text=f"{mode.title()} Selected", mode=mode)
        if _effectable(o):
            self.effector_list(layout, o)


class MB_PT_bridge(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MoBlend"
    bl_label = "MCP Bridge"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        running = bridge.running()
        layout.label(text="Running" if running else "Stopped", icon="CHECKMARK" if running else "CANCEL")
        if running:
            layout.label(text=bridge.socket_path())
        layout.operator("moblend.bridge", text="Stop" if running else "Start").action = "STOP" if running else "START"
        layout.operator("moblend.color_material", icon="MATERIAL")
        row = layout.row(align=True)
        for action, icon in (("MULTI", "NODE_MATERIAL"), ("BEAT", "SOUND"), ("BAKE", "PHYSICS")):
            _op(row, "moblend.materials", icon, action=action)
        layout.operator("moblend.rebuild", icon="FILE_REFRESH")


class MB_Prefs(bpy.types.AddonPreferences):
    bl_idname = __package__
    autostart: BoolProperty(name="Start MCP bridge with Blender", default=True)

    def draw(self, ctx):
        self.layout.prop(self, "autostart")
        self.layout.label(text=f"Socket: {bridge.socket_path()}")


CLASSES = (MB_OT_add_cloner, MB_OT_add_effector, MB_OT_add_deformer, MB_OT_add_generator, MB_OT_voronoi,
           MB_OT_volume_builder, MB_OT_volume_members, MB_OT_loft, MB_OT_mograph_object,
           MB_OT_cloner_mode,
           MB_OT_link, MB_OT_move_effector, MB_OT_color_material, MB_OT_bridge, MB_OT_rebuild,
           MB_OT_add_field, MB_OT_link_field, MB_OT_group_effector, MB_OT_clones, MB_OT_add_matrix,
           MB_OT_materials,
           MB_MT_cloners, MB_MT_effectors, MB_MT_deformers, MB_MT_fields, MB_MT_generators, MB_MT_add,
           MB_PT_main, MB_PT_bridge, MB_Prefs)
