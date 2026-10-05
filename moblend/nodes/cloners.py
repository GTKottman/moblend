"""Cloner node groups (C4D Cloner modes). Each mode builds points carrying per-clone rotation and scale,
then the shared instancer clones the collection onto them.

Every mode is O(clones) per evaluation; Object mode adds O(target elements) (Volume: O(voxels)).
"""

import math

from .core import CLONE_ORDERS, instancer
from .util import S, geometry_group, out

COMMON = [S("Collection", "COLLECTION", desc="Children of this collection are cloned"),
          S("Order", "MENU", desc="Iterate through children, pick randomly, or Blend between them"),
          S("Seed", "INT", 0)]
STEP_MODES = ("Per Step", "End Point")


def _cloner(name, inputs, body, menus=None):
    """Cloner group: `body(b, g) -> (points, rotation|None, scale|None)`, then the shared instancer.
    The group's Geometry input (the cloner's own mesh) is the per-clone data (selection / weight tags)."""
    def instance(b, g):
        points, rotation, scale = body(b, g)
        return b.group(instancer(), {"Points": points, "Collection": g["Collection"], "Seed": g["Seed"],
                                     "Order": g["Order"], "Rotation": rotation, "Scale": scale,
                                     "Data": g["Geometry"]}).outputs[0]
    return geometry_group(name, inputs + COMMON, instance, {"Order": CLONE_ORDERS[0], **(menus or {})})


def _points(b, count, position):
    return b.node("GeometryNodePoints", {"Count": count, "Position": position}).outputs[0]


def _end_point_mode(b, g):
    """True in End Point mode. Build once per group: one menu input must drive a single Menu Switch."""
    return b.compare(b.menu(STEP_MODES, g["Mode"]), 1)


def _end_point(b, is_end, value, count):
    """Per Step: `value` is the step. End Point: `value` is the whole span, so the step is value/(count-1)."""
    return b.mix("FLOAT", is_end, value, b.math("DIVIDE", value, b.steps(count)))


def _keep(b, geo, attrs):
    """Store per-point fields as attributes so they survive deleting points; returns (geo, named readers)."""
    readers = []
    for name, value, dtype in attrs:
        geo = b.store(geo, name, value, dtype, "POINT")
        readers.append(b.named(name, dtype))
    return geo, readers


# ---------------------------------------------------------------- Linear

def _linear(b, g):
    """C4D Linear: Offset per step (or End Point span) x Amount x Step Size, curled by Step Curve
    (Cumulative: the turn grows every step, giving arcs and spirals; Single Value: one fixed turn).
    Start Offset skips the first clones. Positions are a running sum over clones: O(n)."""
    start = g["Start Offset"]
    total = b.math("ADD", g["Count"], start)
    amount = g["Amount"]
    sx, sy, sz = b.separate(g["Offset"])
    is_end = _end_point_mode(b, g)
    step = b.combine(*(_end_point(b, is_end, c, g["Count"]) for c in (sx, sy, sz)))
    step = b.vmath("SCALE", step, scale=b.math("MULTIPLY", amount, g["Step Size"]))
    idx = b.index()
    turns = b.mix("FLOAT", b.compare(b.menu(["Cumulative", "Single Value"], g["Step Mode"]), 1), idx, 1.0)
    direction = b.node("FunctionNodeRotateVector", {"Vector": step, "Rotation": b.euler_to_rot(
        b.vmath("SCALE", g["Step Curve"], scale=turns))}).outputs[0]
    origin = _points(b, total, (0, 0, 0))
    walk = b.node("GeometryNodeAccumulateField", {"Value": direction}, data_type="FLOAT_VECTOR", domain="POINT")
    pts = b.node("GeometryNodeSetPosition", {"Geometry": origin, "Position": out(walk, "Trailing")}).outputs[0]
    rot = b.euler_to_rot(b.vmath("SCALE", g["Step Rotation"], scale=b.math("MULTIPLY", idx, amount)))
    grow = b.vmath("MULTIPLY_ADD", g["Scale Step"], b.math("MULTIPLY", idx, amount), (1, 1, 1))
    scale = b.vmath("SCALE", grow, scale=b.math("POWER", g["Step Scale"], idx))
    pts, (rot, scale) = _keep(b, pts, [("mb_rot", rot, "QUATERNION"), ("mb_scale", scale, "FLOAT_VECTOR")])
    pts = b.node("GeometryNodeDeleteGeometry", {"Geometry": pts, "Selection": b.math("LESS_THAN", b.index(), start)},
                 domain="POINT").outputs[0]
    return pts, rot, scale


# ---------------------------------------------------------------- Radial

def _radial(b, g):
    n = g["Count"]
    span = b.math("SUBTRACT", g["End Angle"], g["Start Angle"])
    full = b.math("GREATER_THAN", b.math("ABSOLUTE", span), 2 * math.pi - 1e-3)
    # A full circle spaces by span/n (last clone must not overlap the first); an arc by span/(n-1).
    div = b.mix("FLOAT", full, b.steps(n), n)
    step = b.math("DIVIDE", span, div)
    jitter = b.math("MULTIPLY", b.rand("FLOAT", -0.5, 0.5, seed=g["Seed"]),
                    b.math("MULTIPLY", g["Offset Variation"], step))
    a = b.math("ADD", b.math("ADD", g["Start Angle"], g["Offset"]),
               b.math("ADD", b.math("MULTIPLY", b.index(), step), jitter))
    c = b.math("MULTIPLY", b.math("COSINE", a), g["Radius"])
    s = b.math("MULTIPLY", b.math("SINE", a), g["Radius"])
    plane = b.menu(["XY", "XZ", "YZ"], g["Plane"])
    pos = b.index_switch("VECTOR", plane, [b.combine(c, s), b.combine(c, 0.0, s), b.combine(0.0, c, s)])
    eul = b.index_switch("VECTOR", plane, [b.combine(z=a), b.combine(y=b.math("MULTIPLY", a, -1.0)),
                                           b.combine(x=a)])
    return _points(b, n, pos), b.euler_to_rot(b.vmath("SCALE", eul, scale=g["Align"])), None


# ---------------------------------------------------------------- Grid

def _grid(b, g):
    cx, cy, cz = g["Count X"], g["Count Y"], g["Count Z"]
    is_end = _end_point_mode(b, g)
    sx, sy, sz = (_end_point(b, is_end, c, n) for c, n in zip(b.separate(g["Spacing"]), (cx, cy, cz), strict=True))
    i = b.index()
    ix = b.math("FLOORED_MODULO", i, cx)
    iy = b.math("FLOORED_MODULO", b.math("FLOOR", b.math("DIVIDE", i, cx)), cy)
    iz = b.math("FLOOR", b.math("DIVIDE", i, b.math("MULTIPLY", cx, cy)))

    def axis(ii, count, spacing):
        """Centered position along one axis, and the same in -1..1 units for shape tests."""
        half = b.math("MULTIPLY", b.math("SUBTRACT", count, 1.0), 0.5)
        rel = b.math("SUBTRACT", ii, half)
        return b.math("MULTIPLY", rel, spacing), b.math("DIVIDE", rel, b.at_least(half, 0.5))

    (px, ux), (py, uy), (pz, uz) = axis(ix, cx, sx), axis(iy, cy, sy), axis(iz, cz, sz)
    odd_row = b.math("FLOORED_MODULO", iy, 2.0)
    hx = b.math("MULTIPLY", b.math("MULTIPLY", odd_row, g["Honeycomb"]), b.math("MULTIPLY", sx, 0.5))
    total = b.math("MULTIPLY", b.math("MULTIPLY", cx, cy), cz)
    pos = b.combine(b.math("ADD", px, hx), py, pz)
    pts = _points(b, total, pos)
    au, av, aw = b.separate(b.vmath("ABSOLUTE", b.combine(ux, uy, uz)))
    norms = {"Cube": b.math("MAXIMUM", b.math("MAXIMUM", au, av), aw),
             "Sphere": b.vmath("LENGTH", b.combine(ux, uy, uz)),
             "Cylinder": b.math("MAXIMUM", b.vmath("LENGTH", b.combine(ux, uy)), aw)}
    shape = b.menu(list(norms) + ["Object"], g["Shape"])
    norm = b.index_switch("FLOAT", shape, list(norms.values()) + [0.0])
    # Outside the shape, or (Fill < 1) inside its hollow core.
    drop = b.math("MAXIMUM", b.math("GREATER_THAN", norm, 1.05),
                  b.math("LESS_THAN", norm, b.math("SUBTRACT", 0.999, g["Fill"])))
    sdf = b.node("GeometryNodeMeshToSDFGrid", {"Mesh": b.object_geometry(g["Object"]), "Voxel Size": 0.05,
                                               "Band Width": 3}).outputs[0]
    outside = b.node("GeometryNodeSampleGrid", {"Grid": sdf, "Position": b.position()}, data_type="FLOAT").outputs[0]
    drop = b.mix("FLOAT", b.compare(shape, 3), drop, b.math("GREATER_THAN", outside, 0.0))
    pts = b.node("GeometryNodeDeleteGeometry", {"Geometry": pts, "Selection": b.math("GREATER_THAN", drop, 0.5)},
                 domain="POINT").outputs[0]
    return pts, None, None


# ---------------------------------------------------------------- Honeycomb

def _honeycomb(b, g):
    """C4D Honeycomb Array: rows offset by Offset (fraction of a step) in the chosen direction, with optional
    random variation, in a square or circle, on the chosen plane."""
    cw, ch = g["Count Width"], g["Count Height"]
    is_end = _end_point_mode(b, g)
    sw, sh = (_end_point(b, is_end, s, n) for s, n in ((g["Size Width"], cw), (g["Size Height"], ch)))
    i = b.index()
    iw = b.math("FLOORED_MODULO", i, cw)
    ih = b.math("FLOOR", b.math("DIVIDE", i, cw))
    u = b.math("MULTIPLY", b.math("SUBTRACT", iw, b.math("MULTIPLY", b.math("SUBTRACT", cw, 1.0), 0.5)), sw)
    v = b.math("MULTIPLY", b.math("SUBTRACT", ih, b.math("MULTIPLY", b.math("SUBTRACT", ch, 1.0), 0.5)), sh)
    by_width = b.compare(b.menu(["Width", "Height"], g["Offset Direction"]), 0)
    line = b.mix("FLOAT", by_width, iw, ih)  # which index decides "every other row"
    shifted = b.math("MULTIPLY", b.math("FLOORED_MODULO", line, 2.0),
                     b.math("ADD", g["Offset"], b.math("MULTIPLY", g["Offset Variation"],
                                                         b.rand("FLOAT", -0.5, 0.5, seed=g["Seed"]))))
    perpendicular = b.math("MULTIPLY", g["Perpendicular Variation"], b.rand("FLOAT", -0.5, 0.5, seed=b.math(
        "ADD", g["Seed"], 1.0)))
    # Width: odd rows slide sideways (u); Height: odd columns slide up (v). Variation goes the other way.
    u = b.math("ADD", u, b.mix("FLOAT", by_width, b.math("MULTIPLY", perpendicular, sw),
                               b.math("MULTIPLY", shifted, sw)))
    v = b.math("ADD", v, b.mix("FLOAT", by_width, b.math("MULTIPLY", shifted, sh),
                               b.math("MULTIPLY", perpendicular, sh)))
    plane = b.menu(["XY", "XZ", "YZ"], g["Orientation"])
    pos = b.index_switch("VECTOR", plane, [b.combine(u, v), b.combine(u, 0.0, v), b.combine(0.0, u, v)])
    pts = _points(b, b.math("MULTIPLY", cw, ch), pos)
    half_w = b.at_least(b.math("MULTIPLY", b.math("MULTIPLY", b.math("SUBTRACT", cw, 1.0), 0.5), sw), 1e-4)
    half_h = b.at_least(b.math("MULTIPLY", b.math("MULTIPLY", b.math("SUBTRACT", ch, 1.0), 0.5), sh), 1e-4)
    ellipse = b.vmath("LENGTH", b.combine(b.math("DIVIDE", u, half_w), b.math("DIVIDE", v, half_h)))
    circle = b.compare(b.menu(["Square", "Circle"], g["Form"]), 1)
    drop = b.math("MULTIPLY", circle, b.math("GREATER_THAN", ellipse, 1.05))
    pts = b.node("GeometryNodeDeleteGeometry", {"Geometry": pts, "Selection": drop}, domain="POINT").outputs[0]
    return pts, None, None


# ---------------------------------------------------------------- Object

OBJECT_MODES = ("Vertices", "Edges", "Faces", "Surface", "Volume", "Axis", "Instances")


def _object(b, g):
    """Clones on a target: its vertices, edge midpoints, face centers, random surface or volume points,
    its origin, or the clones of another cloner/Matrix (taking their rotation and scale)."""
    info = b.node("GeometryNodeObjectInfo", {"Object": g["Object"]}, transform_space="RELATIVE")
    raw = out(info, "Geometry")
    geo = b.node("GeometryNodeRealizeInstances", {"Geometry": raw}).outputs[0]
    sel_attr = b.node("GeometryNodeInputNamedAttribute", {"Name": g["Selection"]}, data_type="FLOAT")
    selected = b.switch("BOOLEAN", out(sel_attr, "Exists"), True,
                        b.math("GREATER_THAN", out(sel_attr, "Attribute"), 0.5))
    nrm = b.inp("GeometryNodeInputNormal")
    area = b.math("SQRT", b.inp("GeometryNodeInputMeshFaceArea"))

    def from_mesh(domain, mode, direction, size=1.0):
        stored = b.store(geo, "mb_n", direction, "FLOAT_VECTOR", domain)
        stored = b.store(stored, "mb_s", size, "FLOAT", domain)
        return b.node("GeometryNodeMeshToPoints", {"Mesh": stored, "Selection": selected}, mode=mode).outputs[0]

    ends = b.node("GeometryNodeInputMeshEdgeVertices")
    edge_dir = b.vmath("NORMALIZE", b.vmath("SUBTRACT", out(ends, "Position 2"), out(ends, "Position 1")))
    bounds = b.node("GeometryNodeBoundBox", {"Geometry": geo})
    box = b.vmath("SUBTRACT", out(bounds, "Max"), out(bounds, "Min"))
    bx, by, bz = b.separate(box)
    count = g["Count"]
    totals = b.node("GeometryNodeAttributeStatistic", {"Geometry": geo,
                                                       "Attribute": b.inp("GeometryNodeInputMeshFaceArea")},
                    data_type="FLOAT", domain="FACE")
    scatter = b.node("GeometryNodeDistributePointsOnFaces", {
        "Mesh": geo, "Selection": selected, "Seed": g["Seed"],
        "Density": b.math("DIVIDE", count, b.at_least(out(totals, "Sum"), 1e-6))}, distribute_method="RANDOM")
    surface = b.store(out(scatter, "Points"), "mb_n", out(scatter, "Normal"), "FLOAT_VECTOR", "POINT")
    volume = b.node("GeometryNodeMeshToVolume", {"Mesh": geo, "Density": 1.0})
    volume = b.node("GeometryNodeDistributePointsInVolume", {
        "Volume": volume.outputs[0], "Seed": g["Seed"],
        "Density": b.math("DIVIDE", count, b.at_least(b.math("MULTIPLY", b.math("MULTIPLY", bx, by), bz), 1e-6))})
    volume = b.store(volume.outputs[0], "mb_n", (0, 0, 1), "FLOAT_VECTOR", "POINT")
    axis = b.store(_points(b, 1, out(info, "Location")), "mb_n", (0, 0, 1), "FLOAT_VECTOR", "POINT")
    _, inst_rot, inst_scale = b.split_transform(b.true_transform())
    tagged = b.node("GeometryNodeStoreNamedAttribute", {"Geometry": raw, "Name": "mb_r", "Value": inst_rot},
                    data_type="QUATERNION", domain="INSTANCE").outputs[0]
    tagged = b.store(tagged, "mb_v", inst_scale, "FLOAT_VECTOR", "INSTANCE")
    inst = b.node("GeometryNodeInstancesToPoints", {"Instances": tagged}).outputs[0]
    mode = b.menu(OBJECT_MODES, g["Distribution"])
    pts = b.index_switch("GEOMETRY", mode, [
        from_mesh("POINT", "VERTICES", nrm), from_mesh("EDGE", "EDGES", edge_dir),
        from_mesh("FACE", "FACES", nrm, area), surface, volume, axis, inst])
    aligned = b.node("FunctionNodeAlignRotationToVector",
                     {"Factor": g["Align"], "Vector": b.named("mb_n", "FLOAT_VECTOR")}, axis="Z").outputs[0]
    up = g["Up Vector"]
    has_up = b.math("GREATER_THAN", b.vmath("LENGTH", up), 0.0)
    aligned = b.node("FunctionNodeAlignRotationToVector", {"Rotation": aligned, "Factor": has_up, "Vector": up},
                     axis="Y", pivot_axis="Z").outputs[0]  # spin around the normal so Y follows Up Vector
    instances_mode = b.compare(mode, OBJECT_MODES.index("Instances"))
    rot = b.mix("ROTATION", instances_mode, aligned, b.named("mb_r", "QUATERNION"))
    size = b.mix("FLOAT", g["Scale by Area"], 1.0, b.named("mb_s", "FLOAT"))
    scale = b.mix("VECTOR", instances_mode, b.combine(size, size, size), b.named("mb_v", "FLOAT_VECTOR"))
    return pts, rot, scale


# ---------------------------------------------------------------- Spline

def _spline(b, g):
    crv = b.object_geometry(g["Curve"])
    cyclic = b.node("GeometryNodeSampleIndex", {"Geometry": crv, "Value": b.inp("GeometryNodeInputSplineCyclic"),
                                                "Index": 0}, data_type="BOOLEAN", domain="CURVE").outputs[0]
    n = g["Count"]
    div = b.mix("FLOAT", cyclic, b.steps(n), n)
    f = b.math("ADD", b.math("MULTIPLY", b.math("DIVIDE", b.index(), div), g["Spread"]), g["Offset"])
    # Wrap offsets outside [0, 1] but keep exactly 1.0 (the end of an open curve).
    f = b.mix("FLOAT", b.math("GREATER_THAN", f, 1.0001), f, b.math("FRACT", f))
    f = b.mix("FLOAT", b.math("LESS_THAN", f, 0.0), f, b.math("FRACT", f))
    smp = b.node("GeometryNodeSampleCurve", {"Curves": crv, "Factor": f}, mode="FACTOR", use_all_curves=True)
    follow = b.node("FunctionNodeAxesToRotation", {"Primary Axis": out(smp, "Tangent"),
                                                   "Secondary Axis": out(smp, "Normal")},
                    primary_axis="X", secondary_axis="Z").outputs[0]
    rot = b.mix("ROTATION", g["Align"], b.euler_to_rot((0, 0, 0)), follow)
    return _points(b, n, out(smp, "Position")), rot, None


MODE = S("Mode", "MENU", desc="Per Step: values are the distance between clones. End Point: the whole span")

BUILDERS = {
    "linear": _cloner("MB Cloner Linear", [
        S("Count", "INT", 5, 0, 100000),
        S("Offset", "VECTOR", (2.5, 0, 0), subtype="TRANSLATION", desc="Distance between clones (or span)"),
        MODE,
        S("Amount", "FLOAT", 1.0, desc="Scales the Offset, Step Rotation and Scale Step together"),
        S("Start Offset", "INT", 0, 0, desc="Skip this many clones at the start"),
        S("Step Rotation", "VECTOR", (0, 0, 0), subtype="EULER", desc="Rotation added per clone"),
        S("Step Scale", "FLOAT", 1.0, 0.0, desc="Scale multiplier per clone"),
        S("Scale Step", "VECTOR", (0, 0, 0), subtype="XYZ", desc="Scale added per clone (0.1 = +10% each)"),
        S("Step Size", "FLOAT", 1.0, desc="Multiplies the distance between clones"),
        S("Step Curve", "VECTOR", (0, 0, 0), subtype="EULER", desc="Turns the line per step (C4D Step Rotation)"),
        S("Step Mode", "MENU", desc="Cumulative: the turn grows every step (arcs, spirals). Single Value: once"),
    ], _linear, {"Mode": "Per Step", "Step Mode": "Cumulative"}),
    "radial": _cloner("MB Cloner Radial", [
        S("Count", "INT", 8, 0, 100000),
        S("Radius", "FLOAT", 4.0, 0.0, subtype="DISTANCE"),
        S("Plane", "MENU"),
        S("Start Angle", "FLOAT", 0.0, subtype="ANGLE"),
        S("End Angle", "FLOAT", 2 * math.pi, subtype="ANGLE"),
        S("Offset", "FLOAT", 0.0, subtype="ANGLE", desc="Rotate every clone along the circle"),
        S("Offset Variation", "FLOAT", 0.0, 0.0, 1.0, "FACTOR", "Random offset, as a fraction of a step"),
        S("Align", "BOOL", True, desc="Rotate clones to face outward"),
    ], _radial, {"Plane": "XY"}),
    "grid": _cloner("MB Cloner Grid", [
        S("Count X", "INT", 3, 1, 1000), S("Count Y", "INT", 3, 1, 1000), S("Count Z", "INT", 3, 1, 1000),
        S("Spacing", "VECTOR", (2.5, 2.5, 2.5), subtype="TRANSLATION", desc="Step (or whole size in End Point)"),
        MODE,
        S("Shape", "MENU", desc="Fill a cube, sphere, cylinder or another object's volume"),
        S("Object", "OBJECT", desc="Shape Object: clones inside this closed mesh"),
        S("Fill", "FLOAT", 1.0, 0.0, 1.0, "FACTOR", "Below 1, only an outer shell of the shape is filled"),
        S("Honeycomb", "BOOL", False, desc="Offset every other row by half a step"),
    ], _grid, {"Shape": "Cube", "Mode": "Per Step"}),
    "honeycomb": _cloner("MB Cloner Honeycomb", [
        S("Count Width", "INT", 6, 1, 1000), S("Count Height", "INT", 6, 1, 1000),
        S("Size Width", "FLOAT", 2.0, 0.0, subtype="DISTANCE"),
        S("Size Height", "FLOAT", 1.75, 0.0, subtype="DISTANCE"),
        MODE,
        S("Orientation", "MENU", desc="Plane of the array"),
        S("Offset Direction", "MENU", desc="Shift alternate rows (Width) or columns (Height)"),
        S("Offset", "FLOAT", 0.5, 0.0, 1.0, "FACTOR", "Shift as a fraction of a step"),
        S("Offset Variation", "FLOAT", 0.0, 0.0, 1.0, "FACTOR"),
        S("Perpendicular Variation", "FLOAT", 0.0, 0.0, 1.0, "FACTOR"),
        S("Form", "MENU", desc="Square or circle outline"),
    ], _honeycomb, {"Mode": "Per Step", "Orientation": "XY", "Offset Direction": "Width", "Form": "Square"}),
    "object": _cloner("MB Cloner Object", [
        S("Object", "OBJECT", desc="Clone onto this object (or onto another cloner's clones)"),
        S("Distribution", "MENU"),
        S("Count", "INT", 50, 0, 1000000, desc="Surface / Volume: number of clones"),
        S("Selection", "STRING", "", desc="Vertex group or attribute limiting where clones go"),
        S("Align", "BOOL", True, desc="Point clones' Z along the surface normal (edge direction on Edges)"),
        S("Up Vector", "VECTOR", (0, 0, 0), subtype="XYZ", desc="Keep clones' Y toward this (0 = off)"),
        S("Scale by Area", "BOOL", False, desc="Faces: scale clones with the size of their polygon"),
    ], _object, {"Distribution": "Vertices"}),
    "spline": _cloner("MB Cloner Spline", [
        S("Curve", "OBJECT", desc="Curve object to clone along"),
        S("Count", "INT", 10, 0, 100000),
        S("Offset", "FLOAT", 0.0, desc="Slide clones along the curve (animate for motion)"),
        S("Spread", "FLOAT", 1.0, 0.0, 1.0, "FACTOR", "Fraction of the curve covered"),
        S("Align", "BOOL", True, desc="Rotate clones to follow the curve"),
    ], _spline),
}
