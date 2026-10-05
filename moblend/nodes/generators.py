"""Generators: MoText, Sweep, Fracture, Tracer, Volume Builder (each O(output elements) unless noted)."""

import math

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
    return b.group(split_centered(), {"Mesh": mesh, "Group": group}).outputs[0]


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
    mesh = b.node("GeometryNodeRealizeInstances", {"Geometry": g["Geometry"]}).outputs[0]
    polygons = b.compare(b.menu(["Islands", "Polygons"], g["Mode"]), 1)
    # Splitting every edge turns each face into its own island.
    split = b.node("GeometryNodeSplitEdges", {"Mesh": mesh}).outputs[0]
    island = out(b.node("GeometryNodeInputMeshIsland"), "Island Index")
    return b.group(split_centered(), {"Mesh": b.switch("GEOMETRY", polygons, mesh, split),
                                      "Group": island}).outputs[0]


def _tracer(b, g):
    pts = b.node("GeometryNodeInstancesToPoints", {"Instances": g["Geometry"]}).outputs[0]
    crv = b.node("GeometryNodePointsToCurves", {"Points": pts}).outputs[0]
    crv = b.node("GeometryNodeSetSplineCyclic", {"Geometry": crv, "Cyclic": g["Closed"]}).outputs[0]
    profile = b.node("GeometryNodeCurvePrimitiveCircle", {"Resolution": g["Sides"], "Radius": g["Radius"]},
                     mode="RADIUS").outputs[0]
    tube = b.node("GeometryNodeCurveToMesh", {"Curve": crv, "Profile Curve": profile}).outputs[0]
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
        S("Mode", "MENU", desc="Islands: each loose part. Polygons: every face flies alone"),
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
    "tracer": geometry_group("MB Tracer", [
        S("Radius", "FLOAT", 0.04, 0.0, subtype="DISTANCE"),
        S("Sides", "INT", 8, 3, 128),
        S("Closed", "BOOL", False),
        S("Keep Clones", "BOOL", True),
        S("Material", "MATERIAL"),
    ], _tracer),
}
