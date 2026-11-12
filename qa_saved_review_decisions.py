"""Seeded decisions, separate fixed checks and an existing actual receipt.

This acceptance never starts an agent. The actual accepted Python receipt must
already exist from the earlier offline workflow; absent evidence is not rerun.
"""

import copy
import json

from agent import Refused, canonical, sha, write_new
from git_workspace import fixed_checks
from test_bundle_workspace_integration import no_provider_calls
from test_saved_run_review_integration import private_inventory, review_guard, selected_request
from test_saved_review_decisions_integration import build_decision_fixture, memory_review_http
from workbench import Manager


def existing_actual_decision(work):
    root = work / "offline-workflow"
    receipt_path = work / "offline-workflow-acceptance.json"
    if not root.is_dir() or not receipt_path.is_file():
        raise Refused("SAVED_REVIEW_NOT_FOUND")
    prior = json.loads(receipt_path.read_bytes())
    if (prior.get("scripted_python_agent_run") is not True or prior.get("real_model_qualified") is not False
            or prior.get("python_report", {}).get("accepted") is not True):
        raise Refused("SAVED_REVIEW_RECORD_INVALID")
    run_id = prior["run_id"]
    before = private_inventory(root)
    manager = Manager(root / "workspace/config.json", root / "workspace/data")
    try:
        with review_guard(manager):
            request = selected_request(manager, run_id)
            status, value = memory_review_http(manager)(request)
            assert status == 200 and value["version"] == 2
            decision = value["decision"]
            assert decision["state"] == "ACCEPTED" and decision["catalog_complete"]
            assert decision["current"]["result_sha256"] == prior["python_report"]["result_sha256"]
            assert decision["current"]["patch_sha256"] == prior["python_report"]["patch_sha256"]
            assert decision["receipt"]["verdict"] == "accepted" and decision["receipt"]["name"] == "review-000.json"
        assert before == private_inventory(root)
    finally:
        manager.close()
    assert before == private_inventory(root)
    return {"review": value, "prior_actual_report_sha256": sha(receipt_path.read_bytes()),
            "existing_completed_actual_scripted_receipt": True, "new_worker_starts": 0, "new_checks": 0,
            "all_prior_actual_fixture_bytes_modes_unchanged": True, "real_model_qualified": False}


def acceptance(jdk, work):
    actual = existing_actual_decision(work)
    root = work / "saved-review-decisions"
    manager, fixtures, cases = build_decision_fixture(root, jdk)
    observations, check_results = {}, {}
    try:
        definitions = {language: copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
                       for language, fixture in fixtures.items()}
        source_before = {language: private_inventory(fixture["source"]) for language, fixture in fixtures.items()}
        task_before = {language: fixture["task"].read_bytes() for language, fixture in fixtures.items()}
        config_before = manager.config_path.read_bytes()
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented saved-decision planning hold", "turn": 1})
        write_new(hold, hold_raw)
        before = private_inventory(root)
        with review_guard(manager):
            for language, rows in cases.items():
                observed = {}
                for label, row in rows.items():
                    request = selected_request(manager, row["id"])
                    status, value = memory_review_http(manager)(request)
                    assert status == 200 and value["version"] == 2
                    assert value["decision"]["state"] == row["expected_state"]
                    if label == "unknown": assert value["decision"]["receipt"] is None
                    if label == "formatted":
                        assert value["decision"]["current"]["result_sha256"] != value["summary"]["result_sha256"]
                        assert value["decision"]["current"]["result_sha256"] == value["decision"]["receipt"]["result_sha256"]
                    observed[label] = value
                observations[language] = observed
        assert before == private_inventory(root)
        config, data = manager.config_path, manager.data
        manager.close(); manager = None
        manager = Manager(config, data, jdk)
        with review_guard(manager):
            for language, rows in cases.items():
                for label, row in rows.items():
                    value = manager.run_history_review(selected_request(manager, row["id"]))
                    assert value == observations[language][label]
        assert before == private_inventory(root)

        # Actual checks are independent of the seeded review/outcome records.
        checks_root = work / "saved-review-decisions-explicit-checks"
        checks_root.mkdir(mode=0o700)
        for language, fixture in fixtures.items():
            task = copy.deepcopy(definitions[language])
            snapshot = checks_root / language
            snapshot.mkdir(mode=0o700)
            for name, expected in task["files"].items():
                raw = (fixture["source"] / name).read_bytes(); assert sha(raw) == expected
                path = snapshot / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); write_new(path, raw)
            with no_provider_calls(): checked = fixed_checks(snapshot, task, jdk)
            assert checked and all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in checked.values())
            check_results[language] = checked
            assert source_before[language] == private_inventory(fixture["source"])
            assert task_before[language] == fixture["task"].read_bytes()
            assert definitions[language] == manager.projects[fixture["project_id"]]["definition"]
        assert config_before == manager.config_path.read_bytes() and hold.read_bytes() == hold_raw
        assert before == private_inventory(root)
        write_new(work / "saved-review-decisions-acceptance.json", canonical({
            "seeded_decision_histories": observations, "all_seeded_decisions_are_invented": True,
            "separate_actual_fixed_checks": check_results, "existing_actual_scripted_receipt": actual,
            "seeded_private_bytes_modes_hold_unchanged": True, "restart_decisions_identical": True,
            "new_agent_starts": 0, "new_inference_requests": 0,
        }))
    finally:
        if manager is not None: manager.close()
    return {"saved_review_decisions_python_java_five_states": True,
            "saved_review_decisions_canonical_raw_hashes_distinct": True,
            "saved_review_decisions_invalid_latest_no_fallback": True,
            "saved_review_decisions_readonly_hold_restart_preserved": True,
            "saved_review_decisions_existing_actual_accepted_receipt_without_rerun": True,
            "saved_review_decisions_separate_actual_fixed_checks_passed": True,
            "saved_review_decisions_new_agent_starts": 0, "saved_review_decisions_new_model_requests": 0}
