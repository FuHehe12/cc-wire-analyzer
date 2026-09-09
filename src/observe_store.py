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
_GOAL_ITERATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class ObserveError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _now() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def _validate(oid: str) -> None:
    """id 直接拼文件名，形状必须验（同 `date` 那条，防路径穿越）。"""
    if not isinstance(oid, str) or not _ID_RE.fullmatch(oid):
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


PREVIEW_MAX = 60


def _preview(items: list) -> str:
    """列表里认得出是哪场对话的一句话。**title 可省，所以不能只靠 title**——
    外环建观测时常常不写标题，界面全变成「未命名观测」，同一天几条根本分不开。
    这里只从已保存的事实里回落，不生成新说法：当前理解 → A 的用户原话 → 首条正文。"""
    live = [i for i in items if i.get("status") != "retracted"]
    flow = next((i["goal_flow"] for i in live if isinstance(i.get("goal_flow"), dict)), {})
    text = ((flow.get("current") or {}).get("understanding")
            or (flow.get("anchor") or {}).get("user_text")
            or next((i.get("title") or i.get("text") or "" for i in live), ""))
    text = " ".join(str(text).split())
    return text[:PREVIEW_MAX - 1] + "…" if len(text) > PREVIEW_MAX else text


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
            "preview": _preview(items), "has_flow": any(
                "goal_flow" in i and i.get("status") != "retracted" for i in items),
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
    check_fields(scope, {"date", "source", "lane", "session"}, "scope")
    if any(not isinstance(v, str) for v in scope.values()) or not isinstance(title, str):
        raise ObserveError("bad_payload", "scope 各字段与 title 必须为字符串")
    if len(title) > TITLE_MAX:
        raise ObserveError("bad_title", f"title 最多 {TITLE_MAX} 字符")
    return _write({
        "id": oid, "title": title,
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


# Only fields actually consumed by the store are accepted. HTTP expands cover_span
# into covers before entering here; misplaced or misspelled fields cannot succeed.
ITEM_FIELDS = {"kind", "text", "status", "evidence", "title", "progress", "covers", "forecast", "goal_flow", "goal_iteration"}
PATCH_FIELDS = ITEM_FIELDS | {"goal_flow_delta"}
OP_FIELDS = {
    "add_item": ITEM_FIELDS | {"op", "client_ref"},
    "update_item": {"op", "id", "patch"},
    "retract_item": {"op", "id", "reason"},
    "link_items": {"op", "from", "to", "type", "remove"},
    "set_cursor": {"op", "cursor"},
    "rebuild_goal_flow": {"op", "id", "reason", "goal_flow"},
}
REASON_MAX = 1000
REBUILDS_MAX = 20


def check_fields(data, allowed, context):
    if not isinstance(data, dict):
        raise ObserveError("bad_payload", f"{context} 必须为对象")
    unknown = set(data) - allowed
    if unknown:
        raise ObserveError("unknown_field", f"{context} 未知字段：{', '.join(sorted(unknown))}")


def _check_op(op):
    if not isinstance(op, dict):
        raise ObserveError("bad_op", "每个操作必须是对象")
    kind = op.get("op")
    if not isinstance(kind, str) or kind not in OP_FIELDS:
        raise ObserveError("bad_op", f"未知操作：{kind}")
    check_fields(op, OP_FIELDS[kind], kind)
    data = op
    if kind == "update_item":
        data = op.get("patch")
        check_fields(data, PATCH_FIELDS, "update_item.patch")
        if not data:
            raise ObserveError("empty_patch", "update_item.patch 不能为空")
    for field in ({"id"} if kind in ("update_item", "retract_item", "rebuild_goal_flow") else
                  {"from", "to"} if kind == "link_items" else set()):
        if not isinstance(op.get(field), str) or not op[field].strip():
            raise ObserveError("bad_reference", f"{kind}.{field} 必须为非空字符串")
    for field, values, code in (("kind", ITEM_KINDS, "bad_kind"), ("status", ITEM_STATUS, "bad_status")):
        if field in data and (not isinstance(data[field], str) or data[field] not in values):
            raise ObserveError(code, f"{field} 必须为 {values} 之一")
    if "type" in op and (not isinstance(op["type"], str) or op["type"] not in LINK_TYPES):
        raise ObserveError("bad_link", f"type 必须为 {LINK_TYPES} 之一")
    if "text" in data and isinstance(data["text"], str) and len(data["text"].strip()) > 4000:
        raise ObserveError("bad_text", "text 最多4000字符，超限请拆分或缩短，不能静默截断")
    if "evidence" in data and (not isinstance(data["evidence"], list) or len(data["evidence"]) > 50 or
            any(not isinstance(x, str) or not _RID_RE.fullmatch(x) for x in data["evidence"])):
        raise ObserveError("bad_evidence", "evidence 必须为最多50项的请求 ID 字符串数组")
    if "reason" in op and (not isinstance(op["reason"], str) or len(op["reason"].strip()) > REASON_MAX):
        raise ObserveError("bad_reason", f"reason 必须为最多{REASON_MAX}字符的字符串")
    # 重建是覆盖判断，理由不能省：没有它，界面上无法解释这版 A→G 为什么替换了上一版。
    if kind == "rebuild_goal_flow" and not (op.get("reason") or "").strip():
        raise ObserveError("bad_reason", "rebuild_goal_flow.reason 必填：说明为什么重建这份 A→G")
    if "remove" in op and type(op["remove"]) is not bool:
        raise ObserveError("bad_link", "remove 必须为布尔值")
    if kind == "set_cursor" and (type(op.get("cursor")) is not int or op["cursor"] < 0):
        raise ObserveError("bad_cursor", "set_cursor.cursor 必须为非负整数")
    if "client_ref" in op and (not isinstance(op["client_ref"], str) or
            not op["client_ref"].strip() or op["client_ref"] != op["client_ref"].strip() or
            op["client_ref"].startswith("i_")):
        raise ObserveError("bad_reference", "client_ref 必须为非空短名，不能以 i_ 开头或含首尾空格")


def _persistent_refs(state):
    """Migrate surviving legacy submit refs; never choose a winner for old collisions."""
    refs = dict(state.get("refs") or {})
    for rec in state.get("submits") or []:
        for name, iid in (rec.get("refs") or {}).items():
            if name in refs and refs[name] != iid:
                refs[name] = None
            else:
                refs[name] = iid
    return refs


def _semantic_fields(data: dict, kind: str, previous: dict | None = None) -> dict:
    """Optional graph fields; missing keys preserve legacy records unchanged.

    covers is explicit membership, not evidence or an inferred min/max interval.
    Validate shape here; existence and scope membership require the recording read
    layer. A forecast records the observer's declared boundary, not enforced blindness.
    """
    out = {}
    if "goal_iteration" in data:
        iteration = data["goal_iteration"]
        if not isinstance(iteration, str) or (iteration and not _GOAL_ITERATION_RE.fullmatch(iteration)):
            raise ObserveError("bad_goal_iteration", "goal_iteration 必须为1..64字符的迭代 ID，或用空串清除关联")
        if iteration and kind == "goal":
            raise ObserveError("bad_goal_iteration", "goal_iteration 只允许关联非 goal 条目")
        out["goal_iteration"] = iteration
    if "goal_flow" in data and "goal_flow_delta" in data:
        raise ObserveError("bad_goal_flow", "goal_flow 与 goal_flow_delta 不可同时提供")
    if "goal_flow" in data or "goal_flow_delta" in data:
        if kind != "goal":
            raise ObserveError("bad_goal_flow", "goal_flow 只允许用于 goal 条目")
        import observe_goal
        out["goal_flow"] = (observe_goal.apply_delta(previous, data["goal_flow_delta"])
                            if "goal_flow_delta" in data else
                            observe_goal.validate(data["goal_flow"], previous=previous))
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
    ev = list(op.get("evidence") or [])
    extra = _semantic_fields(op, kind)
    if "forecast" in extra and len(text) > 4000:
        raise ObserveError("bad_forecast", "带 forecast 的预测正文最多 4000 字符，不能截断原预测")
    return {
        "id": "i_" + uuid.uuid4().hex[:6], "kind": kind, "text": text,
        "status": st, "evidence": ev, "links": [], "history": [],
        "created": now, "updated": now, "rev": 1,
        **extra,
    }


def apply(oid: str, submission_id: str, base_revision, ops: list) -> dict:
    """一批操作原子落盘。返回 `{state, refs, replayed}`。

    `refs` 返回本批新建 client_ref → id。名称在观测内持久、唯一，后续批次可直接
    引用；旧流水中的重名不猜归属，要求调用方改用真实 id。
    """
    if not isinstance(ops, list) or not ops:
        raise ObserveError("empty_ops", "ops 不能为空")
    if len(ops) > 200:
        raise ObserveError("too_many", "一批最多 200 个操作")
    if not isinstance(submission_id, str) or not submission_id.strip():
        raise ObserveError("no_submission", "缺 submission_id（幂等靠它，不能省）")
    with _LOCK:
        s = read(oid)
        if s is None:
            raise ObserveError("not_found", f"观测不存在：{oid}")
        # 幂等：同一个 submission 重放，原样退回当前状态，不重复建条目
        for rec in s.get("submits") or []:
            if rec.get("sid") == submission_id:
                return {"state": s, "refs": rec.get("refs") or {}, "replayed": True, "changed_ids": rec.get("changed_ids", [i["id"] for i in s.get("items", [])])}
        if base_revision is not None:
            if type(base_revision) is not int or base_revision < 0:
                raise ObserveError("bad_revision", "base_revision 必须为非负整数")
            base = base_revision
            if base != s.get("revision", 0):
                raise ObserveError(
                    "conflict",
                    f"base_revision={base} 与当前 revision={s.get('revision', 0)} 不符，"
                    "请重读当前状态再合并")

        now = _now()
        items = {i["id"]: i for i in s.get("items") or []}
        order = [i["id"] for i in s.get("items") or []]
        refs: dict = {}
        persistent_refs = _persistent_refs(s)
        before_items = deepcopy(items)

        def _resolve(x):
            """条目引用：既认真实 id，也认本批的 client_ref。"""
            if x in persistent_refs:
                target = persistent_refs[x]
                if target is None or (x in items and x != target):
                    raise ObserveError("ambiguous_ref", f"client_ref 对应多个条目，请使用真实 id：{x}")
                return target
            return x

        for op in ops:
            _check_op(op)
            kind = op.get("op")
            if kind == "add_item":
                it = _new_item(op, now)
                items[it["id"]] = it
                order.append(it["id"])
                if op.get("client_ref"):
                    name = op["client_ref"]
                    if name in persistent_refs or name in items:
                        raise ObserveError("duplicate_ref", f"client_ref 已被使用：{name}；更新请用 update_item")
                    refs[name] = persistent_refs[name] = it["id"]
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
                        it["reason"] = op["reason"].strip()
                else:
                    patch = op.get("patch") or {}
                    if not isinstance(patch, dict):
                        raise ObserveError("bad_op", "patch 必须为对象")
                    new_kind = patch.get("kind", it.get("kind"))
                    if new_kind == "goal" and patch.get("goal_iteration", it.get("goal_iteration")):
                        raise ObserveError("bad_goal_iteration", "改为 goal 前必须清除 goal_iteration，可在同一 patch 中写空串")
                    if "goal_flow" in it and new_kind != "goal":
                        raise ObserveError("goal_flow_locked", "已有 goal_flow 的条目不能修改 kind；请撤回后新建")
                    extra = _semantic_fields(patch, new_kind, previous=it.get("goal_flow"))
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
                        it["text"] = t
                    if "status" in patch:
                        if patch["status"] not in ITEM_STATUS:
                            raise ObserveError("bad_status", f"status 非法：{patch['status']}")
                        it["status"] = patch["status"]
                    if "kind" in patch:
                        if patch["kind"] not in ITEM_KINDS:
                            raise ObserveError("bad_kind", f"kind 非法：{patch['kind']}")
                        it["kind"] = patch["kind"]
                    if "evidence" in patch:
                        it["evidence"] = list(patch["evidence"])
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
                exists = any(l.get("to") == b and l.get("type") == rel for l in links)
                removing = op.get("remove", False)
                if removing and not exists:
                    raise ObserveError("no_link", f"关系不存在：{a} --{rel}--> {b}")
                if removing or not exists:
                    _remember(items[a])
                    if removing:
                        items[a]["links"] = [l for l in links if not (l.get("to") == b and l.get("type") == rel)]
                    else:
                        links.append({"type": rel, "to": b})
                    items[a]["rev"] = items[a].get("rev", 1) + 1
                    items[a]["updated"] = now
            elif kind == "rebuild_goal_flow":
                # 冻结的目的是「改判要留痕」，不是「永远不能重来」。外环第一次把 A→G 建歪，
                # 或旧观测结构过时，此前只能整条删掉重建——连 cursor、条目和历史一起丢。
                # 这里保留同一个目的：旧结构整版压进 history，理由必填，界面显式标注已重建。
                tid = _resolve(op.get("id"))
                it = items.get(tid)
                if it is None:
                    raise ObserveError("no_item", f"条目不存在：{op.get('id')}")
                if it.get("kind") != "goal" or "goal_flow" not in it:
                    raise ObserveError("bad_goal_flow", "rebuild_goal_flow 只能用于已有 goal_flow 的 goal 条目；首次建立请用 add_item.goal_flow")
                import observe_goal
                rebuilt = observe_goal.validate(op.get("goal_flow"))   # 独立校验，不与旧结构比前缀
                _remember(it)
                it["goal_flow"] = rebuilt
                it.setdefault("rebuilds", []).append(
                    {"at": now, "reason": op["reason"].strip(), "from_rev": it.get("rev", 1)})
                it["rebuilds"] = it["rebuilds"][-REBUILDS_MAX:]
                it["rev"] = it.get("rev", 1) + 1
                it["updated"] = now
            elif kind == "set_cursor":
                try:
                    s["cursor"] = max(0, int(op.get("cursor") or 0))
                except (TypeError, ValueError):
                    raise ObserveError("bad_cursor", f"cursor 不是数字：{op.get('cursor')}")
            else:
                raise ObserveError("bad_op", f"未知操作：{kind}")

        active_flows = [it["goal_flow"] for it in items.values()
                        if "goal_flow" in it and it.get("status") != "retracted"]
        if len(active_flows) > 1:
            raise ObserveError("multiple_goal_flows", "一个观测最多保留一个未撤回的 goal_flow；演变请追加其 iterations")
        # Validate the final batch, so an item may precede the flow/iteration it
        # references. Retraction must not strand live work on an invisible goal.
        iteration_ids = {entry["id"] for flow in active_flows for entry in flow["iterations"]}
        for it in items.values():
            iteration = it.get("goal_iteration")
            if it.get("status") != "retracted" and iteration:
                if it.get("kind") == "goal" or iteration not in iteration_ids:
                    raise ObserveError("bad_goal_iteration",
                        f"条目 {it['id']} 的 goal_iteration={iteration} 未指向当前活跃目标流；请清除、改关联或撤回条目")
        changed_ids = [i for i in order if items[i] != before_items.get(i)]
        s["refs"] = persistent_refs
        s["items"] = [items[i] for i in order]
        s["revision"] = s.get("revision", 0) + 1
        s["updated"] = now
        # 提交流水与状态**在同一次原子替换里落盘**：分两次写，中间挂掉就会出现
        # 「水位前移了、状态没保存」或反过来。
        s.setdefault("submits", []).append({"sid": submission_id, "at": now,
                                            "rev": s["revision"], "refs": refs, "changed_ids": changed_ids})
        s["submits"] = s["submits"][-SUBMITS_MAX:]
        _write(s)
        return {"state": s, "refs": refs, "replayed": False, "changed_ids": changed_ids}
