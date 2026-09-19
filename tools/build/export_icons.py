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

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / "src" / "static" / "icons"

# macOS 图标网格（Apple HIG）：图形区占 824/1024 居中、板外**透明**；圆角用
# rounded-rect 近似 squircle（连续曲率的常规替代）。macOS **不会自动裁形**——
# icns 画布不透明时 Dock 呈直角白卡（260919 实测，全 Dock 唯一直角白矩形）。
# 只作用于 icns 出口：Windows .ico 与网页用图平台惯例不同，各自不动。
_MAC_PLATE = 824 / 1024          # 板占画布比例
_MAC_CORNER = 185 / 1024         # 圆角半径比例（约 0.225 × 板宽）


def _mac_masked(master: Image.Image) -> Image.Image:
    """对原画应用 mac 网格遮罩：板外透明。原画（app.png）保持已采纳设计不动。"""
    size = master.width
    plate = round(size * _MAC_PLATE)
    off = (size - plate) // 2
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [off, off, off + plate - 1, off + plate - 1],
        radius=round(plate * _MAC_CORNER / _MAC_PLATE), fill=255)
    out = master.copy()
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out


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
    _mac_masked(master).resize((1024, 1024), Image.Resampling.LANCZOS).save(ICONS / "app.icns")
    # 运行时 Dock 图标：desktop.py 经 webview.start(icon=…) 在 mac 上会
    # setApplicationIconImage 覆盖 bundle icns（pywebview cocoa.py 实测行为）——
    # 传不透明原画会把「白卡」在启动瞬间盖回来，故 mac 必须用遮罩版。
    _mac_masked(master).resize((256, 256), Image.Resampling.LANCZOS).save(ICONS / "app-mac.png")
    (ROOT / "site" / "assets" / "favicon.png").write_bytes((ICONS / "app-64.png").read_bytes())
    for size in (192, 512):
        master.resize((size, size), Image.Resampling.LANCZOS).save(
            ROOT / "site" / "assets" / f"app-{size}.png", optimize=True)
    print("Exported PNG 32/64, ICO 16-256, ICNS up to 1024 (mac-masked), and site icons")


if __name__ == "__main__":
    main()
