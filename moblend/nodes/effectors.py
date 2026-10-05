"""Effector type groups (all O(clones) per frame).

Each effector object gets its own wrapper group holding one node of its type
group; that node's input values ARE the effector's parameters, so editing
them updates every cloner it is linked to (see api/effector.py).
"""

import math

from ..catalog import COLOR_ATTR
from .util import S, out
from .core import apply, falloff_group

PARAMS = [
    S("Position", "VECTOR", (0, 0, 0), subtype="TRANSLATION"),
    S("Rotation", "VECTOR", (0, 0, 0), subtype="EULER"),
    S("Scale", "VECTOR", (0, 0, 0), subtype="XYZ", desc="Added scale (0 = unchanged, -1 = vanish)"),
    S("Uniform Scale", "FLOAT", 0.0, desc="Added uniform scale"),
    S("Color", "COLOR", (1.0, 0.35, 0.1, 1.0)),
    S("Color Mix", "FLOAT", 0.0, 0.0, 1.0, "FACTOR", "How much the effector paints its color"),
    S("Local Space", "BOOL", True, desc="Move clones along their own axes"),
]


def _apply(b, g, geo, weight, position=None, rotation=None, scale=None, color=None):
    """Run MB Apply with the effector's parameters, overriding any of them with fields."""
    u = g["Uniform Scale"]
    if scale is None:
        scale = b.vmath("ADD", g["Scale"], b.combine(u, u, u))
    n = b.group(apply(), {"Instances": geo, "Weight": weight,
                          "Position": position or g["Position"], "Rotation": rotation or g["Rotation"],
                          "Scale": scale, "Color": color or g["Color"],
                          "Color Mix": g["Color Mix"], "Local Space": g["Local Space"]})
    return n.outputs[0]


def _effector(name, extra, body, falloff="Infinite", menus=None, params=True):
    return falloff_group(name, "Instances", (PARAMS if params else []) + extra, body, falloff, menus)


def _plain(b, g, w):
    return _apply(b, g, g["Instances"], w)


def _index_ramp(b, g, divisor):
    return b.math("DIVIDE", b.index(), divisor(b.instance_count(g["Instances"])))


def _step(b, g, w):
    t = _index_ramp(b, g, b.steps)
    t = b.mix("FLOAT", g["Reverse"], t, b.math("SUBTRACT", 1.0, t))
    return _apply(b, g, g["Instances"], b.math("MULTIPLY", w, t))


def _wave(b, g, w):
    t = _index_ramp(b, g, b.at_least)
    phase = b.math("SUBTRACT", b.math("MULTIPLY", t, g["Frequency"]), b.math("MULTIPLY", b.seconds(), g["Speed"]))
    s = b.math("SINE", b.math("MULTIPLY", phase, 2 * math.pi))
    s = b.mix("FLOAT", g["Bipolar"], b.math("MULTIPLY_ADD", s, 0.5, 0.5), s)
    return _apply(b, g, g["Instances"], b.math("MULTIPLY", w, s))


def _time(b, g, w):
    return _apply(b, g, g["Instances"], b.math("MULTIPLY", w, b.seconds()))


def _random(b, g, w):
    seed = g["Seed"]
    seeds = [b.math("ADD", seed, k * 101) for k in range(4)]
    t = b.math("MULTIPLY", b.seconds(), g["Speed"])
    pos = b.vmath("SCALE", b.position(), scale=0.35)

    def variation(k):
        """Per-clone -1..1 vector: fixed random, or smooth noise over time (chosen by Mode)."""
        rnd = b.rand("FLOAT_VECTOR", (-1, -1, -1), (1, 1, 1), seed=seeds[k])
        wk = b.math("ADD", t, b.math("ADD", b.math("MULTIPLY", seed, 7.31), k * 13.7))
        nz = b.vmath("SCALE", b.vmath("SUBTRACT", out(b.noise4d(pos, wk), "Color"), (0.5, 0.5, 0.5)), scale=4.0)
        return b.index_switch("VECTOR", mode, [rnd, nz])

    mode = b.menu(["Random", "Noise"], g["Mode"])
    r_pos, r_rot, r_scale = variation(0), variation(1), variation(2)
    rx, _, _ = b.separate(r_scale)
    uni = b.combine(rx, rx, rx)
    scale = b.vmath("ADD", b.vmath("MULTIPLY", g["Scale"], b.mix("VECTOR", g["Uniform"], r_scale, uni)),
                    b.vmath("SCALE", uni, scale=g["Uniform Scale"]))
    color = b.mix("RGBA", g["Random Color"], g["Color"], b.rand("FLOAT_VECTOR", (0, 0, 0), (1, 1, 1), seed=seeds[3]))
    return _apply(b, g, g["Instances"], w, position=b.vmath("MULTIPLY", g["Position"], r_pos),
                  rotation=b.vmath("MULTIPLY", g["Rotation"], r_rot), scale=scale, color=color)


def _target(b, g, w):
    t, r, s = b.instance_trs()
    eff_pos, _, _ = b.split_transform(g["Transform"])
    d = b.vmath("SCALE", b.vmath("SUBTRACT", eff_pos, t), scale=b.mix("FLOAT", g["Away"], 1.0, -1.0))
    aimed = b.node("FunctionNodeAlignRotationToVector", {"Rotation": r, "Factor": w, "Vector": d},
                   axis="Z", pivot_axis="AUTO").outputs[0]
    geo = b.node("GeometryNodeSetInstanceTransform",
                 {"Instances": g["Instances"], "Transform": b.combine_transform(t, aimed, s)}).outputs[0]
    return _apply(b, g, geo, w)


def _delay(b, g, w):
    """Simulation zone: per frame each clone moves toward its effected transform. O(clones) per frame."""
    inst = g["Instances"]
    tp, tr, ts = b.instance_trs()
    state = {"mb_p": ("FLOAT_VECTOR", tp), "mb_r": ("QUATERNION", tr), "mb_s": ("FLOAT_VECTOR", ts)}
    init = inst
    for name, (dtype, value) in state.items():
        init = b.store(init, name, value, dtype, "INSTANCE")

    sim_in, sim_out = b.node("GeometryNodeSimulationInput"), b.node("GeometryNodeSimulationOutput")
    sim_in.pair_with_output(sim_out)
    b.link(init, sim_in.inputs[0])
    idx = b.index()

    def sample(geo, value, dtype):
        return b.node("GeometryNodeSampleIndex", {"Geometry": geo, "Value": value, "Index": idx},
                      data_type=dtype, domain="INSTANCE").outputs[0]

    target = {k: sample(inst, v, d) for k, (d, v) in state.items()}
    cur = {k: b.named(k, d) for k, (d, _) in state.items()}
    vel_p, vel_s = b.named("mb_v", "FLOAT_VECTOR"), b.named("mb_vs", "FLOAT_VECTOR")

    def spring(key, vel):
        """v' = v*damping + (target - x)*stiffness; x' = x + v'."""
        nv = b.vmath("ADD", b.vmath("SCALE", vel, scale=g["Damping"]),
                     b.vmath("SCALE", b.vmath("SUBTRACT", target[key], cur[key]), scale=g["Stiffness"]))
        return b.vmath("ADD", cur[key], nv), nv

    sp, nv = spring("mb_p", vel_p)
    ss, nvs = spring("mb_s", vel_s)
    mode = b.menu(["Blend", "Spring"], g["Mode"])
    nxt = {
        "mb_p": b.index_switch("VECTOR", mode, [b.mix("VECTOR", g["Blend"], cur["mb_p"], target["mb_p"]), sp]),
        "mb_s": b.index_switch("VECTOR", mode, [b.mix("VECTOR", g["Blend"], cur["mb_s"], target["mb_s"]), ss]),
        "mb_r": b.mix("ROTATION", b.index_switch("FLOAT", mode, [g["Blend"], g["Stiffness"]]),
                      cur["mb_r"], target["mb_r"]),
    }
    st = sim_in.outputs[1]  # Geometry (index 0 is Delta Time)
    for name, (dtype, _) in state.items():
        st = b.store(st, name, nxt[name], dtype, "INSTANCE")
    st = b.store(st, "mb_v", nv, "FLOAT_VECTOR", "INSTANCE")
    st = b.store(st, "mb_vs", nvs, "FLOAT_VECTOR", "INSTANCE")
    b.link(st, sim_out.inputs["Geometry"])

    lag = {k: sample(sim_out.outputs[0], cur[k], d) for k, (d, _) in state.items()}
    m = b.combine_transform(b.mix("VECTOR", w, tp, lag["mb_p"]), b.mix("ROTATION", w, tr, lag["mb_r"]),
                            b.mix("VECTOR", w, ts, lag["mb_s"]))
    return b.node("GeometryNodeSetInstanceTransform", {"Instances": inst, "Transform": m}).outputs[0]


def _inheritance(b, g, w):
    """Blend each clone toward the transform (and color) of the same-index clone of Source. O(clones)."""
    src = b.object_geometry(g["Source"], realize=False)
    idx = b.index()

    def from_source(value, dtype):
        return b.node("GeometryNodeSampleIndex", {"Geometry": src, "Value": value, "Index": idx},
                      data_type=dtype, domain="INSTANCE").outputs[0]

    t, r, s = b.instance_trs()
    tt, tr, ts = b.split_transform(from_source(b.inp("GeometryNodeInstanceTransform"), "FLOAT4X4"))
    m = b.combine_transform(b.mix("VECTOR", w, t, tt), b.mix("ROTATION", w, r, tr), b.mix("VECTOR", w, s, ts))
    geo = b.node("GeometryNodeSetInstanceTransform", {"Instances": g["Instances"], "Transform": m}).outputs[0]
    color = b.mix("RGBA", b.math("MULTIPLY", w, g["Inherit Color"]), b.named(COLOR_ATTR, "FLOAT_COLOR"),
                  from_source(b.named(COLOR_ATTR, "FLOAT_COLOR"), "FLOAT_COLOR"))
    return b.store(geo, COLOR_ATTR, color, "FLOAT_COLOR", "INSTANCE")


def _sound(b, g, w):
    """Weight by the loudness of a frequency band: every clone its own band (Spread) or all the same."""
    n = b.instance_count(g["Instances"])
    ratio = b.math("DIVIDE", g["High"], b.at_least(g["Low"], 1.0))

    def band_edge(i):
        """Log-spaced band edge: Low * (High/Low)^(i/n)."""
        return b.math("MULTIPLY", g["Low"], b.math("POWER", ratio, b.math("DIVIDE", i, b.at_least(n))))

    spread = b.compare(b.menu(["Spread", "All"], g["Mode"]), 0)
    idx = b.index()
    lo = b.mix("FLOAT", spread, g["Low"], band_edge(idx))
    hi = b.mix("FLOAT", spread, g["High"], band_edge(b.math("ADD", idx, 1.0)))
    amp = b.node("GeometryNodeSampleSoundFrequencies", {
        "Sound": g["Sound"], "Time": b.math("ADD", b.seconds(), g["Time Offset"]), "All Channels": True,
        "Low": lo, "High": hi}).outputs[0]
    level = b.math("MINIMUM", b.math("MULTIPLY", amp, g["Gain"]), 1.0)
    return _apply(b, g, g["Instances"], b.math("MULTIPLY", w, level))


_plain_builder = _effector("MB Effector Plain", [], _plain, falloff="Sphere")

BUILDERS = {
    "plain": _plain_builder,
    "random": _effector("MB Effector Random", [
        S("Seed", "INT", 0),
        S("Mode", "MENU", desc="Random: fixed per clone. Noise: smoothly animated"),
        S("Speed", "FLOAT", 0.5, desc="Noise mode: animation speed"),
        S("Uniform", "BOOL", False, desc="Same random value on every scale axis"),
        S("Random Color", "BOOL", False, desc="Paint each clone a random color (uses Color Mix)"),
    ], _random, menus={"Mode": "Random"}),
    "step": _effector("MB Effector Step", [S("Reverse", "BOOL", False)], _step),
    "noise": _plain_builder,  # Plain with a Noise falloff (C4D "Shader"); falloff set on creation
    "wave": _effector("MB Effector Wave", [
        S("Frequency", "FLOAT", 1.0, desc="Waves across all clones"),
        S("Speed", "FLOAT", 0.5, desc="Waves per second"),
        S("Bipolar", "BOOL", False, desc="Swing -1..1 instead of 0..1"),
    ], _wave),
    "time": _effector("MB Effector Time", [], _time),
    "target": _effector("MB Effector Target", [S("Away", "BOOL", False, desc="Turn away instead of toward")],
                        _target),
    "delay": _effector("MB Effector Delay", [
        S("Mode", "MENU", desc="Blend eases toward the target; Spring overshoots and wobbles"),
        S("Blend", "FLOAT", 0.15, 0.0, 1.0, "FACTOR", "Blend mode: fraction caught up per frame"),
        S("Stiffness", "FLOAT", 0.2, 0.0, 1.0, "FACTOR", "Spring mode: pull toward the target"),
        S("Damping", "FLOAT", 0.75, 0.0, 1.0, "FACTOR", "Spring mode: velocity kept per frame"),
    ], _delay, menus={"Mode": "Spring"}, params=False),
    "inheritance": _effector("MB Effector Inheritance", [
        S("Source", "OBJECT", desc="Cloner (or other instancer) whose clone transforms to inherit"),
        S("Inherit Color", "BOOL", True, desc="Also blend toward the source clones' colors"),
    ], _inheritance, params=False),
    "sound": _effector("MB Effector Sound", [
        S("Sound", "SOUND", desc="Audio to listen to (name, or a file path via set_params)"),
        S("Mode", "MENU", desc="Spread: each clone gets its own frequency band. All: whole range for every clone"),
        S("Low", "FLOAT", 40.0, 1.0, 22000.0, desc="Lowest frequency (Hz)"),
        S("High", "FLOAT", 12000.0, 1.0, 22000.0, desc="Highest frequency (Hz)"),
        S("Gain", "FLOAT", 4.0, 0.0, desc="Amplitude multiplier before clamping to 1"),
        S("Time Offset", "FLOAT", 0.0, desc="Seconds added to the scene time when sampling"),
    ], _sound, menus={"Mode": "Spread"}),
}

# Falloff an effector of each type starts with (the type group's default otherwise).
DEFAULT_FALLOFF = {"plain": "Sphere", "noise": "Noise"}
