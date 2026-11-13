"""One fresh native controlled Stop through the normal HTTP handler in memory.

The parent qualification runner invokes this driver once after source freeze.
It never opens earlier operational/held fixtures, retries a failed root, or
relabels Failed production metadata as an agent success.
"""

import re
import signal
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, canonical, parse, sha, write_new
import offline_live_stop as live
from offline_workflow import new_counters
from qa_failed_stopped_workflow import REPORT_KEYS as LIFECYCLE_KEYS, execution_guards as inherited_guards, inspect_terminal
from test_live_run_stop import memory_http, snapshot, start_request


REPORT_KEYS = {"version", "format", "fixture_id", "run_id", "status", "outcome", "lifecycle",
               "running_response", "armed_stop", "explicit_stop", "containment", "notes", "browser_observed", "counts"}
DEADLINE_SECONDS = 20


@contextmanager
def execution_guards(read_only=False):
    with inherited_guards(read_only=read_only) as inherited, ExitStack() as stack:
        counts = {"start": 0, "stop": 0, "publish": 0}
        if read_only:
            def blocked(name):
                def refuse(*args, **kwargs):
                    counts[name] += 1
                    raise AssertionError("live stop readonly reached " + name)
                return refuse
            stack.enter_context(patch.object(live.LiveStopManager, "start", side_effect=blocked("start")))
            stack.enter_context(patch.object(live.LiveStopManager, "stop", side_effect=blocked("stop")))
            stack.enter_context(patch.object(live, "_publish", side_effect=blocked("publish")))
        yield {"inherited": inherited, "readonly": counts}


def verified_report(root):
    value = live.live_stop_report(root)
    assert type(value) is dict and set(value) == REPORT_KEYS
    assert type(value["version"]) is int and value["version"] == 1 and value["format"] == live.FORMAT
    assert type(value["fixture_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", value["fixture_id"])
    assert type(value["run_id"]) is str and re.fullmatch(r"[0-9a-f]{16}", value["run_id"])
    assert value["status"] == "VERIFIED" and value["outcome"] == "OWNED_STOP"
    assert all(value[key] is True for key in ["running_response", "armed_stop", "explicit_stop"])
    assert value["containment"] is False and value["browser_observed"] is False and value["notes"] == []
    assert type(value["counts"]) is dict and set(value["counts"]) == {"running_responses", "armed_stops", "explicit_stops", "containment_stops"}
    assert all(type(number) is int for number in value["counts"].values())
    assert value["counts"] == {"running_responses": 1, "armed_stops": 1, "explicit_stops": 1, "containment_stops": 0}
    old = value["lifecycle"]
    assert type(old) is dict and set(old) == LIFECYCLE_KEYS and type(old["version"]) is int and old["version"] == 1
    assert old["scenario"] == "stop" and old["fixture_id"] == value["fixture_id"] and old["run_id"] == value["run_id"]
    assert old["status"] == "VERIFIED" and old["outcome"] == "OWNED_STOP" and old["metadata_state"] == "FAILED"
    assert type(old["exit_code"]) is int and old["exit_code"] == 130
    assert type(old["signal"]) is int and old["signal"] == signal.SIGTERM
    assert old["source_unchanged"] is True and old["original_inputs_unchanged"] is True
    assert old["run_directory_present"] is False and old["agent_executed"] is False and old["notes"] == []
    assert type(old["guard_attempts"]) is dict and set(old["guard_attempts"]) == {"provider", "checks", "network"}
    assert all(type(number) is int and number == 0 for number in old["guard_attempts"].values())
    assert len(canonical(value)) <= 65536
    return value


def _zero(group):
    return all(type(number) is int and number == 0 for number in group.values())


def refuse_terminal_outputs(root, manager, request, identifier):
    """Probe real review/export gates through the live wrapper's in-memory handler."""
    before = snapshot(root)
    counters = dict(manager.counters)
    code, review = request("/api/review", {"id": identifier, "result_sha256": "0" * 64,
        "patch_sha256": "0" * 64, "verdict": "accepted", "note": "Controlled Stop has no passing agent evidence."})
    assert code == 409 and review == {"error": "TASK_NOT_REVIEW_READY"}
    code, exported = request("/api/export/" + identifier, method="GET")
    assert code == 409 and exported == {"error": "REVIEW_REQUIRED"}
    assert manager.counters["review_requests"] - counters["review_requests"] == 1
    assert manager.counters["export_requests"] - counters["export_requests"] == 1
    assert snapshot(root) == before
    return {"review_request_refusal": review["error"], "export_request_refusal": exported["error"],
        "negative_review_requests": 1, "negative_export_requests": 1, "review_writes": 0, "export_outputs": 0,
        "whole_outer_fixture_bytes_modes_unchanged": True, "handler_in_memory": True}


def wait_for_armed(root, manager, identifier, deadline):
    """Serialize readiness with owned receipt publication; never retry a refusal."""
    while True:
        with manager.lock:
            ready = live.armed_checkpoint(root, identifier)
        if ready: return
        assert time.monotonic() < deadline, "native child did not durably arm; evidence retained"
        time.sleep(0.02)


def setup_manager(root):
    """Pin initialized files across setup, then retain the full pre-Run tree."""
    before = snapshot(root)
    files = {name: row for name, row in before.items() if "sha256" in row}
    directories = {name: row for name, row in before.items() if "sha256" not in row}
    manager = live.LiveStopManager(root)
    try:
        initialized = snapshot(root)
        assert all(initialized.get(name) == row for name, row in files.items()), "setup changed an initialized file"
        assert all(name in initialized and set(initialized[name]) == {"mode", "uid", "links"}
                   and all(initialized[name][field] == row[field] for field in ["mode", "uid"])
                   for name, row in directories.items()), "setup changed an initialized directory mode or owner"
        evidence = {"initial_regular_files": len(files), "initial_regular_file_pins_sha256": sha(canonical(files)),
            "initial_file_bytes_modes_links_unchanged": True, "existing_directory_modes_owners_unchanged": True,
            "full_run_baseline_after_manager_setup": True}
        return manager, initialized, evidence
    except BaseException:
        manager.close()
        raise


def acceptance(jdk, work):
    """Native only when the final runner invokes us on its NEW private work root."""
    del jdk  # This case runs no Java or other project check.
    root, manager = work / "live-run-stop", None
    with execution_guards() as guards:
        try:
            control = live.initialize(root)
            manager, initialized, setup = setup_manager(root)
            request = memory_http(manager, token="invented-live-stop-native-initial")
            code, history = request("/api/history", method="GET")
            assert code == 200 and history == []
            initial_report = live.live_stop_report(root)
            assert initial_report["status"] == initial_report["outcome"] == "UNKNOWN"
            assert initial_report["running_response"] is False and initial_report["armed_stop"] is False
            code, started = request("/api/start", start_request(manager))
            assert code == 200, "native launch refused; fresh evidence retained without retry"
            identifier = started["id"]
            metadata = parse((manager.root / "workspace/data/jobs" / (identifier + ".json")).read_bytes())
            assert metadata["state"] == "RUNNING"
            code, running_history = request("/api/history", method="GET")
            assert code == 200 and len(running_history) == 1 and running_history[0]["state"] == "RUNNING"
            code, running_view = request("/api/run/" + identifier, method="GET")
            assert code == 200 and running_view["state"] == "RUNNING" and running_view["id"] == identifier
            deadline = time.monotonic() + DEADLINE_SECONDS
            wait_for_armed(root, manager, identifier, deadline)
            code, stopping = request("/api/stop", {"id": identifier})
            assert code == 200 and stopping == {"state": "STOP_REQUESTED"}
            states = ["RUNNING"]
            while True:
                code, history = request("/api/history", method="GET")
                assert code == 200 and len(history) == 1 and history[0]["id"] == identifier
                state = history[0]["state"]
                if states[-1] != state: states.append(state)
                if state not in {"RUNNING", "STOP_REQUESTED"}: break
                assert time.monotonic() < deadline, "native Stop did not settle; evidence retained"
                time.sleep(0.02)
            assert state == "FAILED" and manager.children == {}
            report = verified_report(root)
            assert report["run_id"] == identifier
            assert manager.counters["start_requests"] == manager.counters["start_attempts"] == manager.counters["worker_launches"] == 1
            assert manager.lifecycle_counters == {"native_launches": 1, "explicit_stops": 1, "containment_stops": 0}
            assert manager.live_counters == {"running_responses": 1, "armed_stops": 1, "explicit_stops": 1, "containment_stops": 0}
            before = snapshot(root)
            gate_refusals = refuse_terminal_outputs(root, manager, request, identifier)
            assert snapshot(root) == before
            first = inspect_terminal(manager, {"run_id": identifier}, "invented-live-stop-native-terminal")
            assert snapshot(root) == before
            assert all(before.get(name) == row for name, row in initialized.items())
            parent_counters, lifecycle_counters, live_counters = dict(manager.counters), dict(manager.lifecycle_counters), dict(manager.live_counters)
            manager.close(); manager = None
            assert snapshot(root) == before
            with execution_guards(read_only=True) as restarted_guards:
                manager = live.LiveStopManager(root)
                request2 = memory_http(manager, token="invented-live-stop-native-restarted")
                code, refused = request2("/api/history", method="GET", headers={"X-Workbench-Token": "invented-live-stop-native-terminal"})
                assert code == 403 and refused == {"error": "SESSION_REQUIRED"}
                manager.counters = new_counters()
                restarted_report = verified_report(root)
                second = inspect_terminal(manager, {"run_id": identifier}, "invented-live-stop-native-restart-reads")
                assert first == second and restarted_report == report and snapshot(root) == before
                assert manager.counters["start_requests"] == manager.counters["start_attempts"] == manager.counters["worker_launches"] == 0
                assert manager.counters["review_requests"] == manager.counters["export_requests"] == 0
                assert _zero(manager.lifecycle_counters) and _zero(manager.live_counters)
                manager.close(); manager = None
                assert snapshot(root) == before and _zero(restarted_guards["inherited"]) and _zero(restarted_guards["readonly"])
            assert _zero(guards["inherited"]) and _zero(guards["readonly"])
        finally:
            if manager is not None: manager.close()  # Containment never becomes expected Stop proof.
    value = {"version": 1, "status": "PASS", "control_sha256": sha(canonical(control)), "report": report,
        "initial_metadata_state": metadata["state"], "normal_history_states": states,
        "successful_running_view_sha256": sha(canonical(running_view)), "stop_response": stopping,
        "setup": setup, "gate_refusals": gate_refusals,
        "first": first, "restart": second, "parent_counters": parent_counters,
        "lifecycle_counters": lifecycle_counters, "live_counters": live_counters, "guard_attempts": guards,
        "all_settled_bytes_modes_unchanged_on_restart": True, "no_native_restart_launch": True,
        "controlled_processes": 1, "agent_executions": 0, "check_executions": 0, "model_requests": 0,
        "real_model_qualified": False, "browser_observed_running_transition": False,
        "native_evidence_class": "CONTROLLED_PROCESS_WITH_NORMAL_HTTP_HANDLER_IN_MEMORY",
        "native_socket_or_client_delivery_qualified": False,
        "python_level_guards_not_packet_audit": True}
    write_new(work / "live-run-stop-acceptance.json", canonical(value))
    return {"live_run_stop_native_once": True, "live_run_stop_http_running_before_owned_stop": True,
        "live_run_stop_failed_receipt_preserved": True, "live_run_stop_restart_bytes_unchanged": True,
        "live_run_stop_agent_executions": 0, "live_run_stop_checks": 0, "live_run_stop_model_requests": 0,
        "live_run_stop_real_model_qualified": False}
