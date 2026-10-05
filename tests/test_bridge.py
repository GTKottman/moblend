"""End-to-end: MCP server process -> Unix socket -> bridge -> Blender.

Run: blender -b --factory-startup -P tests/test_bridge.py
Background Blender has no event loop, so this script pumps the bridge itself.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
os.environ["MOBLEND_SOCKET"] = os.path.join(tempfile.mkdtemp(), "moblend-test.sock")

import bpy  # noqa: E402
import moblend  # noqa: E402
from moblend import bridge  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
moblend.register()
assert bridge.start()

PREVIEW = os.path.join(tempfile.gettempdir(), f"moblend_preview_{os.getpid()}.png")
results, errors = {}, []


def client():
    p = subprocess.Popen(["python3", os.path.join(ROOT, "mcp", "moblend_mcp.py")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=os.environ)
    n = [0]

    def rpc(method, params=None):
        n[0] += 1
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    def tool(tool_name, **args):
        r = rpc("tools/call", {"name": tool_name, "arguments": args})["result"]
        if r["isError"]:
            errors.append((tool_name, r["content"][0]["text"][:800]))
        return r

    try:
        results["init"] = rpc("initialize", {"protocolVersion": "2025-06-18"})
        results["tools"] = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
        tool("status")
        r = tool("create_cloner", mode="radial", name="Ring", params={"Count": 12, "Radius": 4})
        results["cloner"] = json.loads(r["content"][0]["text"])
        tool("add_effector", type="plain", cloners=["Ring"], location=[4, 0, 0], size=2.5,
             params={"Position": [0, 0, 1.5], "Uniform Scale": 0.6, "Color": "#ff5a1f", "Color Mix": 1})
        tool("add_effector", type="random", cloners=["Ring"], params={"Rotation": [0, 0, 45]})
        tool("create_motext", text="MO", location=[0, 0, 0], params={"Size": 2})
        tool("keyframes", object="Ring", frames={"1": {"Radius": 3}, "30": {"Radius": 4}})
        tool("add_primitive", kind="plane", size=40, location=[0, 0, -1])
        tool("set_material", objects=["Plane"], color="#20232a")
        results["stats"] = json.loads(tool("stats", object="Ring")["content"][0]["text"])
        r = tool("render_preview", mode="camera", width=640, height=360, frame=30)
        results["preview_types"] = [c["type"] for c in r["content"]]
        results["bad"] = tool("set_params", object="Ring", params={"Nope": 1})
    finally:
        p.stdin.close()
        p.wait(5)


t = threading.Thread(target=client)
t.start()
deadline = time.time() + 120
while t.is_alive() and time.time() < deadline:
    bridge._pump()
    time.sleep(0.01)

ok = True
try:
    assert results["init"]["result"]["serverInfo"]["name"] == "moblend"
    assert "create_cloner" in results["tools"] and "render_preview" in results["tools"]
    assert results["cloner"]["params"]["Count"]["value"] == 12
    assert results["stats"]["instances"] == 12, results["stats"]
    assert results["preview_types"] == ["text", "image"], results["preview_types"]
    assert results["bad"]["isError"] and "Unknown parameter" in results["bad"]["content"][0]["text"]
    bad_calls = [e for e in errors if e[0] != "set_params"]
    assert not bad_calls, bad_calls
except Exception as e:
    ok = False
    print("FAIL", repr(e), errors)
bridge.stop()
print("PREVIEW", PREVIEW)
print("RESULT", "PASS" if ok else "FAIL")
