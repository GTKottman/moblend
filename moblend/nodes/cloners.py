"""Cloner node groups: each generates points, then instances the clone collection.

Every mode is O(clones) per evaluation (Object/Surface adds O(faces) to measure area).
"""

import math

from .util import S, geometry_group, out
from .core import instancer

COMMON = [S("Collection", "COLLECTION", desc="Children of this collection are cloned"),
          S("Order", "MENU", desc="Iterate through children or pick randomly"),
          S("Seed", "INT", 0)]


def _cloner(name, inputs, body, menus=None):
    """Cloner group: `body(b, g) -> (points, rotation|None, scale|None)`, then the shared instancer."""
    def instance(b, g):
        points, rotation, scale = body(b, g)
        return b.group(instancer(), {"Points": points, "Collection": g["Collection"], "Seed": g["Seed"],
                                     "Order": g["Order"], "Rotation": rotation, "Scale": scale}).outputs[0]
    return geometry_group(name, inputs + COMMON, instance, {"Order": "Iterate", **(menus or {})})


def _points(b, count, position):
    return b.node("GeometryNodePoints", {"Count": count, "Position": position}).outputs[0]


def _linear(b, g):
    line = b.node("GeometryNodeMeshLine", {"Count": g["Count"], "Offset": g["Offset"]},
                  mode="OFFSET", count_mode="TOTAL").outputs[0]
    pts = b.node("GeometryNodeMeshToPoints", {"Mesh": line}, mode="VERTICES").outputs[0]
    idx = b.index()
    rot = b.euler_to_rot(b.vmath("SCALE", g["Step Rotation"], scale=idx))
    return pts, rot, b.math("POWER", g["Step Scale"], idx)


def _radial(b, g):
    n = g["Count"]
    span = b.math("SUBTRACT", g["End Angle"], g["Start Angle"])
    full = b.math("GREATER_THAN", b.math("ABSOLUTE", span), 2 * math.pi - 1e-3)
    # A full circle spaces by span/n (last clone must not overlap the first); an arc by span/(n-1).
    div = b.mix("FLOAT", full, b.steps(n), n)
    a = b.math("ADD", g["Start Angle"], b.math("MULTIPLY", b.index(), b.math("DIVIDE", span, div)))
    c = b.math("MULTIPLY", b.math("COSINE", a), g["Radius"])
    s = b.math("MULTIPLY", b.math("SINE", a), g["Radius"])
    plane = b.menu(["XY", "XZ", "YZ"], g["Plane"])
    pos = b.index_switch("VECTOR", plane, [b.combine(c, s), b.combine(c, 0.0, s), b.combine(0.0, c, s)])
    eul = b.index_switch("VECTOR", plane, [b.combine(z=a), b.combine(y=b.math("MULTIPLY", a, -1.0)),
                                           b.combine(x=a)])
    return _points(b, n, pos), b.euler_to_rot(b.vmath("SCALE", eul, scale=g["Align"])), None


def _grid(b, g):
    cx, cy, cz = g["Count X"], g["Count Y"], g["Count Z"]
    sx, sy, sz = b.separate(g["Spacing"])
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
    pts = _points(b, total, b.combine(b.math("ADD", px, hx), py, pz))
    outside = {
        "Cube": 0.0,
        "Sphere": b.math("GREATER_THAN", b.vmath("LENGTH", b.combine(ux, uy, uz)), 1.05),
        "Cylinder": b.math("GREATER_THAN", b.vmath("LENGTH", b.combine(ux, uy)), 1.05),
    }
    drop = b.index_switch("FLOAT", b.menu(list(outside), g["Shape"]), list(outside.values()))
    pts = b.node("GeometryNodeDeleteGeometry", {"Geometry": pts, "Selection": b.math("GREATER_THAN", drop, 0.5)},
                 domain="POINT").outputs[0]
    return pts, None, None


def _object(b, g):
    geo = b.object_geometry(g["Object"])
    nrm = b.inp("GeometryNodeInputNormal")

    def from_mesh(domain, mode):
        stored = b.store(geo, "mb_n", nrm, "FLOAT_VECTOR", domain)
        return b.node("GeometryNodeMeshToPoints", {"Mesh": stored}, mode=mode).outputs[0]

    area = b.node("GeometryNodeAttributeStatistic", {"Geometry": geo,
                                                     "Attribute": b.inp("GeometryNodeInputMeshFaceArea")},
                  data_type="FLOAT", domain="FACE")
    density = b.math("DIVIDE", g["Count"], b.at_least(out(area, "Sum"), 1e-6))
    scatter = b.node("GeometryNodeDistributePointsOnFaces", {"Mesh": geo, "Density": density, "Seed": g["Seed"]},
                     distribute_method="RANDOM")
    surface = b.store(out(scatter, "Points"), "mb_n", out(scatter, "Normal"), "FLOAT_VECTOR", "POINT")
    pts = b.index_switch("GEOMETRY", b.menu(["Vertices", "Faces", "Surface"], g["Distribution"]),
                         [from_mesh("POINT", "VERTICES"), from_mesh("FACE", "FACES"), surface])
    rot = b.node("FunctionNodeAlignRotationToVector",
                 {"Factor": g["Align"], "Vector": b.named("mb_n", "FLOAT_VECTOR")}, axis="Z").outputs[0]
    return pts, rot, None


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


BUILDERS = {
    "linear": _cloner("MB Cloner Linear", [
        S("Count", "INT", 5, 0, 100000),
        S("Offset", "VECTOR", (2.5, 0, 0), subtype="TRANSLATION", desc="Distance between clones"),
        S("Step Rotation", "VECTOR", (0, 0, 0), subtype="EULER", desc="Rotation added per clone"),
        S("Step Scale", "FLOAT", 1.0, 0.0, desc="Scale multiplier per clone"),
    ], _linear),
    "radial": _cloner("MB Cloner Radial", [
        S("Count", "INT", 8, 0, 100000),
        S("Radius", "FLOAT", 4.0, 0.0, subtype="DISTANCE"),
        S("Plane", "MENU"),
        S("Start Angle", "FLOAT", 0.0, subtype="ANGLE"),
        S("End Angle", "FLOAT", 2 * math.pi, subtype="ANGLE"),
        S("Align", "BOOL", True, desc="Rotate clones to face outward"),
    ], _radial, {"Plane": "XY"}),
    "grid": _cloner("MB Cloner Grid", [
        S("Count X", "INT", 3, 1, 1000), S("Count Y", "INT", 3, 1, 1000), S("Count Z", "INT", 3, 1, 1000),
        S("Spacing", "VECTOR", (2.5, 2.5, 2.5), subtype="TRANSLATION"),
        S("Shape", "MENU", desc="Fill a cube, sphere or cylinder"),
        S("Honeycomb", "BOOL", False, desc="Offset every other row by half a step"),
    ], _grid, {"Shape": "Cube"}),
    "object": _cloner("MB Cloner Object", [
        S("Object", "OBJECT", desc="Clone onto this object's surface"),
        S("Distribution", "MENU"),
        S("Count", "INT", 50, 0, 1000000, desc="Surface mode: number of clones"),
        S("Align", "BOOL", True, desc="Point clones' Z along the surface normal"),
    ], _object, {"Distribution": "Vertices"}),
    "spline": _cloner("MB Cloner Spline", [
        S("Curve", "OBJECT", desc="Curve object to clone along"),
        S("Count", "INT", 10, 0, 100000),
        S("Offset", "FLOAT", 0.0, desc="Slide clones along the curve (animate for motion)"),
        S("Spread", "FLOAT", 1.0, 0.0, 1.0, "FACTOR", "Fraction of the curve covered"),
        S("Align", "BOOL", True, desc="Rotate clones to follow the curve"),
    ], _spline),
}
