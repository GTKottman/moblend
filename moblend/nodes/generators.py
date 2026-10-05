"""Generators: MoText, Sweep, Fracture, Tracer, Volume Builder (each O(output elements) unless noted)."""

import math

from ..catalog import COLOR_ATTR
from .util import S, geometry_group, out
from .core import split_centered

TEXT_PARTS = {"Characters": "mb_char", "Words": "mb_word", "Lines": "mb_line"}


def _motext(b, g):
    s2c = b.node("GeometryNodeStringToCurves", {
        "String": g["Text"], "Size": g["Size"], "Font": g["Font"], "Align X": g["Align"],
        "Character Spacing": g["Character Spacing"], "Word Spacing": g["Word Spacing"],
        "Line Spacing": g["Line Spacing"]})
    s2c.inputs["Align Y"].default_value = "Middle"
    inst = out(s2c, "Curve Instances")
    for attr, value in zip(TEXT_PARTS.values(), (b.index(), out(s2c, "Word"), out(s2c, "Line")), strict=True):
        inst = b.store(inst, attr, value, "INT", "INSTANCE")
    flat = b.node("GeometryNodeRealizeInstances",
                  {"Geometry": b.node("GeometryNodeFillCurve", {"Curve": inst}).outputs[0]}).outputs[0]
    # Extrusion leaves the original faces open, so close the back with a flipped copy.
    top = b.node("GeometryNodeExtrudeMesh", {"Mesh": flat, "Offset": (0, 0, 1), "Offset Scale": g["Depth"]},
                 mode="FACES").outputs[0]
    back = b.node("GeometryNodeFlipFaces", {"Mesh": flat}).outputs[0]
    solid = b.node("GeometryNodeMergeByDistance", {"Geometry": b.join(back, top), "Distance": 1e-5}).outputs[0]
    mesh = b.switch("GEOMETRY", b.math("GREATER_THAN", g["Depth"], 0.0), flat, solid)
    mesh = b.node("GeometryNodeTransform", {"Geometry": mesh,
                                            "Translation": b.combine(z=b.math("MULTIPLY", g["Depth"], -0.5))}
                  ).outputs[0]
    upright = b.euler_to_rot(b.combine(x=b.math("MULTIPLY", g["Upright"], math.pi / 2)))
    mesh = b.node("GeometryNodeTransform", {"Geometry": mesh, "Rotation": upright}).outputs[0]
    mesh = b.node("GeometryNodeSetMaterial", {"Geometry": mesh, "Material": g["Material"]}).outputs[0]
    split = b.menu(list(TEXT_PARTS) + ["Whole"], g["Split"])
    group = b.index_switch("INT", split, [b.named(a, "INT") for a in TEXT_PARTS.values()] + [0])
    return b.group(split_centered(), {"Geometry": mesh, "Group": group}).outputs[0]


def _sweep(b, g):
    path = b.node("GeometryNodeResampleCurve", {"Curve": b.object_geometry(g["Path"]),
                                                "Count": g["Path Resolution"]}).outputs[0]
    path = b.node("GeometryNodeTrimCurve", {"Curve": path, "Start": g["Start"], "End": g["End"]},
                  mode="FACTOR").outputs[0]
    along = out(b.node("GeometryNodeSplineParameter"), "Factor")
    path = b.node("GeometryNodeSetCurveTilt", {"Curve": path, "Tilt": b.math("MULTIPLY", along, g["Twist"])}
                  ).outputs[0]
    circle = b.node("GeometryNodeCurvePrimitiveCircle", {"Resolution": g["Sides"], "Radius": g["Radius"]},
                    mode="RADIUS").outputs[0]
    custom = b.object_geometry(g["Profile"], space="ORIGINAL")
    curves = b.node("GeometryNodeAttributeDomainSize", {"Geometry": custom}, component="CURVE")
    profile = b.switch("GEOMETRY", b.math("GREATER_THAN", out(curves, "Spline Count"), 0.0), circle, custom)
    mesh = b.node("GeometryNodeCurveToMesh", {"Curve": path, "Profile Curve": profile, "Fill Caps": g["Fill Caps"],
                                              "Scale": b.mix("FLOAT", along, 1.0, g["End Scale"])}).outputs[0]
    mesh = b.node("GeometryNodeSetShadeSmooth", {"Geometry": mesh}).outputs[0]
    return b.node("GeometryNodeSetMaterial", {"Geometry": mesh, "Material": g["Material"]}).outputs[0]


def _fracture(b, g):
    """Pieces as clones: mesh islands (or a stored mb_piece id, e.g. from Voronoi Fracture), every polygon,
    or every curve segment (PolyFX). O(elements)."""
    geo = b.node("GeometryNodeRealizeInstances", {"Geometry": g["Geometry"]}).outputs[0]
    parts = b.node("GeometryNodeSeparateComponents", {"Geometry": geo})
    mesh, curves = out(parts, "Mesh"), out(parts, "Curve")
    polygons = b.compare(b.menu(["Islands", "Polygons"], g["Mode"]), 1)
    mesh = b.switch("GEOMETRY", polygons, mesh, b.node("GeometryNodeSplitEdges", {"Mesh": mesh}).outputs[0])
    piece = b.node("GeometryNodeInputNamedAttribute", {"Name": "mb_piece"}, data_type="INT")
    island = out(b.node("GeometryNodeInputMeshIsland"), "Island Index")
    use_piece = b.node("FunctionNodeBooleanMath", {0: out(piece, "Exists"), 1: b.bool_not(polygons)},
                       operation="AND").outputs[0]
    mesh_group = b.switch("INT", use_piece, island, out(piece, "Attribute"))
    curve_group = out(b.node("GeometryNodeCurveOfPoint"), "Curve Index")
    pieces = b.join(b.group(split_centered("FACE"), {"Geometry": mesh, "Group": mesh_group}).outputs[0],
                    b.group(split_centered("CURVE"), {"Geometry": curves, "Group": curve_group}).outputs[0])
    tint = b.rand("FLOAT_VECTOR", (0.15, 0.15, 0.15), (1, 1, 1), seed=g["Color Seed"])
    color = b.mix("RGBA", g["Colorize"], (1, 1, 1, 1), tint)
    return b.store(pieces, COLOR_ATTR, color, "FLOAT_COLOR", "INSTANCE")


def _trails(b, g, clone_points):
    """Simulation zone keeping each clone's last `Length` positions as points (mb_id, mb_age).

    O(clones x Length) per frame; needs playback from the start frame like any simulation.
    """
    sim_in, sim_out = b.node("GeometryNodeSimulationInput"), b.node("GeometryNodeSimulationOutput")
    sim_in.pair_with_output(sim_out)
    history = sim_in.outputs[1]  # Geometry (index 0 is Delta Time)
    # World Space: store world positions so moving/rotating the object itself leaves trails too.
    world = b.node("GeometryNodeObjectInfo", {"Object": b.inp("GeometryNodeSelfObject")}, transform_space="ORIGINAL")
    to_world = b.switch("MATRIX", g["World Space"], b.node("FunctionNodeCombineTransform").outputs[0],
                        out(world, "Transform"))
    aged = b.store(history, "mb_age", b.math("ADD", b.named("mb_age", "INT"), 1.0), "INT", "POINT")
    expired = b.math("GREATER_THAN", b.named("mb_age", "INT"), b.math("SUBTRACT", g["Length"], 1.0))
    aged = b.node("GeometryNodeDeleteGeometry", {"Geometry": aged, "Selection": expired}, domain="POINT").outputs[0]
    fresh = b.node("GeometryNodeSetPosition", {"Geometry": clone_points,
                                               "Position": b.transform_point(b.position(), to_world)}).outputs[0]
    fresh = b.store(fresh, "mb_id", b.index(), "INT", "POINT")
    fresh = b.store(fresh, "mb_age", 0, "INT", "POINT")
    b.link(b.join(aged, fresh), sim_out.inputs["Geometry"])
    local = b.node("GeometryNodeSetPosition", {"Geometry": sim_out.outputs[0],
                                               "Position": b.to_local(b.position(), to_world)}).outputs[0]
    return b.node("GeometryNodePointsToCurves", {"Points": local,
                                                 "Curve Group ID": b.named("mb_id", "INT"),
                                                 "Weight": b.named("mb_age", "INT")}).outputs[0]


def _tracer(b, g):
    pts = b.node("GeometryNodeInstancesToPoints", {"Instances": g["Geometry"]}).outputs[0]
    connect = b.node("GeometryNodePointsToCurves", {"Points": pts}).outputs[0]
    connect = b.node("GeometryNodeSetSplineCyclic", {"Geometry": connect, "Cyclic": g["Closed"]}).outputs[0]
    crv = b.index_switch("GEOMETRY", b.menu(["Connect", "Trails"], g["Mode"]), [connect, _trails(b, g, pts)])
    profile = b.node("GeometryNodeCurvePrimitiveCircle", {"Resolution": g["Sides"], "Radius": g["Radius"]},
                     mode="RADIUS").outputs[0]
    # Trails thin out with age (Connect points have no age, so they keep full size).
    age = b.math("DIVIDE", b.named("mb_age", "INT"), b.at_least(g["Length"]))
    taper = b.math("SUBTRACT", 1.0, b.math("MULTIPLY", age, g["Taper"]))
    tube = b.node("GeometryNodeCurveToMesh", {"Curve": crv, "Profile Curve": profile, "Scale": taper}).outputs[0]
    tube = b.node("GeometryNodeSetMaterial", {"Geometry": tube, "Material": g["Material"]}).outputs[0]
    return b.join(b.switch("GEOMETRY", g["Keep Clones"], None, g["Geometry"]), tube)


def _volume(b, g):
    """Union of the Add collection minus the Subtract collection, as one smooth mesh.

    O(voxels): grid resolution ~ (extent / Voxel Size)^2 in the narrow band around surfaces.
    """
    def mesh_of(collection):
        geo = b.node("GeometryNodeCollectionInfo", {"Collection": collection}, transform_space="RELATIVE")
        return b.node("GeometryNodeRealizeInstances", {"Geometry": out(geo)}).outputs[0]

    # Smoothing/fillet passes eat into the narrow band; widen it so the surface never tears.
    band = b.math("ADD", b.math("ADD", g["Smooth"], g["Fillet"]), 3.0)

    def sdf(mesh):
        return b.node("GeometryNodeMeshToSDFGrid", {"Mesh": mesh, "Voxel Size": g["Voxel Size"],
                                                    "Band Width": band}).outputs[0]

    added, cutters = sdf(mesh_of(g["Add"])), mesh_of(g["Subtract"])
    carved = b.node("GeometryNodeSDFGridBoolean", {"Grid 1": added, "Grid 2": sdf(cutters)},
                    operation="DIFFERENCE").outputs[0]
    # A difference with an empty grid erases everything, so only carve when there are cutters.
    faces = out(b.node("GeometryNodeAttributeDomainSize", {"Geometry": cutters}, component="MESH"), "Face Count")
    grid = b.switch("FLOAT", b.math("GREATER_THAN", faces, 0.0), added, carved)
    grid = b.node("GeometryNodeSDFGridMean", {"Grid": grid, "Width": 1, "Iterations": g["Smooth"]}).outputs[0]
    grid = b.node("GeometryNodeSDFGridFillet", {"Grid": grid, "Iterations": g["Fillet"]}).outputs[0]
    grid = b.node("GeometryNodeSDFGridOffset", {"Grid": grid, "Distance": g["Offset"]}).outputs[0]
    mesh = b.node("GeometryNodeGridToMesh", {"Grid": grid, "Threshold": 0.0, "Adaptivity": g["Adaptivity"]}
                  ).outputs[0]
    mesh = b.node("GeometryNodeSetShadeSmooth", {"Geometry": mesh}).outputs[0]
    return b.node("GeometryNodeSetMaterial", {"Geometry": mesh, "Material": g["Material"]}).outputs[0]


def _loft(b, g):
    """Skin ordered profile curves (curve attribute mb_profile = order) into one surface.

    Every profile is resampled to `Points`; rails run through matching points across profiles and are
    resampled to `Rows`. O(Points x Rows) output; O(Points x profiles) to build the rails.
    """
    profiles = b.node("GeometryNodeResampleCurve", {"Curve": g["Geometry"], "Count": g["Points"]}).outputs[0]
    pts = b.store(profiles, "mb_i", out(b.node("GeometryNodeSplineParameter"), "Index"), "INT", "POINT")
    pts = b.node("GeometryNodeCurveToPoints", {"Curve": pts}, mode="EVALUATED").outputs[0]
    rails = b.node("GeometryNodePointsToCurves", {"Points": pts, "Curve Group ID": b.named("mb_i", "INT"),
                                                  "Weight": b.named("mb_profile", "INT")}).outputs[0]
    smooth = b.node("GeometryNodeCurveSplineType", {"Curve": rails}, spline_type="CATMULL_ROM").outputs[0]
    rails = b.switch("GEOMETRY", g["Smooth"], rails, smooth)
    rows = g["Rows"]
    rails = b.node("GeometryNodeResampleCurve", {"Curve": rails, "Count": rows}).outputs[0]

    cyclic = b.node("GeometryNodeSampleIndex", {"Geometry": profiles, "Value": b.inp("GeometryNodeInputSplineCyclic"),
                                                "Index": 0}, data_type="BOOLEAN", domain="CURVE").outputs[0]
    columns = b.math("ADD", g["Points"], cyclic)  # a closed loop repeats its first column, welded below
    grid = b.node("GeometryNodeMeshGrid", {"Vertices X": columns, "Vertices Y": rows}).outputs[0]
    i = b.index()
    column = b.math("FLOORED_MODULO", b.math("FLOOR", b.math("DIVIDE", i, rows)), g["Points"])
    src = b.math("ADD", b.math("MULTIPLY", column, rows), b.math("FLOORED_MODULO", i, rows))
    pos = b.node("GeometryNodeSampleIndex", {"Geometry": rails, "Value": b.position(), "Index": src},
                 data_type="FLOAT_VECTOR", domain="POINT").outputs[0]
    skin = b.node("GeometryNodeSetPosition", {"Geometry": grid, "Position": pos}).outputs[0]
    # Grid winding (around x along) faces the opposite way to the cap fans for any profile/loft
    # direction, so flipping the skin makes the closed surface consistent; "Flip" turns it inside out.
    skin = b.node("GeometryNodeFlipFaces", {"Mesh": skin}).outputs[0]

    def end_cap(order, flip):
        """Triangle fan closing the profile with this order. Fill Curve would flatten it onto XY, so the
        loop's edges are extruded to its centroid instead (works in any plane; welded by the merge below)."""
        keep = b.compare(b.named("mb_profile", "INT"), order)
        one = b.node("GeometryNodeDeleteGeometry", {"Geometry": profiles, "Selection": b.bool_not(keep)},
                     domain="CURVE").outputs[0]
        loop = b.node("GeometryNodeCurveToMesh", {"Curve": one}).outputs[0]
        stat = b.node("GeometryNodeAttributeStatistic", {"Geometry": loop, "Attribute": b.position()},
                      data_type="FLOAT_VECTOR", domain="POINT")
        ext = b.node("GeometryNodeExtrudeMesh", {"Mesh": loop, "Offset Scale": 0.0}, mode="EDGES")
        # Edge-mode offsets are per edge, so snap the new ring exactly onto the centroid instead.
        fan = b.node("GeometryNodeSetPosition", {"Geometry": out(ext, "Mesh"), "Selection": out(ext, "Top"),
                                                 "Position": out(stat, "Mean")}).outputs[0]
        return b.node("GeometryNodeFlipFaces", {"Mesh": fan}).outputs[0] if flip else fan

    count = out(b.node("GeometryNodeAttributeDomainSize", {"Geometry": profiles}, component="CURVE"), "Spline Count")
    both = b.node("FunctionNodeBooleanMath", {0: g["Caps"], 1: cyclic}, operation="AND").outputs[0]
    caps = b.switch("GEOMETRY", both, None, b.join(end_cap(0, True), end_cap(b.math("SUBTRACT", count, 1.0), False)))
    mesh = b.node("GeometryNodeMergeByDistance", {"Geometry": b.join(skin, caps), "Distance": 1e-4}).outputs[0]
    mesh = b.switch("GEOMETRY", g["Flip"], mesh, b.node("GeometryNodeFlipFaces", {"Mesh": mesh}).outputs[0])
    mesh = b.node("GeometryNodeSetShadeSmooth", {"Geometry": mesh}).outputs[0]
    return b.node("GeometryNodeSetMaterial", {"Geometry": mesh, "Material": g["Material"]}).outputs[0]


def _display(b, g):
    """Cinema 4D Viewport Mode: in the viewport only, show clones as boxes, points or nothing. O(clones)."""
    geo = g["Geometry"]
    bounds = b.node("GeometryNodeInputInstanceBounds")
    _, rot, scale = b.instance_trs()
    box = b.vmath("MULTIPLY", b.vmath("SUBTRACT", out(bounds, "Max"), out(bounds, "Min")), scale)
    tagged = b.store(b.store(geo, "mb_box", box, "FLOAT_VECTOR", "INSTANCE"), "mb_rot", rot, "QUATERNION", "INSTANCE")
    pts = b.node("GeometryNodeInstancesToPoints", {"Instances": tagged}).outputs[0]
    boxes = b.node("GeometryNodeInstanceOnPoints", {
        "Points": pts, "Instance": b.node("GeometryNodeMeshCube", {"Size": (1, 1, 1)}).outputs[0],
        "Rotation": b.named("mb_rot", "QUATERNION"), "Scale": b.named("mb_box", "FLOAT_VECTOR")}).outputs[0]
    shown = b.index_switch("GEOMETRY", b.menu(["Object", "Bounding Box", "Points", "Off"], g["Viewport"]),
                           [geo, boxes, pts, None])
    return b.switch("GEOMETRY", b.inp("GeometryNodeIsViewport"), geo, shown)


BUILDERS = {
    "motext": geometry_group("MB MoText", [
        S("Text", "STRING", "MOBLEND"),
        S("Font", "FONT"),
        S("Size", "FLOAT", 1.0, 0.0),
        S("Depth", "FLOAT", 0.2, 0.0, desc="Extrusion depth"),
        S("Split", "MENU", desc="Which parts effectors move: characters, words, lines or the whole"),
        S("Align", "MENU"),
        S("Character Spacing", "FLOAT", 1.0), S("Word Spacing", "FLOAT", 1.0), S("Line Spacing", "FLOAT", 1.0),
        S("Upright", "BOOL", True, desc="Stand the text up facing front (-Y), like C4D MoText"),
        S("Material", "MATERIAL"),
    ], _motext, {"Split": "Characters", "Align": "Center"}),
    "sweep": geometry_group("MB Sweep", [
        S("Path", "OBJECT", desc="Curve to sweep along"),
        S("Profile", "OBJECT", desc="Optional profile curve; a circle is used when empty"),
        S("Radius", "FLOAT", 0.1, 0.0, subtype="DISTANCE"),
        S("Sides", "INT", 16, 3, 512),
        S("Start", "FLOAT", 0.0, 0.0, 1.0, "FACTOR", "Animate Start/End to grow the sweep"),
        S("End", "FLOAT", 1.0, 0.0, 1.0, "FACTOR"),
        S("Twist", "FLOAT", 0.0, subtype="ANGLE"),
        S("End Scale", "FLOAT", 1.0, 0.0, desc="Taper toward the end"),
        S("Path Resolution", "INT", 128, 2, 100000),
        S("Fill Caps", "BOOL", True),
        S("Material", "MATERIAL"),
    ], _sweep),
    "fracture": geometry_group("MB Fracture", [
        S("Mode", "MENU", desc="Islands: each loose part (or Voronoi piece). Polygons: every face flies alone"),
        S("Colorize", "BOOL", False, desc="Give every piece its own random MoGraph color"),
        S("Color Seed", "INT", 0),
    ], _fracture, {"Mode": "Islands"}),
    "volume": geometry_group("MB Volume Builder", [
        S("Add", "COLLECTION", desc="Objects merged into the volume"),
        S("Subtract", "COLLECTION", desc="Objects carved out of it"),
        S("Voxel Size", "FLOAT", 0.05, 0.002, subtype="DISTANCE", desc="Smaller = more detail, slower"),
        S("Smooth", "INT", 0, 0, 50, desc="Mean-filter passes (soft blending)"),
        S("Fillet", "INT", 0, 0, 50, desc="Rounds concave creases"),
        S("Offset", "FLOAT", 0.0, subtype="DISTANCE", desc="Grow (+) or shrink (-) the surface"),
        S("Adaptivity", "FLOAT", 0.0, 0.0, 1.0, "FACTOR", "Fewer polygons on flat areas"),
        S("Material", "MATERIAL"),
    ], _volume),
    "loft": geometry_group("MB Loft", [
        S("Points", "INT", 32, 3, 4096, desc="Samples around each profile"),
        S("Rows", "INT", 32, 2, 4096, desc="Samples along the loft"),
        S("Smooth", "BOOL", True, desc="Curve smoothly through the profiles (off = straight between them)"),
        S("Caps", "BOOL", True, desc="Close the ends of closed profiles"),
        S("Flip", "BOOL", False, desc="Flip normals"),
        S("Material", "MATERIAL"),
    ], _loft),
    "display": geometry_group("MB Display", [
        S("Viewport", "MENU", desc="Viewport only: Object, Bounding Box, Points or Off (renders always show clones)"),
    ], _display, {"Viewport": "Object"}),
    "tracer": geometry_group("MB Tracer", [
        S("Mode", "MENU", desc="Connect: a tube through the clones. Trails: each clone leaves a trail over time"),
        S("Radius", "FLOAT", 0.04, 0.0, subtype="DISTANCE"),
        S("Sides", "INT", 8, 3, 128),
        S("Closed", "BOOL", False, desc="Connect mode: close the loop"),
        S("Length", "INT", 24, 1, 10000, desc="Trails mode: frames a trail lasts"),
        S("Taper", "FLOAT", 1.0, 0.0, 1.0, "FACTOR", "Trails mode: how much old trail thins out"),
        S("World Space", "BOOL", True, desc="Trails mode: also trace the object's own movement"),
        S("Keep Clones", "BOOL", True),
        S("Material", "MATERIAL"),
    ], _tracer, {"Mode": "Connect"}),
}
