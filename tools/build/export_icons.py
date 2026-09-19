# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow==12.3.0"]
# ///
"""Export application icon resources from the approved, unmodified PNG master.

Run from any directory: uv run tools/build/export_icons.py
These versioned runtime assets let a checkout run/build without an image tool.
Pillow is only needed when changing the artwork, not by the application.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / "src" / "static" / "icons"


def main() -> None:
    with Image.open(ICONS / "app.png") as source:
        if source.width != source.height:
            raise ValueError("The approved icon master must be square")
        master = source.convert("RGBA")
    for size in (32, 64):
        master.resize((size, size), Image.Resampling.LANCZOS).save(
            ICONS / f"app-{size}.png", optimize=True)
    master.resize((256, 256), Image.Resampling.LANCZOS).save(
        ICONS / "app.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    master.resize((1024, 1024), Image.Resampling.LANCZOS).save(ICONS / "app.icns")
    (ROOT / "site" / "assets" / "favicon.png").write_bytes((ICONS / "app-64.png").read_bytes())
    for size in (192, 512):
        master.resize((size, size), Image.Resampling.LANCZOS).save(
            ROOT / "site" / "assets" / f"app-{size}.png", optimize=True)
    print("Exported PNG 32/64, ICO 16-256, ICNS up to 1024, and site icons")


if __name__ == "__main__":
    main()
