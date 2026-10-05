# MoGraph checklist

This compares every MoGraph feature in Cinema 4D's documentation
([help.maxon.net](https://help.maxon.net/c4d/en-us/)) with MoBlend. Every ✅ item has an automated test
(`tests/test_api.py`) that checks the evaluated result.

Legend: ✅ implemented · 🔶 partial (the note says what's missing) · ➖ not applicable in Blender (the note
says what to use instead)

## Cloner

| Feature | Status | Notes |
|---|---|---|
| Modes: Object, Linear, Radial, Grid Array, Honeycomb Array | ✅ | |
| Clones: Iterate, Random | ✅ | |
| Clones: Blend | ✅ | Children with the same vertex count morph; others switch at the halfway point |
| Clones: Sort | ✅ | Clones start as the first child; effectors pick the child with Modify Clone |
| Fix Clone, Reset Coordinates | ✅ | Clones keep the child's rotation and scale; position is reset |
| Viewport Mode: Off, Points, Bounding Box, Object | ✅ | "MB Display" modifier, always last; affects the viewport only |
| Fix Texture | ➖ | Use object-space or generated texture coordinates |
| Instance Mode (Instance, Render Instance, Multi-Instance) | ➖ | Geometry Nodes instances already share memory |
| Object: Vertex, Edge, Polygon Center, Surface, Volume, Axis | ✅ | |
| Object: onto another cloner / Matrix | ✅ | Distribution "Instances" (uses their rotation and scale) |
| Object: Selection, Align Clone, Up Vector, Enable Scale | ✅ | Selection = vertex group or attribute; Enable Scale = "Scale by Area" |
| Object mode on a spline (count, offset, spread, align) | ✅ | Spline mode |
| Linear: Count, Offset, Per Step / End Point, Amount | ✅ | |
| Linear: Position / Scale / Rotation displacement | ✅ | Offset, Scale Step / Step Scale, Step Rotation |
| Linear: Step Mode (Cumulative / Single Value), Step Size, Step Rotation (curl) | ✅ | Step Curve = C4D Step Rotation |
| Linear: Offset (first clone index) | ✅ | Start Offset |
| Radial: Count, Radius, Plane, Align, Start/End, Offset, Offset Variation, Seed | ✅ | |
| Grid: Count, Per Step / End Point, Size, Form Cube/Sphere/Cylinder/Object, Fill | ✅ | |
| Honeycomb: orientation, offset direction, offset, variations, counts, sizes, Square/Circle | ✅ | |
| Honeycomb: Spline form | ➖ | Use Object mode on a filled curve |
| Transform tab: Color, Weight | ✅ | Clones start white with weight 0; effectors change both |
| Transform tab: Time Offset, Animation Mode | ➖ | Blender instances share one evaluated object |
| Effectors list with order, toggles | ✅ | |

## Other MoGraph objects

| Object | Status | Notes |
|---|---|---|
| Matrix, Swap Cloner/Matrix | ✅ | A cloner that renders nothing |
| Fracture: Off, Explode Segments, Explode Segments & Connect | ✅ | Fracture Objects / Polygons / Islands |
| Voronoi Fracture | ✅ | Every tab; see its own table below |
| MoInstance (History Depth, Step) | ✅ | Simulation; bake with MoGraph Cache |
| MoSpline: Simple, Spline, Turtle (L-system) | ✅ | Growth (Start/End/Offset), width tubes |
| MoSpline: Rail / Destination splines, Simple-mode Curve/Bend/Twist curves | 🔶 | Angle (curl) and Spread cover the common shapes |
| MoExtrude (steps, offset, scale, selection, driven by fields) | ✅ | A deformer-style object, so fields link to it |
| PolyFX (polygons / spline segments as clones) | ✅ | Fracture → Polygons; curves split per segment |
| Tracer: connect elements, trace paths, trace another object's points | ✅ | Connect / Trails, world space, taper |
| Tracer: trace particles | ➖ | Blender particles aren't Geometry Nodes geometry; trace a point cloud object instead |
| MoText: all / lines / words / letters, extrude, bevel | ✅ | |
| MoText: separate effector lists per level at the same time | 🔶 | One split level at a time |
| Spline Mask: union, intersection, subtract; curve or fill | ✅ | Exact booleans, closed curves in the XY plane |
| Spline Wrap | ✅ | Blender Curve modifier |
| Displace (noise and textures) | ✅ | Procedural textures or an image, along the normal or as a vector |

## Voronoi Fracture

| Tab / feature | Status | Notes |
|---|---|---|
| Autoupdate (live re-fracture) and cached result | ✅ | Debounced; also reacts to moving source/sort/glue objects. The result is saved in the .blend |
| Sources: Point Generator — Uniform, Normal, Inverse Normal, Exponential (+ axes) | ✅ | |
| Sources: Point Amount, Seed, Standard Deviation, Inside, High Quality, box position/scale | ✅ | |
| Sources: objects (points, curves, polygons, particles, nulls) | ✅ | Source collection |
| Sources: Shader source | ✅ | A Blender texture drives where points go |
| Sources: Create Points per Object, Viewport Amount | ➖ | MoBlend fractures one object at a time |
| Object: Colorize Fragments, Create N-Gon Surfaces, Offset Fragments, Invert | ✅ | |
| Object: Hull Only + Thickness, Hollow Object, Optimize and Close Holes, Scale Cells | ✅ | Caps keep holes, so hollow objects work |
| Object: MoGraph Selection, MoGraph Weightmap | ✅ | Vertex groups: what breaks, and where pieces get smaller |
| Sorting: Sort Result, Invert, By Direction, Distance to Object, Along Spline | ✅ | Sorts by the pieces' real centers |
| Detailing: Max Edge Length, noise (strength, scale, seed, octaves), Noise Surface, Keep Original Surface | ✅ | |
| Detailing: Low/High Clip, Strength at Depth, Relax Inside Edges, Smooth Normals | ✅ | |
| Detailing: Artefact Prevention, Use Original Edges / Phong Angle | 🔶 | Smooth Normals only |
| Geometry Glue: Cluster, Point Distance (+ Bigger), Falloff/Object (+ Glue Rest) | ✅ | |
| Selections: Inside/Outside Faces, Surface Break Edges, Inside/Outside/Edge vertex maps | ✅ | Attributes `mb_inside_faces`, `mb_break_edges`, `mb_*_weight` |
| Connectors: Fixed connectors between neighbours, breaking threshold, connector Falloff | ✅ | Make Dynamic: rigid bodies and breakable Fixed constraints between pieces that actually touch |
| Connectors: Breaking Torque | ➖ | Blender constraints break on an impulse threshold only |

## Effectors

| Effector | Status | Notes |
|---|---|---|
| Plain, Random (random, noise), Step, Time, Target, Delay (blend, spring), Inheritance, Sound | ✅ | |
| Formula | ✅ | A safe expression compiler builds nodes (variables id, count, t, f, x, y, z) |
| Shader | ✅ | Noise, Voronoi, Wave, Gradient, Checker, Magic, Image; can paint the texture's color |
| Spline | ✅ | Start, End, Offset, Loop, Align |
| Volume | ✅ | Inside test against another mesh, with soft edge |
| Push Apart (push, hide) | ✅ | Relaxation passes |
| Group, ReEffector | ✅ | One Strength / falloff / fields scaling several effectors |
| Python | ➖ | Use `run_python` or Blender drivers |
| Common: Strength, Minimum/Maximum, falloff, fields | ✅ | |
| Common: Position, Rotation, Scale, Uniform Scale, Color, Visibility | ✅ | |
| Common: Weight Transform, Modify Clone | ✅ | |
| Common: Selection (index pattern, MoGraph Selection tag, Weightmap) | ✅ | |
| Common: Deformation Off / Point / Polygon / Object | ✅ | Effectors also act on plain meshes |
| Common: U/V Transform, Time Offset | ➖ | Instances share texture coordinates and animation in Blender |

## Fields

| Field | Status | Notes |
|---|---|---|
| Linear, Radial, Spherical, Box, Cylinder, Cone, Capsule, Torus, Random | ✅ | |
| Shader, Sound, Formula, Group | ✅ | |
| Python | ➖ | Formula field covers most uses |
| Layers: Solid, Time, Step, Spline Object, Point Object, Variable (vertex map) | ✅ | Solid, Time, Step, Object (distance to surface/edges/points, curves count), Attribute |
| Blending: Normal, Multiply, Max, Min, Add, Subtract, Screen, Average, Difference + Opacity | ✅ | |
| Modifiers: Clamp, Invert, Remap, Quantize | ✅ | Remap Min/Max, Contour (Quadratic, Ease, Step, Quantize) |
| Modifiers: Formula, Noise | ✅ | Formula / Shader field layers with a blend mode |
| Modifiers: Decay, Delay, Freeze | ✅ | Effector Memory: Decay, Ease, Freeze |
| Modifiers: Curve (custom spline) | 🔶 | Contour presets; no free-form curve |
| Modifiers: Colorize, Color Filter | ➖ | Fields carry a weight; color comes from effector Color / Shader effector |

## Tags, shaders and tools

| Item | Status | Notes |
|---|---|---|
| MoGraph Color shader | ✅ | "MB MoGraph Color" material |
| MoGraph Multi Shader (index, random, weight) | ✅ | Works on cloners, MoText letters and fracture pieces |
| MoGraph Beat Shader | ✅ | Simple-expression driver; no Python auto-run |
| MoGraph Camera Shader | ➖ | |
| MoGraph Selection tag + Selection tool | ✅ | Tag: index lists or patterns. Tool: Pick Clones puts a vertex on every clone for Edit Mode selection |
| MoGraph Weightmap | ✅ | Per-clone weights (API, MCP or vertex group) |
| MoGraph Weight Paintbrush | 🔶 | Weights are set by value; Blender can't brush-paint loose points |
| MoGraph Cache | ✅ | Bakes the simulations (Delay, Memory, Trails, MoInstance) |
| Hide Selected | ✅ | |
