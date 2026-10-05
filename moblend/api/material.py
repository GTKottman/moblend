"""Materials: the MoGraph color material and simple solid materials."""

import bpy

from ..catalog import COLOR_ATTR, COLOR_MATERIAL, KEY_CLONES, Kind
from .objects import get_objects, mb_kind
from .params import list_params, parse_color, set_params


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def mograph_material():
    """Material whose base color is the per-clone effector color (COLOR_ATTR)."""
    mat = bpy.data.materials.get(COLOR_MATERIAL)
    if mat:
        return mat
    mat = bpy.data.materials.new(COLOR_MATERIAL)
    mat.use_nodes = True
    bsdf = _principled(mat)
    attr = mat.node_tree.nodes.new("ShaderNodeAttribute")
    attr.attribute_type, attr.attribute_name = "INSTANCER", COLOR_ATTR
    attr.location = (bsdf.location.x - 300, bsdf.location.y)
    mat.node_tree.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.35
    return mat


def solid_material(color, metallic=0.0, roughness=0.4, emission=0.0, name=None):
    mat = bpy.data.materials.new(name or "MB Material")
    mat.use_nodes = True
    bsdf = _principled(mat)
    rgba = parse_color(color)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = rgba
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def assign(objects, mat):
    """Assign `mat` to objects. A cloner means its clones; a generator with a Material input (MoText,
    Sweep, Volume Builder, Tracer) gets it there, because that input overrides the mesh's slots. O(objects)."""
    done = []
    for o in get_objects(objects):
        if mb_kind(o) == Kind.CLONER:
            done += assign(list(o[KEY_CLONES].objects), mat)
            continue
        if any(p.name == "Material" for p in list_params(o)):
            set_params(o, {"Material": mat.name})
        elif getattr(o.data, "materials", None) is not None:
            o.data.materials.clear()
            o.data.materials.append(mat)
        else:
            continue
        done.append(o.name)
    return done


def set_color_material(objects):
    mat = mograph_material()
    assign(objects, mat)
    return mat.name
