"""快照存储：用户显式保存的提示词片段与完整录制，可长期保留、可精确对比。

## 与已有三个概念的边界（命名先划清，否则 UI 上会打架）

  `compact_date()`  整天录制**原地压实**成 pack（内容寻址去重 + zstd），读取侧透明 ——
                    什么都不删，`uncompact_date()` 可逆。260825 新增，别与下面两条混为一谈
  `archive_date()`  整天录制打成可搬运的单文件 `.ccwa`，**默认保留**原录制；
                    `keep=False` 才删（那条路是清理动作）
  `enforce_retention()` 按天数**自动删**过期录制 —— 唯一会自动删数据的动作
  **snapshot（本模块）** 用户显式保存的一份拷贝，**不删任何东西、永不自动清理**

沿用 `archives/` 已确立的原则：用户显式保存的绝不自动删。代价是快照会一直堆，
所以必须给出占用总量（`usage()`）与手动删除入口，让"堆着"这件事是可见的。

## 两类快照的元数据待遇不对称（260808 用户决定）

  kind=capture —— 信封极薄，事实全在 payload（完整 record）里。**不存元数据副本**：
                  record 里本来就有 id/ts/model/upstream/计费头/session_id，再存一份
                  平行副本就是本项目文档腐化四因之首「副本必然分叉」——总有一天两边
                  对不上，而且没人知道该信哪个。
  kind=prompt  —— 片段脱离上下文就只是一坨文本，必须带足元数据，否则"这两段不一样"
                  能看出来，"为什么不一样"永远答不了。

## 索引是缓存不是事实源

`index.jsonl` 只为列表页服务（不必为显示 20 行去读 20 个 800KB 文件）。它**可以从
快照文件全量重建**（`rebuild_index()`），schema 不符或文件缺失时自动重建——与
`captures/*.idx.jsonl` 同一套做法，`_backfill_index` 已经证明这套能自愈。

## 存储的语言中立

快照里**不存任何人类语言文案**（没有自动生成的中文标题）。本项目是三语界面，
存一个中文默认标题，英文用户会永远看到它。label 默认为空，界面按元数据现渲染标题。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

import classifier
import config as CFG

log = logging.getLogger(__name__)

SNAPSHOTS_DIR = CFG.CONFIG_DIR / "snapshots"
_INDEX_FILE = SNAPSHOTS_DIR / "index.jsonl"

# 快照信封格式版本。**改字段集要 bump**——索引 schema 的教训（capture_store._read_idx_entries）：
# 字段集变了而版本没变，旧记录仍"结构有效"，新字段恒缺失、逻辑静默退化成回落分支，
# 没有任何东西会报错。这里同理：版本不符的索引整体重建（快照文件本身永不因版本被丢弃）。
SNAP_SCHEMA = 1

# **可重入**：`list_snapshots()` 在锁内调 `rebuild_index()`，而重建自己也必须持锁
# （260915）——重建要把每个快照文件整份打开读，Windows 上被打开的文件删不掉也覆盖不了，
# 与它并发的删除/更新会当场拿到 WinError 32/5。普通 Lock 在这条路径上会自锁，所以用 RLock。
_LOCK = threading.RLock()

# 索引追加了多少条还没压实。`update_meta` 走追加而不是全量重建（重建是 O(全部快照字节)，
# 拖一张贴纸不该付这个价），代价是同一个 sid 会在索引里留多条——读取侧按 sid 去重、
# 保留最后一条即是当前值。这个计数只为「别让索引无限长」：超过阈值压实一次。
_APPENDS = 0
_APPENDS_MAX = 200

# 写失败计数（对齐 capture_store 的做法）：快照写不进去**必须顶到 UI**。
# 用户点了"备份"、界面弹了成功、磁盘上没有——这是本项目惯犯 bug ③ 的标准形状。
_WRITE_ERRORS = 0
_LAST_WRITE_ERROR: str | None = None


class SnapshotError(RuntimeError):
    """带 code 的快照错误（对齐 capture_store.StoreError / app.LlmConfigError 的 code+detail）。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


# sid 白名单：sid 来自 API 参数，直接拼路径会被 `../` 穿越出目录
# （capture_store._validate_date 同款教训，260712 安全修复）。
_SID_RE = re.compile(r"snap_[0-9a-f]{7,16}\Z")

# 标签：用户自标（"官方链路" / "改配置前"），比较时按标签筛。有界，防单条快照被撑爆。
TAG_MAX_LEN = 32
TAG_MAX_N = 12
LABEL_MAX = 120
NOTE_MAX = 2000


def _validate_sid(sid: str) -> None:
    if not isinstance(sid, str) or not _SID_RE.match(sid):
        raise SnapshotError("bad_sid", f"非法快照 ID：{sid!r}")


def new_snapshot_id() -> str:
    return "snap_" + uuid.uuid4().hex[:7]


def _now_iso() -> str:
    """ISO 8601 带毫秒，本地时区（与 capture_store._now_iso 同格式，两处时间才可比）。"""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


# ===== 指纹 =====

# 归一化规则：抹掉**每次必然不同**的部分，让"除了日期外完全一样"能被判出来。
#
# 为什么必须有这一层：CC 的 system prompt 里含当天日期（`Today's date is ...`）。
# 不做归一化，**每天存的快照两两都"有差异"**，真正的变化（换了模型、改了规则）
# 会淹没在日期噪声里，diff 页面天天满屏红色，等于没做。
#
# 顺序有意义：uuid 先于 hex（uuid 含短横，先抹掉才不会被 hex 规则拆碎），
# date/time 先于 hex（否则 20260802082259ad76 这类无分隔长串会先被 hex 吃掉）。
# **这是启发式不是真理**——命中的规则名会一起存进 fp.norm_rules，让读的人知道抹了什么。
_NORM_RULES: list[tuple[str, re.Pattern]] = [
    ("uuid", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
    ("date", re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}")),
    ("time", re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")),
    # 长 hex 无词边界（`20260802082259ad76…`，260807 失败指纹归并踩过的坑：
    # 数字与字母之间没有 \b，加了词边界反而匹配不到）。16 位阈值同那次结论：
    # 更短的 hex 可能是有意义的错误码，抹掉会丢信息。
    ("hex16+", re.compile(r"[0-9a-fA-F]{16,}")),
]


def normalize_text(text: str) -> tuple[str, list[str]]:
    """归一化文本 → (归一化结果, 命中的规则名)。规则见 _NORM_RULES 注释。"""
    hit: list[str] = []
    out = text
    for name, pat in _NORM_RULES:
        out, n = pat.subn(f"<{name}>", out)
        if n:
            hit.append(name)
    return out, hit


def text_fingerprint(text: str) -> dict:
    """文本指纹：原文 hash + 归一化 hash + 规模。

    两个 hash 各有用途：
      sha256      判「一模一样」（去重、"与快照 X 内容相同"提示）
      norm_sha256 判「除了日期这类必变部分外一模一样」——这才是日常真正想问的问题
    """
    norm, rules = normalize_text(text)
    return {
        "sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
        "norm_sha256": hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest(),
        "norm_rules": rules,
        "chars": len(text),
        "lines": text.count("\n") + 1 if text else 0,
    }


# ===== 元数据提取（只给 kind=prompt 用） =====

# 工作空间：实测 `Primary working directory: D:\Claude`（260808，89 次命中）。
# 与它同段的还有 git 仓库标志与平台——CC 把运行环境写在同一块里，一次正则全取。
_WS_RE = re.compile(r"Primary working directory:\s*(.+)")
_GIT_RE = re.compile(r"Is a git repository:\s*(true|false)", re.IGNORECASE)
_PLATFORM_RE = re.compile(r"Platform:\s*(\S+)")


def _iter_texts(body: dict):
    """请求体里所有**真实文本**（system 各块 + messages 的 text 块）。

    环境信息要在这些文本上找，**不能在 `json.dumps(body)` 上找**：序列化后换行变成字面
    `\\n`、整个 body 成了一行，于是 `(.+)` 会一路贪婪匹配到几十万字符之后，抽出来的
    "工作空间"是半个请求体。（260808 自测抓到，此前肉眼"验证"过却因为打印被截断而没看见。）
    """
    sysv = body.get("system")
    if isinstance(sysv, str):
        yield sysv
    elif isinstance(sysv, list):
        for b in sysv:
            if isinstance(b, dict) and b.get("text"):
                yield b["text"]
    for m in (body.get("messages") or []):
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            yield c
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                    yield b["text"]


def _env_of(body: dict) -> dict:
    """从请求体里抽运行环境（工作空间/平台/是否 git 仓库）。

    **不限定在 system 里找**：证据 6（260808）实测 CC 的规则库可能在 system[2]，
    也可能在 messages[0]（用户 CLAUDE.md 注入），链路不同位置不同。所以扫全部文本，
    找到第一处即可——这几个值在一次请求内不会自相矛盾。

    取不到就留空并**不编造**：空值在界面上显示为「未知」，比一个猜出来的路径诚实。
    """
    out: dict = {}
    for text in _iter_texts(body):
        if "workspace" not in out:
            m = _WS_RE.search(text)
            if m:
                out["workspace"] = m.group(1).strip().rstrip(",")
        if "git_repo" not in out:
            m = _GIT_RE.search(text)
            if m:
                out["git_repo"] = m.group(1).lower() == "true"
        if "platform" not in out:
            m = _PLATFORM_RE.search(text)
            if m:
                out["platform"] = m.group(1).strip().rstrip(",")
        if len(out) == 3:
            break
    return out


def _upstream_host(record: dict) -> str:
    """上游主机名（供应商指纹）。

    record.upstream 实测是完整 URL（`https://open.bigmodel.cn/api/anthropic/v1/messages`）。
    只取 host：**同一个 CC 走不同供应商，提示词本就不同**——没有这个字段，diff 出差异
    也归因不了，而它恰恰是最常见的差异来源。存 host 不存全路径，路径里可能有版本段，
    对"哪家供应商"这个问题是噪声。
    """
    up = record.get("upstream") or ""
    if not isinstance(up, str) or not up:
        return ""
    try:
        from urllib.parse import urlparse
        return urlparse(up).netloc or ""
    except Exception:
        return ""


def _harness(sys_text: str) -> tuple[str, str]:
    """(harness, entrypoint)：CC 自报的版本与入口，来自 system[0] 计费头。"""
    kv = classifier.billing_kv(sys_text[:2000])
    ver = kv.get("cc_version") or ""
    return (f"claude-code/{ver}" if ver else ""), (kv.get("cc_entrypoint") or "")


def _prompt_ctx(record: dict) -> dict:
    """提示词快照的 ctx 组：产生这段提示词的条件。差异归因全靠这一组。

    大部分字段直接取 `classifier.index_record` 的产物——采集侧早就在算了，
    这里再抄一遍提取逻辑就是第二个会分叉的副本。
    """
    idx = classifier.index_record(record)
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    sys_text = classifier._system_text(body)
    harness, entrypoint = _harness(sys_text)
    try:
        wire_kind = classifier.classify_idx(idx)
    except Exception as e:
        # 分类失败降级但**记日志**（capture_store._public_summary 同款纪律）：
        # 分类原料一变，整批快照会静默全变 other，没人会怀疑。
        log.error("快照 wire_kind 分类失败（降级 other）: %s", e)
        wire_kind = "other"
    return {
        "model": body.get("model") or "",
        "upstream": _upstream_host(record),
        "harness": harness,
        "entrypoint": entrypoint or idx.get("entrypoint") or "",
        "wire_kind": wire_kind,
        "is_subagent": bool(idx.get("is_subagent")),
        "agent_fp": idx.get("agent_fp") or "",
        "agent_id": idx.get("agent_id") or "",
        "session_id": idx.get("session_id") or "",
        "beta": idx.get("beta") or [],
        "env": _env_of(body),
    }


# ===== origin：这段文字是从哪儿撕下来的 =====

# kind_hint 的判别措辞。**故意保守**：认不出来就是 "other"，不猜。
# 一个猜错的类型标签会让可比性护栏（4.2）给出错误的"这两段不是同类"警告，
# 比没有标签更坏。
_HINT_BILLING = "x-anthropic-billing-header"
_HINT_IDENTITY = "you are claude code"


def _kind_hint(where: dict, text: str, role: str) -> str:
    """这段提示词属于哪一类来源。见证据 6：指令来源实测有五处，不止 system。"""
    w = where.get("kind")
    if w == "selection":
        return "selection"
    low = text[:200].lower()
    if w == "system":
        i = where.get("index")
        if low.startswith(_HINT_BILLING):
            return "billing_header"
        if i == 1 or (len(text) < 200 and _HINT_IDENTITY in low):
            return "identity"
        return "cc_rules"
    if w == "message":
        if role == "system":
            # 会话中系统消息（skill 清单 / 注入提醒）。实测 9,722 字，
            # 是与 system 块平级的第五个指令来源。
            return "midconv_system"
        if role == "user":
            return "user_rules"
        return "assistant_text"
    return "other"


def _system_block_texts(body: dict) -> list[str]:
    sysv = body.get("system")
    if isinstance(sysv, str):
        return [sysv]
    if isinstance(sysv, list):
        return [(b.get("text") or "") if isinstance(b, dict) else str(b) for b in sysv]
    return []


def _resolve_origin(body: dict, where: dict) -> tuple[str, dict]:
    """按 where 定位并取出那段文字 → (text, origin)。

    where 三种形态：
      {"kind": "system",    "index": i}
      {"kind": "message",   "index": i, "block": j}
      {"kind": "selection", "text": "..."}   自由选中，位置不可定位
    """
    kind = (where or {}).get("kind")
    blocks = _system_block_texts(body)
    origin: dict = {
        "sys_blocks": len(blocks),
        # 块形状：「提示词变了」有一种形态是**块被拆分或合并**，只盯单块文本会完全漏掉。
        "block_shape": [len(t) for t in blocks],
    }
    role = ""
    cache_control = ""

    if kind == "system":
        i = where.get("index")
        if not isinstance(i, int) or not (0 <= i < len(blocks)):
            raise SnapshotError("bad_origin", f"system[{i}] 不存在（共 {len(blocks)} 块）")
        text = blocks[i]
        role = "system"
        sysv = body.get("system")
        if isinstance(sysv, list) and isinstance(sysv[i], dict):
            cc = sysv[i].get("cache_control")
            if isinstance(cc, dict):
                cache_control = cc.get("type") or "on"
            elif cc:
                cache_control = str(cc)
        origin["where"] = f"system[{i}]"

    elif kind == "message":
        i, j = where.get("index"), where.get("block")
        msgs = body.get("messages") or []
        if not isinstance(i, int) or not (0 <= i < len(msgs)):
            raise SnapshotError("bad_origin", f"messages[{i}] 不存在（共 {len(msgs)} 条）")
        msg = msgs[i]
        role = msg.get("role") or ""
        content = msg.get("content")
        if isinstance(content, str):
            text = content
            origin["where"] = f"messages[{i}]"
        else:
            if not isinstance(content, list) or not isinstance(j, int) or not (0 <= j < len(content)):
                raise SnapshotError("bad_origin", f"messages[{i}].content[{j}] 不存在")
            blk = content[j]
            text = (blk.get("text") if isinstance(blk, dict) else str(blk)) or ""
            cc = blk.get("cache_control") if isinstance(blk, dict) else None
            if isinstance(cc, dict):
                cache_control = cc.get("type") or "on"
            origin["where"] = f"messages[{i}].content[{j}]"

    elif kind == "selection":
        text = where.get("text") or ""
        if not text.strip():
            raise SnapshotError("bad_origin", "选中内容为空")
        origin["where"] = "selection"

    else:
        raise SnapshotError("bad_origin", f"未知的来源类型：{kind!r}")

    origin["role"] = role
    origin["cache_control"] = cache_control
    origin["kind_hint"] = _kind_hint(where, text, role)
    return text, origin


# ===== 写入 =====

def _sanitize_meta(label: str, note: str, tags) -> tuple[str, str, list[str]]:
    lab = (str(label or "")).strip()[:LABEL_MAX]
    nt = (str(note or "")).strip()[:NOTE_MAX]
    out_tags: list[str] = []
    if isinstance(tags, list):
        for t in tags[:TAG_MAX_N]:
            s = str(t).strip()[:TAG_MAX_LEN]
            if s and s not in out_tags:
                out_tags.append(s)
    return lab, nt, out_tags


def _snap_file(sid: str) -> Path:
    return SNAPSHOTS_DIR / f"{sid}.json"


def _tmp_file(stem: str) -> Path:
    """写入用的临时文件名。**每个写入方各用各的**（pid + 线程 id）：
    固定名字（`.index.writing`）在两个请求线程同时重建索引时会互相截断，
    Windows 上后一个 `replace()` 直接 WinError 32（260915 实测）。"""
    return SNAPSHOTS_DIR / f".{stem}.{os.getpid()}.{threading.get_ident()}.writing"


def _atomic_write(path: Path, data: bytes, *, stem: str) -> None:
    """先写临时文件再 rename：中途断电/磁盘满不会留下半个 JSON 让读取侧崩。
    失败时把自己的临时文件清掉，不在快照目录里留垃圾。"""
    tmp = _tmp_file(stem)
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# 旁挂文件：跟着快照走、可重算的派生物。**清单只在这一处**——删除、size_of、便携包
# 三处都从这里取。此前各抄一份，于是 260910 取消八视图后 `.semantic.json` 只在导入侧
# 被记得、删除侧漏了，磁盘上留下一堆谁也不读的孤儿（本机实测两份共 22KB）。
def _side_files(sid: str) -> list[Path]:
    return [chat_file(sid), analysis_file(sid), semantic_file(sid)]


def _capture_summary(record: dict) -> dict:
    """kind=capture 的列表显示字段。**现算的缓存，不是元数据副本**——
    随时可从 payload 重算（rebuild_index 就是这么做的）。"""
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    msgs = body.get("messages") or []
    th_n = th_chars = red_n = 0
    for m in msgs:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "thinking":
                th_n += 1
                th_chars += len(b.get("thinking") or "")
            elif b.get("type") == "redacted_thinking":
                red_n += 1
    try:
        wire_kind = classifier.classify_idx(classifier.index_record(record))
    except Exception:
        wire_kind = "other"
    try:
        nbytes = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        nbytes = 0
    return {
        "record_id": record.get("id") or "",
        "ts_start": record.get("ts_start") or "",
        "model": body.get("model") or "",
        "wire_kind": wire_kind,
        "msgs": len(msgs),
        "tools": len(body.get("tools") or []),
        "thinking_blocks": th_n,
        "thinking_chars": th_chars,
        "redacted_blocks": red_n,
        "bytes": nbytes,
    }


def _envelope_summary(snap: dict) -> dict:
    """快照信封 → 索引条目（列表页/API 列表用，**不含 payload**）。"""
    out = {k: snap.get(k) for k in
           ("sid", "kind", "schema", "ccwa_version", "created", "created_by",
            "label", "note", "tags", "board")}
    if snap.get("kind") == "prompt":
        out["origin"] = snap.get("origin") or {}
        out["src"] = snap.get("src") or {}
        out["ctx"] = snap.get("ctx") or {}
        out["fp"] = snap.get("fp") or {}
    else:
        out["summary"] = _capture_summary((snap.get("payload") or {}))
    return out


def _append_index(entry: dict) -> None:
    """往索引追加一条信封（**调用方须持锁**）。同 sid 追加多条是允许的：
    读取侧按 sid 去重、保留最后一条。攒够 `_APPENDS_MAX` 条压实一次。"""
    global _APPENDS
    with _INDEX_FILE.open("ab") as fh:
        fh.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
    _APPENDS += 1
    if _APPENDS >= _APPENDS_MAX:
        try:
            rebuild_index()          # 内部会把 _APPENDS 归零
        except OSError as e:
            # 压实失败不影响这次写入（索引已经落盘，只是长了点）
            log.warning("快照索引压实失败（下次再试）: %s", e)


def _write(snap: dict) -> dict:
    """落盘快照 + 追加索引。失败**抛错**（与录制不同：录制失败不许阻塞转发，
    而快照是用户的显式动作，失败必须让用户知道，不能假装成功）。"""
    global _WRITE_ERRORS, _LAST_WRITE_ERROR
    sid = snap["sid"]
    entry = _envelope_summary(snap)
    with _LOCK:
        try:
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            data = json.dumps(snap, ensure_ascii=False).encode("utf-8")
            _atomic_write(_snap_file(sid), data, stem=sid)
            _append_index(entry)
        except OSError as e:
            _WRITE_ERRORS += 1
            _LAST_WRITE_ERROR = f"{type(e).__name__}: {e}"
            log.error("快照写入失败（第 %d 次）: %s", _WRITE_ERRORS, e)
            raise SnapshotError("write_failed", f"快照写入失败：{e}")
    return entry


def create_capture(record: dict, *, label: str = "", note: str = "",
                   tags=None, created_by: str = "ui") -> dict:
    """录制快照：信封 + 完整 record 原样。不存元数据副本（见模块 docstring）。"""
    if not isinstance(record, dict) or not record.get("id"):
        raise SnapshotError("bad_record", "录制记录为空或缺 id")
    lab, nt, tg = _sanitize_meta(label, note, tags)
    snap = {
        "sid": new_snapshot_id(),
        "kind": "capture",
        "schema": SNAP_SCHEMA,
        "ccwa_version": _version(),
        "created": _now_iso(),
        "created_by": created_by,
        "label": lab, "note": nt, "tags": tg,
        "payload": record,
    }
    return _write(snap)


def create_prompt(record: dict, where: dict, *, label: str = "", note: str = "",
                  tags=None, created_by: str = "ui") -> dict:
    """提示词快照：一段文字 + 四组元数据（origin / src / ctx / fp）。"""
    if not isinstance(record, dict) or not record.get("id"):
        raise SnapshotError("bad_record", "录制记录为空或缺 id")
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    text, origin = _resolve_origin(body, where or {})
    lab, nt, tg = _sanitize_meta(label, note, tags)
    snap = {
        "sid": new_snapshot_id(),
        "kind": "prompt",
        "schema": SNAP_SCHEMA,
        "ccwa_version": _version(),
        "created": _now_iso(),
        "created_by": created_by,
        "label": lab, "note": nt, "tags": tg,
        "origin": origin,
        "src": {
            "record_id": record.get("id") or "",
            "date": (record.get("ts_start") or "")[:10],
            "ts_start": record.get("ts_start") or "",
            "path": record.get("path") or "",
        },
        "ctx": _prompt_ctx(record),
        "fp": text_fingerprint(text),
        "payload": {"text": text},
    }
    return _write(snap)


def _version() -> str:
    """本工具版本（写进快照，将来读旧快照时知道它是哪个版本产的）。
    `_version.py` 由 CI 从 tag 生成、仓库不含，源码跑时可能不存在 → 回落 dev。"""
    try:
        from _version import VERSION
        return VERSION
    except ImportError:
        return "dev"


# ===== 读取 =====

def _read_index() -> list[dict] | None:
    """读索引；文件缺失或任一条目 schema 不符 → None（调用方全量重建）。

    **按 sid 去重、保留最后一条**（260915）。两个理由，缺一不可：

      ① `update_meta` 走追加而不是全量重建，同一个 sid 本来就会有多条，后写的是当前值。
      ② 就算没有 ①，索引里也可能混进重复行（追加与重建交叠、导入、崩溃残留）。不去重的
         后果实测过：白板上凭空多出一张一模一样的贴纸，而且批量删除时同一个 sid 被删两遍，
         第二遍必然报「快照不存在」——用户看到的「贴纸变多」和「批量删除失败」是同一个病。
    """
    if not _INDEX_FILE.exists():
        return None
    by_sid: dict[str, dict] = {}
    try:
        with _INDEX_FILE.open("rb") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    e = json.loads(raw)
                except json.JSONDecodeError:
                    continue          # 崩溃残留半行：跳过（索引可重建，不必为它报错）
                if e.get("schema") != SNAP_SCHEMA:
                    log.info("快照索引 schema 过期（%r，当前 %d）→ 整体重建",
                             e.get("schema"), SNAP_SCHEMA)
                    return None
                sid = e.get("sid")
                if not sid:
                    continue          # 没有 sid 的条目点不动也删不掉，不往界面上放
                by_sid[sid] = e       # dict 保插入序，后写的覆盖前一条、位置不变
    except OSError as e:
        log.error("快照索引读取失败（改走重建）: %s", e)
        return None
    return list(by_sid.values())


def rebuild_index() -> list[dict]:
    """从快照文件全量重建索引。索引是缓存不是事实源——丢了、坏了、版本旧了都能重来。

    **全程持锁**（260915）：重建要把每个快照文件整份打开读，而 Windows 上被打开的文件
    删不掉、也不能被 `replace()` 覆盖。此前它不取锁，于是与它并发的删除当场拿到
    `WinError 32`、更新拿到 `WinError 5`——实测「16 张删 15 张、1 张失败」，正是用户报的
    「批量删除失败」。锁是 RLock，`list_snapshots` 那条已在锁内的路径可以照常进来。

    代价是重建是 O(全部快照字节)，所以**只在真需要时调**：索引坏了、删除之后、攒够
    `_APPENDS_MAX` 条追加。拖一张贴纸不该付这个价（见 `update_meta`）。
    """
    with _LOCK:
        return _rebuild_index_locked()


def _rebuild_index_locked() -> list[dict]:
    global _APPENDS
    entries: list[dict] = []
    if not SNAPSHOTS_DIR.exists():
        _APPENDS = 0
        return entries
    for f in sorted(SNAPSHOTS_DIR.glob("snap_*.json")):
        # 旁挂文件不是快照。`snap_*.json` 这个 glob 会把 `snap_x.analysis.json` 一起捞进来
        # （260827 实测：重建后贴纸板上每份分析多出一张没有 kind/label 的幽灵贴纸）。
        # 判据用 sid 正则而不是"排除 .analysis"——将来再加旁挂后缀不用回来改这里。
        if not _SID_RE.match(f.name[:-len(".json")]):
            continue
        try:
            snap = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.error("快照文件损坏，跳过 %s: %s", f.name, e)
            continue
        try:
            entries.append(_envelope_summary(snap))
        except Exception as e:
            log.error("快照索引重建失败 %s: %s", f.name, e)
    entries.sort(key=lambda e: e.get("created") or "")
    try:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write(_INDEX_FILE,
                      ("".join(json.dumps(e, ensure_ascii=False) + "\n"
                               for e in entries)).encode("utf-8"),
                      stem="index")
        _APPENDS = 0
    except OSError as e:
        log.error("快照索引写回失败（本次仍返回内存结果）: %s", e)
    return entries


def list_snapshots(kind: str = "") -> list[dict]:
    """快照列表（新的在前）。kind 可选过滤 prompt/capture。"""
    with _LOCK:
        entries = _read_index()
        if entries is None:
            entries = rebuild_index()
    if kind:
        entries = [e for e in entries if e.get("kind") == kind]
    return sorted(entries, key=lambda e: e.get("created") or "", reverse=True)


def get_snapshot(sid: str) -> dict:
    """完整快照（含 payload）。"""
    _validate_sid(sid)
    f = _snap_file(sid)
    if not f.exists():
        raise SnapshotError("not_found", f"快照不存在：{sid}")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SnapshotError("read_failed", f"快照读取失败：{e}")


def get_text(sid: str) -> str:
    """快照的可对比文本。prompt → 那段文字；capture → 不适用（对比面由 diff 侧决定）。"""
    snap = get_snapshot(sid)
    if snap.get("kind") != "prompt":
        raise SnapshotError("not_prompt", f"{sid} 不是提示词快照")
    return (snap.get("payload") or {}).get("text") or ""


def update_meta(sid: str, *, label=None, note=None, tags=None, board=None) -> dict:
    """改标签/备注/标记/白板位置。只动信封，payload 与元数据不可改
    （快照的价值就在于它不变）。

    `board` 是白板上这张贴纸的坐标。它跟着快照走而不是存在配置里：贴纸摆在哪儿是
    **用户对这批快照的信息组织**（哪几张归一堆、哪张摆在显眼处），删掉快照它就该一起消失，
    而不是在配置里留一条指向不存在快照的孤儿坐标。

    **读与写在同一把锁里**（260915）：此前只锁写入那一段，于是「拖贴纸」与「批量清理」
    撞上时，update_meta 会把刚被删掉的快照整份写回磁盘——贴纸删完又自己长回来，实测复现。
    """
    with _LOCK:
        return _update_meta_locked(sid, label=label, note=note, tags=tags, board=board)


def _update_meta_locked(sid: str, *, label=None, note=None, tags=None, board=None) -> dict:
    snap = get_snapshot(sid)
    if label is not None:
        snap["label"] = str(label).strip()[:LABEL_MAX]
    if note is not None:
        snap["note"] = str(note).strip()[:NOTE_MAX]
    if tags is not None:
        _, _, snap["tags"] = _sanitize_meta("", "", tags)
    if board is not None:
        try:
            x, y = int(board.get("x", 0)), int(board.get("y", 0))
        except (AttributeError, TypeError, ValueError):
            raise SnapshotError("bad_board", f"非法白板坐标：{board!r}")
        # 夹在合理范围内：负坐标会让贴纸飘到画布外再也点不到，超大坐标把画布撑成几万像素
        snap["board"] = {"x": max(0, min(x, 20000)), "y": max(0, min(y, 20000))}
    entry = _envelope_summary(snap)
    try:
        _atomic_write(_snap_file(sid),
                      json.dumps(snap, ensure_ascii=False).encode("utf-8"), stem=sid)
        # 信封变了，索引**追加一条新的**而不是全量重建（260915）。重建要读遍所有快照
        # 文件（本机 16 张 4.2MB 实测 80ms，堆到几百 MB 就是几秒），而拖一张贴纸松手
        # 就走这条路——「点击调整贴纸有卡顿」的全部来源。读取侧按 sid 保留最后一条，
        # 追加与重建对外是同一个结果。
        _append_index(entry)
    except OSError as e:
        raise SnapshotError("write_failed", f"快照更新失败：{e}")
    return entry


def _unlink_retry(f: Path) -> None:
    """删文件，被占用时退一步再试一次。

    Windows 上「另一个程序正在使用此文件」是本地环境的常态（杀毒、搜索索引器、还没关掉
    的读句柄）。本进程内的读写已经由 `_LOCK` 串起来了，剩下的是进程外的瞬时占用——
    一次短重试就能把这类偶发挡掉，挡不掉的才是真失败，照常抛出去让 UI 说得出原因。"""
    try:
        f.unlink()
    except PermissionError:
        time.sleep(0.15)
        f.unlink()


def delete_snapshot(sid: str) -> dict:
    """删除快照（含它的分析对话记录）。用户显式动作，不做软删。"""
    _validate_sid(sid)
    f = _snap_file(sid)
    if not f.exists():
        raise SnapshotError("not_found", f"快照不存在：{sid}")
    with _LOCK:
        try:
            _unlink_retry(f)
        except OSError as e:
            raise SnapshotError("delete_failed", f"删除失败：{e}")
        # 派生物跟着快照走，清单在 `_side_files`。删不掉不致命——快照已没，它们成了孤儿
        # 文件，重建索引看不到；但新增派生文件时要去 `_side_files` 加，删除侧不再各抄一份。
        for side in _side_files(sid):
            if side.exists():
                try:
                    _unlink_retry(side)
                except OSError:
                    pass
        _rebuild_index_locked()
    return {"sid": sid, "deleted": True}


def select_snapshots(*, kind: str = "", tags=None, before: str = "",
                     sids=None) -> list[dict]:
    """按条件选出快照信封。**这是批量清理的第一步**——先看命中谁，再决定删不删。

    条件之间是「与」：kind 匹配、tags 至少命中一个、created 早于 before。
    `before` 收 `YYYY-MM-DD` 或完整 ISO 时间戳，字符串前缀比较即可（created 是 ISO）。
    什么条件都不给时返回全部——调用方必须自己确认这是不是用户的本意，
    本函数不替它兜底（兜底就意味着"全选"这个合法意图永远做不到）。
    """
    items = list_snapshots(kind)
    if sids:
        want = set(sids)
        items = [e for e in items if e.get("sid") in want]
    if tags:
        want_t = {str(t).strip() for t in tags if str(t).strip()}
        if want_t:
            items = [e for e in items if want_t & set(e.get("tags") or [])]
    if before:
        b = str(before).strip()
        items = [e for e in items if (e.get("created") or "") < b]
    return items


def size_of(sid: str) -> int:
    """这个快照（含它的对话记录）占多少字节。清理预览要说得出"能腾出多少"，
    否则"删 12 条"这句话不构成决策依据。"""
    _validate_sid(sid)
    n = 0
    for f in [_snap_file(sid)] + _side_files(sid):
        try:
            n += f.stat().st_size
        except OSError:
            continue
    return n


def delete_many(sids) -> dict:
    """批量删除。索引只重建一次（逐条删各重建一次，删 50 条就重建 50 遍）。

    单条失败不中断——删一半停下来，用户既不知道删了哪些、也不知道还剩哪些。
    失败的 sid 原样返回，让 UI 说得出「3 条删了、1 条没删掉，原因是…」。

    **入参先去重**（260915）：同一个 sid 传两遍时，第二遍必然撞上「快照不存在」，
    于是一次正常的清理会报出失败。索引侧已经去重了，这里是第二道——批量删除的入口
    不止 UI 一处（API、CLI），不该要求每个调用方自己保证不重复。
    """
    ok: list[str] = []
    failed: list[dict] = []
    freed = 0
    with _LOCK:
        for sid in dict.fromkeys(sids or []):
            try:
                _validate_sid(sid)
                f = _snap_file(sid)
                if not f.exists():
                    failed.append({"sid": sid, "error": "快照不存在"})
                    continue
                try:
                    freed += f.stat().st_size
                except OSError:
                    pass
                _unlink_retry(f)
                ok.append(sid)
                # 派生物与单条删除走同一份清单 `_side_files`
                for side in _side_files(sid):
                    if side.exists():
                        try:
                            freed += side.stat().st_size
                            _unlink_retry(side)
                        except OSError:
                            pass
            except (SnapshotError, OSError) as e:
                failed.append({"sid": sid, "error": str(e)})
        _rebuild_index_locked()
    return {"deleted": len(ok), "sids": ok, "failed": failed, "freed": freed}


# ===== 骨架的 AI 语义分析（落盘，跟着快照走；产出由 app 侧调用 LLM 得到）=====
#
# **单独一个文件，不进快照信封**（260809）。信封里的正文与元数据是不可改的——快照的价值
# 就在于它不变（见 update_meta 的 docstring）。而这份东西是**可重算的派生物**，"重新分析"
# 要覆盖写；混进信封就意味着每次重新分析都在改快照本体，直接破坏那条不变量。
# 独立文件另外白得三件事，且都照 chat_file 的现成先例：删快照时一并删、size_of 统计得到、
# 重新分析是原子替换独立文件（失败不损坏快照本体）。

def analysis_file(sid: str) -> Path:
    _validate_sid(sid)
    return SNAPSHOTS_DIR / f"{sid}.analysis.json"


def semantic_file(sid: str) -> Path:
    """八视图语义层的产物。**已不再生成**（260910 随八视图取消），但旧快照旁边还躺着，
    所以它必须留在 `_side_files` 里：删快照时一起删、占用统计算得到。
    取消一个功能不等于它的磁盘残留会自己消失。"""
    _validate_sid(sid)
    return SNAPSHOTS_DIR / f"{sid}.semantic.json"


def read_analysis(sid: str) -> dict | None:
    """已有的语义分析；没有则 None。**外部 agent 也读得到**（同 chat_history 的理由）。"""
    f = analysis_file(sid)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # 读不出来当作没有，但要留痕：静默返回 None 会让"文件坏了"和"没分析过"
        # 在界面上完全一样（惯犯 ③）。
        log.warning("analysis unreadable %s: %s", sid, e)
        return None


def write_analysis(sid: str, data: dict) -> dict:
    """落盘（原子替换）。重新分析走同一条路径，直接覆盖。"""
    _validate_sid(sid)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        # 在锁内确认快照还在：锁外查一次再进来写，中间快照可能已被批量清理删掉，
        # 那样会留下一份没有主人的 analysis 孤儿（与 update_meta 同一类竞态）
        if not _snap_file(sid).exists():
            raise SnapshotError("not_found", f"快照不存在：{sid}")
        try:
            _atomic_write(analysis_file(sid),
                          json.dumps(data, ensure_ascii=False).encode("utf-8"),
                          stem=f"{sid}.analysis")
        except OSError as e:
            raise SnapshotError("write_failed", f"分析结果写入失败：{e}")
    return data


# ===== 分析对话（落盘，跟着快照走；写入由 app 侧调用） =====

def chat_file(sid: str) -> Path:
    _validate_sid(sid)
    return SNAPSHOTS_DIR / f"{sid}.chat.jsonl"


def chat_history(sid: str) -> list[dict]:
    """该快照的 AI 分析对话历史。**外部 agent 也读得到**——软件内 AI 已经分析出什么，
    两条路不该互相隔绝（issue 4.5）。"""
    f = chat_file(sid)
    if not f.exists():
        return []
    out: list[dict] = []
    try:
        with f.open("rb") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        log.error("分析对话读取失败 %s: %s", sid, e)
    return out


def chat_append(sid: str, role: str, content: str) -> None:
    """追加一条对话消息。失败只记日志不抛——对话已经发生过了，
    存不下来不该让用户以为这轮问答失败了；但错误要留痕。"""
    global _WRITE_ERRORS, _LAST_WRITE_ERROR
    rec = {"ts": _now_iso(), "role": role, "content": content}
    try:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        with chat_file(sid).open("ab") as fh:
            fh.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    except (OSError, SnapshotError) as e:
        _WRITE_ERRORS += 1
        _LAST_WRITE_ERROR = f"{type(e).__name__}: {e}"
        log.error("分析对话落盘失败 %s: %s", sid, e)


def chat_clear(sid: str) -> None:
    f = chat_file(sid)
    if f.exists():
        try:
            f.unlink()
        except OSError as e:
            raise SnapshotError("delete_failed", f"对话记录清除失败：{e}")


# ===== 占用（快照永不自动清理，占用必须可见） =====

def usage() -> dict:
    """快照占用总量。**这是「永不自动清理」这个决定的配套**——不给出占用，
    "堆着"就是不可见的，用户某天才发现磁盘被吃光。

    `count` 只数真快照，`bytes` 把旁挂文件也算上——问的是两个不同的问题：「有几张贴纸」
    和「这个目录吃了多少磁盘」。此前 `snap_*.json` 一把抓，把 `.analysis.json`、
    `.semantic.json` 也数成了快照（本机实测报 22 张、实为 16 张）。判据与 `rebuild_index`
    同一个 `_SID_RE`——260827 修「幽灵贴纸」时就是这么判的，占用这一处当时漏了。
    """
    n = 0
    total = 0
    if SNAPSHOTS_DIR.exists():
        for f in SNAPSHOTS_DIR.glob("snap_*"):
            try:
                total += f.stat().st_size
            except OSError:
                continue
            if f.suffix == ".json" and _SID_RE.match(f.name[:-len(".json")]):
                n += 1
    return {"count": n, "bytes": total, "dir": str(SNAPSHOTS_DIR)}


def write_errors() -> dict:
    """写失败统计（顶到 UI 与 /api/proxy/status，对齐 capture_store.write_errors）。"""
    return {"count": _WRITE_ERRORS, "last": _LAST_WRITE_ERROR}
