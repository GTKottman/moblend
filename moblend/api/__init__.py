"""MoBlend's high-level API, used by the UI operators and the MCP bridge alike.

Conventions: objects are passed by name (or bpy object), angles are in degrees,
colors are [r, g, b(, a)] in 0..1 or "#rrggbb" hex strings.
"""

from ..catalog import SOURCES_COLLECTION as SOURCES  # noqa: F401
from .objects import get_object, mb_kind, users_of  # noqa: F401
from .params import Param, get_params, list_params, parse_color, set_params  # noqa: F401
from .material import assign as assign_material, mograph_material, set_color_material, solid_material  # noqa: F401
from .cloner import add_clone_objects, create_cloner, create_matrix, set_cloner_mode  # noqa: F401
from .selection import (clone_positions, hide_selected_clones, is_matrix, make_matrix, parse_indices,  # noqa: F401
                        selection_from_edit_mode, set_clone_selection, set_clone_weights, sync_clone_points)
from .effector import (add_effector, add_group_effector, effectors_of, group_members, link_effector,  # noqa: F401
                       move_effector, unlink_effector)
from .deformer import add_deformer, attach_deformer  # noqa: F401
from .generator import (add_boole, add_extrude, add_fracture, add_lathe, add_subdivision,  # noqa: F401
                        add_symmetry, add_tracer, add_volume_objects, create_motext, create_sweep,
                        create_volume_builder)
from .field import add_field, field_users, fields_of, link_field, unlink_field  # noqa: F401
from .loft import create_loft, set_loft_profiles, sort_along_spread  # noqa: F401
from . import voronoi as _voronoi
from .voronoi import SECTIONS as VORONOI_SECTIONS, is_voronoi, restore as restore_fracture, voronoi_fracture  # noqa: F401
from .connectors import make_dynamic  # noqa: F401
from .scene import delete, evaluated_stats, list_mograph  # noqa: F401



def register():
    """Register the API's own Blender types (Voronoi settings). Called by the add-on and by tests."""
    _voronoi.register()


def unregister():
    _voronoi.unregister()


# kind -> function(object, **options); used by the UI and the MCP bridge.
GENERATORS = {"fracture": add_fracture, "voronoi": voronoi_fracture, "tracer": add_tracer, "lathe": add_lathe,
              "extrude": add_extrude, "symmetry": add_symmetry, "boole": add_boole, "subdivision": add_subdivision}
