# MoBlend

**Cinema 4D-style MoGraph for Blender 5.x**: cloners, effectors with falloff fields,
MoText, fracture, sweep and deformers. It's built entirely on Geometry Nodes and
comes with an MCP server, so AI agents can build and animate scenes in your live
Blender.

![The MoBlend title in multi-colored bevelled letters in front of a wall of colored cubes](docs/demo.jpg)

*[`examples/demo_scene.py`](examples/demo_scene.py): a wall of 1,900 cloned cubes pushed into
relief by a Noise-mode Random effector and painted by fifteen drifting Plain effectors, bevelled
MoText with a Multi shader color per letter, and a ring of spheres orbiting it.*

## Gallery

One picture per feature, each rendered by a short script. Click a picture to see the exact code that made it.

<!-- gallery:start -->
<table>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#linear-cloner--step-curve"><img src="docs/gallery/cloner_linear_spiral.jpg" alt="Linear cloner · Step Curve"></a><br><sub><b>Linear cloner · Step Curve</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#radial-cloner--wave-effector"><img src="docs/gallery/cloner_radial_wave.jpg" alt="Radial cloner · Wave effector"></a><br><sub><b>Radial cloner · Wave effector</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#grid-cloner--sphere-form--random-noise"><img src="docs/gallery/cloner_grid_sphere.jpg" alt="Grid cloner · sphere form + Random noise"></a><br><sub><b>Grid cloner · sphere form + Random noise</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#honeycomb-cloner--shader-field"><img src="docs/gallery/cloner_honeycomb.jpg" alt="Honeycomb cloner · Shader field"></a><br><sub><b>Honeycomb cloner · Shader field</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#object-cloner--on-a-surface"><img src="docs/gallery/cloner_object.jpg" alt="Object cloner · on a surface"></a><br><sub><b>Object cloner · on a surface</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#spline-cloner--along-a-spiral"><img src="docs/gallery/cloner_spline.jpg" alt="Spline cloner · along a spiral"></a><br><sub><b>Spline cloner · along a spiral</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#blend-clones--morphing"><img src="docs/gallery/cloner_blend.jpg" alt="Blend clones · morphing"></a><br><sub><b>Blend clones · morphing</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#matrix--inheritance"><img src="docs/gallery/matrix_inheritance.jpg" alt="Matrix + Inheritance"></a><br><sub><b>Matrix + Inheritance</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#plain-effector--sphere-falloff"><img src="docs/gallery/effector_plain.jpg" alt="Plain effector · sphere falloff"></a><br><sub><b>Plain effector · sphere falloff</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#random-effector"><img src="docs/gallery/effector_random.jpg" alt="Random effector"></a><br><sub><b>Random effector</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#step-effector"><img src="docs/gallery/effector_step.jpg" alt="Step effector"></a><br><sub><b>Step effector</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#formula-effector--ripple"><img src="docs/gallery/effector_formula.jpg" alt="Formula effector · ripple"></a><br><sub><b>Formula effector · ripple</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#target-effector"><img src="docs/gallery/effector_target.jpg" alt="Target effector"></a><br><sub><b>Target effector</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#spline-effector"><img src="docs/gallery/effector_spline.jpg" alt="Spline effector"></a><br><sub><b>Spline effector</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#push-apart-effector"><img src="docs/gallery/effector_push_apart.jpg" alt="Push Apart effector"></a><br><sub><b>Push Apart effector</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#shader-effector"><img src="docs/gallery/effector_shader.jpg" alt="Shader effector"></a><br><sub><b>Shader effector</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#sound-effector--equalizer"><img src="docs/gallery/effector_sound.jpg" alt="Sound effector · equalizer"></a><br><sub><b>Sound effector · equalizer</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#tracer--trails"><img src="docs/gallery/effector_tracer.jpg" alt="Tracer · trails"></a><br><sub><b>Tracer · trails</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#layered-fields"><img src="docs/gallery/fields_layered.jpg" alt="Layered fields"></a><br><sub><b>Layered fields</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#voronoi-fracture--detailed"><img src="docs/gallery/voronoi.jpg" alt="Voronoi Fracture · detailed"></a><br><sub><b>Voronoi Fracture · detailed</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#voronoi-fracture--hollow-shell"><img src="docs/gallery/voronoi_shell.jpg" alt="Voronoi Fracture · hollow shell"></a><br><sub><b>Voronoi Fracture · hollow shell</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#polyfx--polygons-as-clones"><img src="docs/gallery/polyfx.jpg" alt="PolyFX · polygons as clones"></a><br><sub><b>PolyFX · polygons as clones</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#motext"><img src="docs/gallery/motext.jpg" alt="MoText"></a><br><sub><b>MoText</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#mospline--simple-and-turtle"><img src="docs/gallery/mospline.jpg" alt="MoSpline · Simple and Turtle"></a><br><sub><b>MoSpline · Simple and Turtle</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#sweep--growth"><img src="docs/gallery/sweep.jpg" alt="Sweep · growth"></a><br><sub><b>Sweep · growth</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#loft"><img src="docs/gallery/loft.jpg" alt="Loft"></a><br><sub><b>Loft</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#volume-builder"><img src="docs/gallery/volume_builder.jpg" alt="Volume Builder"></a><br><sub><b>Volume Builder</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#spline-mask"><img src="docs/gallery/spline_mask.jpg" alt="Spline Mask"></a><br><sub><b>Spline Mask</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#moextrude"><img src="docs/gallery/moextrude.jpg" alt="MoExtrude"></a><br><sub><b>MoExtrude</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#moinstance"><img src="docs/gallery/moinstance.jpg" alt="MoInstance"></a><br><sub><b>MoInstance</b></sub></td></tr>
<tr><td width="33%" valign="top"><a href="docs/GALLERY.md#deformers--twist--wave"><img src="docs/gallery/deformers.jpg" alt="Deformers · Twist + Wave"></a><br><sub><b>Deformers · Twist + Wave</b></sub></td><td width="33%" valign="top"><a href="docs/GALLERY.md#multi--beat-shaders"><img src="docs/gallery/shaders.jpg" alt="Multi + Beat shaders"></a><br><sub><b>Multi + Beat shaders</b></sub></td></tr>
</table>

Click any picture for its caption and the exact code that rendered it.
<!-- gallery:end -->

## Why

Blender's Geometry Nodes can do everything MoGraph does, but building it means wiring
node trees by hand. MoBlend gives you the C4D workflow on top of them:

- Select objects, then add a Cloner, and those objects become the clones.
- Add an effector while a cloner is selected and it's linked.
- One effector can drive many cloners. Its settings live on the effector, so changing
  them updates every cloner it's linked to.
- An effector's scale is the size of its falloff.

Every node group is generated by code. Nothing is hidden in a `.blend` file, and the
add-on works in any file you open.

## Features

MoBlend covers Cinema 4D's MoGraph module item by item. **[docs/MOGRAPH_CHECKLIST.md](docs/MOGRAPH_CHECKLIST.md)**
compares every feature in Maxon's documentation with MoBlend: **71 implemented, 5 partial, 12 not applicable
in Blender** (each with the Blender alternative), and nothing left as not started. Every implemented item has
an automated test.

| Area | What you get |
|---|---|
| **Cloner** | Linear, Radial, Grid, Honeycomb, Object, Spline modes with their C4D options; Iterate / Random / Blend (morph) / Sort clones; Viewport Mode; Matrix object |
| **Effectors** | Plain, Random, Step, Noise, Shader, Formula, Wave, Time, Target, Delay, Inheritance, Sound, Spline, Volume, Push Apart, Group / ReEffector. Common options: Strength, Min/Max, Visibility, Weight Transform, Modify Clone, Memory (Decay / Freeze / Ease), Deformation on plain meshes |
| **Fields** | Linear, Radial, Spherical, Box, Cylinder, Cone, Capsule, Torus, Random, Noise, Shader, Sound, Formula, Time, Step, Object/Spline distance, Attribute, Group. Blend modes, opacity, contour, remap |
| **Selection** | MoGraph Selection and Weightmap tags, a Pick Clones tool (Edit Mode), index patterns, Hide Selected |
| **Voronoi Fracture** | Live re-fracture, point distributions, source objects, shader source, weightmap, offset/invert, hull only, scale cells, sorting, detailing, geometry glue, selection attributes, rigid-body connectors |
| **Other objects** | Fracture (objects / islands / polygons), MoText (letters / words / lines, bevel), MoSpline (Simple / Spline / Turtle L-system), MoExtrude, MoInstance, Tracer (connect / trails), Spline Mask, Spline Wrap, Sweep, Loft, Volume Builder, Lathe, Extrude, Symmetry, Boole, Subdivision |
| **Deformers** | Bend, Twist, Taper, Stretch, Wave, Spherify, Shear, Bulge, Displace (textures), all with falloffs and fields |
| **Shaders & tools** | MoGraph Color, Multi, Beat; MoGraph Cache (bake) |

## Install

Requires **Blender 5.0+** (developed on 5.2).

1. Download the repo, then zip the `moblend/` folder or use a release zip.
2. In Blender, go to *Edit → Preferences → Add-ons → Install from Disk*, pick the zip, and enable **MoBlend**.

For development, symlink the folder instead:

```sh
ln -s "$PWD/moblend" ~/.config/blender/5.2/scripts/addons/moblend   # Linux
```

Then use **Shift+A → MoBlend**, and the **N sidebar → MoBlend** tab.

## MCP server

`mcp/moblend_mcp.py` is a stdio MCP server with no dependencies. It needs Python 3.10+.

```sh
claude mcp add moblend -s user -- python3 /path/to/moblend/mcp/moblend_mcp.py
```

It talks to the add-on through a Unix socket at `$XDG_RUNTIME_DIR/moblend.sock`
(override with `MOBLEND_SOCKET`). That's a file, not a network port, so nothing is
exposed on your network. The bridge starts with Blender; you can turn that off in the
add-on preferences. Unix sockets aren't available on Windows, so the bridge is
disabled there for now.

Tools:
- Building: `create_cloner`, `add_effector`, `link_effector`, `add_field`, `link_field`, `add_deformer`, `create_motext`, `create_sweep`, `create_loft`, `create_volume_builder`, `add_generator` (incl. `voronoi`)
- Parameters and animation: `get_params`, `set_params` (pass `frame` to keyframe), `keyframes`
- Materials: `set_material`, `set_color_material`
- Seeing the result: `render_preview` (returns the image), `frame_camera`, `stats`
- Scene: `scene_info`, `add_primitive`, `set_frame`, `save_file`, `run_python`, `launch_blender`

Angles are in degrees. Colors are `#rrggbb` hex strings.

```jsonc
create_cloner  {"mode": "radial", "name": "Ring", "params": {"Count": 24, "Radius": 5}}
add_effector   {"type": "plain", "cloners": ["Ring"], "size": 3, "location": [5,0,0],
                "params": {"Position": [0,0,1.5], "Color": "#ff5a1f", "Color Mix": 1}}
keyframes      {"object": "Plain Effector", "frames": {"1": {"location": [5,0,0]}, "60": {"location": [-5,0,0]}}}
render_preview {"frame": 30, "mode": "camera", "engine": "BLENDER_EEVEE"}
```

## Python

`moblend.api` is the same API the UI and the MCP server use:

```python
from moblend import api
ring = api.create_cloner("radial", params={"Count": 12})
api.add_effector("random", cloners=[ring], params={"Rotation": [0, 0, 90]})
```

## Development

```sh
blender -b --factory-startup -P tests/test_api.py      # every feature, checks evaluated geometry
blender -b --factory-startup -P tests/test_ui.py       # panels/menus draw + operators
blender -b --factory-startup -P tests/test_bridge.py   # MCP server -> socket -> Blender end to end
```

Each suite takes a few seconds. [CLAUDE.md](CLAUDE.md) covers the layout and conventions.

## License

GPL-3.0-or-later, the same as Blender, which requires it for add-ons that use its Python API.
