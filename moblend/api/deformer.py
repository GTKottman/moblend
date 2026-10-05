"""Deformers placed by an empty: Simple Deform (driven by the empty's Angle/Factor) or GN wrappers."""

import math

from ..catalog import (DEFORMER_GROUP_PREFIX, DEFORMER_MOD_PREFIX, DEFORMER_TYPES, KEY_AXIS, KEY_GROUP, KEY_KIND,
                       KEY_TYPE, SIMPLE_DEFORMERS, Kind, AXES)
from ..nodes import deformers
from .generator import LAST
from .objects import (add_nodes_modifier, choice, get_object, get_objects, keep_last, make_wrapper, mb_kind,
                      new_empty, select_only, tag)
from .params import set_params

# Simple deformer types -> (custom property, default, UI options).
_SIMPLE_PROP = {
    "bend": ("Angle", math.radians(90.0), {"subtype": "ANGLE", "soft_min": -2 * math.pi, "soft_max": 2 * math.pi}),
    "twist": ("Angle", math.radians(90.0), {"subtype": "ANGLE", "soft_min": -2 * math.pi, "soft_max": 2 * math.pi}),
    "taper": ("Factor", 0.5, {"soft_min": -2.0, "soft_max": 2.0}),
    "stretch": ("Factor", 0.5, {"soft_min": -2.0, "soft_max": 2.0}),
}


def add_deformer(deformer_type="bend", targets=None, name=None, params=None, location=None, size=1.0, axis="Z"):
    t = choice(deformer_type, DEFORMER_TYPES, "deformer type")
    tgts = get_objects(targets)
    if location is None and tgts:
        location = tgts[0].matrix_world.translation.copy()
    simple = t in SIMPLE_DEFORMERS
    d = new_empty(name or t.title(), "ARROWS" if simple else "PLAIN_AXES", size, location)
    tag(d, **{KEY_TYPE: t, KEY_KIND: Kind.SIMPLE_DEFORMER if simple else Kind.DEFORMER})
    if simple:
        d[KEY_AXIS] = choice(axis, AXES, "axis")
        key, default, ui = _SIMPLE_PROP[t]
        d[key] = default
        d.id_properties_ui(key).update(**ui)
    else:
        d[KEY_GROUP] = make_wrapper(DEFORMER_GROUP_PREFIX, d, deformers.BUILDERS[t](), realize=True)
    for x in tgts:
        attach_deformer(d, x)
    if params:
        set_params(d, params)
    select_only(d)
    return d


def attach_deformer(deformer, target):
    d, t = get_object(deformer), get_object(target)
    name = f"{DEFORMER_MOD_PREFIX}{d.name}"
    if mb_kind(d) != Kind.SIMPLE_DEFORMER:
        add_nodes_modifier(t, name, d[KEY_GROUP])
        keep_last(t, LAST)
        return t
    m = t.modifiers.new(name, "SIMPLE_DEFORM")
    m.deform_method, m.origin, m.deform_axis = SIMPLE_DEFORMERS[d[KEY_TYPE]], d, d.get(KEY_AXIS, "Z")
    key = _SIMPLE_PROP[d[KEY_TYPE]][0]
    drv = t.driver_add(f'modifiers["{m.name}"].{key.lower()}').driver
    drv.type = "AVERAGE"  # a plain variable copy: no Python expression, so no auto-run needed
    var = drv.variables.new()
    var.targets[0].id = d
    var.targets[0].data_path = f'["{key}"]'
    keep_last(t, LAST)
    return t
