"""文档对账：把**代码里的事实**与**文档里的说法**摆在一起，只报差异，不改任何东西。

    uv run python tools/doc_audit.py            # 人看
    uv run python tools/doc_audit.py --json     # 给 agent

为什么存在（`docs/文档维护策略.md` 策略五挂了很久的"待实现"）：
那份策略自己给出的判据是——**给腐化开的药方如果需要人工定期同步，它自己就是下一处腐化**。
文档矩阵已有 8 份、24 万字符，靠"改功能时记得回读"守不住：已经发生过的实例包括
CONTRIBUTING 复述的开发约定失真（自测停在 2 条、不变量停在 3 条、"dev server 实时读模板"
是错的，还真的骗到了人）、验证清单指向不存在的 `settings_guard_selftest.py`、
`IDX_SCHEMA` 在文档里标 4 而代码是 5。这些**全都是机器可判定的**。

对账五项（都只查"机器能判定"的，语义正确性交给人）：
  1. HTTP 端点：`@app.route` 的全集 vs 各文档端点表提到的
  2. CLI 子命令：`sub.add_parser` 的全集 vs 文档提到的
  3. 文档里写到的仓库文件路径是否真实存在（防"指了个空"）
  4. 文档里引用的 `IDX_SCHEMA = N` 是否与代码一致
  5. 开发指南「验证」节列的自测命令，对应文件是否存在

与 `lane_probe` / `self-audit 工作流` 同哲学：**摊开证据，不替人做判断**——差异不等于错误
（文档有意不提某个内部端点是合理的），所以输出是清单不是断言，退出码永远 0。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, DOCS = ROOT / "src", ROOT / "docs"
# 文档面：仓库里会提到端点/命令/路径的公开文档（本地 CLAUDE.md 与 issues/ 不进对账——
# 它们是过程记录，允许留下当时的说法）。
DOC_FILES = sorted(DOCS.glob("*.md")) + [ROOT / "README.md", ROOT / "README.zh.md",
                                         ROOT / "README.ja.md", ROOT / "CONTRIBUTING.md"]
# 端点表也在代码里躺着一份（产物自带的说明书回落），一并当"文档面"对账。
GUIDE_FALLBACK = SRC / "app.py"


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


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
    for m in re.finditer(r"uv run python (src/[A-Za-z0-9_]+\.py)", _read(DOCS / "开发指南.md")):
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
        "note": "差异 ≠ 错误：有意不写进文档的内部端点也会出现在 undocumented 里。人判断。",
    }


def main() -> None:
    r = audit()
    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    print(f"代码事实：{r['routes']} 个路由 / {r['cli_commands']} 个 CLI 子命令 / "
          f"IDX_SCHEMA={r['idx_schema']}\n")
    rows = [("文档里没提到的端点", r["undocumented_routes"]),
            ("文档提到但代码没有的端点", r["ghost_routes"]),
            ("文档里没提到的 CLI 子命令", r["undocumented_cli"]),
            ("文档指向的不存在文件", [f"{x['doc']} → {x['path']}" for x in r["missing_paths"]]),
            ("IDX_SCHEMA 数值不一致", [f"{x['doc']} 写 {x['says']}，代码 {x['code']}"
                                       for x in r["idx_schema_drift"]]),
            ("自测清单里不存在的文件", r["missing_selftest_files"])]
    clean = True
    for title, items in rows:
        if items:
            clean = False
            print(f"[{len(items)}] {title}")
            for it in items:
                print("   -", it)
    print("对账干净：机器可判定的六项没有差异。" if clean else f"\n{r['note']}")


if __name__ == "__main__":
    main()
