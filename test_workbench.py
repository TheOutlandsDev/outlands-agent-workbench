"""Synthetic controller/HTTP tests; model and check execution are mocked here."""

import copy
import http.client
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

from agent import Refused, ScriptedDemo, Session, canonical, sha, write_new
from test_agent import fake_check, fixture
from workbench import Manager, init_demo, make_handler


@contextmanager
def manager_fixture(seed=False):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", "fictional-model")
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        run_id = "0123456789abcdef"
        if seed:
            project = manager.projects["arithmetic"]
            task = copy.deepcopy(project["definition"])
            write_new(manager.data / "tasks" / (run_id + ".json"), canonical(task))
            session = Session(
                task, project["source"], manager.run_path(run_id), fake_check
            )
            result = session.run(
                ScriptedDemo(), manager.data / "state/hold.json", "scripted-demo"
            )
            assert result["status"] == "REVIEW_READY"
            meta = {
                "id": run_id,
                "project": "arithmetic",
                "project_name": "Arithmetic demo",
                "source": str(project["source"]),
                "goal": task["goal"],
                "model": "scripted-demo",
                "backend": "scripted-demo",
                "created": 1,
                "state": "REVIEW_READY",
            }
            write_new(manager.meta_path(run_id), canonical(meta))
        try:
            yield root, manager, run_id
        finally:
            manager.close()


def decision(manager, run_id, verdict="accepted"):
    view = manager.view(run_id)
    return {
        "id": run_id,
        "result_sha256": view["result_sha256"],
        "patch_sha256": view["patch_sha256"],
        "verdict": verdict,
        "note": "Fictional review",
    }


class TargetedEditTests(unittest.TestCase):
    def test_preserves_crlf_unicode_and_final_newline(self):
        with fixture() as (_, session):
            raw = '"""Fictional café."""\r\n\r\ndef add(a,b):\r\n    return a - b\r\n'.encode()
            (session.work / "calculator.py").write_bytes(raw)
            session.tool("set_plan", {"steps": ["Replace one expression"]})
            session.tool(
                "replace_text",
                {
                    "path": "calculator.py",
                    "expected_sha256": sha(raw),
                    "old_text": "a - b",
                    "new_text": "a + b",
                },
            )
            self.assertEqual(
                (session.work / "calculator.py").read_bytes(),
                raw.replace(b"a - b", b"a + b"),
            )

    def test_duplicate_match_refused(self):
        with fixture() as (_, session):
            raw = b"same same\n"
            (session.work / "calculator.py").write_bytes(raw)
            session.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaisesRegex(Refused, "REPLACEMENT_NOT_UNIQUE"):
                session.tool(
                    "replace_text",
                    {
                        "path": "calculator.py",
                        "expected_sha256": sha(raw),
                        "old_text": "same",
                        "new_text": "new",
                    },
                )
            self.assertEqual((session.work / "calculator.py").read_bytes(), raw)

    def test_missing_match_refused(self):
        with fixture() as (_, session):
            raw = (session.work / "calculator.py").read_bytes()
            session.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaisesRegex(Refused, "REPLACEMENT_NOT_UNIQUE"):
                session.tool(
                    "replace_text",
                    {
                        "path": "calculator.py",
                        "expected_sha256": sha(raw),
                        "old_text": "not present",
                        "new_text": "new",
                    },
                )

    def test_empty_match_refused(self):
        with fixture() as (_, session):
            raw = (session.work / "calculator.py").read_bytes()
            session.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaisesRegex(Refused, "REPLACEMENT_LIMIT"):
                session.tool(
                    "replace_text",
                    {
                        "path": "calculator.py",
                        "expected_sha256": sha(raw),
                        "old_text": "",
                        "new_text": "new",
                    },
                )

    def test_whole_file_tool_removed(self):
        with fixture() as (_, session):
            session.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaisesRegex(Refused, "UNKNOWN_TOOL"):
                session.tool(
                    "write_file", {"path": "calculator.py", "content": "changed"}
                )


class ControllerTests(unittest.TestCase):
    def test_config_view_has_no_absolute_paths(self):
        with manager_fixture() as (_, manager, _):
            public = manager.config_view()
            self.assertNotIn("source", public["projects"][0])
            self.assertNotIn("task", public["projects"][0])
            self.assertEqual(public["projects"][0]["editable"], ["calculator.py"])

    def test_accept_export_preserves_original(self):
        with manager_fixture(True) as (_, manager, run_id):
            before = (
                manager.projects["arithmetic"]["source"] / "calculator.py"
            ).read_bytes()
            with self.assertRaisesRegex(Refused, "REVIEW_REQUIRED"):
                manager.export(run_id)
            record = manager.review(decision(manager, run_id))
            self.assertFalse(record["source_applied"])
            self.assertIn(b"+    return a + b", manager.export(run_id))
            self.assertEqual(
                (
                    manager.projects["arithmetic"]["source"] / "calculator.py"
                ).read_bytes(),
                before,
            )

    def test_reject_and_later_accept_retained(self):
        with manager_fixture(True) as (_, manager, run_id):
            manager.review(decision(manager, run_id, "rejected"))
            with self.assertRaisesRegex(Refused, "REVIEW_REQUIRED"):
                manager.export(run_id)
            manager.review(decision(manager, run_id))
            self.assertEqual(
                len(list(manager.run_path(run_id).glob("review-*.json"))), 2
            )

    def test_source_change_blocks_review(self):
        with manager_fixture(True) as (_, manager, run_id):
            request = decision(manager, run_id)
            (manager.projects["arithmetic"]["source"] / "calculator.py").write_text(
                "changed"
            )
            with self.assertRaisesRegex(Refused, "ORIGINAL_SOURCE_CHANGED"):
                manager.review(request)

    def test_candidate_change_blocks_export(self):
        with manager_fixture(True) as (_, manager, run_id):
            manager.review(decision(manager, run_id))
            (manager.run_path(run_id) / "work/calculator.py").write_text("changed")
            with self.assertRaisesRegex(Refused, "CANDIDATE_CHANGED"):
                manager.export(run_id)

    def test_patch_change_blocks_export(self):
        with manager_fixture(True) as (_, manager, run_id):
            manager.review(decision(manager, run_id))
            (manager.run_path(run_id) / "changes.diff").write_text("changed")
            with self.assertRaisesRegex(Refused, "PATCH_CHANGED"):
                manager.export(run_id)

    def test_stale_review_hash_refused(self):
        with manager_fixture(True) as (_, manager, run_id):
            request = decision(manager, run_id)
            request["result_sha256"] = "0" * 64
            with self.assertRaisesRegex(Refused, "RESULT_CHANGED"):
                manager.review(request)

    def test_hold_blocks_start(self):
        with manager_fixture() as (_, manager, _):
            write_new(
                manager.data / "state/hold.json", canonical({"state": "unsettled"})
            )
            project = manager.projects["arithmetic"]
            with self.assertRaisesRegex(Refused, "UNCERTAIN_REQUEST_HELD"):
                manager.start(
                    {
                        "project": "arithmetic",
                        "model": "scripted-demo",
                        "goal": project["definition"]["goal"],
                    }
                )

    def test_recovery_blocks_start(self):
        with manager_fixture() as (_, manager, run_id):
            write_new(
                manager.meta_path(run_id),
                canonical(
                    {
                        "id": run_id,
                        "state": "RUNNING",
                        "created": 1,
                        "pid": 99999999,
                        "process_stamp": "0",
                    }
                ),
            )
            self.assertEqual(manager.admission(), "TASK_ACTIVE_OR_UNRESOLVED")
            self.assertEqual(manager.history()[0]["state"], "RECOVERY_REQUIRED")

    def test_history_limit_does_not_hide_admission_hold(self):
        with manager_fixture() as (_, manager, _):
            for i in range(101):
                run_id = f"{i:016x}"
                write_new(
                    manager.meta_path(run_id),
                    canonical(
                        {
                            "id": run_id,
                            "created": i,
                            "state": "RECOVERY_REQUIRED" if i == 0 else "FAILED",
                        }
                    ),
                )
            self.assertEqual(len(manager.history()), 100)
            self.assertEqual(manager.admission(), "TASK_ACTIVE_OR_UNRESOLVED")

    def test_second_server_lock_refused(self):
        with (
            manager_fixture() as (root, manager, _),
            self.assertRaisesRegex(Refused, "SERVER_ALREADY_RUNNING"),
        ):
            Manager(root / "workspace/config.json", manager.data)

    def test_unknown_model_and_project_refused(self):
        with manager_fixture() as (_, manager, _):
            for value in [
                {"project": "unknown", "model": "scripted-demo", "goal": "Fix"},
                {"project": "arithmetic", "model": "unconfigured", "goal": "Fix"},
            ]:
                with self.assertRaises(Refused):
                    manager.start(value)

    def test_run_path_traversal_refused(self):
        with (
            manager_fixture() as (_, manager, _),
            self.assertRaisesRegex(Refused, "RUN_ID"),
        ):
            manager.view("../../secret")


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.context = manager_fixture()
        _, self.manager, _ = self.context.__enter__()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), object)
        self.server.daemon_threads = True
        self.origin = "http://127.0.0.1:" + str(self.server.server_address[1])
        self.server.RequestHandlerClass = make_handler(
            self.manager, "fictional-unit-token", self.origin
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.context.__exit__(None, None, None)

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_page_and_csp(self):
        code, headers, raw = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"OUTLANDS", raw)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_api_requires_session(self):
        self.assertEqual(self.request("GET", "/api/history")[0], 403)

    def test_api_with_session(self):
        code, _, raw = self.request(
            "GET", "/api/config", {"X-Workbench-Token": "fictional-unit-token"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["projects"][0]["id"], "arithmetic")

    def test_host_guard(self):
        self.assertEqual(
            self.request("GET", "/", {"Host": "malicious.invalid"})[0], 403
        )

    def test_cross_site_guard(self):
        self.assertEqual(
            self.request("GET", "/", {"Sec-Fetch-Site": "cross-site"})[0], 403
        )

    def test_post_origin_guard(self):
        code, _, raw = self.request(
            "POST",
            "/api/start",
            {
                "X-Workbench-Token": "fictional-unit-token",
                "Origin": "https://malicious.invalid",
                "Content-Type": "application/json",
            },
            b"{}",
        )
        self.assertEqual(code, 409)
        self.assertEqual(json.loads(raw)["error"], "ORIGIN_REFUSED")

    def test_static_traversal(self):
        self.assertEqual(self.request("GET", "/../agent.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
