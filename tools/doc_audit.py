"""文档对账闸门：把**代码里的事实**与**文档里的说法**摆在一起，不改任何东西，但会挡发版。

    uv run python tools/doc_audit.py            # 人看；有硬差异则退出码 1
    uv run python tools/doc_audit.py --json     # 给 agent；数据里看 `ok` 字段
    uv run python tools/doc_audit.py --self-test

**退出码语义（260808 从"永远 0"改成"硬差异即 1"）**：差异分两类，判据见 `_rows()`——
文档**说错**（幽灵端点 / 断链 / 过期的 `IDX_SCHEMA` / 不存在的自测文件 / 缺取值的 token）
会挡；文档**没说**（内部端点、未登记的子命令、死 token）只提示。不分类就一律挡的话，
第一个有意不公开的内部端点就会卡住发版，接着有人会加 `|| true`，闸门永久失效。

这一步是它从"报告"变成"门"的关键：一个永远 exit 0 的检查靠人记得跑、记得看，而
`docs/文档维护策略.md` 自己的判据就是**需要人工定期同步的药方自己就是下一处腐化**。
`.github/workflows/release.yml` 在 PyInstaller 之前跑它，fail-fast。

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

对**软**差异仍与 `lane_probe` / `self-audit 工作流` 同哲学：摊开证据、不替人做判断——
文档有意不提某个内部端点是合理的，那类输出是清单不是断言。硬差异不适用这条：
文档说了代码里不成立的事，没有"留给人判断"的余地。
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
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


# ---- 枚举三件套：代码侧真源 ----------------------------------------------------
# 文档维护策略「策略一 SSOT」为这三类各指定了一个权威位置，但此前没有任何东西**验证**
# 文档抄过去的值还对得上。三者都是具名依赖，用 `_read_required` 读（文件被移走要立刻炸，
# 不能像 `_read` 那样返回 "" 让检查静默变成永远通过）。

def _kinds() -> set[str]:
    """`classifier.KIND_ORDER` 是 kind 的单一真源。"""
    m = re.search(r"KIND_ORDER\s*=\s*\(([^)]*)\)",
                  _read_required(SRC / "classifier.py"), re.S)
    return set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()


def _err_kinds() -> set[str]:
    """`proxy.py` 里每个 `error.kind` 赋值点。

    其中一个是 f-string：`f"upstream_{status // 100}xx"`。它只在 `status >= 400` 的分支里
    执行，所以实际取值只可能是 4xx / 5xx——**这个展开是硬编码的**，因为正则读不出运行时
    的取值范围。改那个分支的条件（比如开始记 3xx）时必须回来改这里。
    """
    t = _read_required(SRC / "proxy.py")
    out = set(re.findall(r'"kind":\s*"([a-z_0-9]+)"', t))
    if re.search(r'"kind":\s*f"upstream_\{', t):
        out |= {"upstream_4xx", "upstream_5xx"}
    return out


def _doctor_codes() -> set[str]:
    """`doctor.py` 的 `_issue(code, ...)` 首个实参 = 规则 code。"""
    return set(re.findall(r'_issue\(\s*"([a-z_]+)"', _read_required(SRC / "doctor.py")))


def _git_ignored(paths: list[str]) -> set[str]:
    """这些路径里哪些被 `.gitignore` 排除——**生成物，文档提到它们不算断链**。

    来由是 `src/_version.py`（260808 CI 首跑抓到）：CI 构建前从 git tag 生成它，仓库里没有。
    本地跑对账时它存在（本地构建生成过），**干净 checkout 里不存在**——所以这条差异
    在本地永远看不见，只在 CI 里现身。这正是加 CI 验证的价值，也说明"本地全绿"从来
    不等于"没问题"。

    用 `git check-ignore` 而不是硬编码一张豁免名单：名单是要人维护的，下一个生成物
    出现时没人记得加——而那正是这个项目反复记录的腐化形态。
    没有 git 时退回严格判断（宁可多报，不可漏报）。
    """
    if not paths:
        return set()
    try:
        r = subprocess.run(["git", "check-ignore", "--stdin"],
                           input="\n".join(paths), capture_output=True,
                           text=True, cwd=ROOT, timeout=15)
        return {ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()


def _lane_kinds() -> set[str]:
    """泳道的 kind（`classifier.build_dag` 里的 `lane_kind`）——**与请求的 kind 是两个枚举**，
    只是恰好都叫 kind。契约里 `"lanes": [{"kind":"main|subagent|aux"}]` 列的是这一个。

    不单独对账它，只是把它并进"已知合法值"全集：首版没有这一步，于是 `aux` 被当成
    err_kind 的幽灵报了出来——文档其实完全正确，是对账工具自己不认识这个枚举。
    """
    t = _read_required(SRC / "classifier.py")
    return set(re.findall(r'lane_kind\s*=\s*"([a-z_]+)"', t))


# ---- 枚举三件套：文档侧声称值 --------------------------------------------------
# **两个方向用两套判据，这是首版写错的地方。**
#
# 首版对两个方向共用一条"反引号斜杠列举"规则，结果一次报出 149 处全是误报——文档里
# `input` / `output` / `cache_read` 这类字段列举、参数列举全是同一个形态，而三类枚举又共用
# 同一份提取结果，于是同一批词被当成三类的幽灵各报一遍。教训：**这些值是 `main` / `other` /
# `connect` 这样的普通英文词，任何不锚定上下文的提取都必然误报**，而误报会毁掉闸门
# （验收线是 0 误报——同 check_refs 的两条判据）。
#
#   幽灵方向（文档列了、代码没有）→ **窄**：只认各自专属的锚点语法，宁可漏报
#   未文档化方向（代码有、文档没列）→ **宽**：只问这个词在文档里出现过没有
#
# 宽窄相反是有道理的：幽灵是硬差异要挡发版，判错代价高；未文档化只是提示，宽匹配
# 让它不至于因为"文档换了种写法提"就虚报。

# 「kind 枚举」这个显式标签所在行里的反引号项（API契约的写法：
#   **kind 枚举**（真源 `src/classifier.py` 的 `KIND_ORDER`）：`main` / `subagent` / …）
_KIND_ANCHOR = re.compile(r"kind\s*枚举[^\n]*")
# 含管道的 JSON 值是全枚举列举：`"kind": "connect|timeout|http_error|…"`
_PIPE_JSON = re.compile(r'"(?:err_)?kind":\s*"([a-z_0-9]+(?:\|[a-z_0-9]+)+)"')
_ERRK_JSON = re.compile(r'"err_kind":\s*"([a-z_0-9]+)"')
# doctor 规则表：| `dead_port_leftover` | error | …
_SEVERITY_ROW = re.compile(r"\|\s*`([a-z_]{4,})`\s*\|\s*(?:error|warning|info)\s*\|")
_CODE_JSON = re.compile(r'"code":\s*"([a-z_]+)"')


def _doc_enum_claims(text: str) -> dict[str, set[str]]:
    """文档**以枚举语法明确列出**的值，按三类分开。"""
    kinds: set[str] = set()
    for line in _KIND_ANCHOR.findall(text):
        kinds |= set(re.findall(r"`([a-z][a-z_0-9]{2,})`", line))
    errk: set[str] = set(_ERRK_JSON.findall(text))
    for v in _PIPE_JSON.findall(text):
        errk |= set(v.split("|"))
    codes: set[str] = set(_SEVERITY_ROW.findall(text)) | set(_CODE_JSON.findall(text))
    return {"kind": kinds, "err_kind": errk, "doctor_code": codes}


def _mentioned_anywhere(text: str, value: str) -> bool:
    """这个枚举值在文档里出现过没有——宽匹配，用于「代码有、文档没列」那一侧。"""
    return re.search(rf"(?<![a-z_0-9]){re.escape(value)}(?![a-z_0-9])", text) is not None


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
    _cands = []
    for name, text in doc_text.items():
        for m in re.finditer(r"`((?:src|tools|docs)/[A-Za-z0-9_./-]+\.(?:py|md|html))`", text):
            if not (ROOT / m.group(1)).exists():
                _cands.append({"doc": name, "path": m.group(1)})
    # 生成物（gitignore 的）不算断链：仓库里本来就没有，文档提它是在讲构建机制
    _ignored = _git_ignored(sorted({c["path"] for c in _cands}))
    missing_paths = [c for c in _cands if c["path"] not in _ignored]

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

    # 6. 枚举三件套：kind / err_kind / doctor rule code
    #    幽灵值（文档列了、代码没有）是硬差异——agent 会照着分支处理一个永远不出现的值，
    #    人会去找一条不存在的规则。未文档化（代码有、文档没列）是软的，与端点同判据。
    kinds, err_kinds, dcodes = _kinds(), _err_kinds(), _doctor_codes()
    claims = _doc_enum_claims(joined)
    all_code_enums = kinds | err_kinds | dcodes | _lane_kinds()

    enums = []
    for label, code_set in (("kind", kinds), ("err_kind", err_kinds),
                            ("doctor_code", dcodes)):
        # 幽灵 = 文档以枚举语法列出、却不属于**任何一类**的代码真源。减去全集而不只是本类，
        # 是因为锚点之间仍会串味（`"kind": "connect|…"` 那行列的其实是 err_kind 的值）。
        # 代价：把 err_kind 的值误写进 kind 的枚举表这种错查不出来——但那种错很罕见，
        # 而误报会让整个闸门被绕过。**宁可漏一种罕见错，不可制造常见误报。**
        ghosts = sorted(claims[label] - all_code_enums)
        # 未文档化用宽匹配：文档里压根没出现过这个词才算
        missing = sorted(v for v in code_set if not _mentioned_anywhere(joined, v))
        enums.append({"enum": label, "ghost": ghosts, "undocumented": missing})

    return {
        "routes": len(routes), "cli_commands": len(cmds), "idx_schema": schema,
        "enums": enums,
        "undocumented_routes": undocumented,
        "ghost_routes": ghost_routes,
        "undocumented_cli": undocumented_cmds,
        "missing_paths": missing_paths,
        "idx_schema_drift": schema_drift,
        "missing_selftest_files": sorted(set(missing_selftests)),
        "tokens": _theme_tokens(),
        "note": ("硬差异（ghost_routes / missing_paths / idx_schema_drift / "
                 "missing_selftest_files / tokens.theme_gaps / tokens.shared_leaked）"
                 "是文档说错了，会挡发版；软差异（undocumented_*、dead_tokens）只是文档没写，"
                 "有意不公开的内部端点会一直待在那里，人判断。看 `ok` 字段，别猜退出码。"),
    }


def _rows(r: dict) -> tuple[list, list]:
    """把九类差异分成「挡发版的」和「只报告的」两组。

    **判据只有一句：文档说了一件代码里不成立的事，还是代码有的东西文档没说。**

    前者（硬）会主动误导读者——照着文档去调一个不存在的端点、点一条断链、信一个过期的
    `IDX_SCHEMA`、按清单跑一个不存在的自测文件。后者（软）只是覆盖不全，读者顶多查不到，
    不会被骗，而且**有意不写进文档的内部端点会永远待在这一类里**。

    这个区分是这个脚本能变成硬门的前提。原先它退出码永远 0，理由正是"差异 ≠ 错误、判断留给
    人"——那个理由对软类成立、对硬类不成立。如果不分类就一律 exit 1，第一个内部端点就会卡住
    发版，接着有人会在 CI 里加 `|| true`，**闸门就永久失效了**——这比没有闸门更糟，因为它还
    挂在那里冒充防线。
    """
    tk = r["tokens"]
    hard = [("文档提到但代码没有的端点", r["ghost_routes"]),
            ("文档指向的不存在文件", [f"{x['doc']} → {x['path']}" for x in r["missing_paths"]]),
            ("IDX_SCHEMA 数值不一致", [f"{x['doc']} 写 {x['says']}，代码 {x['code']}"
                                       for x in r["idx_schema_drift"]]),
            ("自测清单里不存在的文件", r["missing_selftest_files"]),
            ("某套外观缺取值的 token（会变成隐形字）", [f"{g['theme']} 缺 {', '.join(g['missing'])}"
                                                        for g in tk["theme_gaps"]]),
            ("共用块与深色块重复定义的 token", tk["shared_leaked"])]
    hard += [(f"文档列了但代码没有的 {e['enum']} 值", e["ghost"])
             for e in r.get("enums", [])]
    soft = [("文档里没提到的端点", r["undocumented_routes"]),
            ("文档里没提到的 CLI 子命令", r["undocumented_cli"]),
            ("定义了但无人引用的 token", tk["dead_tokens"])]
    soft += [(f"代码有但文档没列的 {e['enum']} 值", e["undocumented"])
             for e in r.get("enums", [])]
    return hard, soft


def main() -> None:
    r = audit()
    hard, soft = _rows(r)
    n_hard = sum(len(v) for _, v in hard)
    r["ok"] = n_hard == 0          # 与 CLI 各子命令同惯例：agent 看 ok，不猜退出码语义

    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        # --json 同样遵守退出码，否则 CI 里换个 --json 就悄悄绕过了闸门
        raise SystemExit(0 if r["ok"] else 1)

    tk = r["tokens"]
    print(f"代码事实：{r['routes']} 个路由 / {r['cli_commands']} 个 CLI 子命令 / "
          f"IDX_SCHEMA={r['idx_schema']} / 语义 token "
          f"{tk['counts']['shared']} 共用 + {tk['counts']['dark']} 深色"
          f"（classic {tk['counts']['classic']} / light {tk['counts']['light']}）\n")

    for title, items in hard:
        if items:
            print(f"[FAIL {len(items)}] {title}")
            for it in items:
                print("   -", it)
    n_soft = sum(len(v) for _, v in soft)
    if n_soft:
        print(f"\n以下 {n_soft} 项**不挡发版**，是提示：代码有、文档没写。"
              f"有意不公开的内部端点/子命令会一直待在这里，人判断。")
        for title, items in soft:
            if items:
                print(f"[提示 {len(items)}] {title}")
                for it in items:
                    print("   -", it)

    if r["ok"]:
        print("\n对账通过：没有任何「文档说了代码里不成立的事」。" if n_soft
              else "对账干净：清单上每一项都没有差异。")
    else:
        print(f"\n对账失败：{n_hard} 处文档与代码矛盾。这些会直接误导读者，修完再发版。")
    raise SystemExit(0 if r["ok"] else 1)


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

    # 门本身也要被验证：分类错了（把硬差异归进软类）闸门就形同虚设，而它照样打印
    # 「对账通过」——正是本项目惯犯 ③「静默失效」的形状，且这次犯在守卫自己身上。
    base = {"routes": 0, "cli_commands": 0, "idx_schema": 1,
            "undocumented_routes": [], "ghost_routes": [], "undocumented_cli": [],
            "missing_paths": [], "idx_schema_drift": [], "missing_selftest_files": [],
            "tokens": {"counts": {}, "theme_gaps": [], "shared_leaked": [], "dead_tokens": []}}

    def n_hard(**over):
        d = {**base, **over}
        return sum(len(v) for _, v in _rows(d)[0])

    cases = [
        ("幽灵端点挡", n_hard(ghost_routes=["/api/gone"]) == 1),
        ("断链挡", n_hard(missing_paths=[{"doc": "x.md", "path": "docs/nope.md"}]) == 1),
        ("IDX_SCHEMA 漂移挡", n_hard(idx_schema_drift=[{"doc": "x", "says": 1, "code": 2}]) == 1),
        ("缺失自测文件挡", n_hard(missing_selftest_files=["src/nope.py"]) == 1),
        ("缺 token 取值挡",
         n_hard(tokens={**base["tokens"], "theme_gaps": [{"theme": "light", "missing": ["--x"]}]}) == 1),
        # 反向：软差异**不该**挡，否则第一个内部端点就卡住发版
        ("未登记端点不挡", n_hard(undocumented_routes=["/api/internal"]) == 0),
        ("未登记子命令不挡", n_hard(undocumented_cli=["secret"]) == 0),
        ("死 token 不挡",
         n_hard(tokens={**base["tokens"], "dead_tokens": ["--unused"]}) == 0),
    ]
    for name, passed in cases:
        print("[闸门分类]", ("PASS " if passed else "FAIL ") + name)
        ok = ok and passed

    # 枚举对账：提取器要认得真源、幽灵要能检出、合法值不许被误报
    allc = _kinds() | _err_kinds() | _doctor_codes() | _lane_kinds()
    fake = "**kind 枚举**（真源 `src/classifier.py`）：`main` / `subagent` / `ghost_kind`。"
    ecases = [
        ("kind 真源可提取", {"main", "subagent", "other"} <= _kinds()),
        ("err_kind 含动态展开的 upstream_4xx/5xx",
         {"upstream_4xx", "upstream_5xx", "connect"} <= _err_kinds()),
        ("doctor code 可提取", "effort_max_rejected_upstream" in _doctor_codes()),
        ("幽灵枚举能检出",
         sorted(_doc_enum_claims(fake)["kind"] - allc) == ["ghost_kind"]),
        # 回归：`aux` 是 lane kind，首版把它报成了 err_kind 的幽灵——文档没错，是工具
        # 不认识第四个枚举。合法值被报成硬差异会直接卡住发版。
        ("lane kind aux 不算幽灵", "aux" in allc),
        # 回归：首版用一条通用的「反引号斜杠列举」判据，把文档里的字段列举全当成枚举，
        # 一次报出 149 处误报。这条守住真实文档必须零幽灵。
        ("真实文档零幽灵", all(not e["ghost"] for e in audit()["enums"])),
        # 回归：CI 首跑抓到 `src/_version.py`——CI 从 tag 生成、仓库里没有，本地却存在，
        # 于是这条差异只在干净 checkout 里现身。生成物不算断链。
        ("gitignore 的生成物被豁免", _git_ignored(["src/_version.py"]) == {"src/_version.py"}),
        ("普通缺失文件不被豁免", _git_ignored(["docs/definitely-not-here.md"]) == set()),
    ]
    for name, passed in ecases:
        print("[枚举对账]", ("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_selftest())
    main()
