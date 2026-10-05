"""Voronoi Fracture: cut a mesh into convex cells around random seed points.

Done once in Python (exact plane bisection, like Blender's Cell Fracture) rather
than in Geometry Nodes: a GN fracture would be re-evaluated every frame whenever
an effector on the same object animates. The original mesh is kept, so calling
again with new settings re-fractures from the source, not from the pieces.

Cost: n seeds, F source faces. Seed placement O(attempts * log F) with a BVH.
Each cell copies the source (O(F)) and is bisected by neighbours in order of
distance until the next neighbour is more than twice the cell's radius away;
past that point no bisector can touch the cell, so the cut is exact.
Neighbour order: one KD-tree query of O(n log n) per seed, O(n^2 log n) total.
"""

import random

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from ..catalog import KEY_KIND, KEY_SOURCE, Kind
from .generator import MOD_NAMES, add_fracture
from .material import solid_material
from .objects import get_object

INSIDE_MATERIAL = "MB Fracture Inside"
SEED_ATTEMPTS_PER_PIECE = 200
SETTINGS = {"pieces": "Voronoi Pieces", "seed": "Voronoi Seed", "gap": "Voronoi Gap"}  # stored on the object


def _inside_test(bvh):
    """Point-in-mesh by the nearest surface normal; valid for closed meshes. O(log F)."""
    def inside(p):
        hit = bvh.find_nearest(p)
        return hit[0] is not None and (p - hit[0]).dot(hit[1]) < 0.0
    return inside


def _seeds(bm, count, rng):
    """`count` random points inside the mesh (inside its bounds when it is open or flat)."""
    lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
    hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])

    def sample():
        return Vector([rng.uniform(lo[i], hi[i]) for i in range(3)])

    inside = _inside_test(BVHTree.FromBMesh(bm))
    points = []
    for _ in range(count * SEED_ATTEMPTS_PER_PIECE):
        if len(points) == count:
            return points
        p = sample()
        if inside(p):
            points.append(p)
    return points + [sample() for _ in range(count - len(points))]  # open/flat mesh: fill from the bounds


def _cell(source, seeds, kd, i, inside_index):
    """bmesh of source ∩ Voronoi cell i, with cut faces capped and given `inside_index`."""
    bm = source.copy()
    seed = seeds[i]

    def radius():
        return max(((v.co - seed).length for v in bm.verts), default=0.0)

    r = radius()
    for co, j, dist in kd.find_n(seed, len(seeds)):
        if j == i:
            continue
        if dist > 2.0 * r or not bm.faces:
            break  # the bisector of every farther seed lies outside the cell
        res = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-6,
                                     plane_co=(seed + co) / 2, plane_no=(co - seed).normalized(), clear_outer=True)
        cut = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        if cut:
            for f in bmesh.ops.holes_fill(bm, edges=cut, sides=0)["faces"]:
                f.material_index = inside_index
        r = radius()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def _shrink(bm, gap):
    """Pull a piece toward its center by `gap` (0..0.9) so pieces separate visibly. O(V)."""
    if gap <= 0 or not bm.verts:
        return
    center = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    for v in bm.verts:
        v.co = center + (v.co - center) * (1.0 - gap)


def _inside_material_index(mesh):
    """Index of the inner-face material on `mesh`, adding it (after a placeholder slot if needed)."""
    mat = bpy.data.materials.get(INSIDE_MATERIAL) or solid_material("#2a2d33", roughness=0.8, name=INSIDE_MATERIAL)
    if mat.name not in mesh.materials:
        if not mesh.materials:
            mesh.materials.append(None)  # faces use slot 0; keep it for the outside
        mesh.materials.append(mat)
    return list(mesh.materials).index(mat)


def voronoi_fracture(ref, pieces=24, seed=0, gap=0.0):
    """Cut a mesh into `pieces` convex chunks, ready for effectors (adds MB Fracture: Islands).

    Calling it again re-fractures from the original mesh with the new settings.
    """
    o = get_object(ref)
    if o.type != "MESH":
        raise ValueError(f"{o.name} is not a mesh")
    pieces, gap = max(int(pieces), 1), min(max(float(gap), 0.0), 0.9)
    src = o.get(KEY_SOURCE)
    if src is None:
        src = o.data.copy()
        src.name = f"{o.data.name} (unfractured)"
        src.use_fake_user = True  # keep the original for re-fracturing
        o[KEY_SOURCE] = src

    source = bmesh.new()
    source.from_mesh(src)
    seeds = _seeds(source, pieces, random.Random(seed))
    kd = KDTree(len(seeds))
    for i, p in enumerate(seeds):
        kd.insert(p, i)
    kd.balance()

    out = src.copy()
    out.name = f"{src.name.removesuffix(' (unfractured)')} (fractured)"
    out.use_fake_user = False
    inside_index = _inside_material_index(out)
    joined, scratch = bmesh.new(), bpy.data.meshes.new("mb_voronoi_scratch")
    try:
        for i in range(len(seeds)):
            cell = _cell(source, seeds, kd, i, inside_index)
            _shrink(cell, gap)
            cell.to_mesh(scratch)
            cell.free()
            joined.from_mesh(scratch)  # appends: each cell stays its own island
        joined.to_mesh(out)
    finally:
        joined.free()
        source.free()
        bpy.data.meshes.remove(scratch)

    old = o.data
    o.data = out
    if old.users == 0 and old != src:
        bpy.data.meshes.remove(old)
    for key, value in zip(SETTINGS.values(), (pieces, seed, gap), strict=True):
        o[key] = value
    if not any(m.name == MOD_NAMES["fracture"] for m in o.modifiers):
        add_fracture(o, "Islands")
    o[KEY_KIND] = Kind.FRACTURE
    return o
