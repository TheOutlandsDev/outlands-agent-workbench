"""Private goal presets plus separate actual Python/Java fixed checks.

The projects and goals are invented. Preset planning never runs checks, Git,
workers, providers or inference; explicit fixed checks below are separate.
"""

import copy
import json

from agent import canonical, sha, write_new
from git_workspace import fixed_checks
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_task_presets_integration import (
    build_presets_manager, close_and_reload, list_request, load_request, preset_guard, preset_path, save_request,
)


def acceptance(jdk, work):
    root = work / "task-presets"
    manager, fixtures = build_presets_manager(root, jdk)
    observations, saved_rows = {}, {}
    try:
        originals = {language: private_hashes(fixture["source"]) for language, fixture in fixtures.items()}
        project_raw = {language: fixture["task"].read_bytes() for language, fixture in fixtures.items()}
        config_raw = manager.config_path.read_bytes()
        # This invented planning hold is new and stays retained throughout QA.
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented task-preset planning hold", "turn": 1})
        write_new(hold, hold_raw)
        for language, fixture in fixtures.items():
            goal = "Review the selected " + language + " arithmetic error handling — café Ω.\nKeep all checks and permissions fixed."
            before = private_hashes(root)
            directory = manager.data / "task-presets" / fixture["project_id"]
            assert not directory.exists()
            with preset_guard(manager):
                listed = manager.task_preset_list(list_request(fixture))
                assert listed["presets"] == []
            assert not directory.exists()
            assert before == private_hashes(root)
            with preset_guard(manager):
                saved = manager.task_preset_save(save_request(listed, "Error handling — café", goal))
                current = manager.task_preset_list(list_request(fixture))
                loaded = manager.task_preset_load(load_request(current))
            path = preset_path(manager, fixture["project_id"], saved["preset"]["id"])
            after = private_hashes(root)
            relative = str(path.relative_to(root))
            assert {name: value for name, value in after.items() if name != relative} == before
            assert loaded["goal"] == goal and loaded["record_sha256"] == sha(path.read_bytes())
            assert "goal" not in current["presets"][0]
            assert hold.read_bytes() == hold_raw
            assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o777 == 0o700
            assert manager.config_path.read_bytes() == config_raw and fixture["task"].read_bytes() == project_raw[language]
            assert private_hashes(fixture["source"]) == originals[language]
            saved_rows[language] = {"list": current, "goal": goal, "record": path, "sha256": sha(path.read_bytes())}
            observations[language] = {"project_id": fixture["project_id"], "preset_id": saved["preset"]["id"],
                                      "binding_sha256": loaded["binding_sha256"], "record_sha256": loaded["record_sha256"]}

        before_restart = private_hashes(root)
        manager = close_and_reload(manager, jdk)
        for language, fixture in fixtures.items():
            with preset_guard(manager):
                listed = manager.task_preset_list(list_request(fixture))
                loaded = manager.task_preset_load(load_request(listed))
            assert listed == saved_rows[language]["list"] and loaded["goal"] == saved_rows[language]["goal"]
            assert sha(saved_rows[language]["record"].read_bytes()) == saved_rows[language]["sha256"]
        assert before_restart == private_hashes(root)

        # Loading did not start a task. These are separate explicit fixed checks,
        # using unchanged scope/check specifications and copies of selected bytes.
        checks_root = work / "task-presets-explicit-checks"
        checks_root.mkdir(mode=0o700)
        for language, fixture in fixtures.items():
            with preset_guard(manager):
                listed = manager.task_preset_list(list_request(fixture))
                loaded = manager.task_preset_load(load_request(listed))
            task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
            original_definition = copy.deepcopy(task)
            task["goal"] = loaded["goal"]
            assert {key: value for key, value in task.items() if key != "goal"} == {
                key: value for key, value in original_definition.items() if key != "goal"}
            snapshot = checks_root / language
            snapshot.mkdir(mode=0o700)
            for name, expected_hash in task["files"].items():
                raw = (fixture["source"] / name).read_bytes()
                assert sha(raw) == expected_hash
                target = snapshot / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                write_new(target, raw)
            before_checks = private_hashes(root)
            with no_provider_calls():
                checks = fixed_checks(snapshot, task, jdk)
            assert checks and all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in checks.values())
            assert before_checks == private_hashes(root)
            observations[language]["separate_fixed_checks"] = checks
            assert private_hashes(fixture["source"]) == originals[language]
            assert fixture["task"].read_bytes() == project_raw[language]
        assert manager.config_path.read_bytes() == config_raw and hold.read_bytes() == hold_raw
        assert all(not any((manager.data / name).iterdir()) for name in ["jobs", "runs", "tasks"])
        write_new(work / "task-presets-acceptance.json", canonical({
            "observations": observations, "fixtures_are_invented": True, "preset_execution_model_git_calls": 0,
            "separate_explicit_fixed_checks": True, "configuration_source_and_task_unchanged": True,
            "restart_persistence": True, "held_planning_allowed_hold_retained": True,
            "only_new_private_preset_files_written": True, "no_agent_run_started": True,
        }))
    finally:
        manager.close()
    return {"task_presets_python_java_private_save_list_load": True,
            "task_presets_restart_persistence": True,
            "task_presets_source_scope_checks_budgets_unchanged": True,
            "task_presets_held_planning_without_runtime_calls": True,
            "task_presets_separate_python_java_fixed_checks_passed": True,
            "task_presets_no_agent_run_started": True,
            "task_presets_model_requests": 0}
