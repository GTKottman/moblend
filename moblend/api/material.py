"""Materials: the MoGraph color material and simple solid materials."""

import bpy

from ..catalog import COLOR_ATTR, COLOR_MATERIAL, KEY_CLONES, Kind
from .objects import choice, get_objects, mb_kind
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


def _ramp(nt, colors, constant):
    """Color Ramp holding `colors` evenly (constant steps or a smooth blend). O(colors)."""
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT" if constant else "LINEAR"
    elems = ramp.color_ramp.elements
    while len(elems) < len(colors):
        elems.new(0.5)
    for i, (el, c) in enumerate(zip(elems, colors, strict=True)):
        el.position = i / len(colors) if constant else i / max(len(colors) - 1, 1)
        el.color = parse_color(c)
    return ramp


def multi_material(objects, colors, mode="Index", name=None):
    """C4D MoGraph Multi Shader: a color per clone, chosen by clone index (cycling), at random, or by
    MoGraph weight (blended). Assigned like set_color_material. O(colors)."""
    mode = choice(mode, ("Index", "Random", "Weight"), "mode")
    mat = bpy.data.materials.new(name or f"MB Multi {mode}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _principled(mat)
    n = len(colors)
    if mode == "Random":
        source = nt.nodes.new("ShaderNodeObjectInfo").outputs["Random"]
    else:
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_type, attr.attribute_name = "INSTANCER", "mb_index" if mode == "Index" else "mb_weight"
        source = attr.outputs["Fac"]
    if mode == "Index":  # (index mod n + 0.5) / n lands in the middle of color index mod n
        mod = nt.nodes.new("ShaderNodeMath")
        mod.operation, mod.inputs[1].default_value = "FLOORED_MODULO", n
        nt.links.new(source, mod.inputs[0])
        scale = nt.nodes.new("ShaderNodeMath")
        scale.operation = "MULTIPLY_ADD"
        scale.inputs[1].default_value, scale.inputs[2].default_value = 1.0 / n, 0.5 / n
        nt.links.new(mod.outputs[0], scale.inputs[0])
        source = scale.outputs[0]
    ramp = _ramp(nt, colors, constant=mode != "Weight")
    nt.links.new(source, ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    assign(objects, mat)
    return mat.name


def beat_material(objects, bpm=120.0, color="#ff5a1f", base="#202020", sharpness=4.0, emission=4.0, name=None):
    """C4D MoGraph Beat Shader: color and glow pulsing on the beat. The pulse is a driver using a simple
    expression (no Python execution needed): pulse = max(sin(beat phase), 0) ^ sharpness."""
    mat = bpy.data.materials.new(name or "MB Beat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _principled(mat)
    pulse = nt.nodes.new("ShaderNodeValue")
    pulse.label = "Beat"
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    drv = pulse.outputs[0].driver_add("default_value").driver
    drv.type = "SCRIPTED"
    drv.expression = f"pow(max(sin(frame / {fps:.4f} * {bpm / 60.0:.6f} * 6.283185), 0.0), {float(sharpness)})"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    for s in mix.inputs:
        if s.name == "A" and s.type == "RGBA":
            s.default_value = parse_color(base)
        if s.name == "B" and s.type == "RGBA":
            s.default_value = parse_color(color)
    nt.links.new(pulse.outputs[0], mix.inputs[0])
    out_color = next(s for s in mix.outputs if s.type == "RGBA")
    nt.links.new(out_color, bsdf.inputs["Base Color"])
    nt.links.new(out_color, bsdf.inputs["Emission Color"])
    strength = nt.nodes.new("ShaderNodeMath")
    strength.operation, strength.inputs[1].default_value = "MULTIPLY", emission
    nt.links.new(pulse.outputs[0], strength.inputs[0])
    nt.links.new(strength.outputs[0], bsdf.inputs["Emission Strength"])
    assign(objects, mat)
    return mat.name
