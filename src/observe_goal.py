"""Explicit, evidence-backed A→G records. This module never infers a goal.

The anchor and recorded iterations are append-only. Corrections, closure and
unresolved work are new iterations referencing the earlier ones. Evidence IDs
are checked for shape here, not existence or semantic support in the recording.
"""

from __future__ import annotations

import re

TEXT_MAX = 4000
ITERATIONS_MAX = 200
EVIDENCE_MAX = 50
CHOICES_MAX = 20
CHOICE_MAX = 1000
PARENTS_MAX = 20
_RID = re.compile(r"req_[A-Za-z0-9_-]{1,124}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _error(detail: str, code: str = "bad_goal_flow"):
    # observe_store calls validate; importing only on failure avoids a cycle.
    from observe_store import ObserveError
    raise ObserveError(code, detail)


def _object(value, required: set, optional: set, path: str) -> dict:
    if not isinstance(value, dict):
        _error(f"{path} 必须为对象")
    if set(value) - required - optional or required - set(value):
        _error(f"{path} 缺少必填字段或含未知字段；必填：{', '.join(sorted(required))}")
    return value


def _text(value, path: str, limit: int = TEXT_MAX) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _error(f"{path} 必须为非空字符串，最多 {limit} 字符")
    # Preserve quotes verbatim, including whitespace: this is evidence, not copy.
    return value


def _enum(value, allowed: tuple, path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        _error(f"{path} 必须为 {' / '.join(allowed)}")
    return value


def _evidence(value, path: str) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= EVIDENCE_MAX:
        _error(f"{path} 必须含 1..{EVIDENCE_MAX} 个请求 ID")
    if any(not isinstance(rid, str) or not _RID.fullmatch(rid) for rid in value):
        _error(f"{path} 每项必须为 req_ 开头的请求 ID")
    if len(set(value)) != len(value):
        _error(f"{path} 不可含重复请求 ID")
    return list(value)


def _normalize(value) -> dict:
    flow = _object(value, {"anchor", "iterations"}, set(), "goal_flow")
    raw = _object(flow["anchor"], {"user_text", "understanding", "evidence", "basis"},
                  {"choices"}, "anchor")
    choices = raw.get("choices", [])
    if not isinstance(choices, list) or len(choices) > CHOICES_MAX:
        _error(f"anchor.choices 必须为最多 {CHOICES_MAX} 项的数组")
    anchor = {
        "user_text": _text(raw["user_text"], "anchor.user_text"),
        "understanding": _text(raw["understanding"], "anchor.understanding"),
        "choices": [_text(c, "anchor.choices", CHOICE_MAX) for c in choices],
        "evidence": _evidence(raw["evidence"], "anchor.evidence"),
        "basis": _enum(raw["basis"], ("inferred", "explicit"), "anchor.basis"),
    }
    iterations = flow["iterations"]
    if not isinstance(iterations, list) or len(iterations) > ITERATIONS_MAX:
        _error(f"iterations 必须为最多 {ITERATIONS_MAX} 项的数组")
    out, seen = [], set()
    for index, raw in enumerate(iterations):
        path = f"iterations[{index}]"
        raw = _object(raw, {"id", "actor", "before", "after", "trigger", "evidence", "basis"},
                      {"parent_ids", "status", "verification"}, path)
        iid = raw["id"]
        if not isinstance(iid, str) or not _ID.fullmatch(iid) or iid in seen:
            _error(f"{path}.id 必须为唯一的 1..64 字符字母/数字/下划线/连字符 ID，以字母或数字开头")
        parents = raw.get("parent_ids", [])
        if (not isinstance(parents, list) or len(parents) > PARENTS_MAX
                or any(not isinstance(p, str) or p not in seen for p in parents)):
            _error(f"{path}.parent_ids 必须为最多 {PARENTS_MAX} 个此前迭代的 ID")
        if len(set(parents)) != len(parents) or (index > 0 and not parents):
            _error(f"{path}.parent_ids 不可重复；首条之后必须显式引用此前迭代")
        item = {
            "id": iid,
            "actor": _enum(raw["actor"], ("user", "ai", "user_ai"), path + ".actor"),
            **{key: _text(raw[key], path + "." + key) for key in ("before", "after", "trigger")},
            "evidence": _evidence(raw["evidence"], path + ".evidence"),
            "basis": _enum(raw["basis"], ("inferred", "explicit"), path + ".basis"),
            "parent_ids": list(parents),
            "status": _enum(raw.get("status", "active"),
                            ("active", "achieved", "unresolved"), path + ".status"),
        }
        if "verification" in raw:
            proof = _object(raw["verification"], {"method", "text", "evidence"}, set(),
                            path + ".verification")
            item["verification"] = {
                "method": _enum(proof["method"], ("user_acceptance", "independent_check"),
                                path + ".verification.method"),
                "text": _text(proof["text"], path + ".verification.text"),
                "evidence": _evidence(proof["evidence"], path + ".verification.evidence"),
            }
        if item["status"] == "achieved" and "verification" not in item:
            _error(f"{path} 判定达成必须提供用户验收或独立核验 verification")
        out.append(item)
        seen.add(iid)
    return {"anchor": anchor, "iterations": out}


def validate(value, previous=None) -> dict:
    """Return an independent normalized copy, or ObserveError without mutation.

    previous is the saved goal_flow (not the containing goal item). Once present,
    callers must preserve it on omitted updates; passing null explicitly fails.
    Optional choices/parent_ids/status receive defaults, nothing is truncated.
    """
    if value is None and previous is not None:
        _error("已有 goal_flow 不可清除，请追加迭代保留历史", "goal_flow_frozen")
    result = _normalize(value)
    if previous is not None:
        old = _normalize(previous)
        count = len(old["iterations"])
        if (result["anchor"] != old["anchor"]
                or result["iterations"][:count] != old["iterations"]):
            _error("A 锚点及已有 G 迭代不可删改；修正与达成请追加新迭代", "goal_flow_frozen")
    return result
