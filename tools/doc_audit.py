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
  7. 端点标题的机械事实（260904）：同一 (方法, 路径) 只准占一节；标题声明的方法与查询参数
     必须在代码里成立；`error_code` 的取值必须在代码里出现过
  8. markdown 相对链接点得到（第 3 项查的是"反引号里提到的文件在不在"，这项查"点下去到不到"）
  9. CHANGELOG 的两条量（260904）：未发布节条目 ≤25 词 / ≤40 字；整份文件不许硬折行

最后一项是 v0.4.7 加的，来由与前面几项一样：三主题落地后，"新加的 token 要三套都定义"
这条只存在于人的记忆里——实测当时就有 7 个 token 定义了从没被引用。为了让它可判定，
`:root` 拆成了「主题无关」与「深色取值」两块（见 index.html 顶部注释）：**共用的不该出现在
主题块里，深色块里的必须在两个主题块里都有**——这两句都是纯机械判断。

对**软**差异仍与 `lane_probe` / `self-audit 工作流` 同哲学：摊开证据、不替人做判断——
文档有意不提某个内部端点是合理的，那类输出是清单不是断言。硬差异不适用这条：
文档说了代码里不成立的事，没有"留给人判断"的余地。
"""
from __future__ import annotations

import ast
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
HANDBOOK = ROOT / "handbook"
# docs/ 分层（260808 立、260904 收敛成两层）：reference/ = 参考手册（描述当前实现、会腐化，
# **这就是对账范围**），根下 = 元文档。范围是**路径规则不是文件清单**——新文档放进
# reference/ 自动进对账，清单式的名单则会因为"忘了加"而漏。
# 原 `methodology/` 260904 拆掉：`报文解读.md` 随代码腐化（kind 枚举的对账一直扫的就是它，
# 而它被归成"不用管"那一类，实测已腐化）→ 并进 reference/；`同类工具构建手册.md` 的受众在
# 本项目之外、不随本项目迭代 → 搬到仓库根 `handbook/`。**handbook/ 仍进文档面**：
# 它引用本项目的端点与文件路径，断链和幽灵端点照样要查（只是不在"描述当前实现"那一类里）。
REFERENCE = DOCS / "reference"
# 具名依赖的文档路径集中在此，配 `_read_required` 使用（见那个函数的 docstring）。
GUIDE = REFERENCE / "开发约定.md"
# 文档面：仓库里会提到端点/命令/路径的公开文档（本地 CLAUDE.md 与 issues/ 不进对账——
# 它们是过程记录，允许留下当时的说法）。
DOC_FILES = (sorted(DOCS.rglob("*.md")) + sorted(HANDBOOK.rglob("*.md"))
             + [ROOT / "README.md", ROOT / "README.zh.md",
                ROOT / "README.ja.md", ROOT / "CONTRIBUTING.md"])
# 端点表也在代码里躺着一份（产物自带的说明书回落），一并当"文档面"对账。
GUIDE_FALLBACK = SRC / "app.py"

# **别的工具的端点**。文档里出现它们是正常的——`handbook/同类工具构建手册.md` 的主题
# 就是给其他 agent 工具做同类分析器，写到被测工具的端点是这份文档的本职内容。
#
# 形状照 `classifier.KNOWN_BETAS`：硬编码 + 可审计 + 一条一条加，每条注明属于谁。
# **不整篇豁免那份手册**——实测它那 5 处端点引用有 4 处是本项目的真端点
# （`/api/unknowns` ×3、`/api/ai-guide` ×1），整篇豁免等于为消一个误报放弃四处真覆盖：
# 「主语是别的工具」是段落属性，不是文件属性，用文件粒度的规则去切它必然误伤。
EXTERNAL_ENDPOINTS = {
    "/api/anthropic/v1/messages",   # zcode：Electron 客户端 → 自家后端（TLS MITM 实测那节）
}


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
      · **引用了却没人定义、且没写 fallback 的 token 是隐形失效**（260826 加）：CSS 里
        `color:var(--没定义)` 不是报错也不是落回默认值，而是整条声明作废，颜色静默继承父级。
        分析视图（260808 加入）沿用一套老命名（`--text` / `--text-dim` / `--bg`），21 处引用
        就这么空转了两周多没人发现——那一族颜色分层在三套外观下全部消失，而界面看起来"有颜色"。
        带 fallback 的引用（`var(--mono,ui-monospace)`）不算这一类：它有确定的降级结果，
        只是可能降到不想要的值上，那是判断题不是错误。
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
    # 无 fallback 的引用（`var(--x)` 而非 `var(--x, 兜底)`）对着**文件里任何地方**的定义解析：
    # 组件局部变量（`.sticky:nth-of-type(3n){--paper:…}`）与 JS 内联下发的（`--tilt`）都算数。
    bare = set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*\)", text))
    anywhere = set(re.findall(r"(--[a-z0-9-]+)\s*:", text))

    return {
        "counts": {"shared": len(shared), "dark": len(dark),
                   **{k: len(v) for k, v in themes.items()}},
        "theme_gaps": [{"theme": k, "missing": sorted(dark - v)}
                       for k, v in themes.items() if dark - v],
        "shared_leaked": sorted((shared & dark)),   # 拆块拆漏了：同一个 token 两边都定义
        "dead_tokens": sorted((shared | dark) - used - local),
        "unresolved_refs": sorted(bare - anywhere),
    }


# ---- 枚举三件套：代码侧真源 ----------------------------------------------------
# 文档维护策略「策略一 SSOT」为这三类各指定了一个权威位置，但此前没有任何东西**验证**
# 文档抄过去的值还对得上。三者都是具名依赖，用 `_read_required` 读（文件被移走要立刻炸，
# 不能像 `_read` 那样返回 "" 让检查静默变成永远通过）。

# ===== 端点标题的机械事实（260904，批二）=====
# 批一修掉的那份分叉复制品（同一端点写了两遍、内容已经不一致）是**结果**不是原因：
# 端点的机械事实靠人手抄进文档，抄一次就多一个会各自演化的副本。原有对账只查
# 「路径存不存在」——**同一个端点写两遍照样满足"提到了"**，方法写错、参数写错一概看不见。
def _route_facts() -> dict[str, dict]:
    """每个路由的 methods 与它真读的查询参数名。

    用 AST 不用正则：`methods=[...]` 与 `request.args.get("x")` 都要按函数体归属，
    正则读不出"这个 args.get 属于哪个视图函数"。
    """
    tree = ast.parse(_read_required(SRC / "app.py"))
    out: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args: set[str] = set()
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ("get", "getlist")
                    and isinstance(sub.func.value, ast.Attribute)
                    and sub.func.value.attr in ("args", "form")
                    and sub.args and isinstance(sub.args[0], ast.Constant)):
                args.add(sub.args[0].value)
        for d in node.decorator_list:
            if not (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "route"
                    and d.args and isinstance(d.args[0], ast.Constant)):
                continue
            methods = {"GET"}
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = {e.value for e in kw.value.elts if isinstance(e, ast.Constant)}
            e = out.setdefault(_norm_path(d.args[0].value),
                               {"methods": set(), "args": set(), "funcs": []})
            e["methods"] |= methods
            e["args"] |= args
            e["funcs"].append(node.name)
    return out


def _norm_path(p: str) -> str:
    """路径骨架：`<sid>` / `<id>` 一律归一（契约里统一写 `<id>`，代码里多是 `<sid>`）。"""
    return re.sub(r"<[^>]+>", "<id>", p.rstrip("/?"))


# 端点标题形如：### `GET|POST /api/snapshots/<id>/analysis` — 说明
#               ### `GET /api/snapshots/<id>/subagents[?lane=&step=]` — 说明
#               ### `GET /api/snapshots/<id>/thinking?level=0|1|2&step=N&budget=` — 说明
_HEAD = re.compile(r"^### `([A-Z|]+) (/[^\s`?\[]+)([^`]*)`", re.M)


def _contract_heads(text: str) -> list[dict]:
    """契约里的端点标题 → [{methods, path, args}]。标题是这份文档的**索引**，
    也是唯一一处"每个端点恰好一节"的结构承诺——重复即分叉的开始。"""
    heads = []
    for m in _HEAD.finditer(text):
        heads.append({"methods": set(m.group(1).split("|")),
                      "path": _norm_path(m.group(2)),
                      "args": set(re.findall(r"[?&]([a-z_0-9]+)=", m.group(3))),
                      "raw": f"{m.group(1)} {m.group(2)}{m.group(3)}"})
    return heads


def _error_codes() -> set[str]:
    """代码里真出现过的 `error_code` 取值。三种写法：直接写进响应字面量、异常类的
    `code=`、`raise XError("code", …)`。**跨模块扫 src/**——错误码是端点契约的一部分，
    但生产它的常常不是 app.py（trajectory / snapshot_pack / updater 各有一批）。"""
    out: set[str] = set()
    for p in sorted(SRC.glob("*.py")):
        t = _read(p)
        out |= set(re.findall(r'"error_code":\s*"([a-z_0-9]+)"', t))
        out |= set(re.findall(r'\bcode\s*=\s*"([a-z_0-9]+)"', t))
        out |= set(re.findall(r'Error\(\s*"([a-z_0-9]{3,})"', t))
    return out


# markdown 相对链接。反引号里的路径（`docs/x.md`）另有一条检查，那条查的是"提到的文件在不在"；
# 这条查的是"点下去到不到得了"——**两者会各自漏**：260904 把两份文档换目录时，
# 手册里一条同目录写法的兄弟链接（`[报文解读.md](报文解读.md)`）就这么断在那儿，
# 反引号那条完全看不见它。
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def _dead_links() -> list[str]:
    """指不到东西的相对链接。

    **跳过解析后落在仓库外的**（`../../releases` 这类）：那是 GitHub 的相对写法，
    在网页上能用、在文件系统里本来就不该存在。用"跳出仓库根"当判据而不是维护一张
    白名单——白名单是会腐化的那种东西，判据不是。
    """
    bad = []
    for f in DOC_FILES:
        if not f.exists():
            continue
        for m in _MD_LINK.finditer(_read(f)):
            t = m.group(1)
            if t.startswith(("http://", "https://", "mailto:")):
                continue
            tgt = (f.parent / t).resolve()
            if ROOT not in tgt.parents and tgt != ROOT:
                continue
            if not tgt.exists():
                bad.append(f"{f.relative_to(ROOT)} → {t}")
    return sorted(bad)


CHANGELOGS = (ROOT / "CHANGELOG.md", ROOT / "CHANGELOG.zh.md")
# 「一条一行」的量(CLAUDE.md 与 开发约定.md 第十二节同口径)。取值来自实测:合规条目落在
# 15-25 词 / 25-40 字,而 260904 之前的 Unreleased 五条是 89-127 词 / 126-158 字。
CHANGELOG_EN_WORDS, CHANGELOG_ZH_CHARS = 25, 40
_BLOCK_START = re.compile(r"^(#|\||>|-\s|\*\s|\d+\.\s|```)")


def _changelog_style(paths=None) -> tuple[list[str], list[str]]:
    """CHANGELOG 的两条机械约束(260904 立):条目长度、硬折行。

    **为什么要机械查**:规则本来就写在三处(CLAUDE.md、开发约定.md、CHANGELOG 自己的抬头),
    三处口径一致,照样没守住——因为 `CHANGELOG-history.md` 里躺着 251 条存量示范,中位 106 词、
    只有 7% 合规。写新条目的人(AI 尤其)看的是文件里的样子,不是文档里的规则,**示范压过规则**。
    这正是本脚本存在的理由那一句:需要人工记得的药方自己就是下一处腐化。

    **两条的范围不同,别统一**:
    - 长度只查未发布节。已发版那几节的正文 CI 已经抽去 GitHub Releases 了,事后改短会让仓库
      与已发布的说明分叉——那是另一种腐化,比长条目更坏。它们下次发版整节搬进 history。
    - 折行查整份文件(含已发版节):只动换行不动字,与已发布正文的**内容**不分叉。
    `CHANGELOG-history.md` 两条都不查:它的读者是"想翻旧账的人",长条目对那个读者不算病;
    存量作为坏示范的影响由 CLAUDE.md 那句「别照抄存量」拦,不靠重写 251 条。

    硬折行判据:一行既不是新块的开头(标题/列表/表格/引用/代码围栏),前一行又非空——
    那它只能是上一行被折下来的续行。**中文本来就不该折**(会坏渲染),英文这边则是全仓
    只有 CHANGELOG.md 折过,无 .editorconfig / prettier 支持,纯写作习惯,因此一并禁掉。
    """
    too_long, wrapped = [], []
    for path in (paths or CHANGELOGS):
        if not path.exists():
            continue
        zh = path.name.endswith(".zh.md")
        text = path.read_text(encoding="utf-8")
        fence, prev_blank, prev_quote = False, True, False
        for i, ln in enumerate(text.split("\n"), 1):
            if ln.strip().startswith("```"):
                fence = not fence
                prev_blank, prev_quote = False, False
                continue
            if fence:
                continue
            if not ln.strip():
                prev_blank, prev_quote = True, False
                continue
            is_quote = ln.lstrip().startswith(">")
            if not prev_blank and not _BLOCK_START.match(ln.lstrip()):
                wrapped.append(f"{path.name}:{i} 续行(上一行被硬折了):{ln.strip()[:40]}…")
            elif is_quote and prev_quote:
                wrapped.append(f"{path.name}:{i} 引用块被折成多行:{ln.strip()[:40]}…")
            prev_blank, prev_quote = False, is_quote

        # 未发布节的条目长度。两种语言各一个标题写法,找不到就是这份文件没有未发布节。
        head = "## 未发布" if zh else "## Unreleased"
        if head not in text:
            continue
        seg = text.split(head, 1)[1].split("\n## ", 1)[0]
        cap = CHANGELOG_ZH_CHARS if zh else CHANGELOG_EN_WORDS
        unit = "字" if zh else "词"
        for entry in [l[2:].strip() for l in seg.split("\n") if l.startswith("- ")]:
            n = len(re.findall(r"[一-鿿]", entry)) if zh else len(entry.split())
            if n > cap:
                too_long.append(f"{path.name} 一条 {n} {unit}(上限 {cap}):{entry[:36]}…")
    return too_long, wrapped


# 「量」在文档里的写法。抽成模块常量是为了让自测能反过来数命中数——**解析读空了,
# 漂移检查就静默变成永远通过**,而它长得和通过一模一样(本项目惯犯 ③)。
_CAP_PAT = re.compile(r"≤\s*(\d+)\s*词\s*/\s*≤\s*(\d+)\s*字")


def _changelog_cap_drift() -> list[str]:
    """文档里写的「≤N 词 / ≤N 字」必须与闸门常量一致——形状同 `IDX_SCHEMA` 漂移那条。

    规则的数字一旦在文档里手抄一份,就是下一处腐化(本项目在版本号上栽过,判据见第十二节)。
    这里**破例把本地 `CLAUDE.md` 也纳入**:模块顶部写着"CLAUDE.md 不进对账",那句管的是
    "说法"——过程记录允许留下当时的看法;而这两个数字不是说法,是闸门会照着挡发版的硬事实,
    而且 CLAUDE.md 恰恰是每个会话都被读到、最可能被照着执行的那一份。
    """
    pat = _CAP_PAT
    out = []
    for p in list(DOC_FILES) + [ROOT / "CLAUDE.md"]:
        if not p.exists():
            continue
        for w, c in pat.findall(p.read_text(encoding="utf-8")):
            if (int(w), int(c)) != (CHANGELOG_EN_WORDS, CHANGELOG_ZH_CHARS):
                out.append(f"{p.name} 写 ≤{w} 词 / ≤{c} 字，闸门是 "
                           f"≤{CHANGELOG_EN_WORDS} 词 / ≤{CHANGELOG_ZH_CHARS} 字")
    return out


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


_SPECS = ("build.spec", "build-mac.spec")


def _spec_facts() -> dict:
    """两份 PyInstaller spec 的 `datas` 源路径与显式 `hiddenimports`。

    两条检查，各防一个已经发生过的事故：

    1. **datas 源路径必须存在**。260808 把 `docs/AI_USAGE.md` 移进 `reference/` 时，两份 spec
       里的源路径是**靠人工 grep 发现的**——漏了的话打包会失败，或者更糟：产物少一份说明书，
       而 `/api/ai-guide` 找不到文件时是**静默回落**到最小速查的，没人会注意到。
    2. **两份 spec 不许分叉**。注释自己记着「260801 发现两个 spec 分叉」：mac spec 没跟上
       `brotli`，于是 macOS 产物对非流式响应（安全分类器正是非流式）的 body/usage 整段丢失。
       平台后端不同是合理的（EdgeChromium vs WebKit），所以只对账**显式写死的那部分**。
    """
    out = {}
    for name in _SPECS:
        t = _read(ROOT / name)
        m = re.search(r"datas\s*=\s*\[(.*?)\n\]", t, re.S)
        datas = re.findall(r"\(\s*'([^']+)'\s*,", m.group(1)) if m else []
        h = re.search(r"hiddenimports\s*=[^\n]*?\+\s*\[([^\]]*)\]", t)
        hidden = re.findall(r"'([A-Za-z_][A-Za-z_0-9]*)'", h.group(1)) if h else []
        # 3. **两份 spec 都必须刻版本资源**（260808）。产物在程序外能不能看出版本，
        #    全靠 `tools/version_res.py`；哪份 spec 掉了这行，那个平台的产物就退回
        #    "属性页一片空白"。两个平台各取一半（Windows 的 VERSIONINFO / macOS 的
        #    Info.plist），所以只对账"有没有用这个模块"，不对账具体调用了哪个函数。
        out[name] = {"datas": sorted(datas), "hidden": sorted(hidden),
                     "version_res": "from version_res import" in t}
    return out


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
# 错误码只认 JSON 字面量形（`"error_code": "a|b|c"`）。散文里反引号包着的 snake_case 太多
# （`delta` / `done` 这些 SSE 事件名就同句出现过），宽匹配必然误报——**宁可少查一点，
# 不可制造误报**，与上面 kind 那条同一条铁律。
_ERRCODE_JSON = re.compile(r'"error_code":\s*"([a-z_0-9|]+)"')


def _doc_enum_claims(text: str) -> dict[str, set[str]]:
    """文档**以枚举语法明确列出**的值，按三类分开。"""
    kinds: set[str] = set()
    for line in _KIND_ANCHOR.findall(text):
        kinds |= set(re.findall(r"`([a-z][a-z_0-9]{2,})`", line))
    errk: set[str] = set(_ERRK_JSON.findall(text))
    for v in _PIPE_JSON.findall(text):
        errk |= set(v.split("|"))
    codes: set[str] = set(_SEVERITY_ROW.findall(text)) | set(_CODE_JSON.findall(text))
    ecodes: set[str] = set()
    for v in _ERRCODE_JSON.findall(text):
        ecodes |= {x for x in v.split("|") if x}
    return {"kind": kinds, "err_kind": errk, "doctor_code": codes, "error_code": ecodes}


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
    #
    # 「不是本服务的端点引用」有**两层**，别只修撞见的那层（惯犯 ⑦）：上面那个先行断言管的是
    # 「长得像 URL 的」，EXTERNAL_ENDPOINTS 管的是「长得完全像本项目端点、只是主语不是本项目」
    # ——同类工具构建手册的主题就是给别的 agent 工具做分析器，写到它们的端点是常态。
    mentioned = set(re.findall(r"(?<![:\w])`?(/api/[a-zA-Z0-9_/<>-]+)", joined))
    ghost_routes = sorted(
        m for m in mentioned
        if m not in EXTERNAL_ENDPOINTS
        and re.sub(r"<[^>]+>", "<id>", m.rstrip("/?")) not in routes
        and not m.endswith("<id>")
        and not any(r.startswith(m.rstrip("/")) for r in routes))
    # 白名单防腐：万一本项目将来真加了同名端点，这条豁免会让对账对它永远闭嘴。
    # 命中即报硬差异，提示删掉该条——**检查本身也要被检查**，代价一行。
    stale_external = sorted(EXTERNAL_ENDPOINTS & set(routes))

    # 2. CLI 子命令
    # 命中形式：`list --date …`（表格里的用法行）/ `list` / `cli.py list …`
    undocumented_cmds = sorted(c for c in cmds
                               if not re.search(rf"`{c}[ `]|cli\.py.{{0,40}}\b{c}\b", joined))

    # 3. 文档提到的仓库文件是否存在
    missing_paths = []
    _cands = []
    for name, text in doc_text.items():
        for m in re.finditer(r"`((?:src|tools|docs|handbook)/[A-Za-z0-9_./-]+\.(?:py|md|html))`", text):
            if not (ROOT / m.group(1)).exists():
                _cands.append({"doc": name, "path": m.group(1)})
    # 生成物（gitignore 的）不算断链：仓库里本来就没有，文档提它是在讲构建机制
    _ignored = _git_ignored(sorted({c["path"] for c in _cands}))
    missing_paths = [c for c in _cands if c["path"] not in _ignored]
    dead_links = _dead_links()

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
    ecodes = _error_codes()
    claims = _doc_enum_claims(joined)
    all_code_enums = kinds | err_kinds | dcodes | _lane_kinds() | ecodes

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
    # `error_code` **只报幽灵、不报未文档化**：代码里有 60+ 个错误码，绝大多数是内部分支，
    # 全列出来是一张没人会看的清单——软差异存在的意义是"提示人做判断"，一张 50 行的
    # 清单提示不了任何判断，只会把真正该看的两三行淹掉。
    enums.append({"enum": "error_code",
                  "ghost": sorted(claims["error_code"] - all_code_enums),
                  "undocumented": []})

    # 8. 端点标题的机械事实（260904 批二）：**标题是这份文档的索引**，也是唯一一处
    #    "每个端点恰好一节"的结构承诺。原有对账只查路径存不存在——写两遍照样算"提到了",
    #    批一那份分叉复制品就是这么长出来的；方法/查询参数写错更是一概看不见。
    rfacts = _route_facts()
    heads = _contract_heads(contract)
    seen_heads: dict[tuple, int] = {}
    ghost_methods, ghost_query = [], []
    documented_methods: dict[str, set] = {}
    for h in heads:
        for meth in h["methods"]:
            seen_heads[(meth, h["path"])] = seen_heads.get((meth, h["path"]), 0) + 1
        documented_methods.setdefault(h["path"], set()).update(h["methods"])
        f = rfacts.get(h["path"])
        if not f:
            continue    # 路径本身不存在 → 幽灵端点那条已经报了，不重复报同一件事
        real = f["methods"] - {"HEAD", "OPTIONS"}   # Flask 隐式补的，文档不写是对的
        if h["methods"] - real:
            ghost_methods.append(f"{h['raw']} → 代码只有 {'/'.join(sorted(real))}")
        if h["args"] - f["args"]:
            ghost_query.append(f"{h['raw']} → 代码不读 {', '.join(sorted(h['args'] - f['args']))}")
    dup_heads = [f"{m} {p}（{n} 节）" for (m, p), n in sorted(seen_heads.items()) if n > 1]
    # 软：代码有、标题没写的方法。GET/POST 分两节写是合法的（`/api/config` 就是），
    # 所以按 (方法, 路径) 判重、按路径合并方法集——两个口径缺一不可。
    undocumented_methods = []
    for p, f in sorted(rfacts.items()):
        if not p.startswith("/api") or p not in documented_methods:
            continue
        miss = (f["methods"] - {"HEAD", "OPTIONS"}) - documented_methods[p]
        if miss:
            undocumented_methods.append(f"{p} 少写 {'/'.join(sorted(miss))}")

    # 7. PyInstaller spec：打包源路径是否存在 + 两份 spec 是否分叉
    specs = _spec_facts()
    spec_missing = sorted({f"{name} → {d}" for name, f in specs.items()
                           for d in f["datas"] if not (ROOT / d).exists()})
    a, b = specs.get("build.spec", {}), specs.get("build-mac.spec", {})
    spec_divergence = []
    if a and b:
        if a["datas"] != b["datas"]:
            spec_divergence.append(
                f"datas 不一致：build.spec={a['datas']} / build-mac.spec={b['datas']}")
        if a["hidden"] != b["hidden"]:
            spec_divergence.append(
                f"显式 hiddenimports 不一致：build.spec={a['hidden']} / build-mac.spec={b['hidden']}")
        for name, f in ((n, specs[n]) for n in _SPECS if n in specs):
            if not f.get("version_res"):
                spec_divergence.append(
                    f"{name} 没有引入 tools/version_res.py —— 该平台的产物在程序外看不到版本号")

    changelog_long, changelog_wrapped = _changelog_style()
    changelog_cap = _changelog_cap_drift()

    return {
        "routes": len(routes), "cli_commands": len(cmds), "idx_schema": schema,
        "changelog_too_long": changelog_long,
        "changelog_hard_wrapped": changelog_wrapped,
        "changelog_cap_drift": changelog_cap,
        "enums": enums,
        "spec_missing_datas": spec_missing,
        "spec_divergence": spec_divergence,
        "undocumented_routes": undocumented,
        "duplicate_endpoint_sections": dup_heads,
        "ghost_methods": ghost_methods,
        "ghost_query_args": ghost_query,
        "undocumented_methods": undocumented_methods,
        "ghost_routes": ghost_routes,
        "stale_external_endpoints": stale_external,
        "undocumented_cli": undocumented_cmds,
        "missing_paths": missing_paths,
        "dead_links": dead_links,
        "idx_schema_drift": schema_drift,
        "missing_selftest_files": sorted(set(missing_selftests)),
        "tokens": _theme_tokens(),
        "note": ("硬差异（ghost_routes / dead_links / duplicate_endpoint_sections / ghost_methods / "
                 "ghost_query_args / missing_paths / idx_schema_drift / "
                 "missing_selftest_files / changelog_too_long / changelog_hard_wrapped / "
                 "tokens.theme_gaps / tokens.shared_leaked / "
                 "tokens.unresolved_refs）"
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
            ("点下去到不了的相对链接", r.get("dead_links", [])),
            ("IDX_SCHEMA 数值不一致", [f"{x['doc']} 写 {x['says']}，代码 {x['code']}"
                                       for x in r["idx_schema_drift"]]),
            ("自测清单里不存在的文件", r["missing_selftest_files"]),
            ("某套外观缺取值的 token（会变成隐形字）", [f"{g['theme']} 缺 {', '.join(g['missing'])}"
                                                        for g in tk["theme_gaps"]]),
            ("共用块与深色块重复定义的 token", tk["shared_leaked"]),
            # 归硬类的理由与缺取值同源：两者都没有任何运行时反馈。缺取值是"某套外观变深色块"，
            # 这个是"整条声明作废、颜色继承父级"——后者更隐蔽，因为三套外观一起失效。
            ("引用了但没定义、也没写 fallback 的 token（整条声明作废）", tk["unresolved_refs"]),
            ("spec 要打包的文件不存在", r.get("spec_missing_datas", [])),
            ("两份 spec 分叉了", r.get("spec_divergence", [])),
            # 白名单过期：本项目真加了同名端点，那条外部豁免必须删，否则它会让对账对这个
            # 端点永远闭嘴。归硬类是因为后果与幽灵端点同源——判据带着一条静默的例外在跑。
            ("已成真路由、该从 EXTERNAL_ENDPOINTS 删掉的豁免",
             r.get("stale_external_endpoints", []))]
    # 归硬类的理由与别的硬差异同源：它们都是"文档说了一件不成立的事"——CHANGELOG 抬头、
    # CLAUDE.md、开发约定 三处都写着「一条一行」，条目却是段落，那三句话就是假的。
    # 而且这条不像内部端点那样存在"有意不写"的合理情形，不会逼出 `|| true`。
    hard += [("CHANGELOG 条目超出「一条一行」的量", r.get("changelog_too_long", [])),
             ("CHANGELOG 里的硬折行", r.get("changelog_hard_wrapped", [])),
             ("文档写的 CHANGELOG 量与闸门常量不一致", r.get("changelog_cap_drift", []))]
    hard += [("同一端点在契约里写了不止一节（分叉的开始）", r.get("duplicate_endpoint_sections", [])),
             ("端点标题声明了代码没有的方法", r.get("ghost_methods", [])),
             ("端点标题声明了代码不读的查询参数", r.get("ghost_query_args", []))]
    hard += [(f"文档列了但代码没有的 {e['enum']} 值", e["ghost"])
             for e in r.get("enums", [])]
    soft = [("文档里没提到的端点", r["undocumented_routes"]),
            ("端点标题没写全的方法", r.get("undocumented_methods", [])),
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

    # 第二个反例（260826）：把一处引用改成没人定义的名字，确认"隐形失效"这一类真会响。
    # 复刻的是分析视图那 21 处空转的形状——它当年没被任何检查抓到，正是因为这一类不存在。
    broken2 = real.replace("color:var(--paper-text);", "color:var(--paper-txt);", 1)
    assert broken2 != real, "反例没造出来：--paper-text 的引用点变了，改这里"
    try:
        globals()["SRC"] = tmp.parent.parent
        (tmp.parent.parent / "templates" / "index.html").write_text(broken2, encoding="utf-8")
        unresolved = _theme_tokens()["unresolved_refs"]
    finally:
        globals()["SRC"] = orig
        (tmp.parent.parent / "templates" / "index.html").write_text(real, encoding="utf-8")
    ok2 = "--paper-txt" in unresolved
    print("[无定义引用自测]", "PASS 隐形失效能被检出" if ok2 else "FAIL 隐形失效没被检出")
    ok = ok and ok2

    # 门本身也要被验证：分类错了（把硬差异归进软类）闸门就形同虚设，而它照样打印
    # 「对账通过」——正是本项目惯犯 ③「静默失效」的形状，且这次犯在守卫自己身上。
    base = {"routes": 0, "cli_commands": 0, "idx_schema": 1,
            "undocumented_routes": [], "ghost_routes": [], "undocumented_cli": [],
            "missing_paths": [], "idx_schema_drift": [], "missing_selftest_files": [],
            "stale_external_endpoints": [],
            "duplicate_endpoint_sections": [], "ghost_methods": [], "ghost_query_args": [],
            "dead_links": [],
            "undocumented_methods": [],
            "tokens": {"counts": {}, "theme_gaps": [], "shared_leaked": [], "dead_tokens": [],
                       "unresolved_refs": []}}

    # 外部端点白名单的两种腐化，各查一次（260809）。豁免是判据上开的口子，开了就得看住：
    #   ① 死条目——文档早就不提它了，白名单却还留着，下次有人看到会以为这个豁免仍有意义；
    #   ② 过期条目——本项目真加了同名端点，豁免会让对账对它永远闭嘴（下面 n_hard 那条断言）。
    _docs_joined = "\n".join(_read(p) for p in DOC_FILES)
    dead_ext = sorted(e for e in EXTERNAL_ENDPOINTS if e not in _docs_joined)
    print("[外部端点白名单]",
          "PASS 每条都仍被文档引用" if not dead_ext else f"FAIL 死条目（该删）{dead_ext}")
    ok = ok and not dead_ext

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
        ("外部端点豁免过期挡", n_hard(stale_external_endpoints=["/api/anthropic/v1/messages"]) == 1),
        ("无定义引用挡",
         n_hard(tokens={**base["tokens"], "unresolved_refs": ["--nope"]}) == 1),
        ("断掉的相对链接挡", n_hard(dead_links=["docs/x.md → nope.md"]) == 1),
        ("重复端点小节挡", n_hard(duplicate_endpoint_sections=["GET /api/x（2 节）"]) == 1),
        ("幽灵方法挡", n_hard(ghost_methods=["POST /api/x → 代码只有 GET"]) == 1),
        ("幽灵查询参数挡", n_hard(ghost_query_args=["GET /api/x?zz= → 代码不读 zz"]) == 1),
        ("方法没写全不挡（软）", n_hard(undocumented_methods=["/api/x 少写 POST"]) == 0),
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
    # 端点标题的机械事实（260904 批二）：提取器要真读到东西，三条硬检查各造一个反例。
    # 读空了检查就静默变成永远通过——本项目惯犯 ③ 犯在守卫自己身上的形状。
    _rf = _route_facts()
    _fake_doc = ("### `GET|POST /api/config` — 甲\n\n"
                 "### `GET /api/config` — 乙\n\n"
                 "### `GET /api/dag?date=&nope=` — 丙\n")
    _fh = _contract_heads(_fake_doc)
    _seen: dict = {}
    for _h in _fh:
        for _m in _h["methods"]:
            _seen[(_m, _h["path"])] = _seen.get((_m, _h["path"]), 0) + 1
    ecases += [
        ("路由方法可提取", _rf.get("/api/config", {}).get("methods") == {"GET", "POST"}),
        ("查询参数可提取", "date" in _rf.get("/api/dag", {}).get("args", set())),
        ("标题解析出方法与路径", {h["path"] for h in _fh} == {"/api/config", "/api/dag"}),
        ("重复小节能算出来", _seen[("GET", "/api/config")] == 2),
        ("标题里的查询参数解析得到",
         next(h["args"] for h in _fh if h["path"] == "/api/dag") == {"date", "nope"}),
        ("幽灵查询参数能检出",
         bool(next(h["args"] for h in _fh if h["path"] == "/api/dag") - _rf["/api/dag"]["args"])),
        # 回归：真实契约必须零幽灵——260904 加这条检查时它抓到过一处真错
        #（`GET|POST /semantic` 的 POST 其实在 `/trajectory` 上），修完才允许留在基线里。
        ("真实契约零幽灵方法与参数",
         not audit()["ghost_methods"] and not audit()["ghost_query_args"]),
        ("真实契约每个端点只占一节", not audit()["duplicate_endpoint_sections"]),
        ("error_code 真源可提取", {"not_capture", "bad_json"} <= _error_codes()),
        # 链接检查：解析器要真读到链接（读空了就静默变成永远通过），
        # 且仓库外的 GitHub 相对写法不许被误报成断链。
        ("markdown 链接解析得到", len(_MD_LINK.findall(_read(DOCS / "README.md"))) > 5),
        ("仓库外的相对写法不算断链",
         not any("releases" in x for x in _dead_links())),
        ("真实文档零断链", not _dead_links()),
    ]
    # spec 对账：提取器要真读到东西（读空了会让检查静默变成永远通过），
    # 两份 spec 的一致性是 260801 真事故（mac spec 没跟上 brotli）的防线。
    sf = _spec_facts()
    a, b = sf.get("build.spec", {}), sf.get("build-mac.spec", {})
    ecases += [
        ("两份 spec 都提取到 datas", bool(a.get("datas")) and bool(b.get("datas"))),
        ("spec 的 datas 源路径都存在",
         all((ROOT / d).exists() for f in sf.values() for d in f["datas"])),
        ("两份 spec 的 datas 一致", a.get("datas") == b.get("datas")),
        ("两份 spec 的显式 hiddenimports 一致", a.get("hidden") == b.get("hidden")),
        ("说明书确实在打包清单里", any("AI_USAGE" in d for d in a.get("datas", []))),
        ("两份 spec 都刻了版本资源", a.get("version_res") and b.get("version_res")),
        # 反向断言：掉了版本资源必须被判成硬差异。检查本身不被验证，就是下一个
        # 「守卫函数存在但调用点缺失」。
        ("spec 掉了版本资源会挡发版",
         n_hard(spec_divergence=["build-mac.spec 没有引入 tools/version_res.py"]) == 1),
    ]
    # CHANGELOG 两条量(260904):反例造不出来就说明解析读空了,检查会静默变成永远通过。
    import tempfile as _tf
    _cd = pathlib.Path(_tf.mkdtemp())
    _NL = chr(10)
    _good_en = "## Unreleased" + _NL * 2 + "- Retries now merge into the turn they retry." + _NL
    _long_en = "## Unreleased" + _NL * 2 + "- " + "word " * 40 + _NL
    _wrap_en = "## Unreleased" + _NL * 2 + "- A line that got" + _NL + "  hard wrapped here." + _NL
    _quote_en = "> first quoted line" + _NL + "> folded continuation" + _NL
    _long_zh = "## 未发布" + _NL * 2 + "- " + "字" * 60 + _NL
    _rel_en = "## v0.1.0" + _NL * 2 + "- " + "word " * 40 + _NL

    def _w(name, text):
        f = _cd / name
        f.write_text(text, encoding="utf-8")
        return [f]

    _t_long = _changelog_style(_w("a.md", _long_en))
    _t_zh = _changelog_style(_w("e.zh.md", _long_zh))
    _t_wrap = _changelog_style(_w("b.md", _wrap_en))
    _t_quote = _changelog_style(_w("c.md", _quote_en))
    _t_good = _changelog_style(_w("d.md", _good_en))
    ecases += [
        ("超长英文条目能检出", len(_t_long[0]) == 1),
        ("超长中文条目按汉字数检出", len(_t_zh[0]) == 1),
        ("续行(硬折行)能检出", len(_t_wrap[1]) == 1),
        ("被折成多行的引用块能检出", len(_t_quote[1]) == 1),
        # 反向:合规条目不许被报,否则闸门天天红,下一步就是有人加 `|| true`
        ("合规条目不误报", _t_good == ([], [])),
        # 已发版节不查长度:正文 CI 已抽去 GitHub Releases,事后改短会与已发布说明分叉
        ("已发版节的长条目不查长度", _changelog_style(_w("f.md", _rel_en))[0] == []),
        ("真实 CHANGELOG 两条都干净", _changelog_style() == ([], [])),
        ("CHANGELOG 超长挡发版", n_hard(changelog_too_long=["x.md 一条 99 词"]) == 1),
        ("CHANGELOG 硬折行挡发版", n_hard(changelog_hard_wrapped=["x.md:9 续行"]) == 1),
        ("量的数字漂移挡发版", n_hard(changelog_cap_drift=["x.md 写 ≤9 词"]) == 1),
        ("真实文档写的量与闸门一致", not _changelog_cap_drift()),
        # 正向:模式必须真的命中(开发约定.md 与 CLAUDE.md 各一处)。只断言"没有漂移"
        # 等于奖励一个什么都匹配不到的正则。
        ("量的写法在文档里真被匹配到",
         sum(1 for _p in list(DOC_FILES) + [ROOT / "CLAUDE.md"]
             if _p.exists() and _CAP_PAT.search(_p.read_text(encoding="utf-8"))) >= 2),
    ]
    for name, passed in ecases:
        print("[枚举对账]", ("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_selftest())
    main()
