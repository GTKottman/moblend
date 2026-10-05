"""Fields: shape objects layered into effectors/deformers (C4D field lists).

A field is an empty with its own wrapper group ("MBFL <name>") whose Params node
holds its settings, so one field can drive many owners. Each owner's wrapper
keeps a chain of layer nodes named LAYER_NODE_PREFIX + order, feeding its Params
node's Layers input; the chain itself is the source of truth (rename-safe).
"""

import bpy

from ..catalog import (FIELD_GROUP_PREFIX, FALLOFF_SHAPES, KEY_GROUP, KEY_KIND, KEY_TYPE, LAYER_NODE_PREFIX,
                       PARAMS_NODE, Kind)
from ..nodes import core
from .objects import choice, get_object, get_objects, group_owners, new_empty, select_only, tag
from .params import set_params

_LAYERED = (Kind.EFFECTOR, Kind.DEFORMER)  # owners whose wrapper has a Layers input


def _field_wrapper(f):
    ng = bpy.data.node_groups.new(f"{FIELD_GROUP_PREFIX}{f.name}", "GeometryNodeTree")
    ng.interface.new_socket("Previous", in_out="INPUT", socket_type="NodeSocketFloat").default_value = 1.0
    ng.interface.new_socket("First", in_out="INPUT", socket_type="NodeSocketBool").default_value = True
    ng.interface.new_socket("Weight", in_out="OUTPUT", socket_type="NodeSocketFloat")
    nodes, links = ng.nodes, ng.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "RELATIVE"
    info.inputs["Object"].default_value = f
    params = nodes.new("GeometryNodeGroup")
    params.node_tree = core.field()
    params.name = params.label = PARAMS_NODE
    for name in ("Previous", "First"):
        links.new(gin.outputs[name], params.inputs[name])
    links.new(info.outputs["Transform"], params.inputs["Transform"])
    links.new(params.outputs[0], gout.inputs[0])
    gin.location, info.location, params.location, gout.location = (-400, 0), (-400, -200), (0, 0), (300, 0)
    return ng


def add_field(shape="Sphere", effectors=None, name=None, params=None, location=(0, 0, 0), size=3.0,
              blend="Multiply"):
    """New field object (shape sized by its scale), linked into each owner's field list."""
    shape = choice(shape, FALLOFF_SHAPES, "shape")
    f = new_empty(name or f"{shape} Field", "SPHERE", size, location)
    tag(f, **{KEY_KIND: Kind.FIELD, KEY_TYPE: shape.lower()})
    f[KEY_GROUP] = _field_wrapper(f)
    set_params(f, {"Falloff": shape, "Blend": blend, **(params or {})})
    for owner in get_objects(effectors):
        link_field(f, owner)
    select_only(f)
    return f


def _layer_nodes(owner):
    """The owner's layer nodes in order. O(nodes in its wrapper)."""
    ng = owner[KEY_GROUP]
    layers = [n for n in ng.nodes if n.name.startswith(LAYER_NODE_PREFIX)]
    return sorted(layers, key=lambda n: int(n.name[len(LAYER_NODE_PREFIX):]))


def fields_of(owner):
    """Names of the fields in an owner's list, in order. O(N + layers)."""
    owners = group_owners()
    return [owners[n.node_tree.name].name for n in _layer_nodes(get_object(owner)) if n.node_tree.name in owners]


def _set_layers(owner, fields):
    """Rebuild the owner's chain: field_1 -> field_2 -> ... -> Params.Layers. O(fields)."""
    ng = owner[KEY_GROUP]
    for n in _layer_nodes(owner):
        ng.nodes.remove(n)
    params = ng.nodes[PARAMS_NODE]
    prev = None
    for i, f in enumerate(fields):
        n = ng.nodes.new("GeometryNodeGroup")
        n.node_tree = f[KEY_GROUP]
        n.name = n.label = f"{LAYER_NODE_PREFIX}{i}"
        n.location = (-700 + 180 * i, -400)
        n.inputs["First"].default_value = prev is None
        if prev is not None:
            ng.links.new(prev.outputs[0], n.inputs["Previous"])
        prev = n
    sock = params.inputs[core.LAYERS_INPUT]
    for link in list(sock.links):
        ng.links.remove(link)
    if prev is not None:
        ng.links.new(prev.outputs[0], sock)
    owner.update_tag()


def _owner(ref):
    o = get_object(ref)
    if o.get(KEY_KIND) not in _LAYERED:
        raise ValueError(f"{o.name} is not an effector or a Geometry Nodes deformer")
    return o


def link_field(field, owner):
    """Append a field to the owner's list. The owner's own falloff becomes Infinite on the first field,
    since the fields now define where it acts (as in C4D)."""
    f, o = get_object(field), _owner(owner)
    current = [get_object(n) for n in fields_of(o)]
    if f in current:
        return fields_of(o)
    if not current:
        set_params(o, {"Falloff": "Infinite"})
    _set_layers(o, current + [f])
    return fields_of(o)


def unlink_field(field, owner):
    f, o = get_object(field), _owner(owner)
    _set_layers(o, [x for x in map(get_object, fields_of(o)) if x != f])
    return fields_of(o)


def field_users(field):
    """Owners whose list contains this field. O(N x wrapper nodes)."""
    group = get_object(field)[KEY_GROUP]
    return [o for o in bpy.data.objects if o.get(KEY_KIND) in _LAYERED
            and any(n.node_tree == group for n in _layer_nodes(o))]
