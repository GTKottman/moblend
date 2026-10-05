# MoBlend — notes for Claude

C4D-style MoGraph add-on for Blender 5.2 + stdio MCP server. Read README.md for the feature map.

## Layout
- `moblend/catalog.py` — single source of truth for every mode/type list, custom-property keys, name prefixes
  and the socket path. Pure Python: the MCP server loads it by path. Add new types here first.
- `moblend/nodes/util.py` — node-building DSL (`B`, `new_group`, `ensure`, `geometry_group`). **Bump
  `GROUP_VERSION` whenever any group's nodes or interface change**; stale groups are rebuilt (modifier values reset).
- `moblend/nodes/core.py` — falloff field, `falloff_group` (shared scaffold of every effector and GN deformer),
  apply, instancer, split_centered. `cloners/effectors/deformers/generators.py` hold `BUILDERS` tables whose
  keys must match the catalog (a test enforces it).
- `moblend/api/` — the API, by domain: `objects` (lookup, modifiers, wrappers, usage index), `params`
  (`Param`, list/get/set), `cloner`, `effector`, `deformer`, `generator` (`GENERATORS` registry used by UI and
  MCP), `material`, `scene`. `api/__init__` re-exports the public names.
- Effectors and GN deformers: each object gets a wrapper group (`MBFX <name>` / `MBDF <name>`) with one node named
  `Params` whose socket values are the shared parameters; stored in `obj["mb_group"]`.
- `moblend/commands.py` — bridge commands: mostly `register(name, api_fn, aliases, describe)`; results go
  through `_jsonable`. `bridge.py` — Unix socket server, runs commands on the main thread via a timer.
- `mcp/moblend_mcp.py` — hand-rolled MCP over stdio (no deps); tool schemas use catalog enums.
- Dev install: symlink `<blender config>/5.x/scripts/addons/moblend` → `moblend/` and enable it; register the
  MCP server with `claude mcp add moblend -s user -- python3 <repo>/mcp/moblend_mcp.py`.

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

## Testing
Run only the touched suite; each takes seconds (`blender -b --factory-startup -P tests/<suite>.py`, look for
`RESULT PASS`). The GUI can't be screenshotted from an unviewed workspace; `tests/test_ui.py` checks panel draw
code with a recording layout instead. Don't open GUI Blender over the user's working window
(`launch_blender` honours `MOBLEND_HYPR_WORKSPACE` on Hyprland).
