"""Isolated read-only trace projection tests; no proxy, model or real recordings."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="ccwa-trace-test-")
os.environ["CCWA_HOME"] = TMP.name
os.environ["CCWA_CLAUDE_SETTINGS"] = str(Path(TMP.name) / "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import observe_trace as trace
import capture_store as store

DATE = "2026-09-08"


def call(cid="call_a", name="Bash"):
    return {"type": "tool_use", "id": cid, "name": name,
            "input": {"command": "python -m unittest", "description": "运行回归测试"}}


def result(cid="call_a", content="PASS", error=False):
    return {"type": "tool_result", "tool_use_id": cid, "content": content, "is_error": error}


def record(blocks=(), results=()):
    return {"request": {"body": {"messages": [{"role": "user", "content": list(results)}]}},
            "response": {"content_blocks": list(blocks)}}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        trace._CACHE.clear()
        self.rows = []
        self.records = {}
        self.dag = {"nodes": [], "turns": [], "lanes": []}
        self.reads = []
        self.patches = [patch.object(store, "list_index", side_effect=self.index),
                        patch.object(store, "records_by_index", side_effect=self.read_batch)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def index(self, date, exclude, session, source):
        return [e for e in self.rows if e["source"] == source
                and e["session"].startswith(session)]

    def read_batch(self, entries, date, source):
        self.reads.append((source, [e["id"] for e in entries]))
        return [copy.deepcopy(self.records.get((source, e["id"]))) for e in entries]

    def add(self, rid, rec, lane="main", session="session-a", source="", turn="t1"):
        self.rows.append({"id": rid, "off": len(self.rows) * 100, "len": 100,
                          "session": session, "source": source})
        self.records[source, rid] = rec
        self.dag["nodes"].append({"id": rid, "lane": lane, "turn": turn, "summary": "tool",
                                  "ts_start": f"{DATE}T12:00:{len(self.rows):02}", "total_ms": 10})
        if not any(t["turn_id"] == turn for t in self.dag["turns"]):
            self.dag["turns"].append({"turn_id": turn, "head": rid, "node_ids": [], "steps": 0})
        t = next(t for t in self.dag["turns"] if t["turn_id"] == turn)
        t["node_ids"].append(rid)
        t["steps"] += 1
        if not any(l["lane_id"] == lane for l in self.dag["lanes"]):
            self.dag["lanes"].append({"lane_id": lane, "count": 999})

    def run_projection(self, source="", lane="", session=""):
        return trace.project(DATE, source, lane, session, self.dag)

    def test_append_reads_only_new_and_updates_old_action(self):
        self.add("req_a", record([call()]))
        before = self.run_projection()
        self.assertFalse(before["nodes"][0]["actions"][0]["result_available"])
        self.run_projection()
        self.assertEqual(self.reads, [("", ["req_a"])])
        self.add("req_b", record(results=[result(error=True)]))
        after = self.run_projection()
        a = after["nodes"][0]["actions"][0]
        self.assertEqual(a["result_record_id"], "req_b")
        self.assertTrue(a["result_error"])
        self.assertTrue(after["nodes"][0]["has_tool_error"])
        self.assertFalse(before["nodes"][0]["actions"][0]["result_available"])
        self.assertEqual(self.reads[-1], ("", ["req_b"]))

    def test_shrink_prefix_and_classifier_lane_change_invalidate(self):
        self.add("req_a", record([call()]))
        self.add("req_b", record(results=[result()]))
        self.run_projection()
        self.rows.pop()
        self.run_projection()
        self.assertEqual(self.reads[-1][1], ["req_a"])
        self.rows[0]["off"] += 1
        self.run_projection()
        self.assertEqual(len(self.reads), 3)
        self.dag["nodes"][0]["lane"] = "reclassified"
        self.run_projection()
        self.assertEqual(len(self.reads), 4)

    def test_lane_session_source_and_turn_metadata_are_scoped(self):
        self.add("req_a", record([call()]), lane="main")
        self.add("req_other", record(), lane="aux", session="session-b")
        self.add("req_remote", record(), lane="main", source="remote")
        output = self.run_projection(lane="main", session="session-a")
        self.assertEqual([n["id"] for n in output["nodes"]], ["req_a"])
        self.assertEqual(output["turns"][0]["node_ids"], ["req_a"])
        self.assertEqual(output["turns"][0]["steps"], 1)
        self.assertTrue(output["turns"][0]["scope_filtered"])
        self.assertEqual(output["lanes"], [{"lane_id": "main", "count": 1}])
        remote = self.run_projection(source="remote")
        self.assertEqual([n["id"] for n in remote["nodes"]], ["req_remote"])
        self.assertEqual(self.reads[-1], ("remote", ["req_remote"]))

    def test_results_require_prior_call_in_same_lane(self):
        self.add("req_a", record(results=[result()]))
        self.add("req_b", record([call()]))
        self.add("req_c", record(results=[result()]), lane="other")
        output = self.run_projection()
        self.assertFalse(output["nodes"][1]["actions"][0]["result_available"])
        self.add("req_d", record(results=[result(content="")]))
        action = self.run_projection()["nodes"][1]["actions"][0]
        self.assertTrue(action["result_available"])
        self.assertEqual(action["result_preview"], "")
        self.assertEqual(action["result_record_id"], "req_d")

    def test_repeated_history_is_not_new_result_and_duplicate_call_is_ambiguous(self):
        self.add("req_a", record([call()]))
        self.add("req_b", record(results=[result(content="first")]))
        self.add("req_c", record(results=[result(content="later copy")]))
        output = self.run_projection()
        self.assertEqual(output["nodes"][0]["actions"][0]["result_preview"], "first")
        self.add("req_d", record([call()]))
        output = self.run_projection()
        for index in (0, 3):
            action = output["nodes"][index]["actions"][0]
            self.assertTrue(action["result_ambiguous"])
            self.assertFalse(action["result_available"])
            self.assertNotIn("result_record_id", action)

    def test_missing_can_recover_and_bad_result_id_is_ignored(self):
        self.add("req_a", None)
        output = self.run_projection()
        self.assertEqual(output["missing"], 1)
        self.records["", "req_a"] = record([call()], [result(cid=[])])
        output = self.run_projection()
        self.assertEqual(output["missing"], 0)
        self.assertEqual(len(output["nodes"][0]["actions"]), 1)

    def test_previews_bounded_and_return_copies_do_not_poison_cache(self):
        self.add("req_a", record([call(), {"type": "text", "text": "a" * 400}]))
        self.add("req_b", record(results=[result(content="x" * 500)]))
        output = self.run_projection()
        action = output["nodes"][0]["actions"][0]
        self.assertEqual(len(action["result_preview"]), trace.PREVIEW_LIMIT)
        self.assertTrue(action["result_truncated"])
        self.assertTrue(output["nodes"][0]["text_truncated"])
        action["name"] = "poison"
        self.assertEqual(self.run_projection()["nodes"][0]["actions"][0]["name"], "Bash")

    def test_failed_append_does_not_partially_commit_cache(self):
        self.add("req_a", record([call()]))
        self.run_projection()
        self.add("req_b", record(results=[result()]))
        self.add("req_c", record())
        normal = self.read_batch
        def fail(entries, date, source):
            if entries[0]["id"] == "req_c":
                raise OSError("broken segment")
            return normal(entries, date, source)
        with patch.object(trace, "BATCH_SIZE", 1), patch.object(store, "records_by_index", side_effect=fail):
            with self.assertRaises(OSError):
                self.run_projection()
        output = self.run_projection()
        self.assertEqual([n["id"] for n in output["nodes"]], ["req_a", "req_b", "req_c"])
        self.assertEqual(output["nodes"][0]["actions"][0]["result_record_id"], "req_b")

    def test_short_reader_batch_is_explicit_error(self):
        self.add("req_a", record())
        with patch.object(store, "records_by_index", return_value=[]):
            with self.assertRaisesRegex(ValueError, "batch size"):
                self.run_projection()

    def test_cache_is_bounded(self):
        for n in range(trace.CACHE_SCOPES + 2):
            self.run_projection(source="scope" + str(n))
        self.assertEqual(len(trace._CACHE), trace.CACHE_SCOPES)


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.module = app
        cls.client = app.app.test_client()

    def test_route_validates_date_before_any_dag_read(self):
        with patch.object(self.module, "_dag_of") as dag:
            for date in ("", "../secret", "2026-02-30", "not-a-date"):
                response = self.client.get("/api/observations/trace", query_string={"date": date})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"], "bad_scope")
            dag.assert_not_called()

    def test_bad_source_path_rejected_without_starting_proxy(self):
        with patch.object(self.module, "_dag_of", return_value={}), patch.object(store, "append") as append:
            response = self.client.get("/api/observations/trace", query_string={"date": DATE, "source": "../secret"})
            self.assertEqual(response.status_code, 400)
            append.assert_not_called()

    def test_route_forwards_scope_and_is_read_only(self):
        with patch.object(self.module, "_dag_of", return_value={"nodes": []}), \
                patch.object(trace, "project", return_value={"nodes": [], "missing": 0}) as project, \
                patch.object(store, "append") as append:
            response = self.client.get("/api/observations/trace", query_string={
                "date": DATE, "source": "remote", "lane": "lane-a", "session": "session-a"})
            self.assertEqual(response.status_code, 200)
            project.assert_called_once_with(DATE, "remote", "lane-a", "session-a", {"nodes": []})
            append.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
