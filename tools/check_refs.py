#!/usr/bin/env python3
"""前端引用完整性审计（260808）：每个名字必须能解析到它的声明。

    uv run python tools/check_refs.py             # 审计
    uv run python tools/check_refs.py --self-test # 造反例，验证它真会报

根因：260807 上游历史那一轮撞出三个前端 bug，现有三条静态对账只抓到一个——
  ① `const n` 重复声明                       → `check_i18n_js` 的 `node --check` 抓到
  ② 调 `loadStatus()`，真名是 `refreshStatus()` → 漏（表现：修复成功但绿色回执不出现，
     ReferenceError 把成功分支甩进了 catch）
  ③ 提示元素 `class="sub"`，而 `sub` 的规则是 `.srow .sub`，元素却是 `.scard` 直接子元素
     → 漏（表现：红字字号不协调，用户看出来的）
②③ 的共同点是**都不是语法错**：`node --check` 只验语法结构、不验标识符能否解析；
CSS 里一条匹配不上的选择器在浏览器看来完全合法。两者都只有「人真去点/看」才暴露。

为什么是静态而不是 ESLint：单文件无构建链是有意选择（开发约定第六节——加构建链等于给每个
贡献者加 Node 工具链）。`node --check` 已是既有依赖、无需 npm install；ESLint 要装包。

两项检查（本质是同一件事——引用能否解析，所以合在一个脚本里）：
  一、JS 标识符引用：每个被调用的函数名必须解析到定义（含 HTML 内联 `onclick=` 里的调用）
  二、CSS 类引用：  每个静态 HTML 里用到的类，必须至少被它自己的一条规则真正命中

**误报即失败**：两项的验收线都是当前代码基线为 0。理由与配置体检的铁律同源——
第二次误报之后就再没人看这个脚本了，那比没有它更坏。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from html.parser import HTMLParser

# Windows 默认控制台是 GBK，编不出 ✓ 之类的字符 → print 抛 UnicodeEncodeError，脚本以非零码
# 退出，**检查全过也会被读成失败**（260808 撞到：check_render 全 OK 却崩在最后那句 ALL PASSED）。
# src/ 的自测脚本一直有这段，tools/ 四个漏了；中文输出在 GBK 下也只是乱码不可读。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "src" / "templates" / "index.html"

IDENT = r"[A-Za-z_$][\w$]*"
CLS = r"[A-Za-z_][\w-]*"

# 浏览器全局 + 两个内联库（marked / DOMPurify，见 <script src="/static/...">）。
# 新用一个浏览器 API 就往这里加一行——这张表就是本检查要维护的契约。
GLOBALS = {
    "console", "JSON", "Math", "Date", "fetch", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "parseInt", "parseFloat", "isNaN", "String",
    "Number", "Boolean", "Array", "Object", "Promise", "Error", "RegExp", "Set",
    "Map", "WeakMap", "Symbol", "BigInt", "Proxy", "Reflect", "encodeURIComponent",
    "decodeURIComponent", "alert", "confirm", "prompt", "requestAnimationFrame",
    "cancelAnimationFrame", "structuredClone", "queueMicrotask", "Intl", "URL",
    "URLSearchParams", "Blob", "FormData", "getComputedStyle", "matchMedia",
    "btoa", "atob", "EventSource", "AbortController", "TextDecoder", "TextEncoder",
    "marked", "DOMPurify",
}
KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof", "new",
    "await", "else", "do", "try", "delete", "void", "in", "of", "instanceof",
    "case", "yield", "throw", "with", "super", "constructor",
    # `async (…) => …`（异步箭头函数）在词法上与调用同形。260808 加更新面板时撞到：
    # `setInterval(async () => {…}, 500)` 被判成"调用了一个叫 async 的函数"。
    # 这是判据的漏洞，不是代码的问题——按项目铁律，check_refs 的验收线是 0 误报。
    "async",
}
# 这些关键字后面的 `/` 是正则开头而不是除号
REGEX_OK_AFTER = {
    "return", "typeof", "case", "in", "of", "new", "delete", "void",
    "instanceof", "do", "else", "yield", "await", "throw",
}
VOID_TAGS = {"br", "img", "input", "hr", "meta", "link", "source", "track", "wbr"}


# ---------------------------------------------------------------- JS 词法剥离

def _regex_here(prev: str) -> bool:
    """此处的 `/` 是正则开头还是除号：看前一个有意义 token 能否结束一个表达式。"""
    s = prev.rstrip()
    if not s:
        return True
    ch = s[-1]
    if ch in ")]":
        return False                              # (a)/b、arr[i]/2 → 除法
    if ch.isalnum() or ch in "_$":
        m = re.search(IDENT + r"$", s)
        return bool(m) and m.group(0) in REGEX_OK_AFTER
    return True                                   # 运算符 / ( / , / = / ; / : 之后 → 正则


def strip_literals(src: str) -> str:
    """把字符串、注释、正则字面量替换成等长空白（保留换行，行号不变）。

    模板字符串的 `${...}` **保留**并加括号——真正的调用大量住在里面。
    正则字面量必须识别：漏掉的话 `/['"]/` 里的引号会开一个假字符串，把后面整段吞掉。
    实测漏这一条会让 24 个明明有定义的函数（含 1896 行的 `toast`）被误判为未定义——
    这是本脚本从「47 条噪声」降到 0 的两级台阶里更隐蔽的那级。
    """
    out: list[str] = []
    i, n = 0, len(src)

    def blanked(seg: str) -> str:
        return "".join(c if c == "\n" else " " for c in seg)

    while i < n:
        c = src[i]
        if c in ('"', "'"):
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(blanked(src[i:j + 1]))
            i = j + 1
        elif c == "`":
            j = start = i + 1
            out.append(" ")
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                    k, depth = j + 2, 1
                    while k < n and depth:
                        if src[k] == "{":
                            depth += 1
                        elif src[k] == "}":
                            depth -= 1
                        k += 1
                    out.append(blanked(src[start:j]))
                    out.append("(" + src[j + 2:k - 1] + ")")
                    start = j = k
                    continue
                if src[j] == "`":
                    break
                j += 1
            out.append(blanked(src[start:j + 1]))
            i = j + 1
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i)
            j = n if j < 0 else j + 2
            out.append(blanked(src[i:j]))
            i = j
        elif c == "/" and _regex_here("".join(out)):
            j, in_class, closed = i + 1, False, False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "\n":
                    break                         # 正则不跨行 → 其实是除号，退回
                elif src[j] == "/" and not in_class:
                    closed = True
                    break
                j += 1
            if closed:
                out.append(" " * (j - i + 1))
                i = j + 1
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- 检查一：JS

def check_js(html: str) -> list[str]:
    js = "\n;\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    js = re.sub(r"\{\{.*?\}\}", json.dumps([]), js)     # Jinja 占位符不是合法 JS
    code = strip_literals(js)

    defined = set(re.findall(r"\bfunction\s+(" + IDENT + r")\s*\(", code))
    defined |= set(re.findall(r"\b(?:const|let|var)\s+(" + IDENT + r")\s*=", code))
    defined |= set(re.findall(r"\bclass\s+(" + IDENT + r")", code))
    defined |= set(re.findall(r"\bwindow\.(" + IDENT + r")\s*=", code))

    # 形参整体计入白名单：回调形参被调用是常态（`function f(cb){cb()}`）。
    # 精确作用域分析要写完整 JS 解析器——宁可放过，不可误报。
    params: set[str] = set()
    for m in re.finditer(r"\bfunction\s*[\w$]*\s*\(([^)]*)\)", code):
        params |= set(re.findall(IDENT, m.group(1)))
    for m in re.finditer(r"\(([^()]*)\)\s*=>", code):
        params |= set(re.findall(IDENT, m.group(1)))
    params |= set(re.findall(r"(" + IDENT + r")\s*=>", code))

    known = defined | params | GLOBALS
    problems: list[str] = []

    calls: dict[str, int] = {}
    for m in re.finditer(r"(?<![.\w$])(" + IDENT + r")\s*\(", code):
        nm = m.group(1)
        if nm not in KEYWORDS:
            calls.setdefault(nm, code[:m.start()].count("\n") + 1)
    for nm, line in sorted(calls.items(), key=lambda kv: kv[1]):
        if nm not in known:
            problems.append(f"JS 第 {line} 行（<script> 内累计行号）调用 {nm}() —— 无定义")

    # HTML 内联事件处理器：onclick="foo()" 是这类 bug 最常见的入口，
    # 且它连 `node --check` 的视野都不在（不在 <script> 里）。
    inline: dict[str, int] = {}
    for m in re.finditer(r'\son[a-z]+\s*=\s*"([^"]*)"', html):
        for nm in re.findall(r"(?<![.\w$])(" + IDENT + r")\s*\(", m.group(1)):
            if nm not in KEYWORDS:
                inline.setdefault(nm, html[:m.start()].count("\n") + 1)
    for nm, line in sorted(inline.items(), key=lambda kv: kv[1]):
        if nm not in defined and nm not in GLOBALS:
            problems.append(f"index.html:{line} 内联事件调用 {nm}() —— 无定义")

    print(f"[JS] 调用名 {len(calls)}（内联 {len(inline)}）/ 定义 {len(defined)} / "
          f"形参 {len(params)} → 未解析 {len(problems)}")
    return problems


# ---------------------------------------------------------------- 检查二：CSS

class _Tree(HTMLParser):
    """解析静态 HTML，记录每个类用法的「自身类集合 + 祖先类集合」。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[set[str]] = []
        self.uses: list[tuple[str, int, set[str], set[str]]] = []

    def handle_starttag(self, tag, attrs):
        own = set((dict(attrs).get("class") or "").split())
        anc: set[str] = set().union(*self.stack) if self.stack else set()
        for c in own:
            self.uses.append((c, self.getpos()[0], own, anc))
        if tag not in VOID_TAGS:
            self.stack.append(own)

    def handle_endtag(self, tag):
        if tag not in VOID_TAGS and self.stack:
            self.stack.pop()


def _split_selector(sel: str) -> list[str]:
    sel = re.sub(r"::?[a-zA-Z-]+(\([^)]*\))?", "", sel)   # 去伪类 / 伪元素
    sel = re.sub(r"\[[^\]]*\]", "", sel)                  # 去属性选择器
    return [p for p in re.split(r"[\s>+~]+", sel) if p]   # 组合符按后代一视同仁


def _requirements(cls: str, sel: str) -> tuple[set[str], set[str]] | None:
    """某条选择器对 cls 的要求 → (自身要求, 祖先要求)；cls 只作祖先出现时返回 None。

    关键判断（探针踩过）：`.turn-badge.sub` 是**复合**选择器，不是裸 `.sub`——
    同一复合里的其他类是**自身要求**。第一版把它当成裸规则而豁免，
    结果变异测试整个漏报（`.sub` 那个真 bug 一条都没报出来）。
    """
    parts = _split_selector(sel)
    if not parts:
        return None
    last_classes = set(re.findall(r"\.(" + CLS + r")", parts[-1]))
    if cls not in last_classes:
        return None                                        # 这里 cls 是祖先，不是目标
    anc_req: set[str] = set()
    for p in parts[:-1]:
        anc_req |= set(re.findall(r"\.(" + CLS + r")", p))
    return last_classes - {cls}, anc_req


def check_css(html: str) -> list[str]:
    style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)

    rules: dict[str, set[str]] = {}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", style):
        group = m.group(1)
        if group.strip().startswith("@") or ":root" in group:
            continue
        for sel in group.split(","):
            for cls in re.findall(r"\.(" + CLS + r")", sel.strip()):
                rules.setdefault(cls, set()).add(sel.strip())

    tree = _Tree()
    tree.feed(html[html.find("</style>"):])

    # JS 运行时加的类 → 视为「可能存在」。不豁免的话，`.test-result` 这种规则全是
    # `.test-result.ok/.err/.busy`、静态 HTML 上一个状态类都没有的合法写法会被判失配
    # （实测基线那 2 条噪声就是它贡献的）。
    dynamic: set[str] = set()
    for m in re.finditer(r"classList\.(?:add|toggle|remove)\(([^)]*)\)", html):
        dynamic |= set(re.findall(r"""['"](""" + CLS + r""")['"]""", m.group(1)))
    for m in re.finditer(r"""className\s*=\s*['"]([^'"]*)['"]""", html):
        dynamic |= set(m.group(1).split())

    problems: list[str] = []
    for cls, line, own, anc in tree.uses:
        sels = rules.get(cls)
        if not sels:
            continue                       # 零规则的类由下面的「查询锚点」提示处理
        candidates = []
        for s in sels:
            r = _requirements(cls, s)
            if r is not None:
                candidates.append((s, r))
        if not candidates:
            continue
        for _sel, (self_req, anc_req) in candidates:
            if (self_req - dynamic) <= own and (not anc_req or anc_req & (anc | dynamic)):
                break
        else:
            shown = sorted(s for s, _ in candidates)[:3]
            problems.append(
                f'index.html:{line} class="{cls}" 没有任何一条自己的规则命中'
                f"（自身类 {sorted(own)}；祖先含 {sorted(anc)[:5]}；规则 {shown}）")

    # 提示项（不判失败）：用了但零规则的类。当前 4 个全是 querySelector(".bt-full")
    # 这类**纯 JS 查询锚点**，故意不给样式——按「被查询引用过」自动豁免。
    hooks: set[str] = set()
    for m in re.finditer(r"(?:querySelector(?:All)?|closest|getElementsByClassName)\(([^)]*)\)", html):
        hooks |= set(re.findall(r"\.?(" + CLS + r")", m.group(1)))
    unstyled = sorted({c for c, _, _, _ in tree.uses if c not in rules and c not in hooks})

    print(f"[CSS] 规则类 {len(rules)} / 静态用法 {len(tree.uses)} / 动态类 {len(dynamic)} "
          f"→ 失配 {len(problems)}")
    if unstyled:
        print("      提示：用了但零规则、且不是 JS 查询锚点的类：" + ", ".join(unstyled))
    return problems


# ---------------------------------------------------------------- 变异自测

def self_test() -> int:
    """造反例证明检查真会响——只证明当前代码干净是不够的（沿用 check_render 的做法）。

    两个变异直接复刻 260807 的两个真 bug。**在内存里变异，绝不落盘**：
    这个脚本审的是仓库源文件，任何写回都可能被中断或别的 agent 撞成半吊子
    （本机同时跑多个 agent CLI，见 CLAUDE.md）。
    """
    orig = HTML.read_text(encoding="utf-8")
    ok = True

    # 变异 1：把一处**调用**改名（不是定义），复刻 loadStatus / refreshStatus。
    # 负向断言 `(?!\s*\{)` 很关键：`function refreshStatus(){` 里也含 "refreshStatus()"，
    # 改到定义上就成了「重命名函数」——那是另一种 bug，不是本轮要复刻的形状。
    m = re.search(r"(?<![\w$.])refreshStatus\(\)(?!\s*\{)", orig)
    if not m:
        print("SELFTEST FAIL: 找不到 refreshStatus() 调用点，锚点变了")
        return 1
    hit = [p for p in check_js(orig[:m.start()] + "loadStatus()" + orig[m.end():])
           if "loadStatus" in p]
    print(f"  变异 1（调用 loadStatus()）→ {'抓到' if hit else '**漏报**'}")
    ok &= bool(hit)

    # 变异 2：把提示元素改回 class="sub"（规则是 `.srow .sub`，而它是 .scard 直接子元素）
    anchor = '<div class="fix-note" id="cfgFixNote"></div>'
    if anchor not in orig:
        print("SELFTEST FAIL: 找不到 fix-note 锚点，模板变了")
        return 1
    hit = [p for p in check_css(orig.replace(anchor, '<div class="sub" id="cfgFixNote"></div>', 1))
           if 'class="sub"' in p]
    print(f"  变异 2（class=\"sub\" 挂在 .scard 下）→ {'抓到' if hit else '**漏报**'}")
    ok &= bool(hit)

    print("SELFTEST:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    html = HTML.read_text(encoding="utf-8")
    problems = check_js(html) + check_css(html)
    if problems:
        print("\nFAIL —— 有引用解析不了：")
        for p in problems:
            print("  " + p)
        return 1
    print("OK —— 所有 JS 调用与 CSS 类引用都能解析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
