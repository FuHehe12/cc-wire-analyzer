#!/usr/bin/env python3
"""Generate the Pages manual from its single maintained source."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "product-manual.html"
TARGET = ROOT / "site" / "manual.html"


def main() -> None:
    if SOURCE.is_symlink() or TARGET.is_symlink():
        raise SystemExit("Refusing symlinked manual paths")
    content = SOURCE.read_bytes()
    if b'<script id="bookData"' not in content or b'<script id="data"' not in content:
        raise SystemExit("Source is not a complete product manual")
    TARGET.write_bytes(content)
    print(f"Generated site/manual.html from docs/product-manual.html ({len(content)} bytes)")


if __name__ == "__main__":
    main()
