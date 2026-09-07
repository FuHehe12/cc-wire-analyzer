"""Pure index/DAG span expansion tests. No recordings, proxy or model calls."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import sys
import tempfile
import unittest

TMP = tempfile.TemporaryDirectory(prefix="ccwa-scope-test-")
os.environ["CCWA_HOME"] = TMP.name
os.environ["CCWA_CLAUDE_SETTINGS"] = str(Path(TMP.name) / "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import observe_scope as scope
import observe_store as OB


class SpanTests(unittest.TestCase):
    def setUp(self):
        self.state = {"scope": {"lane": ""}}
        self.dag = {"nodes": [{"id": rid, "lane": lane} for rid, lane in
                              [("req_a", "main"), ("req_x", "other"),
                               ("req_b", "main"), ("req_c", "main")]]}
        self.entries = [{"id": rid} for rid in ("req_a", "req_x", "req_b", "req_c")]

    def op(self, first="req_a", last="req_c"):
        return {"op": "add_item", "text": "阶段", "cover_span": {"first_rid": first, "last_rid": last}}

    def expand(self, ops):
        return scope.expand_spans(self.state, ops, self.dag, self.entries)

    def reject(self, ops):
        before = deepcopy((self.state, ops, self.dag, self.entries))
        with self.assertRaises(OB.ObserveError) as error:
            self.expand(ops)
        self.assertEqual(error.exception.code, "bad_cover_span")
        self.assertEqual((self.state, ops, self.dag, self.entries), before)

    def test_inclusive_same_lane_no_input_mutation(self):
        ops = [self.op()]
        original = deepcopy(ops)
        out = self.expand(ops)
        self.assertEqual(out[0]["covers"], ["req_a", "req_b", "req_c"])
        self.assertNotIn("cover_span", out[0])
        self.assertEqual(ops, original)
        self.assertIsNot(ops[0], out[0])

    def test_update_and_single_boundary(self):
        out = self.expand([{"op": "update_item", "id": "i_123456", "patch": {
            "title": "阶段", "cover_span": {"first_rid": "req_b", "last_rid": "req_b"}}}])
        self.assertEqual(out[0]["patch"], {"title": "阶段", "covers": ["req_b"]})

    def test_recording_order_not_dag_order(self):
        self.dag["nodes"].reverse()
        self.assertEqual(self.expand([self.op()])[0]["covers"], ["req_a", "req_b", "req_c"])
        self.reject([self.op("req_c", "req_a")])

    def test_cross_lane_unknown_and_filtered_endpoint_rejected(self):
        self.reject([self.op("req_a", "req_x")])
        self.reject([self.op("req_missing", "req_c")])
        self.state["scope"]["lane"] = "other"
        self.reject([self.op()])
        self.state["scope"]["lane"] = ""
        self.entries = self.entries[1:]  # caller's session filter excludes req_a
        self.reject([self.op()])

    def test_session_filtered_intersection_excludes_interior(self):
        self.entries = [e for e in self.entries if e["id"] != "req_b"]
        self.assertEqual(self.expand([self.op()])[0]["covers"], ["req_a", "req_c"])

    def test_exact_shape_and_covers_conflict(self):
        for span in [None, [], "req_a", {}, {"first_rid": "req_a"},
                     {"first_rid": "req_a", "last_rid": "req_c", "extra": 1},
                     {"first_rid": 1, "last_rid": "req_c"},
                     {"first_rid": "../req_a", "last_rid": "req_c"},
                     {"first_rid": "req_a\n", "last_rid": "req_c"}]:
            with self.subTest(span=span):
                self.reject([dict(self.op(), cover_span=span)])
        self.reject([dict(self.op(), covers=[])])
        self.reject([{"op": "update_item", "patch": "invalid"}])

    def test_no_span_passthrough_and_detached(self):
        ops = [{"op": "set_cursor", "cursor": 4}, {"op": "update_item", "patch": {"text": "保留"}}]
        output = self.expand(ops)
        self.assertEqual(output, ops)
        output[1]["patch"]["text"] = "改动副本"
        self.assertEqual(ops[1]["patch"]["text"], "保留")

    def test_2000_boundary_and_2001_rejected(self):
        self.dag = {"nodes": [{"id": f"req_{i}", "lane": "main"} for i in range(2001)]}
        self.entries = [{"id": f"req_{i}"} for i in range(2001)]
        self.assertEqual(len(self.expand([self.op("req_0", "req_1999")])[0]["covers"]), 2000)
        self.reject([self.op("req_0", "req_2000")])

    def test_duplicate_identity_or_missing_lane_rejected(self):
        self.entries.append({"id": "req_b"})
        self.reject([self.op()])
        self.entries.pop()
        self.dag["nodes"][0].pop("lane")
        self.reject([self.op()])

    def test_bad_second_span_does_not_mutate_first(self):
        self.reject([self.op(), self.op("req_c", "req_a")])


class SpanApiTests(unittest.TestCase):
    def test_http_expansion_replay_and_conflict(self):
        from unittest.mock import patch
        import app as web
        state = OB.create({"date": "2026-09-06", "lane": "main", "session": "session-a"}, "span test")
        client = web.app.test_client()
        payload = {"id": state["id"], "submission_id": "span-once", "base_revision": 0,
                   "ops": [{"op": "add_item", "kind": "phase", "text": "stage",
                            "cover_span": {"first_rid": "req_a", "last_rid": "req_b"}}]}
        dag = {"nodes": [{"id": "req_a", "lane": "main"}, {"id": "req_b", "lane": "main"}]}
        with patch.object(web, "_dag_of", return_value=dag), patch.object(web.capture_store, "list_index", return_value=[{"id": "req_a"}, {"id": "req_b"}]) as index:
            response = client.post("/api/observations", json=payload)
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["state"]["items"][0]["covers"], ["req_a", "req_b"])
            index.assert_called_with("2026-09-06", "", "session-a", "")
        # Retrying after capture cleanup must still replay, not re-resolve a span.
        with patch.object(web.capture_store, "list_index", side_effect=AssertionError("must not read")):
            retry = client.post("/api/observations", json=payload)
            self.assertEqual(retry.status_code, 200, retry.json)
            self.assertTrue(retry.json["replayed"])
            payload["submission_id"] = "stale-new-submit"
            conflict = client.post("/api/observations", json=payload)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json["state"]["revision"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
