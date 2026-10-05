"""Local bridge the MCP server talks to.

Listens on a Unix domain socket (a file, not a network port), so nothing is
exposed on the network. Requests are newline-delimited JSON
{"id", "cmd", "args"}; each runs on Blender's main thread via a timer.
"""

import contextlib
import json
import os
import queue
import socket
import threading

import bpy

from . import commands
from .catalog import socket_path

BATCH = 20        # commands run per timer tick, so a flood can't freeze the UI
TICK = 0.02       # seconds between ticks


_jobs = queue.Queue()
_server = None
_stop = threading.Event()


def _pump():
    """Main-thread timer: run queued commands."""
    for _ in range(BATCH):
        try:
            req, box, done = _jobs.get_nowait()
        except queue.Empty:
            break
        box["resp"] = commands.safe_dispatch(req.get("cmd"), req.get("args"))
        box["resp"]["id"] = req.get("id")
        done.set()
    return None if _stop.is_set() else TICK


def _client(conn):
    with conn:
        f = conn.makefile("rwb")
        for line in f:
            try:
                req = json.loads(line)
            except ValueError as e:
                resp = {"ok": False, "error": f"bad json: {e}"}
            else:
                box, done = {}, threading.Event()
                _jobs.put((req, box, done))
                if not done.wait(float(req.get("timeout", 300))):
                    resp = {"ok": False, "id": req.get("id"), "error": "timed out waiting for Blender (busy?)"}
                else:
                    resp = box["resp"]
            f.write((json.dumps(resp, default=str) + "\n").encode())
            f.flush()


def _serve(srv):
    while not _stop.is_set():
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        threading.Thread(target=_client, args=(conn,), daemon=True).start()


def _alive(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        s.close()


def start():
    """Start the bridge. Returns the socket path, or None if another Blender owns it."""
    global _server
    if _server is not None:
        return socket_path()
    if not hasattr(socket, "AF_UNIX"):
        print("MoBlend bridge: this platform has no Unix sockets; MCP bridge disabled")
        return None
    path = socket_path()
    if os.path.exists(path):
        if _alive(path):
            print(f"MoBlend bridge: {path} is served by another Blender; not starting")
            return None
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(8)
    _stop.clear()
    _server = srv
    threading.Thread(target=_serve, args=(srv,), daemon=True).start()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.1, persistent=True)
    print(f"MoBlend bridge listening on {path}")
    return path


def stop():
    global _server
    _stop.set()
    if _server is not None:
        try:
            _server.close()
        finally:
            _server = None
        with contextlib.suppress(OSError):
            os.unlink(socket_path())
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)


def running():
    return _server is not None
