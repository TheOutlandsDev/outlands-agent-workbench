"""Restricted completed-workflow composition, using unit-only invented evidence.

Session tool/event shapes use fake checks. Worker/Java receipts and prior-report
claims below are fabricated test inputs, never actual execution qualification.
No child, compiler, check, provider or network connection is launched here.
"""

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from offline_workflow import WorkflowManager, initialize, new_counters, python_report
from qa_complete_review_workflow import (
    GUARD_KEYS, READ_COUNTERS, ZERO_COUNTERS, acceptance, inspect_completed, load_dependency, zero_execution,
)
from test_offline_workflow_integration import memory_http, seed_completed, snapshot
from test_run_history_integration import history_request, open_request
from test_saved_review_history_integration import history_pins, saved_history_guard
from test_saved_run_review_integration import review_guard
from workbench import Manager


UNIT_NOTE = "Unit-only fabricated decision — café e\u0301 🧪\x00\r\n<b>literal</b>"


def seed_dependency(work, manager):
    """Fabricate earlier-stage inputs after fake_check; not actual QA evidence."""
    root = manager.root
    identifier, _ = seed_completed(manager)
    view = manager.view(identifier)
    manager.review({"id": identifier, "result_sha256": view["result_sha256"],
                    "patch_sha256": view["patch_sha256"], "verdict": "accepted", "note": UNIT_NOTE})
    exported = manager.export(identifier)
    write_new(work / "offline-workflow-export.patch", exported)
    java = root / "java"; java.mkdir(mode=0o700)
    write_new(java / "claim.json", canonical({"version": 1, "fixture_id": manager.marker["fixture_id"], "attempt": 1}))
    java_raw = canonical({"version": 1, "java_agent_run": False, "model_inference": False,
        "checks": {"unit": {"exit_code": 0, "tests_ran": 1, "timed_out": False,
                            "output_limited": False, "infrastructure_error": False}}})
    write_new(java / "result.json", java_raw)
    report = python_report(root, exported, True)
    previous, restarted = new_counters(), new_counters()
    previous.update(worker_launches=1, start_attempts=1)
    prior = {"run_id": identifier, "initial_metadata_state": "RUNNING", "normal_history_states": ["REVIEW_READY"],
        "scripted_python_agent_run": True, "java_agent_run": False, "real_model_qualified": False,
        "normal_history_feed_stubbed": False, "source_config_task_and_protected_bytes_modes_unchanged": True,
        "terminal_runtime_evidence_unchanged_after_restart": True, "python_report": report,
        "terminal_restart_report": report, "parent_counters": previous, "restarted_parent_counters": restarted,
        "worker_guard_receipt": json.loads((root / "receipts/worker-exit.json").read_bytes()),
        "baseline_tests": 4, "final_tests": 4,
        "separate_java_checks": {"version": 1, "status": "PASS", "java_agent_run": False,
            "model_inference": False, "protected_mains": 1, "sources_unchanged": True,
            "receipt_sha256": sha(java_raw)}, "export_sha256": sha(exported),
        "unit_only_fabricated_dependency": True}
    write_new(work / "offline-workflow-acceptance.json", canonical(prior))
    return identifier


@contextmanager
def unit_dependency():
    with tempfile.TemporaryDirectory() as directory, patch("offline_workflow.REAL_POPEN", side_effect=AssertionError(
            "unit-only complete review attempted a real worker")) as spawn:
        work = Path(directory)
        root = work / "offline-workflow"
        initialize(root); manager = WorkflowManager(root)
        try:
            identifier = seed_dependency(work, manager)
            yield work, root, manager, identifier, spawn
        finally:
            manager.close()


def review_request(manager, identifier):
    request = memory_http(manager)
    status, searched = request("/api/run-history-search", history_request(identifier))
    assert status == 200
    pins = open_request(searched)
    with review_guard(manager):
        status, reviewed = request("/api/run-history-review", pins)
    assert status == 200
    return request, reviewed


class CompleteReviewWorkflowIntegrationTests(unittest.TestCase):
    def test_missing_dependency_refuses_without_creation_manager_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            with patch("qa_complete_review_workflow.WorkflowManager", side_effect=AssertionError("missing dependency created Manager")):
                with self.assertRaisesRegex(Refused, "^COMPLETE_REVIEW_DEPENDENCY$"):
                    acceptance(None, work)
            self.assertEqual(list(work.iterdir()), [])

    def test_unit_only_dependency_is_bound_to_exact_prior_bytes_export_and_java_receipt(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            before = snapshot(work)
            with zero_execution() as calls:
                dependency = load_dependency(work)
            self.assertEqual(dependency["root"], root)
            self.assertEqual(dependency["prior"]["run_id"], identifier)
            self.assertTrue(dependency["prior"]["unit_only_fabricated_dependency"])
            self.assertEqual(dependency["prior_sha256"], sha((work / "offline-workflow-acceptance.json").read_bytes()))
            self.assertEqual(dependency["export_sha256"], sha((work / "offline-workflow-export.patch").read_bytes()))
            self.assertEqual(dependency["java_receipt_sha256"], sha((root / "java/result.json").read_bytes()))
            self.assertFalse(any(calls.values()))
            self.assertEqual(snapshot(work), before); spawn.assert_not_called()

    def test_malformed_or_incomplete_prior_claims_refuse_without_repair(self):
        for kind in ["malformed", "list", "missing-accepted", "model", "feed", "worker-count", "java-count", "counter-bool", "worker-receipt", "duplicate", "too-large"]:
            with self.subTest(kind=kind), unit_dependency() as (work, root, manager, identifier, spawn):
                path = work / "offline-workflow-acceptance.json"
                value = json.loads(path.read_bytes())
                if kind == "malformed": raw = b'{"run_id":'
                elif kind == "list": raw = b"[]"
                elif kind == "duplicate": raw = b'{"run_id":"x","run_id":"y"}'
                elif kind == "too-large": raw = b" " * 65537
                else:
                    if kind == "missing-accepted": value["python_report"]["accepted"] = False
                    elif kind == "model": value["real_model_qualified"] = True
                    elif kind == "feed": value["normal_history_feed_stubbed"] = True
                    elif kind == "worker-count": value["parent_counters"]["worker_launches"] = 2
                    elif kind == "counter-bool": value["restarted_parent_counters"]["worker_launches"] = False
                    elif kind == "worker-receipt": value["worker_guard_receipt"]["provider_attempts"] = 1
                    else: value["separate_java_checks"]["protected_mains"] = 2
                    raw = canonical(value)
                path.write_bytes(raw); before = snapshot(work)
                with zero_execution(), patch("qa_complete_review_workflow.WorkflowManager", side_effect=AssertionError("bad dependency created Manager")):
                    with self.assertRaisesRegex(Refused, "^COMPLETE_REVIEW_DEPENDENCY$"):
                        acceptance(None, work)
                self.assertEqual(snapshot(work), before); spawn.assert_not_called()

    def test_private_prior_receipt_modes_and_links_are_required(self):
        for kind in ["mode", "hardlink", "symlink"]:
            with self.subTest(kind=kind), unit_dependency() as (work, root, manager, identifier, spawn):
                path = work / "offline-workflow-acceptance.json"
                if kind == "mode": path.chmod(0o640)
                elif kind == "hardlink": os.link(path, work / "unit-prior-hardlink.json")
                else:
                    renamed = work / "unit-prior-original.json"; path.rename(renamed); path.symlink_to(renamed)
                before = snapshot(work)
                with self.assertRaisesRegex(Refused, "^COMPLETE_REVIEW_DEPENDENCY$"):
                    load_dependency(work)
                self.assertEqual(snapshot(work), before); spawn.assert_not_called()

    def test_foreign_source_launch_and_incomplete_terminal_are_not_adopted(self):
        for kind in ["source-bound-argv", "terminal", "partial-claim", "foreign-root"]:
            with self.subTest(kind=kind), unit_dependency() as (work, root, manager, identifier, spawn):
                if kind == "source-bound-argv":
                    path = root / "receipts/launch.json"; value = json.loads(path.read_bytes())
                    value["argv"][2] = "/invented-other-version/agent.py"; path.write_bytes(canonical(value))
                elif kind == "terminal": (root / "receipts/terminal.json").unlink()
                elif kind == "partial-claim": (root / "receipts/start-claim.json").write_bytes(b'{"version":')
                else:
                    path = root / "fixture.json"; value = json.loads(path.read_bytes())
                    value["work_dir"] = str(work / "invented-other-root"); path.write_bytes(canonical(value))
                before = snapshot(work)
                with zero_execution(), patch("qa_complete_review_workflow.WorkflowManager", side_effect=AssertionError("foreign dependency adopted Manager")):
                    with self.assertRaisesRegex(Refused, "^COMPLETE_REVIEW_DEPENDENCY$"):
                        acceptance(None, work)
                self.assertEqual(snapshot(work), before); spawn.assert_not_called()

    def test_changed_earlier_export_java_result_and_selected_source_refuse_without_rerun(self):
        for kind in ["export", "java-result", "selected-source"]:
            with self.subTest(kind=kind), unit_dependency() as (work, root, manager, identifier, spawn):
                if kind == "export":
                    path = work / "offline-workflow-export.patch"; path.write_bytes(path.read_bytes() + b"\n")
                elif kind == "java-result":
                    path = root / "java/result.json"; value = json.loads(path.read_bytes())
                    value["checks"]["unit"]["exit_code"] = 1; path.write_bytes(canonical(value))
                else:
                    path = root / "workspace/project/calculator.py"; path.write_bytes(path.read_bytes() + b"# unit-only drift\n")
                before = snapshot(work)
                with zero_execution() as calls:
                    with self.assertRaisesRegex(Refused, "^COMPLETE_REVIEW_DEPENDENCY$"):
                        load_dependency(work)
                self.assertFalse(any(calls.values())); self.assertEqual(snapshot(work), before); spawn.assert_not_called()

    def test_guard_intercepts_check_aliases_and_provider_without_executing_them(self):
        with zero_execution() as calls:
            import agent
            import offline_workflow
            for operation in [lambda: offline_workflow.fixed_checks(None, None, None),
                              lambda: offline_workflow.java_checks(None, None),
                              lambda: agent.Ollama.request(None, [], 1)]:
                with self.assertRaisesRegex(AssertionError, "^complete review reached (checks|provider)$"):
                    operation()
        self.assertEqual(calls["checks"], 2); self.assertEqual(calls["provider"], 1)
        self.assertTrue(all(count == 0 for key, count in calls.items() if key not in {"checks", "provider"}))

    def test_completed_real_base_feed_and_view_compose_with_guarded_saved_routes(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            dependency = load_dependency(work); before = snapshot(root)
            original_history, original_view = Manager.history, Manager.view
            with zero_execution() as calls, patch.object(Manager, "history", autospec=True, side_effect=original_history) as feed, patch.object(
                    Manager, "view", autospec=True, side_effect=original_view) as view:
                observed = inspect_completed(manager, dependency)
            # The real run view also asks unchanged admission() for history.
            self.assertEqual(feed.call_count, 2); self.assertEqual(view.call_count, 1)
            self.assertEqual(feed.call_args_list[0].args, (manager,))
            self.assertEqual(feed.call_args_list[1].kwargs, {"limit": None})
            self.assertFalse(observed["normal_feed_stubbed"])
            self.assertEqual(observed["normal_run_id"], identifier)
            self.assertEqual(observed["detail"]["history"]["entry"]["note"], UNIT_NOTE)
            self.assertEqual(observed["saved_review"]["decision"]["state"], "ACCEPTED")
            self.assertEqual(observed["history"]["history"]["current"], observed["saved_review"]["decision"]["current"])
            self.assertEqual({k: manager.counters[k] for k in READ_COUNTERS}, READ_COUNTERS)
            self.assertTrue(all(manager.counters[k] == 0 for k in ZERO_COUNTERS))
            self.assertFalse(any(calls.values())); self.assertEqual(snapshot(root), before); spawn.assert_not_called()

    def test_restart_preserves_exact_views_counters_and_new_session_authentication(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            dependency = load_dependency(work); before = snapshot(root)
            with zero_execution():
                first = inspect_completed(manager, dependency, token="invented-first-token")
                manager.close()
                restarted = WorkflowManager(root)
                try:
                    request = memory_http(restarted, token="invented-restarted-token")
                    status, denied = request("/api/history", headers={"X-Workbench-Token": "invented-first-token"}, method="GET")
                    self.assertEqual(status, 403); self.assertEqual(denied["error"], "SESSION_REQUIRED")
                    # Rejected requests are counted before auth, so use another
                    # untouched handler/counter set for exact positive counts.
                    restarted.counters = new_counters()
                    second = inspect_completed(restarted, dependency, token="invented-restarted-token")
                    self.assertEqual(first, second)
                finally: restarted.close()
            self.assertEqual(snapshot(root), before); spawn.assert_not_called()

    def test_stale_four_and_five_pins_refuse_without_writer_or_fallback(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            request, reviewed = review_request(manager, identifier)
            for route, name in [("/api/saved-review-history", None), ("/api/saved-review-history-entry", "review-000.json")]:
                for field in ["record_sha256", "history_sha256", "evidence_sha256"]:
                    value = history_pins(reviewed, name); value[field] = "0" * 64; before = snapshot(root)
                    with zero_execution(), saved_history_guard(manager):
                        status, denied = request(route, value)
                    self.assertEqual(status, 409); self.assertRegex(denied["error"], r"^SAVED_REVIEW_[A-Z_]+$")
                    self.assertEqual(snapshot(root), before)
            with saved_history_guard(manager):
                status, denied = request("/api/saved-review-history-entry", history_pins(reviewed, "review-001.json"))
            self.assertEqual((status, denied["error"]), (409, "SAVED_REVIEW_NOT_FOUND")); spawn.assert_not_called()

    def test_additive_receipt_drift_refuses_old_context_and_never_repairs_evidence(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            request, reviewed = review_request(manager, identifier)
            write_new(root / "workspace/data/runs" / identifier / "review-001.json", b"{}")
            before = snapshot(root)
            with zero_execution(), saved_history_guard(manager):
                status, denied = request("/api/saved-review-history-entry", history_pins(reviewed, "review-000.json"))
            self.assertEqual((status, denied["error"]), (409, "SAVED_REVIEW_EVIDENCE_CHANGED"))
            self.assertEqual(snapshot(root), before); spawn.assert_not_called()

    def test_restricted_saved_route_auth_and_framing_precede_manager_action(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            request, reviewed = review_request(manager, identifier)
            for route, method, name in [("/api/saved-review-history", "saved_review_history", None),
                                        ("/api/saved-review-history-entry", "saved_review_history_entry", "review-000.json")]:
                value = history_pins(reviewed, name)
                for headers in [{"Host": "untrusted.invalid"}, {"Origin": "https://untrusted.invalid"}, {"X-Workbench-Token": ""},
                                {"Content-Length": "32769"}, {"Content-Length": "9999"}, {"Transfer-Encoding": "chunked"},
                                [("Content-Type", "application/json")], [("Content-Length", str(len(canonical(value))))]]:
                    before = snapshot(root)
                    with patch.object(manager, method, side_effect=AssertionError("invalid HTTP reached saved reader")) as action:
                        status, denied = request(route, value, headers=headers)
                        action.assert_not_called()
                    self.assertIn(status, [403, 409]); self.assertIsInstance(denied["error"], str)
                    self.assertEqual(snapshot(root), before)
            spawn.assert_not_called()

    def test_unit_only_dependent_acceptance_preserves_fixture_and_has_no_extra_execution(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            manager.close(); before = snapshot(root)
            result = acceptance(None, work)
            receipt = json.loads((work / "complete-review-workflow-acceptance.json").read_bytes())
            self.assertEqual(receipt["first"], receipt["restarted"])
            self.assertEqual(receipt["run_id"], identifier)
            self.assertEqual(receipt["earlier_actual_acceptance_sha256"], sha((work / "offline-workflow-acceptance.json").read_bytes()))
            self.assertFalse(any(receipt["guard_attempts"].values()))
            self.assertEqual(set(receipt["guard_attempts"]), set(GUARD_KEYS))
            self.assertEqual(receipt["new_workers"], receipt["new_checks"])
            self.assertEqual(receipt["new_workers"], 0)
            self.assertFalse(receipt["normal_history_feed_stubbed"])
            self.assertFalse(receipt["browser_observed_running_transition"])
            self.assertTrue(result["complete_review_workflow_whole_fixture_preserved"])
            self.assertEqual((work / "complete-review-workflow-acceptance.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(snapshot(root), before); spawn.assert_not_called()
            original = (work / "complete-review-workflow-acceptance.json").read_bytes()
            with self.assertRaises(FileExistsError): acceptance(None, work)
            self.assertEqual((work / "complete-review-workflow-acceptance.json").read_bytes(), original)
            self.assertEqual(snapshot(root), before)

    def test_changed_prior_report_after_inspection_refuses_before_new_receipt(self):
        with unit_dependency() as (work, root, manager, identifier, spawn):
            manager.close(); original = inspect_completed; count = 0
            def observed(*args, **kwargs):
                nonlocal count
                value = original(*args, **kwargs); count += 1
                if count == 2:
                    path = work / "offline-workflow-acceptance.json"
                    path.write_bytes(path.read_bytes() + b"\n")
                return value
            with patch("qa_complete_review_workflow.inspect_completed", side_effect=observed):
                with self.assertRaises(AssertionError): acceptance(None, work)
            self.assertEqual(count, 2)
            self.assertFalse((work / "complete-review-workflow-acceptance.json").exists()); spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
