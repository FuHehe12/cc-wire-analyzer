"""A→G contract boundaries and frozen-history regressions; no real recordings."""

from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
TMP = tempfile.TemporaryDirectory(prefix="ccwa-goal-")
os.environ["CCWA_HOME"] = TMP.name
os.environ["CCWA_CLAUDE_SETTINGS"] = str(Path(TMP.name) / "settings.json")

from observe_goal import (validate, apply_delta, project_statuses, ITERATIONS_MAX,
                          EVENTS_MAX, TASKS_MAX)  # noqa: E402
from observe_store import ObserveError  # noqa: E402
import observe_store as OB  # noqa: E402


def iteration(iid="g0", parents=None, **fields):
    return {"id": iid, "actor": "ai", "before": "排查现象", "after": "核对失败原因",
            "trigger": "核对录制后发现此前理解过宽", "basis": "inferred",
            "evidence": ["req_sample-1"], "parent_ids": parents or [], **fields}


def sample():
    return {"anchor": {"user_text": " 先看看为什么不好用。\n", "understanding": "先审查体验记录",
                       "choices": ["AI 自选先审计接口"], "basis": "inferred",
                       "evidence": ["req_sample-1"]}, "iterations": [iteration()]}


class GoalContract(unittest.TestCase):
    def reject(self, value, code="bad_goal_flow", previous=None):
        original, prior = deepcopy(value), deepcopy(previous)
        with self.assertRaises(ObserveError) as caught:
            validate(value, previous)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(value, original, "invalid input was mutated")
        self.assertEqual(previous, prior, "saved history was mutated")

    def test_copy_and_verbatim_quotes(self):
        value = sample()
        original = deepcopy(value)
        result = validate(value)
        self.assertEqual(result["anchor"]["user_text"], " 先看看为什么不好用。\n")
        result["anchor"]["evidence"].append("req_other")
        result["iterations"][0]["parent_ids"].append("other")
        self.assertEqual(value, original)
        self.assertEqual(validate(original), validate(validate(original)))

    def test_branch_merge_and_completion(self):
        value = sample()
        value["iterations"] += [iteration("g1a", ["g0"], actor="user"),
                                iteration("g1b", ["g0"], actor="user_ai", status="unresolved"),
                                iteration("g2", ["g1a", "g1b"], status="achieved",
                                          verification={"method": "independent_check",
                                                        "text": "独立重放两个失败样例均通过",
                                                        "evidence": ["req_verified"]})]
        previous = validate(sample())
        self.assertEqual(len(validate(value, previous)["iterations"]), 4)
        self.assertEqual(previous, validate(sample()))

    def test_history_cannot_disappear_or_change(self):
        previous = validate(sample())
        changes = [lambda v: v.update(anchor={**v["anchor"], "user_text": "改写用户原话"}),
                   lambda v: v["iterations"][0].update(after="事后改目标"),
                   lambda v: v["iterations"].clear(),
                   lambda v: v["iterations"][0].update(status="unresolved")]
        for change in changes:
            value = deepcopy(previous)
            change(value)
            self.reject(value, "goal_flow_frozen", previous)
        self.reject(None, "goal_flow_frozen", previous)

    def test_evidence_basis_and_success_are_not_optional(self):
        for field, bad in [("evidence", []), ("evidence", ["fake"]),
                           ("evidence", ["req_a", "req_a"]), ("evidence", [True]),
                           ("evidence", ["req_../secret"]), ("evidence", ["req_x\n"]),
                           ("basis", "fact"), ("basis", None), ("actor", "system"),
                           ("status", "achieved")]:
            with self.subTest(field=field, bad=bad):
                value = sample()
                value["iterations"][0][field] = bad
                self.reject(value)
        value = sample()
        value["iterations"][0]["verification"] = {
            "method": "tool_success", "text": "exit 0", "evidence": ["req_x"]}
        self.reject(value)
        value = sample()
        del value["anchor"]["basis"]
        self.reject(value)

    def test_no_unknown_fields_or_invalid_graphs(self):
        for parents in [[], ["future"], ["g1"], ["g0", "g0"], [None], "g0"]:
            value = sample()
            value["iterations"].append(iteration("g1", parents))
            self.reject(value)
        for target in ["flow", "anchor", "iteration"]:
            value = sample()
            obj = value if target == "flow" else value["anchor"] if target == "anchor" else value["iterations"][0]
            obj["typo"] = "cannot silently ignore"
            self.reject(value)
        value = sample()
        value["iterations"].append(iteration("g0", ["g0"]))
        self.reject(value)

    def test_exact_bounds_and_no_truncation(self):
        value = sample()
        value["anchor"]["user_text"] = "x" * 4000
        value["anchor"]["choices"] = ["x" * 1000] * 20
        value["anchor"]["evidence"] = ["req_" + "x" * 124] + [f"req_{i}" for i in range(49)]
        value["iterations"] = [iteration(f"g{i}", [f"g{i-1}"] if i else []) for i in range(ITERATIONS_MAX)]
        self.assertEqual(len(validate(value)["iterations"]), ITERATIONS_MAX)
        for change in [lambda v: v["anchor"].update(user_text="x" * 4001),
                       lambda v: v["anchor"].update(choices=["x"] * 21),
                       lambda v: v["anchor"].update(choices=["x" * 1001]),
                       lambda v: v["anchor"]["evidence"].append("req_extra"),
                       lambda v: v["anchor"].update(evidence=["req_" + "x" * 125]),
                       lambda v: v["iterations"].append(iteration("extra", ["g0"]))]:
            bad = deepcopy(value)
            change(bad)
            self.reject(bad)

    def test_empty_and_non_json_shapes(self):
        for value in [None, [], {}, "goal", {"anchor": [], "iterations": []}]:
            self.reject(value)
        value = sample()
        value["iterations"] = []
        self.assertEqual(validate(value)["iterations"], [])
        value["anchor"]["choices"] = []
        value["anchor"]["understanding"] = " "
        self.reject(value)

    def test_parent_and_id_bounds_and_frozen_branch_order(self):
        value = sample()
        value["iterations"] += [iteration(f"b{i}", ["g0"]) for i in range(21)]
        value["iterations"].append(iteration("m" * 64, [f"b{i}" for i in range(20)]))
        validate(value)
        bad = deepcopy(value)
        bad["iterations"][-1]["parent_ids"].append("b20")
        self.reject(bad)
        bad = deepcopy(value)
        bad["iterations"][-1]["id"] += "x"
        self.reject(bad)
        bad = deepcopy(value)
        bad["iterations"][1], bad["iterations"][2] = bad["iterations"][2], bad["iterations"][1]
        self.reject(bad, "goal_flow_frozen", value)
        value["iterations"][-1].update(status="achieved", verification={
            "method": "user_acceptance", "text": "用户确认完成", "evidence": ["req_accept"]})
        result = validate(value)
        result["iterations"][-1]["verification"]["evidence"].append("req_changed")
        self.assertEqual(value["iterations"][-1]["verification"]["evidence"], ["req_accept"])


class GoalEvents(unittest.TestCase):
    reject = GoalContract.reject

    def event(self, **fields):
        return {"id": "e1", "kind": "status", "target": "g0", "status": "achieved",
                "text": "后续核验通过", "evidence": ["req_check"], "verification": {
                    "method": "independent_check", "text": "重跑反例得到预期400", "evidence": ["req_check"]}, **fields}

    def test_complete_existing_goal_without_new_iteration(self):
        previous = validate(sample())
        value = deepcopy(previous)
        value["events"] = [self.event()]
        result = validate(value, previous)
        self.assertEqual(result["iterations"], previous["iterations"])
        self.assertEqual(len(result["iterations"]), 1)
        self.assertEqual(project_statuses(result)["g0"]["status"], "achieved")
        result["events"].append(self.event(id="e2", status="unresolved"))
        result["events"][-1].pop("verification")
        result = validate(result, value)
        self.assertEqual(project_statuses(result)["g0"], {"status": "unresolved", "event_id": "e2"})
        self.assertEqual(value["iterations"][0]["status"], "active")

    def test_correction_is_observer_annotation_not_goal_change(self):
        previous = validate(sample())
        value = deepcopy(previous)
        value["events"] = [{"id": "c1", "kind": "correction", "target": "@anchor",
            "text": "先前把试用误解为验收，现在订正", "evidence": ["req_user"], "basis": "explicit"},
            {"id": "c2", "kind": "correction", "target": "g0",
             "text": "先前将推断标为明确表达，应保留不确定性", "evidence": ["req_user"], "basis": "inferred"}]
        result = validate(value, previous)
        self.assertEqual(result["anchor"], previous["anchor"])
        self.assertEqual(result["iterations"], previous["iterations"])
        self.assertEqual(project_statuses(result), project_statuses(previous))
        for update in [{"actor": "ai"}, {"status": "active"}, {"target": "missing"}, {"basis": "fact"}]:
            bad = deepcopy(value)
            bad["events"][0].update(update)
            self.reject(bad)

    def test_event_shape_and_targets(self):
        for update in [{"target": "@anchor"}, {"target": "missing"}, {"target": []},
                       {"kind": "update"}, {"id": "_e"}, {"id": "e" * 65},
                       {"text": ""}, {"evidence": []}, {"status": "done"}, {"basis": "explicit"}]:
            value = sample()
            value["events"] = [self.event(**update)]
            self.reject(value)
        value = sample()
        event = self.event()
        event.pop("verification")
        value["events"] = [event]
        self.reject(value)
        value["events"] = [self.event(), self.event()]
        self.reject(value)
        for bad in [None, {}, "events", [None]]:
            value["events"] = bad
            self.reject(value)
        value["events"] = [self.event(status="superseded")]
        self.assertEqual(project_statuses(value)["g0"]["status"], "superseded")

    def test_event_prefix_cannot_be_deleted_or_rewritten(self):
        previous = sample()
        previous["events"] = [self.event(), self.event(id="e2", status="active")]
        previous = validate(previous)
        for change in [lambda v: v.pop("events"), lambda v: v.update(events=[]),
                       lambda v: v["events"].reverse(), lambda v: v["events"][0].update(text="rewrite"),
                       lambda v: v["events"].pop()]:
            value = deepcopy(previous)
            change(value)
            self.reject(value, "goal_flow_frozen", previous)

    def test_legacy_shape_and_event_capacity_independent_of_goal_capacity(self):
        legacy = validate(sample())
        self.assertNotIn("events", legacy)
        self.assertEqual(validate(legacy, dict(legacy, events=[])), legacy)
        full = sample()
        full["iterations"] = [iteration(f"g{i}", [f"g{i-1}"] if i else []) for i in range(ITERATIONS_MAX)]
        old = validate(full)
        full["events"] = [self.event(id=f"e{i}", target="g199") for i in range(EVENTS_MAX)]
        result = validate(full, old)
        self.assertEqual(len(result["iterations"]), ITERATIONS_MAX)
        self.assertEqual(len(result["events"]), EVENTS_MAX)
        self.assertEqual(project_statuses(result)["g199"]["status"], "achieved")
        full["events"].append(self.event(id="extra"))
        self.reject(full)

    def test_valid_id_is_not_evidence_semantic_verification(self):
        value = sample()
        value["events"] = [self.event(evidence=["req_nonexistent"], verification={
            "method": "independent_check", "text": "自报完成，没有独立断言", "evidence": ["req_nonexistent"]})]
        # Explicitly preserve this boundary; storage cannot inspect missing exports.
        self.assertEqual(validate(value)["events"][0]["status"], "achieved")


def current(ids=None, **fields):
    return {"goal_ids": ids or ["g0"], "understanding": "先核对体验问题",
            "situation": "只有用户反馈，尚未复现", "evidence": ["req_current"], **fields}


def tasked():
    flow = sample()
    flow["iterations"][0].update(task_id="t0", change="initial")
    flow["tasks"] = [{"id": "t0", "title": "修复体验问题", "start_id": "g0"}]
    return flow


class GoalTasksAndCurrent(unittest.TestCase):
    reject = GoalContract.reject

    def test_parallel_refinements_merge_and_explicit_turn(self):
        flow = tasked()
        flow["iterations"] += [iteration("g1", ["g0"], task_id="t0", change="refine"),
                               iteration("g2", ["g0"], task_id="t0", change="refine"),
                               iteration("g3", ["g1", "g2"], task_id="t0", change="refine")]
        before = validate(flow)
        flow["tasks"].append({"id": "t1", "title": "另做接口文档", "start_id": "g4"})
        flow["iterations"].append(iteration("g4", ["g3"], task_id="t1", change="turn"))
        flow["current"] = current(["g3", "g4"], carryover="体验问题尚未验收，继续保留复现要求")
        result = validate(flow, before)
        self.assertEqual(result["iterations"][-1]["parent_ids"], ["g3"])
        self.assertEqual(project_statuses(result)["g3"]["status"], "active")
        self.assertEqual(result["current"]["goal_ids"], ["g3", "g4"])
        # Returning to an existing task remains a refinement of that task.
        result["iterations"].append(iteration("g5", ["g3"], task_id="t0", change="refine"))
        validate(result, flow)

    def test_legacy_prefix_needs_no_retagging_and_current_is_independent(self):
        old = validate(sample())
        with_current = validate(dict(old, current=current()), old)
        self.assertNotIn("tasks", with_current)
        new = apply_delta(with_current, {
            "tasks": [{"id": "t1", "title": "现在开始显式任务", "start_id": "g1"}],
            "iterations": [iteration("g1", ["g0"], task_id="t1", change="initial")]})
        self.assertEqual(new["iterations"][0], old["iterations"][0])
        self.assertNotIn("task_id", new["iterations"][0])
        self.assertEqual(new["current"], with_current["current"])
        self.assertNotIn("current", validate(tasked()))
        retagged = tasked()
        self.reject(retagged, "goal_flow_frozen", old)

    def test_task_and_change_semantics_reject_mislabelled_edges(self):
        for change, tid, parents in [("initial", "t0", ["g0"]),
                                     ("turn", "t0", ["g0"]),
                                     ("refine", "t1", ["g0"]),
                                     ("initial", "t1", ["g0"])]:
            bad = tasked()
            if tid == "t1":
                bad["tasks"].append({"id": "t1", "title": "新任务", "start_id": "g1"})
            bad["iterations"].append(iteration("g1", parents, task_id=tid, change=change))
            self.reject(bad)
        bad = tasked()
        bad["iterations"][0]["change"] = "turn"
        self.reject(bad)
        bad = tasked()
        bad["iterations"].append(iteration("g1", ["g0"]))
        self.reject(bad)
        good = tasked()
        good["tasks"].append({"id": "t1", "title": "新任务", "start_id": "g1"})
        good["iterations"].append(iteration("g1", ["g0"], task_id="t1", change="turn"))
        # A cross-task parent cannot hide among valid same-task branch parents.
        good["iterations"].append(iteration("g2", ["g1", "g0"], task_id="t1", change="refine"))
        self.reject(good)
        # An unlabelled legacy edge cannot prove a known cross-task turn.
        bad = sample()
        bad["tasks"] = [{"id": "t1", "title": "新任务", "start_id": "g1"}]
        bad["iterations"].append(iteration("g1", ["g0"], task_id="t1", change="turn"))
        self.reject(bad)

    def test_task_shape_references_and_history(self):
        for field, value in [("id", "_bad"), ("id", None), ("title", " "),
                             ("title", "x" * 201), ("start_id", "missing"), ("extra", True)]:
            bad = tasked()
            bad["tasks"][0][field] = value
            self.reject(bad)
        for field, value in [("task_id", "missing"), ("task_id", []), ("task_id", None),
                             ("change", "revision"), ("change", None)]:
            bad = tasked()
            bad["iterations"][0][field] = value
            self.reject(bad)
        for field in ("task_id", "change"):
            bad = tasked()
            del bad["iterations"][0][field]
            self.reject(bad)
        for tasks in [None, {}, "tasks", [None], tasked()["tasks"] * 2,
                      [{"id": "unused", "title": "空任务", "start_id": "g0"}],
                      tasked()["tasks"] * (TASKS_MAX + 1)]:
            bad = tasked()
            bad["tasks"] = tasks
            self.reject(bad)
        old = validate(tasked())
        bad = deepcopy(old)
        bad["tasks"][0]["title"] = "改写任务标题"
        self.reject(bad, "goal_flow_frozen", old)
        bad = deepcopy(old)
        bad["iterations"].append(iteration("g1", ["g0"], task_id="t0", change="refine"))
        bad["tasks"][0]["start_id"] = "g1"
        self.reject(bad)

    def test_current_replacement_preserves_goals_and_does_not_imply_achievement(self):
        old = validate(dict(tasked(), current=current(carryover="保留原要求")))
        updated = validate(dict(old, current=current(situation="模型说已结束，尚未用户验收")), old)
        self.assertEqual(updated["iterations"], old["iterations"])
        self.assertNotIn("carryover", updated["current"])
        self.assertEqual(project_statuses(updated), project_statuses(old))
        omitted = deepcopy(updated)
        omitted.pop("current")
        self.assertEqual(validate(omitted, updated)["current"], updated["current"])
        updated["current"]["goal_ids"].append("mutated")
        self.assertEqual(old["current"]["goal_ids"], ["g0"])
        old["iterations"][0].update(status="achieved", verification={
            "method": "user_acceptance", "text": "用户验收过此前版本", "evidence": ["req_old"]})
        # Current understanding is explicit prose, never generated from statuses.
        self.assertEqual(validate(old)["current"]["situation"], "只有用户反馈，尚未复现")

    def test_task_current_limits_and_task_order_remain_frozen(self):
        flow = sample()
        flow["tasks"] = [{"id": f"t{i}", "title": "名" * 200, "start_id": f"g{i}"}
                         for i in range(TASKS_MAX)]
        flow["iterations"] = [iteration(f"g{i}", [f"g{i-1}"] if i else [],
            task_id=f"t{i}", change="turn" if i else "initial") for i in range(TASKS_MAX)]
        flow["current"] = current([f"g{i}" for i in range(20)], understanding="字" * 4000,
                                  situation="字" * 4000, carryover="字" * 4000)
        saved = validate(flow)
        self.assertEqual(len(saved["tasks"]), 200)
        self.assertEqual(len(saved["current"]["goal_ids"]), 20)
        bad = deepcopy(saved)
        bad["current"]["goal_ids"].append("g20")
        self.reject(bad)
        bad = deepcopy(saved)
        bad["tasks"].reverse()
        self.reject(bad, "goal_flow_frozen", saved)
        with self.assertRaises(ObserveError):
            apply_delta(saved, {"tasks": [{"id": "overflow", "title": "超限", "start_id": "g0"}]})

    def test_current_requires_complete_explicit_evidence_backed_description(self):
        for field, value in [("goal_ids", []), ("goal_ids", ["g0", "g0"]),
                             ("goal_ids", ["missing"]), ("goal_ids", [True]),
                             ("goal_ids", "g0"), ("understanding", ""),
                             ("situation", " "), ("evidence", []), ("evidence", ["fake"]),
                             ("carryover", ""), ("carryover", None),
                             ("status", "achieved"), ("situation", "x" * 4001)]:
            self.reject(dict(sample(), current=current(**{field: value})))
        for value in [None, [], {}, {"situation": "只有现状"}]:
            self.reject(dict(sample(), current=value))

    def test_delta_merges_without_mutation_and_checks_combined_graph(self):
        old = validate(tasked())
        delta = {"tasks": [{"id": "t1", "title": "另一个交付", "start_id": "g1"}],
                 "iterations": [iteration("g1", ["g0"], task_id="t1", change="turn")],
                 "events": [{"id": "e1", "kind": "status", "target": "g1", "status": "unresolved",
                             "text": "新交付未验收", "evidence": ["req_new"]}],
                 "current": current(["g1"], carryover="旧任务仍需复验")}
        prior, incoming = deepcopy(old), deepcopy(delta)
        merged = apply_delta(old, delta)
        self.assertEqual(old, prior)
        self.assertEqual(delta, incoming)
        self.assertEqual(merged["iterations"][0], old["iterations"][0])
        merged["tasks"][1]["title"] = "不应改变输入"
        merged["current"]["evidence"].append("req_new")
        self.assertEqual(delta, incoming)
        for bad in [None, {}, [], {"anchor": old["anchor"]}, {"current": None},
                    {"iterations": None}, {"tasks": {}}, {"events": "bad"},
                    {"iterations": [old["iterations"][0]]},
                    {"current": current(["future"])}]:
            with self.subTest(delta=bad), self.assertRaises(ObserveError):
                apply_delta(old, bad)
            self.assertEqual(old, prior)
        with self.assertRaises(ObserveError):
            apply_delta(None, {"current": current()})


class GoalDeltaStore(unittest.TestCase):
    def setUp(self):
        self.oid = OB.create({"date": "2026-09-09", "lane": "sample"}, "增量契约测试")["id"]
        result = OB.apply(self.oid, "initial", 0, [{"op": "add_item", "client_ref": "goal",
            "kind": "goal", "text": "明确目标", "goal_flow": dict(tasked(), current=current())}])
        self.iid = result["refs"]["goal"]

    def patch(self, delta):
        return {"op": "update_item", "id": self.iid, "patch": {"goal_flow_delta": delta}}

    def test_small_current_update_is_replayable_and_keeps_history(self):
        old = OB.read(self.oid)
        delta = {"current": current(situation="已有复现，仍待修复")}
        ops = [self.patch(delta), {"op": "set_cursor", "cursor": 27}]
        fresh = OB.apply(self.oid, "current-only", 1, ops)
        saved = fresh["state"]["items"][0]
        self.assertNotIn("goal_flow_delta", saved)
        self.assertEqual(saved["goal_flow"]["iterations"], old["items"][0]["goal_flow"]["iterations"])
        self.assertEqual(saved["history"][-1]["goal_flow"], old["items"][0]["goal_flow"])
        replay = OB.apply(self.oid, "current-only", 1, ops)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["state"], fresh["state"])
        with self.assertRaises(ObserveError) as caught:
            OB.apply(self.oid, "stale", 1, ops)
        self.assertEqual(caught.exception.code, "conflict")
        self.assertEqual(OB.read(self.oid), fresh["state"])

    def test_task_turn_and_associated_item_commit_in_one_batch(self):
        delta = {"tasks": [{"id": "t1", "title": "另外的交付", "start_id": "g1"}],
                 "iterations": [iteration("g1", ["g0"], task_id="t1", change="turn")],
                 "current": current(["g0", "g1"], carryover="旧任务仍需验收")}
        state = OB.apply(self.oid, "turn", 1, [
            {"op": "add_item", "kind": "open", "text": "新任务缺验收", "goal_iteration": "g1"},
            self.patch(delta)])["state"]
        flow = state["items"][0]["goal_flow"]
        self.assertEqual(len(flow["tasks"]), 2)
        self.assertEqual(flow["iterations"][-1]["parent_ids"], ["g0"])
        self.assertEqual(project_statuses(flow)["g0"]["status"], "active")

    def test_invalid_delta_rolls_back_cursor_history_items_and_submission(self):
        old = OB.read(self.oid)
        for delta in [{"current": current(["future"])},
                      {"iterations": [iteration("g1", ["g0"], task_id="missing", change="turn")]},
                      {"iterations": [tasked()["iterations"][0]]}]:
            with self.assertRaises(ObserveError):
                OB.apply(self.oid, "retry-after-reject", 1, [
                    {"op": "set_cursor", "cursor": 999},
                    {"op": "update_item", "id": self.iid, "patch": {"text": "不应落盘"}},
                    self.patch(delta)])
            self.assertEqual(OB.read(self.oid), old)
        result = OB.apply(self.oid, "retry-after-reject", 1, [self.patch({"current": current()})])
        self.assertFalse(result["replayed"])

    def test_delta_is_patch_only_mutually_exclusive_and_requires_existing_goal(self):
        old = OB.read(self.oid)
        bad_ops = [
            {"op": "add_item", "kind": "goal", "text": "x", "goal_flow_delta": {"current": current()}},
            {"op": "update_item", "id": self.iid,
             "patch": {"goal_flow": tasked(), "goal_flow_delta": {"current": current()}}},
            {"op": "update_item", "id": self.iid, "goal_flow_delta": {"current": current()}},
        ]
        for op in bad_ops:
            with self.assertRaises(ObserveError):
                OB.apply(self.oid, "bad-surface", 1, [op])
            self.assertEqual(OB.read(self.oid), old)
        another = OB.create({"date": "2026-09-09"}, "没有目标流")["id"]
        res = OB.apply(another, "empty-goal", 0, [
            {"op": "add_item", "kind": "goal", "client_ref": "empty", "text": "尚未初始化"},
            {"op": "add_item", "kind": "finding", "client_ref": "finding", "text": "仅发现"}])
        for ref in ("empty", "finding"):
            with self.assertRaises(ObserveError):
                OB.apply(another, "needs-init", 1, [{"op": "update_item", "id": res["refs"][ref],
                    "patch": {"goal_flow_delta": {"current": current()}}}])
            self.assertEqual(OB.read(another), res["state"])


if __name__ == "__main__":
    unittest.main()
