"""Names shared by the add-on and the MCP server.

Pure Python (no bpy), so mcp/moblend_mcp.py can load it outside Blender. Every
list of modes/types and every naming convention lives here exactly once.
"""

import os
import tempfile

VERSION = "0.2.0"  # bl_info and blender_manifest.toml must match (Blender reads them as literals; a test checks)

CLONER_MODES = ("linear", "radial", "grid", "honeycomb", "object", "spline")
EFFECTOR_TYPES = ("plain", "random", "step", "noise", "wave", "time", "target", "delay", "inheritance", "sound",
                  "formula", "shader", "spline", "volume", "push_apart")
FALLOFF_SHAPES = ("Infinite", "Sphere", "Box", "Cylinder", "Cone", "Capsule", "Torus", "Linear", "Radial", "Noise",
                  "Random")
FIELD_BLENDS = ("Normal", "Multiply", "Max", "Min", "Add", "Subtract", "Screen", "Average", "Difference")
# Field object kinds: falloff shapes ("Solid" = Infinite, "Group" = Infinite holding its own field list)
# plus layer types.
FIELD_KINDS = ("Solid", "Group") + tuple(s for s in FALLOFF_SHAPES if s != "Infinite") + (
    "Time", "Step", "Object", "Shader", "Sound", "Formula", "Attribute")
SIMPLE_DEFORMERS = {"bend": "BEND", "twist": "TWIST", "taper": "TAPER", "stretch": "STRETCH"}
GN_DEFORMERS = ("wave", "spherify", "shear", "bulge", "displace", "moextrude")
DEFORMER_TYPES = tuple(SIMPLE_DEFORMERS) + GN_DEFORMERS
GENERATOR_KINDS = ("fracture", "voronoi", "tracer", "lathe", "extrude", "symmetry", "boole", "subdivision")
PRIMITIVES = ("cube", "sphere", "icosphere", "cylinder", "cone", "torus", "plane", "monkey",
              "circle_curve", "bezier_curve", "spiral_curve")
AXES = ("X", "Y", "Z")


class Kind:
    """Values of the KEY_KIND custom property on MoBlend objects."""
    CLONER = "cloner"
    EFFECTOR = "effector"
    DEFORMER = "deformer"              # Geometry Nodes deformer (has a wrapper group)
    SIMPLE_DEFORMER = "simple_deformer"  # Blender Simple Deform driven by the empty
    MOTEXT = "motext"
    SWEEP = "sweep"
    FRACTURE = "fracture"
    VOLUME = "volume"
    LOFT = "loft"
    FIELD = "field"
    MOSPLINE = "mospline"
    MOINSTANCE = "moinstance"


# Custom properties stored on objects.
KEY_KIND = "mb_kind"
KEY_TYPE = "mb_type"
KEY_GROUP = "mb_group"    # wrapper node group of an effector / GN deformer
KEY_CLONES = "mb_clones"  # a cloner's source collection
KEY_VOLUME_SETS = {"add": "mb_volume_add", "subtract": "mb_volume_subtract"}  # a volume builder's collections
KEY_AXIS = "mb_axis"      # simple deformer axis
KEY_VERSION = "mb_version"
KEY_PROFILES = "mb_profiles"  # a loft's profile object names, in order
KEY_SOURCE = "mb_source"  # original mesh kept by Voronoi Fracture for re-fracturing

# Node group and modifier names.
GROUP_PREFIX = "MB "              # shared, generated node groups ("MB Falloff", ...)
EFFECTOR_GROUP_PREFIX = "MBFX "   # one wrapper per effector object
DEFORMER_GROUP_PREFIX = "MBDF "   # one wrapper per GN deformer object
FIELD_GROUP_PREFIX = "MBFL "      # one wrapper per Field object
LAYER_NODE_PREFIX = "MB Layer "   # field layer nodes inside an effector/deformer wrapper, numbered in order
EFFECTOR_MOD_PREFIX = "MBE "      # an effector's modifier on a target
DEFORMER_MOD_PREFIX = "MBD "      # a deformer's modifier on a target
CLONER_MOD = "MB Cloner"
PARAMS_NODE = "Params"            # node inside a wrapper whose inputs are the parameters

COLOR_ATTR = "mb_color"           # per-clone color written by effectors
COLOR_MATERIAL = "MB MoGraph Color"
SOURCES_COLLECTION = "MoBlend Sources"


def socket_path():
    """Unix socket the bridge listens on (a file, never a network port)."""
    return os.environ.get("MOBLEND_SOCKET") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "moblend.sock")
