"""Offline saved-only readiness acceptance on invented Python/Java projects."""

import json
from pathlib import Path

from agent import canonical, write_new
from test_project_readiness_integration import install_java_project, private_hashes, saved_only_guard
from workbench import Manager, init_demo


def acceptance(work):
    root = work / "project-readiness"
    root.mkdir(mode=0o700)
    paths = init_demo(root / "workspace", None)
    manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
    observations = {}
    try:
        java_source = install_java_project(root, manager)

        def inspect(label, project, status, reason=None):
            before = private_hashes(root)
            with saved_only_guard(manager):
                result = manager.project_readiness(project)
            assert before == private_hashes(root), "readiness changed private bytes"
            assert result["status"] == status, (label, result["reasons"])
            if reason:
                assert reason in result["reasons"]
            assert len(result["not_checked"]) == 8
            observations[label] = result

        inspect("python_static", "arithmetic", "STATIC_CHECKS_PASSED")
        inspect("java_static", "java", "STATIC_CHECKS_PASSED")
        source = java_source / "sample/Counter.java"
        source.write_bytes(source.read_bytes() + b"// invented source revision\n")
        inspect("java_stale", "java", "REFRESH_REQUIRED", "SOURCE_CHANGED")
        (manager.jdk_home / "bin/javac").unlink()
        inspect("java_missing_compiler", "java", "BLOCKED", "PREREQUISITE_MISSING")
        hold = manager.data / "state/hold.json"
        write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": "invented-held-run", "turn": 1}))
        hold_raw = hold.read_bytes()
        inspect("python_saved_hold", "arithmetic", "BLOCKED", "HOLD_PRESENT")
        assert hold.read_bytes() == hold_raw
        config_raw = manager.config_path.read_bytes()
        manager.config_path.write_bytes(config_raw + b"\n")
        inspect("python_config_drift", "arithmetic", "NEEDS_INSPECTION", "CONFIG_CHANGED")
        assert all(row["status"] == "NOT_CHECKED" for row in observations["python_config_drift"]["files"])
    finally:
        manager.close()
    (work / "project-readiness-acceptance.json").write_text(json.dumps({
        "observations": observations, "saved_bytes_unchanged_per_inspection": True,
        "fixture_hold_retained": True, "records_are_invented": True,
        "readiness_model_requests": 0, "readiness_checks_executed": 0,
    }, indent=2) + "\n")
    return {"readiness_python_java_static_passed": True, "readiness_source_drift_detected": True,
            "readiness_missing_java_compiler_blocked": True, "readiness_saved_hold_retained": True,
            "readiness_config_drift_skips_source": True, "readiness_private_bytes_unchanged": True,
            "readiness_checks_executed": 0, "readiness_model_requests": 0}
