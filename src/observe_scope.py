"""Expand an explicitly requested span into stable capture IDs, never evidence guesses."""
from __future__ import annotations

from copy import deepcopy

import observe_store as OB


def expand_spans(state: dict, ops: list, dag: dict, entries: list) -> list:
    """Return detached operations with cover_span expanded in recording order.

    The caller supplies entries already filtered by source/date/session. Intersect
    with DAG nodes and the observation lane; each span must stay in one known lane.
    No raw capture reads, timestamps, turn ordinals or inferred evidence intervals.
    """
    def fail(detail):
        raise OB.ObserveError("bad_cover_span", detail)

    if not isinstance(ops, list):
        fail("ops 必须为数组")
    output = deepcopy(ops)
    targets = []
    for op in output:
        if not isinstance(op, dict):
            continue  # existing store validation owns non-span operation errors
        if op.get("op") == "add_item":
            if "cover_span" in op:
                targets.append(op)
        elif op.get("op") == "update_item":
            patch = op.get("patch")
            if patch is not None and not isinstance(patch, dict):
                fail("update_item.patch 必须为对象")
            if isinstance(patch, dict) and "cover_span" in patch:
                targets.append(patch)
    if not targets:
        return output

    scope_lane = (state.get("scope") or {}).get("lane") or ""
    nodes = {}
    ambiguous = set()
    for node in dag.get("nodes") or []:
        rid = node.get("id")
        if rid in nodes:
            ambiguous.add(rid)
        nodes[rid] = node
    selected = []
    positions = {}
    for entry in entries:
        rid = entry.get("id")
        node = nodes.get(rid)
        if node is None or (scope_lane and node.get("lane") != scope_lane):
            continue
        if rid in positions:
            ambiguous.add(rid)
        positions[rid] = len(selected)
        selected.append(node)

    for target in targets:
        span = target["cover_span"]
        if "covers" in target:
            fail("cover_span 与 covers 不能同时提供")
        if (not isinstance(span, dict) or set(span) != {"first_rid", "last_rid"}
                or any(not isinstance(span[k], str) or not OB._RID_RE.fullmatch(span[k])
                       for k in ("first_rid", "last_rid"))):
            fail("cover_span 必须且只能包含有效的 first_rid/last_rid 字符串")
        first, last = span["first_rid"], span["last_rid"]
        if first not in positions or last not in positions:
            fail("范围边界不存在于当前来源、日期、会话与泳道的可用索引中")
        if first in ambiguous or last in ambiguous:
            fail("范围边界的请求 ID 不唯一")
        begin, end = positions[first], positions[last]
        lane = selected[begin].get("lane")
        if not lane or lane != selected[end].get("lane"):
            fail("范围两端必须属于同一条已知泳道")
        if end < begin:
            fail("last_rid 必须在 first_rid 之后或与其相同（按录制顺序）")
        covers = [node["id"] for node in selected[begin:end + 1] if node.get("lane") == lane]
        if any(rid in ambiguous for rid in covers):
            fail("范围内存在重复请求 ID，不能确定覆盖身份")
        if len(covers) > OB.COVERS_MAX:
            fail(f"展开后超过 {OB.COVERS_MAX} 个请求，请显式拆分范围")
        target["covers"] = covers
        del target["cover_span"]
    return output
