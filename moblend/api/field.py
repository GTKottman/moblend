"""Fields: objects layered into effectors / GN deformers / Group fields (C4D field lists).

A field is an empty with its own wrapper group ("MBFL <name>") whose Params node holds its settings, so
one field can drive many owners. Each owner's wrapper keeps a chain of layer nodes named
LAYER_NODE_PREFIX + order feeding its Params node's Layers input; the chain is the source of truth
(rename-safe). Owners also feed the chain the element count (clones or points), for Step/Sound fields.
"""

import bpy

from ..catalog import (FALLOFF_SHAPES, FIELD_GROUP_PREFIX, FIELD_KINDS, KEY_GROUP, KEY_KIND, KEY_TYPE,
                       LAYER_NODE_PREFIX, PARAMS_NODE, Kind)
from ..nodes import fields
from ..nodes.core import LAYERS_INPUT
from ..nodes.formula import check
from .objects import (choice, get_object, get_objects, group_owners, new_empty, rebuild_params_group,
                      select_only, tag)
from .params import PARAM_SOURCES, Param, set_params

_LAYERED = (Kind.EFFECTOR, Kind.DEFORMER, Kind.FIELD)  # objects whose wrapper takes a field list
_TYPES = {k: k for k in ("time", "step", "object", "shader", "sound", "attribute")}
_COUNT_NODE = "MB LayerCount"
KEY_FORMULA = "mb_formula"
DEFAULT_FORMULA = "0.5 + 0.5 * sin((x + t) * tau)"


def _type_group(f):
    kind = f[KEY_TYPE]
    if kind == "formula":
        return fields.formula_group(f"MB Field Formula {f.name}", f[KEY_FORMULA])
    return fields.BUILDERS[_TYPES.get(kind, "shape")]()


def _field_wrapper(f):
    ng = bpy.data.node_groups.new(f"{FIELD_GROUP_PREFIX}{f.name}", "GeometryNodeTree")
    sockets = (("Previous", "NodeSocketFloat", 1.0), ("First", "NodeSocketBool", True),
               ("Element Count", "NodeSocketInt", 1))
    for name, kind, default in sockets:
        ng.interface.new_socket(name, in_out="INPUT", socket_type=kind).default_value = default
    ng.interface.new_socket("Weight", in_out="OUTPUT", socket_type="NodeSocketFloat")
    nodes, links = ng.nodes, ng.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "RELATIVE"
    info.inputs["Object"].default_value = f
    params = nodes.new("GeometryNodeGroup")
    params.node_tree = _type_group(f)
    params.name = params.label = PARAMS_NODE
    for name, _, _ in sockets:
        links.new(gin.outputs[name], params.inputs[name])
    links.new(info.outputs["Transform"], params.inputs["Transform"])
    links.new(params.outputs[0], gout.inputs[0])
    gin.location, info.location, params.location, gout.location = (-400, 0), (-400, -200), (0, 0), (300, 0)
    return ng


def add_field(kind="Sphere", effectors=None, name=None, params=None, location=(0, 0, 0), size=3.0, blend="Normal",
              formula=None, shape=None):
    """New field object linked into each owner's field list. `kind`: a falloff shape (Sphere, Box, Cylinder,
    Cone, Capsule, Torus, Linear, Radial, Noise, Random), Solid, Group, or a layer type (Time, Step,
    Object, Shader, Sound, Formula). `shape` is the old name for `kind`."""
    kind = choice(shape or kind, FIELD_KINDS, "field kind")
    f = new_empty(name or f"{kind} Field", "PLAIN_AXES", size, location)
    tag(f, **{KEY_KIND: Kind.FIELD, KEY_TYPE: kind.lower()})
    if kind == "Formula":
        f[KEY_FORMULA] = formula or DEFAULT_FORMULA
    f[KEY_GROUP] = _field_wrapper(f)
    values = {"Blend": blend, **(params or {})}
    if kind.lower() not in _TYPES and kind != "Formula":
        values = {"Falloff": "Infinite" if kind in ("Solid", "Group") else kind, **values}
    set_params(f, values)
    for owner in get_objects(effectors):
        link_field(f, owner)
    select_only(f)
    return f


# ---------------------------------------------------------------- field lists

def _layer_nodes(owner):
    """The owner's layer nodes in order. O(nodes in its wrapper)."""
    ng = owner[KEY_GROUP]
    layers = [n for n in ng.nodes if n.name.startswith(LAYER_NODE_PREFIX)]
    return sorted(layers, key=lambda n: int(n.name[len(LAYER_NODE_PREFIX):]))


def fields_of(owner):
    """Names of the fields in an owner's list, in order. O(N + layers)."""
    owners = group_owners()
    return [owners[n.node_tree.name].name for n in _layer_nodes(get_object(owner)) if n.node_tree.name in owners]


def _count_socket(owner, ng):
    """Element count for the chain: a field passes its own through; others count clones or points."""
    gin = next(n for n in ng.nodes if n.bl_idname == "NodeGroupInput")
    if owner.get(KEY_KIND) == Kind.FIELD:
        return gin.outputs["Element Count"]
    sizes = []
    for component, output in (("INSTANCES", "Instance Count"), ("MESH", "Point Count")):
        n = ng.nodes.new("GeometryNodeAttributeDomainSize")
        n.component, n.name = component, f"{_COUNT_NODE} {component}"
        ng.links.new(gin.outputs[0], n.inputs[0])
        sizes.append(n.outputs[output])
    most = ng.nodes.new("FunctionNodeIntegerMath")
    most.operation, most.name = "MAXIMUM", f"{_COUNT_NODE} Max"
    ng.links.new(sizes[0], most.inputs[0])
    ng.links.new(sizes[1], most.inputs[1])
    return most.outputs[0]


def _set_layers(owner, chain):
    """Rebuild the owner's chain: field_1 -> field_2 -> ... -> Params.Layers. O(fields)."""
    ng = owner[KEY_GROUP]
    for n in [n for n in ng.nodes if n.name.startswith((LAYER_NODE_PREFIX, _COUNT_NODE))]:
        ng.nodes.remove(n)
    sock = ng.nodes[PARAMS_NODE].inputs[LAYERS_INPUT]
    for link in list(sock.links):
        ng.links.remove(link)
    count = _count_socket(owner, ng) if chain else None
    prev = None
    for i, f in enumerate(chain):
        n = ng.nodes.new("GeometryNodeGroup")
        n.node_tree = f[KEY_GROUP]
        n.name = n.label = f"{LAYER_NODE_PREFIX}{i}"
        n.location = (-700 + 180 * i, -400)
        n.inputs["First"].default_value = prev is None
        ng.links.new(count, n.inputs["Element Count"])
        if prev is not None:
            ng.links.new(prev.outputs[0], n.inputs["Previous"])
        prev = n
    if prev is not None:
        ng.links.new(prev.outputs[0], sock)
    owner.update_tag()


def _owner(ref):
    o = get_object(ref)
    if o.get(KEY_KIND) not in _LAYERED:
        raise ValueError(f"{o.name} is not an effector, a Geometry Nodes deformer or a field")
    return o


def _contains(tree, target, seen=None):
    """Does node tree `tree` use `target` anywhere inside (nested groups)? O(nodes reachable)."""
    seen = seen if seen is not None else set()
    if tree == target:
        return True
    seen.add(tree.name)
    return any(n.bl_idname == "GeometryNodeGroup" and n.node_tree and n.node_tree.name not in seen
               and _contains(n.node_tree, target, seen) for n in tree.nodes)


def link_field(field, owner, take_over=True):
    """Append a field to the owner's list. With `take_over`, an effector/deformer's own falloff becomes
    Infinite on its first field, since the fields now define where it acts (as in C4D)."""
    f, o = get_object(field), _owner(owner)
    if f == o or _contains(f[KEY_GROUP], o[KEY_GROUP]):
        raise ValueError(f"Linking {f.name} into {o.name} would make a loop")
    current = [get_object(n) for n in fields_of(o)]
    if f in current:
        return fields_of(o)
    if take_over and not current and o.get(KEY_KIND) != Kind.FIELD:
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
    return [o for o in bpy.data.objects if o.get(KEY_KIND) in _LAYERED and o.get(KEY_GROUP) is not None
            and any(n.node_tree == group for n in _layer_nodes(o))]


# ---------------------------------------------------------------- formula fields

def _set_formula(f):
    """Rebuild a formula field's type group from its formula text (validated first)."""
    check(f[KEY_FORMULA], fields.FORMULA_VARIABLES)
    rebuild_params_group(f, lambda: _type_group(f))


def _formula_params(f):
    return [Param("Formula", f, f'["{KEY_FORMULA}"]', "STRING", on_change=_set_formula,
                  desc="Variables: x y z (field space), id, count, t (seconds), f (frame)")]


PARAM_SOURCES.append((lambda o: o.get(KEY_KIND) == Kind.FIELD and KEY_FORMULA in o, _formula_params))
assert all(s in FIELD_KINDS for s in FALLOFF_SHAPES if s != "Infinite")
