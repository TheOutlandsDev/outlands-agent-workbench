"""Invented saved history search/review and separate explicit fixed checks.

Seeded outcomes are synthetic recorded observations. Independent checks below
run copied correct Python/Java projects; neither workflow runs an agent/model.
"""

import copy

from agent import canonical, sha, write_new
from git_workspace import fixed_checks
from test_bundle_workspace_integration import no_provider_calls
from test_run_comparison_integration import private_hashes, saved_only_guard, seed_saved_run
from test_run_history_integration import history_guard, history_request, open_request
from test_task_presets_integration import build_presets_manager
from workbench import Manager


def acceptance(jdk, work):
    root = work / "run-history"
    manager, fixtures = build_presets_manager(root, jdk)
    ids = {"python": ("1" * 16, "2" * 16), "java": ("5" * 16, "6" * 16)}
    observations, handoffs = {}, {}
    try:
        original_sources = {language: private_hashes(fixture["source"]) for language, fixture in fixtures.items()}
        original_tasks = {language: fixture["task"].read_bytes() for language, fixture in fixtures.items()}
        original_config = manager.config_path.read_bytes()
        definitions = {language: copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
                       for language, fixture in fixtures.items()}
        for language, fixture in fixtures.items():
            task = copy.deepcopy(definitions[language])
            task["goal"] = "Invented " + language + " saved task " + "x" * 240 + " END-" + language + " café e\u0301 🧪 <b>literal</b>"
            for number, (run_id, state) in enumerate(zip(ids[language], ["REVIEW_READY", "FAILED"])):
                seed_saved_run(manager, run_id, task, project=fixture["project_id"],
                               project_name="Invented " + language + " history", state=state, created=100 + number)
        uncertain = "3" * 16
        seed_saved_run(manager, uncertain, definitions["python"], project=fixtures["python"]["project_id"],
                       state="UNCERTAIN", reason="PROVIDER_HEADER_TIMEOUT", created=103)
        write_new(manager.meta_path("9" * 16), canonical({"private_extra": "invented legacy metadata", "state": "FUTURE_UNKNOWN"}))
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented history planning hold", "turn": 1})
        write_new(hold, hold_raw)
        before = private_hashes(root)
        for language, fixture in fixtures.items():
            with history_guard(manager):
                search = manager.run_history_search(history_request("END-" + language, fixture["project_id"], ""))
                assert search["matched"] == search["returned"] == 2
                assert all("END-" + language in row["goal_excerpt"] for row in search["runs"])
                assert all(row["goal_truncated"] for row in search["runs"])
                filtered = manager.run_history_search(history_request("END-" + language, fixture["project_id"], "FAILED"))
                assert filtered["matched"] == filtered["returned"] == 1
                assert filtered["runs"][0]["id"] == ids[language][1]
                reviewed = {row["id"]: manager.run_history_open(open_request(search, row)) for row in search["runs"]}
                assert all("<b>literal</b>" in row["goal"] and len(row["goal"]) > 160 for row in reviewed.values())
                # Handoff pins are explicitly reviewed IDs only. Existing
                # comparison is called separately below, never by search/open.
                handoffs[language] = {"left": reviewed[ids[language][0]]["id"], "right": reviewed[ids[language][1]]["id"]}
            assert before == private_hashes(root)
            observations[language] = {"search": search, "filtered": filtered, "reviewed": reviewed,
                                      "handoff": handoffs[language]}
        with history_guard(manager):
            unknown = manager.run_history_search(history_request("", "UNKNOWN", "UNKNOWN"))
            no_match = manager.run_history_search(history_request("invented-no-such-literal"))
            all_rows = manager.run_history_search(history_request())
            assert unknown["returned"] == 1 and unknown["runs"][0]["id"] == "9" * 16
            assert no_match["returned"] == no_match["matched"] == 0
            assert all_rows["returned"] == 6
            assert next(row for row in all_rows["runs"] if row["id"] == uncertain)["state"] == "UNCERTAIN"
        assert before == private_hashes(root)

        # Explicit Compare can inspect saved task/result/event/diff evidence.
        # Those fields are synthetic seeded observations, never actual runs.
        with saved_only_guard(manager):
            comparisons = {language: manager.compare(pair["left"], pair["right"]) for language, pair in handoffs.items()}
        assert all(value["comparable"] for value in comparisons.values())
        assert all(value["left"]["result_status"] == "REVIEW_READY" and value["right"]["result_status"] == "FAILED"
                   for value in comparisons.values())
        assert before == private_hashes(root)
        config, data = manager.config_path, manager.data
        manager.close()
        manager = None
        manager = Manager(config, data, jdk)
        with history_guard(manager):
            after = manager.run_history_search(history_request())
            assert after == all_rows
            for language, fixture in fixtures.items():
                searched = manager.run_history_search(history_request("END-" + language, fixture["project_id"], ""))
                assert searched == observations[language]["search"]
                for row in searched["runs"]:
                    assert manager.run_history_open(open_request(searched, row)) == observations[language]["reviewed"][row["id"]]
        assert before == private_hashes(root)

        checks_root = work / "run-history-explicit-checks"
        checks_root.mkdir(mode=0o700)
        for language, fixture in fixtures.items():
            task = copy.deepcopy(definitions[language])
            task["goal"] = observations[language]["reviewed"][ids[language][0]]["goal"]
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
            with no_provider_calls():
                checked = fixed_checks(snapshot, task, jdk)
            assert checked and all(value["exit_code"] == 0 and value["tests_ran"] > 0 and not any(value[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for value in checked.values())
            observations[language]["separate_actual_fixed_checks"] = checked
            assert private_hashes(fixture["source"]) == original_sources[language]
            assert fixture["task"].read_bytes() == original_tasks[language]
            assert manager.projects[fixture["project_id"]]["definition"] == definitions[language]
        assert manager.config_path.read_bytes() == original_config and hold.read_bytes() == hold_raw
        assert before == private_hashes(root)
        write_new(work / "run-history-acceptance.json", canonical({
            "observations": observations, "explicit_comparisons_of_seeded_observations": comparisons,
            "unknown": unknown, "no_match": no_match, "all": all_rows,
            "all_saved_outcomes_seeded_not_executed": True, "search_open_and_handoff_read_only": True,
            "comparison_explicit_and_separate": True, "restart_persistent": True,
            "separate_actual_fixed_checks_on_copies": True, "all_private_bytes_and_hold_unchanged": True,
            "agent_runs": 0, "model_requests": 0,
        }))
    finally:
        if manager is not None: manager.close()
    return {"run_history_python_java_search_review_handoff": True,
            "run_history_explicit_compare_separate": True, "run_history_seeded_outcomes_not_live_acceptance": True,
            "run_history_full_goal_queries_filters_unknown_and_no_match": True,
            "run_history_restart_persistence": True, "run_history_private_bytes_and_hold_unchanged": True,
            "run_history_separate_actual_python_java_fixed_checks_passed": True,
            "run_history_agent_runs": 0, "run_history_model_requests": 0}
