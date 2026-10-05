"""Scene-wide queries and cleanup."""

import bpy

from ..catalog import (DEFORMER_MOD_PREFIX, EFFECTOR_MOD_PREFIX, GROUP_PREFIX, KEY_CLONES, KEY_GROUP,
                       KEY_TYPE, Kind)
from .objects import detach, get_object, mb_kind, usage_index, users_of

_OWNERS = (Kind.EFFECTOR, Kind.DEFORMER, Kind.SIMPLE_DEFORMER)
_MB_MOD_PREFIXES = (GROUP_PREFIX, EFFECTOR_MOD_PREFIX, DEFORMER_MOD_PREFIX)


def list_mograph():
    """Every MoBlend object with its links. One O(N x M) pass (usage index), not one per effector."""
    usage = usage_index()
    res = []
    for o in bpy.data.objects:
        k = mb_kind(o)
        if not k and not any(m.name.startswith(_MB_MOD_PREFIXES) for m in o.modifiers):
            continue
        item = {"name": o.name, "kind": k or "object", "type": o.get(KEY_TYPE, "")}
        if k in _OWNERS:
            item["affects"] = usage.get(o.name, [])
        else:
            item["modifiers"] = [m.name for m in o.modifiers]
            if k == Kind.CLONER:
                item["clones"] = [s.name for s in o[KEY_CLONES].objects]
        res.append(item)
    return res


def delete(ref):
    """Delete a MoBlend object cleanly: owners detach from targets; cloners release their children."""
    o = get_object(ref)
    k, name = mb_kind(o), o.name
    if k in _OWNERS:
        for t in users_of(o):
            detach(o, t)
        if o.get(KEY_GROUP) is not None:
            bpy.data.node_groups.remove(o[KEY_GROUP])
    elif k == Kind.CLONER and o.get(KEY_CLONES) is not None:
        coll = o[KEY_CLONES]
        scene_coll = bpy.context.scene.collection
        for s in tuple(coll.objects):
            coll.objects.unlink(s)
            scene_coll.objects.link(s)
            s.location = o.location
        bpy.data.collections.remove(coll)
    bpy.data.objects.remove(o)
    return name


def evaluated_stats(ref):
    """Instance / vertex / face counts after modifiers. O(instances in the scene)."""
    o = get_object(ref)
    dg = bpy.context.evaluated_depsgraph_get()
    stats = {"instances": sum(1 for inst in dg.object_instances
                              if inst.is_instance and inst.parent and inst.parent.original == o)}
    ev = o.evaluated_get(dg)
    if ev.type == "MESH":
        me = ev.to_mesh()
        stats.update(vertices=len(me.vertices), faces=len(me.polygons))
        ev.to_mesh_clear()
    return stats
