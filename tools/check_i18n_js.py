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

# Windows 默认控制台是 GBK，编不出 ✓ 之类的字符 → print 抛 UnicodeEncodeError，脚本以非零码
# 退出，**检查全过也会被读成失败**（260808 撞到：check_render 全 OK 却崩在最后那句 ALL PASSED）。
# src/ 的自测脚本一直有这段，tools/ 四个漏了；中文输出在 GBK 下也只是乱码不可读。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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
    # encoding 必须显式给（260825）：不给的话 text=True 走系统 locale，Windows 上是 GBK，
    # 而 node 报语法错时会把**出错那一行原文**打进 stderr——本项目那一行往往是中日文案，
    # 于是读取管道的线程抛 UnicodeDecodeError、r.stderr 变成 None、脚本崩在下一行。
    # 表现是「真有语法错时这个检查自己先崩掉」，恰恰在最需要它的时候失灵（260825 撞到）。
    r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("node --check:", "OK" if r.returncode == 0 else f"FAIL\n{r.stderr[:2000]}")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
