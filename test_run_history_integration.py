"""Saved metadata search/review: invented histories, no live reconciliation."""

import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_run_comparison_integration import (
    PRIVATE_SENTINEL, comparison_fixture, populate_saved_histories, private_hashes, saved_only_guard,
)
from workbench import Manager, init_demo, make_handler


def history_request(query="", project="", state=""):
    return {"query": query, "project": project, "state": state}


def open_request(search, row=None):
    row = search["runs"][0] if row is None else row
    return {"id": row["id"], "record_sha256": row["record_sha256"], "history_sha256": search["history_sha256"]}


@contextmanager
def history_guard(manager):
    """Only bounded jobs metadata reads are allowed in the new workflow."""
    with saved_only_guard(manager), ExitStack() as stack:
        for name in ["compare", "comparison_history", "view", "export", "verified_artifact", "current_project",
                     "config_view", "project_readiness", "readiness_admission", "snapshot_workspace_view"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("history reached " + name)))
        for name in ["workbench.read_file", "workbench.readiness_read_file", "workbench.json_file",
                     "workbench.subprocess.run", "git_workspace.git", "workbench.readiness_presence"]:
            stack.enter_context(patch(name, side_effect=AssertionError("history read or executed " + name)))
        original = manager.comparison_directory
        def jobs_only(root):
            if Path(root) != manager.data / "jobs":
                raise AssertionError("history opened non-jobs evidence")
            return original(root)
        stack.enter_context(patch.object(manager, "comparison_directory", side_effect=jobs_only))
        yield


@contextmanager
def history_http_fixture():
    with comparison_fixture() as (root, manager, ids):
        handler_type = make_handler(manager, "invented-history-token", "http://127.0.0.1:8765")
        def request(path, value, headers=None, raw=None):
            raw = canonical(value) if raw is None else raw
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-history-token",
                        "Origin": "http://127.0.0.1:8765", "Content-Type": "application/json",
                        "Content-Length": str(len(raw))}
            duplicates = headers if isinstance(headers, list) else []
            if isinstance(headers, dict): supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "POST", path
            handler.request_version, handler.requestline = "HTTP/1.1", "POST " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in list(supplied.items()) + duplicates: handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
            handler.do_POST()
            head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(body)
        yield root, manager, ids, request


class RunHistoryIntegrationTests(unittest.TestCase):
    def refusal(self, root, action, request, code=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught: action(request)
        self.assertRegex(str(caught.exception), r"^HISTORY_SEARCH_[A-Z_]{1,48}$")
        if code is not None: self.assertEqual(str(caught.exception), code)
        self.assertNotIn(str(root), str(caught.exception))
        self.assertEqual(before, private_hashes(root))

    def test_python_java_search_and_metadata_open_preserve_all_evidence_and_hold(self):
        with comparison_fixture() as (root, manager, ids), history_guard(manager):
            before = private_hashes(root)
            result = manager.run_history_search(history_request())
            self.assertEqual(set(result), {"version", "query", "project", "state", "history_sha256", "runs", "projects",
                "inspected", "matched", "returned", "catalog_truncated", "result_truncated", "limit", "notes"})
            self.assertEqual((result["inspected"], result["matched"], result["returned"]), (len(ids), len(ids), len(ids)))
            self.assertEqual(result["projects"], ["arithmetic", "java"])
            self.assertFalse(result["catalog_truncated"] or result["result_truncated"])
            self.assertEqual({row["id"] for row in result["runs"]}, set(ids.values()))
            for row in result["runs"]:
                self.assertEqual(set(row), {"id", "project", "project_name", "goal_excerpt", "goal_truncated", "state",
                                           "created", "record_sha256", "match_fields"})
                self.assertEqual(row["match_fields"], [])
                self.assertEqual(row["record_sha256"], sha(manager.meta_path(row["id"]).read_bytes()))
                opened = manager.run_history_open(open_request(result, row))
                self.assertEqual(set(opened), {"version", "id", "project", "project_name", "goal", "state", "created",
                                              "record_sha256", "history_sha256", "notes"})
                self.assertEqual((opened["id"], opened["state"]), (row["id"], row["state"]))
                self.assertNotIn(PRIVATE_SENTINEL, json.dumps(opened))
                self.assertNotIn(str(root), json.dumps(opened))
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result))
            self.assertEqual(before, private_hashes(root))

    def test_literal_full_goal_search_beyond_excerpt_unicode_id_and_filters(self):
        with comparison_fixture(seed=False) as (root, manager, _):
            run_id = "a" * 16
            goal = "x" * 400 + " café e\u0301 🧪 <script>literal</script> END"
            write_new(manager.meta_path(run_id), canonical({"id": run_id, "goal": goal, "project": "historical_java",
                       "project_name": "Invented Java", "state": "FAILED", "created": 12}))
            with history_guard(manager):
                before = private_hashes(root)
                for query in ["café", "e\u0301", "🧪", "<script>literal</script>", "END", run_id]:
                    result = manager.run_history_search(history_request(query, "historical_java", "FAILED"))
                    self.assertEqual((result["matched"], result["returned"]), (1, 1))
                    row = result["runs"][0]
                    self.assertEqual(row["match_fields"], ["id"] if query == run_id else ["goal"])
                    self.assertLessEqual(len(row["goal_excerpt"].encode()), 160)
                    if query != run_id: self.assertIn(query, row["goal_excerpt"])
                    opened = manager.run_history_open(open_request(result))
                    self.assertEqual(opened["goal"], goal)
                for query, project, state in [("CAFÉ", "", ""), ("é 🧪", "", ""), ("END", "other", ""), ("END", "", "RUNNING")]:
                    self.assertEqual(manager.run_history_search(history_request(query, project, state))["matched"], 0)
                self.assertEqual(before, private_hashes(root))

    def test_unknown_recognized_fields_are_null_with_notes_and_extras_remain_private(self):
        with comparison_fixture(seed=False) as (root, manager, _):
            run_id = "b" * 16
            write_new(manager.meta_path(run_id), canonical({"id": run_id, "project": "../invalid", "project_name": 9,
                       "goal": ["invalid"], "state": "PROVIDER_DONE", "created": True, "source": PRIVATE_SENTINEL,
                       "model": PRIVATE_SENTINEL, "pid": 999999, "extra": {"private": PRIVATE_SENTINEL}}))
            with history_guard(manager):
                before = private_hashes(root)
                result = manager.run_history_search(history_request("", "UNKNOWN", "UNKNOWN"))
                self.assertEqual(result["projects"], ["UNKNOWN"])
                self.assertEqual(result["matched"], 1)
                opened = manager.run_history_open(open_request(result))
                for key in ["project", "project_name", "goal", "state", "created"]: self.assertIsNone(opened[key])
                self.assertIn("RECORD_INVALID", opened["notes"])
                self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result) + json.dumps(opened))
                self.assertEqual(before, private_hashes(root))

    def test_empty_legacy_record_and_saved_active_states_are_observations_only(self):
        with comparison_fixture(seed=False) as (root, manager, _):
            states = ["RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED", "UNCERTAIN", "INTERRUPTED"]
            for number, state in enumerate(states, 1):
                run_id = format(number, "016x")
                write_new(manager.meta_path(run_id), canonical({"state": state, "created": number}))
            write_new(manager.meta_path("0" * 16), canonical({}))
            child = Mock(); child.poll.side_effect = AssertionError("history polled an owned process")
            manager.children["1" * 16] = (child, Mock())
            try:
                with history_guard(manager):
                    before = private_hashes(root)
                    result = manager.run_history_search(history_request())
                    self.assertEqual(result["returned"], 6)
                    self.assertEqual([row["state"] for row in result["runs"]], list(reversed(states)) + [None])
                    self.assertEqual(result["projects"], ["UNKNOWN"])
                    for row in result["runs"]: manager.run_history_open(open_request(result, row))
                    self.assertEqual(before, private_hashes(root))
                child.poll.assert_not_called()
            finally:
                manager.children.clear()

    def test_source_config_tasks_results_events_and_hold_are_not_needed_or_read(self):
        with comparison_fixture() as (root, manager, ids):
            manager.config_path.write_bytes(b"{invented invalid current config")
            project = manager.projects["arithmetic"]
            project["task"].write_bytes(b"{invented invalid current task")
            for path in project["source"].iterdir(): path.unlink()
            project["source"].rmdir()
            for path in (manager.data / "tasks").iterdir(): path.write_bytes(b"{invented invalid saved task")
            for path in (manager.data / "runs").rglob("*.json"): path.write_bytes(b"{invented invalid result or event")
            with history_guard(manager):
                before = private_hashes(root)
                result = manager.run_history_search(history_request())
                opened = manager.run_history_open(open_request(result))
                self.assertEqual((result["returned"], opened["id"]), (len(ids), result["runs"][0]["id"]))
                self.assertEqual(before, private_hashes(root))

    def test_search_schema_query_and_filter_bounds_refuse_without_writes(self):
        with comparison_fixture() as (root, manager, _), history_guard(manager):
            for value in [{}, {**history_request(), "extra": True}, [], None]:
                self.refusal(root, manager.run_history_search, value, "HISTORY_SEARCH_INPUT")
            for query in [None, True, "x" * 129, "🧪" * 33, "a\x00b", "a\rb", "a\nb", "\ud800"]:
                self.refusal(root, manager.run_history_search, history_request(query),
                             "HISTORY_SEARCH_QUERY" if type(query) is str else "HISTORY_SEARCH_INPUT")
            for key, value in [("project", "../private"), ("project", "Bad"), ("project", None),
                               ("state", "complete"), ("state", True), ("state", "uncertain")]:
                self.refusal(root, manager.run_history_search, {**history_request(), key: value},
                             "HISTORY_SEARCH_FILTER" if type(value) is str else "HISTORY_SEARCH_INPUT")

    def test_open_exact_pins_missing_ids_and_record_change_refuse_without_fallback(self):
        with comparison_fixture() as (root, manager, _), history_guard(manager):
            result = manager.run_history_search(history_request())
            request = open_request(result)
            for value in [{}, {**request, "extra": True}, {**request, "id": "../private"},
                          {**request, "id": True}, {**request, "record_sha256": "bad"}, {**request, "history_sha256": None}]:
                self.refusal(root, manager.run_history_open, value)
            self.refusal(root, manager.run_history_open, {**request, "id": "f" * 16}, "HISTORY_SEARCH_NOT_FOUND")
            self.refusal(root, manager.run_history_open, {**request, "record_sha256": "0" * 64}, "HISTORY_SEARCH_RECORD_CHANGED")
            self.refusal(root, manager.run_history_open, {**request, "history_sha256": "0" * 64}, "HISTORY_SEARCH_HISTORY_CHANGED")
            path = manager.meta_path(request["id"])
            path.write_bytes(path.read_bytes() + b" \n")
            self.refusal(root, manager.run_history_open, request, "HISTORY_SEARCH_HISTORY_CHANGED")

    def test_malformed_nonobject_mismatched_id_and_excess_keys_refuse_without_repair(self):
        for raw in [b'{"id":', b'[]', b'{"id":"ffffffffffffffff"}', b'{"id":"a","id":"b"}',
                    canonical({"field" + str(n): n for n in range(65)})]:
            with self.subTest(raw=raw[:80]), comparison_fixture(seed=False) as (root, manager, _):
                write_new(manager.meta_path("a" * 16), raw)
                with history_guard(manager): self.refusal(root, manager.run_history_search, history_request())

    def test_job_file_modes_symlinks_hardlinks_and_store_links_refuse(self):
        for kind in ["mode", "symlink", "hardlink", "directory", "store-mode", "store-link"]:
            with self.subTest(kind=kind), comparison_fixture(seed=False) as (root, manager, _):
                path = manager.meta_path("a" * 16)
                write_new(path, canonical({"id": "a" * 16, "goal": "Invented private metadata."}))
                if kind == "mode": path.chmod(0o640)
                elif kind == "hardlink": os.link(path, root / "invented-job-link")
                elif kind == "symlink":
                    target = root / "invented-job-copy"; write_new(target, path.read_bytes()); path.unlink(); path.symlink_to(target)
                elif kind == "directory": path.unlink(); path.mkdir(mode=0o700)
                elif kind == "store-mode": path.parent.chmod(0o750)
                else:
                    store = path.parent; moved = store.with_name("invented-jobs-original")
                    store.rename(moved); store.symlink_to(moved, target_is_directory=True)
                with history_guard(manager): self.refusal(root, manager.run_history_search, history_request())

    def test_per_record_and_aggregate_read_bounds_refuse_preserving_evidence(self):
        for kind in ["record", "aggregate"]:
            with self.subTest(kind=kind), comparison_fixture(seed=False) as (root, manager, _):
                count = 1 if kind == "record" else 64
                for number in range(count):
                    run_id = format(number, "016x")
                    raw = canonical({"id": run_id, "goal": "Invented metadata read budget."})
                    size = 32769 if kind == "record" else 32767 if number == 63 else 32768
                    write_new(manager.meta_path(run_id), raw + b" " * (size - len(raw)))
                with history_guard(manager):
                    if kind == "aggregate":
                        boundary = manager.run_history_search(history_request())
                        self.assertEqual(boundary["inspected"], 64)
                        run_id = format(64, "016x")
                        raw = canonical({"id": run_id})
                        write_new(manager.meta_path(run_id), raw + b" " * (32768 - len(raw)))
                    self.refusal(root, manager.run_history_search, history_request(), "HISTORY_SEARCH_LIMIT")

    def test_catalog_and_result_bounds_report_partial_inspection_honestly(self):
        with comparison_fixture(seed=False) as (root, manager, _):
            for number in range(201):
                run_id = format(number, "016x")
                write_new(manager.meta_path(run_id), canonical({"id": run_id, "goal": "Invented searchable record.", "created": number}))
            with history_guard(manager):
                before = private_hashes(root)
                result = manager.run_history_search(history_request())
                self.assertEqual((result["inspected"], result["matched"], result["returned"]), (200, 200, 100))
                self.assertTrue(result["catalog_truncated"] and result["result_truncated"])
                self.assertIn("CATALOG_TRUNCATED", result["notes"]); self.assertIn("RESULT_TRUNCATED", result["notes"])
                self.assertLessEqual(len(canonical(result)), 65536)
                self.assertEqual(before, private_hashes(root))
        with comparison_fixture(seed=False) as (root, manager, _):
            for number in range(1025): write_new(manager.data / "jobs" / ("invented-ignored-" + str(number)), b"private ignored")
            with history_guard(manager):
                before = private_hashes(root)
                result = manager.run_history_search(history_request())
                self.assertEqual((result["inspected"], result["matched"], result["returned"]), (0, 0, 0))
                self.assertTrue(result["catalog_truncated"])
                self.assertEqual(before, private_hashes(root))

    def test_search_and_open_repin_metadata_after_pure_computation(self):
        import workbench
        for method, alias in [("run_history_search", "search_history"), ("run_history_open", "review_record")]:
            with self.subTest(method=method), comparison_fixture() as (root, manager, _), history_guard(manager):
                result = manager.run_history_search(history_request())
                request = history_request() if method == "run_history_search" else open_request(result)
                path = manager.meta_path(result["runs"][0]["id"])
                original = getattr(workbench, alias)
                def drift(*args, **kwargs):
                    value = original(*args, **kwargs)
                    path.write_bytes(path.read_bytes() + b" \n")
                    return value
                with patch.object(workbench, alias, side_effect=drift):
                    with self.assertRaisesRegex(Refused, "^HISTORY_SEARCH_HISTORY_CHANGED$"):
                        getattr(manager, method)(request)

    def test_restart_preserves_saved_metadata_search_and_review_with_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = init_demo(root / "workspace", None)
            manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
            try:
                populate_saved_histories(manager)
                with history_guard(manager):
                    result = manager.run_history_search(history_request("Java", "java", "FAILED"))
                    opened = manager.run_history_open(open_request(result))
                before = private_hashes(root)
                config, data = manager.config_path, manager.data
                manager.close()
                manager = None
                manager = Manager(config, data)
                with history_guard(manager):
                    after = manager.run_history_search(history_request("Java", "java", "FAILED"))
                    reviewed = manager.run_history_open(open_request(after))
                self.assertEqual(result, after); self.assertEqual(opened, reviewed)
                self.assertEqual(before, private_hashes(root))
            finally:
                if manager is not None: manager.close()


class RunHistoryHTTPTests(unittest.TestCase):
    def test_http_search_open_roundtrip_returns_only_saved_metadata(self):
        with history_http_fixture() as (root, manager, ids, request), history_guard(manager):
            before = private_hashes(root)
            status, result = request("/api/run-history-search", history_request("Java", "java", ""))
            self.assertEqual((status, result["returned"]), (200, 2))
            status, opened = request("/api/run-history-open", open_request(result))
            self.assertEqual((status, opened["project"]), (200, "java"))
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result) + json.dumps(opened))
            self.assertEqual(before, private_hashes(root))

    def test_http_framing_origin_and_session_are_checked_before_actions(self):
        with history_http_fixture() as (root, manager, _, request):
            for route, method in [("/api/run-history-search", "run_history_search"), ("/api/run-history-open", "run_history_open")]:
                value = history_request()
                with patch.object(manager, method, side_effect=AssertionError("bad framing reached history")) as action:
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                        {"Content-Length": "32769"}, {"Content-Length": "999"}, {"Content-Type": "application/zip"},
                        [("Content-Length", str(len(canonical(value))))], [("Content-Type", "application/json")]]:
                        status, result = request(route, value, headers)
                        self.assertEqual(status, 409); self.assertRegex(result["error"], r"^HISTORY_SEARCH_[A-Z_]+$")
                    for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"),
                        ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"), ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                        ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        status, result = request(route, value, headers)
                        self.assertEqual((status, result["error"]), (409, error))
                    action.assert_not_called()

    def test_http_duplicate_json_invalid_unicode_schema_and_output_caps_refuse(self):
        with history_http_fixture() as (root, manager, _, request):
            for route in ["/api/run-history-search", "/api/run-history-open"]:
                for raw in [b'{"query":"x","query":"y"}', b"\xff", b"[]"]:
                    before = private_hashes(root)
                    status, result = request(route, {}, raw=raw)
                    self.assertEqual(status, 409); self.assertRegex(result["error"], r"^HISTORY_SEARCH_[A-Z_]+$")
                    self.assertEqual(before, private_hashes(root))
            for route, method in [("/api/run-history-search", "run_history_search"), ("/api/run-history-open", "run_history_open")]:
                with patch.object(manager, method, return_value={"invented": "x" * 65536}):
                    status, result = request(route, {})
                    self.assertEqual((status, result["error"]), (409, "HISTORY_SEARCH_OUTPUT_LIMIT"))


if __name__ == "__main__":
    unittest.main()
