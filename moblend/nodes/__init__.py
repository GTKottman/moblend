"""Generated Geometry Nodes groups. Builders are lazy: a group is built on first use."""

from . import core, cloners, effectors, deformers, fields, generators

TABLES = {"cloner": cloners.BUILDERS, "effector": effectors.BUILDERS, "deformer": deformers.BUILDERS,
          "generator": generators.BUILDERS, "field": fields.BUILDERS}


def build_all():
    """Build every MoBlend node group; returns them. O(total nodes)."""
    groups = [f() for f in (core.falloff, core.apply, core.instancer, core.split_centered)]
    for table in TABLES.values():
        groups += [f() for f in table.values()]
    return groups
