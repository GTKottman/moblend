"""Uniform access to every editable value of a MoBlend object.

A parameter is either a modifier input (cloners, generators), a socket of the
PARAMS_NODE in an effector/deformer wrapper group, or a custom property
(simple deformers). P = parameters of one object, K = keys being set.
"""

import math
import os

import bpy

from ..catalog import KEY_GROUP, KEY_TYPE, PARAMS_NODE, Kind
from .objects import get_object, mb_kind, mb_modifiers, norm, vec3

_SKIP = {"Geometry", "Instances", "Transform", "Layers", "Previous", "First", "Element Count"}  # wired internally
_KIND = {"NodeSocketFloat": "FLOAT", "NodeSocketInt": "INT", "NodeSocketBool": "BOOL",
         "NodeSocketVector": "VECTOR", "NodeSocketColor": "COLOR", "NodeSocketString": "STRING",
         "NodeSocketObject": "OBJECT", "NodeSocketCollection": "COLLECTION", "NodeSocketMaterial": "MATERIAL",
         "NodeSocketFont": "FONT", "NodeSocketMenu": "MENU", "NodeSocketRotation": "ROTATION",
         "NodeSocketSound": "SOUND", "NodeSocketImage": "IMAGE"}
_ID_COLLECTIONS = {"OBJECT": "objects", "COLLECTION": "collections", "MATERIAL": "materials", "FONT": "fonts",
                   "SOUND": "sounds", "TEXTURE": "textures", "IMAGE": "images"}
# ID kinds that can also be given as a file path -> (extensions, bpy.data collection to load into).
_LOADABLE = {"FONT": (".ttf", ".otf", ".pfb", ".woff", ".woff2"),
             "SOUND": (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"),
             "IMAGE": (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".webp", ".bmp", ".hdr")}
_TRANSFORM = {"location": "location", "size": "scale", "objectrotation": "rotation_euler",
              "objectscale": "scale", "rotation": "rotation_euler", "scale": "scale"}
_FALLOFF_DISPLAY = {"Sphere": "SPHERE", "Box": "CUBE", "Cylinder": "CIRCLE", "Linear": "SINGLE_ARROW"}


def parse_color(v):
    """'#rrggbb' (sRGB) or [r, g, b(, a)] (linear) -> linear RGBA list."""
    if isinstance(v, str):
        h = v.lstrip("#")
        srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        v = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    v = [float(c) for c in v]
    return v + [1.0] if len(v) == 3 else v


def _to_bool(v):
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")


class Param:
    """One editable value. `attr` is an RNA property name or '["key"]' for a custom property.

    `on_change(obj)` (optional) runs once after set_params changed any parameter sharing it.
    """

    def __init__(self, name, holder, attr, kind, subtype=None, group=None, items=None, desc="", on_change=None):
        self.name, self.holder, self.attr = name, holder, attr
        self.kind, self.subtype, self.group, self.items, self.desc = kind, subtype, group, items, desc
        self.on_change = on_change

    @property
    def angular(self):
        return self.subtype in ("ANGLE", "EULER")

    @property
    def _idprop(self):
        return self.attr[2:-2] if self.attr.startswith('["') else None

    def get(self):
        key = self._idprop
        v = self.holder[key] if key else getattr(self.holder, self.attr)
        if isinstance(v, bpy.types.ID):
            return v.name
        conv = math.degrees if self.angular else (lambda x: x)
        if self.kind == "BOOLVECTOR":
            return [bool(x) for x in v]
        if isinstance(v, float):
            return round(conv(v), 5)
        if hasattr(v, "__len__") and not isinstance(v, str):
            return [round(conv(x), 5) for x in v]
        return v

    def set(self, v):
        v = self.convert(v)
        key = self._idprop
        if key:
            self.holder[key] = v
        else:
            setattr(self.holder, self.attr, v)

    def keyframe(self, frame):
        self.holder.keyframe_insert(self.attr, frame=frame)

    def convert(self, v):
        """User value (degrees, names, hex colors...) -> what Blender stores."""
        k = self.kind
        if k in _ID_COLLECTIONS:
            return self._to_id(v)
        if k == "MENU":
            for item in self.items or ():
                if norm(item) == norm(v):
                    return item
            raise ValueError(f"{self.name}: {v!r} not one of {self.items}")
        if k == "COLOR":
            return parse_color(v)
        if k == "BOOLVECTOR":
            return [_to_bool(x) for x in v]
        if k == "VECTOR":
            v = [float(x) for x in vec3(v)]
            return [math.radians(x) for x in v] if self.angular else v
        if k == "FLOAT":
            return math.radians(float(v)) if self.angular else float(v)
        return {"INT": int, "BOOL": _to_bool}.get(k, lambda x: x)(v)

    def _to_id(self, v):
        if v in (None, "") or isinstance(v, bpy.types.ID):
            return v or None
        coll = getattr(bpy.data, _ID_COLLECTIONS[self.kind])
        if v in coll:
            return coll[v]
        if str(v).lower().endswith(_LOADABLE.get(self.kind, ())):
            return coll.load(os.path.expanduser(v), check_existing=True)
        raise ValueError(f"{self.name}: no {self.kind.lower()} named {v!r}")

    def describe(self):
        d = {"value": self.get(), "type": self.kind.lower()}
        if self.angular:
            d["unit"] = "degrees"
        if self.items:
            d["options"] = self.items
        return d


def menu_items(tree, name):
    """Item names of the Menu Switch that group input `name` drives, following nested groups.

    Needed because a fresh group node's menu socket reports no enum items. O(nodes) per tree level.
    """
    for gi in (n for n in tree.nodes if n.bl_idname == "NodeGroupInput"):
        sock = gi.outputs.get(name)
        for link in (sock.links if sock else ()):
            to = link.to_node
            if to.bl_idname == "GeometryNodeMenuSwitch":
                return [e.name for e in to.enum_items]
            if to.bl_idname == "GeometryNodeGroup" and to.node_tree:
                found = menu_items(to.node_tree, link.to_socket.name)
                if found:
                    return found
    return []


def _socket_params(tree, holder_of, attr, group=None):
    """Params for a group's user-facing inputs; `holder_of(interface_item)` returns the value holder."""
    res = []
    for it in tree.interface.items_tree:
        if it.item_type != "SOCKET" or it.in_out != "INPUT" or it.name in _SKIP:
            continue
        holder = holder_of(it)
        if holder is None:
            continue
        kind = _KIND.get(it.socket_type, "OTHER")
        items = menu_items(tree, it.name) if kind == "MENU" else None
        res.append(Param(it.name, holder, attr, kind, getattr(it, "subtype", None), group, items, it.description))
    return res


def _modifier_params(mod):
    ins = mod.properties.inputs
    return _socket_params(mod.node_group, lambda it: getattr(ins, it.identifier, None), "value", mod.name)


def _node_params(node):
    def holder(it):
        s = node.inputs.get(it.identifier) or node.inputs.get(it.name)
        return s if s is not None and not s.is_linked else None
    return _socket_params(node.node_tree, holder, "default_value")


# Extra parameter providers registered by feature modules (avoids import cycles):
# (applies(obj) -> bool, params(obj) -> [Param]).
PARAM_SOURCES = []
_RNA_KIND = {"BOOLEAN": "BOOL", "INT": "INT", "FLOAT": "FLOAT", "ENUM": "MENU", "STRING": "STRING"}


def rna_params(holder, group, on_change):
    """Params for every property of an RNA struct (e.g. a PropertyGroup). O(properties)."""
    res = []
    for prop in holder.bl_rna.properties:
        if prop.identifier in ("rna_type", "name"):
            continue
        if prop.type == "POINTER":
            kind = {"Object": "OBJECT", "Collection": "COLLECTION", "Texture": "TEXTURE",
                    "Material": "MATERIAL"}.get(prop.fixed_type.identifier, "OTHER")
        else:
            kind = _RNA_KIND.get(prop.type, "OTHER")
            if getattr(prop, "array_length", 0) == 3:
                kind = "BOOLVECTOR" if prop.type == "BOOLEAN" else "VECTOR"
        items = [e.identifier for e in prop.enum_items] if prop.type == "ENUM" else None
        p = Param(prop.name, holder, prop.identifier, kind, getattr(prop, "subtype", None), group, items,
                  prop.description, on_change)
        p.aliases = (prop.identifier,)
        res.append(p)
    return res


def list_params(ref, modifier=None):
    """All editable parameters of a MoBlend object, primary modifier first. O(P)."""
    o = get_object(ref)
    k = mb_kind(o)
    want = norm(modifier) if modifier else None
    if k in (Kind.EFFECTOR, Kind.DEFORMER, Kind.LOFT, Kind.FIELD):  # parameters live on the wrapper's Params node
        res = _node_params(o[KEY_GROUP].nodes[PARAMS_NODE])
    elif k == Kind.SIMPLE_DEFORMER:
        res = [Param(key, o, f'["{key}"]', "FLOAT", "ANGLE" if key == "Angle" else None)
               for key in ("Angle", "Factor") if key in o]
    else:
        res = [p for m in mb_modifiers(o) if want is None or want in norm(m.name) for p in _modifier_params(m)]
    for applies, make in PARAM_SOURCES:
        if applies(o):
            res += [p for p in make(o) if want is None or (p.group and want in norm(p.group))]
    return res


def get_params(ref, modifier=None):
    """{object, kind, type, params, transform}; secondary-modifier params are keyed 'Modifier/Name'."""
    o = get_object(ref)
    mods = mb_modifiers(o)
    primary = mods[0].name if mods else None
    params = {p.name if p.group in (None, primary) else f"{p.group}/{p.name}": p.describe()
              for p in list_params(o, modifier)}
    return {"object": o.name, "kind": mb_kind(o) or "object", "type": o.get(KEY_TYPE, ""), "params": params,
            "transform": {"location": [round(x, 4) for x in o.location],
                          "rotation": [round(math.degrees(x), 3) for x in o.rotation_euler],
                          "scale": [round(x, 4) for x in o.scale]}}


def set_params(ref, values, frame=None, modifier=None):
    """Set parameters by name (case/spacing-insensitive); with `frame`, keyframe them too. O(P + K).

    Object transform keys: `location`, `size` (uniform scale, e.g. an effector's falloff radius),
    `object_rotation` (degrees), `object_scale`. Plain `rotation`/`scale` mean the object's transform
    only when no parameter has that name.
    """
    o = get_object(ref)
    ps = list_params(o, modifier)
    by_name = {}
    for p in ps:
        for alias in (p.name, *getattr(p, "aliases", ())):
            by_name.setdefault(norm(alias), p)
            if p.group:
                by_name.setdefault(norm(f"{p.group}/{alias}"), p)
    done, unknown, hooks = [], [], []
    for key, v in values.items():
        nk = norm(key)
        p = by_name.get(nk)
        if p is not None:
            p.set(v)
            if frame is not None:
                p.keyframe(frame)
            if p.on_change is not None and p.on_change not in hooks:
                hooks.append(p.on_change)
            if p.name == "Falloff":
                o.empty_display_type = _FALLOFF_DISPLAY.get(p.get(), "PLAIN_AXES")
        elif nk in _TRANSFORM:
            path = _TRANSFORM[nk]
            setattr(o, path, [math.radians(x) for x in v] if path == "rotation_euler" else vec3(v))
            if frame is not None:
                o.keyframe_insert(path, frame=frame)
        else:
            unknown.append(key)
            continue
        done.append(key)
    o.update_tag()  # custom-property changes (simple deformers) are not tagged automatically
    for hook in hooks:
        hook(o)
    if unknown:
        raise ValueError(f"Unknown parameter(s) {unknown} for {o.name}. Available: {[p.name for p in ps]}")
    return {"object": o.name, "set": done, "frame": frame}
