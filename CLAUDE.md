# MoBlend — notes for Claude

C4D-style MoGraph add-on for Blender 5.2 + stdio MCP server. Read README.md for the feature map.

## Layout
- `moblend/catalog.py` — single source of truth for every mode/type/kind list, custom-property keys, name prefixes,
  the version and the socket path. Pure Python: the MCP server loads it by path. Add new types here first.
- `moblend/nodes/util.py` — node-building DSL (`B`, `new_group`, `ensure`, `geometry_group`, `geometry_socket`).
  **Bump `GROUP_VERSION` whenever any group's nodes or interface change**; stale groups are rebuilt.
- `moblend/nodes/core.py` — falloff field, `falloff_group` (effector / GN-deformer scaffold: strength, layers,
  selection, min/max, memory), apply (+ Modify Clone, Deformation), instancer (Blend/Sort, per-clone data,
  children bundle), split_centered, texture and sound helpers.
- `moblend/nodes/{cloners,effectors,deformers,fields,generators}.py` — `BUILDERS` tables (keys must match the
  catalog; a test enforces it). `nodes/formula.py` compiles safe math expressions to nodes.
- `moblend/api/` — the API by domain: `objects` (lookup, modifiers, wrappers, usage index, link-preserving group
  rebuild), `params` (`Param`, list/get/set, `PARAM_SOURCES` hooks for non-modifier settings), `cloner`,
  `selection` (MoGraph Selection/Weight tags, Matrix), `effector` (incl. Formula, Group), `field`, `deformer`,
  `generator` (MoText, Sweep, Volume, Fracture Objects, MoInstance, MoSpline, Spline Mask, Spline Wrap, ...),
  `voronoi` (live Voronoi Fracture, settings in `object.moblend_voronoi`), `connectors`, `loft`, `turtle`,
  `material` (Color, Multi, Beat), `scene` (list, delete, cache). `api/__init__` re-exports and registers.
- Wrapper pattern: effectors, GN deformers, fields and lofts own a wrapper group (`MBFX`/`MBDF`/`MBFL`/`MBLF`)
  with one node named `Params` holding their settings; field chains are layer nodes `MB Layer <i>` in owners.
- `moblend/commands.py` — bridge commands (`register(name, api_fn, aliases, describe)`), `bridge.py` — Unix
  socket server; `mcp/moblend_mcp.py` — stdio MCP server, schemas from catalog enums.
- `docs/MOGRAPH_CHECKLIST.md` — Cinema 4D MoGraph feature checklist; keep it in sync with what ships.
- Dev install: symlink `<blender config>/5.x/scripts/addons/moblend` → `moblend/`; MCP:
  `claude mcp add moblend -s user -- python3 <repo>/mcp/moblend_mcp.py`.

## Standards
- No builtin shadowing (`type`, `object`, `min`, `max`); the MCP's `type`/`object` args are aliased in commands.
- State Big-O in docstrings for anything that scans objects/modifiers (N objects x M modifiers). Use
  `objects.usage_index()` / `group_owners()` for one-pass lookups instead of per-item scans.
- Lint: `uvx ruff check --select E,F,W,B,A,C4,SIM,PIE --line-length 120 .` and
  `uvx pylint --disable=all --enable=duplicate-code --min-similarity-lines=5 moblend mcp tests examples`.

## Blender 5.2 API gotchas (verified)
- Modifier inputs are `mod.properties.inputs.<Socket_N>.value` (not `mod["Socket_N"]`); menu inputs are enums
  of item names.
- Menu sockets on a freshly created group node report no enum items, but assigning the name string works. Use
  `api/params.py: menu_items()`, which reads the inner Menu Switch.
- Render engine ids: `BLENDER_WORKBENCH`, `BLENDER_EEVEE`, `CYCLES`.
- Collection Info "Reset Children" resets rotation/scale too; the instancer zeroes translation only.
- Simulation zones work inside nested groups (Delay effector).
- A vector socket `default_value` is a live view: copy it (`objects.socket_values`) before rebuilding a group,
  or writing it back is a use-after-free crash. Rebuilding an interface also drops links to its sockets.
- One menu group input must drive a single Menu Switch (several make the menu's items empty).
- Extrude Mesh defaults to Individual; use `generators._solid` for closed extrusions.
- Exact booleans dislike coplanar faces; Mesh Boolean Union/Intersect take every operand on multi-input
  "Mesh 2" (its label changes, the identifier doesn't).

## Testing
Run only the touched suite; each takes seconds (`blender -b --factory-startup -P tests/<suite>.py`, look for
`RESULT PASS`). The GUI can't be screenshotted from an unviewed workspace; `tests/test_ui.py` checks panel draw
code with a recording layout instead. Don't open GUI Blender over the user's working window
(`launch_blender` honours `MOBLEND_HYPR_WORKSPACE` on Hyprland).
