"""捕获记录存储：JSONL append-only 落盘 + 内存 deque + LIVE SSE 推送。

架构：
  - append-only jsonl（按天分文件，PyInstaller 冻结态持久位置 ~/.cc-wire-analyzer/captures/）
  - threading.Lock 串行写盘
  - deque(maxlen=200) 供 LIVE 推送
  - 订阅者 queue.Queue 广播，SSE 客户端阻塞读
"""
from __future__ import annotations

import collections
import json
import queue
import threading
import time
import uuid
from pathlib import Path

import config as CFG

CAPTURES_DIR = CFG.CONFIG_DIR / "captures"
ARCHIVES_DIR = CFG.CONFIG_DIR / "archives"

_LOCK = threading.Lock()
_LIVE_DEQUE: collections.deque = collections.deque(maxlen=200)
_LIVE_SUBSCRIBERS: set[queue.Queue] = set()
_SUB_LOCK = threading.Lock()


def new_record_id() -> str:
    return "req_" + uuid.uuid4().hex[:7]


def _now_iso() -> str:
    """ISO 8601 带毫秒，本地时区。"""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def new_record() -> dict:
    """新建空记录模板（proxy 填充）。"""
    return {
        "id": new_record_id(),
        "ts_start": _now_iso(),
        "ts_end": None,
        "method": None,
        "path": None,
        "upstream": None,
        "request": {"headers_safe": {}, "body": None},
        "response": None,
        "error": None,
    }


def append(record: dict) -> None:
    """落盘 + 推 LIVE。record 应已填完。"""
    date = time.strftime("%Y-%m-%d", time.localtime())
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    f = CAPTURES_DIR / f"{date}.jsonl"
    line = json.dumps(record, ensure_ascii=False)
    with _LOCK:
        try:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # 落盘失败不阻塞转发
    # 内存 deque + 广播（推摘要不推完整 record：契约规定 SSE 是列表项形状，
    # 且完整 body 可能 MB 级，推给 SSE 会拖垮 LIVE 通道）
    summ = _summary(record)
    _LIVE_DEQUE.append(summ)
    with _SUB_LOCK:
        for q in list(_LIVE_SUBSCRIBERS):
            try:
                q.put(summ, block=False)
            except queue.Full:
                pass  # LIVE 不保证可靠，满则丢
            except Exception:
                _LIVE_SUBSCRIBERS.discard(q)


def _summary(rec: dict) -> dict:
    """列表项摘要（去掉大字段 body/content_blocks）。"""
    resp = rec.get("response") or {}
    req_body = (rec.get("request") or {}).get("body") or {}
    summary = ""
    for blk in (resp.get("content_blocks") or []):
        if blk.get("type") == "text" and blk.get("text"):
            summary = blk["text"][:80]
            break
    return {
        "id": rec.get("id"),
        "ts_start": rec.get("ts_start"),
        "method": rec.get("method"),
        "path": rec.get("path"),
        "model": req_body.get("model"),
        "status": resp.get("status"),
        "ttft_ms": resp.get("ttft_ms"),
        "total_ms": resp.get("total_ms"),
        "usage": resp.get("usage"),
        "stop_reason": resp.get("stop_reason"),
        "has_error": rec.get("error") is not None,
        "summary": summary,
    }


def list_captures(date: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    """读指定日期 jsonl，倒序分页返回摘要列表。"""
    if date is None:
        date = time.strftime("%Y-%m-%d", time.localtime())
    f = CAPTURES_DIR / f"{date}.jsonl"
    items = []
    total = 0
    if f.exists():
        with _LOCK:
            with f.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()
        total = len(lines)
        for line in lines[::-1][offset:offset + limit]:
            try:
                items.append(_summary(json.loads(line)))
            except json.JSONDecodeError:
                continue
    return {
        "date": date,
        "total": total,
        "items": items,
        "dates_available": _available_dates(),
    }


def list_full(date: str | None = None, limit: int = 1000) -> list[dict]:
    """读指定日期全量完整 records（供 DAG 分类分析用；nodes 只回摘要不含 body）。"""
    if date is None:
        date = time.strftime("%Y-%m-%d", time.localtime())
    f = CAPTURES_DIR / f"{date}.jsonl"
    if not f.exists():
        return []
    out = []
    with _LOCK:
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(out) >= limit:
                    break
    return out


def get_capture(rid: str, date: str | None = None) -> dict | None:
    """线性扫描找 id 匹配（MVP 不建索引，单文件 < 10k 行可接受）。

    date 指定则只扫该日；为 None 则先扫今天，找不到回退遍历所有历史日期
    （修复：原先写死今天，历史日期详情必然 404，审计 260712 #4）。
    """
    def _scan_one(d: str) -> dict | None:
        f = CAPTURES_DIR / f"{d}.jsonl"
        if not f.exists():
            return None
        with _LOCK:
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                        if rec.get("id") == rid:
                            return rec
                    except json.JSONDecodeError:
                        continue
        return None

    if date:
        return _scan_one(date)
    today = time.strftime("%Y-%m-%d", time.localtime())
    hit = _scan_one(today)
    if hit is not None:
        return hit
    for d in _available_dates():  # 回退遍历历史，最近优先
        if d == today:
            continue
        hit = _scan_one(d)
        if hit is not None:
            return hit
    return None


def _available_dates() -> list[str]:
    if not CAPTURES_DIR.exists():
        return []
    dates = [f.stem for f in CAPTURES_DIR.glob("*.jsonl")]
    dates.sort(reverse=True)
    return dates


def _count_lines(f: Path) -> int:
    """数 jsonl 行数（= 记录条数），不解析 JSON。"""
    try:
        with f.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


class StoreError(RuntimeError):
    """带 code 的存储错误（对齐 app.LlmConfigError 的 code+detail 模式）。"""
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


# 日期白名单：仅 YYYY-MM-DD。date 来自 API 参数，必须校验防路径穿越（260712 安全修复）——
# 否则 date="../etc/x" 会让 purge/archive 读写到 captures/archives 目录外。
import re as _re
_DATE_RE = _re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _validate_date(date: str) -> None:
    """YYYY-MM-DD 格式 + 语义校验（防路径穿越 + 拒非法月日）。"""
    if not isinstance(date, str) or not _DATE_RE.match(date):
        raise StoreError("bad_date", f"非法日期：{date!r}")
    try:
        time.strptime(date, "%Y-%m-%d")   # 校验月日范围（如 2026-13-45 拒绝）
    except ValueError:
        raise StoreError("bad_date", f"非法日期：{date!r}")


def purge_date(date: str) -> int:
    """删除指定日期的录制文件，返回删除的记录条数。
    持 _LOCK 防与 append 竞争；当天则一并清内存 deque（否则 SSE 客户端还看到旧摘要）。"""
    _validate_date(date)
    f = CAPTURES_DIR / f"{date}.jsonl"
    removed = 0
    today = time.strftime("%Y-%m-%d", time.localtime())
    with _LOCK:
        if f.exists():
            removed = _count_lines(f)
            try:
                f.unlink()
            except OSError as e:
                raise StoreError("delete_failed", f"删除失败：{e}")
        if date == today:
            _LIVE_DEQUE.clear()
    return removed


def archive_date(date: str) -> dict:
    """压缩存档指定日期录制到 archives/，再删原文件。
    优先 ZIP_DEFLATED（真压缩，需 zlib）；不可用降级 ZIP_STORED（只打包）——对应用户「压缩不了就打包」。

    锁粒度（260712 性能修复）：锁内只做原子 rename 抢占（毫秒级，不阻塞代理 append），
    压缩移到锁外（数十 MB 可能数秒）。rename 后代理若继续 append 当天会创建新文件（=清除「到目前为止」），
    压缩失败则把临时文件 rename 回原位，不丢数据。"""
    _validate_date(date)
    import zipfile
    import time as _t
    f = CAPTURES_DIR / f"{date}.jsonl"
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    # 压缩级别：DEFLATED 优先，zlib 缺失（极罕见）降级 STORED（只打包）
    try:
        import zlib  # noqa: F401  zipfile 用 zlib 做 DEFLATED，缺则降级
        zmode, compressed = zipfile.ZIP_DEFLATED, True
    except ImportError:
        zmode, compressed = zipfile.ZIP_STORED, False
    ts = _t.strftime("%H%M%S", _t.localtime())
    staging = CAPTURES_DIR / f".{date}.archiving.{ts}.jsonl"
    dst = ARCHIVES_DIR / f"{date}.{ts}.jsonl.zip"
    today = time.strftime("%Y-%m-%d", time.localtime())
    # 锁内：复检 exists（TOCTOU）+ 数行 + rename 抢占 + 清 deque
    with _LOCK:
        if not f.exists():
            raise StoreError("not_found", f"{date} 无录制文件")
        count = _count_lines(f)
        f.rename(staging)   # 原子抢占；此后 append 会建新 {date}.jsonl
        if date == today:
            _LIVE_DEQUE.clear()
    # 锁外：压缩 staging → dst，失败回退
    try:
        with zipfile.ZipFile(dst, "w", zmode) as zf:
            zf.write(staging, arcname=f"{date}.jsonl")
        staging.unlink()
    except Exception as e:
        # 压缩失败/删除失败：把 staging 放回原位，不丢录制；dst 若已建则清掉
        try:
            if staging.exists():
                staging.rename(f)
        except OSError:
            pass
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass
        raise StoreError("archive_failed", f"压缩存档失败：{e}")
    return {"path": str(dst), "size": dst.stat().st_size, "count": count, "compressed": compressed}


def subscribe() -> tuple[queue.Queue, list[dict]]:
    """SSE 订阅。返回 (queue, recent_records)。
    在 SSE generator 里循环 q.get(timeout=N)，新记录 yield 给客户端。"""
    q: queue.Queue = queue.Queue(maxsize=100)
    with _SUB_LOCK:
        _LIVE_SUBSCRIBERS.add(q)
    recent = list(_LIVE_DEQUE)
    return q, recent


def unsubscribe(q: queue.Queue) -> None:
    with _SUB_LOCK:
        _LIVE_SUBSCRIBERS.discard(q)
