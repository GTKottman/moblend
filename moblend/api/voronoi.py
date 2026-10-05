"""Voronoi Fracture, following Cinema 4D's tabs: Sources, Object, Sorting, Detailing, Geometry Glue,
Selections (attributes) and Connectors (rigid-body glue, see make_dynamic).

The fracture is exact (each cell is the source cut by the bisector planes of its neighbouring seeds,
caps filled with a constrained triangulation so cuts through hollow parts keep their holes) and is
computed in Python, then cached in the object's mesh: a Geometry Nodes version would be recomputed
every frame whenever an effector animates the pieces. Settings live in `object.moblend_voronoi`; any
change (or moving a source / sort / glue object) re-fractures automatically after a short debounce,
like C4D's Autoupdate. The original mesh is kept (KEY_SOURCE), so re-fracturing never compounds.

Cost (n seeds, F source faces): seed placement O(n * attempts * log F) with a BVH; each cell copies
the source (O(F)) and is cut by neighbours in order of distance, stopping once the next seed is more
than twice the cell's radius (+ offset) away, beyond which no bisector can touch the cell; one KD-tree
query per seed, O(n^2 log n) worst case overall. Sorting O(n log n), glue O(n log n) (cluster/object)
or O(n^2) (distance, "Bigger").
"""

import math
import random

import bmesh
import bpy
from bpy.props import (BoolProperty, BoolVectorProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from mathutils import Matrix, Vector, noise
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from ..catalog import KEY_KIND, KEY_SOURCE, Kind
from .generator import MOD_NAMES, add_fracture
from .material import solid_material
from .objects import get_object
from .params import PARAM_SOURCES, rna_params, set_params

INSIDE_MATERIAL = "MB Fracture Inside"
SEED_ATTEMPTS_PER_PIECE = 200
DEBOUNCE = 0.2  # seconds of quiet before an automatic re-fracture
KEY_STATE = "mb_voronoi_state"  # hash of everything the last fracture depended on
KEY_PAIRS = "mb_voronoi_pairs"  # flattened neighbouring piece pairs, for connectors

_AXES = [("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")]


def _changed(self, context):
    if self.auto_update:
        schedule(self.id_data)


class MB_VoronoiSettings(bpy.types.PropertyGroup):
    auto_update: BoolProperty(name="Autoupdate", default=True, description="Re-fracture whenever a setting changes")
    # -- Sources: point generator
    use_generator: BoolProperty(name="Point Generator", default=True, update=_changed)
    distribution: EnumProperty(name="Distribution", update=_changed, items=[
        ("UNIFORM", "Uniform", "Random points in the bounding box"),
        ("NORMAL", "Normal", "Concentrated toward the center (Gaussian)"),
        ("INVERSE_NORMAL", "Inverse Normal", "Concentrated toward the corners"),
        ("EXPONENTIAL", "Exponential", "Concentrated at the object's axes chosen below")])
    pieces: IntProperty(name="Point Amount", default=24, min=1, soft_max=2000, update=_changed)
    seed: IntProperty(name="Seed", default=0, update=_changed)
    std_dev: FloatProperty(name="Standard Deviation", default=0.2, min=0.01, max=0.7, update=_changed)
    exp_axes: BoolVectorProperty(name="Axes", size=3, default=(True, False, False), subtype="XYZ", update=_changed)
    inside: BoolProperty(name="Inside", default=True, update=_changed, description="Only place points inside the mesh")
    high_quality: BoolProperty(name="High Quality", default=False, update=_changed,
                               description="Ray-parity inside test: slower, robust for open or "
                                           "self-intersecting meshes")
    bounds_offset: FloatVectorProperty(name="Box Position", size=3, subtype="TRANSLATION", update=_changed)
    bounds_scale: FloatVectorProperty(name="Box Scale", size=3, default=(1, 1, 1), subtype="XYZ", min=0.0,
                                      update=_changed)
    # -- Sources: objects, shader, weight map
    sources: PointerProperty(name="Source Objects", type=bpy.types.Collection, update=_changed,
                             description="Points, vertices, curve points, particles or origins of these objects")
    texture: PointerProperty(name="Shader Source", type=bpy.types.Texture, update=_changed,
                             description="Extra points placed where this texture is bright")
    texture_points: IntProperty(name="Shader Points", default=0, min=0, update=_changed)
    density_group: StringProperty(name="Weightmap", default="", update=_changed,
                                  description="Vertex group: more pieces where its weight is high")
    selection_group: StringProperty(name="MoGraph Selection", default="", update=_changed,
                                    description="Vertex group: only this part breaks; the rest stays one piece")
    # -- Object
    colorize: BoolProperty(name="Colorize Fragments", default=True, update=_changed)
    ngons: BoolProperty(name="Create N-Gon Surfaces", default=False, update=_changed)
    offset: FloatProperty(name="Offset Fragments", default=0.0, min=0.0, subtype="DISTANCE", update=_changed,
                          description="Gap on each side of every cut (the visible gap is twice this)")
    invert: BoolProperty(name="Invert", default=False, update=_changed,
                         description="Keep the gaps instead of the pieces")
    hull_only: BoolProperty(name="Hull Only", default=False, update=_changed, description="Fracture only a shell")
    thickness: FloatProperty(name="Thickness", default=0.1, min=0.0, subtype="DISTANCE", update=_changed)
    close_holes: BoolProperty(name="Optimize and Close Holes", default=False, update=_changed)
    scale_cells: FloatVectorProperty(name="Scale Cells", size=3, default=(1, 1, 1), min=0.01, subtype="XYZ",
                                     update=_changed)
    # -- Sorting
    sort: EnumProperty(name="Sort Result", update=_changed, items=[
        ("NONE", "Off", "Seed order"), ("DIRECTION", "By Direction", "Along an axis"),
        ("DISTANCE", "Distance to Object", "Farther pieces get smaller indices (as in Cinema 4D)")])
    sort_axis: EnumProperty(name="Direction", items=_AXES, default="X", update=_changed)
    sort_object: PointerProperty(name="Object", type=bpy.types.Object, update=_changed)
    along_spline: BoolProperty(name="Along Spline", default=False, update=_changed,
                               description="With a curve: number pieces in the curve's direction")
    invert_sort: BoolProperty(name="Invert Sort", default=False, update=_changed)
    # -- Detailing
    detail: BoolProperty(name="Enable Detailing", default=False, update=_changed)
    max_edge: FloatProperty(name="Maximum Edge Length", default=0.1, min=0.005, subtype="DISTANCE", update=_changed)
    noise_strength: FloatProperty(name="Noise Strength", default=0.05, subtype="DISTANCE", update=_changed)
    noise_scale: FloatProperty(name="Noise Scale", default=2.0, min=0.0, update=_changed)
    noise_seed: IntProperty(name="Noise Seed", default=0, update=_changed)
    octaves: IntProperty(name="Octaves", default=3, min=0, max=16, update=_changed)
    noise_surface: BoolProperty(name="Noise Surface", default=False, update=_changed,
                                description="Also distort the original outer surface")
    keep_surface: BoolProperty(name="Keep Original Surface", default=True, update=_changed,
                               description="Points on the outer surface never move")
    low_clip: FloatProperty(name="Low Clip", default=0.0, min=0.0, max=1.0, subtype="FACTOR", update=_changed)
    high_clip: FloatProperty(name="High Clip", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=_changed)
    depth: FloatProperty(name="Strength at Depth", default=0.0, min=0.0, subtype="DISTANCE", update=_changed,
                         description="Noise grows from 0 at the surface to full strength at this depth (0 = off)")
    relax: IntProperty(name="Relax Inside Edges", default=0, min=0, max=50, update=_changed)
    smooth_inside: BoolProperty(name="Smooth Normals", default=False, update=_changed,
                                description="Smooth-shade the cut faces")
    # -- Geometry Glue
    glue: EnumProperty(name="Glue", update=_changed, items=[
        ("NONE", "Off", ""), ("CLUSTER", "Cluster", "Random groups of fragments"),
        ("DISTANCE", "Point Distance", "Fragments whose points are within Distance"),
        ("OBJECT", "Object", "Fragments whose points are inside an object's shape")])
    cluster_amount: IntProperty(name="Cluster Amount", default=6, min=1, update=_changed)
    cluster_seed: IntProperty(name="Cluster Seed", default=0, update=_changed)
    glue_distance: FloatProperty(name="Distance", default=0.5, min=0.0, subtype="DISTANCE", update=_changed)
    bigger: BoolProperty(name="Bigger", default=False, update=_changed,
                         description="Connect points that are farther apart than Distance")
    glue_object: PointerProperty(name="Glue Object", type=bpy.types.Object, update=_changed)
    glue_rest: BoolProperty(name="Glue Rest", default=False, update=_changed,
                            description="Also merge every fragment outside into one piece")


SECTIONS = {  # panel layout and MCP grouping, in C4D tab order
    "Sources": ("use_generator", "distribution", "pieces", "seed", "std_dev", "exp_axes", "inside", "high_quality",
                "bounds_offset", "bounds_scale", "sources", "texture", "texture_points", "density_group",
                "selection_group"),
    "Object": ("colorize", "ngons", "offset", "invert", "hull_only", "thickness", "close_holes", "scale_cells",
               "auto_update"),
    "Sorting": ("sort", "sort_axis", "sort_object", "along_spline", "invert_sort"),
    "Detailing": ("detail", "max_edge", "noise_strength", "noise_scale", "noise_seed", "octaves", "noise_surface",
                  "keep_surface", "low_clip", "high_clip", "depth", "relax", "smooth_inside"),
    "Geometry Glue": ("glue", "cluster_amount", "cluster_seed", "glue_distance", "bigger", "glue_object",
                      "glue_rest"),
}


def register():
    _register_params()
    bpy.utils.register_class(MB_VoronoiSettings)
    bpy.types.Object.moblend_voronoi = PointerProperty(type=MB_VoronoiSettings)
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    del bpy.types.Object.moblend_voronoi
    bpy.utils.unregister_class(MB_VoronoiSettings)


def _voronoi_params(o):
    return rna_params(o.moblend_voronoi, "Voronoi", refresh)


def _register_params():
    if not any(make is _voronoi_params for _, make in PARAM_SOURCES):
        PARAM_SOURCES.append((is_voronoi, _voronoi_params))


def is_voronoi(o):
    return o is not None and o.get(KEY_SOURCE) is not None and o.get(KEY_KIND) == Kind.FRACTURE


# ---------------------------------------------------------------- live updates

_pending = set()


def schedule(o):
    """Re-fracture `o` once settings stop changing for DEBOUNCE seconds (coalesces slider drags)."""
    _pending.add(o.name)
    if not bpy.app.timers.is_registered(_flush):
        bpy.app.timers.register(_flush, first_interval=DEBOUNCE)


def _flush():
    names = list(_pending)
    _pending.clear()
    for name in names:
        o = bpy.data.objects.get(name)
        if is_voronoi(o):
            refresh(o)
    return None


def _plain(v):
    """Settings value as something with a stable repr (vectors -> tuples, IDs -> names)."""
    if isinstance(v, bpy.types.ID):
        return v.name
    return tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v


def _state(o):
    """Everything the fracture depends on, as a string. O(settings + source objects)."""
    s = o.moblend_voronoi
    parts = [repr(_plain(getattr(s, k))) for sec in SECTIONS.values() for k in sec if k != "auto_update"]
    watched = list(s.sources.all_objects) if s.sources else []
    watched += [x for x in (s.sort_object, s.glue_object) if x is not None]
    parts += [x.name + repr([round(v, 5) for row in x.matrix_world for v in row]) for x in watched]
    parts.append(repr([round(v, 5) for row in o.matrix_world.inverted_safe() for v in row]) if watched else "")
    return "|".join(parts)


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    """Source/sort/glue objects moved: re-fracture the objects that use them (C4D Autoupdate)."""
    for o in scene.objects:
        if is_voronoi(o) and o.moblend_voronoi.auto_update and o.get(KEY_STATE) != _state(o):
            schedule(o)


# ---------------------------------------------------------------- sources

def _box(bm, s):
    lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
    hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])
    half = Vector([(hi[i] - lo[i]) / 2 * s.bounds_scale[i] for i in range(3)])
    return (lo + hi) / 2 + Vector(s.bounds_offset), half


def _inside_test(bvh, parity):
    """Point-in-mesh. Nearest-normal: O(log F), needs consistent normals. Ray parity: robust, slower."""
    if parity:
        direction = Vector((0.5773, 0.5774, 0.5773))

        def inside(p):
            hits, origin = 0, p.copy()
            for _ in range(256):
                hit = bvh.ray_cast(origin, direction)
                if hit[0] is None:
                    break
                hits += 1
                origin = hit[0] + direction * 1e-5
            return hits % 2 == 1
        return inside

    def inside(p):
        hit = bvh.find_nearest(p)
        return hit[0] is not None and (p - hit[0]).dot(hit[1]) < 0.0
    return inside


def _sample_unit(s, rng):
    """One point in [-1, 1]^3 following the chosen distribution."""
    sd = s.std_dev
    if s.distribution == "UNIFORM":
        return Vector([rng.uniform(-1, 1) for _ in range(3)])
    if s.distribution == "NORMAL":
        return Vector([max(-1.0, min(1.0, rng.gauss(0, sd * 2))) for _ in range(3)])
    if s.distribution == "INVERSE_NORMAL":
        return Vector([math.copysign(1.0 - min(abs(rng.gauss(0, sd * 2)), 1.0), rng.uniform(-1, 1))
                       for _ in range(3)])
    return Vector([math.copysign(min(rng.expovariate(1.0 / (sd * 2)), 1.0), rng.uniform(-1, 1))
                   if s.exp_axes[i] else rng.uniform(-1, 1) for i in range(3)])


def _weight_lookup(o, bm, bvh, group_name):
    """Vertex-group weight at the nearest surface point, or None when the group is missing. O(log F)."""
    vg = o.vertex_groups.get(group_name) if group_name else None
    deform = bm.verts.layers.deform.active
    if vg is None or deform is None:
        return None
    bm.faces.ensure_lookup_table()

    def weight(p):
        hit = bvh.find_nearest(p)
        if hit[2] is None:
            return 0.0
        verts = bm.faces[hit[2]].verts
        return sum(v[deform].get(vg.index, 0.0) for v in verts) / len(verts)
    return weight


def _generated(bm, s, rng, inside, accept):
    center, half = _box(bm, s)
    points = []
    for _ in range(s.pieces * SEED_ATTEMPTS_PER_PIECE):
        if len(points) == s.pieces:
            break
        u = _sample_unit(s, rng)
        p = center + Vector([u[i] * half[i] for i in range(3)])
        if (not s.inside or inside(p)) and accept(p):
            points.append(p)
    if len(points) < s.pieces and not s.inside:
        return points
    if len(points) < s.pieces:  # open or flat mesh: fill the rest from the box
        points += [center + Vector([rng.uniform(-1, 1) * half[i] for i in range(3)])
                   for _ in range(s.pieces - len(points))]
    return points


def _object_points(o, collection):
    """Points of every object in `collection`, in the fractured object's local space. O(total points)."""
    if collection is None:
        return []
    to_local = o.matrix_world.inverted_safe()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    pts = []
    for x in collection.all_objects:
        ev = x.evaluated_get(depsgraph)
        m = to_local @ x.matrix_world
        if x.type == "MESH":
            pts += [m @ v.co for v in ev.data.vertices]
        elif x.type == "CURVE":
            for sp in x.data.splines:
                pts += [m @ Vector(p.co[:3]) for p in sp.points] + [m @ p.co for p in sp.bezier_points]
        else:
            pts.append(m.translation.copy())
        for ps in ev.particle_systems:
            pts += [to_local @ Vector(pa.location) for pa in ps.particles if pa.alive_state == "ALIVE"]
    return pts


def _texture_points(bm, s, rng, inside):
    if s.texture is None or s.texture_points == 0:
        return []
    center, half = _box(bm, s)
    points = []
    for _ in range(s.texture_points * SEED_ATTEMPTS_PER_PIECE):
        if len(points) == s.texture_points:
            break
        p = center + Vector([rng.uniform(-1, 1) * half[i] for i in range(3)])
        rgba = s.texture.evaluate(p)
        if rng.random() < (rgba[0] + rgba[1] + rgba[2]) / 3 and (not s.inside or inside(p)):
            points.append(p)
    return points


def _seeds(o, bm, s):
    rng = random.Random(s.seed)
    bvh = BVHTree.FromBMesh(bm)
    inside = _inside_test(bvh, s.high_quality)
    weight = _weight_lookup(o, bm, bvh, s.density_group)

    def accept(p):
        return weight is None or rng.random() < weight(p)

    pts = _generated(bm, s, rng, inside, accept) if s.use_generator else []
    pts += _object_points(o, s.sources) + _texture_points(bm, s, rng, inside)
    if not pts:  # nothing to cut with: one piece
        pts = [_box(bm, s)[0]]
    kd = _kdtree(pts)  # coincident seeds would give degenerate bisectors: keep one of each
    return [p for i, p in enumerate(pts) if kd.find(p)[1] == i]


# ---------------------------------------------------------------- source preparation

def _prepare(src, s):
    bm = bmesh.new()
    bm.from_mesh(src)
    if s.close_holes:
        bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
    if s.hull_only and s.thickness > 0:  # outer surface + inner surface pushed in and flipped = a shell
        bm.normal_update()
        dup = bmesh.ops.duplicate(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:])
        verts = [g for g in dup["geom"] if isinstance(g, bmesh.types.BMVert)]
        for v in verts:
            v.co -= v.normal * s.thickness
        bmesh.ops.reverse_faces(bm, faces=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)])
    return bm


# ---------------------------------------------------------------- cells

def _cap(bm, cut_edges, normal, inside_index, neighbour, cap_layer):
    """Fill the cut with a constrained triangulation (keeps holes, e.g. cutting a tube). O(cut edges log)."""
    faces = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=cut_edges, normal=normal)["geom"]
    for f in (g for g in faces if isinstance(g, bmesh.types.BMFace)):
        f.material_index = inside_index
        f[cap_layer] = neighbour
        f.normal_update()
        if f.normal.dot(normal) < 0:
            f.normal_flip()


def _cell(source, seeds, kd, i, offset, inside_index):
    """bmesh of source ∩ (Voronoi cell i shrunk by `offset`); cap faces record their neighbour index."""
    bm = source.copy()
    cap = bm.faces.layers.int.get("mb_cap_of") or bm.faces.layers.int.new("mb_cap_of")
    for f in bm.faces:
        f[cap] = -1
    seed = seeds[i]

    def radius():
        return max(((v.co - seed).length for v in bm.verts), default=0.0)

    r = radius()
    for co, j, dist in kd.find_n(seed, len(seeds)):
        if j == i:
            continue
        if dist > 2.0 * (r + offset) or not bm.faces:
            break  # the bisector of every farther seed lies outside the cell
        normal = (co - seed).normalized()
        res = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-6,
                                     plane_co=(seed + co) / 2 - normal * offset, plane_no=normal, clear_outer=True)
        cut = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        if cut:
            _cap(bm, cut, normal, inside_index, j, cap)
        r = radius()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def _clipped(n, s):
    """Noise component -1..1 with C4D Low/High Clip: values outside the window become plateaus."""
    t = (n + 1) / 2
    span = max(s.high_clip - s.low_clip, 1e-6)
    return (min(max((t - s.low_clip) / span, 0.0), 1.0)) * 2 - 1


def _detail(bm, s, inside_index, surface):
    """Subdivide the cut faces to Maximum Edge Length, then displace them with fractal noise (clipped, and
    ramped in from the original surface by Strength at Depth), then relax and smooth.

    Displacement depends only on position, so the two sides of a cut move identically. O(new faces log F).
    """
    inside_faces = [f for f in bm.faces if f.material_index == inside_index]
    bmesh.ops.triangulate(bm, faces=inside_faces)
    for _ in range(12):
        long_edges = [e for e in bm.edges if e.calc_length() > s.max_edge
                      and any(f.material_index == inside_index for f in e.link_faces)]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=True)
    offset = Vector((s.noise_seed * 17.31, s.noise_seed * 5.77, s.noise_seed * 11.13))
    for v in bm.verts:
        on_cut = any(f.material_index == inside_index for f in v.link_faces)
        on_surface = any(f.material_index != inside_index for f in v.link_faces)
        if not (on_cut or s.noise_surface) or (on_surface and s.keep_surface and not s.noise_surface):
            continue
        n = noise.turbulence_vector(v.co * s.noise_scale + offset, max(s.octaves, 1), False)
        depth = 1.0
        if s.depth > 0:
            hit = surface.find_nearest(v.co)
            depth = min((hit[3] or 0.0) / s.depth, 1.0)
        v.co += Vector([_clipped(c, s) for c in n]) * (s.noise_strength * depth)
    inside_only = [v for v in bm.verts if v.link_faces and all(f.material_index == inside_index for f in v.link_faces)]
    for _ in range(s.relax):
        bmesh.ops.smooth_vert(bm, verts=inside_only, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    if s.smooth_inside:
        for f in bm.faces:
            if f.material_index == inside_index:
                f.smooth = True


# ---------------------------------------------------------------- sorting & glue

def _curve_polyline(c):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    me = c.evaluated_get(depsgraph).to_mesh()
    pts = [c.matrix_world @ v.co for v in me.vertices]
    c.evaluated_get(depsgraph).to_mesh_clear()
    return pts


def _sort_keys(o, s, centers):
    """Sort key per piece center (world-independent unless an object is involved). O(n log P)."""
    if s.sort == "DIRECTION":
        axis = "XYZ".index(s.sort_axis)
        return [c[axis] for c in centers]
    target = s.sort_object
    if s.sort != "DISTANCE" or target is None:
        return list(range(len(centers)))
    world = [o.matrix_world @ c for c in centers]
    if target.type == "CURVE":
        line = _curve_polyline(target)
        kd = _kdtree(line)
        if s.along_spline:
            return [kd.find(p)[1] for p in world]  # position along the curve
        return [-kd.find(p)[2] for p in world]
    if target.type == "MESH":
        depsgraph = bpy.context.evaluated_depsgraph_get()
        ev = target.evaluated_get(depsgraph)
        bvh = BVHTree.FromObject(ev, depsgraph)
        inv = target.matrix_world.inverted_safe()
        return [-(bvh.find_nearest(inv @ p)[3] or 0.0) for p in world]
    return [-(p - target.matrix_world.translation).length for p in world]  # farther = smaller index


class _Union:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, a):
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def inside_object(obj, p):
    """Is world point p inside `obj`'s shape (sphere/box empties, otherwise its bounding box)?"""
    local = obj.matrix_world.inverted_safe() @ p
    if obj.type == "EMPTY" and obj.empty_display_type == "SPHERE":
        return local.length <= obj.empty_display_size
    if obj.type == "EMPTY":
        return all(abs(c) <= obj.empty_display_size for c in local)
    lo = Vector([min(c[i] for c in obj.bound_box) for i in range(3)])
    hi = Vector([max(c[i] for c in obj.bound_box) for i in range(3)])
    return all(lo[i] <= local[i] <= hi[i] for i in range(3))


def _kdtree(points):
    kd = KDTree(len(points))
    for i, p in enumerate(points):
        kd.insert(p, i)
    kd.balance()
    return kd


def _glue(o, s, seeds, selected=None):
    """Group label per seed (real, unstretched positions): same label = one piece. Seeds outside the
    MoGraph Selection (selected(p) false) all join one unbroken piece."""
    n = len(seeds)
    uf = _Union(n)
    kd = _kdtree(seeds)
    if selected is not None:
        rest = [i for i in range(n) if not selected(seeds[i])]
        for i in rest[1:]:
            uf.join(i, rest[0])
    if s.glue == "CLUSTER":
        rng = random.Random(s.cluster_seed)
        centers = rng.sample(range(n), min(s.cluster_amount, n))
        ck = _kdtree([seeds[c] for c in centers])
        for i in range(n):
            uf.join(i, centers[ck.find(seeds[i])[1]])
    elif s.glue == "DISTANCE":
        for i in range(n):
            if s.bigger:  # literal C4D "Bigger": join pairs farther apart than Distance. O(n^2)
                for j in range(i + 1, n):
                    if (seeds[i] - seeds[j]).length > s.glue_distance:
                        uf.join(i, j)
            else:
                for _, j, _ in kd.find_range(seeds[i], s.glue_distance):
                    uf.join(i, j)
    elif s.glue == "OBJECT" and s.glue_object is not None:
        inside = [i for i in range(n) if inside_object(s.glue_object, o.matrix_world @ seeds[i])]
        outside = [i for i in range(n) if i not in set(inside)]
        for group in (inside, outside if s.glue_rest else []):
            for i in group[1:]:
                uf.join(i, group[0])
    return [uf.find(i) for i in range(n)]


# ---------------------------------------------------------------- selections

def _selection_attributes(mesh, inside_index):
    """Inside/Outside Faces, Surface Break Edges and the matching vertex weights. O(F + E + V)."""
    inside = [p.material_index == inside_index for p in mesh.polygons]
    face_attr = mesh.attributes.new("mb_inside_faces", "BOOLEAN", "FACE")
    face_attr.data.foreach_set("value", inside)
    out_attr = mesh.attributes.new("mb_outside_faces", "BOOLEAN", "FACE")
    out_attr.data.foreach_set("value", [not x for x in inside])
    vert_in, vert_out = [0.0] * len(mesh.vertices), [0.0] * len(mesh.vertices)
    edge_faces = {}
    for p in mesh.polygons:
        for v in p.vertices:
            (vert_in if inside[p.index] else vert_out)[v] = 1.0
        for ek in p.edge_keys:
            edge_faces.setdefault(ek, set()).add(inside[p.index])
    breaks = [len(edge_faces.get(e.key, ())) == 2 for e in mesh.edges]
    mesh.attributes.new("mb_break_edges", "BOOLEAN", "EDGE").data.foreach_set("value", breaks)
    vert_edge = [0.0] * len(mesh.vertices)
    for e, is_break in zip(mesh.edges, breaks, strict=True):
        if is_break:
            vert_edge[e.vertices[0]] = vert_edge[e.vertices[1]] = 1.0
    for name, values in (("mb_inside_weight", vert_in), ("mb_outside_weight", vert_out), ("mb_edge_weight", vert_edge)):
        mesh.attributes.new(name, "FLOAT", "POINT").data.foreach_set("value", values)


# ---------------------------------------------------------------- main

def _inside_material_index(mesh):
    mat = bpy.data.materials.get(INSIDE_MATERIAL) or solid_material("#2a2d33", roughness=0.8, name=INSIDE_MATERIAL)
    if mat.name not in mesh.materials:
        if not mesh.materials:
            mesh.materials.append(None)  # faces use slot 0; keep it for the outside
        mesh.materials.append(mat)
    return list(mesh.materials).index(mat)


def _source_mesh(o):
    src = o.get(KEY_SOURCE)
    if src is None:
        src = o.data.copy()
        src.name = f"{o.data.name} (unfractured)"
        src.use_fake_user = True  # keep the original for re-fracturing
        o[KEY_SOURCE] = src
    return src


def _append(joined, cell, scratch, piece, piece_layer_name="mb_piece"):
    layer = cell.faces.layers.int.get(piece_layer_name) or cell.faces.layers.int.new(piece_layer_name)
    for f in cell.faces:
        f[layer] = piece
    cell.to_mesh(scratch)
    joined.from_mesh(scratch)  # appends: each cell stays its own island


def _finish_cell(cell, s, scale, labels, i, inside_index, surface):
    """Stretch back, drop faces inside a glued piece, detail, n-gons. Returns raw neighbour labels."""
    cell.transform(scale)
    cap = cell.faces.layers.int["mb_cap_of"]
    glued = [f for f in cell.faces if f[cap] >= 0 and labels[f[cap]] == labels[i]]
    if glued and s.offset == 0 and not s.invert:  # faces inside a glued piece are never seen
        bmesh.ops.delete(cell, geom=glued, context="FACES")
    touching = {labels[f[cap]] for f in cell.faces if f[cap] >= 0 and labels[f[cap]] != labels[i]}
    if s.detail:
        _detail(cell, s, inside_index, surface)
    if s.ngons:
        caps = [f for f in cell.faces if f.material_index == inside_index]
        bmesh.ops.dissolve_limit(cell, angle_limit=1e-4, verts=[], edges=list(
            {e for f in caps for e in f.edges if all(g.material_index == inside_index for g in e.link_faces)}))
    return touching


def _bounds_center(cells):
    pts = [v.co for c in cells for v in c.verts]
    if not pts:
        return Vector()
    return Vector([(min(p[k] for p in pts) + max(p[k] for p in pts)) / 2 for k in range(3)])


def refresh(ref):
    """Re-fracture from the original mesh with the object's current settings."""
    o = get_object(ref)
    s = o.moblend_voronoi
    src = _source_mesh(o)
    source = _prepare(src, s)
    scale = Matrix.Diagonal(Vector(s.scale_cells).to_4d())
    unscale = scale.inverted_safe()
    seeds = _seeds(o, source, s)
    surface = BVHTree.FromBMesh(source)  # original space: Strength at Depth, MoGraph Selection
    weight = _weight_lookup(o, source, surface, s.selection_group)
    labels = _glue(o, s, seeds, None if weight is None else (lambda p: weight(p) >= 0.5))
    source.transform(unscale)  # Scale Cells: Voronoi in a stretched space, then stretched back
    space = [unscale @ p for p in seeds]
    kd = _kdtree(space)

    out = src.copy()
    out.name = f"{src.name.removesuffix(' (unfractured)')} (fractured)"
    out.use_fake_user = False
    for name in [a.name for a in out.attributes if a.name.startswith("mb_")]:
        out.attributes.remove(out.attributes[name])
    inside_index = _inside_material_index(out)

    # Build every piece first: sorting needs the pieces' real centers (what effectors see), not seeds.
    pieces, touching = {}, {}
    for i in range(len(seeds)):
        cells = [_cell(source, space, kd, i, s.offset, inside_index)]
        if s.invert:  # the gap: full cell plus the shrunk cell turned inside out
            bmesh.ops.reverse_faces(cells[0], faces=cells[0].faces[:])
            cells.append(_cell(source, space, kd, i, 0.0, inside_index))
        for cell in cells:
            touching.setdefault(labels[i], set()).update(_finish_cell(cell, s, scale, labels, i, inside_index,
                                                                      surface))
        pieces.setdefault(labels[i], []).extend(cells)
    source.free()
    groups = list(pieces)
    if s.sort != "NONE":
        keys = _sort_keys(o, s, [_bounds_center(pieces[g]) for g in groups])
        groups = [g for _, g in sorted(zip(keys, groups, strict=True), key=lambda kg: kg[0], reverse=s.invert_sort)]
    rank = {g: k for k, g in enumerate(groups)}

    joined, scratch = bmesh.new(), bpy.data.meshes.new("mb_voronoi_scratch")
    try:
        for g in groups:
            for cell in pieces[g]:
                _append(joined, cell, scratch, rank[g])
                cell.free()
        joined.to_mesh(out)
    finally:
        joined.free()
        bpy.data.meshes.remove(scratch)
    if "mb_cap_of" in out.attributes:
        out.attributes.remove(out.attributes["mb_cap_of"])
    _selection_attributes(out, inside_index)

    old = o.data
    o.data = out
    if old.users == 0 and old != src:
        bpy.data.meshes.remove(old)
    pairs = sorted({tuple(sorted((rank[g], rank[h]))) for g, hs in touching.items() for h in hs})
    o[KEY_PAIRS] = [k for pair in pairs for k in pair]
    if not any(m.name == MOD_NAMES["fracture"] for m in o.modifiers):
        add_fracture(o, "Islands")
    set_params(o, {"Colorize": s.colorize}, modifier=MOD_NAMES["fracture"])
    o[KEY_KIND] = Kind.FRACTURE
    o[KEY_STATE] = _state(o)
    _pending.discard(o.name)
    return o


def voronoi_fracture(ref, pieces=None, seed=None, gap=None, **settings):
    """Fracture a mesh into convex Voronoi pieces that effectors can move (adds MB Fracture).

    `settings` are any MB_VoronoiSettings names (e.g. distribution="NORMAL", sort="DIRECTION",
    glue="CLUSTER", detail=True). `gap` is the old name for `offset`. Calling again re-fractures.
    """
    o = get_object(ref)
    if o.type != "MESH":
        raise ValueError(f"{o.name} is not a mesh")
    s = o.moblend_voronoi
    updates = {"pieces": pieces, "seed": seed, "offset": gap, **settings}
    auto, s.auto_update = s.auto_update, False  # one fracture below, not one per assignment
    try:
        for key, value in updates.items():
            if value is None:
                continue
            if not hasattr(s, key):
                raise ValueError(f"Unknown Voronoi setting {key!r}. Known: {[k for v in SECTIONS.values() for k in v]}")
            if key in ("sources",) and isinstance(value, str):
                value = bpy.data.collections[value]
            elif key in ("sort_object", "glue_object") and isinstance(value, str):
                value = bpy.data.objects[value]
            elif key == "texture" and isinstance(value, str):
                value = bpy.data.textures[value]
            setattr(s, key, value)
    finally:
        s.auto_update = auto
    return refresh(o)


def restore(ref):
    """Undo the fracture: give the object its original mesh back and drop the Fracture modifier."""
    o = get_object(ref)
    src = o.get(KEY_SOURCE)
    if src is None:
        return o
    fractured = o.data
    o.data = src
    src.use_fake_user = False
    del o[KEY_SOURCE]
    for key in (KEY_STATE, KEY_PAIRS, KEY_KIND):
        if key in o:
            del o[key]
    for m in [m for m in o.modifiers if m.name == MOD_NAMES["fracture"]]:
        o.modifiers.remove(m)
    if fractured.users == 0:
        bpy.data.meshes.remove(fractured)
    return o
