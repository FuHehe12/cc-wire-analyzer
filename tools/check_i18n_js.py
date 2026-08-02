"""前端静态校验：i18n 三语键集同步 + 抽取 <script> 做 `node --check`。

    uv run python tools/check_i18n_js.py

改 `src/templates/index.html` 后跑它（键集不同步会在运行时把 key 名显示给用户，
JS 语法错会让整个页面白屏——两者都不会有任何后端报错）。

260802 重写：原版是一次性脚本——写死了维护者的绝对路径、写死了"那一次"新增的两个键名，
放在 tools/ 里看着像通用工具，实际只对那一次改动有意义（`node --check` 还会被模板占位符
噎住）。工具留在仓库里就会被下一个人当通用的用，要么写通用，要么别留。"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "src" / "templates" / "index.html"
LANGS = ("zh", "en", "ja")


def main() -> int:
    html = HTML.read_text(encoding="utf-8")
    tables: dict[str, set[str]] = {}
    for lang in LANGS:
        m = re.search(r"\n" + lang + r": \{\n(.*?)\n\},\n", html, re.S)
        if not m:
            print(f"FAIL: {lang} 表没找到（i18n 表结构变了？）")
            return 1
        keys = re.findall(r'"([a-zA-Z0-9_.]+)":', m.group(1))
        if len(keys) != len(set(keys)):
            print(f"FAIL: {lang} 重复键: {sorted({k for k in keys if keys.count(k) > 1})}")
            return 1
        tables[lang] = set(keys)

    ok = True
    for lang in LANGS[1:]:
        miss, extra = tables[LANGS[0]] - tables[lang], tables[lang] - tables[LANGS[0]]
        if miss or extra:
            ok = False
            print(f"FAIL: {lang} 缺={sorted(miss)} 多={sorted(extra)}")
    print(f"i18n keys: { {k: len(v) for k, v in tables.items()} } sync={'OK' if ok else 'FAIL'}")
    if not ok:
        return 1

    # 模板占位符先填掉再检查语法：index.html 是 Jinja 模板，`{{ x }}` 不是合法 JS。
    # 用 JSON 空数组替身——只验语法结构，值是什么无关。
    js = "\n;\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    js = re.sub(r"\{\{.*?\}\}", json.dumps([]), js)
    tmp = pathlib.Path(tempfile.gettempdir()) / "ccwa_check.js"
    tmp.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
    print("node --check:", "OK" if r.returncode == 0 else f"FAIL\n{r.stderr[:2000]}")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
