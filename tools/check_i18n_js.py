"""一次性校验：i18n 三语键集同步 + 抽取 <script> 做 node --check。"""
import re, subprocess, sys, tempfile, pathlib

ROOT = pathlib.Path(r"D:\Claude\workshop\cc-wire-analyzer")
html = (ROOT / "src" / "templates" / "index.html").read_text(encoding="utf-8")

# --- i18n 键集 ---
tables = {}
for lang in ("zh", "en", "ja"):
    m = re.search(r"\n" + lang + r": \{\n(.*?)\n\},\n", html, re.S)
    if not m:
        print(f"FAIL: {lang} table not found"); sys.exit(1)
    keys = re.findall(r'"([a-zA-Z0-9_.]+)":', m.group(1))
    if len(keys) != len(set(keys)):
        dup = sorted({k for k in keys if keys.count(k) > 1})
        print(f"FAIL: {lang} dup keys: {dup}"); sys.exit(1)
    tables[lang] = set(keys)
base = tables["zh"]
ok = True
for lang in ("en", "ja"):
    miss, extra = base - tables[lang], tables[lang] - base
    if miss or extra:
        ok = False
        print(f"FAIL: {lang} missing={sorted(miss)} extra={sorted(extra)}")
counts = {k: len(v) for k, v in tables.items()}
print(f"i18n keys: {counts} sync={'OK' if ok else 'FAIL'}")
if not ok: sys.exit(1)

# --- 新增键确实在表里 ---
for k in ("dag.spawnedBySub", "dag.laneCascaded"):
    for lang in ("zh", "en", "ja"):
        if k not in tables[lang]:
            print(f"FAIL: {k} not in {lang}"); sys.exit(1)
print("new keys present: dag.spawnedBySub, dag.laneCascaded")

# --- JS 语法 ---
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
js = "\n;\n".join(scripts)
tmp = pathlib.Path(tempfile.gettempdir()) / "ccwa_check.js"
tmp.write_text(js, encoding="utf-8")
r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
print("node --check:", "OK" if r.returncode == 0 else f"FAIL\n{r.stderr[:2000]}")
sys.exit(0 if r.returncode == 0 else 1)
