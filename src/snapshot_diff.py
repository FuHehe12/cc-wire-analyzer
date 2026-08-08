"""精确对比：两个快照之间逐字符级的差异，且**不可见的差异必须看得见**。

## 为什么不能用通用 diff

提示词的真实差异经常是肉眼不可见的。已知的实例：CC 针对中国用户的字符水印，把日期里的
`-` 换成 `/`、把撇号换成 4 种同形变体之一。普通 diff 工具把这些渲染成「两行看起来完全
一样却被标成不同」，读的人只会以为工具坏了。

对策是**先揭示、再比对**（`reveal()` → `difflib`）：零宽字符、NBSP、全角空格、CR、
行尾空格在进入比对之前就被换成可见记号。于是
  - 不可见差异 → 变成可见的字面差异，diff 自然标出来；
  - 两侧同样的不可见字符 → 揭示后仍然相同，不会凭空造出差异。
同形异码字符（撇号/连字符/引号/全角标点）不改写——它们本来就可见，改写会造成满屏噪声；
改为在行内字符级差异上**打标**（`hg` 字段），让界面能把"这俩看着一样但不是同一个码位"
单独渲染出来。

## 判等用原文，展示用揭示后的文本

`equal` / `norm_equal` 一律基于原文计算（揭示只是显示层的事）。`norm_equal` 用
`snapshot_store.normalize_text` 抹掉日期/时间/UUID/长 hex —— 回答日常最想问的那个问题：
「除了每天必然变的那些，到底有没有变？」
"""
from __future__ import annotations

import difflib
import json
import re

import snapshot_store as SS

# 一次 diff 的产出上限。提示词可达十万字符，行数上万；不设限时 API 会返回几十 MB JSON，
# 前端渲染直接卡死。超限截断并**在结果里说明**（惯犯 bug ③：截断了必须说）。
MAX_LINES = 4000
MAX_INLINE_LINE = 2000      # 单行超这个长度不做行内字符级 diff（O(n²) 会卡住）


# ===== 揭示不可见字符 =====

# 每一项：码位 → 可见记号。记号用 ⟨⟩ 包住，正常文本里几乎不会出现，
# 不容易与原文内容混淆。
# **一律用 \u 转义写码位，不写字面字符**：这些字符在编辑器里不可见，字面写法会被某些
# 工具静默改掉或吃掉，而这份表恰恰是用来抓这类字符的——表本身被污染就彻底失效了。
_INVISIBLE = {
    "\u200b": "\u27e8ZWSP\u27e9",        # 零宽空格
    "\u200c": "\u27e8ZWNJ\u27e9",        # 零宽非连接符
    "\u200d": "\u27e8ZWJ\u27e9",         # 零宽连接符
    "\u2060": "\u27e8WJ\u27e9",          # word joiner
    "\ufeff": "\u27e8BOM\u27e9",         # 字节序标记 / 零宽不换行空格
    "\u00a0": "\u27e8NBSP\u27e9",        # 不换行空格
    "\u3000": "\u27e8全角空格\u27e9",
    "\u180e": "\u27e8MVS\u27e9",         # 蒙古文元音分隔符
    "\u00ad": "\u27e8SHY\u27e9",         # 软连字符：显示时不可见，却是实实在在一个字符
    "\u2028": "\u27e8LS\u27e9",          # 行分隔符
    "\u2029": "\u27e8PS\u27e9",          # 段分隔符
    "\r": "\u27e8CR\u27e9",              # CRLF 与 LF 之差
    "\x00": "\u27e8NUL\u27e9",
}

_TRAILING_WS_RE = re.compile(r"([ \t]+)$")


def reveal(text: str) -> str:
    """把不可见字符换成可见记号；行尾空白也标出来（行尾多一个空格是典型的看不见的差异）。"""
    out = text
    for ch, mark in _INVISIBLE.items():
        if ch in out:
            out = out.replace(ch, mark)
    lines = out.split("\n")
    for i, ln in enumerate(lines):
        m = _TRAILING_WS_RE.search(ln)
        if m:
            ws = m.group(1)
            tag = "".join("⟨TAB⟩" if c == "\t" else "⟨SP⟩" for c in ws)
            lines[i] = ln[:m.start()] + tag
    return "\n".join(lines)


def invisible_census(text: str) -> dict:
    """文本里各类不可见字符的计数（摆在 diff 顶部，让人知道这份文本本身"有猫腻"）。"""
    out: dict[str, int] = {}
    for ch, mark in _INVISIBLE.items():
        n = text.count(ch)
        if n:
            out[mark.strip("⟨⟩")] = n
    trail = sum(1 for ln in text.split("\n") if _TRAILING_WS_RE.search(ln))
    if trail:
        out["行尾空白"] = trail
    return out


# ===== 同形异码 =====

# 每组内的字符**看起来几乎一样、或是同一标点的全/半角两态，码位却不同**。
# CC 的中国用户水印就利用了撇号这一组。不改写文本（它们本来可见，改写会满屏噪声），
# 只在行内字符差异上打标。
#
# **每组第一个字符是基准**（ASCII / 半角的那个），`homoglyph_census` 跳过它——见该函数注释。
#
# 分组必须**逐对精确**，不能把"一堆中文标点"塞进同一组：若 `:` 与 `,` 同组，
# 一次 `:` → `,` 的真实改动就会被打上"同形异码"标签，而那是个**错误的断言**——
# 断言错了比不断言更坏，读的人会以为自己发现了隐蔽水印，其实只是正常编辑。
_HOMOGLYPH_GROUPS = [
    ("撇号", "'\u2018\u2019\u02b9\u02bc\u2032\u201b`\u00b4"),
    ("连字符", "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d"),
    ("双引号", "\"\u201c\u201d\u2033\u301d\u301e"),
    ("空格", "\u0020\u00a0\u2007\u202f\u3000"),
    ("冒号", ":\uff1a"),
    ("逗号", ",\uff0c"),
    ("句点", ".\u3002"),
    ("分号", ";\uff1b"),
    ("叹号", "!\uff01"),
    ("问号", "?\uff1f"),
    ("左括号", "(\uff08"),
    ("右括号", ")\uff09"),
    ("斜杠", "/\u2044\uff0f"),
]
_HG_OF: dict[str, str] = {}
for _name, _chars in _HOMOGLYPH_GROUPS:
    for _c in _chars:
        _HG_OF[_c] = _name


def homoglyph_census(a: str, b: str) -> dict:
    """两侧的**非基准**同形异码字符分布差异。

    每组第一个字符是基准（ASCII 撇号 / ASCII 连字符 / 半角空格 …），**基准不参与比较**。
    否则每一次正常的内容增删都会改变半角空格的数量，于是"同形异码"这一栏对每个真实改动
    都报一条——一个恒亮的告警等于没有告警。真正值得报的是非基准成员出现或数量变化：
    正文里冒出 U+2019 撇号、U+00A0 空格、全角冒号，那才是可疑的。

    跨组替换（如日期里 `-` → `/`）不归这里管——那两个字符本来就看得出区别，
    而且行内字符级 diff 已经精确指出了位置。
    """
    out: dict[str, dict] = {}
    for name, chars in _HOMOGLYPH_GROUPS:
        rest = chars[1:]            # 跳过基准字符
        ca = {c: a.count(c) for c in rest if a.count(c)}
        cb = {c: b.count(c) for c in rest if b.count(c)}
        if ca == cb:
            continue
        # **只列出计数真的变了的码位**。整组一起摆出来的话，两侧都有 42 个反引号这种
        # 「没变的成员」会和真正的差异（多了 4 个 U+2019）混在一起，读者得自己找不同——
        # 而这一栏存在的全部意义就是「差异一眼可见」。
        keys = {c for c in set(ca) | set(cb) if ca.get(c, 0) != cb.get(c, 0)}
        out[name] = {
            "a": {f"U+{ord(c):04X}": ca[c] for c in sorted(keys) if c in ca},
            "b": {f"U+{ord(c):04X}": cb[c] for c in sorted(keys) if c in cb},
        }
    return out


# ===== 行内字符级 diff =====

def _inline_ops(a: str, b: str) -> list[dict]:
    """两行之间的字符级差异。返回 [{op, a, b, hg}]。

    op: equal / insert / delete / replace
    hg: 该 replace 是同形异码替换时，给出组名（"撇号"等）——**水印就长这样**：
        一整行只有一个字符从 U+0027 变成 U+2019，肉眼完全看不出来。
    """
    if len(a) > MAX_INLINE_LINE or len(b) > MAX_INLINE_LINE:
        return [{"op": "replace", "a": a, "b": b, "hg": "", "skipped": True}]
    ops: list[dict] = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        sa, sb = a[i1:i2], b[j1:j2]
        hg = ""
        if tag == "replace" and len(sa) == len(sb):
            # 逐字符看是不是同形异码替换（长度相同才可能是"换了个长得像的"）
            names = {_HG_OF.get(x) for x, y in zip(sa, sb)
                     if x != y and _HG_OF.get(x) and _HG_OF.get(x) == _HG_OF.get(y)}
            names.discard(None)
            if names and len(names) == 1:
                hg = names.pop()
        ops.append({"op": tag, "a": sa, "b": sb, "hg": hg})
    return ops


# ===== 主 diff =====

def diff_text(a_raw: str, b_raw: str, *, context: int = 3) -> dict:
    """两段文本的结构化差异。**先揭示后比对**（见模块 docstring）。

    context = 相同行的保留上下文行数；-1 表示全量保留（不折叠）。
    """
    equal = a_raw == b_raw
    na, _ = SS.normalize_text(a_raw)
    nb, _ = SS.normalize_text(b_raw)
    norm_equal = na == nb

    a, b = reveal(a_raw), reveal(b_raw)
    la, lb = a.split("\n"), b.split("\n")
    truncated = False
    if len(la) > MAX_LINES or len(lb) > MAX_LINES:
        la, lb = la[:MAX_LINES], lb[:MAX_LINES]
        truncated = True

    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    hunks: list[dict] = []
    counts = {"same": 0, "added": 0, "removed": 0, "changed": 0}

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            counts["same"] += i2 - i1
            n = i2 - i1
            if context >= 0 and n > context * 2:
                # 折叠中间的相同段，只留两端上下文
                head = [{"side": "both", "na": i1 + k + 1, "nb": j1 + k + 1, "text": la[i1 + k]}
                        for k in range(context)]
                tail = [{"side": "both", "na": i2 - context + k + 1, "nb": j2 - context + k + 1,
                         "text": la[i2 - context + k]} for k in range(context)]
                hunks.append({"tag": "equal", "lines": head + tail,
                              "folded": n - context * 2})
            else:
                hunks.append({"tag": "equal", "folded": 0, "lines": [
                    {"side": "both", "na": i1 + k + 1, "nb": j1 + k + 1, "text": la[i1 + k]}
                    for k in range(n)]})
            continue

        lines: list[dict] = []
        if tag in ("delete", "replace"):
            for k in range(i1, i2):
                lines.append({"side": "a", "na": k + 1, "text": la[k]})
        if tag in ("insert", "replace"):
            for k in range(j1, j2):
                lines.append({"side": "b", "nb": k + 1, "text": lb[k]})
        if tag == "replace":
            counts["changed"] += max(i2 - i1, j2 - j1)
            # 一一对应的行对做字符级 diff（行数不等时只对齐能对上的部分）
            for k in range(min(i2 - i1, j2 - j1)):
                ops = _inline_ops(la[i1 + k], lb[j1 + k])
                lines[k]["inline"] = ops
                lines[(i2 - i1) + k]["inline"] = ops
        elif tag == "delete":
            counts["removed"] += i2 - i1
        else:
            counts["added"] += j2 - j1
        hunks.append({"tag": tag, "lines": lines, "folded": 0})

    return {
        "equal": equal,
        # 「除了日期这类每次必变的部分，其实没变」——日常最想问的那个问题
        "norm_equal": norm_equal,
        "counts": counts,
        "chars": {"a": len(a_raw), "b": len(b_raw)},
        "lines": {"a": a_raw.count("\n") + 1, "b": b_raw.count("\n") + 1},
        "invisible": {"a": invisible_census(a_raw), "b": invisible_census(b_raw)},
        "homoglyphs": homoglyph_census(a_raw, b_raw),
        "truncated": truncated,
        "max_lines": MAX_LINES if truncated else None,
        "hunks": hunks,
    }


# ===== 可比性护栏 =====

# 这些 ctx 字段不同，意味着两个快照**本来就不是同一类东西**，差异大部分来自类型本身
# 而非"提示词变了"。**提示但绝不阻止**——用户完全可能就是想看两类之间差在哪。
_GUARD_FIELDS = [
    ("wire_kind", "请求类型不同（主线 / 子代理 / 标题 / 安全审查……）"),
    ("agent_fp", "提示词身份指纹不同——这两段本就是不同的提示词，不是同一段的两个版本"),
    ("model", "模型不同"),
    ("upstream", "上游供应商不同"),
    ("harness", "CC 版本不同"),
]


def compare_meta(a: dict, b: dict) -> dict:
    """两个提示词快照的元数据对照：哪些条件不同 + 可比性提醒。

    这一组恰恰常常就是「提示词为什么变了」的答案本身：换了供应商、换了 CC 版本、
    一个是主线一个是子代理。所以界面把它并排摆在 diff 上方，差异项高亮。
    """
    ca, cb = (a.get("ctx") or {}), (b.get("ctx") or {})
    diffs: list[dict] = []
    for k in ("model", "upstream", "harness", "entrypoint", "wire_kind",
              "is_subagent", "agent_fp", "agent_id", "session_id"):
        va, vb = ca.get(k), cb.get(k)
        if va != vb:
            diffs.append({"field": k, "a": va, "b": vb})
    ea, eb = (ca.get("env") or {}), (cb.get("env") or {})
    for k in ("workspace", "platform", "git_repo"):
        if ea.get(k) != eb.get(k):
            diffs.append({"field": f"env.{k}", "a": ea.get(k), "b": eb.get(k)})
    if sorted(ca.get("beta") or []) != sorted(cb.get("beta") or []):
        diffs.append({"field": "beta", "a": ca.get("beta") or [], "b": cb.get("beta") or []})

    warns = [{"field": f, "why": why} for f, why in _GUARD_FIELDS
             if ca.get(f) != cb.get(f) and (ca.get(f) or cb.get(f))]

    oa, ob = (a.get("origin") or {}), (b.get("origin") or {})
    origin_diff = []
    for k in ("where", "role", "kind_hint", "cache_control", "sys_blocks", "block_shape"):
        if oa.get(k) != ob.get(k):
            origin_diff.append({"field": k, "a": oa.get(k), "b": ob.get(k)})
    return {"ctx_diff": diffs, "origin_diff": origin_diff, "warnings": warns}


# ===== 录制快照的对比面 =====

# 录制快照没有单一"文本"，得先选一个面。三个面各回答一个问题。
FACES = ("system", "tools", "messages")


def face_text(record: dict, face: str) -> str:
    """把一条 record 的某个面拍平成可比对的文本。

      system   —— 系统提示词全部块（含块序号与字符数表头，块被拆合时表头先变）
      tools    —— 工具清单（名称 + 描述 + 参数 schema），按名称排序后拼接：
                  **排序是必须的**，上游返回顺序不稳定，不排序会把顺序抖动当成差异
      messages —— 对话历史拍平（角色 + 块类型 + 正文）。这一面是**上下文腐烂的观测口**：
                  同一条对话的两个时刻，早期历史有没有被改写、截断、丢弃，一比就现形
    """
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    if face == "system":
        blocks = SS._system_block_texts(body)
        parts = []
        for i, t in enumerate(blocks):
            parts.append(f"───── system[{i}]  {len(t)} chars ─────\n{t}")
        return "\n\n".join(parts)
    if face == "tools":
        tools = body.get("tools") or []
        parts = []
        for t in sorted(tools, key=lambda x: (x.get("name") or "") if isinstance(x, dict) else ""):
            if not isinstance(t, dict):
                continue
            parts.append(f"───── tool: {t.get('name') or ''} ─────\n"
                         f"{t.get('description') or ''}\n"
                         f"input_schema: {json.dumps(t.get('input_schema') or {}, ensure_ascii=False, sort_keys=True, indent=1)}")
        return "\n\n".join(parts)
    if face == "messages":
        msgs = body.get("messages") or []
        parts = []
        for i, m in enumerate(msgs):
            role = m.get("role") or ""
            c = m.get("content")
            if isinstance(c, str):
                parts.append(f"───── messages[{i}] {role} ─────\n{c}")
                continue
            if not isinstance(c, list):
                continue
            for j, blk in enumerate(c):
                if not isinstance(blk, dict):
                    continue
                bt = blk.get("type") or ""
                if bt == "text":
                    val = blk.get("text") or ""
                elif bt == "thinking":
                    val = blk.get("thinking") or ""
                elif bt == "tool_use":
                    val = f"{blk.get('name') or ''} {json.dumps(blk.get('input') or {}, ensure_ascii=False, sort_keys=True)}"
                elif bt == "tool_result":
                    val = json.dumps(blk.get("content"), ensure_ascii=False)[:4000]
                elif bt == "redacted_thinking":
                    val = "（上游加密的思考，不可读）"
                else:
                    val = json.dumps({k: v for k, v in blk.items() if k != "type"},
                                     ensure_ascii=False)[:2000]
                parts.append(f"───── messages[{i}].{j} {role}/{bt} ─────\n{val}")
        return "\n\n".join(parts)
    raise SS.SnapshotError("bad_face", f"未知的对比面：{face!r}（可选 {'/'.join(FACES)}）")


# ===== 对外入口 =====

def diff_snapshots(sid_a: str, sid_b: str, *, face: str = "", context: int = 3) -> dict:
    """两个快照的完整对比结果（元数据对照 + 文本 diff）。

    两边都是 prompt → 直接比正文，face 忽略。
    两边都是 capture → 必须选一个面（默认 system）。
    一 prompt 一 capture → 拒绝：没有意义的比较，与其给一堆红色不如说清楚为什么不能比。
    """
    a = SS.get_snapshot(sid_a)
    b = SS.get_snapshot(sid_b)
    ka, kb = a.get("kind"), b.get("kind")
    if ka != kb:
        raise SS.SnapshotError(
            "kind_mismatch",
            f"不能比较不同类型的快照（{ka} vs {kb}）：一个是提示词片段，一个是完整录制")

    if ka == "prompt":
        ta = (a.get("payload") or {}).get("text") or ""
        tb = (b.get("payload") or {}).get("text") or ""
        used_face = ""
    else:
        used_face = face or "system"
        if used_face not in FACES:
            raise SS.SnapshotError("bad_face", f"未知的对比面：{used_face!r}")
        ta = face_text(a.get("payload") or {}, used_face)
        tb = face_text(b.get("payload") or {}, used_face)

    out = diff_text(ta, tb, context=context)
    out["a"] = {"sid": sid_a, "kind": ka, "label": a.get("label") or "",
                "created": a.get("created")}
    out["b"] = {"sid": sid_b, "kind": kb, "label": b.get("label") or "",
                "created": b.get("created")}
    out["face"] = used_face
    out["meta"] = compare_meta(a, b) if ka == "prompt" else _capture_meta_compare(a, b)
    return out


def _capture_meta_compare(a: dict, b: dict) -> dict:
    """录制快照没有元数据副本（有意为之），对照时从 payload 现算。"""
    sa = SS._capture_summary(a.get("payload") or {})
    sb = SS._capture_summary(b.get("payload") or {})
    diffs = [{"field": k, "a": sa.get(k), "b": sb.get(k)}
             for k in sa if sa.get(k) != sb.get(k)]
    warns = []
    if sa.get("wire_kind") != sb.get("wire_kind"):
        warns.append({"field": "wire_kind", "why": "请求类型不同，差异大部分来自类型本身"})
    if sa.get("model") != sb.get("model"):
        warns.append({"field": "model", "why": "模型不同"})
    return {"ctx_diff": diffs, "origin_diff": [], "warnings": warns}
