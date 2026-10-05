"""Cloners: an object whose MB Cloner modifier instances its source collection."""

import bmesh
import bpy

from ..catalog import CLONER_MOD, CLONER_MODES, KEY_CLONES, KEY_KIND, KEY_TYPE, Kind
from ..nodes import cloners, generators
from .generator import MOD_NAMES
from .material import mograph_material
from .objects import (add_nodes_modifier, choice, get_object, get_objects, move_to_collection, new_mesh_object,
                      select_only, sources_root, tag)
from .params import list_params, set_params

_KEEP_ON_MODE_SWITCH = ("Collection", "Order", "Seed", "Count")


def _default_clone(name):
    """A 1 m cube showing MoGraph colors, used when a cloner is made with no objects."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mograph_material())
    return bpy.data.objects.new(name, me)


def create_cloner(mode="linear", objects=None, name=None, params=None, location=None):
    """New cloner; `objects` become its children (moved to a hidden source collection, like C4D)."""
    mode = choice(mode, CLONER_MODES, "mode")
    srcs = get_objects(objects)
    if location is None and srcs:
        location = srcs[0].matrix_world.translation.copy()
    c = tag(new_mesh_object(name or "Cloner", location), **{KEY_KIND: Kind.CLONER, KEY_TYPE: mode})
    coll = bpy.data.collections.new(f"{c.name} Clones")
    sources_root().children.link(coll)
    c[KEY_CLONES] = coll
    move_to_collection(srcs or [_default_clone(f"{c.name} Cube")], coll)
    add_nodes_modifier(c, CLONER_MOD, cloners.BUILDERS[mode]())
    add_nodes_modifier(c, MOD_NAMES["display"], generators.BUILDERS["display"]())
    set_params(c, {"Collection": coll.name, **(params or {})})
    select_only(c)
    return c


def set_cloner_mode(ref, mode):
    """Switch between linear/radial/grid/object/spline, keeping settings the new mode also has."""
    c = get_object(ref)
    mode = choice(mode, CLONER_MODES, "mode")
    keep = {p.name: p.get() for p in list_params(c, CLONER_MOD) if p.name in _KEEP_ON_MODE_SWITCH}
    c.modifiers[CLONER_MOD].node_group = cloners.BUILDERS[mode]()
    c[KEY_TYPE] = mode
    names = {p.name for p in list_params(c, CLONER_MOD)}
    set_params(c, {k: v for k, v in keep.items() if k in names}, modifier=CLONER_MOD)
    return c


def add_clone_objects(ref, objects):
    c = get_object(ref)
    move_to_collection(get_objects(objects), c[KEY_CLONES])
    c.update_tag()
    return [o.name for o in c[KEY_CLONES].objects]


def create_matrix(mode="grid", name=None, params=None, location=None):
    """C4D Matrix object: a cloner that only provides positions (small boxes in the viewport, nothing in
    renders). Effectors work on it, and Object-mode cloners can clone onto it (Distribution: Instances)."""
    from .selection import make_matrix  # local: selection imports effector lazily too
    c = create_cloner(mode, name=name or "Matrix", params=params, location=location)
    c[KEY_CLONES].objects[0].scale = (0.2, 0.2, 0.2)
    return make_matrix(c)
