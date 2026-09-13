#!/usr/bin/env python3
"""Assemble the deployable site: copy the handwritten site/ source, add the built manual.

Run: uv run python tools/site/build_site.py
Requires dist/manual/index.html first (tools/build/build_manual.py).
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "site"
MANUAL = ROOT / "dist" / "manual" / "index.html"
TARGET = ROOT / "dist" / "site"


def main() -> None:
    if not MANUAL.is_file():
        raise SystemExit("Manual not built yet: run tools/build/build_manual.py first")
    if SOURCE.is_symlink() or MANUAL.is_symlink() or TARGET.is_symlink():
        raise SystemExit("Refusing symlinked site paths")
    content = MANUAL.read_bytes()
    if b'<script id="bookData"' not in content or b'<script id="data"' not in content:
        raise SystemExit("Manual source is not a complete product manual")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    (TARGET / "manual.html").write_bytes(content)
    print(f"Assembled dist/site from site/ plus manual ({len(content)} bytes)")


if __name__ == "__main__":
    main()
