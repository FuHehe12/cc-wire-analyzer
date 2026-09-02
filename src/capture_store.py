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

## 一天有两种形态，读取侧一律经 `_Day` 取数（260825 压实上线）

  {date}.jsonl    **热**：今天正在录的那天。格式与写盘路径一个字节都没改——
                  代理透明性优先级最高，压实再省也不许碰 `append()` 的同步段。
  {date}.pack/    **温**：已压实的过去某天。内容寻址去重 + 逐 blob zstd（见 pack.py），
                  实测 477MB → 17MB，且仍能按索引 off/len 随机取单条（中位 3.7ms）。

索引对两种形态一视同仁：`off/len` 指向**锚点文件**——jsonl 形态是主文件本身，pack 形态是
`skel.jsonl`。所以 `_load_index` 的「覆盖到哪了」判据从"主文件大小"推广成"锚点文件大小"，
回填逻辑也跟着分两路（pack 回填要先把 `$cas` 指针还原成完整记录再交给 classifier）。

**别再自己拼 `{date}.jsonl` 路径**。压实上线前全仓有六处各自拼路径，压实之后它们会各自
静默失效：文件不在了 → 当成空的一天 → 列表空白但没有任何东西报错（惯犯 bug ③ 的形状）。

## 三个存储根，语义各不相同

  captures/        本机录制（热 + 温）。retention 会自动删这里
  archives/        归档单文件 .ccwa（用户显式产出，**绝不自动删**）
  sources/<标签>/  从别的机器导入的录制。日期会与本机撞车（两台机器同一天都在录），
                   靠标签命名空间隔开；界面上必须一眼可辨是外来的
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import json
import logging
import queue
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path

import classifier
import config as CFG
import pack

log = logging.getLogger(__name__)

CAPTURES_DIR = CFG.CONFIG_DIR / "captures"
ARCHIVES_DIR = CFG.CONFIG_DIR / "archives"
SOURCES_DIR = CFG.CONFIG_DIR / "sources"

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

# kind 分类失败计数（260729）：列表/SSE 摘要按行现算 kind，失败降级 "other"——
# 降级本身没问题（列表照常出），但不能没人知道，见 _public_summary。
_KIND_ERRORS = 0


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


# 索引记录里不对外（列表/SSE 摘要）的内部字段：
# off/len 是 seek 锚点，v 是 schema 版本，其余是 DAG 分类原料（classifier 内部消费）。
# 新增分类原料字段时也要登记到这里，否则会漏进列表/SSE 摘要（契约是「列表项形状」）。
# ⚠️ session_id 虽是 lane 分组键（分类原料），但同时也是 agent 审计标识——能对上
# ~/.claude/projects/ 下的 jsonl 会话文件名。v0.4.6 的 session filter 场景里，审计方
# exclude_session 排除自己后，必须在结果里看到每条请求的归属，否则「能过滤、看不见」。
# 260802 从此移除，列表/SSE 摘要现在带 session_id（DAG lane 本就暴露，两处归一）。
# is_subagent/entrypoint/agent_fp 是真正的子代理判别位（身份指纹），仍归内部不暴露。
_IDX_PRIVATE = ("off", "len", "v", "sys_head", "first_user", "last_user",
                "tools_n", "uid", "task_prompts", "turn_start", "tool_uses",
                "is_subagent", "entrypoint", "agent_fp", "first_user_task")


def _public_summary(idx: dict) -> dict:
    """索引记录 → 列表/SSE 摘要（剥掉内部字段 + 补 kind）。

    kind 由 classifier.classify_idx(idx) 现算（idx 里有 path/sys_head/is_subagent/tools_n
    等判别原料）——让列表/SSE 一眼看出这条请求的角色，不必另查 DAG。

    分类失败降级成 "other" 但**要记日志**（260729）：分类原料字段一旦变动，
    整天的列表会静默全变 "other"，没人会怀疑。日志有界——本函数在列表路径上按行调用，
    真出问题是成片失败，首次必打、之后每 100 次一条，免得刷爆 run.log。"""
    global _KIND_ERRORS
    out = {k: v for k, v in idx.items() if k not in _IDX_PRIVATE}
    try:
        out["kind"] = classifier.classify_idx(idx)
    except Exception as e:
        out["kind"] = "other"
        _KIND_ERRORS += 1
        if _KIND_ERRORS == 1 or _KIND_ERRORS % 100 == 0:
            log.error("kind 分类失败（第 %d 次，该条降级为 other）: %s", _KIND_ERRORS, e)
    return out


def _idx_file(date: str) -> Path:
    """**热路径专用**：今天那天的索引文件。`append` 只写今天，今天永远是 jsonl 形态
    （压实不碰今天，见模块 docstring），所以这里不必判形态。
    其余一切读取走 `_Day(date, source).idx`。"""
    return CAPTURES_DIR / f"{date}.idx.jsonl"


def _source_root(source: str = "") -> Path:
    """录制根目录：空 = 本机 captures/，否则 sources/<标签>/（导入的外来录制）。"""
    if not source:
        return CAPTURES_DIR
    _validate_label(source)
    return SOURCES_DIR / source


class _Day:
    """一天录制的统一访问器：屏蔽 jsonl（热）/ pack（已压实）/ 分片（滚动压实中）三种形态。

    读取侧一律经它拿数据。三条不变量：
      1. **单 pack 与 jsonl 同时存在时以 pack 为准**——pack 只有在逐字节校验通过后才会就位，
         残留的 jsonl 是"删到一半"的垃圾，不是另一份事实。`stray_jsonl` 把它暴露出来给清理用。
      2. **不缓存打开的 PackReader**。Windows 上占着文件句柄会让删除/改名失败（本项目
         已经因为句柄占用踩过存档失败），而 map.json 解析实测只有毫秒级——用一点点重复
         解析换"任何时候都能删掉一天"，划算。
      3. **分片与尾巴 jsonl 是互补的两截，不是两份事实**（与 1 相反，别照搬）。
         滚动压实把已写完的前缀封存成 `{date}.pNN.pack`，`append` 继续往 `{date}.jsonl`
         写后面的记录。读一天 = 按序读完所有分片再读尾巴。

    ## 三种形态怎么区分（判断顺序有讲究）

        {date}.pack/         单 pack —— 历史天的终态，`compact_date` 或跨天合并的产出
        {date}.pNN.pack/     分片   —— **只可能出现在今天**，滚动压实的中间态
        {date}.jsonl         尾巴   —— 今天还在写的那一截；没有分片时它就是一整天

    单 pack 一旦存在就是权威（它是合并的产物，合并完分片就该删了），所以 `is_pack` 先判。
    """

    __slots__ = ("date", "source", "root", "jsonl", "pack_dir")

    def __init__(self, date: str, source: str = ""):
        self.date = date
        self.source = source
        self.root = _source_root(source)
        self.jsonl = self.root / f"{date}.jsonl"
        self.pack_dir = self.root / f"{date}{pack.PACK_SUFFIX}"

    # -- 形态 --
    @property
    def is_pack(self) -> bool:
        return pack.is_pack(self.pack_dir)

    @property
    def segments(self) -> list[Path]:
        """已封存的分片目录，按序号升序；没有分片则空列表。

        **不认后缀认结构**（`pack.is_pack` 而不是"名字像分片"）：切段被打断时可能留下
        一个半拉目录，把它当成一截录制读进来，就是拿残骸冒充事实。
        """
        if self.is_pack:
            return []      # 已合并成单 pack，分片就算还没删也不再是事实源
        pre = f"{self.date}.p"
        found = []
        for d in self.root.glob(f"{pre}*{pack.PACK_SUFFIX}"):
            n = d.name[len(pre):-len(pack.PACK_SUFFIX)]
            if n.isdigit() and pack.is_pack(d):
                found.append((int(n), d))
        return [d for _, d in sorted(found)]

    @property
    def is_segmented(self) -> bool:
        return bool(self.segments)

    @property
    def exists(self) -> bool:
        return self.is_pack or self.jsonl.exists() or self.is_segmented

    @property
    def stray_jsonl(self) -> Path | None:
        """单 pack 已就位却还留着的原 jsonl（压实收尾时被打断的残留）。

        **分片形态下永远返回 None**：那时的 jsonl 是还在写的尾巴，不是残留。
        把尾巴当残留清掉 = 删掉今天最新的一截录制。
        """
        return self.jsonl if (self.is_pack and self.jsonl.exists()) else None

    @property
    def idx(self) -> Path:
        """**尾巴/单 pack 的**索引文件。分片各自的索引在自己的 pack 目录内，走 `segments`。

        单 pack 形态放在 pack 目录内（且整体压缩）——一天自包含，删一天 = 删一个目录。
        """
        if self.is_pack:
            return pack.idx_path(self.pack_dir)
        return self.root / f"{self.date}.idx.jsonl"

    # -- 索引读写（两种形态的差异全部收在这三个方法里）--
    def idx_lines(self):
        """索引的原始行（bytes）。**两种形态都整体读进内存再按行切**，句柄不跨 yield 存活。

        jsonl 分支原先是 `with open(...) as fh: for raw in fh: yield raw`——生成器在 yield 处
        挂起时那个句柄还开着。消费方 `_read_idx_entries` 恰恰会在循环体内判到 schema 过期后
        调 `drop_idx()`，于是在 Windows 上**本进程自己占着这个文件，unlink 直接 WinError 32**：
        旧条目删不掉 → `_backfill_index` 是 append 写 → 下次读第一行仍是旧版本 → 再判过期 →
        每读一次追加一整天。实测本机 2026-09-01：196 条记录堆成 3,955 行、单条最重复 21 次、
        v15~v18 四代混在一个文件里，而读出来的数据一直是对的，所以没人发现（惯犯 ③ 的变种——
        异常没被吞，只是它的后果没有任何出口）。

        体量：索引一条 1~2KB，最大的一天 2,993 条 ≈ 5MB；而消费方本来就要把它们全 parse 成
        dict，峰值内存没有实质变化。**别为了省这点内存改回流式**——那等于把上面那个病放回来。
        更一般的一条：**任何跨 yield 持文件句柄的读取器，都会在 Windows 上挡住同一进程后续的
        删除/改名**（压实、归档、清理路径都有 unlink/rename）。
        """
        if self.is_pack:
            data = pack.read_idx_bytes(self.pack_dir)
        else:
            fi = self.idx
            if not fi.exists():
                return
            try:
                data = fi.read_bytes()
            except OSError as e:
                log.error("索引读失败 %s：%s", fi.name, e)
                return
        for raw in data.splitlines():
            if raw.strip():
                yield raw

    def drop_idx(self) -> None:
        """丢弃索引（schema 过期 / 主文件消失）。索引是缓存，丢了会重建。"""
        try:
            fi = self.idx
            if fi.exists():
                fi.unlink()
        except OSError as e:
            log.error("陈旧索引删除失败 %s：%s", self.date, e)

    def write_idx(self, entries: list[dict], append: bool = True) -> None:
        """写索引条目。jsonl 形态是追加（增量回填），pack 形态**只能整体覆盖**
        （冻结的一天没有追加语义，且它整体压缩存放）。"""
        blob = b"".join((json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8")
                        for e in entries)
        if self.is_pack:
            old = pack.read_idx_bytes(self.pack_dir) if append else b""
            pack.write_idx_bytes(self.pack_dir, old + blob)
            return
        with self.idx.open("ab" if append else "wb") as fh:
            fh.write(blob)

    # -- 尺寸与条数 --
    @property
    def tail_size(self) -> int:
        """**可增长的那一截**的锚点大小：单 pack 是 skel.jsonl，其余是尾巴 jsonl。

        与 `anchor_size` 的分工：这个用来判「索引覆盖到哪了」（只有尾巴会长，分片是冻结的），
        `anchor_size` 是整天的规模、给缓存键用。分片形态下两者必然不等，别互相顶替。
        """
        try:
            if self.is_pack:
                return (self.pack_dir / pack._SKEL).stat().st_size
            return self.jsonl.stat().st_size
        except OSError:
            return 0

    @property
    def anchor_size(self) -> int:
        """整天的锚点字节数（分片的 skel 之和 + 尾巴）。`/api/dag` 拿它当缓存键。

        切段会让这个数**变小**（N 字节的尾巴换成远小于 N 的 skel），所以它同样能当
        "这一天变了没有"的判据——不会出现切段前后巧合相等而缓存不失效的情况。
        """
        total = self.tail_size
        for seg in self.segments:
            try:
                total += (seg / pack._SKEL).stat().st_size
            except OSError:
                continue
        return total

    @property
    def anchor_fp(self) -> tuple:
        """索引缓存的失效指纹。分片数单列一维——只看字节数的话，
        「切段 + 尾巴又长回同样多」在理论上能撞上同一个数。"""
        return (len(self.segments), self.tail_size)

    def disk_bytes(self) -> int:
        """这一天在磁盘上真正占了多少（含索引与全部分片）。设置页算占用用。"""
        total = 0
        if self.is_pack:
            for f in self.pack_dir.rglob("*"):
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
            return total
        for seg in self.segments:
            for f in seg.rglob("*"):
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
        for f in (self.jsonl, self.idx):
            try:
                total += f.stat().st_size
            except OSError:
                continue
        return total

    def count(self) -> int:
        """记录条数。pack 读 manifest（不必数行），jsonl 只数行不 parse，分片两者相加。"""
        if self.is_pack:
            try:
                return int(pack.read_manifest(self.pack_dir).get("count") or 0)
            except pack.PackError:
                return 0
        n = 0
        for seg in self.segments:
            try:
                n += int(pack.read_manifest(seg).get("count") or 0)
            except pack.PackError as e:
                log.error("分片 manifest 读失败 %s：%s", seg.name, e)
        return n + _count_lines(self.jsonl)

    def segment_entries(self) -> list[dict]:
        """所有分片的索引条目，按分片序拼好并贴上 `seg` 标签。

        分片的索引是**切段时连同逐字节校验一起建好的**（见 `_seal_tail`），且分片此后冻结，
        所以这里只读不回填——回填只针对还会长的尾巴。schema 过期的分片就地重建一次：
        不重建的话，新字段在这一截上恒缺失、判别逻辑静默退化成回落分支，而这一天的
        前半截和后半截会给出不一样的结论。
        """
        out: list[dict] = []
        for i, seg in enumerate(self.segments, 1):
            try:
                rows = _seg_idx_rows(seg)
            except pack.PackError as e:
                log.error("分片索引读失败 %s：%s", seg.name, e)
                continue
            for e in rows:
                e["seg"] = i
                out.append(e)
        return out

    def manifest(self) -> dict | None:
        """单 pack 的名片。**分片形态返回 None**——一天有 N 张名片时"这一天是谁打的包"
        没有单一答案，与其挑一张糊弄，不如让调用方看见这天还没合并。"""
        if not self.is_pack:
            return None
        try:
            return pack.read_manifest(self.pack_dir)
        except pack.PackError as e:
            log.error("pack manifest 读失败 %s: %s", self.pack_dir.name, e)
            return None

    # -- 取数 --
    def _anchor_of(self, seg: int | None) -> Path | None:
        """索引条目的 seg 标签 → 它的锚点所在（pack 目录），尾巴则 None。

        seg 是**读取时贴的标签，不进索引文件**：分片内的索引与普通 pack 的索引逐字节同构，
        所以分片可以原样拿去合并/归档，`IDX_SCHEMA` 也不用为分片 bump 一版。
        """
        if not seg:
            return self.pack_dir if self.is_pack else None
        segs = self.segments
        return segs[seg - 1] if 1 <= seg <= len(segs) else None

    def record_at(self, off: int, ln: int, seg: int | None = None) -> dict | None:
        """按锚点的 off/len 取一条完整记录（索引就是这么喂的）。

        `seg` 来自索引条目：给了就去那个分片里取，没给就是尾巴（或单 pack）。
        **分片形态下 seg 缺失不能当成"去第一个分片找"**——那会拿错记录且不报错。
        """
        pd = self._anchor_of(seg)
        if pd is not None:
            try:
                with pack.PackReader(pd) as r:
                    return r.record_at(off, ln)
            except pack.PackError as e:
                log.error("pack 取记录失败 %s@%s: %s", self.date, off, e)
                return None
        if seg:
            return None        # 索引说在第 N 个分片，而那个分片已经不在了
        try:
            with self.jsonl.open("rb") as fh:
                fh.seek(off)
                return json.loads(fh.read(ln))
        except (OSError, json.JSONDecodeError):
            return None

    def find_by_id(self, rid: str) -> dict | None:
        """索引缺行时的兜底扫描。子串预筛后才 parse（不逐行全量 parse）。"""
        for pd in ([self.pack_dir] if self.is_pack else self.segments):
            try:
                with pack.PackReader(pd) as r:
                    hit = r.find_by_id(rid)
                    if hit is not None:
                        return hit
            except pack.PackError as e:
                log.error("pack 扫描失败 %s: %s", pd.name, e)
        if self.is_pack or not self.jsonl.exists():
            return None
        needle = f'"{rid}"'.encode("utf-8")
        try:
            with self.jsonl.open("rb") as fh:
                for raw in fh:
                    if needle not in raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("id") == rid:
                        return rec
        except OSError:
            return None
        return None

    def iter_records(self):
        """按录制顺序遍历完整记录（坏行跳过——三种形态行为一致）。

        分片形态：**先按序读完所有分片，再读尾巴**。顺序错了，DAG 的时序就是错的，
        而且不会有任何东西报错。
        """
        for pd in ([self.pack_dir] if self.is_pack else self.segments):
            try:
                with pack.PackReader(pd) as r:
                    yield from r.iter_records()
            except pack.PackError as e:
                log.error("pack 遍历失败 %s: %s", pd.name, e)
        if self.is_pack or not self.jsonl.exists():
            return
        with self.jsonl.open("rb") as fh:
            for raw in fh:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue

    def iter_indexable(self, start: int = 0):
        """回填索引用：从锚点文件 `start` 字节处续读，产出 (off, len, record | None)。

        **坏行也要产出（record=None）**，只是不建索引条目——调用方据此推进"覆盖到哪了"。
        原实现在这里踩过：坏行若不推进偏移，每次读取都会对同一行重复回填一次。
        """
        if self.is_pack:
            try:
                with pack.PackReader(self.pack_dir) as r:
                    for off, ln in r.lines:
                        if off < start:
                            continue
                        yield off, ln, r.record_at(off, ln)
            except pack.PackError as e:
                log.error("pack 回填失败 %s: %s", self.date, e)
            return
        if not self.jsonl.exists():
            return
        with self.jsonl.open("rb") as fh:
            fh.seek(start)
            data = fh.read()
        lines = data.split(b"\n")
        lines.pop()                 # 末段：以 \n 结尾时是 b""，否则是没写完的半行
        off = start
        for raw in lines:
            ln = len(raw) + 1       # +1 是被 split 吃掉的 \n
            rec = None
            if raw.strip():
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    rec = None      # 崩溃残留/合并坏行：不建条目但仍推进偏移
            yield off, ln, rec
            off += ln


# (source, date) → (covered_end, entries)：covered_end = 索引已覆盖到的**锚点文件**字节位置
# （jsonl 形态是主文件，pack 形态是 skel.jsonl）。锚点 size 不变直接命中缓存
# （/api/dag 被 LIVE 防抖反复调用时近乎零成本）。
# 键带 source 是因为外来录制的日期会与本机撞车（两台机器同一天都在录）——
# 只用 date 当键，切到导入来源的同一天会读到本机的缓存，而且**不会有任何东西报错**。
_IDX_CACHE: dict[tuple[str, str], tuple[int, list[dict]]] = {}


# 滚动压实的开关与阈值（260831）。**不在热路径读配置文件**——`append` 每条记录都要判一次，
# 每条都去 open 一次 config.json 就是把一次磁盘 IO 塞进了转发路径，而代理透明性是第一优先级。
# 由 app 在启动时和配置变更时调 `set_rolling()` 推进来，热路径只读两个模块级变量。
_ROLL_ON = False
_ROLL_BYTES = 200 * 1024 * 1024
_SEAL_LOCK = threading.Lock()
_SEALING_NOW = False


def set_rolling(enabled: bool, mb: int = 200) -> None:
    """设置滚动压实开关与切段阈值（MB）。夹取与 config 侧同口径，两边都夹是有意的：
    配置文件可能被手改坏，而这里是最后一道——阈值为 0 会让每条记录都触发切段。"""
    global _ROLL_ON, _ROLL_BYTES
    _ROLL_ON = bool(enabled)
    try:
        m = int(mb)
    except (TypeError, ValueError):
        m = 200
    _ROLL_BYTES = max(20, min(2000, m)) * 1024 * 1024


def _maybe_seal(date: str, size: int) -> None:
    """尾巴过阈值就切一段。**判断在热路径、执行在后台线程**：
    一截 200MB 要压好几秒，让某一条请求的落盘背上这几秒是不可接受的。

    同时只允许一个切段在跑（`_SEALING_NOW`）：切段期间尾巴仍在长，第二个切段会
    对着同一个尾巴再改一次名，两个 staging 争同一个分片号。
    """
    global _SEALING_NOW
    if not _ROLL_ON or size < _ROLL_BYTES or _SEALING_NOW:
        return
    with _SEAL_LOCK:
        if _SEALING_NOW:
            return
        _SEALING_NOW = True

    def _run():
        global _SEALING_NOW
        try:
            seal_tail(date)
        except Exception as e:
            # 切段失败不影响录制（seal_tail 内部保证要么成功要么还原），但要留下痕迹
            log.error("滚动压实失败（录制未受影响）：%s", e)
        finally:
            _SEALING_NOW = False

    threading.Thread(target=_run, daemon=True, name="rolling-compact").start()


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
    tail_size = 0
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
            tail_size = off + len(data)   # 滚动压实的判据，锁内取（锁外 stat 会读到别人刚写的）
            # 主写成功才写索引（off/len 才有意义）。索引 = classifier.index_record + 字节偏移
            try:
                idx_entry = classifier.index_record(record)
                idx_entry["off"] = off
                idx_entry["len"] = len(data)
                with _idx_file(date).open("ab") as fh:
                    fh.write((json.dumps(idx_entry, ensure_ascii=False) + "\n").encode("utf-8"))
                cached = _IDX_CACHE.get(("", date))
                if cached:
                    cached[1].append(idx_entry)
                    # 指纹的分片维原样带过：切段会把整条缓存 pop 掉，
                    # 所以能走到这里就说明分片数没变，不必为每条记录去 glob 一次目录。
                    _IDX_CACHE[("", date)] = ((cached[0][0], off + len(data)), cached[1])
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
    if tail_size:
        _maybe_seal(date, tail_size)    # 锁外触发：切段自己会拿锁，在锁内叫等于自锁
    _LIVE_DEQUE.append(summ)
    with _SUB_LOCK:
        for q in list(_LIVE_SUBSCRIBERS):
            try:
                q.put(summ, block=False)
            except queue.Full:
                pass  # LIVE 不保证可靠，满则丢
            except Exception:
                _LIVE_SUBSCRIBERS.discard(q)


def _seg_idx_rows(seg: Path) -> list[dict]:
    """一个分片的索引条目。schema 过期就地重建一次（分片冻结，重建结果可以一直用）。"""
    rows: list[dict] = []
    stale = False
    for raw in pack.read_idx_bytes(seg).splitlines():
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if e.get("v") != classifier.IDX_SCHEMA:
            stale = True
            break
        rows.append(e)
    if not stale and rows:
        return rows
    log.info("分片索引重建 %s（schema 过期或为空）", seg.name)
    rows = []
    with pack.PackReader(seg) as r:
        for off, ln in r.lines:
            rec = r.record_at(off, ln)
            if rec is None:
                continue
            try:
                e = classifier.index_record(rec)
            except Exception as err:
                log.error("分片建索引失败 %s@%s：%s", seg.name, off, err)
                continue
            e["off"], e["len"] = off, ln
            rows.append(e)
    try:
        pack.write_idx_bytes(seg, b"".join(
            (json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8") for e in rows))
    except (OSError, pack.PackError) as e:
        log.error("分片索引写回失败 %s（下次读还会重建）：%s", seg.name, e)
    return rows


def _read_idx_entries(day: "_Day") -> tuple[list[dict], int]:
    """读索引全部有效条目，返回 (entries, covered_end)。
    崩溃残留的半行跳过（条目自带 off/len，covered_end 只认完整条目）。

    **schema 版本不符 → 整个索引作废**（返回空 + covered=0，调用方会从 0 全量回填）。
    只校验 off/len 是不够的：`classifier.index_record` 的字段集一变（260725 加了
    is_subagent/session_id 等身份字段），旧索引仍然"结构有效"，于是新字段在老录制上
    恒缺失、判别逻辑静默退化成回落分支，**没有任何东西会报错**——CLAUDE.md 教训②
    「键名错位」的同型。宁可多花一次回填（826MB 天约 5s，有日志）也不要静默错。"""
    entries: list[dict] = []
    covered = 0
    for raw in day.idx_lines():
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if e.get("v") != classifier.IDX_SCHEMA:
            log.info("索引 schema 过期（%s: v=%r，当前 v=%d）→ 整体重建",
                     day.idx.name, e.get("v"), classifier.IDX_SCHEMA)
            # 必须先丢掉旧索引再让调用方从 0 回填：jsonl 形态的回填是 append 写，
            # 不丢的话旧条目留在文件里，下次读又判过期 → 每次读都重复回填一整天。
            day.drop_idx()
            return [], 0
        off, ln = e.get("off"), e.get("len")
        if isinstance(off, int) and isinstance(ln, int):
            covered = max(covered, off + ln)
        entries.append(e)
    return entries, covered


def _backfill_index(day: "_Day", start: int) -> tuple[list[dict], int]:
    """从锚点文件 start 字节处续读，为完整记录建索引并追加进 idx 文件（增量回填自愈）。

    触发场景：旧录制没有索引 / 索引写失败落下几条 / 崩溃后索引落后 / 压实后索引作废。
    返回 (新条目, 新的 covered_end)。两种形态同一套逻辑，差异全部收在 `_Day.iter_indexable`
    里——260825 压实上线时这里若各写一份，pack 天的回填迟早与 jsonl 天分叉。"""
    new_entries: list[dict] = []
    end = start
    for off, ln, rec in day.iter_indexable(start):
        if rec is not None:
            e = classifier.index_record(rec)
            e["off"] = off
            e["len"] = ln
            new_entries.append(e)
        end = max(end, off + ln)
    if new_entries:
        day.write_idx(new_entries, append=True)
    return new_entries, end


def _load_index(date: str, source: str = "") -> list[dict]:
    """读指定日期索引（缓存 + 按需增量回填）。**调用方须持 _LOCK**。"""
    day = _Day(date, source)
    key = (source, date)
    if not day.exists:
        day.drop_idx()              # 主文件被外部删了 → 陈旧索引一并清
        _IDX_CACHE.pop(key, None)
        return []
    fp = day.anchor_fp
    cached = _IDX_CACHE.get(key)
    if cached and cached[0] == fp:
        return cached[1]
    # 分片在前、尾巴在后——这个顺序就是录制顺序，反了整天的时序都是错的。
    seg_entries = day.segment_entries()
    entries, covered = _read_idx_entries(day)
    tail = day.tail_size
    if covered < tail:
        try:
            new_entries, covered = _backfill_index(day, covered)
            entries.extend(new_entries)
            if new_entries:
                log.info("索引回填 %s%s：补 %d 条",
                         f"{source}/" if source else "", date, len(new_entries))
        except Exception as e:
            # 回填失败不致命：返回已有部分（可能不全），下次读取再试
            log.error("索引回填失败 %s: %s", date, e)
    entries = seg_entries + entries
    _IDX_CACHE[key] = (fp, entries)
    return entries


def _session_filter(entries: list[dict], exclude_session: str = "",
                    session: str = "") -> list[dict]:
    """按会话 id 筛索引记录。前缀匹配（给完整 id 或前 8 位都行）。

    存在的理由是「一个 CC 干活、另一个 CC 录制审计」这个场景：审计方自己也在被录，
    每查一次 API 就产生新的请求进同一份录制，不排除的话结果里全是自己、而且越查越多
    （自我污染是递增的）。审计方的 session id 在它自己的 scratchpad 路径里就有。"""
    if exclude_session:
        entries = [e for e in entries
                   if not (e.get("session_id") or "").startswith(exclude_session)]
    if session:
        entries = [e for e in entries
                   if (e.get("session_id") or "").startswith(session)]
    return entries


def list_index(date: str | None = None, exclude_session: str = "",
               session: str = "", source: str = "") -> list[dict]:
    """指定日期的全部索引记录（DAG 构建用）。无 1000 条上限——260719 前 list_full
    写死 limit=1000，大流量天（实测 2993 条）泳道图直接丢后 2/3。"""
    # `not date` 而不是 `date is None`：**空串也要当成"没给"**。
    # 260825 撞到——前端把 `?date=` 空着传上来，空串不是 None 于是被当成一个真日期，
    # 结果是"今天有 14 条但界面显示 0 条"，而 API 本身一切正常、没有任何报错。
    if not date:
        date = time.strftime("%Y-%m-%d", time.localtime())
    with _LOCK:
        entries = list(_load_index(date, source))
    return _session_filter(entries, exclude_session, session)


def list_captures(date: str | None = None, limit: int = 200, offset: int = 0,
                  exclude_session: str = "", session: str = "", source: str = "") -> dict:
    """读指定日期索引，倒序分页返回摘要列表。
    260719 改读索引前：每次 readlines 整个主文件 + parse 倒序头 N 行（恰是最大的行），
    826MB 录制实测峰值内存 3.3GB。"""
    # `not date` 而不是 `date is None`：**空串也要当成"没给"**。
    # 260825 撞到——前端把 `?date=` 空着传上来，空串不是 None 于是被当成一个真日期，
    # 结果是"今天有 14 条但界面显示 0 条"，而 API 本身一切正常、没有任何报错。
    if not date:
        date = time.strftime("%Y-%m-%d", time.localtime())
    # 过滤必须在 total 之前——total 是分页依据，若算的是过滤前的数量，翻页会翻出空页。
    entries = list_index(date, exclude_session, session, source)
    total = len(entries)
    items = [_public_summary(e) for e in entries[::-1][offset:offset + limit]]
    return {
        "date": date,
        "source": source,
        "total": total,
        "items": items,
        "dates_available": _available_dates(source),
    }


def iter_records(date: str | None = None, source: str = ""):
    """按录制顺序流式遍历某天的完整记录（两种形态透明）。

    公开出来是给 CLI 与 dev 工具用的——**它们过去各自 `open(f"{date}.jsonl")`**，
    压实之后那种写法会安静地读到空。要遍历录制就用这个，别自己拼路径。"""
    # `not date` 而不是 `date is None`：**空串也要当成"没给"**。
    # 260825 撞到——前端把 `?date=` 空着传上来，空串不是 None 于是被当成一个真日期，
    # 结果是"今天有 14 条但界面显示 0 条"，而 API 本身一切正常、没有任何报错。
    if not date:
        date = time.strftime("%Y-%m-%d", time.localtime())
    yield from _Day(date, source).iter_records()


def list_full(date: str | None = None, limit: int = 100000, source: str = "") -> list[dict]:
    """读指定日期全量**完整** records（含 body，MB 级/条，大流量天 parse 要秒级）。
    仅供 tools/lane_probe.py 等需要 body 内部细节的 dev 工具；热路径一律走 list_index。"""
    # `not date` 而不是 `date is None`：**空串也要当成"没给"**。
    # 260825 撞到——前端把 `?date=` 空着传上来，空串不是 None 于是被当成一个真日期，
    # 结果是"今天有 14 条但界面显示 0 条"，而 API 本身一切正常、没有任何报错。
    if not date:
        date = time.strftime("%Y-%m-%d", time.localtime())
    out = []
    with _LOCK:
        for rec in _Day(date, source).iter_records():
            out.append(rec)
            if len(out) >= limit:
                break
    return out


# ===== 内容搜索 / 统计（260802：从 cli 抽出作单一真源，HTTP 与 CLI 共用）=====
# 此前 grep/stats 逻辑只在 cli.py，HTTP 端没有——AI 搜内容/算 token 被迫直读 jsonl，
# 违反 ai-guide「别整文件读录制」。抽到数据层后 /api/grep、/api/stats 与 cli 同源，
# 不再有 CLI/HTTP 各抄一份的分叉（stats cache_creation 漏字段事故的根因）。
_GREP_AREAS = ("system", "user", "assistant", "sysmsg", "tool_result", "tool_use", "tools")
_GREP_ALL = ("system", "user", "assistant", "sysmsg", "tool_result", "tool_use")


def _grep_fields(rec: dict, body: dict, areas: tuple) -> dict:
    """按区域抽取可搜文本。键 = where 标签，值 = 该区域全部文本拼接。"""
    out = {}
    if "system" in areas:
        out["system"] = classifier._system_text(body)
    if "user" in areas:
        out["user"] = "\n".join(classifier._user_texts(body))
    if "assistant" in areas:
        out["assistant"] = "\n".join(
            b.get("text") or "" for b in ((rec.get("response") or {}).get("content_blocks") or [])
            if b.get("type") == "text")
    if "tools" in areas:
        out["tools"] = json.dumps(body.get("tools") or [], ensure_ascii=False)
    # 下面三块都藏在 messages 里，是 _system_text/_user_texts 覆盖不到的部分：
    # role=system 的 mid-conversation 消息（skill 清单、注入提醒）、工具返回、工具调用参数。
    # tool_use 区域含**工具名**，且同时覆盖请求侧历史与响应侧当轮（260801 踩出来：只收 input
    # 搜工具名恒 0；只收 messages 历史时当轮调用搜不到）。
    sysmsg, tres, tuse = [], [], []
    for blk in ((rec.get("response") or {}).get("content_blocks") or []):
        if isinstance(blk, dict) and blk.get("type") == "tool_use":
            tuse.append((blk.get("name") or "") + " " +
                        json.dumps(blk.get("input") or {}, ensure_ascii=False))
    for m in body.get("messages") or []:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            sysmsg.append(content if isinstance(content, str)
                          else classifier._text_of_content(content))
            continue
        for blk in (content if isinstance(content, list) else []):
            if not isinstance(blk, dict):
                continue
            t = blk.get("type")
            if t == "tool_result":
                c = blk.get("content")
                tres.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
            elif t == "tool_use":
                tuse.append((blk.get("name") or "") + " " +
                            json.dumps(blk.get("input") or {}, ensure_ascii=False))
    if "sysmsg" in areas:
        out["sysmsg"] = "\n".join(sysmsg)
    if "tool_result" in areas:
        out["tool_result"] = "\n".join(tres)
    if "tool_use" in areas:
        out["tool_use"] = "\n".join(tuse)
    return out


def grep(date: str | None = None, pattern: str = "", in_: str = "all",
         limit: int = 50, case: bool = False, fixed: bool = False,
         exclude_session: str = "", session: str = "", source: str = "") -> dict:
    """在指定日期录制里搜文本。返回结构同 cli cmd_grep（不含 date；HTTP 路由自行包装）。

    命中撞 limit 提前 break 时，两个字符计数只覆盖扫过的那部分记录——此时给比例会偏，
    不如不给。扫完全部（hits < limit，含 0 命中这个最要紧的情形）才报 skipped_ratio。

    会话过滤只能逐条现算（这里读的是主文件，不是索引），用 classifier._session_id ——
    与索引里 session_id 的取法是同一个函数，两边不会分叉。"""
    import re
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    flags = 0 if case else re.IGNORECASE
    try:
        pat = re.compile(re.escape(pattern) if fixed else pattern, flags)
    except re.error as e:
        return {"ok": False, "error": "bad_pattern", "message": f"正则错误：{e}"}
    areas = _GREP_ALL if in_ == "all" else (in_,)
    skipped = [x for x in _GREP_AREAS if x not in areas]
    hits = []
    searched_chars = skipped_chars = 0
    # 走 _Day 而不是自己开主文件：压实后的天没有主文件，自己拼路径 = 整天搜不到且不报错。
    for rec in _Day(date, source).iter_records():
        body = (rec.get("request") or {}).get("body") or {}
        if not isinstance(body, dict):
            body = {}
        if exclude_session or session:
            sid = classifier._session_id(rec, body)
            if exclude_session and sid.startswith(exclude_session):
                continue
            if session and not sid.startswith(session):
                continue
        fields = _grep_fields(rec, body, areas)
        searched_chars += sum(len(v or "") for v in fields.values())
        skipped_chars += sum(len(v or "") for v in _grep_fields(rec, body, tuple(skipped)).values())
        for where, text in fields.items():
            m = pat.search(text or "")
            if not m:
                continue
            s = max(0, m.start() - 50)
            hits.append({
                "id": rec.get("id"), "ts_start": rec.get("ts_start"),
                "kind": classifier.classify(rec), "where": where,
                "snippet": (text[s:m.end() + 50]).replace("\n", " "),
                "match_count": len(pat.findall(text or "")),
            })
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    scanned_all = len(hits) < limit
    total = searched_chars + skipped_chars
    ratio = round(skipped_chars / total, 4) if (scanned_all and total) else None
    coverage = {"searched": list(areas), "skipped": skipped, "skipped_ratio": ratio}
    if not hits:
        coverage["note"] = (
            "0 命中 ≠ 不存在：本次未搜索的区域" +
            (f"占请求体 {ratio:.1%}" if ratio is not None else "未统计") +
            ("；用 --in <区域> 搜它们" if skipped else "")
        )
    return {"ok": True, "pattern": pattern, "in": in_, "hits": len(hits), "items": hits,
            "coverage": coverage,
            "note": "只回片段；要看全文用 get <id> --part system|messages"}


def stats(date: str | None = None, exclude_session: str = "",
          session: str = "", source: str = "") -> dict:
    """指定日期的请求 / token / 耗时统计。返回结构同 cli cmd_stats（含 date）。

    cache_creation 必须累加：它按 token 数只占几个百分点，按**成本**却可能占三到四成
    （缓存写入单价是读取的 12.5~20 倍）。漏掉它，用 stats 做成本判断会系统性低估，
    且低估的正是「上下文被反复重建」这个最该优化的信号（260801）。

    **走索引不走主文件**（260802）：它要的字段（model/status/usage/total_ms/has_error/kind）
    全在索引里。原先逐行 parse 主文件、且每条调 classify(完整 record) —— 那等于把整条
    index_record 重算一遍（含拿 ~108K 规则库去匹配安全审查形状），826MB 的天要 ~9s，
    而索引 ~50ms（260719 索引改造的原始实测）。顺带拿到会话过滤：v0.4.6 承诺"所有检查面
    都能按会话过滤"，stats 当时因为读主文件而落在承诺之外。"""
    from collections import Counter
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    kinds, models, statuses = Counter(), Counter(), Counter()
    tin = tout = tcache = tcreate = 0
    durs = []
    errors = 0
    day = _Day(date, source)
    entries = list_index(date, exclude_session, session, source)
    n = len(entries)
    for e in entries:
        kinds[classifier.classify_idx(e)] += 1
        models[e.get("model") or "?"] += 1
        statuses[str(e.get("status"))] += 1
        u = e.get("usage") or {}
        tin += (u.get("input") or 0)
        tout += (u.get("output") or 0)
        tcache += (u.get("cache_read") or 0)
        tcreate += (u.get("cache_creation") or 0)
        if e.get("total_ms"):
            durs.append(e["total_ms"])
        if e.get("has_error"):
            errors += 1
    durs.sort()

    def pct(p):
        return durs[min(int(len(durs) * p), len(durs) - 1)] if durs else None

    # cache_hit_ratio：读 /（读+写）。分母 0 给 None 而非 0——「没有缓存」≠「命中率 0%」。
    # 不做美元换算：单价随模型/链路/TTL 变，硬编码必然腐化；给全 token 数，换算交给使用者。
    cache_total = tcache + tcreate
    # file_size = 这一天在磁盘上真正占多少。压实后它会变小——这不是"数字对不上"，
    # 而是事实变了；`packed`/`raw_bytes` 把变化讲清楚，免得使用者以为录制少了。
    return {"ok": True, "date": date, "records": n,
            "file_size": day.disk_bytes(),
            "packed": day.is_pack,
            "raw_bytes": ((day.manifest() or {}).get("raw_bytes") if day.is_pack else None),
            "kinds": dict(kinds), "models": dict(models), "statuses": dict(statuses),
            "errors": errors,
            "tokens": {"input": tin, "output": tout,
                       "cache_read": tcache, "cache_creation": tcreate},
            "cache_hit_ratio": (round(tcache / cache_total, 4) if cache_total else None),
            "total_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": (durs[-1] if durs else None)}}


UNK_BETA_LIFT_MIN = 1.5      # beta 关联的提升度门槛（低于它就不是"来源"，是基线噪声）


def unknowns(date: str | None = None, exclude_session: str = "",
             session: str = "", source: str = "") -> dict:
    """盲区雷达（260802）：聚合当天索引里所有「已知集合外」的值，给 AI 当协议演进 / 录制
    盲区的改进线索。读 idx（unknowns 已在写时算好，schema≥14），不读主文件——比 stats 快。

    每个维度返回 [{value, count, samples[≤5 id], snippet, betas, hosts, cc_versions}]：
      - snippet：该未知值的内容片段，AI 不必二次调 /api/captures/{id} 就能判断；
      - hosts / cc_versions：该未知值出现在哪些上游 host、哪些 CC 版本上。**判读第一步**——
        单一第三方 host 独占 = 网关的形状差异，不是 CC 协议演进（实测 08-02 全部 5 条未知
        都来自同一个第三方网关，而端点当时只说"协议演进"，照着提示走会把网关差异并进 KNOWN_*，
        之后官方链路真出问题时雷达就哑了）；
      - betas：与该未知**特异相关**的 beta 特性（提升度 ≥ UNK_BETA_LIFT_MIN），空 = 没有显著
        关联。裸计数做不到这件事：单次出现的未知值所有 beta 都并列 1，most_common 退化成
        "取 header 里的前几个"；高频未知值则被基线 100% 的那几个 beta 支配。两种情形都指不到
        "引入这个字段的那个能力"，所以这里算 P(beta|该未知)/P(beta|全体)。

    betas 维度分 new / known 两段：new = 不在 classifier.KNOWN_BETAS 里的，才是真信号。
    此前按频次升序、宣称"长尾即信号"，实测每天把同样几个结构性低频的已知特性顶在最前
    （structured-outputs 只在标题请求带、token-counting 只在 count_tokens 探针带）。"""
    from collections import Counter, defaultdict
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    SAMPLE_MAX = 5
    blocks, block_keys, body_fields, degraded = Counter(), Counter(), Counter(), Counter()
    stop_reasons, thinking_types, betas = Counter(), Counter(), Counter()
    mainline_suspect = Counter()        # 主线可疑（260901，见 classifier.mainline_doubt）
    samples = defaultdict(list)
    snippets = {}                       # dim:value -> 内容片段（首次见到的作样例）
    beta_assoc = defaultdict(Counter)   # dim:value -> 该值出现的请求的 beta Counter
    host_assoc = defaultdict(Counter)   # dim:value -> 上游 host Counter
    ccver_assoc = defaultdict(Counter)  # dim:value -> CC 版本 Counter
    other_ids = []
    records = with_unknowns = degraded_records = 0

    def _tally(dim: str, val: str, snip: str, r: dict) -> None:
        """记一个未知值：样本 id + 首次片段 + beta/host/版本关联（计数在调用处）。"""
        key = dim + ":" + val
        lst = samples[key]
        if len(lst) < SAMPLE_MAX:
            lst.append(r.get("id"))
        snippets.setdefault(key, snip)
        bc = beta_assoc[key]
        for b in (r.get("beta") or []):
            bc[b] += 1
        if r.get("host"):
            host_assoc[key][r["host"]] += 1
        if r.get("cc_version"):
            ccver_assoc[key][r["cc_version"]] += 1

    for r in list_index(date, exclude_session, session):
        records += 1
        u = r.get("unknowns") or {}
        # degraded 是本工具自己的降级标记，不算"协议未知"——分开计数，否则
        # with_unknowns 会被自己的噪声撑起来（实测 07-29 全天 3 条未知全是它）。
        real_unknown = {k: v for k, v in u.items() if k != "degraded"}
        if real_unknown:
            with_unknowns += 1
        if u.get("degraded"):
            degraded_records += 1
        for dim, counter in (("blocks", blocks), ("block_keys", block_keys),
                             ("body_fields", body_fields), ("degraded", degraded)):
            for val, snip in (u.get(dim) or {}).items():   # value→snippet dict（schema v12+）
                counter[val] += 1
                _tally(dim, val, snip, r)
        for dim, counter in (("stop_reason", stop_reasons), ("thinking_type", thinking_types)):
            val = u.get(dim)                                # 标量单值
            if val:
                counter[val] += 1
                _tally(dim, val, val, r)
        for b in (r.get("beta") or []):
            betas[b] += 1
        kind = classifier.classify_idx(r)
        if kind == "other":
            other_ids.append(r.get("id"))
        # 主线可疑（260901）：判成主线但缺主线的结构特征。**在这里算而不是写时算**——
        # 它由 kind + tools_n 两个已有字段现推，不需要新索引字段，因此**不必 bump IDX_SCHEMA**，
        # 老录制不用重建就能进雷达。判据本身在 classifier.mainline_doubt（单份）。
        doubt = classifier.mainline_doubt(r, kind)
        if doubt:
            mainline_suspect[doubt] += 1
            _tally("mainline_suspect", doubt,
                   classifier._snippet(r.get("sys_head") or r.get("last_user") or ""), r)

    def _lift_betas(key: str, group_n: int) -> list:
        """与该未知特异相关的 beta：提升度 = 组内出现率 / 全体基线出现率。"""
        if not records or not group_n:
            return []
        out = []
        for b, n in beta_assoc[key].items():
            base = betas.get(b, 0) / records
            if not base:
                continue
            lift = (n / group_n) / base
            if lift >= UNK_BETA_LIFT_MIN:
                out.append({"value": b, "lift": round(lift, 1)})
        return sorted(out, key=lambda x: -x["lift"])[:5]

    def _agg(counter: Counter, dim: str) -> list:
        out = []
        for v, n in counter.most_common():
            key = dim + ":" + v
            out.append({"value": v, "count": n,
                        "samples": samples[key][:SAMPLE_MAX],
                        "snippet": snippets.get(key, ""),
                        "betas": _lift_betas(key, n),
                        "hosts": dict(host_assoc[key].most_common()),
                        "cc_versions": dict(ccver_assoc[key].most_common())})
        return out

    def _beta_rows(known: bool) -> list:
        rows = [{"value": v, "count": n} for v, n in betas.items()
                if (v in classifier.KNOWN_BETAS) == known]
        return sorted(rows, key=lambda x: x["count"])

    return {
        "ok": True, "date": date,
        "totals": {"records": records, "with_unknowns": with_unknowns,
                   "degraded": degraded_records, "other_kind": len(other_ids)},
        "blocks": _agg(blocks, "blocks"),
        "block_keys": _agg(block_keys, "block_keys"),
        "body_fields": _agg(body_fields, "body_fields"),
        "stop_reason": _agg(stop_reasons, "stop_reason"),
        "thinking_type": _agg(thinking_types, "thinking_type"),
        # 本工具自己的降级（SSE 截断 / 工具入参拼不出 JSON）——不是协议未知，单列。
        "degraded": _agg(degraded, "degraded"),
        # 主线可疑（260901）：性质是第三种——既不是"上游给了不认识的东西"，也不是本工具降级，
        # 而是**我们自己的分类可能判错了**。留在雷达而不是改判：wire 上没有"是不是主线"的官方位，
        # 精确真值在 CC 本地 jsonl（不过 wire），只在开发期用。
        "mainline_suspect": _agg(mainline_suspect, "mainline_suspect"),
        # new = 不在基线里的 beta（真信号）；known = 已收录的（看用量分布用）。
        # 均按频次升序；不取 samples——高频特性上千条无意义，查具体特性用 grep <beta-name>。
        "betas": {"new": _beta_rows(False), "known": _beta_rows(True)},
        "other_kind_samples": other_ids[:SAMPLE_MAX],
        "known": {
            "block_types": sorted(classifier.KNOWN_BLOCK_TYPES),
            "block_keys": {k: sorted(v) for k, v in classifier.KNOWN_BLOCK_KEYS.items()},
            "body_fields": sorted(classifier.KNOWN_BODY_FIELDS),
            "stop_reasons": sorted(classifier.KNOWN_STOP_REASONS),
            "thinking_types": sorted(classifier.KNOWN_THINKING_TYPES),
            "betas": sorted(classifier.KNOWN_BETAS),
            "mainline_doubt_reasons": classifier.MAINLINE_DOUBT_REASONS,
        },
        "note": ("已知集合（见 known）外的值 = 协议演进 / 录制盲区信号。**判读顺序**："
                 "① 先看 hosts——单一第三方 host 独占 = 那个网关的形状差异，不是 CC 协议演进，"
                 "并入 KNOWN_* 会让官方链路的同名异构块从此哑掉；② betas 是提升度筛过的特异关联，"
                 "空表示没有显著来源；③ 取 samples id 调 /api/captures/{id} 看完整上下文。"
                 "degraded 段性质不同——那是本工具录制降级（SSE 截断 / 入参拼不出 JSON），"
                 "要查的是代理侧不是上游。确认是标准字段的未知并入 KNOWN_* + bump IDX_SCHEMA。"
                 " **mainline_suspect 段是第三种性质**：不是上游给了怪东西，是**我们自己可能把"
                 "辅助调用判成了主线**。判主线在 wire 上没有官方位——CC 自己的答案在它本地的"
                 "对话记录里（标题写成独立的 ai-title 行，安全审查/压缩/配额探测一条都不写进"
                 "对话），而那份记录不过 wire，只在开发期可用。所以这里只报可疑、不改判；"
                 "要精确结论跑 tools/origin_probe.py --mode belong 做 request-id 对账。"),
    }


def get_capture(rid: str, date: str | None = None, source: str = "") -> dict | None:
    """按 id 取完整 record。优先走索引 off/len 直接 seek（826MB 文件也是毫秒级；
    压实后锚点变成 skel.jsonl，实测中位 3.7ms）；索引缺行时兜底扫描（子串预筛后才 parse）。

    date 指定则只扫该日；为 None 则先扫今天，找不到回退遍历所有历史日期
    （修复：原先写死今天，历史日期详情必然 404，审计 260712 #4）。
    """
    def _scan_one(d: str) -> dict | None:
        day = _Day(d, source)
        if not day.exists:
            return None
        entries = list_index(d, source=source)
        hit = next((e for e in entries if e.get("id") == rid), None)
        if hit is not None and isinstance(hit.get("off"), int) and isinstance(hit.get("len"), int):
            rec = day.record_at(hit["off"], hit["len"], hit.get("seg"))
            if rec is not None and rec.get("id") == rid:
                return rec
            # 偏移失效（文件被外部改动 / 索引是压实前的）→ 落到扫描兜底
        with _LOCK:
            return day.find_by_id(rid)

    if date:
        return _scan_one(date)
    today = time.strftime("%Y-%m-%d", time.localtime())
    if not source:
        hit = _scan_one(today)
        if hit is not None:
            return hit
    for d in _available_dates(source):  # 回退遍历历史，最近优先
        if d == today and not source:
            continue
        hit = _scan_one(d)
        if hit is not None:
            return hit
    return None


def _available_dates(source: str = "") -> list[str]:
    """某个录制根下有哪些日期。**两种形态都要认**——只认 jsonl 的话，压实过的天会从
    日期 chip 里整片消失，而且不会有任何东西报错（惯犯 ③ 的形状）。"""
    root = _source_root(source)
    if not root.exists():
        return []
    # 只认 YYYY-MM-DD：滤掉 {date}.idx.jsonl（索引）和 .{date}.packing.* 临时目录，
    # 否则它们会变成日期 chip 混进 UI（260719 索引文件引入后必现）
    dates = {f.stem for f in root.glob("*.jsonl") if _DATE_RE.match(f.stem)}
    for d in root.glob(f"*{pack.PACK_SUFFIX}"):
        if not pack.is_pack(d):
            continue
        stem = d.stem
        if _DATE_RE.match(stem):
            dates.add(stem)
            continue
        # 分片 `{date}.pNN`（260831）。**必须认**：一天只剩分片、尾巴恰好为空时，
        # 不认就是整天从日期列表里消失，且不会有任何东西报错（惯犯 ③ 的形状）。
        # 同时只认这一种形状——别的带点文件名不当日期，否则临时目录会混进 UI。
        head, _, tag = stem.rpartition(".")
        if _DATE_RE.match(head) and tag.startswith("p") and tag[1:].isdigit():
            dates.add(head)
    return sorted(dates, reverse=True)


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
# 来源标签：字母数字加 - _ .，长度 1~40，且不许点开头。
# 点开头会让标签目录变成隐藏目录（在文件管理器里凭空消失），`..` 更是直接路径穿越——
# 标签来自 API 参数和归档文件名，两个入口都不可信。
_LABEL_RE = _re.compile(r"(?!\.)[A-Za-z0-9._-]{1,40}\Z")


def _validate_date(date: str) -> None:
    """YYYY-MM-DD 格式 + 语义校验（防路径穿越 + 拒非法月日）。"""
    if not isinstance(date, str) or not _DATE_RE.match(date):
        raise StoreError("bad_date", f"非法日期：{date!r}")
    try:
        time.strptime(date, "%Y-%m-%d")   # 校验月日范围（如 2026-13-45 拒绝）
    except ValueError:
        raise StoreError("bad_date", f"非法日期：{date!r}")


def _validate_label(label: str) -> None:
    """来源标签校验（防路径穿越 + 防隐藏目录）。"""
    if not isinstance(label, str) or not _LABEL_RE.match(label):
        raise StoreError("bad_label",
                         f"非法来源标签：{label!r}（只允许字母数字与 - _ .，不能以点开头，≤40 字符）")


def _rm(p: Path) -> None:
    """删一个文件或一个 pack 目录。删不掉要上抛——静默失败会让用户以为空间已经释放。"""
    try:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    except OSError as e:
        raise StoreError("delete_failed", f"删除失败 {p.name}：{e}")


def purge_date(date: str, source: str = "") -> int:
    """删除指定日期的录制（jsonl 主文件+索引，或整个 pack 目录），返回删除的记录条数。
    持 _LOCK 防与 append 竞争；当天则一并清内存 deque（否则 SSE 客户端还看到旧摘要）。"""
    _validate_date(date)
    day = _Day(date, source)
    removed = 0
    today = time.strftime("%Y-%m-%d", time.localtime())
    with _LOCK:
        # 路径全部先取好：删掉 pack 目录后 `is_pack` 会翻面，`idx` / `segments` 跟着变，
        # 边删边算就会漏掉后半批（删了一半的一天，界面上还剩几条，没有任何报错）。
        removed = day.count()           # pack 读 manifest、jsonl 只数行，都不 parse
        segs = day.segments
        fi = day.idx
        was_pack = day.is_pack
        if was_pack:
            _rm(day.pack_dir)
        for seg in segs:                # 滚动压实的分片（260831）
            _rm(seg)
        if day.jsonl.exists():
            _rm(day.jsonl)              # 尾巴，或压实收尾被打断留下的残留
        try:
            if fi.exists():
                fi.unlink()
        except OSError:
            pass        # 索引删不掉不致命：主文件已没，读取侧会清陈旧索引
        _IDX_CACHE.pop((source, date), None)
        if date == today and not source:
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


# ===== 压实 / 还原 / 归档 / 导入（260825）=====
#
# 三个动作的边界（命名先划清，否则 UI 上会打架，snapshot_store 头部那份声明同步过）：
#   compact_date()      原地压实成 pack，**不删任何东西**，读取侧透明——纯瘦身
#   archive_date()      打成可搬运的单文件 .ccwa，默认**归档后删原录制**——清理动作
#   enforce_retention() 按天数自动删——唯一会自动删数据的动作
#   snapshot_*          用户显式保存的拷贝——永不自动清理
#
# 260825 前 archive_date 叫「压缩存档」，实为清理；且用 zip DEFLATE（滑动窗口 32KB）压
# 一份重复块相隔几十 MB 的数据，实测 49MB 的一天只压到 19MB（2.6x）。现在归档走 pack，
# 同一天 28x，且拷到另一台机器不解压就能翻。


def _tool_version() -> str:
    """产出这份 pack / 归档的本工具版本。

    **读的是 `VERSION`**——`_version.py` 里从来只有这一个名字（`app.py` 也是这么读的）。
    260826 之前这里取的是 `__version__`，一个谁都没定义过的属性：`getattr` 有默认值，
    于是它安安静静地一直返回空串，所有 pack 与归档的 `tool_version` 全是空的，导入端
    显示的"来自哪个版本"永远空白——这正是惯犯 ③「静默吞异常」的形状（有兜底、不报错、
    结果是错的），而它出现在一个专门用来回答"这份数据是谁产出的"的字段上。
    """
    try:
        from _version import VERSION
        return VERSION or "dev"
    except Exception:
        return "dev"


def local_host() -> str:
    """本机名。归档 manifest 与来源列表都用它回答"这是哪台机器"。

    **只取 hostname，不取用户名**：归档是拿来分享的（跨机排查时会被拷来拷去），用户名是
    个人标识，而 hostname 已经足以把两台机器分开——泄露面小得多。取不到就空着，
    列表侧照旧显示"未知机器"，不编一个。
    """
    try:
        return (socket.gethostname() or "").strip()[:64]
    except OSError:
        return ""


def _verify_and_index(pack_dir: Path, src_jsonl: Path) -> None:
    """逐字节校验 pack，**同一趟把索引也建出来**写进 pack 目录。

    校验本来就要把每条记录还原一遍，顺手交给 classifier 建索引等于白捡（477MB 的一天
    省掉约 10s 的重建）。索引缺了不致命——读取侧会回填自愈——但让每个压实完的天在
    第一次点开时卡十几秒，是"能跑但难用"，而这类问题从来不会有人回头再修。"""
    entries: list[dict] = []

    def _idx(off: int, ln: int, rec: dict) -> None:
        try:
            e = classifier.index_record(rec)
        except Exception as err:        # 单条分类失败不该让整次压实失败（索引是缓存不是事实源）
            log.error("压实建索引失败（该条留给读取侧回填）：%s", err)
            return
        e["off"] = off
        e["len"] = ln
        entries.append(e)

    pack.verify_against(pack_dir, src_jsonl, on_record=_idx)
    pack.write_idx_bytes(pack_dir, b"".join(
        (json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8") for e in entries))


_SEALING = ".sealing."      # 切段中转文件的中缀，点开头 → 不会被 _available_dates 认成日期


def _next_seg(day: "_Day") -> Path:
    """下一个分片目录路径。序号按**现有最大号 +1**，不按个数——中间少了一个（被手工删掉）
    时按个数会撞上已存在的号，而撞号意味着两截录制争同一个目录名。"""
    top = 0
    pre = f"{day.date}.p"
    for d in day.root.glob(f"{pre}*{pack.PACK_SUFFIX}"):
        n = d.name[len(pre):-len(pack.PACK_SUFFIX)]
        if n.isdigit():
            top = max(top, int(n))
    return day.root / f"{day.date}.p{top + 1:02d}{pack.PACK_SUFFIX}"


def seal_tail(date: str = "", source: str = "") -> dict | None:
    """把今天已写完的那一截尾巴封存成一个分片（滚动压实，issue 260831）。

    与 `compact_date` 的分工：那个处理"过去的、不再变化的一天"，这个处理"今天正在写的一截"。
    两者产出的都是**标准 pack 目录**，区别只在怎么把源头拿到手——

      compact_date  源文件不再变化，可以直接对着它 write_pack + 逐字节校验
      seal_tail     源文件正被 append 写着，所以**锁内瞬时改名把它冻住**，再在锁外
                    从容压实校验。改名之后 append 的 `open("ab")` 会自然新建一个空尾巴，
                    两边互不干扰——这是整个方案不必碰转发热路径的关键。

    顺序（每一步都按"这里断电会怎样"设计）：
      1. 锁内：`{date}.jsonl` → `.{date}.sealing.{ts}.jsonl`，索引一并改名，清缓存
         —— 纯 rename，微秒级；断电最坏留下一对 sealing 文件，一个字节没丢
      2. 锁外：`write_pack` + `_verify_and_index` 逐字节校验（与 compact_date 同一条路）
         —— **失败则回退**：把这期间新写的尾巴续到 sealing 后面再改名还原，
            回到"就像没切过"的状态。顺序天然正确（sealing 在前、新尾巴在后）
      3. 锁内：staging → `{date}.pNN.pack`，删掉 sealing 文件
         —— 断电会同时留下分片和 sealing，`cleanup_partials` 清后者

    返回压实结果 dict；没有可封存的尾巴时返回 None（不是错误）。
    """
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    _validate_date(date)
    day = _Day(date, source)
    if day.is_pack:
        raise StoreError("already_packed", f"{date} 已经是压实态，没有尾巴可封")
    ts = time.strftime("%H%M%S", time.localtime())
    sealing = day.root / f".{date}{_SEALING}{ts}.jsonl"
    sealing_idx = day.root / f".{date}{_SEALING}{ts}.idx.jsonl"
    tail_idx = day.root / f"{date}.idx.jsonl"

    # ── 1. 锁内冻住尾巴 ──
    with _LOCK:
        if not day.jsonl.exists() or day.jsonl.stat().st_size == 0:
            return None
        try:
            day.jsonl.rename(sealing)
        except OSError as e:
            raise StoreError("seal_failed", f"封存尾巴失败（录制未动）：{e}")
        try:
            if tail_idx.exists():
                tail_idx.rename(sealing_idx)
        except OSError:
            pass        # 索引搬不动不致命：它是缓存，回填会自愈
        _IDX_CACHE.pop((source, date), None)

    raw_bytes = sealing.stat().st_size
    staging = day.root / f".{date}.packing.{ts}"
    t0 = time.time()
    try:
        manifest = pack.write_pack(sealing, staging, date=date,
                                   tool_version=_tool_version())
        _verify_and_index(staging, sealing)
    except (pack.PackError, OSError) as e:
        pack._rmtree_quiet(staging)
        _unseal(day, sealing, sealing_idx)
        raise StoreError(getattr(e, "code", "seal_failed"),
                         f"分片压实失败，已还原成未切段的状态：{e}")

    # ── 3. 锁内就位 ──
    with _LOCK:
        seg_dir = _next_seg(day)
        try:
            staging.rename(seg_dir)
        except OSError as e:
            pack._rmtree_quiet(staging)
            _unseal(day, sealing, sealing_idx)
            raise StoreError("seal_failed", f"分片就位失败，已还原：{e}")
        for f in (sealing, sealing_idx):
            try:
                if f.exists():
                    f.unlink()
            except OSError as e:
                # 分片已就位且校验过，读取侧以它为准；残留只是占地方，不是数据风险
                log.error("封存文件删除失败 %s（下次 cleanup_partials 再清）：%s", f.name, e)
        _IDX_CACHE.pop((source, date), None)

    packed = sum(f.stat().st_size for f in seg_dir.rglob("*") if f.is_file())
    log.info("滚动压实 %s → %s：%d 条 %.1fMB → %.1fMB（%.1fx，%dms）",
             date, seg_dir.name, manifest["count"], raw_bytes / 1e6, packed / 1e6,
             raw_bytes / packed if packed else 0, int((time.time() - t0) * 1000))
    return {
        "date": date, "source": source, "segment": seg_dir.name,
        "count": manifest["count"], "raw_bytes": raw_bytes, "packed_bytes": packed,
        "saved_bytes": max(0, raw_bytes - packed),
        "ratio": round(raw_bytes / packed, 1) if packed else None,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def _unseal(day: "_Day", sealing: Path, sealing_idx: Path) -> None:
    """切段失败的回退：把封存的那一截还原成尾巴，回到"就像没切过"的状态。

    期间 `append` 可能已经新建了尾巴并写进去了，所以是**把新尾巴续到 sealing 后面**
    再改名还原——顺序天然正确（sealing 那截在前，新写的在后）。

    索引直接删掉不拼接：拼接要把新尾巴每条的 off 加上 sealing 的长度，那是第二份
    偏移改写逻辑，两份迟早分叉；而读取侧的全量回填本来就能自愈，是已被验证的那条路。
    """
    with _LOCK:
        try:
            if day.jsonl.exists():
                with sealing.open("ab") as out, day.jsonl.open("rb") as cur:
                    shutil.copyfileobj(cur, out)
                day.jsonl.unlink()
            sealing.rename(day.jsonl)
        except OSError as e:
            # 走到这里说明还原也失败了。**必须喊出来**：sealing 文件里是真录制，
            # 它不在读取侧的任何一条路上，不喊就是静默丢一截。
            log.error("切段回退失败！%s 里是尚未纳入读取的录制，请手工并回 %s：%s",
                      sealing.name, day.jsonl.name, e)
            return
        for f in (day.root / f"{day.date}.idx.jsonl", sealing_idx):
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                pass
        _IDX_CACHE.pop((day.source, day.date), None)


def _restore_day(day: "_Day", dst: Path) -> int:
    """把一天（分片 + 尾巴）还原成一个完整 jsonl，返回条数。

    **顺序是分片在前、尾巴在后**——那就是录制顺序。

    合并（`merge_segments`）和归档（`archive_date`）都要用它。两处各写一份的下场
    260831 当场演过一次：`archive_date` 原本只认 `day.jsonl`，遇到分片形态就把
    前面几截整个漏掉，归档里只剩尾巴那一点，**而且不会有任何东西报错**——
    等发现时那台机器上的原录制早已按"已归档"删掉了。
    """
    n = 0
    with dst.open("wb") as out:
        for seg in day.segments:
            with pack.PackReader(seg) as r:
                for raw in r.iter_lines():
                    out.write(raw)
                    n += 1
        if day.jsonl.exists():
            with day.jsonl.open("rb") as cur:
                shutil.copyfileobj(cur, out)
            n += _count_lines(day.jsonl)
    return n


def merge_segments(date: str, source: str = "", progress=None) -> dict | None:
    """把一天的分片 + 尾巴合并回**单个 `{date}.pack`**（滚动压实的收尾，跨天时跑）。

    为什么要合回去：分片是"今天"的临时形态，历史天回到单 pack 就回到了已经上线实测过的
    格式——`.ccwa` 归档、导入、跨机搬运、「删一天 = 删一个目录」这些性质全部原样保住，
    `PACK_SCHEMA` 一版都不用动。多分片的读取路径因此只需要服务今天这一天。

    代价是跨分片的 blob 重复没被消除（每个分片一个独立 blob 池）。可重复的主要是
    tools/system，它们在一天之内已经被压到 0.2%~1.0%，增量收益很小——这与 `pack.py`
    「blob 池按天独立」的原始论证是同一条理由。

    做法是**先还原成一个完整 jsonl 再走 compact_date**，不自己拼第二套压实逻辑：
    合并出的那份必须与"这一天从头压实一次"逐字节一致，而保证这件事最省的办法
    就是真的走同一条路。
    """
    _validate_date(date)
    day = _Day(date, source)
    if day.is_pack:
        return None                     # 已经是单 pack，没什么可合的
    segs = day.segments
    if not segs:
        return None                     # 没有分片：这天要么是纯 jsonl（交给 compact_date），要么是空的
    raw_bytes = day.disk_bytes()        # 合并前先量：删完再量就只剩合并后的了
    ts = time.strftime("%H%M%S", time.localtime())
    restored = day.root / f".{date}.merging.{ts}.jsonl"
    t0 = time.time()
    try:
        _restore_day(day, restored)
    except (OSError, pack.PackError) as e:
        _rm_quiet(restored)
        raise StoreError("merge_failed", f"合并分片失败（分片与尾巴都没动）：{e}")

    staging = day.root / f".{date}.packing.{ts}"
    try:
        manifest = pack.write_pack(restored, staging, date=date,
                                   tool_version=_tool_version(), progress=progress)
        _verify_and_index(staging, restored)
    except (pack.PackError, OSError) as e:
        pack._rmtree_quiet(staging)
        _rm_quiet(restored)
        raise StoreError(getattr(e, "code", "merge_failed"),
                         f"合并后压实失败（分片与尾巴都没动）：{e}")

    with _LOCK:
        try:
            staging.rename(day.pack_dir)
        except OSError as e:
            pack._rmtree_quiet(staging)
            _rm_quiet(restored)
            raise StoreError("merge_failed", f"合并结果就位失败（分片与尾巴都没动）：{e}")
        # 单 pack 已就位且逐字节校验过，从这一刻起它就是这天的事实源；
        # 分片与尾巴成了旧副本，删不掉也只是占地方（`is_pack` 会让读取侧无视它们）。
        for seg in segs:
            try:
                shutil.rmtree(seg)
            except OSError as e:
                log.error("合并后删分片失败 %s：%s", seg.name, e)
        for f in (day.jsonl, day.root / f"{date}.idx.jsonl", restored):
            try:
                if f.exists():
                    f.unlink()
            except OSError as e:
                log.error("合并后删残留失败 %s：%s", f.name, e)
        _IDX_CACHE.pop((source, date), None)

    packed = day.disk_bytes()
    log.info("分片合并 %s：%d 个分片 + 尾巴 → %d 条 / %.1fMB（%dms）",
             date, len(segs), manifest["count"], packed / 1e6,
             int((time.time() - t0) * 1000))
    # 形状与 compact_date 对齐：调用方（/api/captures/compact、CLI）拿到的是同一种结果，
    # 不必按"这天走的是哪条路"分支——分不清就会漏字段，而漏字段是 KeyError 或静默 0。
    return {
        "date": date, "source": source, "segments": len(segs),
        "count": manifest["count"], "raw_bytes": raw_bytes, "packed_bytes": packed,
        "saved_bytes": max(0, raw_bytes - packed),
        "ratio": round(raw_bytes / packed, 1) if packed else None,
        "blob_count": manifest["blob_count"],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def _rm_quiet(p: Path) -> None:
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


def compact_date(date: str, source: str = "", progress=None) -> dict:
    """把某天的 jsonl 压实成 pack。**不删今天**，**校验通过才删原文件**。

    为什么不碰今天：`append` 只写今天，压实今天就得和写盘热路径抢同一个文件。代理透明性
    是本项目第一优先级——录制体积再大，也不值得让「转发」这条路上多一个可能失败的环节。

    顺序是有讲究的（每一步都按"这里断电会怎样"设计）：
      1. 锁外写 staging 目录（`.{date}.packing.{ts}`，点开头，不会被 `_available_dates` 认成日期）
         —— 断电只留一个垃圾目录，原录制一个字节没动
      2. 锁外逐字节校验，**顺手把索引也建了**（校验本来就要还原每条记录，见 pack.verify_against）
         —— 校验不过就抛，原录制仍在原地
      3. 锁内 rename staging → `{date}.pack` 并删原文件
         —— 中间断电会同时留下 pack 和 jsonl，读取侧以 pack 为准（它已校验过），
            残留 jsonl 由 `cleanup_partials()` 清
    """
    _validate_date(date)
    day = _Day(date, source)
    today = time.strftime("%Y-%m-%d", time.localtime())
    if not source and date == today:
        raise StoreError("is_today", "今天正在录制，不压实（压实只处理过去的天）")
    if day.is_pack:
        raise StoreError("already_packed", f"{date} 已经是压实态")
    if day.is_segmented:
        # 这天被滚动压实切过段（260831）→ 走合并那条路，它内部同样是
        # write_pack + 逐字节校验，产出也是同一个 `{date}.pack`。
        # 在这里分流而不是让调用方判断：外面只该知道"把这天压实"，不该知道它是怎么长出来的。
        merged = merge_segments(date, source, progress)
        if merged is not None:
            return merged
    if not day.jsonl.exists():
        raise StoreError("not_found", f"{date} 无录制文件")

    raw_bytes = day.jsonl.stat().st_size
    old_idx = day.idx
    ts = time.strftime("%H%M%S", time.localtime())
    staging = day.root / f".{date}.packing.{ts}"
    t0 = time.time()
    try:
        manifest = pack.write_pack(day.jsonl, staging, date=date,
                                   tool_version=_tool_version(), progress=progress)
        _verify_and_index(staging, day.jsonl)
    except pack.PackError as e:
        pack._rmtree_quiet(staging)
        raise StoreError(e.code, str(e))
    except OSError as e:
        pack._rmtree_quiet(staging)
        raise StoreError("compact_failed", f"压实失败：{e}")

    with _LOCK:
        if day.jsonl.stat().st_size != raw_bytes:
            # 压实期间源文件长大了 = 有人在往过去的日期写（不该发生）。宁可放弃也不要
            # 用一个"少了后半截"的 pack 顶替原文件。
            pack._rmtree_quiet(staging)
            raise StoreError("source_changed", f"{date} 在压实期间被写入，已放弃（原录制未动）")
        try:
            staging.rename(day.pack_dir)
        except OSError as e:
            pack._rmtree_quiet(staging)
            raise StoreError("compact_failed", f"压实结果就位失败：{e}")
        try:
            if old_idx.exists():
                old_idx.unlink()        # 老索引的 off/len 指向已不存在的主文件，留着只会误导
        except OSError:
            pass
        try:
            day.jsonl.unlink()
        except OSError as e:
            # pack 已就位且校验过，读取侧以它为准；残留的 jsonl 只是占地方，不是数据风险
            log.error("压实后删原文件失败 %s（下次 cleanup_partials 再清）：%s", date, e)
        _IDX_CACHE.pop((source, date), None)

    packed = day.disk_bytes()
    return {
        "date": date, "source": source, "count": manifest["count"],
        "raw_bytes": raw_bytes, "packed_bytes": packed,
        "saved_bytes": max(0, raw_bytes - packed),
        "ratio": round(raw_bytes / packed, 1) if packed else None,
        "blob_count": manifest["blob_count"],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def uncompact_date(date: str, source: str = "") -> dict:
    """pack → jsonl 还原（compact 的逆操作）。同样是「新的就位了才删旧的」。

    还原后**不重建索引，直接删掉**：pack 里的索引 off/len 指向 skel.jsonl，对还原出来的
    jsonl 是错的；而读取侧的增量回填本来就能自愈（这套机制 260719 起就在跑）。
    与其在这里写第二份 off/len 改写逻辑（两份迟早分叉），不如让已被验证的那条路去干。
    """
    _validate_date(date)
    day = _Day(date, source)
    if not day.is_pack:
        if day.is_segmented:
            # 说真话：这天**是**压过的，只是还在滚动压实的中间态。回一句"不是压实态"
            # 是假的，用户会以为压实没生效而去重压一次。
            raise StoreError(
                "is_segmented",
                f"{date} 正在滚动压实（{len(day.segments)} 个分片），跨天合并成单 pack 后才能还原")
        raise StoreError("not_packed", f"{date} 不是压实态")
    ts = time.strftime("%H%M%S", time.localtime())
    staging = day.root / f".{date}.unpacking.{ts}.jsonl"
    try:
        count = pack.unpack(day.pack_dir, staging)
    except pack.PackError as e:
        try:
            if staging.exists():
                staging.unlink()
        except OSError:
            pass
        raise StoreError(e.code, str(e))
    with _LOCK:
        if day.jsonl.exists():
            try:
                staging.unlink()
            except OSError:
                pass
            raise StoreError("dst_exists", f"{date}.jsonl 已存在，未覆盖")
        try:
            staging.rename(day.jsonl)
        except OSError as e:
            raise StoreError("uncompact_failed", f"还原就位失败：{e}")
        pack_dir = day.pack_dir
        _IDX_CACHE.pop((source, date), None)
    try:
        shutil.rmtree(pack_dir)
    except OSError as e:
        log.error("还原后删 pack 目录失败 %s：%s", date, e)
    return {"date": date, "source": source, "count": count,
            "bytes": day.jsonl.stat().st_size}


def archive_date(date: str, source: str = "", label: str = "", keep: bool = False) -> dict:
    """归档某天成单文件 `.ccwa`（可拷到另一台机器导入）。默认归档后删原录制（清理语义）。

    `keep=True` 只导出不删——跨机排查时源机器往往还要继续用自己的录制。
    今天也能归档（此前的 archive_date 就支持"清除到目前为止"），走的是先压实到临时目录
    再打包的路子，**不动正在录的那个文件**。
    """
    _validate_date(date)
    day = _Day(date, source)
    if not day.exists:
        raise StoreError("not_found", f"{date} 无录制")
    if label:
        _validate_label(label)
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H%M%S", time.localtime())
    dst = ARCHIVES_DIR / (f"{date}.{label}.{ts}{pack.CCWA_SUFFIX}" if label
                          else f"{date}.{ts}{pack.CCWA_SUFFIX}")
    tmp_pack = None
    tmp_jsonl = None
    try:
        if day.is_pack:
            src_pack = day.pack_dir
        else:
            # jsonl 形态：先压实到临时目录（含逐字节校验），再打包。
            # 临时目录点开头，不会被 _available_dates 认成日期。
            tmp_pack = day.root / f".{date}.archiving.{ts}"
            if day.segments:
                # 分片形态（260831）：**必须先把分片 + 尾巴还原成完整一天**。
                # 直接压 day.jsonl 只会归档尾巴那一截，前面几截全丢，而且不报错——
                # 归档默认是删原录制的清理动作，丢了就真没了。
                tmp_jsonl = day.root / f".{date}.archiving.{ts}.jsonl"
                _restore_day(day, tmp_jsonl)
                src_jsonl = tmp_jsonl
            else:
                src_jsonl = day.jsonl
            pack.write_pack(src_jsonl, tmp_pack, date=date, label=label,
                            tool_version=_tool_version())
            # 索引一并建进归档：跨机搬运时对面就不用先卡一次全量重建
            _verify_and_index(tmp_pack, src_jsonl)
            src_pack = tmp_pack
        # 归档本机录制时签上产出者（版本 + 机器名）；归档一个**导入来源**时一个字都不签，
        # 保留原机器写在 manifest 里的身份——否则转手一次就把别人的证据变成了"本机的"。
        stamp = {} if source else {"tool_version": _tool_version(), "host": local_host()}
        info = pack.to_ccwa(src_pack, dst, label=label, **stamp)
    except pack.PackError as e:
        if tmp_pack:
            pack._rmtree_quiet(tmp_pack)
        raise StoreError(e.code, str(e))
    finally:
        if tmp_jsonl:
            _rm_quiet(tmp_jsonl)    # 分片还原出来的中转文件，成败都不该留下
        if tmp_pack and tmp_pack.exists() and dst.exists():
            pack._rmtree_quiet(tmp_pack)
    removed = 0
    if not keep:
        removed = purge_date(date, source)
    return {"path": str(dst), "size": info["size"], "count": info.get("count", 0),
            "removed": removed, "date": date, "label": label, "kept": keep}


def import_archive(src: str | Path, label: str = "") -> dict:
    """导入 `.ccwa` 到 `sources/<标签>/`（外来录制的独立命名空间）。

    **必须分命名空间**：两台机器同一天都在录，日期一定撞车。混进 captures/ 的后果不是
    报错而是更糟的东西——把别的机器的证据当成本机事实读，排查会直接跑偏。

    标签缺省取归档里记的 label，再没有就用文件名前缀。
    """
    src = Path(src)
    if not src.exists():
        raise StoreError("not_found", f"找不到归档文件：{src}")
    try:
        manifest = pack.peek_ccwa(src)
    except pack.PackError as e:
        raise StoreError(e.code, str(e))
    date = manifest.get("date") or ""
    _validate_date(date)
    label = label or manifest.get("label") or src.stem.split(".")[-1] or "imported"
    _validate_label(label)
    dst_dir = SOURCES_DIR / label / f"{date}{pack.PACK_SUFFIX}"
    if pack.is_pack(dst_dir):
        raise StoreError("already_imported", f"来源 {label} 下的 {date} 已经导入过")
    dst_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        pack.from_ccwa(src, dst_dir)
    except pack.PackError as e:
        raise StoreError(e.code, str(e))
    with _LOCK:
        _IDX_CACHE.pop((label, date), None)
    host = manifest.get("host", "")
    return {"label": label, "date": date, "count": manifest.get("count", 0),
            "bytes": _Day(date, label).disk_bytes(),
            "from": manifest.get("tool_version", ""),
            "host": host, "foreign": bool(host) and host != local_host(),
            "created_at": manifest.get("created_at", "")}


def list_sources() -> list[dict]:
    """已导入的外来录制来源清单（界面上要与本机录制区分开）。"""
    if not SOURCES_DIR.exists():
        return []
    out = []
    for d in sorted(SOURCES_DIR.iterdir()):
        if not d.is_dir() or not _LABEL_RE.match(d.name):
            continue
        dates = _available_dates(d.name)
        if not dates:
            continue
        days = [_Day(x, d.name) for x in dates]
        # 名片取最近导入的那天（老归档可能根本没有 host 字段，往前找一天算一天）
        card = {}
        for x in reversed(days):
            card = x.manifest() or {}
            if card.get("host") or card.get("tool_version"):
                break
        host = card.get("host", "")
        out.append({
            "label": d.name,
            "dates": dates,
            "days": len(dates),
            "count": sum(x.count() for x in days),
            "bytes": sum(x.disk_bytes() for x in days),
            "host": host,
            "foreign": bool(host) and host != local_host(),
            "from": card.get("tool_version", ""),
            "archived_at": card.get("archived_at", ""),
        })
    return out


def delete_source(label: str) -> dict:
    """删掉一个导入来源（整个目录）。外来录制不参与 retention，只能显式删。"""
    _validate_label(label)
    d = SOURCES_DIR / label
    if not d.is_dir():
        raise StoreError("not_found", f"没有这个来源：{label}")
    dates = _available_dates(label)
    _rm(d)
    with _LOCK:
        for x in dates:
            _IDX_CACHE.pop((label, x), None)
    return {"label": label, "days": len(dates)}


def list_archives() -> list[dict]:
    """archives/ 下的归档单文件清单（不解包，只读 manifest）。"""
    if not ARCHIVES_DIR.exists():
        return []
    out = []
    for f in sorted(ARCHIVES_DIR.glob(f"*{pack.CCWA_SUFFIX}"), reverse=True):
        item = {"name": f.name, "path": str(f), "size": f.stat().st_size}
        try:
            m = pack.peek_ccwa(f)
            host = m.get("host", "")
            item.update({"kind": "captures",
                         "date": m.get("date"), "count": m.get("count"),
                         "label": m.get("label", ""), "raw_bytes": m.get("raw_bytes"),
                         "archived_at": m.get("archived_at", ""),
                         "host": host, "from": m.get("tool_version", ""),
                         "foreign": bool(host) and host != local_host()})
        except pack.PackError as e:
            # 快照便携包（260827）同后缀不同 kind——它不是坏归档，是另一种包。
            # 延迟 import：snapshot_pack 反过来依赖本模块。
            try:
                import snapshot_pack
                m = snapshot_pack.peek(f)
                if m.get("kind") != snapshot_pack.KIND:
                    raise ValueError("not a snapshot pack")
                host = m.get("host", "")
                item.update({"kind": "snapshots", "count": m.get("count"),
                             "archived_at": m.get("exported_at", ""),
                             "host": host, "from": m.get("tool_version", ""),
                             "foreign": bool(host) and host != local_host()})
            except Exception:
                item["error"] = str(e)  # 坏归档要显示出来，不能从列表里悄悄消失
        out.append(item)
    # 旧版 zip 归档（260825 之前的格式）也列出来，否则用户会以为文件丢了
    for f in sorted(ARCHIVES_DIR.glob("*.jsonl.zip"), reverse=True):
        out.append({"name": f.name, "path": str(f), "size": f.stat().st_size,
                    "legacy": True, "date": f.name.split(".")[0]})
    return out


def _file_blake2b(p: Path) -> str:
    """整个文件的 blake2b-128，与 `pack.write_pack` 记进 manifest 的 `raw_blake2b` 同一口径。"""
    h = hashlib.blake2b(digest_size=16)
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _recover_sealing(root: Path, source: str) -> int:
    """处理切段被打断留下的 `.{date}.sealing.*.jsonl`。返回处理掉的文件数。

    **这个不能当垃圾直接删**——它里面是真录制，而且此刻不在读取侧的任何一条路上。
    删了就是静默丢一截，正是本项目最不能接受的那种错。

    残留分两种，靠哈希区分（`write_pack` 把源文件的 blake2b 记进了 manifest）：

      压实已完成、只是没删掉它  → 分片的 `raw_blake2b` 与它相同 → 内容已在分片里，安全删
      压实没做完就断电了        → 没有分片认领它 → **并回尾巴**（它在尾巴之前，顺序天然对）

    "没有分片认领"才并回，是为了防重复：认领判据用哈希不用文件名，因为分片一旦就位，
    它叫什么名字与它压的是哪一截已经没有关系了。
    """
    n = 0
    for p in sorted(root.glob(f".*{_SEALING}*.jsonl")):
        if p.name.endswith(".idx.jsonl"):
            continue                    # 索引伴随文件，跟着主文件一起处理
        date = p.name[1:p.name.index(_SEALING)]
        if not _DATE_RE.match(date):
            continue
        day = _Day(date, source)
        try:
            digest = _file_blake2b(p)
        except OSError as e:
            log.error("封存残留读不出来 %s：%s", p.name, e)
            continue
        claimed = False
        for seg in day.segments:
            try:
                if pack.read_manifest(seg).get("raw_blake2b") == digest:
                    claimed = True
                    break
            except pack.PackError:
                continue
        idx = root / (p.name[:-len(".jsonl")] + ".idx.jsonl")
        if claimed:
            for f in (p, idx):
                try:
                    if f.exists():
                        f.unlink()
                        n += 1
                except OSError:
                    pass
            log.info("清理已压实的封存残留：%s", p.name)
        else:
            log.warning("切段被打断，把 %s 并回尾巴（%d 字节尚未纳入读取）",
                        p.name, p.stat().st_size)
            _unseal(day, p, idx)
            n += 1
    return n


def cleanup_partials() -> dict:
    """清理压实/归档中断留下的残留（点开头的临时目录 + pack 已就位却还在的原 jsonl）。

    在代理启动时调一次。**只清能证明是残留的东西**：临时目录名带我们自己的前缀，
    残留 jsonl 的旁边一定有一个校验通过的 pack——两条都不会误伤真录制。

    切段留下的 `.sealing.*` 是**唯一一种要先救再清**的残留，见 `_recover_sealing`。
    """
    dirs = files = 0
    roots = [CAPTURES_DIR]
    if SOURCES_DIR.exists():
        roots += [d for d in SOURCES_DIR.iterdir() if d.is_dir()]
    for root in roots:
        if not root.exists():
            continue
        for p in root.iterdir():
            if p.is_dir() and p.name.startswith(".") and (
                    ".packing." in p.name or ".archiving." in p.name):
                shutil.rmtree(p, ignore_errors=True)
                dirs += 1
            elif p.is_file() and p.name.startswith(".") and (
                    ".unpacking." in p.name or ".merging." in p.name
                    or ".archiving." in p.name):
                # .merging.* / .archiving.* 是合并与归档时的中转还原文件，
                # 分片与尾巴此刻都还在（它们只是被读了一遍），删它无损
                try:
                    p.unlink()
                    files += 1
                except OSError:
                    pass
        try:
            files += _recover_sealing(root, "" if root == CAPTURES_DIR else root.name)
        except Exception as e:
            log.error("封存残留处理失败 %s：%s", root.name, e)
        source = "" if root == CAPTURES_DIR else root.name
        for d in _available_dates(source):
            stray = _Day(d, source).stray_jsonl
            if stray is None:
                continue
            try:
                stray.unlink()
                files += 1
                log.info("清理压实残留：%s", stray.name)
            except OSError:
                pass
    if dirs or files:
        log.info("清理中断残留：%d 个目录 / %d 个文件", dirs, files)
    return {"dirs": dirs, "files": files}


def list_dates(source: str = "") -> list[str]:
    """某个录制根下有哪些日期（降序）。`_available_dates` 的公开名——
    app/cli 不该去碰下划线开头的东西。"""
    return _available_dates(source)


def is_packed(date: str, source: str = "") -> bool:
    """这一天是不是压实态。"""
    return _Day(date, source).is_pack


def day_anchor_size(date: str, source: str = "") -> int:
    """索引锚点文件的大小。**给缓存失效判据用**（/api/dag 的缓存键）——
    形态无关：jsonl 天是主文件大小，pack 天是骨架大小，两者都随"这天有没有变"而变。"""
    return _Day(date, source).anchor_size


def day_info(date: str, source: str = "") -> dict:
    """一天的形态与占用（设置页/CLI dates 用）。"""
    day = _Day(date, source)
    info = {"date": date, "source": source, "exists": day.exists,
            "packed": day.is_pack, "bytes": day.disk_bytes(), "count": day.count()}
    try:
        anchor = day.pack_dir if day.is_pack else day.jsonl
        info["mtime"] = anchor.stat().st_mtime
    except OSError:
        info["mtime"] = 0.0
    m = day.manifest()
    if m:
        info["raw_bytes"] = m.get("raw_bytes")
        info["packed_at"] = m.get("created_at")
        info["ratio"] = (round(m["raw_bytes"] / info["bytes"], 1)
                         if m.get("raw_bytes") and info["bytes"] else None)
    return info


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
