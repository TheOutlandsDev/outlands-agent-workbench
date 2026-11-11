"""Offline refresh acceptance on invented Python/Java files; no inference."""

import copy
import json
import shutil
from pathlib import Path

from agent import Refused, canonical, sha, write_new
from isolation import check as python_check
from java_check import check as java_check
from project_setup import prepare
from workbench import Manager


def acceptance(jdk, work):
    here = Path(__file__).resolve().parent
    root = work / "project-refresh"
    root.mkdir(mode=0o700)
    projects, definitions, originals = [], {}, {}
    specs = [
        ("python", "python_manifest", ["manifest_guard.py", "test_manifest_guard.py"],
         "manifest_guard.py", "test_manifest_guard.py",
         b"actual.startswith(expected_digest)", b"actual == expected_digest"),
        ("java", "java_selection", ["selection/SelectionOrder.java", "selection/SelectionOrderTest.java"],
         "selection/SelectionOrder.java", "selection.SelectionOrderTest",
         b"new TreeSet<>(values)", b"new LinkedHashSet<>(values)"),
    ]
    for language, fixture, files, editable, check_name, _, _ in specs:
        source = root / language
        shutil.copytree(here / "examples" / fixture, source)
        request = {"id": language, "name": "Invented " + language, "source": str(source),
                   "language": language, "files": files, "editable": [editable],
                   "check": check_name, "goal": "Check this invented fixture."}
        _, task, _ = prepare(request, True)
        task_path = root / (language + "-initial.json")
        write_new(task_path, canonical(task))
        originals[language] = task_path.read_bytes()
        definitions[language] = task
        projects.append({"id": language, "name": request["name"], "source": str(source), "task": str(task_path)})
    config, data = root / "config.json", root / "data"
    write_new(config, canonical({"format": "outlands-workbench-config-v1", "projects": projects, "models": []}))
    manager = Manager(config, data, jdk)
    observations = {}
    try:
        for language, _, _, editable, _, old, new in specs:
            project = manager.projects[language]
            task = copy.deepcopy(project["definition"])
            spec = task["checks"]["unit"]
            def run_check():
                return (python_check(project["source"], spec["pattern"], 10)
                        if language == "python" else java_check(project["source"], spec, 10, jdk))
            baseline = run_check()
            assert baseline["exit_code"] != 0 and baseline["tests_ran"] > 0 and not baseline["infrastructure_error"]
            protected = {n: (project["source"] / n).read_bytes() for n in task["files"] if n not in task["editable"]}
            path = project["source"] / editable
            raw = path.read_bytes()
            assert raw.count(old) == 1
            path.write_bytes(raw.replace(old, new))
            preview = manager.project_refresh_preview({"project": language, "goal": "Verify the corrected invented fixture."})
            assert preview["files_changed"] == 1 and preview["goal_changed"]
            saved = manager.project_refresh_save({"draft": preview["draft"]})
            active = manager.projects[language]["definition"]
            assert active["files"][editable] == sha(path.read_bytes())
            assert all(active[k] == task[k] for k in ["format", "editable", "checks", "max_turns", "request_seconds"])
            final = run_check()
            assert final["exit_code"] == 0 and final["tests_ran"] > 0
            assert all((project["source"] / n).read_bytes() == raw for n, raw in protected.items())
            assert (root / (language + "-initial.json")).read_bytes() == originals[language]
            first_task_path = manager.projects[language]["task"]
            first_task_raw = first_task_path.read_bytes()
            second = manager.project_refresh_preview({"project": language, "goal": "Inspect the same selected files again."})
            assert second["files_changed"] == 0 and second["goal_changed"]
            manager.project_refresh_save({"draft": second["draft"]})
            assert first_task_path.read_bytes() == first_task_raw
            history = manager.project_revisions(language)
            assert len(history["revisions"]) == 2 and history["revisions"][0]["current"]
            assert history["revisions"][1]["id"] == saved["revision"]
            observations[language] = {"baseline": baseline, "final": final, "saved_revisions": 2,
                                      "scope_preserved": True, "protected_files_unchanged": True,
                                      "prior_task_definitions_unchanged": True}
        manager.close()
        manager = Manager(config, data, jdk)
        assert all(len(manager.project_revisions(language)["revisions"]) == 2 for language in observations)
        source = manager.projects["python"]["source"] / "manifest_guard.py"
        source.write_bytes(source.read_bytes() + b"\n# invented first change\n")
        preview = manager.project_refresh_preview({"project": "python", "goal": "Review changed selected source."})
        config_raw = config.read_bytes()
        source.write_bytes(source.read_bytes() + b"# invented later change\n")
        try:
            manager.project_refresh_save({"draft": preview["draft"]})
        except Refused as exc:
            assert str(exc) == "REFRESH_SOURCE_CHANGED"
        else:
            raise AssertionError("stale refresh accepted")
        assert config.read_bytes() == config_raw and manager.history() == []
        assert not (data / "state/hold.json").exists()
    finally:
        manager.close()
    (work / "project-refresh-acceptance.json").write_text(json.dumps(observations, indent=2) + "\n")
    return {"refresh_python_baseline_failed": True, "refresh_python_final_passed": True,
            "refresh_java_baseline_failed": True, "refresh_java_final_passed": True,
            "refresh_revisions_restart_verified": True, "refresh_stale_save_refused": True,
            "refresh_scope_and_protected_files_preserved": True, "refresh_model_requests": 0}
