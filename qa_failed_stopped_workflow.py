"""Two fresh controlled child lifecycles, with no agent or check execution.

Actual native acceptance is called only by the final runner. Controlled exit and
explicit owned Stop retain the unchanged production FAILED state. No result,
patch, run directory or review is invented to describe either process.
"""

import re
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, canonical, parse, sha, write_new
from offline_lifecycle import LifecycleManager, armed_checkpoint, initialize, lifecycle_report, validate_fixture
from offline_workflow import _read
from test_offline_workflow_integration import memory_http, snapshot, start_request
from test_run_history_integration import history_guard, history_request, open_request
from test_saved_review_history_integration import history_pins, saved_history_guard
from test_saved_run_review_integration import review_guard


REPORT_KEYS = {"version", "scenario", "fixture_id", "run_id", "status", "outcome", "metadata_state", "exit_code",
               "signal", "guard_attempts", "source_unchanged", "original_inputs_unchanged", "run_directory_present",
               "agent_executed", "notes"}
GUARD_KEYS = ("agent", "checks", "provider", "network", "git", "worker", "review", "export", "stop", "start")
DEADLINE_SECONDS = 20


@contextmanager
def execution_guards(read_only=False):
    """Block agent/check/provider/network paths; readonly additionally blocks spawn/writers."""
    counts = dict.fromkeys(GUARD_KEYS, 0)
    targets = {
        "agent": ["agent.main", "agent.Session.run", "agent.ScriptedDemo.request"],
        "checks": ["agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.fixed_checks",
                   "offline_workflow.fixed_checks", "offline_workflow.java_checks"],
        "provider": ["agent.Ollama.request", "agent.Ollama.preflight"],
        "network": ["socket.socket", "http.client.HTTPConnection.connect", "http.client.HTTPSConnection.connect"],
        "git": ["git_workspace.git"],
    }
    if read_only:
        targets.update({"worker": ["offline_lifecycle.REAL_POPEN", "workbench.subprocess.Popen", "workbench.subprocess.run"],
                        "review": ["workbench.Manager.review"], "export": ["workbench.Manager.export"],
                        "stop": ["offline_lifecycle.LifecycleManager.stop"],
                        "start": ["offline_lifecycle.LifecycleManager.start"]})
    def blocked(kind):
        def refuse(*_args, **_kwargs):
            counts[kind] += 1
            raise AssertionError("lifecycle QA reached " + kind)
        return refuse
    with ExitStack() as stack:
        for kind, names in targets.items():
            for name in names:
                stack.enter_context(patch(name, side_effect=blocked(kind)))
        if read_only:
            stack.enter_context(patch("workbench.process_stamp", side_effect=AssertionError("terminal restart probed process")))
        yield counts


def verified_report(root, scenario):
    """Require the genuine typed receipt chain, not a favourable metadata label."""
    report = lifecycle_report(root)
    assert type(report) is dict and set(report) == REPORT_KEYS
    assert type(report["version"]) is int and report["version"] == 1 and report["scenario"] == scenario
    assert type(report["fixture_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", report["fixture_id"]) is not None
    assert type(report["run_id"]) is str and re.fullmatch(r"[0-9a-f]{16}", report["run_id"]) is not None
    assert report["status"] == "VERIFIED" and report["metadata_state"] == "FAILED"
    assert report["outcome"] == ("CONTROLLED_FAILURE" if scenario == "fail" else "OWNED_STOP")
    assert type(report["exit_code"]) is int and report["exit_code"] == (23 if scenario == "fail" else 130)
    if scenario == "fail":
        assert report["signal"] is None
    else:
        assert type(report["signal"]) is int and report["signal"] == 15
    assert report["source_unchanged"] is True and report["original_inputs_unchanged"] is True
    assert report["run_directory_present"] is False and report["agent_executed"] is False
    assert type(report["guard_attempts"]) is dict and set(report["guard_attempts"]) == {"provider", "checks", "network"}
    assert all(type(value) is int and value == 0 for value in report["guard_attempts"].values())
    assert report["notes"] == [] and len(canonical(report)) <= 65536
    return report


def inspect_terminal(manager, report, token):
    """Keep the real failed normal feed; guard only the explicit saved routes."""
    identifier = report["run_id"]
    request = memory_http(manager, token=token)
    status, normal = request("/api/history", method="GET")
    assert status == 200 and len(normal) == 1 and normal[0]["id"] == identifier and normal[0]["state"] == "FAILED"
    status, view = request("/api/run/" + identifier, method="GET")
    assert status == 200 and view["id"] == identifier and view["state"] == "FAILED"
    assert view["result"] is None and view["review"] is None and view["patch"] == ""
    assert view["result_sha256"] is None and view["patch_sha256"] is None
    assert view["checks"] == [] and view["plan"] == [] and view["events"] == []
    assert not manager.run_path(identifier).exists()
    with history_guard(manager):
        status, search = request("/api/run-history-search", history_request(identifier, "arithmetic"))
        assert status == 200 and len(search["runs"]) == 1 and search["runs"][0]["id"] == identifier
        assert search["runs"][0]["state"] == "FAILED"
        pins = open_request(search)
        status, opened = request("/api/run-history-open", pins)
        assert status == 200 and opened["id"] == identifier and opened["state"] == "FAILED"
    with review_guard(manager):
        status, review = request("/api/run-history-review", pins)
        assert status == 200 and review["version"] == 2 and review["summary"]["state"] == "FAILED"
        decision = review["decision"]
        assert decision["state"] == "UNKNOWN" and decision["receipt"] is None
        assert decision["catalog_complete"] is False and decision["inspected"] == 0
        assert all(value is None for value in decision["current"].values())
        assert "REVIEW_CATALOG_MISSING" in decision["notes"]
    with saved_history_guard(manager):
        status, listed = request("/api/saved-review-history", history_pins(review))
        assert status == 200 and listed["history"]["entries"] == []
        assert listed["history"]["inspected"] == 0 and listed["history"]["catalog_complete"] is False
        assert listed["history"]["current"] == decision["current"]
        status, detail = request("/api/saved-review-history-entry", history_pins(review, "review-000.json"))
        assert status == 409 and detail == {"error": "SAVED_REVIEW_NOT_FOUND"}
    return {"normal_history_sha256": sha(canonical(normal)), "normal_state": view["state"],
            "normal_view_sha256": sha(canonical(view)), "metadata_open": opened,
            "saved_review": review, "history": listed, "selected_detail_refusal": detail}


def refuse_insufficient_review_export(manager, identifier):
    """Exercise real gates: requests occur, but no review or export is produced."""
    before = snapshot(manager.lifecycle_root)
    request = memory_http(manager, token="invented-lifecycle-gate-probes")
    status, review = request("/api/review", {"id": identifier, "result_sha256": "0" * 64,
        "patch_sha256": "0" * 64, "verdict": "accepted", "note": "Controlled lifecycle has no passing agent evidence."})
    assert status == 409 and review == {"error": "TASK_NOT_REVIEW_READY"}
    status, exported = request("/api/export/" + identifier, method="GET")
    assert status == 409 and exported == {"error": "REVIEW_REQUIRED"}
    assert snapshot(manager.lifecycle_root) == before
    return {"review_request_refusal": review["error"], "export_request_refusal": exported["error"],
            "negative_review_requests": 1, "negative_export_requests": 1, "review_writes": 0, "export_outputs": 0}


def acceptance(jdk, work):
    """Once per fresh root: expected failure/owned Stop, never an agent attempt."""
    scenarios, manager = {}, None
    with execution_guards() as parent_counts:
        try:
            for scenario in ["fail", "stop"]:
                root = work / ("lifecycle-" + scenario)
                control = initialize(root, scenario)
                manager = LifecycleManager(root)
                initialized = snapshot(root)
                request = memory_http(manager, token="invented-lifecycle-" + scenario + "-initial")
                status, initial = request("/api/history", method="GET")
                assert status == 200 and initial == []
                status, started = request("/api/start", start_request(manager))
                assert status == 200, "controlled lifecycle launch refused; evidence retained without retry"
                identifier = started["id"]
                metadata = parse(_read(manager.root, "workspace/data/jobs/" + identifier + ".json", 32768))
                assert metadata["state"] == "RUNNING"
                states, stop_response, armed_normal_view = [], None, None
                deadline = time.monotonic() + DEADLINE_SECONDS
                if scenario == "stop":
                    while not armed_checkpoint(root, identifier):
                        assert time.monotonic() < deadline, "controlled child did not arm; evidence retained"
                        time.sleep(0.02)
                    status, running = request("/api/history", method="GET")
                    assert status == 200 and len(running) == 1 and running[0]["state"] == "RUNNING"
                    states.append("RUNNING")
                    status, armed_normal_view = request("/api/run/" + identifier, method="GET")
                    assert status == 200 and armed_normal_view["state"] == "RUNNING"
                    status, stop_response = request("/api/stop", {"id": identifier})
                    assert status == 200 and stop_response == {"state": "STOP_REQUESTED"}
                while True:
                    status, normal = request("/api/history", method="GET")
                    assert status == 200 and len(normal) == 1 and normal[0]["id"] == identifier
                    state = normal[0]["state"]
                    if not states or states[-1] != state:
                        states.append(state)
                    if state not in {"RUNNING", "STOP_REQUESTED"}:
                        break
                    assert time.monotonic() < deadline, "controlled child exceeded bounded wait; evidence retained"
                    time.sleep(0.02)
                assert state == "FAILED" and manager.children == {}
                report = verified_report(root, scenario)
                assert report["run_id"] == identifier
                assert manager.counters["worker_launches"] == manager.counters["start_attempts"] == 1
                assert manager.lifecycle_counters == {"native_launches": 1, "explicit_stops": int(scenario == "stop"), "containment_stops": 0}
                gates = refuse_insufficient_review_export(manager, identifier)
                before = snapshot(root)
                assert all(before.get(name) == value for name, value in initialized.items())
                first = inspect_terminal(manager, report, token="invented-lifecycle-" + scenario + "-first-read")
                assert snapshot(root) == before and validate_fixture(root) == control
                native_counters, lifecycle_counters = dict(manager.counters), dict(manager.lifecycle_counters)
                manager.close(); manager = None
                assert snapshot(root) == before
                with execution_guards(read_only=True) as restart_counts:
                    manager = LifecycleManager(root)
                    restarted_report = verified_report(root, scenario)
                    second = inspect_terminal(manager, restarted_report, token="invented-lifecycle-" + scenario + "-restart")
                    assert first == second and report == restarted_report and snapshot(root) == before
                    assert manager.counters["start_requests"] == manager.counters["start_attempts"] == manager.counters["worker_launches"] == 0
                    assert manager.counters["review_requests"] == manager.counters["export_requests"] == 0
                    assert manager.lifecycle_counters == {"native_launches": 0, "explicit_stops": 0, "containment_stops": 0}
                    restarted_counters = dict(manager.counters)
                    manager.close(); manager = None
                    assert not any(restart_counts.values()) and snapshot(root) == before
                scenarios[scenario] = {"control_sha256": sha(canonical(control)), "report": report,
                    "initial_persisted_metadata_state": metadata["state"], "observed_normal_history_states": states,
                    "armed_running_view_observed": armed_normal_view is not None, "explicit_stop_response": stop_response,
                    "gate_refusals": gates, "first": first, "restarted": second,
                    "initial_native_counters": native_counters, "initial_lifecycle_counters": lifecycle_counters,
                    "restarted_native_counters": restarted_counters, "restarted_guard_attempts": restart_counts,
                    "whole_settled_fixture_bytes_modes_unchanged": True,
                    "initialized_paths_bytes_modes_unchanged": True, "new_restart_workers_checks_writes_exports": 0}
        finally:
            if manager is not None:
                manager.close()  # Containment is never relabelled as explicit owned Stop.
        assert not any(parent_counts.values())
    observations = {"version": 1, "status": "PASS", "scenarios": scenarios, "parent_guard_attempts": parent_counts,
        "control_processes": 2, "agent_executions": 0, "check_executions": 0,
        "real_model_qualified": False, "browser_observed_running_transition": False,
        "python_level_guards_not_packet_audit": True}
    write_new(work / "failed-stopped-workflow-acceptance.json", canonical(observations))
    return {"failed_stopped_workflow_actual_controlled_lifecycles": True,
            "failed_stopped_workflow_owned_stop_once": True,
            "failed_stopped_workflow_failed_metadata_not_relabelled": True,
            "failed_stopped_workflow_real_normal_feed_and_saved_reads": True,
            "failed_stopped_workflow_restart_exact_evidence_preserved": True,
            "failed_stopped_workflow_agent_executions": 0, "failed_stopped_workflow_checks": 0,
            "failed_stopped_workflow_model_requests": 0, "failed_stopped_workflow_real_model_qualified": False}
