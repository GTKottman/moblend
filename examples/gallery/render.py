"""Render gallery scenes: blender -b --factory-startup -P examples/gallery/render.py -- [names...]

Writes docs/gallery/<name>.png (then tools/gallery.py makes the JPEGs and the docs). One process renders
all requested scenes in sequence, resetting the file between them.
"""

import os
import sys
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "examples"))

from moblend import api  # noqa: E402
from gallery.scenes import SCENES  # noqa: E402
from gallery.studio import render, reset  # noqa: E402

api.register()
wanted = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_dir = os.path.join(ROOT, "docs", "gallery")
os.makedirs(out_dir, exist_ok=True)
for entry in SCENES:
    if wanted and entry["name"] not in wanted:
        continue
    t = time.time()
    try:
        reset()
        entry["fn"]()
        render(os.path.join(out_dir, entry["name"] + ".png"))
        print(f"RENDERED {entry['name']} {time.time() - t:.1f}s", flush=True)
    except Exception:
        traceback.print_exc()
        print(f"FAILED {entry['name']}", flush=True)
