"""Effectors: an empty plus a wrapper group; linking adds that group as a modifier on a target."""

from ..catalog import (DEFORMER_MOD_PREFIX, EFFECTOR_GROUP_PREFIX, EFFECTOR_MOD_PREFIX, EFFECTOR_TYPES, KEY_GROUP,
                       KEY_KIND, KEY_TYPE, Kind)
from ..nodes import effectors
from .generator import MOD_NAMES
from .objects import (choice, detach, get_object, get_objects, group_owners, make_wrapper, mb_kind, new_empty,
                      select_only, tag, uses)
from .params import set_params

DEFAULT_SIZE = 3.0


def add_effector(effector_type="plain", name=None, cloners=None, params=None, location=(0, 0, 0), size=None,
                 falloff=None):
    """New effector linked to `cloners`. `size` is the falloff radius (object scale)."""
    t = choice(effector_type, EFFECTOR_TYPES, "effector type")
    e = new_empty(name or f"{t.title()} Effector", "PLAIN_AXES", DEFAULT_SIZE if size is None else size, location)
    tag(e, **{KEY_KIND: Kind.EFFECTOR, KEY_TYPE: t})
    e[KEY_GROUP] = make_wrapper(EFFECTOR_GROUP_PREFIX, e, effectors.BUILDERS[t]())
    shape = falloff or effectors.DEFAULT_FALLOFF.get(t)
    set_params(e, {**({"Falloff": shape} if shape else {}), **(params or {})})
    for target in get_objects(cloners):
        link_effector(e, target)
    select_only(e)
    return e


def _is_effector_mod(m):
    return m.type == "NODES" and m.node_group is not None and m.node_group.name.startswith(EFFECTOR_GROUP_PREFIX)


def _is_post_mod(m):
    """Modifiers that must stay below effectors: deformers and the tracer."""
    return m.type == "SIMPLE_DEFORM" or m.name.startswith((MOD_NAMES["tracer"], DEFORMER_MOD_PREFIX))


def link_effector(effector, target):
    """Append the effector to the target's list (above deformers/tracer). Idempotent. O(M)."""
    e, t = get_object(effector), get_object(target)
    if mb_kind(e) != Kind.EFFECTOR:
        raise ValueError(f"{e.name} is not an effector")
    if any(uses(m, e) for m in t.modifiers):
        return t
    m = t.modifiers.new(f"{EFFECTOR_MOD_PREFIX}{e.name}", "NODES")
    m.node_group = e[KEY_GROUP]
    mods = list(t.modifiers)
    first_post = next((i for i, x in enumerate(mods[:-1]) if _is_post_mod(x)), None)
    if first_post is not None:
        t.modifiers.move(len(mods) - 1, first_post)
    return t


def unlink_effector(effector, target):
    t = get_object(target)
    detach(get_object(effector), t)
    return t


def move_effector(target, modifier, direction):
    """Swap an effector with its neighbour in the list (direction -1 up, +1 down).

    Only effector modifiers trade places, so an effector can never move above the
    generator it acts on. Returns False when there is nothing to swap with. O(M).
    """
    t = get_object(target)
    i = t.modifiers.find(modifier)
    j = i + direction
    if i < 0 or not 0 <= j < len(t.modifiers) or not (_is_effector_mod(t.modifiers[i])
                                                       and _is_effector_mod(t.modifiers[j])):
        return False
    t.modifiers.move(i, j)
    return True


def effectors_of(target):
    """The target's effector list in stack order. O(N + M) via one owner map."""
    t = get_object(target)
    owners = group_owners()
    return [{"modifier": m.name, "effector": getattr(owners.get(m.node_group.name), "name", None),
             "enabled": m.show_viewport} for m in t.modifiers if _is_effector_mod(m)]
