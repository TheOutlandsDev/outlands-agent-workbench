"""Synthetic lifecycle controller/QA regressions; no child or check is run.

Receipt examples in this file are deliberate unit data, never native worker
evidence. Actual lifecycle acceptance belongs to the fresh final-runner roots.
"""

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, write_new
from offline_lifecycle import LifecycleManager, initialize, lifecycle_report
from offline_workflow import new_counters
from qa_failed_stopped_workflow import (
    GUARD_KEYS, acceptance, execution_guards, inspect_terminal, refuse_insufficient_review_export, verified_report,
)
from test_offline_workflow_integration import memory_http, snapshot, start_request
from test_run_history_integration import history_request, open_request
from test_saved_review_history_integration import history_pins, saved_history_guard
from test_saved_run_review_integration import review_guard
from workbench import Manager


def synthetic_report(scenario):
    return {"version": 1, "scenario": scenario, "fixture_id": "1" * 32, "run_id": "2" * 16,
        "status": "VERIFIED", "outcome": "CONTROLLED_FAILURE" if scenario == "fail" else "OWNED_STOP",
        "metadata_state": "FAILED", "exit_code": 23 if scenario == "fail" else 130,
        "signal": None if scenario == "fail" else 15, "guard_attempts": {"provider": 0, "checks": 0, "network": 0},
        "source_unchanged": True, "original_inputs_unchanged": True, "run_directory_present": False,
        "agent_executed": False, "notes": []}


@contextmanager
def failed_controller_fixture(scenario="fail"):
    """Real controllers with a mocked Popen/current PID, never a real child.

    The deliberately absent worker/armed/exit receipts MUST remain UNKNOWN;
    these controller tests do not manufacture a verified worker chain.
    """
    class FakeChild:
        pid = os.getpid()
        returncode = None
        def poll(self): return self.returncode
        def terminate(self): self.returncode = 130
        def kill(self): self.returncode = 137
        def wait(self, timeout=None):
            if self.returncode is None: raise AssertionError("unit child was not settled")
            return self.returncode
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "lifecycle"
        initialize(root, scenario)
        manager, child = LifecycleManager(root), FakeChild()
        try:
            with patch("offline_lifecycle.REAL_POPEN", return_value=child) as spawn, patch(
                    "workbench.process_stamp", return_value="invented-unit-process-stamp"):
                request = memory_http(manager)
                status, started = request("/api/start", start_request(manager))
                assert status == 200
                identifier = started["id"]
                child.returncode = 23
                status, normal = request("/api/history", method="GET")
                assert status == 200 and normal[0]["state"] == "FAILED"
            yield root, manager, identifier, spawn
        finally:
            # Only the fake object is settled here; native QA never rewrites a
            # process return code or repairs a failed/partial fixture.
            child.returncode = 23
            manager.close()


def saved_context(manager, identifier):
    request = memory_http(manager)
    status, searched = request("/api/run-history-search", history_request(identifier))
    assert status == 200
    with review_guard(manager):
        status, reviewed = request("/api/run-history-review", open_request(searched))
    assert status == 200
    return request, reviewed


class FailedStoppedWorkflowIntegrationTests(unittest.TestCase):
    def test_synthetic_report_validation_keeps_failed_state_and_distinct_control_outcomes(self):
        for scenario in ["fail", "stop"]:
            report = synthetic_report(scenario)
            with patch("qa_failed_stopped_workflow.lifecycle_report", return_value=report):
                self.assertEqual(verified_report(None, scenario), report)
            self.assertEqual(report["metadata_state"], "FAILED")
            self.assertFalse(report["agent_executed"])

    def test_missing_unknown_or_inconsistent_receipts_never_pass_qa_by_metadata_alone(self):
        for updates in [{"status": "UNKNOWN"}, {"outcome": "UNKNOWN"}, {"metadata_state": "INTERRUPTED"},
                        {"exit_code": 0}, {"signal": None}, {"run_directory_present": True},
                        {"agent_executed": None}, {"source_unchanged": False}, {"original_inputs_unchanged": False},
                        {"notes": ["MISSING_RECEIPT"]}, {"extra": True}]:
            with self.subTest(updates=updates):
                report = {**synthetic_report("stop"), **updates}
                with patch("qa_failed_stopped_workflow.lifecycle_report", return_value=report):
                    with self.assertRaises(AssertionError): verified_report(None, "stop")

    def test_guard_counts_are_strict_zero_integers_not_bool_or_missing_defaults(self):
        for value in [{"provider": False, "checks": 0, "network": 0}, {"provider": 0, "checks": 1, "network": 0},
                      {"provider": 0, "network": 0}, {"provider": 0, "checks": 0, "network": None}]:
            report = synthetic_report("fail"); report["guard_attempts"] = value
            with patch("qa_failed_stopped_workflow.lifecycle_report", return_value=report):
                with self.assertRaises(AssertionError): verified_report(None, "fail")

    def test_readonly_guard_blocks_spawn_check_provider_and_writer_before_any_execution(self):
        import agent
        import offline_lifecycle
        import offline_workflow
        from workbench import Manager
        with execution_guards(read_only=True) as counts:
            for operation in [lambda: offline_lifecycle.REAL_POPEN(["/invented-must-not-execute"]),
                              lambda: offline_workflow.fixed_checks(None, None, None),
                              lambda: agent.Ollama.request(None, [], 1),
                              lambda: Manager.review(None, {}), lambda: Manager.export(None, "2" * 16)]:
                with self.assertRaisesRegex(AssertionError, "^lifecycle QA reached "):
                    operation()
        self.assertEqual(set(counts), set(GUARD_KEYS))
        self.assertEqual({key: value for key, value in counts.items() if value},
                         {"worker": 1, "checks": 1, "provider": 1, "review": 1, "export": 1})

    def test_real_normal_failed_feed_and_view_are_not_replaced_by_synthetic_results(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            original_history, original_view = Manager.history, Manager.view
            before = snapshot(root)
            with execution_guards(read_only=True), patch.object(Manager, "history", autospec=True, side_effect=original_history) as history, patch.object(
                    Manager, "view", autospec=True, side_effect=original_view) as view:
                observed = inspect_terminal(manager, {"run_id": identifier}, "invented-failed-read-token")
            self.assertEqual(observed["normal_state"], "FAILED")
            self.assertEqual(history.call_count, 2)  # GET run also reads admission history.
            self.assertEqual(view.call_count, 1)
            self.assertEqual(before, snapshot(root)); self.assertEqual(spawn.call_count, 1)
            self.assertFalse(manager.run_path(identifier).exists())

    def test_missing_worker_receipts_remain_unknown_even_when_metadata_is_failed(self):
        for scenario in ["fail", "stop"]:
            with self.subTest(scenario=scenario), failed_controller_fixture(scenario) as (root, manager, identifier, spawn):
                before = snapshot(root)
                report = lifecycle_report(root)
                self.assertEqual(report["status"], "UNKNOWN"); self.assertEqual(report["outcome"], "UNKNOWN")
                self.assertEqual(report["metadata_state"], "FAILED")
                self.assertIsNone(report["agent_executed"])
                self.assertTrue(all(value is None for value in report["guard_attempts"].values()))
                with self.assertRaises(AssertionError): verified_report(root, scenario)
                self.assertEqual(snapshot(root), before); self.assertEqual(spawn.call_count, 1)

    def test_saved_failed_task_and_empty_incomplete_receipt_catalog_are_honest(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            before = snapshot(root)
            with execution_guards(read_only=True):
                observed = inspect_terminal(manager, {"run_id": identifier}, "invented-missing-catalog-token")
            decision = observed["saved_review"]["decision"]
            self.assertEqual(decision["state"], "UNKNOWN"); self.assertFalse(decision["catalog_complete"])
            self.assertEqual(decision["inspected"], 0); self.assertIsNone(decision["receipt"])
            self.assertEqual(observed["history"]["history"]["entries"], [])
            self.assertEqual(observed["selected_detail_refusal"], {"error": "SAVED_REVIEW_NOT_FOUND"})
            self.assertEqual(snapshot(root), before); self.assertFalse(manager.run_path(identifier).exists())

    def test_review_export_negative_requests_are_distinct_from_writes_or_outputs(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            before = snapshot(root)
            with execution_guards():
                refusals = refuse_insufficient_review_export(manager, identifier)
            self.assertEqual(refusals["review_request_refusal"], "TASK_NOT_REVIEW_READY")
            self.assertEqual(refusals["export_request_refusal"], "REVIEW_REQUIRED")
            self.assertEqual(manager.counters["review_requests"], 1)
            self.assertEqual(manager.counters["export_requests"], 1)
            self.assertEqual(refusals["review_writes"], refusals["export_outputs"])
            self.assertEqual(refusals["review_writes"], 0); self.assertEqual(snapshot(root), before)

    def test_readonly_restart_preserves_exact_views_and_clears_session_authority(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            with execution_guards(read_only=True):
                first = inspect_terminal(manager, {"run_id": identifier}, "invented-first-failed-token")
            manager.close(); before = snapshot(root)
            with execution_guards(read_only=True) as guards:
                restarted = LifecycleManager(root)
                try:
                    request = memory_http(restarted, token="invented-second-failed-token")
                    status, denied = request("/api/history", headers={"X-Workbench-Token": "invented-first-failed-token"}, method="GET")
                    self.assertEqual((status, denied["error"]), (403, "SESSION_REQUIRED"))
                    restarted.counters = new_counters()
                    second = inspect_terminal(restarted, {"run_id": identifier}, "invented-second-failed-token")
                    self.assertEqual(first, second)
                    self.assertEqual(restarted.counters["worker_launches"], 0)
                    self.assertEqual(restarted.counters["review_requests"], restarted.counters["export_requests"])
                    self.assertEqual(restarted.counters["review_requests"], 0)
                finally: restarted.close()
                self.assertFalse(any(guards.values()))
            self.assertEqual(snapshot(root), before); self.assertEqual(spawn.call_count, 1)

    def test_stale_saved_pins_refuse_without_creating_result_review_or_cache(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            request, reviewed = saved_context(manager, identifier)
            for route, name in [("/api/saved-review-history", None), ("/api/saved-review-history-entry", "review-000.json")]:
                for key in ["record_sha256", "history_sha256", "evidence_sha256"]:
                    value = history_pins(reviewed, name); value[key] = "0" * 64
                    before = snapshot(root)
                    with execution_guards(read_only=True), saved_history_guard(manager):
                        status, denied = request(route, value)
                    self.assertEqual(status, 409); self.assertRegex(denied["error"], r"^SAVED_REVIEW_[A-Z_]+$")
                    self.assertEqual(snapshot(root), before)
            self.assertFalse(manager.run_path(identifier).exists())

    def test_metadata_drift_invalidates_selected_context_without_repair(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            request, reviewed = saved_context(manager, identifier)
            path = manager.meta_path(identifier); value = json.loads(path.read_bytes())
            value["goal"] += " unit-only drift"; path.write_bytes(canonical(value)); before = snapshot(root)
            with saved_history_guard(manager):
                status, denied = request("/api/saved-review-history", history_pins(reviewed))
            self.assertEqual(status, 409); self.assertIn(denied["error"], ["SAVED_REVIEW_HISTORY_CHANGED", "SAVED_REVIEW_RECORD_CHANGED"])
            self.assertEqual(snapshot(root), before)

    def test_failed_saved_http_authentication_and_framing_precede_reader(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            request, reviewed = saved_context(manager, identifier)
            for route, method, name in [("/api/saved-review-history", "saved_review_history", None),
                                        ("/api/saved-review-history-entry", "saved_review_history_entry", "review-000.json")]:
                value = history_pins(reviewed, name)
                for headers in [{"Host": "untrusted.invalid"}, {"Origin": "https://untrusted.invalid"}, {"X-Workbench-Token": ""},
                                {"Content-Length": "32769"}, {"Content-Length": "9999"}, {"Transfer-Encoding": "chunked"},
                                [("Content-Type", "application/json")], [("Content-Length", str(len(canonical(value))))]]:
                    before = snapshot(root)
                    with patch.object(manager, method, side_effect=AssertionError("bad framing reached reader")) as reader:
                        status, denied = request(route, value, headers=headers)
                        reader.assert_not_called()
                    self.assertIn(status, [403, 409]); self.assertIsInstance(denied["error"], str)
                    self.assertEqual(snapshot(root), before)

    def test_existing_partial_outer_root_is_not_adopted_or_repaired_by_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory); partial = work / "lifecycle-fail"; partial.mkdir(mode=0o700)
            write_new(partial / "control.json", b'{"version":')
            before = snapshot(work)
            with patch("offline_lifecycle.REAL_POPEN", side_effect=AssertionError("existing partial root launched child")) as spawn:
                with self.assertRaises(Refused): acceptance(None, work)
                spawn.assert_not_called()
            self.assertEqual(snapshot(work), before)

    def test_readonly_guard_also_denies_start_and_stop_without_signalling(self):
        with failed_controller_fixture() as (root, manager, identifier, spawn):
            before = snapshot(root)
            with execution_guards(read_only=True) as guards:
                with self.assertRaisesRegex(AssertionError, "^lifecycle QA reached start$"):
                    manager.start(start_request(manager))
                with self.assertRaisesRegex(AssertionError, "^lifecycle QA reached stop$"):
                    manager.stop(identifier)
            self.assertEqual(guards["start"], guards["stop"]); self.assertEqual(guards["stop"], 1)
            self.assertEqual(snapshot(root), before); self.assertEqual(spawn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
