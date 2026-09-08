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

from observe_goal import validate, project_statuses, ITERATIONS_MAX, EVENTS_MAX  # noqa: E402
from observe_store import ObserveError  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
