"""Connectors: turn Voronoi pieces into rigid bodies held together by breakable Fixed constraints.

Cinema 4D connects neighbouring fragments with dynamics connectors that break above a force or
torque threshold. Blender's rigid bodies work on objects, so each piece becomes its own object; the
neighbouring pairs come from the fracture itself (cap faces record which cell cut them), so only
pieces that actually touch are connected. O(F) to split the mesh, O(pairs) constraint operators.
"""

import bpy
from mathutils import Matrix, Vector

from .objects import get_object
from .voronoi import KEY_PAIRS, is_voronoi


def _split_pieces(o):
    """One mesh per mb_piece id, origin at the piece's bounding-box center. Single pass over faces: O(F)."""
    me = o.data
    piece = me.attributes["mb_piece"].data
    uv = me.uv_layers.active.data if me.uv_layers.active else None
    buckets = {}
    for poly in me.polygons:
        buckets.setdefault(piece[poly.index].value, []).append(poly)
    meshes = {}
    for pid, polys in sorted(buckets.items()):
        remap, verts, faces, mats, uvs = {}, [], [], [], []
        for poly in polys:
            for vi in poly.vertices:
                if vi not in remap:
                    remap[vi] = len(verts)
                    verts.append(me.vertices[vi].co.copy())
            faces.append([remap[vi] for vi in poly.vertices])
            mats.append(poly.material_index)
            if uv is not None:
                uvs += [uv[li].uv.copy() for li in poly.loop_indices]
        lo = Vector([min(v[i] for v in verts) for i in range(3)])
        hi = Vector([max(v[i] for v in verts) for i in range(3)])
        center = (lo + hi) / 2
        mesh = bpy.data.meshes.new(f"{o.name} Piece {pid}")
        mesh.from_pydata([v - center for v in verts], [], faces)
        for mat in me.materials:
            mesh.materials.append(mat)
        mesh.polygons.foreach_set("material_index", mats)
        if uvs:
            layer = mesh.uv_layers.new()
            for li, value in enumerate(uvs):
                layer.data[li].uv = value
        mesh.update()
        meshes[pid] = (mesh, center)
    return meshes


def _with_selection(objs, active, fn):
    view_layer = bpy.context.view_layer
    for x in view_layer.objects.selected:
        x.select_set(False)
    for x in objs:
        x.select_set(True)
    view_layer.objects.active = active
    with bpy.context.temp_override(selected_objects=objs, active_object=active, object=active):
        fn()


def make_dynamic(ref, breaking_threshold=10.0, mass=1.0, connect=True):
    """Replace a Voronoi-fractured object by rigid-body pieces, connected where they touch.

    The fractured object is hidden (not deleted), so you can go back by deleting the pieces' collection.
    Returns the new collection's name.
    """
    o = get_object(ref)
    if not is_voronoi(o):
        raise ValueError(f"{o.name} is not a Voronoi-fractured object")
    scene = bpy.context.scene
    if scene.rigidbody_world is None:
        with bpy.context.temp_override(scene=scene):
            bpy.ops.rigidbody.world_add()
    coll = bpy.data.collections.new(f"{o.name} Pieces")
    scene.collection.children.link(coll)
    pieces = {}
    for pid, (mesh, center) in _split_pieces(o).items():
        p = bpy.data.objects.new(mesh.name, mesh)
        p.matrix_world = o.matrix_world @ Matrix.Translation(center)
        coll.objects.link(p)
        pieces[pid] = p
    objs = list(pieces.values())
    _with_selection(objs, objs[0], lambda: bpy.ops.rigidbody.objects_add(type="ACTIVE"))
    for p in objs:
        p.rigid_body.mass = mass
        p.rigid_body.collision_shape = "CONVEX_HULL"
    flat = list(o.get(KEY_PAIRS, []))
    pairs = [(flat[k], flat[k + 1]) for k in range(0, len(flat), 2)] if connect else []
    for a, b in pairs:
        if a not in pieces or b not in pieces:
            continue
        empty = bpy.data.objects.new(f"Connector {a}-{b}", None)
        empty.empty_display_size = 0.05
        empty.location = (pieces[a].matrix_world.translation + pieces[b].matrix_world.translation) / 2
        coll.objects.link(empty)
        _with_selection([empty], empty, lambda: bpy.ops.rigidbody.constraint_add(type="FIXED"))
        c = empty.rigid_body_constraint
        c.object1, c.object2 = pieces[a], pieces[b]
        c.use_breaking, c.breaking_threshold = True, breaking_threshold
    o.hide_viewport = o.hide_render = True
    return {"collection": coll.name, "pieces": len(objs), "connectors": len(pairs)}
