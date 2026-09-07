"""外环观测状态：另一个 AI 一边跟踪一边维护的清单，存这里。

**内外环**：内环是被观测的 agent 自己那圈（跑活、调工具）；外环是另开的一个 AI，
只干「它做了什么 / 在做什么 / 接下来要做什么」。外环跑在外部宿主上，读 `/api/actions`
拿会话全文，判断完把结论**小批量**写回来——CCWA 负责事实、持久化和显示，不负责跑模型。

**为什么是文件不是数据库**：整个项目至今没有任何数据库（jsonl + 旁路索引 + 原子替换的
派生物），打包 / 归档 / 压实 / 清理四个现成工具都不认识数据库。首版单写者、条目撑死几百条，
原子替换 + 一份提交流水就满足幂等与事务要求。操作只有五种，形状稳了再迁移不亏。

**三条不许破的线**（外环是另一个进程、会重连、会重试）：

1. **幂等**：同一个 `submission_id` 重放返回原结果、不重复建条目。网络超时后的重试是常态，
   不是异常。
2. **版本冲突不静默覆盖**：提交带 `base_revision`，对不上就退回当前状态让调用方重新合并。
   首版只有一个写者，但恢复出第二个宿主是迟早的事。
3. **改判要回改原条目并留痕**：只追加不回改，最新结论会被埋在中间——可研第十节那条。
   `history` 留最近若干版，界面默认显示当前版。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path

import config as CFG

log = logging.getLogger("ccwa.observe")

OBS_DIR = CFG.CONFIG_DIR / "observations"
_LOCK = threading.Lock()

# 一条条目最多留几版历史。不留会丢改判过程（「它一开始以为是 A，什么时候改判成 B 的」
# 正是可研第四类问法），无上限留会让长会话的状态文件无限涨。
HISTORY_MAX = 20
# 提交流水最多记几条。幂等只需要认得出「最近重试的那一批」，不是审计账本。
SUBMITS_MAX = 200
ITEM_KINDS = ("phase", "finding", "open", "prediction", "deviation", "goal", "artifact", "check")
ITEM_STATUS = ("tentative", "supported", "unresolved", "retracted")
ITEM_PROGRESS = ("planned", "active", "blocked", "done", "unknown")
COVERS_MAX = 2000
TITLE_MAX = 200
FORECAST_HORIZON_MAX = 5000
FORECAST_CRITERION_MAX = 2000
LINK_TYPES = ("belongs_to", "depends_on", "produces", "supports", "contradicts")
_ID_RE = re.compile(r"^obs_[0-9a-f]{7}$")
_RID_RE = re.compile(r"req_[A-Za-z0-9_-]{1,124}\Z")


class ObserveError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _now() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def _validate(oid: str) -> None:
    """id 直接拼文件名，形状必须验（同 `date` 那条，防路径穿越）。"""
    if not _ID_RE.match(oid or ""):
        raise ObserveError("bad_id", f"观测 id 形状不对：{oid}")


def _file(oid: str) -> Path:
    _validate(oid)
    return OBS_DIR / f"{oid}.json"


def _write(state: dict) -> dict:
    """原子替换。**先写临时文件再 rename**：直接覆盖时进程被杀会留下半截 JSON，
    下次读就是「状态整个不见了」，而界面上看不出任何异常（惯犯：静默丢数据）。"""
    OBS_DIR.mkdir(parents=True, exist_ok=True)
    oid = state["id"]
    tmp = OBS_DIR / f".{oid}.writing"
    try:
        tmp.write_bytes(json.dumps(state, ensure_ascii=False).encode("utf-8"))
        tmp.replace(_file(oid))
    except OSError as e:
        raise ObserveError("write_failed", f"观测状态写入失败：{e}")
    return state


def read(oid: str) -> dict | None:
    f = _file(oid)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("观测状态读不出来 %s: %s", oid, e)   # 坏文件如实报，不当成空
        raise ObserveError("unreadable", f"观测状态损坏：{e}")


def listing() -> list[dict]:
    """所有观测的摘要（不带条目正文）。按最近更新倒序。"""
    out: list[dict] = []
    if not OBS_DIR.exists():
        return out
    for f in OBS_DIR.glob("obs_*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue        # 单个坏文件不该让整张列表打不开
        items = s.get("items") or []
        out.append({
            "id": s.get("id"), "title": s.get("title") or "",
            "scope": s.get("scope") or {}, "revision": s.get("revision", 0),
            "cursor": s.get("cursor", 0), "updated": s.get("updated"),
            "n_items": sum(1 for i in items if i.get("status") != "retracted"),
            "n_retracted": sum(1 for i in items if i.get("status") == "retracted"),
        })
    out.sort(key=lambda x: x.get("updated") or "", reverse=True)
    return out


def create(scope: dict, title: str = "") -> dict:
    oid = "obs_" + uuid.uuid4().hex[:7]
    now = _now()
    scope = scope or {}
    return _write({
        "id": oid, "title": (title or "")[:200],
        "scope": {
            "date": str(scope.get("date") or ""), "source": str(scope.get("source") or ""),
            "lane": str(scope.get("lane") or ""), "session": str(scope.get("session") or ""),
        },
        "created": now, "updated": now, "revision": 0, "cursor": 0,
        "items": [], "submits": [],
    })


def delete(oid: str) -> dict:
    f = _file(oid)
    if not f.exists():
        raise ObserveError("not_found", f"观测不存在：{oid}")
    try:
        f.unlink()
    except OSError as e:
        raise ObserveError("write_failed", f"删除失败：{e}")
    return {"id": oid, "deleted": True}


def _semantic_fields(data: dict, kind: str) -> dict:
    """Optional graph fields; missing keys preserve legacy records unchanged.

    covers is explicit membership, not evidence or an inferred min/max interval.
    Validate shape here; existence and scope membership require the recording read
    layer. A forecast records the observer's declared boundary, not enforced blindness.
    """
    out = {}
    if "title" in data:
        title = data["title"]
        if not isinstance(title, str) or len(title.strip()) > TITLE_MAX:
            raise ObserveError("bad_title", f"title 必须为最多 {TITLE_MAX} 字符的字符串")
        out["title"] = title.strip()  # empty string clears the optional short title
    if "progress" in data:
        progress = data["progress"]
        if not isinstance(progress, str) or progress not in ITEM_PROGRESS:
            raise ObserveError("bad_progress", f"progress 必须为 {ITEM_PROGRESS} 之一")
        out["progress"] = progress
    if "covers" in data:
        covers = data["covers"]
        if not isinstance(covers, list) or len(covers) > COVERS_MAX:
            raise ObserveError("bad_covers", f"covers 必须为最多 {COVERS_MAX} 项的请求 ID 数组")
        if any(not isinstance(rid, str) or not _RID_RE.fullmatch(rid) for rid in covers):
            raise ObserveError("bad_covers", "covers 每项必须为 req_ 开头的有效请求 ID")
        out["covers"] = list(dict.fromkeys(covers))  # preserve first-occurrence order
    if "forecast" in data:
        f = data["forecast"]
        if kind != "prediction" or not isinstance(f, dict):
            raise ObserveError("bad_forecast", "forecast 只允许用于 prediction，且必须为对象")
        if set(f) != {"after_rid", "horizon_steps", "criterion"}:
            raise ObserveError("bad_forecast", "forecast 必须且只能含 after_rid/horizon_steps/criterion")
        if not isinstance(f["after_rid"], str) or not _RID_RE.fullmatch(f["after_rid"]):
            raise ObserveError("bad_forecast", "after_rid 必须为有效请求 ID")
        horizon = f["horizon_steps"]
        if type(horizon) is not int or not 1 <= horizon <= FORECAST_HORIZON_MAX:
            raise ObserveError("bad_forecast", f"horizon_steps 必须为 1..{FORECAST_HORIZON_MAX} 的整数")
        criterion = f["criterion"]
        if (not isinstance(criterion, str) or not criterion.strip()
                or len(criterion.strip()) > FORECAST_CRITERION_MAX):
            raise ObserveError("bad_forecast", f"criterion 必须为 1..{FORECAST_CRITERION_MAX} 字符的判断条件")
        out["forecast"] = dict(f, criterion=criterion.strip())
    return out


def _remember(it: dict) -> None:
    """Keep the complete previous item, without recursively copying its history."""
    previous = deepcopy({k: v for k, v in it.items() if k != "history"})
    previous["at"] = it.get("updated")  # retain the legacy history timestamp contract
    it.setdefault("history", []).append(previous)
    it["history"] = it["history"][-HISTORY_MAX:]


def _new_item(op: dict, now: str) -> dict:
    kind = op.get("kind") or "finding"
    if kind not in ITEM_KINDS:
        raise ObserveError("bad_kind", f"kind 非法：{kind}")
    if not isinstance(op.get("text", ""), str):
        raise ObserveError("empty_text", "条目正文必须为非空字符串")
    text = (op.get("text") or "").strip()
    if not text:
        raise ObserveError("empty_text", "条目正文不能为空")
    st = op.get("status") or "tentative"
    if st not in ITEM_STATUS:
        raise ObserveError("bad_status", f"status 非法：{st}")
    ev = [str(x) for x in (op.get("evidence") or []) if str(x).strip()][:50]
    extra = _semantic_fields(op, kind)
    if "forecast" in extra and len(text) > 4000:
        raise ObserveError("bad_forecast", "带 forecast 的预测正文最多 4000 字符，不能截断原预测")
    return {
        "id": "i_" + uuid.uuid4().hex[:6], "kind": kind, "text": text[:4000],
        "status": st, "evidence": ev, "links": [], "history": [],
        "created": now, "updated": now, "rev": 1,
        **extra,
    }


def apply(oid: str, submission_id: str, base_revision, ops: list) -> dict:
    """一批操作原子落盘。返回 `{state, refs, replayed}`。

    `refs` 是本批 `client_ref` → 真实 id 的对照表。**client_ref 是为了省一轮往返**：
    新建条目又要立刻关联它时，调用方不必先提交一次拿 id、再提交第二次，同一批里用自己
    起的临时名指代即可。
    """
    if not isinstance(ops, list) or not ops:
        raise ObserveError("empty_ops", "ops 不能为空")
    if len(ops) > 200:
        raise ObserveError("too_many", "一批最多 200 个操作")
    if not (submission_id or "").strip():
        raise ObserveError("no_submission", "缺 submission_id（幂等靠它，不能省）")
    with _LOCK:
        s = read(oid)
        if s is None:
            raise ObserveError("not_found", f"观测不存在：{oid}")
        # 幂等：同一个 submission 重放，原样退回当前状态，不重复建条目
        for rec in s.get("submits") or []:
            if rec.get("sid") == submission_id:
                return {"state": s, "refs": rec.get("refs") or {}, "replayed": True}
        if base_revision is not None:
            try:
                base = int(base_revision)
            except (TypeError, ValueError):
                raise ObserveError("bad_revision", f"base_revision 不是数字：{base_revision}")
            if base != s.get("revision", 0):
                raise ObserveError(
                    "conflict",
                    f"base_revision={base} 与当前 revision={s.get('revision', 0)} 不符，"
                    "请重读当前状态再合并")

        now = _now()
        items = {i["id"]: i for i in s.get("items") or []}
        order = [i["id"] for i in s.get("items") or []]
        refs: dict = {}

        def _resolve(x):
            """条目引用：既认真实 id，也认本批的 client_ref。"""
            return refs.get(str(x), str(x))

        for op in ops:
            if not isinstance(op, dict):
                raise ObserveError("bad_op", "每个操作必须是对象")
            kind = op.get("op")
            if kind == "add_item":
                it = _new_item(op, now)
                items[it["id"]] = it
                order.append(it["id"])
                if op.get("client_ref"):
                    refs[str(op["client_ref"])] = it["id"]
            elif kind in ("update_item", "retract_item"):
                tid = _resolve(op.get("id"))
                it = items.get(tid)
                if it is None:
                    raise ObserveError("no_item", f"条目不存在：{op.get('id')}")
                # 改判要留痕：把当前版压进 history 再改（可研第十节）
                _remember(it)
                if kind == "retract_item":
                    it["status"] = "retracted"
                    if (op.get("reason") or "").strip():
                        it["reason"] = op["reason"].strip()[:1000]
                else:
                    patch = op.get("patch") or {}
                    if not isinstance(patch, dict):
                        raise ObserveError("bad_op", "patch 必须为对象")
                    new_kind = patch.get("kind", it.get("kind"))
                    extra = _semantic_fields(patch, new_kind)
                    if "forecast" in it:
                        if (new_kind != "prediction"
                                or ("text" in patch and patch["text"] != it.get("text"))
                                or ("forecast" in extra and extra["forecast"] != it["forecast"])):
                            raise ObserveError("forecast_locked", "原预测正文和 forecast 不可改写；请撤回后新建预测")
                    if "text" in patch:
                        if not isinstance(patch["text"], str):
                            raise ObserveError("empty_text", "条目正文必须为非空字符串")
                        t = (patch.get("text") or "").strip()
                        if not t:
                            raise ObserveError("empty_text", "条目正文不能为空")
                        if ("forecast" in it or "forecast" in extra) and len(t) > 4000:
                            raise ObserveError("bad_forecast", "带 forecast 的预测正文最多 4000 字符")
                        it["text"] = t[:4000]
                    if "status" in patch:
                        if patch["status"] not in ITEM_STATUS:
                            raise ObserveError("bad_status", f"status 非法：{patch['status']}")
                        it["status"] = patch["status"]
                    if "kind" in patch:
                        if patch["kind"] not in ITEM_KINDS:
                            raise ObserveError("bad_kind", f"kind 非法：{patch['kind']}")
                        it["kind"] = patch["kind"]
                    if "evidence" in patch:
                        it["evidence"] = [str(x) for x in (patch["evidence"] or [])
                                          if str(x).strip()][:50]
                    it.update(extra)
                it["rev"] = it.get("rev", 1) + 1
                it["updated"] = now
            elif kind == "link_items":
                a, b = _resolve(op.get("from")), _resolve(op.get("to"))
                if a not in items or b not in items:
                    raise ObserveError("no_item",
                                       f"关联的条目不存在：{op.get('from')} → {op.get('to')}")
                rel = op.get("type") or "belongs_to"
                if rel not in LINK_TYPES:
                    raise ObserveError("bad_link", f"关系类型非法：{rel}")
                links = items[a].setdefault("links", [])
                if not any(l.get("to") == b and l.get("type") == rel for l in links):
                    _remember(items[a])
                    links.append({"type": rel, "to": b})
                    items[a]["rev"] = items[a].get("rev", 1) + 1
                items[a]["updated"] = now
            elif kind == "set_cursor":
                try:
                    s["cursor"] = max(0, int(op.get("cursor") or 0))
                except (TypeError, ValueError):
                    raise ObserveError("bad_cursor", f"cursor 不是数字：{op.get('cursor')}")
            else:
                raise ObserveError("bad_op", f"未知操作：{kind}")

        s["items"] = [items[i] for i in order]
        s["revision"] = s.get("revision", 0) + 1
        s["updated"] = now
        # 提交流水与状态**在同一次原子替换里落盘**：分两次写，中间挂掉就会出现
        # 「水位前移了、状态没保存」或反过来。
        s.setdefault("submits", []).append({"sid": submission_id, "at": now,
                                            "rev": s["revision"], "refs": refs})
        s["submits"] = s["submits"][-SUBMITS_MAX:]
        _write(s)
        return {"state": s, "refs": refs, "replayed": False}
