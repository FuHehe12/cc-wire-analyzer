"""文档对账：把**代码里的事实**与**文档里的说法**摆在一起，只报差异，不改任何东西。

    uv run python tools/doc_audit.py            # 人看
    uv run python tools/doc_audit.py --json     # 给 agent

为什么存在（`docs/文档维护策略.md` 策略五挂了很久的"待实现"）：
那份策略自己给出的判据是——**给腐化开的药方如果需要人工定期同步，它自己就是下一处腐化**。
文档矩阵已有 8 份、24 万字符，靠"改功能时记得回读"守不住：已经发生过的实例包括
CONTRIBUTING 复述的开发约定失真（自测停在 2 条、不变量停在 3 条、"dev server 实时读模板"
是错的，还真的骗到了人）、验证清单指向不存在的 `settings_guard_selftest.py`、
`IDX_SCHEMA` 在文档里标 4 而代码是 5。这些**全都是机器可判定的**。

对账清单（都只查"机器能判定"的，语义正确性交给人；**不写条数**——条数会长，写了就是下一处腐化）：
  1. HTTP 端点：`@app.route` 的全集 vs 各文档端点表提到的
  2. CLI 子命令：`sub.add_parser` 的全集 vs 文档提到的
  3. 文档里写到的仓库文件路径是否真实存在（防"指了个空"）
  4. 文档里引用的 `IDX_SCHEMA = N` 是否与代码一致
  5. 开发约定「验证」节列的自测命令，对应文件是否存在
  6. 界面语义 token：深色块里的每个 token，`classic`/`light` 是否都给了取值；有没有无人引用的死 token

最后一项是 v0.4.7 加的，来由与前面几项一样：三主题落地后，"新加的 token 要三套都定义"
这条只存在于人的记忆里——实测当时就有 7 个 token 定义了从没被引用。为了让它可判定，
`:root` 拆成了「主题无关」与「深色取值」两块（见 index.html 顶部注释）：**共用的不该出现在
主题块里，深色块里的必须在两个主题块里都有**——这两句都是纯机械判断。

与 `lane_probe` / `self-audit 工作流` 同哲学：**摊开证据，不替人做判断**——差异不等于错误
（文档有意不提某个内部端点是合理的），所以输出是清单不是断言，退出码永远 0。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

# Windows 默认控制台是 GBK，编不出 ✓ 之类的字符 → print 抛 UnicodeEncodeError，脚本以非零码
# 退出，**检查全过也会被读成失败**（260808 撞到：check_render 全 OK 却崩在最后那句 ALL PASSED）。
# src/ 的自测脚本一直有这段，tools/ 四个漏了；中文输出在 GBK 下也只是乱码不可读。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, DOCS = ROOT / "src", ROOT / "docs"
# 260808 docs/ 分层：reference/ = ①参考手册（描述当前实现，会腐化，**这就是对账范围**），
# methodology/ = ③可迁移方法论，根下 = ④元文档。范围是**路径规则不是文件清单**——
# 新文档放进 reference/ 自动进对账，清单式的名单则会因为"忘了加"而漏。
REFERENCE = DOCS / "reference"
# 具名依赖的文档路径集中在此，配 `_read_required` 使用（见那个函数的 docstring）。
GUIDE = REFERENCE / "开发约定.md"
# 文档面：仓库里会提到端点/命令/路径的公开文档（本地 CLAUDE.md 与 issues/ 不进对账——
# 它们是过程记录，允许留下当时的说法）。
DOC_FILES = sorted(DOCS.rglob("*.md")) + [ROOT / "README.md", ROOT / "README.zh.md",
                                         ROOT / "README.ja.md", ROOT / "CONTRIBUTING.md"]
# 端点表也在代码里躺着一份（产物自带的说明书回落），一并当"文档面"对账。
GUIDE_FALLBACK = SRC / "app.py"


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_required(p: pathlib.Path) -> str:
    """读一份**具名依赖**的文档——缺了就报错，不容忍。

    与 `_read` 的区别正是本函数存在的理由：`_read` 读不到就返回 `""`，这对**批量扫描**是对的
    （少一份文档不该让整个对账崩）；但对**具名依赖**是灾难——文档被移走后正则匹配不到任何
    东西，那条检查就静默变成「永远通过」，而脚本照样打印「对账干净」。**「文件不见了」与
    「文件里没问题」在返回值上无法区分**，于是审计工具自己成了惯犯 ③（静默吞异常）。

    260808 把 `docs/` 拆成子目录时就差点踩中：自测清单检查硬编码读 `DOCS / "开发约定.md"`，
    而那份文档已经移进了 `reference/`。
    """
    if not p.exists():
        raise SystemExit(
            f"[doc_audit] 具名文档不存在：{p.relative_to(ROOT)}\n"
            f"  文档被移动或改名了？请更新本文件顶部的路径常量——\n"
            f"  别让这条检查静默失效（那比没有检查更坏，因为它还会报「对账干净」）。")
    return p.read_text(encoding="utf-8")


def _routes() -> set[str]:
    """app.py 的 @app.route 全集（去掉 <var> 参数，只留路径骨架）。"""
    text = _read(SRC / "app.py")
    out = set()
    for m in re.finditer(r'@app\.route\("([^"]+)"', text):
        out.add(re.sub(r"<[^>]+>", "<id>", m.group(1)))
    return out


def _cli_commands() -> set[str]:
    text = _read(SRC / "cli.py")
    return set(re.findall(r'add_parser\("([a-z_]+)"', text))


def _idx_schema() -> int | None:
    m = re.search(r"^IDX_SCHEMA\s*=\s*(\d+)", _read(SRC / "classifier.py"), re.M)
    return int(m.group(1)) if m else None


def _theme_tokens() -> dict:
    """index.html 的语义 token 覆盖面。

    三块的定位：`主题无关` = 三套共用（字体/圆角/过渡），`深色取值` = 默认外观的颜色与阴影，
    两个 `html[data-theme=...]` = 另外两套的取值。判据两条，都是机械的：
      · 深色块里的每个 token，classic 与 light 都必须给出取值——漏一个，那套外观会静默
        落回深色的颜色（不报错、不白屏，只是某个组件在浅底上变成深色块）；
      · 定义了却没人 `var()` 引用的 token 是死的——留着只会让下一个人从里面挑错。
    主题块**覆盖**共用 token 是合法的（实验室日光覆盖了画布网格），不算差异。
    """
    text = _read(SRC / "templates" / "index.html")

    def block(pat: str) -> set[str]:
        m = re.search(pat, text, re.S)
        return set(re.findall(r"(--[a-z0-9-]+)\s*:", m.group(1))) if m else set()

    shared = block(r"主题无关 token.*?\n:root\{(.*?)\n\}")
    dark = block(r"\n:root\{\n\s*/\* ===== 深色专业模式(.*?)\n\}")
    themes = {name: block(r'html\[data-theme="' + name + r'"\]\{(.*?)\n\}')
              for name in ("classic", "light")}
    used = set(re.findall(r"var\((--[a-z0-9-]+)", text))
    # 主题选择器上的局部变量（.theme-option 的色板样例）不是全局 token，不参与
    local = set(re.findall(r"--swatch-[a-z]+", text))

    return {
        "counts": {"shared": len(shared), "dark": len(dark),
                   **{k: len(v) for k, v in themes.items()}},
        "theme_gaps": [{"theme": k, "missing": sorted(dark - v)}
                       for k, v in themes.items() if dark - v],
        "shared_leaked": sorted((shared & dark)),   # 拆块拆漏了：同一个 token 两边都定义
        "dead_tokens": sorted((shared | dark) - used - local),
    }


def audit() -> dict:
    routes, cmds, schema = _routes(), _cli_commands(), _idx_schema()
    doc_text = {p.name: _read(p) for p in DOC_FILES if p.exists()}
    doc_text["app.py(_AI_GUIDE_FALLBACK)"] = _read(GUIDE_FALLBACK)
    joined = "\n".join(doc_text.values())

    # 1. 端点：代码有、契约没写。**只认 API契约.md**——文档维护策略 策略一 指定它是端点的
    #    单一真源，"某份文档里提过"不算数（/api/grep 与 /api/stats 就是这么漏的：
    #    AI_USAGE 有、契约没有，union 式对账查不出来）。
    contract = doc_text.get("API契约.md", "")
    undocumented = sorted(r for r in routes if r.startswith("/api") and r not in contract)
    # 端点表里写了、代码却没有（改名/删除后遗留）。散文里的通配写法（`/api/proxy/*`）
    # 和上游地址片段（`…:5051/api/anthropic`）不是端点引用，按前缀命中真路由就放过。
    # (?<![:\w]) 挡掉完整 URL 里的路径片段（`http://127.0.0.1:5051/api/anthropic` 是上游地址
    # 举例，不是本服务的端点引用）。
    mentioned = set(re.findall(r"(?<![:\w])`?(/api/[a-zA-Z0-9_/<>-]+)", joined))
    ghost_routes = sorted(
        m for m in mentioned
        if re.sub(r"<[^>]+>", "<id>", m.rstrip("/?")) not in routes
        and not m.endswith("<id>")
        and not any(r.startswith(m.rstrip("/")) for r in routes))

    # 2. CLI 子命令
    # 命中形式：`list --date …`（表格里的用法行）/ `list` / `cli.py list …`
    undocumented_cmds = sorted(c for c in cmds
                               if not re.search(rf"`{c}[ `]|cli\.py.{{0,40}}\b{c}\b", joined))

    # 3. 文档提到的仓库文件是否存在
    missing_paths = []
    for name, text in doc_text.items():
        for m in re.finditer(r"`((?:src|tools|docs)/[A-Za-z0-9_./-]+\.(?:py|md|html))`", text):
            if not (ROOT / m.group(1)).exists():
                missing_paths.append({"doc": name, "path": m.group(1)})

    # 4. 文档里**断言当前值**的 IDX_SCHEMA（`IDX_SCHEMA = N`）。历史叙述（`9→10`、
    #    `IDX_SCHEMA=6 起`）是对的，不该报——只有"当前是 N"会误导下一个读者。
    schema_drift = []
    for name, text in doc_text.items():
        for m in re.finditer(r"IDX_SCHEMA`?\s*=\s*(\d+)", text):
            if schema is None or int(m.group(1)) == schema:
                continue
            tail = text[m.end():m.end() + 4]
            if "起" in tail or "→" in tail:      # "自 N 起" / "N→M"：历史，不是当前值
                continue
            schema_drift.append({"doc": name, "says": int(m.group(1)), "code": schema,
                                 "ctx": text[max(0, m.start() - 40):m.end() + 20].replace("\n", " ")})

    # 5. 自测命令对应文件存在吗
    missing_selftests = []
    for m in re.finditer(r"uv run python (src/[A-Za-z0-9_]+\.py)", _read_required(GUIDE)):
        if not (ROOT / m.group(1)).exists():
            missing_selftests.append(m.group(1))

    return {
        "routes": len(routes), "cli_commands": len(cmds), "idx_schema": schema,
        "undocumented_routes": undocumented,
        "ghost_routes": ghost_routes,
        "undocumented_cli": undocumented_cmds,
        "missing_paths": missing_paths,
        "idx_schema_drift": schema_drift,
        "missing_selftest_files": sorted(set(missing_selftests)),
        "tokens": _theme_tokens(),
        "note": "差异 ≠ 错误：有意不写进文档的内部端点也会出现在 undocumented 里。人判断。",
    }


def main() -> None:
    r = audit()
    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    tk = r["tokens"]
    print(f"代码事实：{r['routes']} 个路由 / {r['cli_commands']} 个 CLI 子命令 / "
          f"IDX_SCHEMA={r['idx_schema']} / 语义 token "
          f"{tk['counts']['shared']} 共用 + {tk['counts']['dark']} 深色"
          f"（classic {tk['counts']['classic']} / light {tk['counts']['light']}）\n")
    rows = [("文档里没提到的端点", r["undocumented_routes"]),
            ("文档提到但代码没有的端点", r["ghost_routes"]),
            ("文档里没提到的 CLI 子命令", r["undocumented_cli"]),
            ("文档指向的不存在文件", [f"{x['doc']} → {x['path']}" for x in r["missing_paths"]]),
            ("IDX_SCHEMA 数值不一致", [f"{x['doc']} 写 {x['says']}，代码 {x['code']}"
                                       for x in r["idx_schema_drift"]]),
            ("自测清单里不存在的文件", r["missing_selftest_files"]),
            ("某套外观缺取值的 token", [f"{g['theme']} 缺 {', '.join(g['missing'])}"
                                        for g in tk["theme_gaps"]]),
            ("共用块与深色块重复定义的 token", tk["shared_leaked"]),
            ("定义了但无人引用的 token", tk["dead_tokens"])]
    clean = True
    for title, items in rows:
        if items:
            clean = False
            print(f"[{len(items)}] {title}")
            for it in items:
                print("   -", it)
    print("对账干净：清单上每一项都没有差异。" if clean else f"\n{r['note']}")


def _selftest() -> int:
    """给 token 检查造两个反例，确认它真的会报——检查本身不被验证，就是下一个"存在但不生效"
    的守卫（本项目的惯犯 bug 之一）。不碰真文件，只对字符串跑一遍解析。"""
    import tempfile
    real = (SRC / "templates" / "index.html").read_text(encoding="utf-8")
    broken = real.replace("--focus-ring:rgba(166,107,19,0.45);", "", 1)   # classic 去掉一个
    tmp = pathlib.Path(tempfile.mkdtemp()) / "index.html"
    tmp.write_text(broken, encoding="utf-8")
    orig = globals()["SRC"]
    try:
        globals()["SRC"] = tmp.parent.parent          # 让 _theme_tokens 读到临时文件
        (tmp.parent.parent / "templates").mkdir(exist_ok=True)
        (tmp.parent.parent / "templates" / "index.html").write_text(broken, encoding="utf-8")
        gaps = _theme_tokens()["theme_gaps"]
    finally:
        globals()["SRC"] = orig
    ok = any(g["theme"] == "classic" and "--focus-ring" in g["missing"] for g in gaps)
    print("[token 检查自测]", "PASS 缺失能被检出" if ok else "FAIL 缺失没被检出")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_selftest())
    main()
