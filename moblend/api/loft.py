"""Loft: skin a surface through profile curves in a given order (C4D Loft).

Geometry Nodes' Collection Info returns objects sorted by name, so each loft owns
a small wrapper group that reads its profiles one by one, tags each with its
order (curve attribute mb_profile) and feeds the shared "MB Loft" group.
"""

import bpy

from ..catalog import GROUP_PREFIX, KEY_GROUP, KEY_KIND, KEY_PROFILES, PARAMS_NODE, Kind
from ..nodes import generators
from .objects import (add_nodes_modifier, get_object, get_objects, new_mesh_object, restore_socket_values,
                      select_only, socket_values, tag)
from .params import set_params

LOFT_GROUP_PREFIX = "MBLF "
MOD_NAME = "MB Loft"


def _fill_wrapper(ng, profiles):
    """(Re)build the wrapper: Object Info per profile -> store order -> join -> Params. O(profiles)."""
    ng.nodes.clear()
    nodes, links = ng.nodes, ng.links
    join = nodes.new("GeometryNodeJoinGeometry")
    for k, prof in enumerate(profiles):
        info = nodes.new("GeometryNodeObjectInfo")
        info.transform_space = "RELATIVE"
        info.inputs["Object"].default_value = prof
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type, store.domain = "INT", "CURVE"
        store.inputs["Name"].default_value = "mb_profile"
        store.inputs["Value"].default_value = k
        links.new(info.outputs["Geometry"], store.inputs["Geometry"])
        links.new(store.outputs[0], join.inputs[0])
        info.location, store.location = (-600, -k * 220), (-350, -k * 220)
    params = nodes.new("GeometryNodeGroup")
    params.node_tree = generators.BUILDERS["loft"]()
    params.name = params.label = PARAMS_NODE
    out = nodes.new("NodeGroupOutput")
    links.new(join.outputs[0], params.inputs[0])
    links.new(params.outputs[0], out.inputs[0])
    params.location, out.location = (0, 0), (250, 0)
    return params


def create_loft(profiles, name=None, params=None):
    """Surface through `profiles` (curve objects, in this order). Params: Points, Rows, Smooth, Caps, Flip."""
    profs = get_objects(profiles)
    if len(profs) < 2:
        raise ValueError("A loft needs at least two profile curves")
    o = tag(new_mesh_object(name or "Loft", (0, 0, 0)), **{KEY_KIND: Kind.LOFT})
    ng = bpy.data.node_groups.new(f"{LOFT_GROUP_PREFIX}{o.name}", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    o[KEY_GROUP] = ng
    set_loft_profiles(o, profs)
    add_nodes_modifier(o, MOD_NAME, ng)
    if params:
        set_params(o, params)
    select_only(o)
    return o


def set_loft_profiles(ref, profiles):
    """Replace the loft's profiles (order matters), keeping its settings. O(profiles + params)."""
    o = get_object(ref)
    ng = o[KEY_GROUP]
    old = ng.nodes.get(PARAMS_NODE)
    keep = socket_values(old) if old else {}
    restore_socket_values(_fill_wrapper(ng, get_objects(profiles)), keep)
    o[KEY_PROFILES] = [p.name for p in get_objects(profiles)]
    o.update_tag()
    return list(o[KEY_PROFILES])


def sort_along_spread(objects):
    """Order objects along the axis where their positions spread most (for unordered selections). O(n log n)."""
    objs = get_objects(objects)
    locs = [x.matrix_world.translation for x in objs]
    axis = max(range(3), key=lambda a: max(v[a] for v in locs) - min(v[a] for v in locs))
    return sorted(objs, key=lambda x: x.matrix_world.translation[axis])


assert MOD_NAME.startswith(GROUP_PREFIX)  # the sidebar lists MB modifiers by this prefix
