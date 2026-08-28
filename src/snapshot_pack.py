"""快照便携包：把贴纸（快照 + AI 归纳 + 问答）打成一个文件搬到另一台机器（issue 260827）。

**为什么需要它**：录制有 `.ccwa` 归档，快照没有。而快照上最贵的东西不是快照本身，是它旁边
那份 `analysis.json`——本机实测一份 97KB 的归纳花了 27 批、26 分钟。它搬不走，就意味着换一台
机器（或换一个人）只能重跑一遍，重新花一次钱、重新等半小时。

沿用归档那套形状与纪律，不另起一套：

- **同一个 `.ccwa` 后缀，靠 manifest 里的 `kind` 区分**。用户那边只有一个"导入"，
  文件是什么由工具自己看出来——多一个后缀就是多一次"这个该点哪个按钮"。
  老的录制归档没有 `kind` 字段，按录制处理（向后兼容，见 `peek`）。
- **签名只签自己产出的**：`host` 只取机器名不取用户名（归档会被拷来拷去，机器名足以分辨
  两台机器，泄露面小得多），`tool_version` 取真实版本。两者与 `pack.py` 同源同判据。
- **导入不覆盖**：sid 撞了就换一个新 sid 落地，并在信封里记下它从哪台机器来。
  盖掉本机同名快照 = 拿别人的证据顶替自己的，正是 `sources/` 独立命名空间要防的那件事。
- **只解格式认识的成员名**，不按 zip 里写的路径解（Zip Slip）——这个包会来自别的机器。
"""
from __future__ import annotations

import json
import logging
import time
import zipfile
from pathlib import Path

import capture_store
import snapshot_store

log = logging.getLogger(__name__)

SNAP_SCHEMA = 1
KIND = "snapshots"
# 同一个后缀，靠 manifest 里的 kind 区分——用户那边只有一个"导入"（见模块 docstring）
KIND_SUFFIX = ".ccwa"
_MANIFEST = "manifest.json"
_DIR = "snapshots/"          # 包内目录前缀，与数据目录里的布局同名（解包即所见）


class SnapPackError(RuntimeError):
    """带 code 的错误（对齐 pack.PackError / snapshot_store.SnapshotError）。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _members(sid: str) -> list[tuple[str, Path]]:
    """一个快照的四份文件：信封 / AI 归纳 / 八视图语义层 / 问答记录。后三份可以不存在。"""
    return [
        (f"{sid}.json", snapshot_store._snap_file(sid)),
        (f"{sid}.analysis.json", snapshot_store.analysis_file(sid)),
        (f"{sid}.semantic.json", snapshot_store.semantic_file(sid)),
        (f"{sid}.chat.jsonl", snapshot_store.chat_file(sid)),
    ]


def export_snapshots(sids: list, dst: Path, *, note: str = "") -> dict:
    """选中的快照 → 单文件 `.ccwa`。返回 manifest（含落地路径与体积）。"""
    sids = [s for s in dict.fromkeys(sids or []) if s]
    if not sids:
        raise SnapPackError("no_snapshots", "没有选中任何快照")
    items = []
    for sid in sids:
        snapshot_store._validate_sid(sid)
        f = snapshot_store._snap_file(sid)
        if not f.exists():
            raise SnapPackError("not_found", f"快照不存在：{sid}")
        try:
            snap = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SnapPackError("unreadable", f"快照读不出来 {sid}：{e}")
        ana = snapshot_store.analysis_file(sid)
        items.append({
            "sid": sid,
            "kind": snap.get("kind") or "",
            "label": snap.get("label") or "",
            "created": snap.get("created") or "",
            # 归纳是这个包最值钱的东西，摆在 manifest 上——不解包就能看清它带没带
            "has_analysis": ana.exists(),
            "has_semantic": snapshot_store.semantic_file(sid).exists(),
            "has_chat": snapshot_store.chat_file(sid).exists(),
            "bytes": snapshot_store.size_of(sid),
        })
    manifest = {
        "kind": KIND,
        "snap_schema": SNAP_SCHEMA,
        "count": len(items),
        "items": items,
        # 谁在哪台机器上用哪个版本打的包。与归档同源（capture_store），判据只有一处。
        "host": capture_store.local_host(),
        "tool_version": capture_store._tool_version(),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "note": str(note or "")[:500],
    }
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 快照信封是 JSON 文本（一条录制可达数 MB），压得动——与 .ccwa 里 blobs 已是 zstd
        # 的情况不同，这里 DEFLATED 是划算的。
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            for sid in sids:
                for name, path in _members(sid):
                    if path.exists():
                        zf.write(path, arcname=_DIR + name)
    except (OSError, zipfile.BadZipFile) as e:
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass
        raise SnapPackError("export_failed", f"打包失败：{e}")
    return {**manifest, "path": str(dst), "size": dst.stat().st_size}


def peek(src: Path) -> dict:
    """不解包读 manifest。**也认录制归档**——一个"导入"入口要能说清收到的是什么。

    返回的 manifest 一定带 `kind`：录制归档（老格式没有这个字段）补成 `captures`。
    """
    src = Path(src)
    try:
        with zipfile.ZipFile(src) as zf:
            m = json.loads(zf.read(_MANIFEST).decode("utf-8"))
    except KeyError:
        raise SnapPackError("bad_archive", f"{src.name} 里没有 {_MANIFEST}，不是本工具的包")
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, ValueError) as e:
        raise SnapPackError("bad_archive", f"读不了 {src.name}：{e}")
    if not isinstance(m, dict):
        raise SnapPackError("bad_archive", f"{src.name} 的 manifest 结构不对")
    kind = m.get("kind") or ("captures" if "pack_schema" in m else "")
    if kind not in ("snapshots", "captures"):
        raise SnapPackError("bad_archive", f"{src.name} 不是本工具认识的包（kind={kind!r}）")
    if kind == KIND and m.get("snap_schema") != SNAP_SCHEMA:
        raise SnapPackError("schema_mismatch",
                            f"快照包格式版本 {m.get('snap_schema')!r}，本版本只认 {SNAP_SCHEMA}")
    m["kind"] = kind
    return m


def import_snapshots(src: Path) -> dict:
    """`.ccwa`（快照包）→ 本机快照库。返回 {imported, renamed, skipped, items, manifest}。

    **同 sid 不覆盖，换一个新 sid 落地**：包里的快照是别的机器的证据，本机同名的是自己的，
    谁顶替谁都是错的。落地后在信封里记 `imported_from`（机器名 / 版本 / 原 sid），
    界面据此标出"这不是本机录的"。
    """
    src = Path(src)
    manifest = peek(src)
    if manifest.get("kind") != KIND:
        raise SnapPackError("wrong_kind", f"{src.name} 是录制归档，不是快照包")
    from_host = manifest.get("host") or ""
    imported, renamed, skipped = [], [], []
    try:
        with zipfile.ZipFile(src) as zf:
            names = set(zf.namelist())
            for item in manifest.get("items") or []:
                sid = item.get("sid") or ""
                try:
                    snapshot_store._validate_sid(sid)
                except Exception:
                    skipped.append({"sid": sid, "why": "bad_sid"})
                    continue
                env_name = _DIR + f"{sid}.json"
                if env_name not in names:
                    skipped.append({"sid": sid, "why": "missing_in_archive"})
                    continue
                new_sid = sid
                if snapshot_store._snap_file(sid).exists():
                    new_sid = snapshot_store.new_snapshot_id()
                    renamed.append({"from": sid, "to": new_sid})
                try:
                    snap = json.loads(zf.read(env_name).decode("utf-8"))
                except (KeyError, ValueError) as e:
                    skipped.append({"sid": sid, "why": f"unreadable: {e}"})
                    continue
                snap["sid"] = new_sid
                snap["imported_from"] = {
                    "host": from_host,
                    "tool_version": manifest.get("tool_version") or "",
                    "sid": sid,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                }
                snapshot_store._write(snap)
                # 旁挂三份：归纳里也记着 sid，跟着改，否则界面拿它去对快照会对不上；
                # 语义层不带 sid（按文件名挂快照），原样落盘即可
                ana_name = _DIR + f"{sid}.analysis.json"
                if ana_name in names:
                    try:
                        ana = json.loads(zf.read(ana_name).decode("utf-8"))
                        if isinstance(ana, dict):
                            ana["sid"] = new_sid
                            snapshot_store.write_analysis(new_sid, ana)
                    except (KeyError, ValueError) as e:
                        log.warning("导入的归纳读不出来 %s：%s", sid, e)
                sem_name = _DIR + f"{sid}.semantic.json"
                if sem_name in names:
                    try:
                        sem = json.loads(zf.read(sem_name).decode("utf-8"))
                        if isinstance(sem, dict):
                            snapshot_store.write_semantic(new_sid, sem)
                    except (KeyError, ValueError) as e:
                        log.warning("导入的语义层读不出来 %s：%s", sid, e)
                chat_name = _DIR + f"{sid}.chat.jsonl"
                if chat_name in names:
                    try:
                        snapshot_store.chat_file(new_sid).write_bytes(zf.read(chat_name))
                    except (KeyError, OSError) as e:
                        log.warning("导入的问答记录写不下 %s：%s", sid, e)
                imported.append({"sid": new_sid, "from_sid": sid,
                                 "label": snap.get("label") or ""})
    except SnapPackError:
        raise
    except (OSError, zipfile.BadZipFile) as e:
        raise SnapPackError("import_failed", f"导入失败：{e}")
    return {"imported": len(imported), "renamed": renamed, "skipped": skipped,
            "items": imported, "manifest": manifest,
            "host": from_host, "foreign": bool(from_host)
            and from_host != capture_store.local_host()}
