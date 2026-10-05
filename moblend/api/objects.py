"""Object, collection, modifier and wrapper-group helpers shared by the API modules.

N = objects in the file, M = modifiers per object.
"""

import contextlib

import bpy

from ..catalog import (GROUP_PREFIX, KEY_GROUP, KEY_KIND, PARAMS_NODE, SOURCES_COLLECTION)


def get_object(ref):
    """Object by name (or the object itself)."""
    if isinstance(ref, bpy.types.Object):
        return ref
    o = bpy.data.objects.get(str(ref))
    if o is None:
        raise ValueError(f"No object named {ref!r}")
    return o


def get_objects(refs):
    return [get_object(r) for r in refs or ()]


def mb_kind(o):
    return o.get(KEY_KIND, "")


def norm(s):
    """Name key that ignores case, spaces and punctuation: 'Count X' == 'count_x'."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def vec3(v):
    """Scalar -> (v, v, v); sequences pass through as tuples."""
    return (v,) * 3 if isinstance(v, (int, float)) else tuple(v)


def choice(value, options, what):
    """Validate `value` (case-insensitive) against `options`; returns the canonical option."""
    for opt in options:
        if norm(opt) == norm(value):
            return opt
    raise ValueError(f"{what} must be one of {list(options)}, not {value!r}")


# ---------------------------------------------------------------- creating objects

def link_new(o, location=None):
    """Link a new object into the active collection at `location` (default: 3D cursor)."""
    ctx = bpy.context
    (ctx.collection or ctx.scene.collection).objects.link(o)
    o.location = location if location is not None else ctx.scene.cursor.location
    return o


def new_mesh_object(name, location=None):
    return link_new(bpy.data.objects.new(name, bpy.data.meshes.new(name)), location)


def new_empty(name, display, size, location):
    e = link_new(bpy.data.objects.new(name, None), location)
    e.empty_display_type = display
    e.empty_display_size = 1.0
    e.scale = vec3(size)
    e.show_in_front = True
    return e


def select_only(o):
    """Make `o` the only selected, active object. O(selected)."""
    vl = bpy.context.view_layer
    if vl is None:
        return
    for x in vl.objects.selected:
        if x is not None:  # a just-deleted object can linger in the selection
            x.select_set(False)
    if o.name in vl.objects:
        o.select_set(True)
        vl.objects.active = o


def tag(o, **props):
    """Set MoBlend custom properties (KEY_* -> value) on an object."""
    for k, v in props.items():
        o[k] = v
    return o


# ---------------------------------------------------------------- collections

def move_to_collection(objs, coll):
    """Unlink each object from all its collections and link it into `coll`. O(objects x their collections)."""
    for o in objs:
        for uc in tuple(o.users_collection):
            uc.objects.unlink(o)
        coll.objects.link(o)


def sources_root():
    """Hidden collection holding cloners' source objects (excluded from every view layer)."""
    scene = bpy.context.scene
    root = bpy.data.collections.get(SOURCES_COLLECTION) or bpy.data.collections.new(SOURCES_COLLECTION)
    if root.name not in scene.collection.children:
        scene.collection.children.link(root)
    for vl in scene.view_layers:
        lc = _find_layer_collection(vl.layer_collection, root)
        if lc is not None:
            lc.exclude = True
    return root


def _find_layer_collection(lc, coll):
    """Depth-first search of the layer-collection tree. O(collections)."""
    stack = [lc]
    while stack:
        cur = stack.pop()
        if cur.collection == coll:
            return cur
        stack.extend(cur.children)
    return None


# ---------------------------------------------------------------- modifiers

def add_nodes_modifier(o, name, group, first=False):
    m = o.modifiers.new(name, "NODES")
    m.node_group = group
    if first:
        o.modifiers.move(len(o.modifiers) - 1, 0)
    return m


def keep_last(o, name):
    """Move modifier `name` (if present) to the end of the stack. O(M)."""
    i = o.modifiers.find(name)
    if 0 <= i < len(o.modifiers) - 1:
        o.modifiers.move(i, len(o.modifiers) - 1)


def mb_modifiers(o):
    """MoBlend generator modifiers (cloner, MoText, Sweep, Fracture, Tracer), in stack order."""
    return [m for m in o.modifiers
            if m.type == "NODES" and m.node_group and m.node_group.name.startswith(GROUP_PREFIX)]


def uses(mod, owner):
    """Does modifier `mod` belong to effector/deformer object `owner`? O(1)."""
    if mod.type == "NODES":
        group = owner.get(KEY_GROUP)
        return group is not None and mod.node_group == group
    return mod.type == "SIMPLE_DEFORM" and mod.origin == owner


def detach(owner, target):
    """Remove every modifier (and driver) `owner` put on `target`. O(M)."""
    for m in [m for m in target.modifiers if uses(m, owner)]:
        if m.type == "SIMPLE_DEFORM":
            for prop in ("angle", "factor"):
                target.driver_remove(f'modifiers["{m.name}"].{prop}')
        target.modifiers.remove(m)


def users_of(owner):
    """Objects affected by an effector/deformer. O(N x M)."""
    return [x for x in bpy.data.objects if any(uses(m, owner) for m in x.modifiers)]


def group_owners():
    """Wrapper node group name -> owning effector/deformer object. O(N)."""
    return {o[KEY_GROUP].name: o for o in bpy.data.objects if o.get(KEY_GROUP) is not None}


def usage_index():
    """owner name -> names of objects it affects, for all owners in one O(N x M) pass."""
    owners = group_owners()
    index = {}
    for x in bpy.data.objects:
        seen = set()
        for m in x.modifiers:
            if m.type == "NODES" and m.node_group and m.node_group.name in owners:
                seen.add(owners[m.node_group.name].name)
            elif m.type == "SIMPLE_DEFORM" and m.origin is not None:
                seen.add(m.origin.name)
        for owner in seen:
            index.setdefault(owner, []).append(x.name)
    return index


def make_wrapper(prefix, owner, type_group, realize=False):
    """Per-object wrapper group: Object Info(owner) -> one PARAMS_NODE of `type_group`.

    Every target's modifier uses this same group, so the PARAMS_NODE's input values are shared.
    """
    ng = bpy.data.node_groups.new(f"{prefix}{owner.name}", "GeometryNodeTree")
    for io in ("INPUT", "OUTPUT"):
        ng.interface.new_socket("Geometry", in_out=io, socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "RELATIVE"  # placement relative to whichever object evaluates the modifier
    info.inputs["Object"].default_value = owner
    params = nodes.new("GeometryNodeGroup")
    params.node_tree = type_group
    params.name = params.label = PARAMS_NODE
    src = gin.outputs[0]
    if realize:  # deformers move real points, so clones must be realized first
        r = nodes.new("GeometryNodeRealizeInstances")
        links.new(src, r.inputs[0])
        src = r.outputs[0]
        r.location = (-150, -200)
    links.new(src, params.inputs[0])
    links.new(info.outputs["Transform"], params.inputs["Transform"])
    links.new(params.outputs[0], gout.inputs[0])
    gin.location, info.location, params.location, gout.location = (-400, 0), (-400, -200), (0, 0), (300, 0)
    return ng


def socket_values(node):
    """Unlinked input values as plain Python copies. A vector default_value is a live view into socket
    memory, which rebuilding the group frees; keeping the view and writing it back later crashes Blender."""
    values = {}
    for s in node.inputs:
        if hasattr(s, "default_value") and not s.is_linked:
            v = s.default_value
            values[s.name] = tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
    return values


def restore_socket_values(node, values):
    for s in node.inputs:
        if s.name in values and not s.is_linked:
            with contextlib.suppress(TypeError, ValueError):  # a socket whose type changed keeps its new default
                s.default_value = values[s.name]


def rebuild_params_group(owner, build):
    """Replace the node group of the owner wrapper's Params node with `build()` (often the same group rebuilt
    in place), keeping its links and input values: rebuilding an interface drops every link to its sockets.
    O(sockets)."""
    ng = owner[KEY_GROUP]
    params = ng.nodes[PARAMS_NODE]
    incoming = [(link.from_socket, link.to_socket.name) for link in ng.links if link.to_node == params]
    outgoing = [(link.from_socket.name, link.to_socket) for link in ng.links if link.from_node == params]
    values = socket_values(params)
    params.node_tree = build()
    for from_socket, name in incoming:
        if name in params.inputs:
            ng.links.new(from_socket, params.inputs[name])
    for name, to_socket in outgoing:
        if name in params.outputs:
            ng.links.new(params.outputs[name], to_socket)
    restore_socket_values(params, values)
    owner.update_tag()
