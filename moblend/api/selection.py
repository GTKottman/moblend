"""MoGraph Selection and Weight tags, and the Matrix object.

A cloner's own mesh is its per-clone data: vertex i belongs to clone i, and the vertex groups
"MoGraph Selection" and "MoGraph Weight" are the tags (the instancer copies them onto the clones as
mb_selection / mb_weight). sync_clone_points places those vertices on the clones, so clones can be
picked by hand in Edit Mode and painted in Weight Paint, like C4D's MoGraph Selection tool and brush.
"""

import bpy

from ..catalog import KEY_KIND, Kind
from ..nodes.core import SELECTION_TAG, WEIGHT_TAG
from .objects import get_object
from .params import set_params

KEY_MATRIX = "mb_matrix"


def parse_indices(spec):
    """'0-3, 7, 10-20:2' -> [0, 1, 2, 3, 7, 10, 12, ..., 20]. Ints and iterables of ints pass through."""
    if isinstance(spec, int):
        return [spec]
    if not isinstance(spec, str):
        return sorted({int(i) for i in spec})
    found = set()
    for part in filter(None, (p.strip() for p in spec.split(","))):
        step = 1
        if ":" in part:
            part, step_text = part.split(":")
            step = max(int(step_text), 1)
        lo, _, hi = part.partition("-")
        found.update(range(int(lo), int(hi or lo) + 1, step))
    return sorted(found)


def clone_positions(ref):
    """Clone positions in the cloner's local space, in clone-index order. O(instances in the scene)."""
    c = get_object(ref)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    to_local = c.matrix_world.inverted_safe()
    return [to_local @ inst.matrix_world.translation for inst in depsgraph.object_instances
            if inst.is_instance and inst.parent and inst.parent.original == c]


def sync_clone_points(ref):
    """Give the cloner's mesh one vertex per clone, sitting on the clone (for picking / painting).
    Existing tag values stay with their clone index. O(clones)."""
    c = get_object(ref)
    positions = clone_positions(c)
    groups = {name: _weights(c, name) for name in (SELECTION_TAG, WEIGHT_TAG)}
    mesh = c.data
    if len(mesh.vertices) != len(positions):
        mesh.clear_geometry()
        mesh.vertices.add(len(positions))
    mesh.vertices.foreach_set("co", [x for p in positions for x in p])
    mesh.update()
    for name, weights in groups.items():
        if weights:
            _write(c, name, weights)
    return len(positions)


def _weights(c, name):
    vg = c.vertex_groups.get(name)
    if vg is None:
        return {}
    res = {}
    for v in c.data.vertices:
        for ge in v.groups:
            if ge.group == vg.index:
                res[v.index] = ge.weight
    return res


def _write(c, name, weights):
    """Write {clone index: weight} into vertex group `name`, growing the data mesh if needed."""
    need = max(weights, default=-1) + 1
    mesh = c.data
    if len(mesh.vertices) < need:
        mesh.vertices.add(need - len(mesh.vertices))
    vg = c.vertex_groups.get(name) or c.vertex_groups.new(name=name)
    vg.remove(list(range(len(mesh.vertices))))
    for i, w in weights.items():
        vg.add([i], float(w), "REPLACE")
    mesh.update()
    c.update_tag()


def set_clone_selection(ref, indices):
    """MoGraph Selection tag: which clones are selected (indices, or a pattern like '0-3, 7, 10-20:2')."""
    c = get_object(ref)
    chosen = parse_indices(indices)
    _write(c, SELECTION_TAG, dict.fromkeys(chosen, 1.0))
    return chosen


def selection_from_edit_mode(ref):
    """Store the vertices selected in Edit Mode (after sync_clone_points) as the MoGraph Selection."""
    c = get_object(ref)
    if c.mode == "EDIT":
        c.update_from_editmode()
    return set_clone_selection(c, [v.index for v in c.data.vertices if v.select])


def set_clone_weights(ref, weights):
    """MoGraph Weightmap: {clone index: weight} or a list of weights in clone order."""
    c = get_object(ref)
    values = dict(enumerate(weights)) if isinstance(weights, (list, tuple)) else {int(k): v for k, v in weights.items()}
    _write(c, WEIGHT_TAG, values)
    return values


def hide_selected_clones(ref):
    """C4D 'Hide Selected': a Plain effector hiding the clones in the MoGraph Selection."""
    from .effector import add_effector  # local import: effector imports field, which imports this package
    c = get_object(ref)
    return add_effector("plain", name=f"{c.name} Hide Selected", cloners=[c], falloff="Infinite",
                        params={"Visibility": True, "Use MoGraph Selection": True})


# ---------------------------------------------------------------- Matrix

def make_matrix(ref, matrix=True):
    """Turn a cloner into a Matrix (positions only: shown as small boxes, never rendered) or back
    (C4D Swap Cloner/Matrix). Object-mode cloners can clone onto a Matrix's positions (Instances)."""
    c = get_object(ref)
    if c.get(KEY_KIND) != Kind.CLONER:
        raise ValueError(f"{c.name} is not a cloner")
    c[KEY_MATRIX] = bool(matrix)
    c.hide_render = bool(matrix)
    set_params(c, {"Viewport": "Bounding Box" if matrix else "Object"}, modifier="MB Display")
    return c


def is_matrix(o):
    return bool(o.get(KEY_MATRIX))

