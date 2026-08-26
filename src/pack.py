"""录制压实格式（pack）：内容寻址去重 + 逐 blob 独立压缩，**保住随机访问**。

## 为什么是去重而不是压缩

prompt caching 让 CC 每轮把整段历史原样重发，而 `capture_store.append` 逐条全量落盘。
实测（本机 2026-08-09，477MB/855 条）：`messages` 占 75.4% 的字节，其中**唯一内容只有 6.6%**；
`tools` 定义在 855 条请求里唯一内容只有 0.13MB，却占了 84MB 磁盘。

所以这不是「压缩率不够」，是「同一份东西存了几十上百遍」。现有的 zip 归档用 DEFLATE，
滑动窗口 **32KB**，而重复块相隔几 MB 到几十 MB —— 它在原理上就看不见跨记录的重复
（实测 49MB 的一天只压到 19MB，2.6x）。换成内容寻址去重后同一天是 28x，且还能随机读单条。

## 格式（`{date}.pack/` 目录，一天一个，自包含）

    skel.jsonl   骨架：一行一条记录，request.body 的 system/tools/messages 换成 {"$cas":[id,...]}
    blobs.zst    blob 池：每个 blob 一个独立 zstd 帧，首尾拼接
    map.json     manifest + blobs[id] = [off, clen, rawlen] + lines[i] = [off, len]
    idx.jsonl.zst  写时索引（off/len 改写为指向 skel.jsonl），整体一个 zstd 帧——
                 压实态的一天是冻结的，没有追加语义，见 `idx_path` 的注释

**blob 引用用整数下标不用哈希串**：哈希串要么截断（截断=可能撞，撞了就是把 A 对话的内容
显示成 B 对话的，这种错没有任何东西会报错）、要么写全 32 个 hex（实测一天 26 万个引用，
全写要多占 4MB 骨架）。整数下标两头都占不着：写时用**完整 128 位** blake2b 去重，
落盘只留下标。哈希只活在打包过程的内存里，不进格式。

**blob 池按天独立**：跨天共享能省的主要是 tools/system，而它们在一天之内已经被压到 0.2%~1.0%，
增量收益很小，换来的却是引用计数。按天独立的好处是「删一天 = 删一个目录」，不会出现
「删了昨天导致前天打不开」这类只在删除时才暴露的耦合故障。

## 无损的定义与验证

盘上的记录本来就是 `json.loads` 后的语义结构（响应侧只存 `content_blocks`，不存原始 SSE
字节）——这是 `capture_store` 既有的基准，pack **不再降一级**。

实测 14 天全部采样记录满足 `json.dumps(json.loads(line), ensure_ascii=False) + "\\n" == line`，
所以还原可以做到**逐字节**一致。但「实测成立」不等于「永远成立」，所以 manifest 存原文件的
blake2b，`verify_against()` 在删原文件之前**逐字节流式比对整个文件**——把假设变成检查。
这条是惯犯 bug ④「测试数据不像真流量」的反面：不拿抽样代替全量。

## 版本不符要拒绝读，不许静默降级

`PACK_SCHEMA` 与 `capture_store` 的 `IDX_SCHEMA` 同一套道理：字段集变了而版本没变，
旧数据仍"结构有效"，新字段恒缺失、逻辑静默退化成回落分支，**没有任何东西会报错**。
这里更严一档——索引是缓存可以重建，pack 是**事实源**，读不懂就必须报错而不是给出半份数据。
"""
from __future__ import annotations

import collections
import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path

import zstandard as zstd

# 格式版本。改字段集/改语义必须 bump，读到不认识的版本一律拒绝（见模块 docstring 末节）。
PACK_SCHEMA = 1

PACK_SUFFIX = ".pack"
CCWA_SUFFIX = ".ccwa"

# 参与去重的 request.body 键。响应侧不参与——实测只占 0.5%~2.2%，压它没有意义，
# 而每多一个参与去重的位置就多一处还原时可能弄错的地方。
BLOB_KEYS = ("system", "tools", "messages")

_SKEL = "skel.jsonl"
_BLOBS = "blobs.zst"
_MAP = "map.json"
_IDX = "idx.jsonl.zst"
_MANIFEST = "manifest.json"      # 归档产出者名片：谁在哪台机器上用哪个版本打的包。
                                 # 打进 .ccwa 顶层（不解包就能看清），导入时一并解进 pack 目录
                                 # ——不然"这是哪台机器录的"在落地那一刻就丢了。

# 压缩级别 3：实测 477MB 的一天打包 9.3s；级别 19 只多省 6% 却慢一个数量级。
_LEVEL = 3

# 单条记录还原时的 blob 解压缓存。grep/全量遍历会让同一个 blob 被反复引用
# （一天里同一条 message 被重发几十上百次，正是本格式存在的理由），不缓存就等于把
# 省下来的磁盘 IO 换成了重复的 CPU。128 条按实测单 blob 中位数几十 KB 计，上限约几十 MB。
_BLOB_CACHE_MAX = 128


class PackError(RuntimeError):
    """带 code 的 pack 错误（对齐 capture_store.StoreError 的 code+detail 模式）。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _dumps(obj) -> bytes:
    """blob 序列化：紧凑分隔符。只用于**哈希与存储**，不用于还原后的记录行——
    还原走 `_dumps_line`，两者分隔符不同是有意的（blob 求小，记录行求与原文件逐字节一致）。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _dumps_line(rec: dict) -> bytes:
    """还原成录制行：必须与 `capture_store.append` 的写法逐字一致
    （`json.dumps(record, ensure_ascii=False)` + 换行），否则「逐字节还原」这条验收线立刻失守。"""
    return (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")


def is_pack(p: Path) -> bool:
    """是不是一个 pack 目录（认结构不认后缀：map.json 在才算，半途失败的残留目录不算）。"""
    return p.is_dir() and (p / _MAP).exists() and (p / _SKEL).exists()


def _read_map(pack_dir: Path) -> dict:
    try:
        m = json.loads((pack_dir / _MAP).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PackError("map_unreadable", f"{pack_dir.name}/{_MAP} 读不出来：{e}")
    v = m.get("pack_schema")
    if v != PACK_SCHEMA:
        raise PackError(
            "schema_mismatch",
            f"pack 格式版本 {v!r}，本版本只认 {PACK_SCHEMA}——拒绝按旧字段猜着读")
    return m


def read_manifest(pack_dir: Path) -> dict:
    """只读 manifest 段（不加载 blobs/lines 表，列表页用）。

    导入进来的 pack 目录里还多躺着一份归档时写的 `manifest.json`（`from_ccwa` 一并解出来），
    它比 map.json 里那份多记了**归档产出者**（`host` / `tool_version` / `archived_at`）——
    而"这是哪台机器录的"只有它能回答，所以它盖在上面。本机自己压实出来的 pack 没有这个
    文件，行为与从前一致。读坏了不能让整个列表页炸掉，但也不能装作没发生：降级回 map.json
    的那份，并把原因塞进 `manifest_error` 让它显出来。
    """
    m = {k: v for k, v in _read_map(pack_dir).items() if k not in ("blobs", "lines")}
    f = pack_dir / _MANIFEST
    if not f.exists():
        return m
    try:
        extra = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        m["manifest_error"] = f"{_MANIFEST} 读不出来：{e}"
        return m
    if isinstance(extra, dict):
        m.update({k: v for k, v in extra.items() if k not in ("blobs", "lines")})
    return m


def idx_path(pack_dir: Path) -> Path:
    """pack 自带的索引文件路径（在目录内 —— 一天自包含，删一天 = 删一个目录）。

    **压实态的索引整体压缩**：一切都缩小 30 倍之后，索引反而成了 pack 里最大的一块
    （实测 477MB 的一天：pack 13MB 里 7.6MB 是索引，因为每条索引都带一份 `sys_head`，
    几百条记录就是几百份几乎相同的系统提示词开头）。压实态的一天是**冻结的**——不会再有
    新记录 append——所以索引可以整体存成一个 zstd 帧，读的时候一次解开；反正读取侧本来
    就是把整份索引读进内存的（`_read_idx_entries` 一直如此）。
    """
    return pack_dir / _IDX


def read_idx_bytes(pack_dir: Path) -> bytes:
    """读出 pack 内索引的原始 jsonl 字节（不存在返回空）。解不开当成没有——
    索引是缓存不是事实源，读取侧会重建。"""
    f = idx_path(pack_dir)
    if not f.exists():
        return b""
    try:
        return zstd.ZstdDecompressor().decompress(f.read_bytes())
    except Exception:
        try:
            return f.read_bytes()       # 兼容：万一是未压缩的旧文件
        except OSError:
            return b""


def write_idx_bytes(pack_dir: Path, data: bytes) -> None:
    """整体写入 pack 内索引（覆盖式——压实态的一天是冻结的，没有追加语义）。"""
    idx_path(pack_dir).write_bytes(zstd.ZstdCompressor(level=_LEVEL).compress(data))


# ===== 写 =====

def write_pack(src_jsonl: Path, pack_dir: Path, *, date: str = "", label: str = "",
               tool_version: str = "", progress=None) -> dict:
    """把一天的 jsonl 压实成 pack 目录。**不删源文件**——删不删由调用方在校验通过后决定。

    `pack_dir` 必须不存在或为空；本函数只往里写，不覆盖别人的东西。
    `progress(done_bytes, total_bytes)` 可选，给长时间压实的 UI 用。

    坏行（崩溃残留的半行）**原样保留成骨架行**而不是跳过：读取侧对坏行的既有行为是
    「当不存在」，但压实是搬家不是清理——把源文件里有的东西丢掉就不再是无损了。
    """
    if pack_dir.exists() and any(pack_dir.iterdir()):
        raise PackError("dst_not_empty", f"目标目录非空：{pack_dir}")
    pack_dir.mkdir(parents=True, exist_ok=True)

    total = src_jsonl.stat().st_size
    cctx = zstd.ZstdCompressor(level=_LEVEL)
    seen: dict[bytes, int] = {}          # blake2b(128位) → blob 下标（只活在内存里，不进格式）
    blobs: list[list[int]] = []          # [off, clen, rawlen]
    lines: list[list[int]] = []          # [off, len] in skel.jsonl
    raw_hash = hashlib.blake2b(digest_size=16)
    count = bad = 0
    done = 0

    try:
        with (src_jsonl.open("rb") as fin,
              (pack_dir / _BLOBS).open("wb") as fb,
              (pack_dir / _SKEL).open("wb") as fs):
            for raw in fin:
                raw_hash.update(raw)
                done += len(raw)
                if progress and count % 200 == 0:
                    progress(done, total)
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    # 坏行：原样搬过去（骨架行 = 源字节），还原时原样吐回
                    bad += 1
                    off = fs.tell()
                    fs.write(raw if raw.endswith(b"\n") else raw + b"\n")
                    lines.append([off, fs.tell() - off])
                    count += 1
                    continue
                body = (rec.get("request") or {}).get("body")
                if isinstance(body, dict):
                    for key in BLOB_KEYS:
                        arr = body.get(key)
                        if not isinstance(arr, list):
                            continue        # 不是数组就原样留在骨架里（协议演进的兜底）
                        ids = []
                        for blk in arr:
                            b = _dumps(blk)
                            h = hashlib.blake2b(b, digest_size=16).digest()
                            i = seen.get(h)
                            if i is None:
                                z = cctx.compress(b)
                                i = len(blobs)
                                blobs.append([fb.tell(), len(z), len(b)])
                                fb.write(z)
                                seen[h] = i
                            ids.append(i)
                        body[key] = {"$cas": ids}
                off = fs.tell()
                fs.write(_dumps(rec) + b"\n")
                lines.append([off, fs.tell() - off])
                count += 1
    except OSError as e:
        raise PackError("write_failed", f"写 pack 失败：{e}")

    manifest = {
        "pack_schema": PACK_SCHEMA,
        "date": date or src_jsonl.stem,
        "count": count,
        "bad_lines": bad,
        "raw_bytes": total,
        "raw_blake2b": raw_hash.hexdigest(),
        "blob_count": len(blobs),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "tool_version": tool_version,
        "hash": "blake2b-128",
        "codec": f"zstd-{_LEVEL}",
        "label": label,
    }
    try:
        (pack_dir / _MAP).write_text(
            json.dumps({**manifest, "blobs": blobs, "lines": lines},
                       ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
    except OSError as e:
        raise PackError("write_failed", f"写 {_MAP} 失败：{e}")
    if progress:
        progress(total, total)
    return manifest


# ===== 读 =====

class PackReader:
    """pack 的只读访问器。用完要 close（或用 with），Windows 上占着句柄会让删除/改名失败。"""

    def __init__(self, pack_dir: Path):
        if not is_pack(pack_dir):
            raise PackError("not_a_pack", f"不是 pack 目录：{pack_dir}")
        self.dir = pack_dir
        m = _read_map(pack_dir)
        self.blobs: list[list[int]] = m.get("blobs") or []
        self.lines: list[list[int]] = m.get("lines") or []
        self.manifest = {k: v for k, v in m.items() if k not in ("blobs", "lines")}
        self._dctx = zstd.ZstdDecompressor()
        self._cache: collections.OrderedDict[int, object] = collections.OrderedDict()
        self._fb = (pack_dir / _BLOBS).open("rb")
        self._fs = (pack_dir / _SKEL).open("rb")

    # -- 生命周期 --
    def close(self) -> None:
        for fh in (self._fb, self._fs):
            try:
                fh.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- 基本属性 --
    @property
    def count(self) -> int:
        return len(self.lines)

    @property
    def skel_size(self) -> int:
        """骨架字节数。索引 off/len 指向骨架，所以它就是索引覆盖判据里的「主文件大小」。"""
        try:
            return (self.dir / _SKEL).stat().st_size
        except OSError:
            return 0

    # -- 还原 --
    def _blob(self, i: int):
        hit = self._cache.get(i)
        if hit is not None:
            self._cache.move_to_end(i)
            return hit
        try:
            off, clen, _ = self.blobs[i]
        except IndexError:
            raise PackError("blob_missing", f"blob 下标越界：{i}（共 {len(self.blobs)}）")
        self._fb.seek(off)
        try:
            obj = json.loads(self._dctx.decompress(self._fb.read(clen)))
        except Exception as e:
            raise PackError("blob_corrupt", f"blob {i} 解不开：{e}")
        self._cache[i] = obj
        if len(self._cache) > _BLOB_CACHE_MAX:
            self._cache.popitem(last=False)
        return obj

    def _inflate(self, rec: dict) -> dict:
        body = (rec.get("request") or {}).get("body")
        if isinstance(body, dict):
            for key in BLOB_KEYS:
                v = body.get(key)
                if isinstance(v, dict) and "$cas" in v:
                    body[key] = [self._blob(i) for i in v["$cas"]]
        return rec

    def record_at(self, off: int, ln: int) -> dict | None:
        """按骨架偏移取一条完整记录（索引 off/len 就是喂给这里的）。"""
        try:
            self._fs.seek(off)
            rec = json.loads(self._fs.read(ln))
        except (OSError, json.JSONDecodeError):
            return None
        return self._inflate(rec)

    def record_i(self, i: int) -> dict | None:
        try:
            off, ln = self.lines[i]
        except IndexError:
            return None
        return self.record_at(off, ln)

    def iter_records(self):
        """按录制顺序遍历完整记录（坏行跳过——与读取侧对坏行的既有行为一致）。"""
        self._fs.seek(0)
        for raw in self._fs:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield self._inflate(rec)

    def iter_lines(self):
        """按录制顺序吐出**还原后的原始录制行字节**（含换行）。用于 uncompact 与逐字节校验。
        坏行原样吐回（打包时也是原样搬的）。"""
        self._fs.seek(0)
        for raw in self._fs:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                yield raw
                continue
            yield _dumps_line(self._inflate(rec))

    def find_by_id(self, rid: str) -> dict | None:
        """索引缺行时的兜底：扫骨架。先做子串预筛（骨架里 id 就在行首附近），命中才 parse。
        原 jsonl 上的同名兜底扫的是几百 MB，这里扫的是几 MB —— 兜底路径反而变快了。"""
        needle = f'"{rid}"'.encode("utf-8")
        self._fs.seek(0)
        for raw in self._fs:
            if needle not in raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if rec.get("id") == rid:
                return self._inflate(rec)
        return None


# ===== 校验 / 还原 =====

def verify_against(pack_dir: Path, src_jsonl: Path, on_record=None) -> int:
    """把 pack 还原出来与源文件**逐字节流式比对**，不一致直接抛。返回比对过的行数。

    这是「压实成功才删原文件」那道门的门锁本身。用全量而不是抽样：抽样过了不等于没坏，
    而这里坏一次的后果是原始证据被删掉且无法察觉——本项目最不能容忍的失败形状。

    `on_record(off, len, record)` 可选：校验这一遍本来就要把每条记录还原出来，顺手交给
    调用方去建索引，**省掉一整趟重建**。不给这个钩子的话，压实完的天要么第一次点开时
    卡十几秒回填，要么就得再遍历一次——两个都不划算。
    """
    with PackReader(pack_dir) as r, src_jsonl.open("rb") as fin:
        n = 0
        for off, ln in r.lines:
            r._fs.seek(off)
            raw = r._fs.read(ln)
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                rec, got = None, raw            # 坏行原样搬的，原样比
            else:
                rec = r._inflate(rec)
                got = _dumps_line(rec)
            want = fin.readline()
            if not want:
                raise PackError("verify_failed", f"第 {n + 1} 行：源文件已到结尾，pack 还多出内容")
            if got != want:
                raise PackError(
                    "verify_failed",
                    f"第 {n + 1} 行还原后与源文件不一致（源 {len(want)}B / 还原 {len(got)}B）")
            if rec is not None and on_record is not None:
                on_record(off, ln, rec)
            n += 1
        if fin.readline():
            raise PackError("verify_failed", f"pack 只有 {n} 行，源文件还有剩余")
    return n


def unpack(pack_dir: Path, dst_jsonl: Path) -> int:
    """pack → jsonl 还原（compact 的逆操作）。返回记录条数。

    还原后按 manifest 里的 blake2b 复核整文件；对不上就删掉半成品并抛——
    宁可还原失败，也不要留下一个"看起来像录制"的文件。
    """
    if dst_jsonl.exists():
        raise PackError("dst_exists", f"目标已存在：{dst_jsonl}")
    r = PackReader(pack_dir)
    want = r.manifest.get("raw_blake2b")
    h = hashlib.blake2b(digest_size=16)
    n = 0
    try:
        with dst_jsonl.open("wb") as out:
            for line in r.iter_lines():
                out.write(line)
                h.update(line)
                n += 1
    except OSError as e:
        raise PackError("write_failed", f"还原写盘失败：{e}")
    finally:
        r.close()
    if want and h.hexdigest() != want:
        try:
            dst_jsonl.unlink()
        except OSError as e:
            raise PackError("verify_failed",
                            f"还原结果与 manifest 哈希不符，且半成品删不掉（{dst_jsonl}）：{e}")
        raise PackError("verify_failed", "还原结果与 manifest 记录的原文件哈希不符")
    return n


# ===== 单文件归档（.ccwa）=====

def to_ccwa(pack_dir: Path, dst: Path, *, label: str = "",
            tool_version: str = "", host: str = "") -> dict:
    """pack 目录 → 单文件 `.ccwa`（可拷到另一台机器）。

    成员用 ZIP_STORED（blobs 已经是 zstd，再压一遍白费 CPU），只有 idx.jsonl 用 DEFLATED
    ——它是纯文本 JSON，压得动，且带上它能让导入端免掉一次全量重建索引。
    顶层另存一份 `manifest.json`：不解包就能看清是哪台机器、哪一天、多少条。

    `tool_version` / `host` 记的是**归档产出者**，给了就盖掉 pack 里原有的值。调用方只在归档
    本机录制时给——归档一个从别的机器导入来的来源时不能给，那会把别人的证据签上自己的名字，
    而这正是 `sources/` 独立命名空间要防的那件事（260826：一份桌面上的 .ccwa 因为 manifest
    答不出"谁录的"，被当成本机数据查了一大圈）。
    """
    if not is_pack(pack_dir):
        raise PackError("not_a_pack", f"不是 pack 目录：{pack_dir}")
    manifest = dict(read_manifest(pack_dir))
    if label:
        manifest["label"] = label
    if tool_version:
        manifest["tool_version"] = tool_version
    if host:
        manifest["host"] = host
    manifest.setdefault("tool_version", "")
    manifest.setdefault("host", "")
    manifest.pop("manifest_error", None)
    manifest["archived_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    try:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr(_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            for name in (_SKEL, _BLOBS, _MAP):
                zf.write(pack_dir / name, arcname=name)
            ix = pack_dir / _IDX
            if ix.exists():
                zf.write(ix, arcname=_IDX, compress_type=zipfile.ZIP_DEFLATED)
    except (OSError, zipfile.BadZipFile) as e:
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass
        raise PackError("archive_failed", f"打包 .ccwa 失败：{e}")
    return {**manifest, "path": str(dst), "size": dst.stat().st_size}


def peek_ccwa(src: Path) -> dict:
    """不解包读 `.ccwa` 的 manifest（导入前给用户看清是什么）。"""
    try:
        with zipfile.ZipFile(src) as zf:
            m = json.loads(zf.read(_MANIFEST).decode("utf-8"))
    except KeyError:
        raise PackError("bad_archive", f"{src.name} 里没有 {_MANIFEST}，不是本工具的归档")
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        raise PackError("bad_archive", f"读不了归档 {src.name}：{e}")
    if m.get("pack_schema") != PACK_SCHEMA:
        raise PackError("schema_mismatch",
                        f"归档格式版本 {m.get('pack_schema')!r}，本版本只认 {PACK_SCHEMA}")
    return m


def from_ccwa(src: Path, pack_dir: Path) -> dict:
    """`.ccwa` → pack 目录（导入）。目标必须不存在或为空。

    只解出格式认识的成员名，**不按 zip 里写的路径解**——zip 条目名可以带 `../`
    （Zip Slip），而归档可能来自别的机器。这条与 `_validate_date` 防路径穿越同源。
    """
    manifest = peek_ccwa(src)
    if pack_dir.exists() and any(pack_dir.iterdir()):
        raise PackError("dst_not_empty", f"目标目录非空：{pack_dir}")
    pack_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(src) as zf:
            names = set(zf.namelist())
            for name in (_SKEL, _BLOBS, _MAP):
                if name not in names:
                    raise PackError("bad_archive", f"归档缺成员 {name}")
            for name in (_SKEL, _BLOBS, _MAP, _IDX, _MANIFEST):
                if name not in names:
                    continue
                with zf.open(name) as fin, (pack_dir / name).open("wb") as fout:
                    shutil.copyfileobj(fin, fout)
    except PackError:
        _rmtree_quiet(pack_dir)
        raise
    except (OSError, zipfile.BadZipFile) as e:
        _rmtree_quiet(pack_dir)
        raise PackError("import_failed", f"解包失败：{e}")
    try:
        _read_map(pack_dir)          # 解完立刻验一次版本与可读性，别等用户点开才炸
    except PackError:
        _rmtree_quiet(pack_dir)
        raise
    return manifest


def _rmtree_quiet(p: Path) -> None:
    """清理半成品目录。删不掉也不能盖掉原始错误——留个残留目录比丢掉真正的失败原因好。"""
    try:
        shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass
