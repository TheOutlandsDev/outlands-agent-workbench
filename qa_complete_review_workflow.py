"""Read the earlier same-source actual workflow; never create another attempt.

Normal completed history/view remain real. Saved-only guards apply only to the
explicit metadata/evidence reads. This stage performs no check or model request.
"""

from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, parse, sha, write_new
from offline_workflow import WorkflowManager, _read, python_report, validate_fixture
from test_offline_workflow_integration import memory_http, snapshot
from test_run_history_integration import history_guard, history_request, open_request
from test_saved_review_history_integration import history_pins, saved_history_guard
from test_saved_run_review_integration import review_guard


GUARD_KEYS = ("worker", "provider", "checks", "process", "outbound", "git", "start", "stop", "review", "export")
ZERO_COUNTERS = ("start_requests", "start_attempts", "worker_launches", "review_requests", "export_requests",
                 "parent_provider_attempts", "parent_outbound_attempts", "denied_requests")
READ_COUNTERS = {"history_requests": 1, "view_requests": 1, "metadata_search_requests": 1,
                 "metadata_open_requests": 1, "saved_review_requests": 2,
                 "saved_review_history_requests": 1, "saved_review_history_entry_requests": 1}


def require(condition, suffix):
    if not condition:
        raise Refused("COMPLETE_REVIEW_" + suffix)


@contextmanager
def zero_execution():
    """Fail before any execution/writer while retaining finite attempt counters."""
    calls = dict.fromkeys(GUARD_KEYS, 0)
    targets = {
        "worker": ["offline_workflow.REAL_POPEN", "workbench.subprocess.Popen", "workbench.subprocess.run"],
        "provider": ["agent.Ollama.request", "agent.Ollama.preflight", "agent.ScriptedDemo.request"],
        "checks": ["agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.fixed_checks",
                   "offline_workflow.fixed_checks", "offline_workflow.java_checks"],
        "process": ["workbench.process_stamp"],
        "outbound": ["socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                     "socket.create_connection", "socket.getaddrinfo", "http.client.HTTPConnection.connect",
                     "http.client.HTTPSConnection.connect"],
        "git": ["git_workspace.git"],
        "start": ["offline_workflow.WorkflowManager.start"],
        "stop": ["workbench.Manager.stop"],
        "review": ["workbench.Manager.review"],
        "export": ["workbench.Manager.export"],
    }
    def blocked(kind):
        def refuse(*_args, **_kwargs):
            calls[kind] += 1
            raise AssertionError("complete review reached " + kind)
        return refuse
    with ExitStack() as stack:
        for kind, names in targets.items():
            for name in names:
                stack.enter_context(patch(name, side_effect=blocked(kind)))
        yield calls


def load_dependency(work):
    """Verify this runner's retained fixture/report without adoption or fallback."""
    require(isinstance(work, Path) and work.is_absolute() and ".." not in work.parts, "DEPENDENCY")
    root = work / "offline-workflow"
    try:
        prior_raw = _read(work, "offline-workflow-acceptance.json", 65536)
        prior = parse(prior_raw)
        require(type(prior) is dict, "DEPENDENCY")
        require(prior.get("scripted_python_agent_run") is True and prior.get("java_agent_run") is False
                and prior.get("real_model_qualified") is False and prior.get("normal_history_feed_stubbed") is False
                and prior.get("initial_metadata_state") == "RUNNING"
                and prior.get("source_config_task_and_protected_bytes_modes_unchanged") is True
                and prior.get("terminal_runtime_evidence_unchanged_after_restart") is True,
                "DEPENDENCY")
        validate_fixture(root)  # Includes the current source-bound launch argv.
        exported = _read(work, "offline-workflow-export.patch", 65536)
        report = python_report(root, patch_raw=exported, require_accepted=True)
        require(report == prior.get("python_report") == prior.get("terminal_restart_report")
                and report["id"] == prior.get("run_id") and report["ai_inference"] is False
                and report["baseline_tests"] == report["agent_tests"] == report["final_tests"] == 4
                and report["accepted"] is True and report["source_unchanged"] is True
                and report["protected_unchanged"] is True and report["download_verified"] is True
                and prior.get("export_sha256") == report["patch_sha256"] == sha(exported), "DEPENDENCY")
        previous = prior.get("parent_counters")
        restarted = prior.get("restarted_parent_counters")
        require(type(previous) is dict and type(restarted) is dict
                and type(previous.get("worker_launches")) is int and previous["worker_launches"] == 1
                and type(previous.get("start_attempts")) is int and previous["start_attempts"] == 1
                and all(type(restarted.get(key)) is int for key in ["worker_launches", "start_attempts"])
                and restarted.get("worker_launches") == restarted.get("start_attempts") == 0
                and all(type(previous.get(key)) is int for key in ["parent_provider_attempts", "parent_outbound_attempts"])
                and previous.get("parent_provider_attempts") == previous.get("parent_outbound_attempts") == 0,
                "DEPENDENCY")
        require(prior.get("worker_guard_receipt") == parse(_read(root, "receipts/worker-exit.json", 32768))
                and type(prior.get("baseline_tests")) is int and prior["baseline_tests"] == 4
                and type(prior.get("final_tests")) is int and prior["final_tests"] == 4, "DEPENDENCY")
        java_raw = _read(root, "java/result.json", 65536)
        java, previous_java = parse(java_raw), prior.get("separate_java_checks")
        require(type(java) is dict and type(java.get("version")) is int and java["version"] == 1 and java.get("java_agent_run") is False
                and java.get("model_inference") is False and type(java.get("checks")) is dict
                and set(java["checks"]) == {"unit"}, "DEPENDENCY")
        checked = java["checks"]["unit"]
        require(type(checked) is dict and type(checked.get("exit_code")) is int and checked["exit_code"] == 0
                and type(checked.get("tests_ran")) is int and checked["tests_ran"] == 1
                and all(checked.get(key) is False for key in ["timed_out", "output_limited", "infrastructure_error"])
                and type(previous_java) is dict and previous_java.get("status") == "PASS"
                and previous_java.get("java_agent_run") is False and previous_java.get("model_inference") is False
                and type(previous_java.get("protected_mains")) is int and previous_java["protected_mains"] == 1
                and previous_java.get("sources_unchanged") is True
                and previous_java.get("receipt_sha256") == sha(java_raw), "DEPENDENCY")
        return {"root": root, "prior": prior, "prior_sha256": sha(prior_raw), "report": report,
                "export_sha256": sha(exported), "java_receipt_sha256": sha(java_raw)}
    except Refused as error:
        if str(error).startswith("COMPLETE_REVIEW_"):
            raise
        raise Refused("COMPLETE_REVIEW_DEPENDENCY") from None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise Refused("COMPLETE_REVIEW_DEPENDENCY") from None


def inspect_completed(manager, dependency, token="invented-complete-review-first-session"):
    """Use only the restricted HTTP handler; do not replace the normal feed."""
    root, prior = dependency["root"], dependency["prior"]
    identifier = prior["run_id"]
    request = memory_http(manager, token=token)
    status, normal = request("/api/history", method="GET")
    assert status == 200 and len(normal) == 1 and normal[0]["id"] == identifier
    assert normal[0]["state"] == "REVIEW_READY"
    status, view = request("/api/run/" + identifier, method="GET")
    assert status == 200 and view["state"] == "REVIEW_READY" and view["backend"] == "scripted-demo"
    assert view["plan"] == ["Read the fixture", "Correct addition", "Run the fixed tests"]
    assert view["result"]["turns"] == 6 and view["result"]["ai_inference"] is False
    assert view["result_sha256"] == dependency["report"]["result_sha256"]
    assert view["patch_sha256"] == dependency["export_sha256"]
    with history_guard(manager):
        status, search = request("/api/run-history-search", history_request(identifier, "arithmetic"))
        assert status == 200 and len(search["runs"]) == 1 and search["runs"][0]["id"] == identifier
        assert search["inspected"] == search["matched"] == search["returned"] == 1
        assert not search["catalog_truncated"] and not search["result_truncated"]
        pins = open_request(search)
        status, opened = request("/api/run-history-open", pins)
        assert status == 200 and opened["id"] == identifier and opened["state"] == "REVIEW_READY"
        assert opened["goal"] == manager.projects["arithmetic"]["definition"]["goal"]
    with review_guard(manager):
        status, review = request("/api/run-history-review", pins)
        assert status == 200 and review["version"] == 2 and review["decision"]["state"] == "ACCEPTED"
    receipt_raw = _read(root, "workspace/data/runs/" + identifier + "/review-000.json", 32768)
    receipt = parse(receipt_raw)
    assert review["decision"]["receipt"]["name"] == "review-000.json"
    assert review["decision"]["receipt"]["sha256"] == sha(receipt_raw)
    assert review["decision"]["receipt"]["note"] == receipt["note"]
    with saved_history_guard(manager):
        status, listed = request("/api/saved-review-history", history_pins(review))
        assert status == 200 and listed["history"]["catalog_complete"] is True
        assert listed["history"]["inspected"] == 1 and len(listed["history"]["entries"]) == 1
        row = listed["history"]["entries"][0]
        assert row["name"] == "review-000.json" and row["status"] == "OK"
        assert row["verdict"] == "accepted" and row["artifact_state"] == "MATCHING" and "note" not in row
        status, detail = request("/api/saved-review-history-entry", history_pins(review, row["name"]))
        assert status == 200
        entry = detail["history"]["entry"]
        assert {key: value for key, value in entry.items() if key != "note"} == row
        assert entry["note"] == receipt["note"] and entry["recorded"] == receipt["recorded"]
        assert listed["history"]["current"] == detail["history"]["current"] == review["decision"]["current"]
        assert listed["history"]["current"]["result_sha256"] == dependency["report"]["result_sha256"]
        assert listed["history"]["current"]["patch_sha256"] == dependency["export_sha256"]
        for body in [listed, detail]:
            assert all(body[key] == review[key] for key in history_pins(review))
            assert len(canonical(body)) <= 65536
    with review_guard(manager):
        status, unchanged = request("/api/run-history-review", pins)
        assert status == 200 and unchanged == review
    assert all(manager.counters[key] == 0 for key in ZERO_COUNTERS)
    assert all(manager.counters[key] == count for key, count in READ_COUNTERS.items())
    return {"normal_run_id": normal[0]["id"], "normal_state": normal[0]["state"],
            "normal_history_sha256": sha(canonical(normal)), "normal_feed_stubbed": False,
            "view_result_sha256": view["result_sha256"], "view_patch_sha256": view["patch_sha256"],
            "metadata_open": opened, "saved_review": review, "history": listed, "detail": detail}


def acceptance(jdk, work):
    """Last stage: earlier Python4/Java1 evidence is read, never re-executed."""
    manager = None
    with zero_execution() as calls:
        dependency = load_dependency(work)
        root = dependency["root"]
        before = snapshot(root)
        try:
            manager = WorkflowManager(root)
            first = inspect_completed(manager, dependency)
            assert snapshot(root) == before
            first_counters = dict(manager.counters)
            manager.close(); manager = None
            assert snapshot(root) == before
            manager = WorkflowManager(root)
            second = inspect_completed(manager, dependency, token="invented-complete-review-restarted-session")
            assert second == first and snapshot(root) == before
            second_counters = dict(manager.counters)
        finally:
            if manager is not None:
                manager.close()
        assert snapshot(root) == before
        final_dependency = load_dependency(work)
        assert final_dependency == dependency and not any(calls.values())
    observations = {"version": 1, "status": "PASS", "run_id": dependency["prior"]["run_id"],
        "earlier_actual_acceptance_sha256": dependency["prior_sha256"],
        "earlier_python_tests": {"baseline": 4, "agent": 4, "final": 4},
        "earlier_java_protected_mains": 1, "earlier_java_receipt_sha256": dependency["java_receipt_sha256"],
        "earlier_export_sha256": dependency["export_sha256"], "first": first, "restarted": second,
        "first_counters": first_counters, "restarted_counters": second_counters, "guard_attempts": calls,
        "whole_fixture_bytes_modes_unchanged": True, "new_workers": 0, "new_checks": 0,
        "new_review_writes": 0, "new_export_requests": 0, "normal_history_feed_stubbed": False,
        "real_model_qualified": False, "browser_observed_running_transition": False,
        "python_level_guards_not_packet_audit": True}
    write_new(work / "complete-review-workflow-acceptance.json", canonical(observations))
    return {"complete_review_workflow_existing_actual_receipt_only": True,
            "complete_review_workflow_restricted_normal_feed_and_saved_history": True,
            "complete_review_workflow_restart_exact_pins_notes_decision": True,
            "complete_review_workflow_whole_fixture_preserved": True,
            "complete_review_workflow_new_workers": 0, "complete_review_workflow_new_checks": 0,
            "complete_review_workflow_model_requests": 0, "complete_review_workflow_real_model_qualified": False}
