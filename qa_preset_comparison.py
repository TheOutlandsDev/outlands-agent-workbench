"""Invented private preview acceptance plus separate explicit fixed checks.

Preview returns comparison data without assigning Task. An explicit Load call
is exercised separately; neither operation starts an agent or inference.
"""

import copy

from agent import canonical, sha, write_new
from git_workspace import fixed_checks
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_preset_comparison_integration import preview_request
from test_task_presets_integration import (
    build_presets_manager, close_and_reload, list_request, load_request, preset_guard, preset_path, save_request,
)


def acceptance(jdk, work):
    root = work / "preset-comparison"
    manager, fixtures = build_presets_manager(root, jdk)
    observations, saved = {}, {}
    try:
        source_hashes = {language: private_hashes(fixture["source"]) for language, fixture in fixtures.items()}
        task_bytes = {language: fixture["task"].read_bytes() for language, fixture in fixtures.items()}
        config_bytes = manager.config_path.read_bytes()
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented preset comparison planning hold", "turn": 1})
        write_new(hold, hold_raw)
        for language, fixture in fixtures.items():
            goal = "Review the selected " + language + " error handling — café Ω.\r\nPreserve selected checks."
            draft = "Consider the current " + language + " arithmetic draft — 🧪.\nKeep Task unchanged during preview."
            directory = manager.data / "task-presets" / fixture["project_id"]
            assert not directory.exists()
            with preset_guard(manager):
                listed = manager.task_preset_list(list_request(fixture))
                result = manager.task_preset_save(save_request(listed, "Compare private " + language, goal))
                listed = manager.task_preset_list(list_request(fixture))
            path = preset_path(manager, fixture["project_id"], result["preset"]["id"])
            record_hash = sha(path.read_bytes())
            definition = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
            before_preview = private_hashes(root)
            with preset_guard(manager):
                preview = manager.task_preset_preview(preview_request(listed, draft))
            comparison = preview["comparison"]
            assert comparison["draft_goal"] == draft and comparison["saved_goal"] == goal
            assert comparison["draft_sha256"] == sha(draft.encode()) and comparison["saved_sha256"] == sha(goal.encode())
            assert not comparison["identical"] and "goal" not in preview
            assert len(canonical(preview)) <= 65536
            assert before_preview == private_hashes(root)
            assert definition == manager.projects[fixture["project_id"]]["definition"]
            # This separate explicit Load returns text; it also does not assign
            # Task or start a task. Backend preview may reuse its pinned reader.
            with preset_guard(manager):
                loaded = manager.task_preset_load(load_request(listed))
            assert loaded["goal"] == goal and "comparison" not in loaded
            assert before_preview == private_hashes(root)
            assert definition == manager.projects[fixture["project_id"]]["definition"]
            assert sha(path.read_bytes()) == record_hash and hold.read_bytes() == hold_raw
            saved[language] = {"list": listed, "draft": draft, "goal": goal, "preview": preview,
                               "record": path, "record_sha256": record_hash}
            observations[language] = {"project_id": fixture["project_id"], "preview": preview,
                                      "task_assignment_occurred": False, "explicit_load_separate": True}

        before_restart = private_hashes(root)
        manager = close_and_reload(manager, jdk)
        for language, fixture in fixtures.items():
            with preset_guard(manager):
                listed = manager.task_preset_list(list_request(fixture))
                preview = manager.task_preset_preview(preview_request(listed, saved[language]["draft"]))
            assert listed == saved[language]["list"] and preview == saved[language]["preview"]
            assert sha(saved[language]["record"].read_bytes()) == saved[language]["record_sha256"]
        assert before_restart == private_hashes(root)

        # These explicit checks are independent of preview and run only copied
        # selected bytes with the same scope/checks/budgets and loaded goal.
        checks_root = work / "preset-comparison-explicit-checks"
        checks_root.mkdir(mode=0o700)
        for language, fixture in fixtures.items():
            with preset_guard(manager):
                listed = manager.task_preset_list(list_request(fixture))
                loaded = manager.task_preset_load(load_request(listed))
            definition = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
            task = copy.deepcopy(definition)
            task["goal"] = loaded["goal"]
            assert {key: value for key, value in task.items() if key != "goal"} == {
                key: value for key, value in definition.items() if key != "goal"}
            snapshot = checks_root / language
            snapshot.mkdir(mode=0o700)
            for name, expected in task["files"].items():
                raw = (fixture["source"] / name).read_bytes()
                assert sha(raw) == expected
                target = snapshot / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                write_new(target, raw)
            before_checks = private_hashes(root)
            with no_provider_calls():
                checks = fixed_checks(snapshot, task, jdk)
            assert checks and all(result["exit_code"] == 0 and result["tests_ran"] > 0 and not any(result[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for result in checks.values())
            assert before_checks == private_hashes(root)
            assert private_hashes(fixture["source"]) == source_hashes[language]
            assert fixture["task"].read_bytes() == task_bytes[language]
            assert manager.projects[fixture["project_id"]]["definition"] == definition
            observations[language]["separate_fixed_checks"] = checks
        assert manager.config_path.read_bytes() == config_bytes and hold.read_bytes() == hold_raw
        assert all(not any((manager.data / name).iterdir()) for name in ["jobs", "runs", "tasks"])
        write_new(work / "preset-comparison-acceptance.json", canonical({
            "observations": observations, "fixtures_are_invented": True, "preview_task_assignment_occurred": False,
            "configuration_source_tasks_records_unchanged_by_preview": True, "explicit_load_separate": True,
            "restart_preview_identical": True, "unrelated_hold_retained": True,
            "separate_explicit_fixed_checks": True, "agent_runs": 0, "model_requests": 0,
        }))
    finally:
        manager.close()
    return {"preset_comparison_python_java_private_preview": True,
            "preset_comparison_exact_draft_and_saved_hashes": True,
            "preset_comparison_no_task_assignment_or_preview_writes": True,
            "preset_comparison_explicit_load_separate": True,
            "preset_comparison_restart_persistence": True,
            "preset_comparison_held_planning_hold_retained": True,
            "preset_comparison_separate_python_java_fixed_checks_passed": True,
            "preset_comparison_agent_runs": 0, "preset_comparison_model_requests": 0}
