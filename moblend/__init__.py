"""MoBlend: Cinema 4D-style MoGraph for Blender (cloners, effectors, fields,
MoText, fracture, sweep, deformers) built on Geometry Nodes, plus a local
bridge so AI agents can drive it over MCP."""

bl_info = {
    "name": "MoBlend",
    "author": "MoBlend contributors",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Add > MoBlend, View3D > Sidebar > MoBlend",
    "description": "MoGraph-style cloners, effectors, fields, MoText, fracture, sweep and deformers + MCP bridge",
    "category": "Animation",
    "doc_url": "https://github.com/GTKottman/moblend",
    "tracker_url": "https://github.com/GTKottman/moblend/issues",
}

import bpy  # noqa: E402

from . import api, bridge, commands, ui  # noqa: E402,F401


def _autostart():
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        if addon is None or getattr(addon.preferences, "autostart", True):
            bridge.start()
    except Exception as e:  # bridge trouble must never block the add-on
        print("MoBlend bridge autostart failed:", e)
    return None


def register():
    for c in ui.CLASSES:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_add.append(ui.add_menu)
    bpy.app.timers.register(_autostart, first_interval=0.5, persistent=True)


def unregister():
    bridge.stop()
    bpy.types.VIEW3D_MT_add.remove(ui.add_menu)
    for c in reversed(ui.CLASSES):
        bpy.utils.unregister_class(c)
