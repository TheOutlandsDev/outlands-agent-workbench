"""Invented private workspace navigation, stale evidence and bounded HTTP tests.

Private Git fixtures use clearly invented saved check observations. Actual
isolated Python/Java checks are separate in qa_workspace_search.py. Navigation
itself is guarded against execution, provider calls and filesystem writes.
"""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_bundle_workspace_integration import private_hashes
from test_snapshot_editor_integration import editor_guard, editor_preview, save_request
from test_snapshot_recheck_integration import populate_recheck_workspaces, recheck_fixture
from workbench import Manager, init_demo, make_handler


@contextmanager
def search_guard(manager, *, open_editor=False):
    """Navigation never runs code or reconciles workers; only handoff reads admission."""
    with editor_guard(manager), ExitStack() as stack:
        if not open_editor:
            for name in ["readiness_admission", "_snapshot_editor_admission"]:
                stack.enter_context(patch.object(manager, name,
                    side_effect=AssertionError("search/read reached saved admission " + name)))
        stack.enter_context(patch("workbench.readiness_presence", side_effect=AssertionError("navigation probed executable")))
        yield


def search_request(fixture, query="a + b"):
    return {"workspace_id": fixture["workspace_id"], "query": query}


def selected_hit(result, *, editable=True):
    return next(hit for hit in result["result"]["matches"] if hit["editable"] is editable)


def open_request(result, hit):
    return {"workspace_id": result["workspace_id"], "path": hit["path"],
            "expected_sha256": hit["sha256"], "snapshot_sha256": result["snapshot_sha256"]}


def read_request(result, hit, start_line=None, end_line=None):
    start_line = hit["line_number"] if start_line is None else start_line
    end_line = start_line if end_line is None else end_line
    return {**open_request(result, hit), "start_line": start_line, "end_line": end_line}


class WorkspaceSearchIntegrationTests(unittest.TestCase):
    def refusal(self, root, operation, request, code=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(request)
        self.assertRegex(str(caught.exception), r"^WORKSPACE_SEARCH_[A-Z_]{1,48}$")
        if code is not None:
            self.assertEqual(str(caught.exception), code)
        self.assertNotIn(str(root), str(caught.exception))
        self.assertEqual(before, private_hashes(root))

    def test_python_java_search_has_exact_line_hash_scope_and_no_writes(self):
        with recheck_fixture(("python", "java")) as (root, manager, fixtures), search_guard(manager):
            before = private_hashes(root)
            for language, fixture in fixtures.items():
                with self.subTest(language=language):
                    result = manager.workspace_search(search_request(fixture, "add"))
                    self.assertEqual(result["version"], 1)
                    self.assertEqual(result["workspace_id"], fixture["workspace_id"])
                    self.assertRegex(result["snapshot_sha256"], r"^[0-9a-f]{64}$")
                    definition = manager.projects[fixture["project_id"]]["definition"]
                    self.assertEqual(result["result"]["files_searched"], len(definition["files"]))
                    self.assertEqual({hit["editable"] for hit in result["result"]["matches"]}, {False, True})
                    for hit in result["result"]["matches"]:
                        raw = (fixture["workspace"] / hit["path"]).read_bytes()
                        line = raw.decode().splitlines()[hit["line_number"] - 1]
                        self.assertEqual(hit["sha256"], sha(raw))
                        self.assertEqual(hit["column"], line.find("add") + 1)
                        self.assertEqual(hit["editable"], hit["path"] in definition["editable"])
                    self.assertLessEqual(len(canonical(result)), 16384)
                    self.assertNotIn(str(root), json.dumps(result))
            self.assertEqual(before, private_hashes(root))

    def test_protected_excerpt_is_readable_but_cannot_open_for_edit(self):
        with recheck_fixture(("python", "java")) as (root, manager, fixtures):
            for fixture in fixtures.values():
                with search_guard(manager):
                    result = manager.workspace_search(search_request(fixture, "add"))
                    hit = selected_hit(result, editable=False)
                    read = manager.workspace_read(read_request(result, hit))
                    self.assertFalse(read["editable"])
                    self.assertEqual(read["result"]["sha256"], hit["sha256"])
                    self.assertEqual(read["result"]["start_line"], hit["line_number"])
                    self.assertIn("add", read["result"]["lines"][0]["text"])
                with search_guard(manager, open_editor=True):
                    self.refusal(root, manager.workspace_search_open, open_request(result, hit), "WORKSPACE_SEARCH_PROTECTED")

    def test_unicode_crlf_cr_and_line_numbers_preserve_underlying_bytes(self):
        with recheck_fixture() as (root, manager, fixtures), search_guard(manager):
            fixture = fixtures["python"]
            path = fixture["workspace"] / "arithmetic.py"
            raw = "# café Ω\r\ndef add(a, b):\r    return a + b\n# café終".encode()
            path.write_bytes(raw)
            before = private_hashes(root)
            result = manager.workspace_search(search_request(fixture, "café"))
            self.assertEqual([hit["line_number"] for hit in result["result"]["matches"]], [1, 4])
            read = manager.workspace_read(read_request(result, result["result"]["matches"][0], 1, 4))
            self.assertEqual([row["text"] for row in read["result"]["lines"]],
                             ["# café Ω", "def add(a, b):", "    return a + b", "# café終"])
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(before, private_hashes(root))

    def test_empty_file_has_no_invented_lines_or_search_matches(self):
        with recheck_fixture() as (root, manager, fixtures), search_guard(manager):
            fixture = fixtures["python"]
            (fixture["workspace"] / "arithmetic.py").write_bytes(b"")
            result = manager.workspace_search(search_request(fixture, "a + b"))
            self.assertEqual(result["result"]["matches"], [])
            request = {"workspace_id": fixture["workspace_id"], "path": "arithmetic.py",
                "expected_sha256": sha(b""), "snapshot_sha256": result["snapshot_sha256"], "start_line": 1, "end_line": 20}
            before = private_hashes(root)
            read = manager.workspace_read(request)
            self.assertEqual(read["result"]["lines"], [])
            self.assertEqual(read["result"]["total_lines"], 0)
            self.assertTrue(read["result"]["end_of_file"])
            self.assertEqual(before, private_hashes(root))

    def test_hit_and_excerpt_clipping_are_explicit_with_bounded_json(self):
        with recheck_fixture() as (root, manager, fixtures), search_guard(manager):
            fixture = fixtures["python"]
            raw = ("# needle " + "Ω" * 700 + "\n" + "# needle\n" * 39).encode()
            (fixture["workspace"] / "arithmetic.py").write_bytes(raw)
            before = private_hashes(root)
            result = manager.workspace_search(search_request(fixture, "needle"))
            self.assertEqual(result["result"]["total_matches"], 40)
            self.assertLessEqual(len(result["result"]["matches"]), 20)
            self.assertTrue(result["result"]["truncated"])
            self.assertTrue(result["result"]["matches"][0]["truncated"])
            self.assertLessEqual(len(canonical(result)), 16384)
            read = manager.workspace_read(read_request(result, result["result"]["matches"][0], 1, 40))
            self.assertTrue(read["result"]["truncated"])
            self.assertTrue(read["result"]["lines"][0]["truncated"])
            self.assertLessEqual(len(canonical(read)), 16384)
            self.assertEqual(before, private_hashes(root))

    def test_invalid_query_and_exact_request_fields_refuse_without_writes(self):
        with recheck_fixture() as (root, manager, fixtures), search_guard(manager):
            fixture = fixtures["python"]
            for query in ["", "a\nb", "a\rb", "\x00", "a" * 129, "Ω" * 65, "\ud800", None, True]:
                self.refusal(root, manager.workspace_search, search_request(fixture, query))
            for value in [{}, {**search_request(fixture), "extra": 1}, {"workspace_id": fixture["workspace_id"]}]:
                self.refusal(root, manager.workspace_search, value, "WORKSPACE_SEARCH_INPUT")
            for identifier in ["", "../private", "f" * 16, None, True]:
                self.refusal(root, manager.workspace_search, {"workspace_id": identifier, "query": "add"})

    def test_stale_file_and_full_snapshot_hashes_refuse_read_and_handoff(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixture))
            hit = selected_hit(result)
            for key in ["expected_sha256", "snapshot_sha256"]:
                read = {**read_request(result, hit), key: "0" * 64}
                opened = {**open_request(result, hit), key: "0" * 64}
                with search_guard(manager):
                    self.refusal(root, manager.workspace_read, read, "WORKSPACE_SEARCH_STALE")
                with search_guard(manager, open_editor=True):
                    self.refusal(root, manager.workspace_search_open, opened, "WORKSPACE_SEARCH_STALE")

    def test_another_editable_file_change_invalidates_whole_snapshot_pin(self):
        with recheck_fixture(("mixed",)) as (root, manager, fixtures):
            fixture = fixtures["mixed"]
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixture, "a + b"))
            hit = selected_hit(result)
            other = fixture["workspace"] / "increment.py"
            other.write_bytes(other.read_bytes() + b"# externally changed invented editable file\n")
            with search_guard(manager):
                self.refusal(root, manager.workspace_read, read_request(result, hit), "WORKSPACE_SEARCH_STALE")
            with search_guard(manager, open_editor=True):
                self.refusal(root, manager.workspace_search_open, open_request(result, hit), "WORKSPACE_SEARCH_STALE")

    def test_original_source_config_task_git_and_protected_drift_refuse(self):
        for kind in ["source", "config", "task", "git", "protected"]:
            with self.subTest(kind=kind), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                with search_guard(manager):
                    result = manager.workspace_search(search_request(fixture))
                hit = selected_hit(result)
                path = {"source": fixture["source"] / hit["path"], "config": manager.config_path,
                        "task": fixture["task"], "git": fixture["workspace"] / ".git",
                        "protected": fixture["workspace"] / "test_arithmetic.py"}[kind]
                path.write_bytes(path.read_bytes() + b" \n")
                with search_guard(manager):
                    self.refusal(root, manager.workspace_search, search_request(fixture))
                    self.refusal(root, manager.workspace_read, read_request(result, hit))
                with search_guard(manager, open_editor=True):
                    self.refusal(root, manager.workspace_search_open, open_request(result, hit))

    def test_unselected_original_source_is_not_discovered_or_returned(self):
        with recheck_fixture() as (root, manager, fixtures), search_guard(manager):
            fixture = fixtures["python"]
            sentinel = "invented-unselected-workspace-search-sentinel"
            write_new(fixture["source"] / "unselected-notes.txt", sentinel.encode())
            before = private_hashes(root)
            result = manager.workspace_search(search_request(fixture, sentinel))
            self.assertEqual(result["result"]["total_matches"], 0)
            self.assertEqual(result["result"]["files_searched"], 2)
            self.assertEqual(before, private_hashes(root))

    def test_unselected_traversal_and_control_paths_cannot_read_or_open(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixture))
            hit = selected_hit(result)
            for path in ["unselected.py", "../arithmetic.py", "/outside.py", ".git", "workspace/review/arithmetic.py"]:
                with search_guard(manager):
                    self.refusal(root, manager.workspace_read, {**read_request(result, hit), "path": path})
                with search_guard(manager, open_editor=True):
                    self.refusal(root, manager.workspace_search_open, {**open_request(result, hit), "path": path})

    def test_selected_symlink_and_hardlink_refuse_without_following(self):
        for kind in ["symlink", "hardlink"]:
            with self.subTest(kind=kind), recheck_fixture() as (root, manager, fixtures), search_guard(manager):
                fixture = fixtures["python"]
                path = fixture["workspace"] / "arithmetic.py"
                outside = root / "invented-other-file.txt"
                write_new(outside, path.read_bytes())
                path.unlink()
                if kind == "symlink":
                    path.symlink_to(outside)
                else:
                    import os
                    os.link(outside, path)
                self.refusal(root, manager.workspace_search, search_request(fixture))

    def test_unrelated_hold_is_not_read_by_search_or_read_and_blocks_only_save(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            hold = manager.data / "state/hold.json"
            raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented navigation hold", "turn": 1})
            write_new(hold, raw)
            before = private_hashes(root)
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixture))
                hit = selected_hit(result)
                manager.workspace_read(read_request(result, hit))
            with search_guard(manager, open_editor=True):
                opened = manager.workspace_search_open(open_request(result, hit))
                self.assertTrue(opened["admission"]["blocked"])
            with editor_guard(manager):
                preview = manager.snapshot_editor_preview({"workspace_id": fixture["workspace_id"], "path": hit["path"],
                    "expected_sha256": hit["sha256"], "old_text": "a + b", "new_text": "(a + b)"})
                with self.assertRaisesRegex(Refused, "SNAPSHOT_EDITOR_BLOCKED"):
                    manager.snapshot_editor_save(save_request(preview))
            self.assertEqual(before, private_hashes(root))
            self.assertEqual(hold.read_bytes(), raw)

    def test_owned_worker_entry_is_not_polled_by_navigation(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            child = Mock(); child.poll.side_effect = AssertionError("navigation polled a worker")
            manager.children["1" * 16] = (child, Mock())
            try:
                before = private_hashes(root)
                with search_guard(manager):
                    result = manager.workspace_search(search_request(fixture))
                    manager.workspace_read(read_request(result, selected_hit(result)))
                with search_guard(manager, open_editor=True):
                    opened = manager.workspace_search_open(open_request(result, selected_hit(result)))
                self.assertTrue(opened["admission"]["blocked"])
                child.poll.assert_not_called()
                self.assertEqual(before, private_hashes(root))
            finally:
                manager.children.clear()

    def test_unresolved_edit_evidence_refuses_navigation_without_repair(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixture))
            directory = manager.data / "snapshot-workspace-edits" / ("1" * 16)
            directory.mkdir(mode=0o700)
            write_new(directory / "receipt.json", b'{"status":"PREPARING"}')
            hit = selected_hit(result)
            with search_guard(manager):
                self.refusal(root, manager.workspace_search, search_request(fixture), "WORKSPACE_SEARCH_UNRESOLVED")
                self.refusal(root, manager.workspace_read, read_request(result, hit), "WORKSPACE_SEARCH_UNRESOLVED")
            with search_guard(manager, open_editor=True):
                self.refusal(root, manager.workspace_search_open, open_request(result, hit), "WORKSPACE_SEARCH_UNRESOLVED")

    def test_range_and_pin_types_refuse_without_source_or_history_writes(self):
        with recheck_fixture() as (root, manager, fixtures), search_guard(manager):
            result = manager.workspace_search(search_request(fixtures["python"]))
            hit = selected_hit(result)
            for start, end in [(True, 1), (1, True), (0, 1), (2, 1), (1, 81), (1000001, 1000001), (1000, 1000)]:
                self.refusal(root, manager.workspace_read, read_request(result, hit, start, end), "WORKSPACE_SEARCH_RANGE")
            for key in ["expected_sha256", "snapshot_sha256"]:
                for value in [None, True, "a" * 63, "A" * 64]:
                    self.refusal(root, manager.workspace_read, {**read_request(result, hit), key: value})
            self.refusal(root, manager.workspace_read, {**read_request(result, hit), "extra": True}, "WORKSPACE_SEARCH_INPUT")

    def test_drift_during_search_read_or_open_is_refused_before_response(self):
        import workbench
        for action, symbol in [("search", "search_workspace"), ("read", "read_workspace"), ("open", "read_snapshot_editor")]:
            with self.subTest(action=action), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                with search_guard(manager):
                    result = manager.workspace_search(search_request(fixture))
                hit = selected_hit(result)
                target = fixture["workspace"] / hit["path"]
                original = getattr(workbench, symbol)
                def changed(*args, **kwargs):
                    value = original(*args, **kwargs)
                    target.write_bytes(target.read_bytes() + b"# invented concurrent owner edit\n")
                    return value
                before = private_hashes(root)
                with search_guard(manager, open_editor=action == "open"), patch("workbench." + symbol, side_effect=changed):
                    with self.assertRaisesRegex(Refused, "WORKSPACE_SEARCH_STALE"):
                        if action == "search": manager.workspace_search(search_request(fixture))
                        elif action == "read": manager.workspace_read(read_request(result, hit))
                        else: manager.workspace_search_open(open_request(result, hit))
                relative = str(target.relative_to(root))
                self.assertEqual({n: d for n, d in before.items() if n != relative},
                                 {n: d for n, d in private_hashes(root).items() if n != relative})

    def test_pinned_handoff_invalidates_old_editor_preview_without_saving(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with editor_guard(manager):
                _, preview = editor_preview(manager, fixture)
            before = private_hashes(root)
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixture))
            with search_guard(manager, open_editor=True):
                opened = manager.workspace_search_open(open_request(result, selected_hit(result)))
            self.assertEqual(opened["text"].encode(), (fixture["workspace"] / opened["path"]).read_bytes())
            with editor_guard(manager), self.assertRaisesRegex(Refused, "SNAPSHOT_EDITOR_PREVIEW_REQUIRED"):
                manager.snapshot_editor_save(save_request(preview))
            self.assertEqual(before, private_hashes(root))

    def test_search_after_explicit_save_returns_new_hash_and_old_pin_stays_stale(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with search_guard(manager):
                first = manager.workspace_search(search_request(fixture))
            hit = selected_hit(first)
            with editor_guard(manager):
                _, preview = editor_preview(manager, fixture)
                saved = manager.snapshot_editor_save(save_request(preview))
            before = private_hashes(root)
            with search_guard(manager):
                refreshed = manager.workspace_search(search_request(fixture))
                self.refusal(root, manager.workspace_read, read_request(first, hit), "WORKSPACE_SEARCH_STALE")
            self.assertNotEqual(first["snapshot_sha256"], refreshed["snapshot_sha256"])
            self.assertEqual(selected_hit(refreshed)["sha256"], saved["after_sha256"])
            self.assertEqual(before, private_hashes(root))

    def test_stateless_pinned_read_after_restart_preserves_saved_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = init_demo(root / "workspace", None)
            manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
            fixtures = populate_recheck_workspaces(manager, root, ("python",))
            with search_guard(manager):
                result = manager.workspace_search(search_request(fixtures["python"]))
            config, data = manager.config_path, manager.data
            manager.close()
            before = private_hashes(root)
            reopened = Manager(config, data)
            try:
                with search_guard(reopened):
                    read = reopened.workspace_read(read_request(result, selected_hit(result)))
                self.assertEqual(read["snapshot_sha256"], result["snapshot_sha256"])
                self.assertEqual(before, private_hashes(root))
            finally:
                reopened.close()


@contextmanager
def search_http_fixture():
    with recheck_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-search-token", "http://127.0.0.1:8765")
        def request(path, value, headers=None, raw=None):
            raw = canonical(value) if raw is None else raw
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-search-token",
                "Origin": "http://127.0.0.1:8765", "Content-Type": "application/json", "Content-Length": str(len(raw))}
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
        yield root, manager, fixtures, request


class WorkspaceSearchHTTPTests(unittest.TestCase):
    def test_search_protected_range_and_editable_handoff_routes_are_read_only(self):
        with search_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]
            before = private_hashes(root)
            with search_guard(manager):
                code, result = request("/api/workspace-search", search_request(fixture, "add"))
                self.assertEqual(code, 200)
                hit = selected_hit(result, editable=False)
                code, read = request("/api/workspace-read", read_request(result, hit))
                self.assertEqual((code, read["editable"]), (200, False))
            with search_guard(manager, open_editor=True):
                code, opened = request("/api/workspace-search-open", open_request(result, selected_hit(result)))
                self.assertEqual((code, opened["editable"]), (200, True))
                self.assertEqual(opened["sha256"], selected_hit(result)["sha256"])
            self.assertEqual(before, private_hashes(root))

    def test_exact_framing_and_authentication_precede_every_navigation_route(self):
        with search_http_fixture() as (root, manager, fixtures, request):
            routes = [("/api/workspace-search", "workspace_search"), ("/api/workspace-read", "workspace_read"),
                      ("/api/workspace-search-open", "workspace_search_open")]
            for path, method in routes:
                with patch.object(manager, method, side_effect=AssertionError("malformed request reached navigation")) as invoke:
                    value = search_request(fixtures["python"])
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                        {"Content-Length": "32769"}, {"Content-Length": "999"}, {"Content-Type": "application/zip"},
                        [("Content-Length", str(len(canonical(value))))], [("Content-Type", "application/json")]]:
                        before = private_hashes(root)
                        code, result = request(path, value, headers)
                        self.assertEqual(code, 409)
                        self.assertRegex(result["error"], r"^WORKSPACE_SEARCH_[A-Z_]+$")
                        self.assertEqual(before, private_hashes(root))
                    for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"),
                        ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"),
                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"), ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        code, result = request(path, value, headers)
                        self.assertEqual((code, result["error"]), (409, error))
                    invoke.assert_not_called()

    def test_duplicate_keys_invalid_unicode_and_unknown_routes_are_finite(self):
        with search_http_fixture() as (root, manager, fixtures, request):
            for path, raw in [("/api/workspace-search", b'{"workspace_id":"a","workspace_id":"b"}'),
                              ("/api/workspace-read", b"\xff"), ("/api/workspace-search-unknown", b"{}")]:
                before = private_hashes(root)
                code, result = request(path, {}, raw=raw)
                self.assertEqual(code, 409)
                self.assertRegex(result["error"], r"^WORKSPACE_SEARCH_[A-Z_]+$")
                self.assertEqual(before, private_hashes(root))

    def test_output_limits_are_route_specific_and_large_pinned_file_can_open(self):
        with search_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]
            path = fixture["workspace"] / "arithmetic.py"
            path.write_bytes(b"# needle " + b"x" * 20000)
            before = private_hashes(root)
            with search_guard(manager):
                code, result = request("/api/workspace-search", search_request(fixture, "needle"))
                self.assertEqual(code, 200)
                hit = selected_hit(result)
            with search_guard(manager, open_editor=True):
                code, opened = request("/api/workspace-search-open", open_request(result, hit))
            self.assertEqual(code, 200)
            self.assertGreater(len(canonical(opened)), 16384)
            self.assertLessEqual(len(canonical(opened)), 262144)
            for path, method, limit in [("/api/workspace-search", "workspace_search", 16384),
                                        ("/api/workspace-read", "workspace_read", 16384),
                                        ("/api/workspace-search-open", "workspace_search_open", 262144)]:
                with patch.object(manager, method, return_value={"invented": "x" * limit}):
                    code, failure = request(path, {})
                    self.assertEqual((code, failure["error"]), (409, "WORKSPACE_SEARCH_OUTPUT_LIMIT"))
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()
