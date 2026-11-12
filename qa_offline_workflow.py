"""One persistent actual scripted Python workflow plus separate Java checks.

Normal history/view stay active. No temporary fixture hides a failed worker;
the owned root, claims, evidence, guarded-child receipts and exports are retained.
"""

import json
import time
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from offline_workflow import WorkflowManager, initialize, java_checks, python_report, validate_fixture
from test_offline_workflow_integration import memory_http, snapshot, start_request


def acceptance(jdk, work):
    root = work / "offline-workflow"
    marker = initialize(root)
    manager = WorkflowManager(root)
    source_pins = {name: {"sha256": sha((root / name).read_bytes()), "mode": (root / name).stat().st_mode & 0o777}
                   for name in marker["files"]}
    states, observations = [], {}
    try:
        request = memory_http(manager)
        status, empty = request("/api/history", method="GET")
        assert manager.models == [] and status == 200 and empty == []
        status, started = request("/api/start", start_request(manager))
        assert status == 200, "scripted start refused; owned evidence retained"
        run_id = started["id"]
        initial_metadata = json.loads((root / "workspace/data/jobs" / (run_id + ".json")).read_bytes())
        assert initial_metadata["state"] == "RUNNING" and initial_metadata["backend"] == "scripted-demo"
        deadline = time.monotonic() + 90
        while True:
            status, rows = request("/api/history", method="GET")
            assert status == 200, "normal history refused; owned evidence retained"
            assert len(rows) == 1 and rows[0]["id"] == run_id
            state = rows[0]["state"]
            if not states or states[-1] != state: states.append(state)
            if state not in {"RUNNING", "STOP_REQUESTED"}: break
            assert time.monotonic() < deadline, "owned scripted workflow exceeded its bounded wait; evidence retained"
            time.sleep(0.05)
        assert state == "REVIEW_READY", "scripted workflow did not pass; owned evidence retained without retry"
        status, view = request("/api/run/" + run_id, method="GET")
        assert status == 200
        assert view["state"] == "REVIEW_READY" and view["backend"] == "scripted-demo"
        assert view["plan"] == ["Read the fixture", "Correct addition", "Run the fixed tests"]
        result = view["result"]
        assert result["status"] == "REVIEW_READY" and result["turns"] == 6
        assert result["ai_inference"] is False and result["source_adopted"] is False
        run = root / "workspace/data/runs" / run_id
        events = [json.loads(path.read_bytes()) for path in sorted(run.glob("event-*.json"))]
        baseline = next(event["value"]["unit"] for event in events if event["kind"] == "baseline_checks")
        final = next(event["value"]["unit"] for event in events if event["kind"] == "independent_final_checks")
        agent_check = next(event["value"]["result"] for event in events if event["kind"] == "tool_result"
                           and event["value"].get("name") == "run_check")
        assert baseline["exit_code"] != 0 and baseline["tests_ran"] == 4
        assert final["exit_code"] == agent_check["exit_code"] == 0
        assert final["tests_ran"] == agent_check["tests_ran"] == 4
        assert not any(row[key] for row in [baseline, agent_check, final] for key in
                       ["timed_out", "output_limited", "infrastructure_error"])
        original = (root / "workspace/project/calculator.py").read_bytes()
        assert (run / "work/calculator.py").read_bytes() == original.replace(b"return a - b", b"return a + b")
        assert (run / "work/test_calculator.py").read_bytes() == (root / "workspace/project/test_calculator.py").read_bytes()
        assert manager.counters["worker_launches"] == 1 and manager.counters["start_attempts"] == 1
        assert manager.counters["history_requests"] > 0 and manager.counters["view_requests"] > 0

        # Existing review/export gates are deliberate independent actions.
        before_review = snapshot(root / "workspace/data")
        try:
            manager.export(run_id)
        except Refused:
            pass
        else:
            raise AssertionError("unreviewed export was accepted")
        assert before_review == snapshot(root / "workspace/data")
        stale = {"id": run_id, "result_sha256": "0" * 64, "patch_sha256": view["patch_sha256"],
                 "verdict": "accepted", "note": "Invented negative stale-pin probe."}
        try:
            manager.review(stale)
        except Refused:
            pass
        else:
            raise AssertionError("stale result pin was accepted")
        assert before_review == snapshot(root / "workspace/data")
        review = manager.review({"id": run_id, "result_sha256": view["result_sha256"], "patch_sha256": view["patch_sha256"],
                                 "verdict": "accepted", "note": "Invented offline workflow acceptance review."})
        assert review["source_applied"] is False
        exported = manager.export(run_id)
        assert exported == (run / "changes.diff").read_bytes()
        assert sha(exported) == result["patch_sha256"] == view["patch_sha256"]
        write_new(work / "offline-workflow-export.patch", exported)
        with patch("offline_workflow.WorkflowManager", side_effect=AssertionError("report reached runtime")), patch(
                "workbench.process_stamp", side_effect=AssertionError("report probed process")):
            report = python_report(root, patch_raw=exported, require_accepted=True)
            try:
                python_report(root, patch_raw=b"Invented mismatched patch", require_accepted=True)
            except Refused:
                pass
            else:
                raise AssertionError("mismatched downloaded patch was accepted")
        assert isinstance(report, dict) and len(canonical(report)) <= 65536
        worker = json.loads((root / "receipts/worker-exit.json").read_bytes())
        assert worker["exit_code"] == worker["provider_attempts"] == worker["network_attempts"] == 0
        assert manager.counters["parent_provider_attempts"] == manager.counters["parent_outbound_attempts"] == 0
        for name, expected in source_pins.items():
            assert {"sha256": sha((root / name).read_bytes()), "mode": (root / name).stat().st_mode & 0o777} == expected
        history = manager.history()
        parent_counters = dict(manager.counters)
        manager.close(); manager = None
        runtime = snapshot(root / "workspace/data")
        worker_raw = (root / "receipts/worker-exit.json").read_bytes()
        with patch("offline_workflow.REAL_POPEN", side_effect=AssertionError("restart launched a worker")), patch(
                "workbench.process_stamp", side_effect=AssertionError("terminal restart probed a process")):
            manager = WorkflowManager(root)
            request = memory_http(manager, token="invented-restarted-workflow-token")
            status, restarted_history = request("/api/history", method="GET")
            assert status == 200 and restarted_history == history
            status, restarted = request("/api/run/" + run_id, method="GET")
            assert status == 200
            assert restarted["result_sha256"] == view["result_sha256"] and restarted["patch_sha256"] == view["patch_sha256"]
            assert manager.export(run_id) == exported
            restarted_report = python_report(root, patch_raw=exported, require_accepted=True)
            assert isinstance(restarted_report, dict)
            assert manager.counters["start_attempts"] == manager.counters["worker_launches"] == 0
        assert runtime == snapshot(root / "workspace/data")
        assert worker_raw == (root / "receipts/worker-exit.json").read_bytes()

        # This is one separate actual Java fixed-check fixture, not a Java
        # agent run, model evaluation or additional Python live-history job.
        java_report = java_checks(root, jdk)
        assert isinstance(java_report, dict) and len(canonical(java_report)) <= 65536
        assert java_report["java_agent_run"] is False and java_report["model_inference"] is False
        assert manager.history() == history and runtime == snapshot(root / "workspace/data")
        assert validate_fixture(root) == marker
        for name, expected in source_pins.items():
            assert {"sha256": sha((root / name).read_bytes()), "mode": (root / name).stat().st_mode & 0o777} == expected
        observations = {"run_id": run_id, "initial_metadata_state": initial_metadata["state"], "normal_history_states": states,
            "python_report": report, "terminal_restart_report": restarted_report, "separate_java_checks": java_report,
            "parent_counters": parent_counters, "restarted_parent_counters": dict(manager.counters), "worker_guard_receipt": worker,
            "export_sha256": sha(exported), "baseline_tests": baseline["tests_ran"], "final_tests": final["tests_ran"],
            "scripted_python_agent_run": True, "java_agent_run": False, "real_model_qualified": False,
            "normal_history_feed_stubbed": False, "source_config_task_and_protected_bytes_modes_unchanged": True,
            "terminal_runtime_evidence_unchanged_after_restart": True, "provider_network_guards_are_python_level_not_packet_audit": True}
        write_new(work / "offline-workflow-acceptance.json", canonical(observations))
    finally:
        if manager is not None: manager.close()
    return {"offline_workflow_actual_scripted_python_normal_history": True,
            "offline_workflow_actual_plan_edit_and_four_baseline_agent_final_tests": True,
            "offline_workflow_explicit_pinned_review_and_export": True,
            "offline_workflow_source_config_task_protected_preserved": True,
            "offline_workflow_terminal_restart_without_launch_or_rerun": True,
            "offline_workflow_separate_actual_java_checks": True,
            "offline_workflow_real_model_qualified": False, "offline_workflow_model_inference_requests": 0}
