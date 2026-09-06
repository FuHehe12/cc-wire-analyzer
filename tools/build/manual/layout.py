from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
PRODUCT = ROOT / "docs" / "product"
DATA = PRODUCT / "data"
TOOLS = Path(__file__).resolve().parent
OUT = ROOT / "build" / "manual"
