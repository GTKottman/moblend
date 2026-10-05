"""Shared building blocks: falloff fields, effect application, instancing, splitting.

All groups evaluate in O(elements) per frame unless noted.
"""

import math

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
        lx, ly, lz = b.separate(local)
        rxy = b.vmath("LENGTH", b.combine(lx, ly))
        cone_radius = b.at_least(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, lz), 0.5), 1e-4)  # base z=-1, tip z=1
        capsule = b.vmath("LENGTH", b.combine(lx, ly, b.math("MAXIMUM", b.math("SUBTRACT", az, 0.5), 0.0)))
        torus = b.vmath("LENGTH", b.combine(b.math("SUBTRACT", rxy, 0.75), lz))  # major 0.75, minor 0.25
        angle = b.math("ARCTAN2", ly, lx)
        w = b.math("ADD", b.math("MULTIPLY", b.seconds(), g["Noise Speed"]), g["Field Seed"])
        noise = out(b.noise4d(b.vmath("SCALE", local, scale=g["Noise Scale"]), w, detail=1.0), "Factor")
        shapes = {
            "Infinite": 1.0,
            "Sphere": radial(b.vmath("LENGTH", local)),
            "Box": radial(b.math("MAXIMUM", b.math("MAXIMUM", ax, ay), az)),
            "Cylinder": radial(b.math("MAXIMUM", b.vmath("LENGTH", b.combine(ax, ay, 0.0)), az)),
            "Cone": radial(b.math("MAXIMUM", az, b.math("DIVIDE", rxy, cone_radius))),
            "Capsule": radial(b.math("DIVIDE", capsule, 0.5)),
            "Torus": radial(b.math("DIVIDE", torus, 0.25)),
            "Linear": b.map_range(lz, -1.0, 1.0, 0.0, 1.0),
            "Radial": b.math("FRACT", b.math("ADD", b.math("DIVIDE", angle, 2 * math.pi), 1.0)),  # sweep around Z
            "Noise": b.map_range(noise, 0.3, 0.7, 0.0, 1.0, "SMOOTHSTEP"),
            "Random": b.rand("FLOAT", 0.0, 1.0, seed=g["Field Seed"]),
        }
        wgt = b.index_switch("FLOAT", b.menu(FALLOFF_SHAPES, g["Falloff"]), [shapes[s] for s in FALLOFF_SHAPES])
        wgt = b.switch("FLOAT", g["Invert"], wgt, b.math("SUBTRACT", 1.0, wgt))
        b.link(wgt, gout.inputs["Weight"])
        set_menu_defaults(ng, {"Falloff": "Sphere"})
        return ng
    return ensure("MB Falloff", build)


# MoGraph Selection as an index pattern (effectors only): which clones an effector may touch.
SELECTION_INPUTS = [
    S("Select From", "INT", 0, 0, desc="First clone index affected"),
    S("Select To", "INT", -1, -1, desc="Last clone index affected (-1 = the last clone)"),
    S("Select Every", "INT", 1, 1, desc="Affect every Nth clone"),
    S("Select Offset", "INT", 0, desc="Shift the Every pattern"),
    S("Invert Selection", "BOOL", False),
]
SELECTION_INPUTS += [
    S("Use MoGraph Selection", "BOOL", False, desc="Only clones in the cloner's MoGraph Selection tag"),
    S("Use Weight", "BOOL", False, desc="Multiply by the clones' MoGraph weight"),
]
SELECTION_NAMES = frozenset(s["name"] for s in SELECTION_INPUTS)
RANGE_INPUTS = [S("Minimum", "FLOAT", 0.0, desc="Effect where the falloff is 0"),
                S("Maximum", "FLOAT", 1.0, desc="Effect where the falloff is 1")]
LAYERS_INPUT = "Layers"  # combined weight of linked Field objects, wired by api/field.py (1 = no fields)


def _selection(b, g):
    """1 for clones inside the From/To/Every/Offset pattern, else 0 (or the reverse when inverted)."""
    idx = b.index()
    after_from = b.math("GREATER_THAN", idx, b.math("SUBTRACT", g["Select From"], 0.5))
    before_to = b.math("MAXIMUM", b.math("LESS_THAN", g["Select To"], 0.0),
                       b.math("LESS_THAN", idx, b.math("ADD", g["Select To"], 0.5)))
    on_step = b.math("LESS_THAN", b.math("FLOORED_MODULO", b.math("SUBTRACT", idx, g["Select Offset"]),
                                         b.at_least(g["Select Every"])), 0.5)
    sel = b.math("MULTIPLY", b.math("MULTIPLY", after_from, before_to), on_step)
    tag = b.mix("FLOAT", g["Use MoGraph Selection"], 1.0, b.named("mb_selection", "FLOAT"))
    sel = b.math("MULTIPLY", sel, tag)
    sel = b.mix("FLOAT", g["Invert Selection"], sel, b.math("SUBTRACT", 1.0, sel))
    return b.math("MULTIPLY", sel, b.mix("FLOAT", g["Use Weight"], 1.0, b.named("mb_weight", "FLOAT")))


def falloff_group(name, geo_name, extra, body, falloff_default="Sphere", menus=None, desc="", selection=False):
    """Builder for an effector/deformer type group.

    Interface: geometry, Transform (placing object), Strength, Layers (field objects), falloff inputs,
    selection + Minimum/Maximum inputs (if `selection`, i.e. effectors), then `extra`. `body(b, g, weight)`
    returns the result geometry, where `weight` = remap(falloff) x Strength x Layers (x selection).
    """
    def build():
        head = [S(geo_name, "GEOMETRY"), S("Transform", "MATRIX", hide_value=True),
                S("Strength", "FLOAT", 1.0, desc="Overall effect amount"),
                S(LAYERS_INPUT, "FLOAT", 1.0, hide_value=True, desc="Weight from linked Field objects")]
        inputs = head + FALLOFF_INPUTS + (SELECTION_INPUTS + RANGE_INPUTS if selection else []) + extra
        ng, gin, gout, b = new_group(name, inputs, [S(geo_name, "GEOMETRY")], desc)
        g = gin.outputs
        fo = b.group(falloff(), {"Transform": g["Transform"]})
        for spec in FALLOFF_INPUTS:
            b.link(g[spec["name"]], fo.inputs[spec["name"]])
        weight = b.math("MULTIPLY", fo.outputs["Weight"], g[LAYERS_INPUT])
        if selection:  # C4D Minimum/Maximum: where the falloff is 0 / 1 (e.g. -1..1 for a two-way effect)
            weight = b.math("MULTIPLY_ADD", weight, b.math("SUBTRACT", g["Maximum"], g["Minimum"]), g["Minimum"])
            weight = b.math("MULTIPLY", weight, _selection(b, g))
        weight = b.math("MULTIPLY", weight, g["Strength"])
        b.link(body(b, g, weight), gout.inputs[0])
        set_menu_defaults(ng, {"Falloff": falloff_default, **(menus or {})})
        return ng
    return lambda: ensure(name, build)


TEXTURES = ("Noise", "Voronoi", "Wave", "Gradient", "Checker", "Magic", "Image")
TEXTURE_INPUTS = [S("Texture", "MENU", desc="Procedural texture, or Image"), S("Image", "IMAGE"),
                  S("Scale", "FLOAT", 1.0), S("Detail", "FLOAT", 2.0, 0.0, 15.0),
                  S("Speed", "FLOAT", 0.0, desc="Animate the texture over time"),
                  S("Contrast", "FLOAT", 0.0, 0.0, 0.99, "FACTOR")]


def texture(b, g, local):
    """(value 0..1, color) of the chosen texture at `local` (an object-local position; images map local
    X/Y -1..1 to the whole image). Uses the TEXTURE_INPUTS of `g`."""
    vec = b.vmath("SCALE", local, scale=g["Scale"])
    w = b.math("MULTIPLY", b.seconds(), g["Speed"])
    lx, ly, _ = b.separate(local)
    image = b.node("GeometryNodeImageTexture", {"Image": g["Image"], "Vector": b.vmath(
        "MULTIPLY_ADD", b.combine(lx, ly), (0.5, 0.5, 0.5), (0.5, 0.5, 0.0))})
    noise = b.noise4d(vec, w, g["Detail"])
    voronoi = b.node("ShaderNodeTexVoronoi", {"Vector": vec, "W": w}, voronoi_dimensions="4D")
    wave = b.node("ShaderNodeTexWave", {"Vector": vec, "Detail": g["Detail"],
                                       "Phase Offset": b.math("MULTIPLY", w, 2 * math.pi)})
    checker = b.node("ShaderNodeTexChecker", {"Vector": vec, "Scale": 1.0, "Color1": (1, 1, 1, 1),
                                              "Color2": (0, 0, 0, 1)})
    magic = b.node("ShaderNodeTexMagic", {"Vector": vec})
    gradient = b.map_range(lx, -1.0, 1.0, 0.0, 1.0)
    values = [out(noise, "Factor"), out(voronoi, "Distance"), out(wave, "Fac"), gradient, out(checker, "Fac"),
              out(magic, "Fac"), b.vmath("DOT_PRODUCT", out(image, "Color"), (0.2126, 0.7152, 0.0722))]  # luminance
    colors = [out(noise, "Color"), out(voronoi, "Color"), out(wave, "Color"), b.combine(gradient, gradient, gradient),
              out(checker, "Color"), out(magic, "Color"), out(image, "Color")]
    which = b.menu(TEXTURES, g["Texture"])
    value = b.index_switch("FLOAT", which, values)
    half = b.math("MULTIPLY", g["Contrast"], 0.5)
    return b.map_range(value, half, b.math("SUBTRACT", 1.0, half), 0.0, 1.0), b.index_switch("RGBA", which, colors)


def sound_level(b, g, count):
    """0..1 loudness from inputs Sound/Mode/Low/High/Gain/Time Offset. Spread mode gives element i the
    log-spaced band Low*(High/Low)^(i/count) .. ^((i+1)/count); All mode uses the whole range."""
    ratio = b.math("DIVIDE", g["High"], b.at_least(g["Low"], 1.0))

    def band_edge(i):
        return b.math("MULTIPLY", g["Low"], b.math("POWER", ratio, b.math("DIVIDE", i, b.at_least(count))))

    spread = b.compare(b.menu(["Spread", "All"], g["Mode"]), 0)
    idx = b.index()
    lo = b.mix("FLOAT", spread, g["Low"], band_edge(idx))
    hi = b.mix("FLOAT", spread, g["High"], band_edge(b.math("ADD", idx, 1.0)))
    amp = b.node("GeometryNodeSampleSoundFrequencies", {
        "Sound": g["Sound"], "Time": b.math("ADD", b.seconds(), g["Time Offset"]), "All Channels": True,
        "Low": lo, "High": hi}).outputs[0]
    return b.math("MINIMUM", b.math("MULTIPLY", amp, g["Gain"]), 1.0)


DEFORMATION = ("Off", "Point", "Polygon", "Object")


def apply():
    """Weighted position/rotation/scale/color/visibility on instances. With Deformation, also on plain
    geometry: Point moves points, Polygon treats every face as a clone, Object the whole mesh. O(elements)."""
    def build():
        ng, gin, gout, b = new_group(
            "MB Apply",
            [S("Instances", "GEOMETRY"), S("Weight", "FLOAT", 1.0),
             S("Position", "VECTOR", (0, 0, 0)), S("Rotation", "VECTOR", (0, 0, 0)),
             S("Scale", "VECTOR", (0, 0, 0)), S("Color", "COLOR", WHITE),
             S("Color Mix", "FLOAT", 0.0), S("Local Space", "BOOL", True), S("Visibility", "BOOL", False),
             S("Deformation", "MENU"), S("Weight Transform", "FLOAT", 0.0)],
            [S("Instances", "GEOMETRY")],
            "Weighted position/rotation/scale/color change on instances (and meshes via Deformation)",
        )
        g = gin.outputs
        w = g["Weight"]

        def effect(geo):
            geo = b.node("GeometryNodeTranslateInstances", {
                "Instances": geo, "Translation": b.vmath("SCALE", g["Position"], scale=w),
                "Local Space": g["Local Space"]}).outputs[0]
            rot = b.euler_to_rot(b.vmath("SCALE", g["Rotation"], scale=w))
            geo = b.node("GeometryNodeRotateInstances", {"Instances": geo, "Rotation": rot,
                                                         "Local Space": True}).outputs[0]
            s = b.vmath("MAXIMUM", b.vmath("MULTIPLY_ADD", g["Scale"], w, (1, 1, 1)), (0, 0, 0))
            hidden = b.math("MULTIPLY", g["Visibility"], b.math("GREATER_THAN", w, 0.5))  # C4D Visibility
            s = b.vmath("SCALE", s, scale=b.math("SUBTRACT", 1.0, hidden))
            geo = b.node("GeometryNodeScaleInstances", {"Instances": geo, "Scale": s, "Local Space": True}).outputs[0]
            col = b.mix("RGBA", b.math("MULTIPLY", w, g["Color Mix"]), b.named(COLOR_ATTR, "FLOAT_COLOR"),
                        g["Color"])
            geo = b.store(geo, COLOR_ATTR, col, "FLOAT_COLOR", "INSTANCE")
            # C4D Weight Transform: effectors raise or lower clones' weight for the effectors after them.
            weight = b.math("MULTIPLY_ADD", g["Weight Transform"], w, b.named("mb_weight", "FLOAT"))
            return b.store(geo, "mb_weight", weight, "FLOAT", "INSTANCE")

        parts = b.node("GeometryNodeSeparateComponents", {"Geometry": g["Instances"]})
        mesh = out(parts, "Mesh")
        moved = b.node("GeometryNodeSetPosition", {"Geometry": mesh,
                                                   "Offset": b.vmath("SCALE", g["Position"], scale=w)}).outputs[0]
        polys = b.group(split_centered("FACE"), {"Geometry": b.node("GeometryNodeSplitEdges", {"Mesh": mesh}
                                                                      ).outputs[0],
                                                  "Group": out(b.node("GeometryNodeInputMeshIsland"), "Island Index")})
        whole = b.node("GeometryNodeGeometryToInstance", {"Geometry": mesh}).outputs[0]

        def realized(geo):
            return b.node("GeometryNodeRealizeInstances", {"Geometry": effect(geo)}).outputs[0]

        deformed = b.index_switch("GEOMETRY", b.menu(DEFORMATION, g["Deformation"]),
                                  [mesh, moved, realized(polys.outputs[0]), realized(whole)])
        rest = b.join(out(parts, "Curve"), out(parts, "Point Cloud"), out(parts, "Volume"),
                      out(parts, "Grease Pencil"))
        b.link(b.join(effect(out(parts, "Instances")), deformed, rest), gout.inputs[0])
        set_menu_defaults(ng, {"Deformation": "Off"})
        return ng
    return ensure("MB Apply", build)


CLONE_ORDERS = ("Iterate", "Random", "Blend")
SELECTION_TAG, WEIGHT_TAG = "MoGraph Selection", "MoGraph Weight"  # vertex groups on the cloner's own mesh


def _child(b, children, k):
    """Child k of the clone collection as real geometry. O(child elements)."""
    keep = b.compare(b.index(), k)
    only = b.node("GeometryNodeDeleteGeometry", {"Geometry": children, "Selection": b.bool_not(keep)},
                  domain="INSTANCE").outputs[0]
    return b.node("GeometryNodeRealizeInstances", {"Geometry": only}).outputs[0]


def _blend(b, points, children, transform):
    """Blend mode: clone i morphs between neighbouring children at t = i/(n-1) * (children-1).

    Children with equal vertex counts morph point by point; others switch at the halfway mark.
    O(clones x child vertices) via a For Each Element zone.
    """
    n_children = b.instance_count(children)
    n_points = out(b.node("GeometryNodeAttributeDomainSize", {"Geometry": points}, component="POINTCLOUD"),
                   "Point Count")
    t = b.math("MULTIPLY", b.math("DIVIDE", b.index(), b.steps(n_points)),
               b.at_least(b.math("SUBTRACT", n_children, 1.0), 0.0))
    pts = b.store(points, "mb_t", t, "FLOAT", "POINT")
    fe_in = b.node("GeometryNodeForeachGeometryElementInput")
    fe_out = b.node("GeometryNodeForeachGeometryElementOutput")
    fe_in.pair_with_output(fe_out)
    fe_out.domain = "POINT"
    b.link(pts, fe_in.inputs["Geometry"])
    i = fe_in.outputs["Index"]
    ti = b.node("GeometryNodeSampleIndex", {"Geometry": pts, "Value": b.named("mb_t", "FLOAT"), "Index": i},
                data_type="FLOAT", domain="POINT").outputs[0]
    k = b.math("FLOOR", ti)
    f = b.math("SUBTRACT", ti, k)
    a = _child(b, children, k)
    last = b.at_least(b.math("SUBTRACT", n_children, 1.0), 0.0)
    c = _child(b, children, b.math("MINIMUM", b.math("ADD", k, 1.0), last))

    def vertex_count(geo):
        return out(b.node("GeometryNodeAttributeDomainSize", {"Geometry": geo}, component="MESH"), "Point Count")

    other = b.node("GeometryNodeSampleIndex", {"Geometry": c, "Value": b.position(), "Index": b.index()},
                   data_type="FLOAT_VECTOR", domain="POINT").outputs[0]
    morph = b.node("GeometryNodeSetPosition", {"Geometry": a, "Position": b.mix("VECTOR", f, b.position(), other)}
                   ).outputs[0]
    nearest = b.switch("GEOMETRY", b.math("GREATER_THAN", f, 0.5), a, c)
    shape = b.switch("GEOMETRY", b.compare(vertex_count(a), vertex_count(c)), nearest, morph)
    b.link(b.node("GeometryNodeGeometryToInstance", {"Geometry": shape}).outputs[0],
           [s for s in fe_out.inputs if s.type == "GEOMETRY"][-1])
    generated = [s for s in fe_out.outputs if s.type == "GEOMETRY"][-1]
    placed = b.node("GeometryNodeSampleIndex", {"Geometry": points, "Value": transform, "Index": b.index()},
                    data_type="FLOAT4X4", domain="POINT").outputs[0]
    return b.node("GeometryNodeSetInstanceTransform", {"Instances": generated, "Transform": placed}).outputs[0]


def instancer():
    def build():
        ng, gin, gout, b = new_group(
            "MB Instancer",
            [S("Points", "GEOMETRY"), S("Rotation", "ROTATION"), S("Scale", "VECTOR", (1, 1, 1)),
             S("Collection", "COLLECTION"), S("Order", "MENU"), S("Seed", "INT", 0), S("Data", "GEOMETRY")],
            [S("Instances", "GEOMETRY")],
            "Instances a collection's children on points (iterate, random or blend) and attaches per-clone data",
        )
        g = gin.outputs
        coll = b.node("GeometryNodeCollectionInfo", {"Collection": g["Collection"], "Separate Children": True,
                                                     "Reset Children": False}).outputs[0]
        # Like C4D children: drop each child's position but keep its rotation and scale.
        _, rot, scale = b.instance_trs()
        coll = b.node("GeometryNodeSetInstanceTransform",
                      {"Instances": coll, "Transform": b.combine_transform(r=rot, s=scale)}).outputs[0]
        rnd = b.rand("INT", 0, 100000, seed=g["Seed"])
        order = b.menu(CLONE_ORDERS, g["Order"])
        pick = b.index_switch("INT", order, [b.index(), rnd, b.index()])
        picked = b.node("GeometryNodeInstanceOnPoints", {
            "Points": g["Points"], "Instance": coll, "Pick Instance": True, "Instance Index": pick,
            "Rotation": g["Rotation"], "Scale": g["Scale"]}).outputs[0]
        transform = b.combine_transform(b.position(), g["Rotation"], g["Scale"])
        geo = b.index_switch("GEOMETRY", order, [picked, picked, _blend(b, g["Points"], coll, transform)])
        geo = init_color(b, geo)
        # Per-clone data from the cloner's own mesh: vertex i holds clone i's selection / weight tags.
        # A missing tag (or a clone index beyond the data points) reads as 0.
        for tag, attr in ((SELECTION_TAG, "mb_selection"), (WEIGHT_TAG, "mb_weight")):
            value = b.node("GeometryNodeSampleIndex", {"Geometry": g["Data"], "Value": b.named(tag, "FLOAT"),
                                                       "Index": b.index()}, data_type="FLOAT", domain="POINT")
            geo = b.store(geo, attr, value.outputs[0], "FLOAT", "INSTANCE")
        geo = b.store(geo, "mb_index", b.index(), "FLOAT", "INSTANCE")
        b.link(geo, gout.inputs[0])
        set_menu_defaults(ng, {"Order": "Iterate"})
        return ng
    return ensure("MB Instancer", build)


def split_centered(domain="FACE"):
    """Split geometry into one instance per group id, each pivoting at its own bounding-box center.

    `domain` is FACE for meshes, CURVE for curves. Two splits of the same groups come out in the same
    order: the first (uncentered) yields each piece's center via Instance Bounds, the second holds the
    centered geometry and is moved back by that center. O(elements).
    """
    name = "MB Split Centered" if domain == "FACE" else f"MB Split Centered {domain.title()}"

    def build():
        ng, gin, gout, b = new_group(name, [S("Geometry", "GEOMETRY"), S("Group", "INT", 0)],
                                     [S("Instances", "GEOMETRY")],
                                     "Splits geometry into one instance per group, each pivoting at its own center")
        g = gin.outputs
        pos = b.position()
        bounds = b.node("GeometryNodeFieldMinAndMax", {"Value": pos, "Group ID": g["Group"]},
                        data_type="FLOAT_VECTOR", domain="POINT")
        center = b.vmath("SCALE", b.vmath("ADD", out(bounds, "Min"), out(bounds, "Max")), scale=0.5)
        geo = b.store(g["Geometry"], "mb_g", g["Group"], "INT", "POINT")
        group = b.named("mb_g", "INT")
        first = b.node("GeometryNodeSplitToInstances", {"Geometry": geo, "Group ID": group}, domain=domain)
        centered = b.node("GeometryNodeSetPosition", {"Geometry": geo,
                                                      "Position": b.vmath("SUBTRACT", pos, center)}).outputs[0]
        second = b.node("GeometryNodeSplitToInstances", {"Geometry": centered, "Group ID": group}, domain=domain)
        box = b.node("GeometryNodeInputInstanceBounds")
        mid = b.vmath("SCALE", b.vmath("ADD", out(box, "Min"), out(box, "Max")), scale=0.5)
        offset = b.node("GeometryNodeSampleIndex", {"Geometry": out(first, "Instances"), "Value": mid,
                                                    "Index": b.index()},
                        data_type="FLOAT_VECTOR", domain="INSTANCE").outputs[0]
        res = b.node("GeometryNodeTranslateInstances", {"Instances": out(second, "Instances"),
                                                        "Translation": offset, "Local Space": False}).outputs[0]
        b.link(init_color(b, res), gout.inputs[0])
        return ng
    return ensure(name, build)
