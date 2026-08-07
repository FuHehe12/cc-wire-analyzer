"""上游配置历史与一键还原：cc-switch 误切之后不必手工改回 settings.json。

260717 解决的是「切换了但软件不知道」（检测 + 降旗 + 一键重新接管），解决不了「切错了要切
回去」——「重新接管」只会把外部**刚设的新上游**收编进代理，它假设切换是有意的。误触时用户
要的是切换**之前**那套配置，而软件里此前没有任何路径能做这件事。

**为什么记的是整组 `ANTHROPIC_*` 而不是 BASE_URL 一个字段**：cc-switch 的切换单位是 provider
的整组 env（`BASE_URL` + `AUTH_TOKEN` + `MODEL` [+ `SMALL_FAST_MODEL`]）。只写回 URL 的话，
token 还是上一个供应商的 → 401，模型映射同样错配，用户仍得再开一次 cc-switch，等于没修。
反过来，「回到官方订阅态」的正确动作是**把这些键删干净**而不是写任何 URL——所以快照必须能
表达空集，这也是选「命名空间全量对齐」而不是「逐字段写入」的原因。

**为什么不复用 backups/**：那 5 份完整备份只在 `/api/proxy/start` 时打，用户切到某 provider
后一直没开录制的话，那套配置从未进过备份；而且整文件回滚会连带撤销此间用户改的
`permissions`/`model` 等无关字段，正面违反「只动该动的字段」的本意。

安全边界（开发指南不变量 9「显式还原动作的四条边界」）：
  1. 只写 `ANTHROPIC_*` 前缀键，文件其余部分（`OTEL_*` / `permissions` / `model` …）一律不动；
  2. 只能还原到**本机采集过的**历史快照，不接受任意输入的 URL/token（不给自己开写凭据的口子）；
  3. 写前必备份，走 settings_guard 的原子写（保行尾符）；
  4. patch 态下拒绝执行；自指地址不入历史、也不可还原。

token 明文只落在本机历史文件（与 backups/ 同等敏感），**永不出 API**：`list_entries()` 一律
脱敏。理由与 260713 删掉 `redact_headers` 假开关一致——录制与接口现在可被 AI 经 CLI/HTTP 读取，
给 key 修一条直通 AI 上下文的路是净损失。

self-test：`uv run python src/upstream_history.py --self-test`，全程临时目录，不碰真 settings.json。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

import config as CFG
import settings_guard

log = logging.getLogger(__name__)

# 采集与还原的作用域：env 里所有这个前缀的键。选前缀而非枚举具体键名，是因为 CC 的
# ANTHROPIC_* 键集随版本增长（`ANTHROPIC_DEFAULT_OPUS_MODEL` / `ANTHROPIC_API_KEY` …），
# 枚举法每加一个键就多一处静默漏记——那正是惯犯 ②「键名错位」的形状。
ENV_PREFIX = "ANTHROPIC_"
MAX_ITEMS = 5
HISTORY_FILE = CFG.CONFIG_DIR / "upstream_history.json"

# 脱敏判据：键名含这些词就当凭据处理（与 proxy._redact 同一思路）
_SECRET_HINTS = ("token", "key", "auth", "secret")

# mtime 门控基线。**这里可以用 mtime 基线，而 check_external_change 不能**：260717 那次踩的是
# 「patch 完成到 watcher 首轮之间有 0~2s 竞态窗，基线建在改写之后 → 永远漏检」，那是安全检测，
# 漏一次就是监控静默断档；历史采集漏一拍只是少记一条候选，不必付每 2s 读文件的代价。
_last_mtime: float | None = None


class HistoryError(Exception):
    """带机器可读 code，供 API 直接映射成响应体。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


# ===== 内部工具 =====

def _extract_env(path: Path) -> dict:
    """读 settings.json 里全部 ANTHROPIC_* env 键。文件不存在/损坏 → 空集（等价订阅态）。"""
    try:
        data = settings_guard._read_settings(path)
    except json.JSONDecodeError:
        return {}
    env = data.get("env")
    if not isinstance(env, dict):
        return {}
    return {k: v for k, v in env.items()
            if isinstance(k, str) and k.startswith(ENV_PREFIX) and isinstance(v, str)}


def _fingerprint(env: dict) -> str:
    """键值组合的内容指纹（sha1 前 8 位）。

    **内容寻址而不是按时间朴素追加**：同一套配置反复切换只占一条，否则在 GLM↔Kimi 之间来回
    切两次就能把 5 格历史全冲成这两个 provider，真正想找的那条被挤掉。"""
    payload = json.dumps(env, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _load() -> list[dict]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    # 手改坏的文件不许把后续逻辑带崩：只留形状对的条目
    return [it for it in items
            if isinstance(it, dict) and isinstance(it.get("id"), str)
            and isinstance(it.get("env"), dict)]


def _save(items: list[dict]) -> None:
    """原子写（tmp + replace）：watcher 线程写、Flask 线程读，半截文件会让下拉整个空掉。"""
    CFG.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)


def _mask(key: str, value: str) -> str:
    """凭据类键值脱敏成 `前3…后4`，长度不足直接全遮。非凭据键（模型映射等）原样。"""
    if not any(h in key.lower() for h in _SECRET_HINTS):
        return value
    if len(value) <= 8:
        return "…" * 3
    return f"{value[:3]}…{value[-4:]}"


def _is_ours(env: dict) -> bool:
    """这组 env 是不是本代理 patch 出来的（= 不该进历史）。

    两条判据都要有：`is_patched()` 只反映**本进程**的模块状态，而 marker 是跨进程真源
    （GUI 在录制、CLI 另起一个进程观察时，只信前者会把本地地址当成用户上游记下来）。"""
    if settings_guard.is_patched():
        return True
    url = env.get("ANTHROPIC_BASE_URL")
    if not url:
        return False
    if settings_guard._is_self_reference(url):
        return True
    marker = settings_guard.read_marker()
    return bool(marker) and url == marker.get("listen")


# ===== 公开 API =====

def observe(path: Path | None = None, force: bool = False) -> dict | None:
    """watcher 每轮调：settings.json 变过就把当前 ANTHROPIC_* 组合收进历史。

    返回新记/更新的条目，或 None（没变 / 是我们自己 patch 的 / 自指）。
    `force=True` 跳过 mtime 门控（自测与「立即采集」用）。"""
    global _last_mtime
    p = path or CFG.CLAUDE_SETTINGS
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None                      # 文件不存在 → 无从采集（全新机器，patch 时才会创建）
    if not force and _last_mtime is not None and mt == _last_mtime:
        return None
    _last_mtime = mt
    return record(p)


def record(path: Path | None = None) -> dict | None:
    """把当前 settings.json 的 ANTHROPIC_* 组合记进历史（去重 + 上限）。"""
    p = path or CFG.CLAUDE_SETTINGS
    env = _extract_env(p)
    if _is_ours(env):
        # 我们 patch 进去的本地地址不是用户的上游配置；自指值更是绝不能进历史——
        # 否则「一键还原」会把 v0.3.0 那条无限递归锁死链**存档**下来，日后一键复现。
        return None
    fid = _fingerprint(env)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    items = _load()
    hit = next((it for it in items if it.get("id") == fid), None)
    if hit:
        hit["at"] = now
        hit["seen"] = int(hit.get("seen", 1)) + 1
        items = [hit] + [it for it in items if it is not hit]   # 移到最前 = 按最近出现排序
    else:
        hit = {"id": fid, "at": now, "seen": 1, "env": env}
        items = [hit] + items
        log.info("upstream history: 新增快照 %s（%d 个 ANTHROPIC_* 键，BASE_URL=%s）",
                 fid, len(env), env.get("ANTHROPIC_BASE_URL") or "（无键·订阅态）")
    items = items[:MAX_ITEMS]
    try:
        _save(items)
    except OSError as e:
        log.warning("upstream history 落盘失败: %s", e)   # 不上抛：采集失败不该拖垮 watcher
        return None
    return hit


def _token_of(env: dict) -> str | None:
    """这组 env 的凭据值（用于「哪条历史是当前这个供应商的干净版本」的判据）。"""
    for k in sorted(env):
        if any(h in k.lower() for h in _SECRET_HINTS):
            return env[k]
    return None


def list_entries(path: Path | None = None) -> list[dict]:
    """给 UI/API 的列表（token 已脱敏，明文永不出这个函数）。

    两个给前端做默认选中的标记：

    - `current=True`：与当前 settings.json 完全一致的那条——用户点开下拉第一眼要能分清
      「我现在在哪」和「我想回哪」。
    - `token_match=True`：**凭据与当前配置相同、但组合不同**的那条 = 同一个供应商的干净版本。
      这正是本功能要修的病的形状：cc-switch 在录制期间把我们 patch 的本地地址固化进了该供应商，
      于是切回来时 token 是对的、URL 是个早已关掉的本地端口。前端默认选中第一条
      `token_match` 就能做到真正的一键——用户不必自己认哪条对应哪个供应商。"""
    p = path or CFG.CLAUDE_SETTINGS
    cur_env = _extract_env(p)
    cur = _fingerprint(cur_env)
    cur_token = _token_of(cur_env)
    out = []
    for it in _load():
        env = it.get("env") or {}
        same = it.get("id") == cur
        out.append({
            "id": it.get("id"),
            "at": it.get("at"),
            "seen": int(it.get("seen", 1)),
            "base_url": env.get("ANTHROPIC_BASE_URL"),   # None = 订阅态（无键），前端出专门文案
            "keys": sorted(env.keys()),
            "env": {k: _mask(k, v) for k, v in sorted(env.items())},
            "has_token": any(any(h in k.lower() for h in _SECRET_HINTS) for k in env),
            "current": same,
            "token_match": bool(cur_token) and _token_of(env) == cur_token and not same,
        })
    return out


def current_state(path: Path | None = None) -> dict:
    """当前 settings.json 的上游状态 + **是否正处于「本地死地址」这个病态**。

    病的来路（260807 用户实测）：录制期间 BASE_URL 被 patch 成 `http://127.0.0.1:<port>`，
    cc-switch 此时切走会把这份带本地地址的配置**固化进它自己的供应商记录**；日后切回该供应商，
    写进 settings.json 的就是一个早已关掉的本地端口 —— 第三方 token 也好、官方订阅 OAuth 也好
    全部连不上，而表面上看配置"是好的"（有 URL 有 token），非常难认。

    `is_self=True`（地址正好等于本代理端口）时连代理都起不来：`snapshot_original` 的自指守卫
    会拒绝启动（否则 forward 转发给自己 → 无限递归 → 全 504）。所以修复入口**不能只挂在
    代理运行时**，必须在这个状态下照样可用——这是本功能的主战场。"""
    p = path or CFG.CLAUDE_SETTINGS
    env = _extract_env(p)
    url = env.get("ANTHROPIC_BASE_URL")
    is_local = bool(url) and settings_guard._is_local_proxy_url(url)
    return {
        "base_url": url,
        "is_local": is_local,
        "is_self": bool(url) and settings_guard._is_self_reference(url),
        # 前端据此决定「当前 BASE_URL」那行显示谁：录制中显示内存里的原上游（那行的文案是
        # "停止代理后恢复为原值"），没录制时显示**文件真值**——否则代理从未成功启动过时
        # （比如正是被这个病挡住了）内存快照是空的，那行会显示 "—"（实测）。
        "recording": settings_guard.is_patched(),
        # 代理正跑着时本地地址是**正常**的（就是我们写进去的），不该报病
        "needs_fix": is_local and not settings_guard.is_patched(),
        "in_history": _fingerprint(env) if any(it.get("id") == _fingerprint(env)
                                               for it in _load()) else None,
    }


def restore(entry_id: str, path: Path | None = None) -> dict:
    """把 settings.json 的 ANTHROPIC_* 命名空间对齐到指定快照。其余字段一律不动。

    **全量对齐而非逐字段写入**：删掉当前有、快照没有的键，再写入快照里的全部键。空集快照
    于是天然表达「回到官方订阅态」（把 BASE_URL/AUTH_TOKEN 删干净），这正是逐字段写入
    表达不了的那个状态（260718 的老伤：切订阅时 BASE_URL 未清理致 OAuth 失效）。"""
    if settings_guard.is_patched():
        # 录制中改上游配置会立刻被 watcher 判成外部接管并降旗，语义混乱 → 让用户先停代理
        raise HistoryError("proxy_running", "代理正在录制，请先停止代理再还原配置")
    entry = next((it for it in _load() if it.get("id") == entry_id), None)
    if entry is None:
        raise HistoryError("not_found", f"没有 id={entry_id} 的历史快照")
    target = {k: v for k, v in (entry.get("env") or {}).items() if k.startswith(ENV_PREFIX)}
    url = target.get("ANTHROPIC_BASE_URL")
    if url and settings_guard._is_self_reference(url):
        # 双保险：record 已经拦过一次，但历史文件可能是手改的/更早版本写的
        raise HistoryError("self_reference", f"快照的 BASE_URL={url} 指向本代理自身，拒绝还原")

    p = path or CFG.CLAUDE_SETTINGS
    backup = settings_guard.backup_file(p)
    data = settings_guard._read_settings(p)
    env = data.get("env")
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    removed = [k for k in list(env) if k.startswith(ENV_PREFIX) and k not in target]
    for k in removed:
        del env[k]
    added = [k for k in target if k not in env]
    updated = [k for k in target if k in env and env[k] != target[k]]
    env.update(target)
    settings_guard._atomic_write(p, data)
    log.info("upstream restore → %s：+%d 改%d 删%d（BASE_URL=%s）",
             entry_id, len(added), len(updated), len(removed),
             url or "（无键·订阅态）")
    return {
        "id": entry_id,
        "base_url": url,
        "added": sorted(added),
        "updated": sorted(updated),
        "removed": sorted(removed),
        "backup": str(backup) if backup else "",
    }


# ===== self-test（临时目录，不碰真 settings.json）=====

def self_test() -> None:
    import shutil
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="ccwa_hist_"))
    global HISTORY_FILE, _last_mtime
    old_hist = HISTORY_FILE
    HISTORY_FILE = tmpdir / "upstream_history.json"
    # settings_guard 的备份目录也必须重定向：`restore()` 会调 `backup_file()`，而那用的是
    # settings_guard 的**模块级** BACKUP_DIR ——不改的话自测会把临时假配置存进用户真实的
    # ~/.cc-wire-analyzer/backups/，既污染真备份，又可能把真备份挤出 MAX_BACKUPS 窗口
    # （首跑实测踩中）。"self-test 不碰真实位置"这句话，光重定向自己的文件是不够的。
    old_bkp = settings_guard.BACKUP_DIR
    settings_guard.BACKUP_DIR = tmpdir / "backups"
    old_marker = settings_guard._PATCHED_MARKER
    settings_guard._PATCHED_MARKER = tmpdir / ".patched"

    fake = tmpdir / "settings.json"
    GLM = {"ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
           "ANTHROPIC_AUTH_TOKEN": "glm-secret-token-1234", "ANTHROPIC_MODEL": "GLM-4.6"}
    KIMI = {"ANTHROPIC_BASE_URL": "https://api.moonshot.cn/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "kimi-secret-token-5678",
            "ANTHROPIC_MODEL": "kimi-k2-thinking"}
    OTHER = {"OTEL_LOGS_EXPORTER": "otlp", "CLAUDE_CODE_ENABLE_TELEMETRY": "1"}

    def write(env: dict, extra: dict | None = None) -> None:
        fake.write_text(json.dumps({
            "env": {**OTHER, **env},
            "model": "opus",
            "permissions": {"defaultMode": "auto"},
            **(extra or {}),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        settings_guard.set_self_listen_port(5051)

        # 1. 采集：三次不同配置 → 三条历史，最近的在最前
        write(GLM);  record(fake)
        write(KIMI); record(fake)
        write({});   record(fake)          # 订阅态（无 ANTHROPIC_* 键）
        items = _load()
        assert len(items) == 3, f"应有 3 条: {len(items)}"
        assert items[0]["env"] == {}, "最近一条应是订阅态（空集）"
        print(f"[1] 采集 OK: 3 条快照，最近的在最前 ✓")

        # 2. 内容寻址去重：切回 GLM 不新增条目，只更新 at/seen 并移到最前
        write(GLM); record(fake)
        items = _load()
        assert len(items) == 3, f"重复组合不该新增: {len(items)}"
        assert items[0]["env"] == GLM and items[0]["seen"] == 2, "命中应更新 seen 并移到最前"
        print(f"[2] 内容寻址去重 OK: 切回旧配置只更新 seen={items[0]['seen']}，不占新格 ✓")

        # 3. 上限 5 条：再造 4 个不同上游，最旧的被挤掉
        for i in range(4):
            write({"ANTHROPIC_BASE_URL": f"https://p{i}.example.com",
                   "ANTHROPIC_AUTH_TOKEN": f"tok{i}"})
            record(fake)
        items = _load()
        assert len(items) == MAX_ITEMS, f"上限应为 {MAX_ITEMS}: {len(items)}"
        assert all(it["env"] != KIMI for it in items), "最旧的 Kimi 应被挤掉"
        print(f"[3] 上限裁剪 OK: 留 {MAX_ITEMS} 条，最旧的被挤掉 ✓")

        # 4. 自指值不入历史（v0.3.0 无限递归锁死链绝不能被存档）
        write({"ANTHROPIC_BASE_URL": "http://127.0.0.1:5051"})
        assert record(fake) is None, "自指地址不该入历史"
        assert all(it["env"].get("ANTHROPIC_BASE_URL") != "http://127.0.0.1:5051"
                   for it in _load()), "历史里出现了自指值！"
        print(f"[4] 自指地址（本代理端口）不入历史 ✓")

        # 5. 合法本地上游（端口 ≠ 本代理）照收——不误伤本地 vLLM 等场景
        write({"ANTHROPIC_BASE_URL": "http://127.0.0.1:8080"})
        assert record(fake) is not None, "合法本地上游应入历史"
        print(f"[5] 合法本地上游（:8080）正常入历史 ✓")

        # 6. patch 态下不采集（那是我们自己写进去的地址）
        write({"ANTHROPIC_BASE_URL": "https://real-upstream.example.com"})
        settings_guard.snapshot_original(fake)
        settings_guard.patch_base_url("http://127.0.0.1:5051", fake)
        assert record(fake) is None, "patch 态下不该采集"
        settings_guard.restore(fake)
        print(f"[6] patch 态下不采集 ✓")

        # 7. token 永不出 API
        write(GLM); record(fake)
        listed = list_entries(fake)
        blob = json.dumps(listed, ensure_ascii=False)
        assert "glm-secret-token-1234" not in blob, "明文 token 出现在 list_entries 输出里！"
        cur = [e for e in listed if e["current"]]
        assert len(cur) == 1 and cur[0]["base_url"] == GLM["ANTHROPIC_BASE_URL"], \
            "current 标记应指向当前配置"
        assert cur[0]["has_token"] and "…" in cur[0]["env"]["ANTHROPIC_AUTH_TOKEN"]
        assert cur[0]["env"]["ANTHROPIC_MODEL"] == "GLM-4.6", "非凭据键不该被遮"
        print(f"[7] token 脱敏 OK: {cur[0]['env']['ANTHROPIC_AUTH_TOKEN']}，模型映射原样 ✓")

        # 8. 还原到别的 provider：整组换过去，无关字段一个不动
        kimi_id = _fingerprint(KIMI)
        write(KIMI); record(fake)          # 让 Kimi 重新进历史
        write(GLM)                         # 现在停在 GLM，要还原回 Kimi
        r = restore(kimi_id, fake)
        d = settings_guard._read_settings(fake)
        assert d["env"]["ANTHROPIC_BASE_URL"] == KIMI["ANTHROPIC_BASE_URL"]
        assert d["env"]["ANTHROPIC_AUTH_TOKEN"] == KIMI["ANTHROPIC_AUTH_TOKEN"], "token 没跟着回来！"
        assert d["env"]["ANTHROPIC_MODEL"] == KIMI["ANTHROPIC_MODEL"]
        assert d["env"]["OTEL_LOGS_EXPORTER"] == "otlp", "OTEL_* 被动了！"
        assert d["model"] == "opus" and d["permissions"]["defaultMode"] == "auto", "非 env 字段被动了！"
        assert r["updated"] and not r["removed"]
        print(f"[8] 还原到别的 provider OK: URL+token+模型整组回来，OTEL/permissions 未动 ✓")

        # 9. 还原到订阅态（空集快照）= 把 ANTHROPIC_* 删干净，而不是写任何 URL（260718 老伤）
        empty_id = _fingerprint({})
        write({}); record(fake)            # 空集在 case 3 的上限裁剪里被挤掉了，重新采一次
        write(KIMI)                        # 停回 KIMI，下面从 KIMI 还原到订阅态
        r9 = restore(empty_id, fake)
        d9 = settings_guard._read_settings(fake)
        assert not any(k.startswith(ENV_PREFIX) for k in d9["env"]), \
            f"订阅态还原后仍有 ANTHROPIC_* 键: {list(d9['env'])}"
        assert d9["env"]["OTEL_LOGS_EXPORTER"] == "otlp", "删键误伤 OTEL_*！"
        assert set(r9["removed"]) == set(KIMI.keys())
        print(f"[9] 还原到订阅态 OK: 删掉 {len(r9['removed'])} 个 ANTHROPIC_* 键，其余无损 ✓")

        # 10. 还原写前有备份
        assert r9["backup"] and Path(r9["backup"]).exists(), "还原前应留备份"
        print(f"[10] 还原前自动备份 OK: {Path(r9['backup']).name} ✓")

        # 11. 行尾符保持（CRLF 文件还原后仍是 CRLF——否则整文件 diff 污染用户的 git）
        crlf = tmpdir / "settings_crlf.json"
        crlf.write_bytes(json.dumps({"env": {**OTHER, **GLM}}, ensure_ascii=False,
                                    indent=2).replace("\n", "\r\n").encode("utf-8"))
        record(crlf)
        restore(_fingerprint(KIMI), crlf)
        raw = crlf.read_bytes()
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "CRLF 行尾符被改成 LF！"
        print(f"[11] 行尾符原样保持（CRLF）✓")

        # 12. patch 态下拒绝还原
        write(GLM)
        settings_guard.snapshot_original(fake)
        settings_guard.patch_base_url("http://127.0.0.1:5051", fake)
        raised = False
        try:
            restore(kimi_id, fake)
        except HistoryError as e:
            raised = e.code == "proxy_running"
        assert raised, "patch 态下应拒绝还原"
        assert settings_guard._read_base_url(fake) == "http://127.0.0.1:5051", "拒绝时不该动文件"
        settings_guard.restore(fake)
        print(f"[12] patch 态下拒绝还原、不动文件 ✓")

        # 13. 未知 id → not_found，且不碰文件
        before = fake.read_bytes()
        try:
            restore("deadbeef", fake)
            raise AssertionError("未知 id 应抛 HistoryError")
        except HistoryError as e:
            assert e.code == "not_found"
        assert fake.read_bytes() == before, "not_found 路径动了文件！"
        print(f"[13] 未知 id → not_found，文件未动 ✓")

        # 14. mtime 门控：没改文件就不重复读写；改了才采
        _last_mtime = None
        assert observe(fake) is not None, "首轮应采集"
        assert observe(fake) is None, "文件没变不该重复采集"
        time.sleep(0.01)
        write(KIMI)
        assert observe(fake) is not None, "文件变了应采集"
        print(f"[14] mtime 门控 OK: 未变跳过、变则采集 ✓")

        # 15. 历史文件损坏 → 降级为空，不炸（手改/写一半）
        HISTORY_FILE.write_text("{not json", encoding="utf-8")
        assert _load() == [] and list_entries(fake) == []
        print(f"[15] 历史文件损坏 → 降级为空，不抛 ✓")

        # 16. 本功能的主战场（260807 用户实测的病）：录制期间 cc-switch 把本地地址固化进供应商，
        #     日后切回该供应商 → token 是对的、URL 是个早已关掉的本地端口 → 全连不上。
        HISTORY_FILE.unlink()
        write(GLM); record(fake)                       # 干净的 GLM 进历史（录制开始前采到）
        polluted = dict(GLM, ANTHROPIC_BASE_URL="http://127.0.0.1:5051")
        write(polluted)                                # 切回 GLM，拿到的是被污染的那份
        assert record(fake) is None, "污染态（自指）不该入历史，否则病会被存档"
        st = current_state(fake)
        assert st["needs_fix"] and st["is_self"] and st["in_history"] is None, f"病态未识别: {st}"
        listed = list_entries(fake)
        m = [e for e in listed if e["token_match"]]
        assert len(m) == 1, f"应有且仅有 1 条 token 相同的干净快照: {len(m)}"
        assert m[0]["base_url"] == GLM["ANTHROPIC_BASE_URL"], "token_match 指错了条目"
        print(f"[16] 病态识别 OK: BASE_URL 是本机死地址 + 认出同 token 的干净快照 ✓")

        # 17. 一键修复：还原后病态消失，token/模型一个没丢
        r17 = restore(m[0]["id"], fake)
        d17 = settings_guard._read_settings(fake)
        assert d17["env"]["ANTHROPIC_BASE_URL"] == GLM["ANTHROPIC_BASE_URL"], "URL 没修回来"
        assert d17["env"]["ANTHROPIC_AUTH_TOKEN"] == GLM["ANTHROPIC_AUTH_TOKEN"]
        assert d17["env"]["OTEL_LOGS_EXPORTER"] == "otlp", "修复误伤 OTEL_*"
        assert current_state(fake)["needs_fix"] is False, "修复后仍报病态"
        assert r17["updated"] == ["ANTHROPIC_BASE_URL"], f"应只改 URL 一项: {r17['updated']}"
        print(f"[17] 一键修复 OK: 死地址 → 真上游，病态解除，其余字段无损 ✓")

        # 18. 订阅供应商被污染（260718 老伤的同源形态）：本来无 BASE_URL 键，被固化上了本地地址
        #     → 修复必须**删键**回到 OAuth 原状，写任何 URL 都是错的
        HISTORY_FILE.unlink()
        write({}); record(fake)                        # 干净的订阅态进历史
        write({"ANTHROPIC_BASE_URL": "http://127.0.0.1:5051"})   # 切回订阅，带着死地址
        assert current_state(fake)["needs_fix"], "订阅态污染未识别"
        r18 = restore(_fingerprint({}), fake)
        d18 = settings_guard._read_settings(fake)
        assert not any(k.startswith(ENV_PREFIX) for k in d18["env"]), "订阅态修复应把键删干净"
        assert r18["removed"] == ["ANTHROPIC_BASE_URL"] and not r18["added"]
        print(f"[18] 订阅供应商被污染 → 修复=删键回 OAuth 原状 ✓")

        print("\n[ALL PASSED] ✓")
    finally:
        HISTORY_FILE = old_hist
        settings_guard.BACKUP_DIR = old_bkp
        settings_guard._PATCHED_MARKER = old_marker
        _last_mtime = None
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    CFG.setup_logging()
    if "--self-test" in sys.argv:
        # 显式捕获 + 打印：`CFG.setup_logging()` 装的 excepthook 只把未捕获异常写进 run.log，
        # **不打 stderr**——于是自测失败时终端一片空白只留 exit=1，得去翻日志才知道断在哪
        # （首跑实测踩中）。对一个自测入口来说这就是惯犯 ③「静默吞异常」的形状。
        import traceback
        try:
            self_test()
        except Exception:
            traceback.print_exc()
            print("\n[FAILED] ✗", file=sys.stderr)
            sys.exit(1)
    else:
        print("用法: python upstream_history.py --self-test")
