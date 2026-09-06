"""Build the local standalone manual and portable exports from repository sources.

Run: .venv/Scripts/python.exe tools/build/build_manual.py
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

def main():
    if sys.version_info < (3, 12):
        raise SystemExit('Manual build requires Python 3.12+; use the project virtual environment.')
    subprocess.run([sys.executable, str(ROOT / 'tools/build/manual/build_product.py')], cwd=ROOT, check=True)
    output = ROOT / 'dist/manual'
    output.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'product-expanded.json', 'AI_产品定义与需求推导.md', 'AI_新产品需求导图.opml'):
        shutil.copyfile(ROOT / 'build/manual' / name, output / name)
    print(f'Local manual: {output / "index.html"}')

if __name__ == '__main__':
    main()
