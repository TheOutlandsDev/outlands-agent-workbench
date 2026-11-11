"""Offline advisory project-check acceptance over private invented fixtures."""

import json
from pathlib import Path
from unittest.mock import patch

from agent import Refused, write_new
from test_bundle_project_check_integration import (
    populate_project_check, private_hashes, saved_only_guard, stage_candidate,
)
from workbench import Manager, init_demo


def acceptance(work):
    root = work / "bundle-project-check"
    root.mkdir(mode=0o700)
    paths = init_demo(root / "workspace", None)
    manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
    observations = {}
    try:
        fixtures = populate_project_check(manager, root)
        assert manager.jdk_home is None
        hold = manager.data / "state/hold.json"
        hold_raw = hold.read_bytes()
        # Private input artifacts remain outside the immutable inspection tree.
        for language, fixture in fixtures.items():
            write_new(work / ("invented-" + language + "-project-check.zip"), fixture["bundle_raw"])

        def inspect(label, fixture, status, reason=None):
            before = private_hashes(root)
            with saved_only_guard(manager):
                value = manager.bundle_project_check(fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"])
            assert before == private_hashes(root), "project check changed private bytes"
            assert hold.read_bytes() == hold_raw
            assert value["comparison"]["status"] == status, (label, value["comparison"]["reasons"])
            assert len(value["comparison"]["not_checked"]) == 6
            if reason:
                assert reason in value["comparison"]["reasons"]
            observations[label] = value

        inspect("python_baseline", fixtures["python"], "BASELINE_MATCH")
        inspect("java_baseline", fixtures["java"], "BASELINE_MATCH")
        stage_candidate(manager, fixtures["python"])
        stage_candidate(manager, fixtures["java"])
        inspect("python_candidate", fixtures["python"], "CANDIDATE_MATCH")
        inspect("java_candidate", fixtures["java"], "CANDIDATE_MATCH")
        stage_candidate(manager, fixtures["mixed"], ["addition.py"])
        inspect("python_mixed", fixtures["mixed"], "MIXED_MATCH", "MIXED_BASELINE_CANDIDATE")
        source = fixtures["java"]["source"] / "sample/Sum.java"
        source.write_bytes(source.read_bytes() + b"// intentional unrelated fixture drift\n")
        inspect("java_different", fixtures["java"], "DIFFERENT", "SOURCE_CHANGED")
        protected = fixtures["python"]["source"] / "test_arithmetic.py"
        protected.unlink()
        inspect("python_missing", fixtures["python"], "NEEDS_INSPECTION", "SOURCE_MISSING")

        before_pin = private_hashes(root)
        with saved_only_guard(manager), patch("bundle_project_check.read_selected", side_effect=AssertionError("bad pin read source")):
            try:
                manager.bundle_project_check(fixtures["java"]["project_id"], fixtures["java"]["bundle_raw"], "0" * 64)
            except Refused as exc:
                assert str(exc) == "BUNDLE_CHANGED"
            else:
                raise AssertionError("wrong archive pin was accepted")
        assert before_pin == private_hashes(root)

        manager.config_path.write_bytes(manager.config_raw + b"\n")
        before_drift = private_hashes(root)
        with saved_only_guard(manager), patch("bundle_project_check.read_selected", side_effect=AssertionError("config drift read source")):
            try:
                manager.bundle_project_check(fixtures["java"]["project_id"], fixtures["java"]["bundle_raw"])
            except Refused as exc:
                assert str(exc) == "PROJECT_CHECK_PROJECT_CHANGED"
            else:
                raise AssertionError("external configuration was silently adopted")
        assert before_drift == private_hashes(root)
        assert hold.read_bytes() == hold_raw
    finally:
        manager.close()
    (work / "bundle-project-check-acceptance.json").write_text(json.dumps({
        "observations": observations, "records_are_invented": True,
        "private_bytes_unchanged_per_inspection": True, "unrelated_fixture_hold_retained": True,
        "project_check_checks_executed": 0, "project_check_model_requests": 0,
    }, indent=2) + "\n")
    return {"project_check_python_java_baseline_candidate": True,
            "project_check_mixed_different_missing": True, "project_check_external_pin_refused": True,
            "project_check_config_drift_skips_source": True, "project_check_private_bytes_unchanged": True,
            "project_check_unrelated_hold_retained": True, "project_check_jdk_not_required": True,
            "project_check_checks_executed": 0, "project_check_model_requests": 0}
