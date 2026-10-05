"""Generators: MoText, Sweep, Fracture, Tracer, Volume Builder (each O(output elements) unless noted)."""

import math

from ..catalog import COLOR_ATTR
from .util import S, geometry_group, geometry_socket, out, socket_by_id
from .core import init_color, split_centered

TEXT_PARTS = {"Characters": "mb_char", "Words": "mb_word", "Lines": "mb_line"}


def _solid(b, flat, depth):
    """Closed solid from a flat mesh pushed `depth` along +Z. Extruding as one region (not per face) moves the
    faces up and leaves the bottom open, so a flipped copy closes it; welding joins the two. O(faces)."""
    top = b.node("GeometryNodeExtrudeMesh", {"Mesh": flat, "Offset": (0, 0, 1), "Offset Scale": depth,
                                             "Individual": False}, mode="FACES").outputs[0]
    back = b.node("GeometryNodeFlipFaces", {"Mesh": flat}).outputs[0]
    return b.node("GeometryNodeMergeByDistance", {"Geometry": b.join(back, top), "Distance": 1e-5}).outputs[0]


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
    solid = _solid(b, flat, g["Depth"])
    sharp = b.math("GREATER_THAN", b.inp("GeometryNodeInputMeshEdgeAngle"), math.radians(30))
    beveled = b.node("GeometryNodeMeshBevel", {"Mesh": solid, "Selection": sharp, "Offset": g["Bevel"],
                                               "Segments": g["Bevel Segments"]}).outputs[0]
    solid = b.switch("GEOMETRY", b.math("GREATER_THAN", g["Bevel"], 0.0), solid, beveled)
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


def _points_of(b, geo):
    """Every point of realized geometry: mesh vertices, curve points and point clouds. O(points)."""
    parts = b.node("GeometryNodeSeparateComponents", {"Geometry": geo})
    return b.join(b.node("GeometryNodeMeshToPoints", {"Mesh": out(parts, "Mesh")}, mode="VERTICES").outputs[0],
                  b.node("GeometryNodeCurveToPoints", {"Curve": out(parts, "Curve")}, mode="EVALUATED").outputs[0],
                  out(parts, "Point Cloud"))


def _tracer(b, g):
    """Trace this object's clones, or (Trace Object set) another object's points, vertices or particles."""
    own = b.node("GeometryNodeInstancesToPoints", {"Instances": g["Geometry"]}).outputs[0]
    other = _points_of(b, b.object_geometry(g["Trace Object"]))
    count = out(b.node("GeometryNodeAttributeDomainSize", {"Geometry": other}, component="POINTCLOUD"),
                "Point Count")
    pts = b.switch("GEOMETRY", b.math("GREATER_THAN", count, 0.0), own, other)
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


def _fracture_objects(b, g):
    """C4D Fracture 'Off': every object of a collection is one clone, left where it is. O(objects)."""
    inst = b.node("GeometryNodeCollectionInfo", {"Collection": g["Collection"], "Separate Children": True,
                                                 "Reset Children": False}, transform_space="RELATIVE").outputs[0]
    return init_color(b, inst)


def _moinstance(b, g):
    """C4D MoInstance: a trail of instances of Object at this object's recent positions (History Depth frames,
    one every Step frames). Simulation: O(History Depth) per frame; play from the start frame."""
    sim_in, sim_out = b.node("GeometryNodeSimulationInput"), b.node("GeometryNodeSimulationOutput")
    sim_in.pair_with_output(sim_out)
    history = sim_in.outputs[1]
    world = out(b.node("GeometryNodeObjectInfo", {"Object": b.inp("GeometryNodeSelfObject")},
                       transform_space="ORIGINAL"), "Transform")
    aged = b.store(history, "mb_age", b.math("ADD", b.named("mb_age", "INT"), 1.0), "INT", "POINT")
    expired = b.math("GREATER_THAN", b.named("mb_age", "INT"),
                     b.math("SUBTRACT", b.math("MULTIPLY", g["History Depth"], g["Step"]), 1.0))
    aged = b.node("GeometryNodeDeleteGeometry", {"Geometry": aged, "Selection": expired}, domain="POINT").outputs[0]
    frame = b.inp("GeometryNodeInputSceneTime", "Frame")
    due = b.math("LESS_THAN", b.math("FLOORED_MODULO", frame, b.at_least(g["Step"])), 0.5)
    fresh = b.store(b.store(_point(b), "mb_m", world, "FLOAT4X4", "POINT"), "mb_age", 0, "INT", "POINT")
    fresh = b.node("GeometryNodeDeleteGeometry", {"Geometry": fresh, "Selection": b.bool_not(due)},
                   domain="POINT").outputs[0]
    b.link(b.join(aged, fresh), sim_out.inputs["Geometry"])
    trail = sim_out.outputs[0]
    shape = out(b.node("GeometryNodeObjectInfo", {"Object": g["Object"], "As Instance": True},
                       transform_space="ORIGINAL"), "Geometry")
    inst = b.node("GeometryNodeInstanceOnPoints", {"Points": trail, "Instance": shape}).outputs[0]
    # Recorded world transforms, seen from where this object is now.
    inv = b.node("FunctionNodeInvertMatrix", {"Matrix": world}).outputs["Matrix"]
    local = b.node("FunctionNodeMatrixMultiply", {0: inv, 1: b.named("mb_m", "FLOAT4X4")}).outputs[0]
    inst = b.node("GeometryNodeSetInstanceTransform", {"Instances": inst, "Transform": local}).outputs[0]
    return init_color(b, inst)


def _point(b):
    return b.node("GeometryNodePoints", {"Count": 1}).outputs[0]


def _mospline(b, g):
    """C4D MoSpline. Simple: Segments curves of Steps points, each step turned by Angle/Steps (curls, spirals,
    flowers). Spline: segments copied from a source curve. Start/End trim (growth), Width makes tubes."""
    segments, steps = g["Segments"], b.at_least(g["Steps"], 2.0)
    i = b.index()
    seg = b.math("FLOOR", b.math("DIVIDE", i, steps))
    k = b.math("FLOORED_MODULO", i, steps)
    turn = b.combine(z=b.math("MULTIPLY", seg, b.math("DIVIDE", 2 * math.pi, b.at_least(segments))))
    start = b.node("FunctionNodeRotateVector", {"Vector": b.node("FunctionNodeRotateVector", {
        "Vector": (0, 0, 1), "Rotation": b.euler_to_rot(b.combine(x=g["Spread"]))}).outputs[0],
        "Rotation": b.euler_to_rot(turn)}).outputs[0]
    step = b.node("FunctionNodeRotateVector", {"Vector": b.vmath("SCALE", start, scale=b.math(
        "DIVIDE", g["Length"], steps)), "Rotation": b.euler_to_rot(b.vmath("SCALE", g["Angle"], scale=b.math(
            "DIVIDE", k, steps)))}).outputs[0]
    pts = b.node("GeometryNodePoints", {"Count": b.math("MULTIPLY", segments, steps)}).outputs[0]
    walk = b.node("GeometryNodeAccumulateField", {"Value": step, "Group ID": seg}, data_type="FLOAT_VECTOR",
                  domain="POINT")
    pts = b.node("GeometryNodeSetPosition", {"Geometry": pts, "Position": out(walk, "Trailing")}).outputs[0]
    simple = b.node("GeometryNodePointsToCurves", {"Points": pts, "Curve Group ID": seg, "Weight": k}).outputs[0]
    source = b.object_geometry(g["Spline"])
    copies = b.node("GeometryNodeInstanceOnPoints", {
        "Points": b.node("GeometryNodePoints", {"Count": segments}).outputs[0], "Instance": source,
        "Rotation": b.euler_to_rot(b.combine(z=b.math("MULTIPLY", b.index(), b.math(
            "DIVIDE", 2 * math.pi, b.at_least(segments)))))}).outputs[0]
    from_spline = b.node("GeometryNodeRealizeInstances", {"Geometry": copies}).outputs[0]
    crv = b.index_switch("GEOMETRY", b.menu(["Simple", "Spline"], g["Mode"]), [simple, from_spline])
    lo = b.math("FRACT", g["Offset"])
    crv = b.node("GeometryNodeTrimCurve", {"Curve": crv, "Start": b.math("MINIMUM", b.math("ADD", g["Start"], lo), 1.0),
                                           "End": b.math("MINIMUM", b.math("ADD", g["End"], lo), 1.0)},
                 mode="FACTOR").outputs[0]
    profile = b.node("GeometryNodeCurvePrimitiveCircle", {"Resolution": 8, "Radius": g["Width"]},
                     mode="RADIUS").outputs[0]
    along = out(b.node("GeometryNodeSplineParameter"), "Factor")
    tube = b.node("GeometryNodeCurveToMesh", {"Curve": crv, "Profile Curve": profile, "Fill Caps": True,
                                              "Scale": b.mix("FLOAT", along, 1.0, g["End Width"])}).outputs[0]
    tube = b.node("GeometryNodeSetMaterial", {"Geometry": tube, "Material": g["Material"]}).outputs[0]
    return b.switch("GEOMETRY", b.math("GREATER_THAN", g["Width"], 0.0), crv, tube)


def _slab(b, curves, half=0.5):
    """Closed slab (z -half..half) from filled XY curves, for 2D booleans. O(curve points)."""
    flat = b.node("GeometryNodeFillCurve", {"Curve": b.node("GeometryNodeRealizeInstances",
                                                            {"Geometry": curves}).outputs[0]}).outputs[0]
    flat = b.node("GeometryNodeTransform", {"Geometry": flat,
                                            "Translation": b.combine(z=b.math("MULTIPLY", half, -1.0))}).outputs[0]
    return _solid(b, flat, b.math("MULTIPLY", half, 2.0))


def _spline_mask(b, g):
    """C4D Spline Mask: 2D boolean of the closed curves in a collection (XY plane), as curves or a filled mesh.
    The shapes are folded one at a time (first op second op third ...): Union, Intersection, or Subtract
    (the first curve by name minus the rest). Exact mesh booleans on extruded slabs: O(curves x boolean).

    Slabs get slightly different thicknesses (coplanar faces are degenerate for booleans), so no face lies
    at z = 0: a thin slice there, cut from the result, is exactly the 2D region."""
    curves = b.node("GeometryNodeCollectionInfo", {"Collection": g["Collection"], "Separate Children": True,
                                                   "Reset Children": False}, transform_space="RELATIVE").outputs[0]

    def slab_of(k):
        only = b.node("GeometryNodeDeleteGeometry", {"Geometry": curves, "Selection": b.bool_not(
            b.compare(b.index(), k))}, domain="INSTANCE").outputs[0]
        return _slab(b, only, b.math("ADD", 0.5, b.math("MULTIPLY", k, 0.0137)))

    mode = b.menu(["Union", "Intersection", "Subtract"], g["Mode"])
    rep_in, rep_out = b.node("GeometryNodeRepeatInput"), b.node("GeometryNodeRepeatOutput")
    rep_in.pair_with_output(rep_out)
    b.set(rep_in, "Iterations", b.at_least(b.math("SUBTRACT", b.instance_count(curves), 1.0), 0.0))
    b.link(slab_of(0), geometry_socket(rep_in.inputs))
    acc = geometry_socket(rep_in.outputs)
    nxt = slab_of(b.math("ADD", out(rep_in, "Iteration"), 1.0))
    def boolean(op):
        n = b.node("GeometryNodeMeshBoolean", operation=op, solver="EXACT")
        operands = socket_by_id(n.inputs, "Mesh 2")
        if op == "DIFFERENCE":
            b.link(acc, socket_by_id(n.inputs, "Mesh 1"))
            b.link(nxt, operands)
        else:  # Union / Intersect take every operand on the multi-input Mesh 2
            b.link(acc, operands)
            b.link(nxt, operands)
        return out(n, "Mesh")

    folded = [boolean(op) for op in ("UNION", "INTERSECT", "DIFFERENCE")]
    b.link(b.index_switch("GEOMETRY", mode, folded), geometry_socket(rep_out.inputs))
    solid = geometry_socket(rep_out.outputs)
    box = b.node("GeometryNodeBoundBox", {"Geometry": solid})
    bx, by, _ = b.separate(b.vmath("SUBTRACT", out(box, "Max"), out(box, "Min")))
    cx, cy, _ = b.separate(b.vmath("SCALE", b.vmath("ADD", out(box, "Max"), out(box, "Min")), scale=0.5))
    knife = b.node("GeometryNodeMeshCube", {"Size": b.combine(b.math("ADD", bx, 1.0), b.math("ADD", by, 1.0), 0.002)})
    knife = b.node("GeometryNodeTransform", {"Geometry": knife.outputs[0], "Translation": b.combine(cx, cy)}).outputs[0]
    cut = b.node("GeometryNodeMeshBoolean", operation="INTERSECT", solver="EXACT")
    b.link(solid, socket_by_id(cut.inputs, "Mesh 2"))
    b.link(knife, socket_by_id(cut.inputs, "Mesh 2"))
    _, _, nz = b.separate(b.inp("GeometryNodeInputNormal"))
    top = b.node("GeometryNodeDeleteGeometry", {"Geometry": out(cut, "Mesh"),
                                                "Selection": b.math("LESS_THAN", nz, 0.99)}, domain="FACE").outputs[0]
    fill = b.node("GeometryNodeTransform", {"Geometry": top, "Translation": (0, 0, -0.001)}).outputs[0]
    border = b.math("LESS_THAN", out(b.node("GeometryNodeInputMeshEdgeNeighbors"), "Face Count"), 1.5)
    outline = b.node("GeometryNodeMeshToCurve", {"Mesh": fill, "Selection": border}).outputs[0]
    return b.index_switch("GEOMETRY", b.menu(["Curve", "Fill"], g["Output"]), [outline, fill])


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
        S("Bevel", "FLOAT", 0.0, 0.0, subtype="DISTANCE", desc="Round the extruded letters' edges"),
        S("Bevel Segments", "INT", 2, 1, 16),
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
    "fracture_objects": geometry_group("MB Fracture Objects", [
        S("Collection", "COLLECTION", desc="Each object becomes one clone, left where it is"),
    ], _fracture_objects),
    "moinstance": geometry_group("MB MoInstance", [
        S("Object", "OBJECT", desc="Object instanced along this object's path"),
        S("History Depth", "INT", 20, 1, 10000, desc="How many past positions to keep"),
        S("Step", "INT", 1, 1, 1000, desc="Record one position every Step frames"),
    ], _moinstance),
    "mospline": geometry_group("MB MoSpline", [
        S("Mode", "MENU", desc="Simple: generated curls. Spline: copies of a source curve"),
        S("Segments", "INT", 1, 1, 1000), S("Steps", "INT", 64, 2, 10000),
        S("Length", "FLOAT", 4.0, 0.0, subtype="DISTANCE"),
        S("Angle", "VECTOR", (0, 0, 0), subtype="EULER", desc="Total turn along each segment (curls, spirals)"),
        S("Spread", "FLOAT", 0.0, subtype="ANGLE", desc="Tilt segments outward (flower shapes)"),
        S("Spline", "OBJECT", desc="Spline mode: source curve"),
        S("Start", "FLOAT", 0.0, 0.0, 1.0, "FACTOR"), S("End", "FLOAT", 1.0, 0.0, 1.0, "FACTOR"),
        S("Offset", "FLOAT", 0.0, desc="Slide the visible part along the curve"),
        S("Width", "FLOAT", 0.0, 0.0, subtype="DISTANCE", desc="Above 0: a tube instead of a curve"),
        S("End Width", "FLOAT", 1.0, 0.0, desc="Tube taper toward the end"),
        S("Material", "MATERIAL"),
    ], _mospline, {"Mode": "Simple"}),
    "spline_mask": geometry_group("MB Spline Mask", [
        S("Collection", "COLLECTION", desc="Closed curves in the XY plane"),
        S("Mode", "MENU", desc="Union, Intersection, or Subtract (first by name minus the rest)"),
        S("Output", "MENU", desc="Curves, or a filled mesh"),
    ], _spline_mask, {"Mode": "Union", "Output": "Curve"}),
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
        S("Trace Object", "OBJECT", desc="Trace this object's points/vertices instead of the clones"),
        S("Keep Clones", "BOOL", True),
        S("Material", "MATERIAL"),
    ], _tracer, {"Mode": "Connect"}),
}
