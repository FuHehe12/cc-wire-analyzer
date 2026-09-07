"""Read-only, incremental display projection of recorded actions.

The observer owns semantic claims; this module only pairs recorded tool calls and
results. Cached state contains bounded previews, never whole request histories.
"""
from __future__ import annotations

import copy
import json
import threading
from collections import OrderedDict

import capture_store

_LOCK = threading.Lock()
_CACHE = OrderedDict()
CACHE_SCOPES = 4
BATCH_SIZE = 12
PREVIEW_LIMIT = 320


def _preview(value, limit=PREVIEW_LIMIT):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit], len(text) > limit


def _blocks(rec):
    response = rec.get("response") or {}
    return response.get("content_blocks") or [] if isinstance(response, dict) else []


def _results(rec):
    req = rec.get("request") or {}
    body = req.get("body") if isinstance(req, dict) else None
    if not isinstance(body, dict):
        return
    for message in body.get("messages") or []:
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                yield block


def _append(state, node, rec):
    node = copy.deepcopy(node)
    node.update(actions=[], text_preview="", missing=rec is None)
    rec = rec if isinstance(rec, dict) else {}
    lane = node.get("lane", "")
    # Request history comes before this response. Only a previously observed call
    # in this same lane can own its result; a reused ID is explicitly ambiguous.
    for block in _results(rec):
        if not isinstance(block.get("tool_use_id"), str):
            continue
        key = (lane, block.get("tool_use_id"))
        calls = state["calls"].get(key, [])
        if len(calls) != 1 or calls[0].get("result_available"):
            continue
        action = calls[0]
        preview, truncated = _preview(block.get("content", ""))
        action.update(result_available=True, result_preview=preview,
                      result_truncated=truncated, result_error=bool(block.get("is_error")),
                      result_record_id=node["id"])
    for block in _blocks(rec):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            inp = block.get("input") or {}
            inp = inp if isinstance(inp, dict) else {}
            name = str(block.get("name") or "tool")
            subject = next((inp[k] for k in ("file_path", "path", "query", "command", "skill", "pattern", "url") if inp.get(k)), "")
            description = inp.get("description") or (name + (" · " + _preview(subject, 120)[0] if subject else ""))
            label, clipped = _preview(description, 180)
            action = dict(name=name, label=label, label_truncated=clipped,
                          tool_call_id=block.get("id"), result_available=False)
            if isinstance(block.get("id"), str):
                calls = state["calls"].setdefault((lane, block["id"]), [])
                calls.append(action)
                if len(calls) > 1:
                    for previous in calls:
                        for field in list(previous):
                            if field.startswith("result_"):
                                del previous[field]
                        previous.update(result_available=False, result_ambiguous=True)
            node["actions"].append(action)
        elif block.get("type") == "text" and not node["text_preview"]:
            node["text_preview"], node["text_truncated"] = _preview(block.get("text", ""))
    node["label"] = (node["actions"][0]["label"] if node["actions"] else
                     node["text_preview"] or node.get("summary") or node["id"])
    state["nodes"].append(node)


def project(date, source, lane, session, dag):
    """Scope-filtered recording order; append-only polls read only new records.

    A changed/deleted/compacted prefix invalidates the projection. Four scope
    caches bound retention; complete source bodies are read twelve at a time.
    """
    capture_store._validate_date(date)
    entries = capture_store.list_index(date, "", session, source)
    by_id = {n["id"]: n for n in dag.get("nodes", []) if not lane or n.get("lane") == lane}
    selected = [e for e in entries if e["id"] in by_id]
    fingerprint = [(e["id"], e.get("off"), e.get("len"), e.get("seg"), by_id[e["id"]].get("lane"))
                   for e in selected]
    key = (str(capture_store.CAPTURES_DIR), date, source, lane, session)
    with _LOCK:
        state = _CACHE.get(key)
        if (state is None or fingerprint[:len(state["fingerprint"])] != state["fingerprint"]
                or any(n["missing"] for n in state["nodes"])):
            state = dict(nodes=[], calls={}, fingerprint=[])
        else:
            # A failed later read must not leave half-appended nodes in the cache.
            state = copy.deepcopy(state)
        start = len(state["fingerprint"])
        for offset in range(start, len(selected), BATCH_SIZE):
            batch = selected[offset:offset+BATCH_SIZE]
            records = capture_store.records_by_index(batch, date, source)
            if len(records) != len(batch):
                raise ValueError("record batch size differs from its index batch")
            for entry, record in zip(batch, records):
                _append(state, by_id[entry["id"]], record)
        state["fingerprint"] = fingerprint
        # Classification metadata can evolve as the next response arrives. Keep
        # cached action facts but refresh classifier fields from its one source.
        for seq, node in enumerate(state["nodes"]):
            node["seq"] = seq
            facts = {k: node[k] for k in ("actions", "text_preview", "text_truncated", "missing", "label") if k in node}
            node.update(by_id[node["id"]])
            node.update(facts)
            node["has_tool_error"] = any(a.get("result_error") for a in node["actions"])
        _CACHE[key] = state
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_SCOPES:
            _CACHE.popitem(last=False)
        turn_ids = {n.get("turn") for n in state["nodes"]}
        node_ids = {n["id"] for n in state["nodes"]}
        lanes = {n.get("lane") for n in state["nodes"]}
        turns = []
        for original in dag.get("turns", []):
            if original.get("turn_id") not in turn_ids:
                continue
            turn = copy.deepcopy(original)
            members = [n for n in state["nodes"] if n.get("turn") == turn.get("turn_id")]
            turn["node_ids"] = [n["id"] for n in members]
            turn["steps"] = len(members)
            # Auxiliary calls can share a main turn but lie outside the chosen
            # lane/session. Never return their IDs or full-scope counters as local.
            turn["scope_filtered"] = set(original.get("node_ids", [])) != set(turn["node_ids"])
            if turn.get("head") not in node_ids:
                turn["head"] = members[0]["id"]
                turn["partial"] = True
                turn["user_text"] = ""
            turn["tool_uses"] = sum(len(n["actions"]) for n in members)
            turn["errors"] = sum(bool(n.get("has_error")) for n in members)
            turn["has_error"] = bool(turn["errors"])
            turn["total_ms"] = sum(n.get("total_ms") or 0 for n in members)
            turn["first_ts"], turn["last_ts"] = members[0].get("ts_start"), members[-1].get("ts_start")
            if turn["scope_filtered"]:
                for field in ("subagents", "aux", "retry_n", "retry_cause"):
                    turn.pop(field, None)
            turns.append(turn)
        lane_rows = []
        for original in dag.get("lanes", []):
            if original.get("lane_id") in lanes:
                row = dict(original)
                row["count"] = sum(n.get("lane") == row["lane_id"] for n in state["nodes"])
                lane_rows.append(row)
        return copy.deepcopy(dict(
            nodes=state["nodes"], turns=turns, lanes=lane_rows,
            date=date, source=source, lane=lane, session=session, truncated=False, order="recording",
            preview_limit=PREVIEW_LIMIT, missing=sum(n["missing"] for n in state["nodes"]),
        ))
