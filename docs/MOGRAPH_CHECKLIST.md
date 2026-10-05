# MoGraph checklist

Every MoGraph feature in Cinema 4D's documentation ([help.maxon.net](https://help.maxon.net/c4d/en-us/)),
and where MoBlend stands on it.

Legend: ✅ implemented · 🔶 partial (the note says what is missing) · ❌ not yet · ➖ not applicable in
Blender (the note says what to use instead)

## Objects

### Cloner
| Feature | Status | Notes |
|---|---|---|
| Modes: Object, Linear, Radial, Grid Array | ✅ | |
| Mode: Honeycomb Array | 🔶 | Grid option only; no orientation, offset %, width/height counts or forms |
| Clones: Iterate, Random | ✅ | |
| Clones: Blend, Sort | ❌ | |
| Fix Clone | ✅ | Clones keep the child's rotation and scale; position is reset |
| Reset Coordinates | ✅ | |
| Fix Texture | ➖ | Use object-space texture coordinates |
| Instance Mode (Instance, Render Instance, Multi-Instance) | ➖ | Geometry Nodes instances are always memory-shared |
| Viewport Mode (Off, Points, Matrix, Bounding Box, Object) | ❌ | |
| Object mode: Vertex, Polygon Center, Surface | ✅ | |
| Object mode: Edge, Volume, Axis | ❌ | |
| Object mode: Selection, Up Vector, Enable Scale | ❌ | Align Clone ✅ |
| Object mode on a spline (count, offset, spread) | ✅ | |
| Linear: Count, Position, Rotation displacement | ✅ | |
| Linear: Offset, Per Step / End Point, Amount, Scale displacement, Step Mode, Step Size, Step Rotation | ❌ | Step Scale exists (multiplicative) |
| Radial: Count, Radius, Plane, Align, Start/End | ✅ | |
| Radial: Offset, Offset Variation, Seed | ❌ | |
| Grid: Count, Size, Form Cube/Sphere/Cylinder | ✅ | |
| Grid: Per Step / End Point, Form Object, Fill | ❌ | |
| Transform tab: Color | ✅ | |
| Transform tab: Weight | ❌ | |
| Transform tab: Time Offset, Animation Mode | ➖ | Blender instances share one evaluated object |
| Effectors list with order | ✅ | |

### Other objects
| Object | Status | Notes |
|---|---|---|
| Matrix | ❌ | |
| Fracture: Explode Segments, Explode Segments & Connect | ✅ | Polygons / Islands |
| Fracture: Off (each child a clone) | ❌ | |
| Voronoi Fracture | ✅ | See its own table below |
| MoInstance | ❌ | |
| MoSpline (Simple, Spline, Turtle) | ❌ | |
| MoExtrude | ❌ | |
| PolyFX (polygons and spline segments as clones) | ✅ | Fracture → Polygons; curve segments split automatically |
| Tracer (connect elements, trace paths) | ✅ | Connect and Trails modes, world space |
| MoText (all, lines, words, letters) | ✅ | Bevel ❌ |
| Spline Mask | ❌ | |
| Spline Wrap | ❌ | |
| Displace | 🔶 | Noise displacement only, no texture |

### Voronoi Fracture
| Tab / feature | Status | Notes |
|---|---|---|
| Autoupdate (live re-fracture), result cached | ✅ | Debounced; also reacts to moving source/sort/glue objects |
| Sources: Point Generator — Uniform, Normal, Inverse Normal, Exponential (+ axes) | ✅ | |
| Sources: Point Amount, Seed, Standard Deviation, Inside, High Quality, box position/scale | ✅ | |
| Sources: objects (points, splines, polygons, particles, nulls) | ✅ | Source collection |
| Sources: Shader source | ✅ | A Blender texture drives point density |
| Sources: Create Points per Object | ➖ | MoBlend fractures one object at a time |
| Sources: Viewport Amount | ➖ | |
| Object: Colorize Fragments, Create N-Gon Surfaces | ✅ | |
| Object: Offset Fragments, Invert | ✅ | |
| Object: Hull Only + Thickness, Hollow Object, Optimize and Close Holes | ✅ | Hollow objects work because caps keep holes |
| Object: Scale Cells | ✅ | |
| Object: MoGraph Weightmap (fragment density) | ✅ | Vertex group |
| Object: MoGraph Selection (restrict to selection) | ❌ | |
| Sorting: Sort Result, Invert, By Direction, Distance to Object, Along Spline | ✅ | |
| Detailing: Max Edge Length, noise (strength, seed, octaves, scale), Noise Surface, Keep Original Surface | ✅ | |
| Detailing: Relax Inside Edges, Smooth Normals, Low/High Clip, Strength at Depth | ❌ | |
| Geometry Glue: Cluster, Point Distance (+ Bigger), Falloff/Object (+ Glue Rest) | ✅ | |
| Selections: Inside/Outside Faces, Surface Break Edges, Inside/Outside/Edge vertex maps | ✅ | Attributes `mb_inside_faces`, `mb_break_edges`, `mb_*_weight` |
| Connectors: Fixed connectors between neighbours, breaking threshold | ✅ | Rigid bodies + breakable Fixed constraints (Make Dynamic) |
| Connectors: Breaking Torque, connector Falloff | ❌ | |

## Effectors

| Effector | Status | Notes |
|---|---|---|
| Plain | ✅ | |
| Delay (Blend, Spring) | ✅ | |
| Formula | ❌ | |
| Group | ❌ | |
| Inheritance | ✅ | |
| Push Apart | ❌ | |
| Python | ➖ | Use `run_python` / Blender drivers |
| Random (Random, Noise) | ✅ | |
| ReEffector | ❌ | |
| Shader | 🔶 | Noise only |
| Sound | ✅ | |
| Spline | ❌ | |
| Step | ✅ | |
| Target | ✅ | |
| Time | ✅ | |
| Volume | ❌ | |
| Common: Strength, Fields, Position/Rotation/Scale, Color | ✅ | |
| Common: Selection (index pattern) | ✅ | |
| Common: MoGraph Selection tag, Weightmap | ❌ | |
| Common: Min/Max, Visibility, Modify Clone, Weight Transform | ❌ | |
| Common: Deformation (Point, Polygon, Object) | ❌ | |

## Fields

| Field | Status | Notes |
|---|---|---|
| Linear, Spherical, Box, Cylinder, Random | ✅ | |
| Radial, Cone, Capsule, Torus | ❌ | |
| Shader, Sound, Formula, Group | ❌ | |
| Python | ➖ | |
| Layers: Solid | ✅ | Infinite |
| Layers: Time, Step, Spline Object, Point Object, Variable (vertex map) | ❌ | |
| Blending: Multiply, Max, Min, Add, Subtract + Opacity | ✅ | |
| Modifiers: Clamp, Invert | ✅ | |
| Modifiers: Remap, Curve, Quantize, Noise, Colorize, Decay, Delay, Freeze, Formula | ❌ | |

## Tags, shaders and tools

| Item | Status | Notes |
|---|---|---|
| MoGraph Color shader | ✅ | "MB MoGraph Color" material |
| MoGraph Multi Shader, Beat Shader | ❌ | |
| Camera Shader | ➖ | |
| MoGraph Selection tag + Selection tool | ❌ | |
| MoGraph Weightmap + Weight Paintbrush | ❌ | |
| MoGraph Cache | ❌ | |
| Swap Cloner/Matrix, Hide Selected | ❌ | |
