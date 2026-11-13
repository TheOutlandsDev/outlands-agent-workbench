"""Read-only observed receipt history, separate checks and prior actual proof."""

import copy
import json

from agent import Refused, canonical, sha, write_new
from git_workspace import fixed_checks
from test_bundle_workspace_integration import no_provider_calls
from test_saved_run_review_integration import private_inventory
from test_saved_review_history_integration import (
    build_history_fixture, current_review, history_pins, memory_history_http, saved_history_guard,
)
from workbench import Manager


def existing_actual_history(work):
    root, prior_path = work / "offline-workflow", work / "offline-workflow-acceptance.json"
    if not root.is_dir() or not prior_path.is_file(): raise Refused("SAVED_REVIEW_NOT_FOUND")
    prior = json.loads(prior_path.read_bytes())
    if (prior.get("scripted_python_agent_run") is not True or prior.get("real_model_qualified") is not False
            or prior.get("python_report", {}).get("accepted") is not True):
        raise Refused("SAVED_REVIEW_RECORD_INVALID")
    before = private_inventory(root)
    manager = Manager(root / "workspace/config.json", root / "workspace/data")
    try:
        review = current_review(manager, prior["run_id"])
        assert review["decision"]["state"] == "ACCEPTED"
        with saved_history_guard(manager):
            request = memory_history_http(manager)
            status, listed = request("/api/saved-review-history", history_pins(review))
            assert status == 200 and listed["history"]["inspected"] == 1 and listed["history"]["catalog_complete"]
            row = listed["history"]["entries"][0]
            assert row["name"] == "review-000.json" and row["status"] == "OK" and row["artifact_state"] == "MATCHING"
            status, detail = request("/api/saved-review-history-entry", history_pins(review, row["name"]))
            assert status == 200 and {key: value for key, value in detail["history"]["entry"].items() if key != "note"} == row
            assert listed["history"]["current"] == review["decision"]["current"]
            assert listed["history"]["current"]["result_sha256"] == prior["python_report"]["result_sha256"]
        assert current_review(manager, prior["run_id"]) == review
        assert before == private_inventory(root)
    finally:
        manager.close()
    assert before == private_inventory(root)
    return {"saved_review": review, "history": listed, "detail": detail,
            "earlier_actual_acceptance_sha256": sha(prior_path.read_bytes()),
            "existing_actual_scripted_receipt_only": True, "fixture_bytes_modes_unchanged": True,
            "new_workers": 0, "new_checks": 0, "real_model_qualified": False}


def acceptance(jdk, work):
    actual = existing_actual_history(work)
    root = work / "saved-review-history"
    manager, projects, cases = build_history_fixture(root, jdk)
    observations, check_results = {}, {}
    try:
        definitions = {language: copy.deepcopy(manager.projects[project["project_id"]]["definition"])
                       for language, project in projects.items()}
        source_before = {language: private_inventory(project["source"]) for language, project in projects.items()}
        task_before = {language: project["task"].read_bytes() for language, project in projects.items()}
        config_before = manager.config_path.read_bytes()
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented review-history hold", "turn": 1})
        write_new(hold, hold_raw)
        before = private_inventory(root)
        for language, rows in cases.items():
            results = {}
            for label, row in rows.items():
                review = current_review(manager, row["id"])
                assert review["decision"]["state"] == row["expected_state"]
                with saved_history_guard(manager):
                    request = memory_history_http(manager)
                    status, listed = request("/api/saved-review-history", history_pins(review))
                    assert status == 200 and listed["history"]["current"] == review["decision"]["current"]
                    entries = listed["history"]["entries"]
                    assert [entry["name"] for entry in entries] == sorted(entry["name"] for entry in entries)
                    details = []
                    for entry in entries:
                        status, detail = request("/api/saved-review-history-entry", history_pins(review, entry["name"]))
                        assert status == 200
                        selected = detail["history"]["entry"]
                        assert {key: value for key, value in selected.items() if key != "note"} == entry
                        assert "note" not in entry and (selected["note"] is None if entry["status"] != "OK" else True)
                        details.append(detail)
                assert current_review(manager, row["id"]) == review
                if label == "multi":
                    assert [entry["artifact_state"] for entry in entries] == ["MATCHING", "MATCHING", "STALE"]
                    assert review["decision"]["state"] == "STALE" and "\x00\r\n<b>literal</b>" in details[1]["history"]["entry"]["note"]
                if label in {"gapped", "missing"}: assert not listed["history"]["catalog_complete"]
                if label == "formatted":
                    assert entries[0]["artifact_state"] == "MATCHING"
                    assert listed["history"]["current"]["result_sha256"] != review["summary"]["result_sha256"]
                results[label] = {"saved_review": review, "history": listed, "details": details}
            observations[language] = results
        assert before == private_inventory(root)
        config, data = manager.config_path, manager.data; manager.close(); manager = None
        manager = Manager(config, data, jdk)
        for language, rows in cases.items():
            for label, row in rows.items():
                review = current_review(manager, row["id"])
                assert review == observations[language][label]["saved_review"]
                with saved_history_guard(manager):
                    assert manager.saved_review_history(history_pins(review)) == observations[language][label]["history"]
                    for detail in observations[language][label]["details"]:
                        assert manager.saved_review_history_entry(history_pins(review, detail["history"]["entry"]["name"])) == detail
        assert before == private_inventory(root)

        checks_root = work / "saved-review-history-explicit-checks"
        checks_root.mkdir(mode=0o700)
        for language, project in projects.items():
            task = copy.deepcopy(definitions[language]); snapshot = checks_root / language; snapshot.mkdir(mode=0o700)
            for name, expected in task["files"].items():
                raw = (project["source"] / name).read_bytes(); assert sha(raw) == expected
                path = snapshot / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); write_new(path, raw)
            with no_provider_calls(): checked = fixed_checks(snapshot, task, jdk)
            assert checked and all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in checked.values())
            check_results[language] = checked
            assert source_before[language] == private_inventory(project["source"])
            assert task_before[language] == project["task"].read_bytes()
            assert definitions[language] == manager.projects[project["project_id"]]["definition"]
        assert config_before == manager.config_path.read_bytes() and hold.read_bytes() == hold_raw
        assert before == private_inventory(root)
        write_new(work / "saved-review-history-acceptance.json", canonical({
            "invented_histories": observations, "all_history_decisions_seeded": True,
            "separate_actual_selected_copy_checks": check_results, "existing_actual_receipt": actual,
            "current_decision_unchanged": True, "private_bytes_modes_hold_preserved": True,
            "restart_same_pins_and_details": True, "new_agent_workers": 0, "new_model_requests": 0,
        }))
    finally:
        if manager is not None: manager.close()
    return {"saved_review_history_python_java_catalogs_and_notes": True,
            "saved_review_history_no_current_decision_promotion": True,
            "saved_review_history_missing_invalid_limited_partial_records": True,
            "saved_review_history_canonical_raw_relation_and_restart": True,
            "saved_review_history_existing_actual_receipt_without_new_run": True,
            "saved_review_history_separate_actual_fixed_checks": True,
            "saved_review_history_private_bytes_modes_hold_preserved": True,
            "saved_review_history_new_workers": 0, "saved_review_history_model_requests": 0}
