#!/usr/bin/env python3
"""Build the gallery docs from examples/gallery/scenes.py and the renders in docs/gallery/.

- Converts each docs/gallery/<name>.png to a web-sized JPEG (needs ImageMagick) and removes the PNG.
- Writes docs/GALLERY.md: every picture with its caption and the exact code that rendered it.
- Rewrites the README gallery grid between <!-- gallery:start --> and <!-- gallery:end -->.

Runs with plain Python (it parses scenes.py instead of importing it, so Blender is not needed).
Render first: blender -b --factory-startup -P examples/gallery/render.py
"""

import ast
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCENES = os.path.join(ROOT, "examples", "gallery", "scenes.py")
IMAGES = os.path.join(ROOT, "docs", "gallery")
COLUMNS = 3
START, END = "<!-- gallery:start -->", "<!-- gallery:end -->"


def scenes():
    """[(name, title, caption, section, source)] in file order, read from the @scene decorators."""
    with open(SCENES) as fh:
        text = fh.read()
    found = []
    for node in ast.parse(text).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and getattr(deco.func, "id", "") == "scene":
                title, caption, section = (ast.literal_eval(a) for a in deco.args)
                body = ast.get_source_segment(text, node)
                found.append((node.name, title, caption, section, body))
    return found


def to_jpeg(name):
    png, jpg = (os.path.join(IMAGES, f"{name}.{ext}") for ext in ("png", "jpg"))
    if os.path.exists(png):
        tool = shutil.which("magick") or shutil.which("convert")
        if tool is None:
            sys.exit("ImageMagick is needed to convert renders to JPEG")
        subprocess.run([tool, png, "-strip", "-quality", "85", jpg], check=True)
        os.remove(png)
    return os.path.exists(jpg)


def anchor(title):
    return "".join(ch for ch in title.lower().replace(" ", "-") if ch.isalnum() or ch == "-")


def gallery_md(entries):
    lines = ["# Gallery", "", "Every picture is rendered from `examples/gallery/scenes.py`; the code under each one "
             "is exactly what made it. Re-render with "
             "`blender -b --factory-startup -P examples/gallery/render.py` and rebuild with "
             "`python3 tools/gallery.py`.",
             ""]
    section = None
    for name, title, caption, sec, body in entries:
        if sec != section:
            lines += [f"## {sec}", ""]
            section = sec
        lines += [f"### {title}", "", f"![{title}](gallery/{name}.jpg)", "", caption, "", "```python", body, "```",
                  ""]
    return "\n".join(lines)


def readme_grid(entries):
    rows = []
    for i in range(0, len(entries), COLUMNS):
        cells = []
        for name, title, _, _, _ in entries[i:i + COLUMNS]:
            cells.append(f'<td width="33%" valign="top"><a href="docs/GALLERY.md#{anchor(title)}">'
                         f'<img src="docs/gallery/{name}.jpg" alt="{title}"></a><br><sub><b>{title}</b></sub></td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join([START, "<table>", *rows, "</table>", "",
                      "Click any picture for its caption and the exact code that rendered it.", END])


def main():
    entries = [e for e in scenes() if to_jpeg(e[0])]
    missing = [e[0] for e in scenes() if e not in entries]
    with open(os.path.join(ROOT, "docs", "GALLERY.md"), "w") as fh:
        fh.write(gallery_md(entries))
    readme_path = os.path.join(ROOT, "README.md")
    with open(readme_path) as fh:
        readme = fh.read()
    if START not in readme:
        sys.exit(f"README.md needs {START} ... {END} markers")
    head, rest = readme.split(START, 1)
    tail = rest.split(END, 1)[1]
    with open(readme_path, "w") as fh:
        fh.write(head + readme_grid(entries) + tail)
    print(f"{len(entries)} pictures" + (f"; not rendered: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
