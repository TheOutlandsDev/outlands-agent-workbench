"""Offline workflow HTTP/session regressions; workers are never launched here.

Actual scripted-worker acceptance uses a separate persistent directory through
qa_offline_workflow.py so failures and partial evidence are retained.
"""

import copy
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, ScriptedDemo, Session, canonical, gate, sha, write_new
from offline_workflow import WorkflowManager, expected_command, initialize, new_counters, offline_handler, python_report, validate_fixture
from test_agent import fake_check
from workbench import Manager as BaseManager


def snapshot(root):
    rows = {}
    for path in root.rglob("*"):
        info = path.lstat()
        row = {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "links": info.st_nlink}
        if stat.S_ISREG(info.st_mode): row["sha256"] = sha(path.read_bytes())
        elif stat.S_ISLNK(info.st_mode): row["link"] = os.readlink(path)
        rows[path.relative_to(root).as_posix()] = row
    return rows


def start_request(manager):
    return {"project": "arithmetic", "model": "scripted-demo", "goal": manager.projects["arithmetic"]["definition"]["goal"]}


def seed_completed(manager, identifier="1" * 16):
    """Unit-only Session shapes: mocked checks and fabricated worker receipts.

    No Popen, actual check, network guard execution or child is claimed. The
    current test PID merely supplies a consistent positive receipt identity.
    Actual acceptance never uses this helper.
    """
    root, marker = manager.root, manager.marker
    data = root / "workspace/data"
    task = copy.deepcopy(manager.projects["arithmetic"]["definition"])
    write_new(root / "receipts/start-claim.json", canonical({"version": 1, "fixture_id": marker["fixture_id"], "attempt": 1}))
    write_new(root / "receipts/launch.json", canonical({"version": 1, "id": identifier, "fixture_id": marker["fixture_id"],
              "argv": expected_command(root, identifier), "task_sha256": sha(canonical(task))}))
    for name in ["parent-started.json", "worker-start.json"]:
        write_new(root / "receipts" / name, canonical({"version": 1, "id": identifier,
                  "fixture_id": marker["fixture_id"], "pid": os.getpid()}))
    write_new(data / "tasks" / (identifier + ".json"), canonical(task))
    with gate(data / "state") as hold:
        result = Session(task, root / "workspace/project", data / "runs" / identifier, checker=fake_check).run(
            ScriptedDemo(), hold, "scripted-demo")
    metadata = {"id": identifier, "project": "arithmetic", "project_name": "Arithmetic demo",
                "source": str(root / "workspace/project"), "project_task_sha256": marker["files"]["workspace/task.json"],
                "task_sha256": sha(canonical(task)), "goal": task["goal"], "backend": "scripted-demo", "model": "scripted-demo",
                "created": 1, "finished": 2, "state": "REVIEW_READY", "exit_code": 0, "pid": os.getpid()}
    write_new(data / "jobs" / (identifier + ".json"), canonical(metadata))
    write_new(data / "jobs" / (identifier + ".log"), b"Unit-only invented worker log; no child or actual checks.\n")
    write_new(root / "receipts/worker-exit.json", canonical({"version": 1, "id": identifier,
              "fixture_id": marker["fixture_id"], "pid": os.getpid(), "exit_code": 0, "provider_attempts": 0,
              "network_attempts": 0, "python_level_guards": True, "os_wide_packet_audit": False}))
    manager.refresh(metadata)
    return identifier, result


@contextmanager
def workflow_fixture():
    with tempfile.TemporaryDirectory() as directory, patch("offline_workflow.REAL_POPEN", side_effect=AssertionError(
            "integration unit fixture attempted a real worker")) as spawn:
        root = Path(directory) / "workflow"
        marker = initialize(root)
        manager = WorkflowManager(root)
        try:
            yield root, manager, marker, spawn
        finally:
            manager.close()


def memory_http(manager, token="invented-workflow-token", origin="http://127.0.0.1:8765"):
    handler_type = offline_handler(manager, token, origin, manager.counters)
    def request(path, value=None, headers=None, raw=None, method="POST"):
        raw = canonical(value) if raw is None and method == "POST" else b"" if raw is None else raw
        supplied = {"Host": origin.split("://", 1)[1], "X-Workbench-Token": token, "Origin": origin,
                    "Content-Type": "application/json", "Content-Length": str(len(raw))}
        duplicates = headers if isinstance(headers, list) else []
        if isinstance(headers, dict): supplied.update(headers)
        handler = handler_type.__new__(handler_type)
        handler.command, handler.path = method, path
        handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
        handler.headers = Message()
        for key, value in list(supplied.items()) + duplicates: handler.headers[key] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        getattr(handler, "do_" + method)()
        head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        status = int(head.split(b" ", 2)[1])
        kind = next((line for line in head.split(b"\r\n") if line.lower().startswith(b"content-type:")), b"")
        return status, json.loads(body) if b"application/json" in kind else body
    return request


class OfflineWorkflowIntegrationTests(unittest.TestCase):
    def refused(self, operation, *args, **kwargs):
        with self.assertRaises(Refused) as caught: operation(*args, **kwargs)
        self.assertRegex(str(caught.exception), r"^OFFLINE_WORKFLOW_[A-Z_]{1,64}$")
        self.assertNotIn("/", str(caught.exception))
        return str(caught.exception)

    def test_initialize_and_validate_are_private_exact_and_read_only(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            self.assertEqual(marker["format"], "outlands-offline-workflow-v1")
            self.assertEqual(marker["version"], 1)
            self.assertEqual(marker["work_dir"], str(root))
            self.assertRegex(marker["fixture_id"], r"^[0-9a-f]{32}$")
            self.assertEqual(manager.models, [])
            self.assertEqual(manager.projects["arithmetic"]["source"], root / "workspace/project")
            before = snapshot(root)
            self.assertEqual(validate_fixture(root), marker)
            self.assertEqual(manager.history(), [])
            self.assertEqual(before, snapshot(root))
            self.assertEqual((root.stat().st_mode & 0o777, (root / "fixture.json").stat().st_mode & 0o777), (0o700, 0o600))
            spawn.assert_not_called()

    def test_existing_relative_and_linked_roots_refuse_without_adoption_or_reset(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            before = snapshot(root)
            self.refused(initialize, root)
            self.refused(initialize, Path("invented-relative-workflow"))
            link = root.parent / "invented-workflow-link"; link.symlink_to(root, target_is_directory=True)
            self.refused(initialize, link)
            self.refused(validate_fixture, link)
            self.assertEqual(before, snapshot(root))
            spawn.assert_not_called()

    def test_altered_sources_config_task_marker_and_private_modes_refuse(self):
        for kind in ["source", "protected", "config", "task", "marker", "mode", "root-mode", "hardlink", "symlink", "component"]:
            with self.subTest(kind=kind), workflow_fixture() as (root, manager, marker, spawn):
                source = root / "workspace/project/calculator.py"
                if kind == "source": source.write_bytes(source.read_bytes() + b"# invented changed input\n")
                elif kind == "protected":
                    path = root / "workspace/project/test_calculator.py"; path.write_bytes(path.read_bytes() + b"# invented change\n")
                elif kind == "config":
                    path = root / "workspace/config.json"; value = json.loads(path.read_bytes()); value["models"] = ["invented-model"]
                    path.write_bytes(canonical(value))
                elif kind == "task":
                    path = root / "workspace/task.json"; value = json.loads(path.read_bytes()); value["goal"] += " changed"
                    path.write_bytes(canonical(value))
                elif kind == "marker":
                    path = root / "fixture.json"; value = json.loads(path.read_bytes()); value["unexpected"] = True
                    path.write_bytes(canonical(value))
                elif kind == "mode": source.chmod(0o640)
                elif kind == "root-mode": root.chmod(0o750)
                elif kind == "hardlink": os.link(source, root.parent / "invented-source-link")
                elif kind == "symlink":
                    other = root.parent / "invented-source-copy"; write_new(other, source.read_bytes()); source.unlink(); source.symlink_to(other)
                else:
                    project = root / "workspace/project"; moved = root.parent / "invented-original-project"
                    project.rename(moved); project.symlink_to(moved, target_is_directory=True)
                before = snapshot(root)
                self.refused(validate_fixture, root)
                self.assertEqual(before, snapshot(root))
                spawn.assert_not_called()

    def test_modified_start_project_goal_or_model_never_reaches_worker(self):
        for updates in [{"project": "unknown"}, {"model": "invented-local-model"}, {"goal": "Changed scripted goal"}, {"extra": True}]:
            with self.subTest(updates=updates), workflow_fixture() as (root, manager, marker, spawn):
                original = {name: (root / name).read_bytes() for name in marker["files"]}
                self.refused(manager.start, {**start_request(manager), **updates})
                self.assertEqual(original, {name: (root / name).read_bytes() for name in marker["files"]})
                spawn.assert_not_called()

    def test_spawn_failure_retains_claim_and_failed_evidence_without_second_attempt(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            with patch("offline_workflow.REAL_POPEN", side_effect=OSError("invented private spawn failure")) as failed_spawn:
                self.refused(manager.start, start_request(manager))
                self.assertEqual(failed_spawn.call_count, 1)
            claim = root / "receipts/start-claim.json"
            self.assertTrue(claim.is_file())
            claim_raw = claim.read_bytes()
            jobs = list((root / "workspace/data/jobs").glob("*.json"))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(json.loads(jobs[0].read_bytes())["state"], "FAILED")
            launch = json.loads((root / "receipts/launch.json").read_bytes())
            foreign = "f" * 16 if launch["id"] != "f" * 16 else "e" * 16
            with patch.object(BaseManager, "stop", side_effect=AssertionError("foreign stop reached controller")) as stop, patch(
                    "workbench.os.killpg", side_effect=AssertionError("foreign process group was signalled")) as signal:
                self.refused(manager.stop, foreign)
                stop.assert_not_called(); signal.assert_not_called()
            before = snapshot(root)
            self.refused(manager.start, start_request(manager))
            self.refused(python_report, root)
            self.assertEqual(claim.read_bytes(), claim_raw)
            after = snapshot(root)
            self.assertEqual({name: value for name, value in after.items() if name in before}, before)
            self.assertEqual(manager.counters["worker_launches"], 0)
            spawn.assert_not_called()

    def test_exact_argv_guard_rejects_provider_flags_foreign_paths_and_shell_shapes(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            command = expected_command(root, "a" * 16)
            changed_backend = command.copy(); changed_backend[-1] = "ollama"
            changed_source = command.copy(); changed_source[6] = str(root.parent)
            changed_script = command.copy(); changed_script[2] = str(root / "invented-runner.py")
            before = snapshot(root)
            for invalid in [tuple(command), ["/bin/sh", "-c", "invented"], command + ["--allow-local-inference"],
                            changed_backend, changed_source, changed_script]:
                self.refused(manager._launch, invalid)
            self.assertEqual(before, snapshot(root))
            spawn.assert_not_called()

    def test_foreign_runtime_records_are_rejected_before_process_reconciliation(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            write_new(root / "workspace/data/jobs" / ("f" * 16 + ".json"), canonical({"id": "f" * 16,
                      "state": "RUNNING", "pid": 99999999, "backend": "ollama", "private_extra": "invented private sentinel"}))
            before = snapshot(root)
            with patch("workbench.process_stamp", side_effect=AssertionError("foreign runtime process was probed")):
                self.refused(validate_fixture, root)
                self.refused(WorkflowManager, root)
            self.assertEqual(before, snapshot(root))
            spawn.assert_not_called()

    def test_incomplete_or_partial_start_claim_is_retained_and_not_repaired(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            path = root / "receipts/start-claim.json"
            write_new(path, b'{"version":')
            before = snapshot(root)
            self.refused(manager.start, start_request(manager))
            self.refused(python_report, root)
            self.assertEqual(before, snapshot(root))
            spawn.assert_not_called()

    def test_normal_http_history_calls_real_base_feed_and_lists_fresh_empty_history(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request = memory_http(manager)
            original = BaseManager.history
            before = snapshot(root)
            with patch.object(BaseManager, "history", autospec=True, side_effect=original) as feed:
                status, history = request("/api/history", method="GET")
                self.assertEqual((status, history), (200, []))
                self.assertGreaterEqual(feed.call_count, 1)
            self.assertGreater(manager.counters["history_requests"], 0)
            self.assertEqual(before, snapshot(root))
            self.assertEqual(manager.counters["parent_provider_attempts"], 0)
            self.assertEqual(manager.counters["parent_outbound_attempts"], 0)
            spawn.assert_not_called()

    def test_http_session_and_host_origin_guards_precede_start_and_no_token_is_logged(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request = memory_http(manager)
            with patch.object(manager, "start", side_effect=AssertionError("invalid session reached start")) as start:
                for headers in [{"Host": "untrusted.invalid"}, {"Origin": "https://untrusted.invalid"},
                                {"X-Workbench-Token": ""}, {"Sec-Fetch-Site": "cross-site"}]:
                    before = snapshot(root)
                    status, value = request("/api/start", start_request(manager), headers)
                    self.assertIn(status, [403, 409])
                    self.assertIsInstance(value.get("error"), str)
                    self.assertNotIn("invented-workflow-token", json.dumps(value))
                    self.assertEqual(before, snapshot(root))
                start.assert_not_called()
            spawn.assert_not_called()

    def test_http_strict_json_framing_duplicate_headers_and_short_body_refuse(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request = memory_http(manager)
            value = start_request(manager)
            for route, method in [("/api/start", "start"), ("/api/review", "review")]:
                with patch.object(manager, method, side_effect=AssertionError("bad framing reached " + method)) as action:
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                        {"Content-Length": "32769"}, {"Content-Length": "9999"}, {"Content-Type": "application/zip"},
                        [("Content-Length", str(len(canonical(value))))], [("Content-Type", "application/json")]]:
                        before = snapshot(root)
                        status, result = request(route, value, headers)
                        self.assertIn(status, [400, 403, 409])
                        self.assertIsInstance(result.get("error"), str)
                        self.assertEqual(before, snapshot(root))
                    for raw in [b'{"project":"x","project":"y"}', b"\xff", b'{"project":']:
                        before = snapshot(root)
                        status, result = request(route, {}, raw=raw)
                        self.assertIn(status, [400, 403, 409])
                        self.assertIsInstance(result.get("error"), str)
                        self.assertEqual(before, snapshot(root))
                    action.assert_not_called()
            spawn.assert_not_called()

    def test_counter_shapes_are_finite_and_do_not_accept_bool_or_unknown_keys(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            counters = new_counters()
            self.assertTrue(counters and all(type(value) is int and value == 0 for value in counters.values()))
            for invalid in [{"unknown": 0}, {"worker_launches": True}, {"parent_provider_attempts": -1}]:
                self.refused(offline_handler, manager, "invented-token", "http://127.0.0.1:8765", invalid)
            spawn.assert_not_called()

    def test_http_route_allowlist_blocks_source_workspace_and_unowned_run_actions(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request = memory_http(manager)
            before = snapshot(root)
            for path in ["/api/project-preview", "/api/project-save", "/api/project-refresh-preview", "/api/bundle-workspace-create",
                         "/api/snapshot-workspace-create", "/api/snapshot-editor-save"]:
                status, value = request(path, {})
                self.assertIn(status, [403, 404, 409])
                self.assertIsInstance(value.get("error"), str)
            for path in ["/api/run/" + "f" * 16, "/api/export/" + "f" * 16]:
                status, value = request(path, method="GET")
                self.assertIn(status, [403, 404, 409])
                self.assertIsInstance(value.get("error"), str)
            self.assertEqual(before, snapshot(root))
            self.assertGreater(manager.counters["denied_requests"], 0)
            spawn.assert_not_called()

    def test_old_session_token_cannot_authenticate_a_new_handler(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request = memory_http(manager, token="invented-new-session-token")
            status, value = request("/api/history", headers={"X-Workbench-Token": "invented-old-session-token"}, method="GET")
            self.assertIn(status, [403, 409])
            self.assertIsInstance(value.get("error"), str)
            spawn.assert_not_called()

    def test_report_and_unstarted_runtime_refuse_without_manager_or_process_calls(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            before = snapshot(root)
            with patch("offline_workflow.WorkflowManager", side_effect=AssertionError("verifier instantiated runtime")), patch(
                    "workbench.process_stamp", side_effect=AssertionError("verifier probed process")):
                self.refused(python_report, root)
                self.refused(python_report, root, patch_raw=b"Invented unmatched patch", require_accepted=True)
            self.assertEqual(before, snapshot(root))
            spawn.assert_not_called()

    def test_fake_session_shapes_support_pinned_review_exact_export_and_read_only_report(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            identifier, result = seed_completed(manager)
            request = memory_http(manager)
            status, history = request("/api/history", method="GET")
            self.assertEqual((status, history[0]["id"]), (200, identifier))
            status, view = request("/api/run/" + identifier, method="GET")
            self.assertEqual((status, view["turns"]), (200, 6))
            self.assertEqual(view["plan"], ["Read the fixture", "Correct addition", "Run the fixed tests"])
            before = snapshot(root)
            status, refused_export = request("/api/export/" + identifier, method="GET")
            self.assertEqual((status, refused_export["error"]), (409, "REVIEW_REQUIRED"))
            self.assertEqual(before, snapshot(root))
            review = {"id": identifier, "result_sha256": view["result_sha256"], "patch_sha256": view["patch_sha256"],
                      "verdict": "accepted", "note": "Unit-only invented acceptance, not actual execution."}
            status, accepted = request("/api/review", review)
            self.assertEqual(status, 200); self.assertIs(accepted["source_applied"], False)
            status, exported = request("/api/export/" + identifier, method="GET")
            self.assertEqual(status, 200)
            self.assertEqual(sha(exported), result["patch_sha256"])
            before_report = snapshot(root)
            with patch("offline_workflow.WorkflowManager", side_effect=AssertionError("report instantiated runtime")), patch(
                    "workbench.process_stamp", side_effect=AssertionError("report probed process")):
                report = python_report(root, exported, True)
                self.refused(python_report, root, exported + b"invented drift", True)
            self.assertTrue(report["accepted"] and report["download_verified"])
            self.assertEqual(before_report, snapshot(root))
            spawn.assert_not_called()

    def test_stale_review_pins_and_candidate_result_event_drift_refuse_without_repair(self):
        for kind in ["review-pin", "candidate", "result", "event", "accepted-record"]:
            with self.subTest(kind=kind), workflow_fixture() as (root, manager, marker, spawn):
                identifier, _ = seed_completed(manager)
                view = manager.view(identifier)
                run = root / "workspace/data/runs" / identifier
                if kind == "review-pin":
                    before = snapshot(root)
                    with self.assertRaises(Refused):
                        manager.review({"id": identifier, "result_sha256": "0" * 64, "patch_sha256": view["patch_sha256"],
                                        "verdict": "accepted", "note": "Invented stale pin."})
                    self.assertEqual(before, snapshot(root))
                else:
                    if kind == "candidate": (run / "work/calculator.py").write_bytes(b"invented unexpected candidate\n")
                    elif kind == "result":
                        path = run / "result.json"; result = json.loads(path.read_bytes()); result["ai_inference"] = True
                        path.write_bytes(canonical(result))
                    elif kind == "event": next(run.glob("event-*.json")).write_bytes(b"{}")
                    else:
                        write_new(run / "review-000.json", canonical({"id": identifier, "result_sha256": view["result_sha256"],
                                  "patch_sha256": view["patch_sha256"], "verdict": "accepted", "note": "Invented invalid adoption flag.",
                                  "recorded": 1, "source_applied": True}))
                    before = snapshot(root)
                    with patch("workbench.process_stamp", side_effect=AssertionError("verifier probed process")):
                        self.refused(python_report, root, require_accepted=kind == "accepted-record")
                    self.assertEqual(before, snapshot(root))
                spawn.assert_not_called()

    def test_terminal_restart_keeps_fake_evidence_without_worker_or_process_recovery(self):
        with tempfile.TemporaryDirectory() as directory, patch("offline_workflow.REAL_POPEN", side_effect=AssertionError(
                "terminal restart launched a real child")) as spawn:
            root = Path(directory) / "workflow"
            initialize(root); manager = WorkflowManager(root)
            try:
                identifier, _ = seed_completed(manager)
                history = manager.history(); report = python_report(root)
                manager.close(); manager = None
                before = snapshot(root)
                with patch("workbench.process_stamp", side_effect=AssertionError("terminal restart probed process")):
                    manager = WorkflowManager(root)
                    self.assertEqual(manager.history(), history)
                    self.assertEqual(python_report(root), report)
                    self.refused(manager.start, start_request(manager))
                self.assertEqual(before, snapshot(root))
                self.assertEqual(manager.counters["worker_launches"], 0)
                self.assertEqual(manager.history()[0]["id"], identifier)
                spawn.assert_not_called()
            finally:
                if manager is not None: manager.close()


if __name__ == "__main__":
    unittest.main()
