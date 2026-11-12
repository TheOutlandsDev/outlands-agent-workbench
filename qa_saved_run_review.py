"""Invented saved evidence review and independent Python/Java fixed checks.

Saved outcomes below are seeded historical observations. Actual fixed checks
run separate copied selected projects; neither workflow runs an agent/model.
"""

import copy

from agent import canonical, sha, write_new
from git_workspace import fixed_checks
from test_bundle_workspace_integration import no_provider_calls
from test_run_comparison_integration import saved_only_guard
from test_run_history_integration import history_request
from test_saved_run_review_integration import populate_review_histories, private_inventory, review_guard, selected_request
from test_task_presets_integration import build_presets_manager
from workbench import Manager


def acceptance(jdk, work):
    root = work / "saved-run-review"
    manager, fixtures = build_presets_manager(root, jdk)
    observations, comparisons = {}, {}
    try:
        original_sources = {language: private_inventory(fixture["source"]) for language, fixture in fixtures.items()}
        original_tasks = {language: fixture["task"].read_bytes() for language, fixture in fixtures.items()}
        original_config = manager.config_path.read_bytes()
        definitions = {language: copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
                       for language, fixture in fixtures.items()}
        ids = populate_review_histories(manager, fixtures)
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented saved-review planning hold", "turn": 1})
        write_new(hold, hold_raw)
        before = private_inventory(root)
        with review_guard(manager):
            for name, run_id in ids.items():
                request = selected_request(manager, run_id)
                value = manager.run_history_review(request)
                assert {key: value[key] for key in request} == request
                assert len(canonical(value)) <= 65536
                assert "state" not in value["diagnostics"] and "hold" not in value["diagnostics"]
                observations[name] = {"request": request, "review": value}
            for language, fixture in fixtures.items():
                searched = manager.run_history_search(history_request("SAVED-" + language, fixture["project_id"], ""))
                assert searched["matched"] >= 2
                assert all("SAVED-" + language in row["goal_excerpt"] for row in searched["runs"])
        assert before == private_inventory(root)
        assert observations["python_ok"]["review"]["summary"]["result_status"] == "REVIEW_READY"
        assert observations["java_ok"]["review"]["summary"]["result_status"] == "REVIEW_READY"
        assert observations["python_failed"]["review"]["summary"]["result_status"] == "FAILED"
        assert observations["java_failed"]["review"]["summary"]["result_status"] == "FAILED"
        assert observations["uncertain"]["review"]["summary"]["state"] == "UNCERTAIN"
        assert observations["uncertain"]["review"]["diagnostics"]["provider_completion"] == "UNKNOWN"
        assert observations["running"]["review"]["summary"]["state"] == "RUNNING"
        assert observations["running"]["review"]["diagnostics"]["provider_completion"] == "UNKNOWN"
        assert observations["legacy"]["review"]["summary"]["task_integrity"] == "NOT_RECORDED"
        assert observations["legacy"]["review"]["diagnostics"]["legacy"]
        assert observations["corrupt"]["review"]["summary"]["task_integrity"] == "UNAVAILABLE"
        assert "RECORD_INVALID" in observations["corrupt"]["review"]["summary"]["notes"]
        assert observations["unknown"]["review"]["diagnostics"]["budget"] == {
            "used": None, "limit": None, "per_request_seconds": None}

        # Existing Compare is an independent explicit action; these outcomes and
        # check observations were seeded, not produced by an agent/model run.
        with saved_only_guard(manager):
            for language in ["python", "java"]:
                comparison = manager.compare(ids[language + "_ok"], ids[language + "_failed"])
                assert comparison["comparable"]
                assert comparison["left"] == observations[language + "_ok"]["review"]["summary"]
                assert comparison["right"] == observations[language + "_failed"]["review"]["summary"]
                comparisons[language] = comparison
        assert before == private_inventory(root)
        config, data = manager.config_path, manager.data
        manager.close(); manager = None
        manager = Manager(config, data, jdk)
        with review_guard(manager):
            for name, run_id in ids.items():
                request = selected_request(manager, run_id)
                assert request == observations[name]["request"]
                assert manager.run_history_review(request) == observations[name]["review"]
        assert before == private_inventory(root)

        # Actual checks below use only copies of unchanged approved selected
        # bytes. They are distinct from the seeded saved check observations.
        checks_root = work / "saved-run-review-explicit-checks"
        checks_root.mkdir(mode=0o700)
        checks_observations = {}
        for language, fixture in fixtures.items():
            task = copy.deepcopy(definitions[language])
            task["goal"] = observations[language + "_ok"]["review"]["summary"]["goal"]
            assert {key: value for key, value in task.items() if key != "goal"} == {
                key: value for key, value in definitions[language].items() if key != "goal"}
            snapshot = checks_root / language
            snapshot.mkdir(mode=0o700)
            for name, expected in task["files"].items():
                raw = (fixture["source"] / name).read_bytes()
                assert sha(raw) == expected
                target = snapshot / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                write_new(target, raw)
            with no_provider_calls(): checked = fixed_checks(snapshot, task, jdk)
            assert checked and all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in checked.values())
            checks_observations[language] = checked
            assert private_inventory(fixture["source"]) == original_sources[language]
            assert fixture["task"].read_bytes() == original_tasks[language]
            assert manager.projects[fixture["project_id"]]["definition"] == definitions[language]
        assert manager.config_path.read_bytes() == original_config and hold.read_bytes() == hold_raw
        assert before == private_inventory(root)
        write_new(work / "saved-run-review-acceptance.json", canonical({
            "observations": observations, "separate_explicit_comparisons": comparisons,
            "separate_actual_fixed_checks_on_copies": checks_observations,
            "saved_outcomes_seeded_not_executed": True, "no_live_state_or_task_assignment": True,
            "all_private_bytes_modes_and_hold_unchanged": True, "restart_exact_pins_and_review": True,
            "agent_runs": 0, "model_requests": 0,
        }))
    finally:
        if manager is not None: manager.close()
    return {"saved_run_review_python_java_scope_checks_results_diagnostics_patch": True,
            "saved_run_review_failed_uncertain_running_legacy_corrupt_unknown_retained": True,
            "saved_run_review_existing_compare_separate_and_consistent": True,
            "saved_run_review_exact_restart_pins": True,
            "saved_run_review_private_bytes_modes_hold_and_task_unchanged": True,
            "saved_run_review_separate_actual_python_java_fixed_checks_passed": True,
            "saved_run_review_agent_runs": 0, "saved_run_review_model_requests": 0}
