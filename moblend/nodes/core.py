"""Shared building blocks: falloff fields, effect application, instancing, splitting.

All groups evaluate in O(elements) per frame unless noted.
"""

from ..catalog import COLOR_ATTR, FALLOFF_SHAPES
from .util import S, new_group, ensure, set_menu_defaults, out

WHITE = (1.0, 1.0, 1.0, 1.0)

# Inputs every effector / deformer exposes for its falloff field, in order.
FALLOFF_INPUTS = [
    S("Falloff", "MENU", desc="Shape of the falloff field, sized by the object's scale"),
    S("Inner", "FLOAT", 0.0, 0.0, 1.0, "FACTOR", "Fraction of the radius at full strength"),
    S("Invert", "BOOL", False),
    S("Noise Scale", "FLOAT", 1.0, 0.0, desc="Noise/Random falloff: feature size"),
    S("Noise Speed", "FLOAT", 0.25, desc="Noise falloff: animation speed"),
    S("Field Seed", "INT", 0),
]
FALLOFF_NAMES = frozenset(s["name"] for s in FALLOFF_INPUTS)


def init_color(b, geo):
    """Every clone starts white so effectors have a color to blend from."""
    return b.store(geo, COLOR_ATTR, WHITE, "FLOAT_COLOR", "INSTANCE")


def falloff():
    def build():
        ng, gin, gout, b = new_group("MB Falloff", [S("Transform", "MATRIX", hide_value=True)] + FALLOFF_INPUTS,
                                     [S("Weight", "FLOAT")], "Weight field (0..1) from a shape placed by a transform")
        g = gin.outputs
        local = b.to_local(b.position(), g["Transform"])
        inner = b.math("MINIMUM", g["Inner"], 0.999)

        def radial(d):
            return b.map_range(d, inner, 1.0, 1.0, 0.0, "SMOOTHSTEP")

        ax, ay, az = b.separate(b.vmath("ABSOLUTE", local))
        _, _, lz = b.separate(local)
        w = b.math("ADD", b.math("MULTIPLY", b.seconds(), g["Noise Speed"]), g["Field Seed"])
        noise = out(b.noise4d(b.vmath("SCALE", local, scale=g["Noise Scale"]), w, detail=1.0), "Factor")
        shapes = {
            "Infinite": 1.0,
            "Sphere": radial(b.vmath("LENGTH", local)),
            "Box": radial(b.math("MAXIMUM", b.math("MAXIMUM", ax, ay), az)),
            "Cylinder": radial(b.math("MAXIMUM", b.vmath("LENGTH", b.combine(ax, ay, 0.0)), az)),
            "Linear": b.map_range(lz, -1.0, 1.0, 0.0, 1.0),
            "Noise": b.map_range(noise, 0.3, 0.7, 0.0, 1.0, "SMOOTHSTEP"),
            "Random": b.rand("FLOAT", 0.0, 1.0, seed=g["Field Seed"]),
        }
        wgt = b.index_switch("FLOAT", b.menu(FALLOFF_SHAPES, g["Falloff"]), [shapes[s] for s in FALLOFF_SHAPES])
        wgt = b.switch("FLOAT", g["Invert"], wgt, b.math("SUBTRACT", 1.0, wgt))
        b.link(wgt, gout.inputs["Weight"])
        set_menu_defaults(ng, {"Falloff": "Sphere"})
        return ng
    return ensure("MB Falloff", build)


def falloff_group(name, geo_name, extra, body, falloff_default="Sphere", menus=None, desc=""):
    """Builder for an effector/deformer type group.

    Interface: geometry, Transform (placing object), Strength, falloff inputs,
    then `extra`. `body(b, g, weight)` returns the result geometry, where
    `weight` = falloff x Strength (a field).
    """
    def build():
        head = [S(geo_name, "GEOMETRY"), S("Transform", "MATRIX", hide_value=True),
                S("Strength", "FLOAT", 1.0, desc="Overall effect amount")]
        ng, gin, gout, b = new_group(name, head + FALLOFF_INPUTS + extra, [S(geo_name, "GEOMETRY")], desc)
        g = gin.outputs
        fo = b.group(falloff(), {"Transform": g["Transform"]})
        for spec in FALLOFF_INPUTS:
            b.link(g[spec["name"]], fo.inputs[spec["name"]])
        weight = b.math("MULTIPLY", fo.outputs["Weight"], g["Strength"])
        b.link(body(b, g, weight), gout.inputs[0])
        set_menu_defaults(ng, {"Falloff": falloff_default, **(menus or {})})
        return ng
    return lambda: ensure(name, build)


def apply():
    def build():
        ng, gin, gout, b = new_group(
            "MB Apply",
            [S("Instances", "GEOMETRY"), S("Weight", "FLOAT", 1.0),
             S("Position", "VECTOR", (0, 0, 0)), S("Rotation", "VECTOR", (0, 0, 0)),
             S("Scale", "VECTOR", (0, 0, 0)), S("Color", "COLOR", WHITE),
             S("Color Mix", "FLOAT", 0.0), S("Local Space", "BOOL", True)],
            [S("Instances", "GEOMETRY")],
            "Weighted position/rotation/scale/color change on instances",
        )
        g = gin.outputs
        w = g["Weight"]
        geo = b.node("GeometryNodeTranslateInstances", {
            "Instances": g["Instances"], "Translation": b.vmath("SCALE", g["Position"], scale=w),
            "Local Space": g["Local Space"]}).outputs[0]
        rot = b.euler_to_rot(b.vmath("SCALE", g["Rotation"], scale=w))
        geo = b.node("GeometryNodeRotateInstances", {"Instances": geo, "Rotation": rot,
                                                     "Local Space": True}).outputs[0]
        s = b.vmath("MAXIMUM", b.vmath("MULTIPLY_ADD", g["Scale"], w, (1, 1, 1)), (0, 0, 0))
        geo = b.node("GeometryNodeScaleInstances", {"Instances": geo, "Scale": s, "Local Space": True}).outputs[0]
        col = b.mix("RGBA", b.math("MULTIPLY", w, g["Color Mix"]), b.named(COLOR_ATTR, "FLOAT_COLOR"), g["Color"])
        b.link(b.store(geo, COLOR_ATTR, col, "FLOAT_COLOR", "INSTANCE"), gout.inputs[0])
        return ng
    return ensure("MB Apply", build)


def instancer():
    def build():
        ng, gin, gout, b = new_group(
            "MB Instancer",
            [S("Points", "GEOMETRY"), S("Rotation", "ROTATION"), S("Scale", "VECTOR", (1, 1, 1)),
             S("Collection", "COLLECTION"), S("Order", "MENU"), S("Seed", "INT", 0)],
            [S("Instances", "GEOMETRY")],
            "Instances a collection's children on points, iterating or random",
        )
        g = gin.outputs
        coll = b.node("GeometryNodeCollectionInfo", {"Collection": g["Collection"], "Separate Children": True,
                                                     "Reset Children": False}).outputs[0]
        # Like C4D children: drop each child's position but keep its rotation and scale.
        _, rot, scale = b.instance_trs()
        coll = b.node("GeometryNodeSetInstanceTransform",
                      {"Instances": coll, "Transform": b.combine_transform(r=rot, s=scale)}).outputs[0]
        rnd = b.rand("INT", 0, 100000, seed=g["Seed"])
        pick = b.index_switch("INT", b.menu(["Iterate", "Random"], g["Order"]), [b.index(), rnd])
        geo = b.node("GeometryNodeInstanceOnPoints", {
            "Points": g["Points"], "Instance": coll, "Pick Instance": True, "Instance Index": pick,
            "Rotation": g["Rotation"], "Scale": g["Scale"]}).outputs[0]
        b.link(init_color(b, geo), gout.inputs[0])
        set_menu_defaults(ng, {"Order": "Iterate"})
        return ng
    return ensure("MB Instancer", build)


def split_centered():
    """O(V) grouping + O(G log G) KD-tree over one helper point per group, O(log G) per lookup."""
    def build():
        ng, gin, gout, b = new_group(
            "MB Split Centered",
            [S("Mesh", "GEOMETRY"), S("Group", "INT", 0)],
            [S("Instances", "GEOMETRY")],
            "Splits a mesh into one instance per group, each pivoting at its own center",
        )
        g = gin.outputs
        pos = b.position()
        bounds = b.node("GeometryNodeFieldMinAndMax", {"Value": pos, "Group ID": g["Group"]},
                        data_type="FLOAT_VECTOR", domain="POINT")
        center = b.vmath("SCALE", b.vmath("ADD", out(bounds, "Min"), out(bounds, "Max")), scale=0.5)
        geo = b.store(g["Mesh"], "mb_c", center, "FLOAT_VECTOR", "POINT")
        geo = b.store(geo, "mb_g", g["Group"], "INT", "POINT")
        c_attr, g_attr = b.named("mb_c", "FLOAT_VECTOR"), b.named("mb_g", "INT")
        centered = b.node("GeometryNodeSetPosition", {"Geometry": geo,
                                                      "Position": b.vmath("SUBTRACT", pos, c_attr)}).outputs[0]
        split = b.node("GeometryNodeSplitToInstances", {"Geometry": centered, "Group ID": g_attr}, domain="FACE")

        # One helper point per group at x = group id, carrying the group's center.
        idx = b.index()
        first = b.node("GeometryNodeFieldMinAndMax", {"Value": idx, "Group ID": g_attr}, data_type="INT",
                       domain="POINT")
        drop = b.bool_not(b.compare(idx, out(first, "Min")))
        pts = b.node("GeometryNodeDeleteGeometry", {"Geometry": geo, "Selection": drop}, domain="POINT").outputs[0]
        pts = b.node("GeometryNodeMeshToPoints", {"Mesh": pts}, mode="VERTICES").outputs[0]
        pts = b.node("GeometryNodeSetPosition", {"Geometry": pts, "Position": b.combine(g_attr)}).outputs[0]

        near = b.node("GeometryNodeSampleNearest", {"Geometry": pts,
                                                    "Sample Position": b.combine(out(split, "Group ID"))},
                      domain="POINT").outputs[0]
        cval = b.node("GeometryNodeSampleIndex", {"Geometry": pts, "Value": c_attr, "Index": near},
                      data_type="FLOAT_VECTOR", domain="POINT").outputs[0]
        res = b.node("GeometryNodeTranslateInstances", {"Instances": out(split, "Instances"),
                                                        "Translation": cval, "Local Space": False}).outputs[0]
        b.link(init_color(b, res), gout.inputs[0])
        return ng
    return ensure("MB Split Centered", build)
