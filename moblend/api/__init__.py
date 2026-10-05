"""MoBlend's high-level API, used by the UI operators and the MCP bridge alike.

Conventions: objects are passed by name (or bpy object), angles are in degrees,
colors are [r, g, b(, a)] in 0..1 or "#rrggbb" hex strings.
"""

from ..catalog import SOURCES_COLLECTION as SOURCES  # noqa: F401
from .objects import get_object, mb_kind, users_of  # noqa: F401
from .params import Param, get_params, list_params, parse_color, set_params  # noqa: F401
from .material import assign as assign_material, mograph_material, set_color_material, solid_material  # noqa: F401
from .cloner import add_clone_objects, create_cloner, set_cloner_mode  # noqa: F401
from .effector import add_effector, effectors_of, link_effector, move_effector, unlink_effector  # noqa: F401
from .deformer import add_deformer, attach_deformer  # noqa: F401
from .generator import (add_boole, add_extrude, add_fracture, add_lathe, add_subdivision,  # noqa: F401
                        add_symmetry, add_tracer, create_motext, create_sweep)
from .voronoi import SETTINGS as VORONOI_SETTINGS, voronoi_fracture  # noqa: F401
from .scene import delete, evaluated_stats, list_mograph  # noqa: F401

# kind -> function(object, **options); used by the UI and the MCP bridge.
GENERATORS = {"fracture": add_fracture, "voronoi": voronoi_fracture, "tracer": add_tracer, "lathe": add_lathe,
              "extrude": add_extrude, "symmetry": add_symmetry, "boole": add_boole, "subdivision": add_subdivision}
