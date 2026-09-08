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

from observe_goal import validate, ITERATIONS_MAX  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
