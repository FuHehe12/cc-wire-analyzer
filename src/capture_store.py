"""捕获记录存储：JSONL append-only 落盘 + 写时轻量索引 + 内存 deque + LIVE SSE 推送。

架构：
  - append-only jsonl（按天分文件，PyInstaller 冻结态持久位置 ~/.cc-wire-analyzer/captures/）
  - 写时轻量索引 {date}.idx.jsonl（260719 大流量改造）：单条完整 record 可超 5MB，
    一天录制能上 GB，而列表/DAG 只用其中几十个字段。append 时 record 本就在内存，
    顺手提取成 1~2KB 索引记录（含主文件字节偏移 off/len）——列表/泳道只读索引（毫秒级），
    详情按偏移直接 seek。索引缺失/落后按末尾偏移从主文件增量回填自愈。
  - threading.Lock 串行写盘
  - deque(maxlen=200) 供 LIVE 推送
  - 订阅者 queue.Queue 广播，SSE 客户端阻塞读
"""
from __future__ import annotations

import collections
import datetime
import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

import classifier
import config as CFG

log = logging.getLogger(__name__)

CAPTURES_DIR = CFG.CONFIG_DIR / "captures"
ARCHIVES_DIR = CFG.CONFIG_DIR / "archives"

_LOCK = threading.Lock()
_LIVE_DEQUE: collections.deque = collections.deque(maxlen=200)
_LIVE_SUBSCRIBERS: set[queue.Queue] = set()
_SUB_LOCK = threading.Lock()

# 落盘失败计数（260713）：磁盘满/权限/文件被锁时 append 写不进去，但**绝不能因此阻塞转发**
# （代理的透明性优先级最高，录不下来也不许把用户的 CC 弄挂）。
# 可"不阻塞"不等于"不告诉任何人"——旧代码 `except OSError: pass` 把两件事混为一谈：
# 写盘失败被完全吞掉，而 deque + SSE 推送在 try 之外照常执行 →
# **界面 LIVE 还在实时跳，磁盘上一个字节都没有**，用户毫无理由怀疑。
# 现在失败要计数 + 记日志 + 经 /api/proxy/status 顶到 UI 上。
_WRITE_ERRORS = 0
_LAST_WRITE_ERROR: str | None = None

# 索引写失败独立计数（260719）：索引丢了不等于录制丢了（主文件完好），回填能自愈，
# 但次数异常增长说明磁盘/权限有问题，要和主写失败一样看得见。
_IDX_ERRORS = 0
_LAST_IDX_ERROR: str | None = None


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


# 索引记录里不对外（列表/SSE/DAG 输出）的内部字段：
# off/len 是 seek 锚点，其余是 DAG 分类原料（classifier 内部消费）
_IDX_PRIVATE = ("off", "len", "sys_head", "first_user", "last_user",
                "tools_n", "uid", "task_prompts", "turn_start", "tool_uses")


def _public_summary(idx: dict) -> dict:
    """索引记录 → 列表/SSE 摘要（剥掉内部字段，形状与旧 _summary(完整 record) 一致）。"""
    return {k: v for k, v in idx.items() if k not in _IDX_PRIVATE}


def _idx_file(date: str) -> Path:
    return CAPTURES_DIR / f"{date}.idx.jsonl"


# date → (covered_end, entries)：covered_end = 索引已覆盖到的主文件字节位置。
# 主文件 size 不变直接命中缓存（/api/dag 被 LIVE 防抖反复调用时近乎零成本）。
_IDX_CACHE: dict[str, tuple[int, list[dict]]] = {}


def append(record: dict) -> None:
    """落盘 + 写索引 + 推 LIVE。record 应已填完。

    落盘失败**不阻塞转发**（代理透明性优先），但必须留下痕迹：计数 + 日志 + 顶到 UI，
    否则就是"界面在跳、盘上没有"的静默数据丢失（见 _WRITE_ERRORS 注释）。
    索引写失败同样不阻塞、独立计数——索引缺失由读取侧增量回填自愈。"""
    global _WRITE_ERRORS, _LAST_WRITE_ERROR, _IDX_ERRORS, _LAST_IDX_ERROR
    date = time.strftime("%Y-%m-%d", time.localtime())
    f = CAPTURES_DIR / f"{date}.jsonl"
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    ok = True
    idx_entry = None
    with _LOCK:
        try:
            CAPTURES_DIR.mkdir(parents=True, exist_ok=True)   # 目录建不出来也算落盘失败，一并计入
            with f.open("ab") as fh:          # 二进制 append：tell() 是真实字节偏移（索引 seek 锚点）
                fh.seek(0, 2)
                off = fh.tell()
                fh.write(data)
        except OSError as e:
            ok = False
            _WRITE_ERRORS += 1
            _LAST_WRITE_ERROR = f"{type(e).__name__}: {e}"
            log.error("录制落盘失败（第 %d 次，转发不受影响）: %s", _WRITE_ERRORS, e)
        else:
            # 主写成功才写索引（off/len 才有意义）。索引 = classifier.index_record + 字节偏移
            try:
                idx_entry = classifier.index_record(record)
                idx_entry["off"] = off
                idx_entry["len"] = len(data)
                with _idx_file(date).open("ab") as fh:
                    fh.write((json.dumps(idx_entry, ensure_ascii=False) + "\n").encode("utf-8"))
                cached = _IDX_CACHE.get(date)
                if cached:
                    cached[1].append(idx_entry)
                    _IDX_CACHE[date] = (off + len(data), cached[1])
            except Exception as e:      # 索引是优化不是事实源，失败不阻塞转发，回填自愈
                idx_entry = None
                _IDX_ERRORS += 1
                _LAST_IDX_ERROR = f"{type(e).__name__}: {e}"
                log.error("索引写入失败（第 %d 次，读取侧会回填自愈）: %s", _IDX_ERRORS, e)
    # 内存 deque + 广播（推摘要不推完整 record：契约规定 SSE 是列表项形状，
    # 且完整 body 可能 MB 级，推给 SSE 会拖垮 LIVE 通道）
    # 失败的记录照样推 LIVE —— 流量确实发生了，用户有权看到；但状态栏会同时告警"这些没存下来"。
    summ = _public_summary(idx_entry) if idx_entry else _public_summary(
        classifier.index_record(record))
    if not ok:
        summ["not_persisted"] = True
    _LIVE_DEQUE.append(summ)
    with _SUB_LOCK:
        for q in list(_LIVE_SUBSCRIBERS):
            try:
                q.put(summ, block=False)
            except queue.Full:
                pass  # LIVE 不保证可靠，满则丢
            except Exception:
                _LIVE_SUBSCRIBERS.discard(q)


def _read_idx_entries(fi: Path) -> tuple[list[dict], int]:
    """读索引文件全部有效条目，返回 (entries, covered_end)。
    崩溃残留的半行跳过（条目自带 off/len，covered_end 只认完整条目）。"""
    entries: list[dict] = []
    covered = 0
    if fi.exists():
        with fi.open("rb") as fh:
            for raw in fh:
                try:
                    e = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                off, ln = e.get("off"), e.get("len")
                if isinstance(off, int) and isinstance(ln, int):
                    covered = max(covered, off + ln)
                entries.append(e)
    return entries, covered


def _backfill_index(f: Path, fi: Path, start: int) -> tuple[list[dict], int]:
    """从主文件 start 字节处续读，为完整行建索引并追加进 idx 文件（增量回填自愈）。

    触发场景：旧录制没有索引 / 索引写失败落下几条 / 崩溃后索引落后。
    返回 (新条目, 新的 covered_end)。不可解析的行（崩溃残留）跳过但仍推进 covered_end
    ——与主文件读取侧行为一致（json 坏的行当不存在），避免每次读取都重复回填同一行。"""
    new_entries: list[dict] = []
    end = start
    with f.open("rb") as fh:
        fh.seek(start)
        data = fh.read()
    lines = data.split(b"\n")
    trailing = lines.pop()          # 最后一段：data 以 \n 结尾时是 b""，否则是未写完的半行
    off = start
    for raw in lines:
        ln = len(raw) + 1           # +1 是被 split 吃掉的 \n
        if raw.strip():
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                pass                # 崩溃残留/合并坏行：跳过但推进偏移
            else:
                e = classifier.index_record(rec)
                e["off"] = off
                e["len"] = ln
                new_entries.append(e)
        off += ln
        end = off
    if new_entries:
        with fi.open("ab") as fh:
            for e in new_entries:
                fh.write((json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8"))
    return new_entries, end


def _load_index(date: str) -> list[dict]:
    """读指定日期索引（缓存 + 按需增量回填）。**调用方须持 _LOCK**。"""
    f = CAPTURES_DIR / f"{date}.jsonl"
    fi = _idx_file(date)
    if not f.exists():
        if fi.exists():
            try:
                fi.unlink()         # 主文件被外部删了 → 陈旧索引一并清
            except OSError:
                pass
        _IDX_CACHE.pop(date, None)
        return []
    size = f.stat().st_size
    cached = _IDX_CACHE.get(date)
    if cached and cached[0] == size:
        return cached[1]
    entries, covered = _read_idx_entries(fi)
    if covered < size:
        try:
            new_entries, covered = _backfill_index(f, fi, covered)
            entries.extend(new_entries)
            if new_entries:
                log.info("索引回填 %s：补 %d 条", date, len(new_entries))
        except Exception as e:
            # 回填失败不致命：返回已有部分（可能不全），下次读取再试
            log.error("索引回填失败 %s: %s", date, e)
    _IDX_CACHE[date] = (covered, entries)
    return entries


def list_index(date: str | None = None) -> list[dict]:
    """指定日期的全部索引记录（DAG 构建用）。无 1000 条上限——260719 前 list_full
    写死 limit=1000，大流量天（实测 2993 条）泳道图直接丢后 2/3。"""
    if date is None:
        date = time.strftime("%Y-%m-%d", time.localtime())
    with _LOCK:
        return list(_load_index(date))


def list_captures(date: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    """读指定日期索引，倒序分页返回摘要列表。
    260719 改读索引前：每次 readlines 整个主文件 + parse 倒序头 N 行（恰是最大的行），
    826MB 录制实测峰值内存 3.3GB。"""
    if date is None:
        date = time.strftime("%Y-%m-%d", time.localtime())
    entries = list_index(date)
    total = len(entries)
    items = [_public_summary(e) for e in entries[::-1][offset:offset + limit]]
    return {
        "date": date,
        "total": total,
        "items": items,
        "dates_available": _available_dates(),
    }


def list_full(date: str | None = None, limit: int = 100000) -> list[dict]:
    """读指定日期全量**完整** records（含 body，MB 级/条，大流量天 parse 要秒级）。
    仅供 tools/lane_probe.py 等需要 body 内部细节的 dev 工具；热路径一律走 list_index。"""
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
    """按 id 取完整 record。优先走索引 off/len 直接 seek（826MB 文件也是毫秒级）；
    索引缺行时兜底子串预筛扫描（命中 `"<rid>"` 的行才 json.loads，不再逐行全量 parse）。

    date 指定则只扫该日；为 None 则先扫今天，找不到回退遍历所有历史日期
    （修复：原先写死今天，历史日期详情必然 404，审计 260712 #4）。
    """
    def _scan_one(d: str) -> dict | None:
        f = CAPTURES_DIR / f"{d}.jsonl"
        if not f.exists():
            return None
        entries = list_index(d)
        hit = next((e for e in entries if e.get("id") == rid), None)
        if hit is not None and isinstance(hit.get("off"), int) and isinstance(hit.get("len"), int):
            try:
                with f.open("rb") as fh:
                    fh.seek(hit["off"])
                    rec = json.loads(fh.read(hit["len"]))
                if rec.get("id") == rid:
                    return rec
            except (OSError, json.JSONDecodeError):
                pass                # 偏移失效（文件被外部改动）→ 落到扫描兜底
        needle = f'"{rid}"'.encode("utf-8")
        with _LOCK:
            with f.open("rb") as fh:
                for raw in fh:
                    if needle not in raw:
                        continue
                    try:
                        rec = json.loads(raw)
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
    # 只认 YYYY-MM-DD 主文件：滤掉 {date}.idx.jsonl（索引）和 .archiving.* 临时文件，
    # 否则它们会变成日期 chip 混进 UI（260719 索引文件引入后必现）
    dates = [f.stem for f in CAPTURES_DIR.glob("*.jsonl") if _DATE_RE.match(f.stem)]
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
    """删除指定日期的录制文件（主文件 + 索引 + 缓存），返回删除的记录条数。
    持 _LOCK 防与 append 竞争；当天则一并清内存 deque（否则 SSE 客户端还看到旧摘要）。"""
    _validate_date(date)
    f = CAPTURES_DIR / f"{date}.jsonl"
    fi = _idx_file(date)
    removed = 0
    today = time.strftime("%Y-%m-%d", time.localtime())
    with _LOCK:
        if f.exists():
            removed = _count_lines(f)   # 只数行不 parse（删 826MB 文件不该先付 9s 回填）
            try:
                f.unlink()
            except OSError as e:
                raise StoreError("delete_failed", f"删除失败：{e}")
        if fi.exists():
            try:
                fi.unlink()
            except OSError:
                pass            # 索引删不掉不致命：主文件已没，读取侧会清陈旧索引
        _IDX_CACHE.pop(date, None)
        if date == today:
            _LIVE_DEQUE.clear()
    return removed


def write_errors() -> dict:
    """落盘失败统计（供 /api/proxy/status → UI 告警、CLI status → AI 健康检查）。"""
    return {"count": _WRITE_ERRORS, "last": _LAST_WRITE_ERROR,
            "idx_count": _IDX_ERRORS, "idx_last": _LAST_IDX_ERROR}


def enforce_retention(days: int) -> list[str]:
    """删除早于 today-days 的录制文件，返回被删日期列表（升序）。

    260713 修复：此前 retention_days 是**死配置**——设置页白纸黑字承诺「超过天数的 captures 自动清理」，
    但全项目没有一行代码消费它，录制从第一天起永远堆着（实测 13 条 = 5.6MB，重度使用一天上百 MB）。

    - days <= 0 视为「永不清理」（给要留全量的人一个显式出口，不是当成 0 天全删）。
    - 只动 captures/*.jsonl；archives/ 是用户显式存档的，绝不自动删。
    - 按日期字符串比（YYYY-MM-DD 字典序 = 时间序），不碰文件 mtime——
      mtime 会被拷贝/同步改掉，日期在文件名里才是事实。
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        return []
    if days <= 0:
        return []
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    removed = []
    for d in sorted(_available_dates()):
        if not _DATE_RE.match(d):
            continue          # 非日期文件名（如存档中的 .YYYY-MM-DD.archiving.* 临时文件）一律不碰
        if d < cutoff:
            try:
                purge_date(d)
                removed.append(d)
            except StoreError:
                continue      # 单个删不掉不影响其他（占用/权限），下次启动再试
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
    staging_idx = CAPTURES_DIR / f".{date}.archiving.{ts}.idx.jsonl"
    dst = ARCHIVES_DIR / f"{date}.{ts}.jsonl.zip"
    today = time.strftime("%Y-%m-%d", time.localtime())
    # 锁内：复检 exists（TOCTOU）+ 数行 + rename 抢占（主文件与索引一起走）+ 清 deque/缓存
    with _LOCK:
        if not f.exists():
            raise StoreError("not_found", f"{date} 无录制文件")
        count = _count_lines(f)
        f.rename(staging)   # 原子抢占；此后 append 会建新 {date}.jsonl
        fi = _idx_file(date)
        if fi.exists():
            try:
                fi.rename(staging_idx)
            except OSError:
                pass        # 索引 rename 失败不阻断存档：残留索引会因主文件消失被读取侧清掉
        _IDX_CACHE.pop(date, None)
        if date == today:
            _LIVE_DEQUE.clear()
    # 锁外：压缩 staging → dst，失败回退
    try:
        with zipfile.ZipFile(dst, "w", zmode) as zf:
            zf.write(staging, arcname=f"{date}.jsonl")
        staging.unlink()
        if staging_idx.exists():
            try:
                staging_idx.unlink()    # 存档成功：索引已无主文件，一并清
            except OSError:
                pass
    except Exception as e:
        # 压缩失败/删除失败：把 staging 放回原位，不丢录制；dst 若已建则清掉
        try:
            if staging.exists():
                staging.rename(f)
            if staging_idx.exists():
                staging_idx.rename(fi)
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
