"""Private actual-check fixtures and zero-execution snapshot/project observations."""

import json

from agent import canonical, sha, write_new
from qa_bundle_workspace import _assert_source_git, _manager, _source_git
from qa_workspace_recheck import _create_initial, _wait_recheck
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_snapshot_project_check_integration import saved_only_guard, stage_tested
from test_workspace_recheck_integration import manual_comment, recheck_preview_guard, recheck_request


def acceptance(jdk, work):
    from snapshot_export import prepare
    root = work / "snapshot-project-check"
    manager, projects = _manager(root, jdk)
    observations, fixtures = {}, {}
    try:
        originals = {language: _source_git(manager, projects[language]) for language in ["python", "java", "mixed"]}
        builder_before = private_hashes(root / "bundle-builder")
        for language in ["python", "java", "mixed"]:
            fixture = _create_initial(manager, projects[language])
            manual_comment(fixture, language)
            creation_before = private_hashes(fixture["job_dir"])
            with recheck_preview_guard(manager):
                preview = manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
            with no_provider_calls():
                started = manager.recheck_start(recheck_request(preview))
                receipt = _wait_recheck(manager, started["id"])
            assert receipt["status"] == "VERIFIED"
            assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 for row in receipt["checks"].values())
            assert creation_before == private_hashes(fixture["job_dir"])
            fixture.update(attempt_id=receipt["id"], attempt_dir=manager.data / "workspace-rechecks" / receipt["id"])
            packet = prepare(fixture["attempt_dir"])["archive"]
            fixture.update(archive_raw=packet, archive_sha256=sha(packet))
            fixtures[language] = fixture
            # Private ZIPs stay outside the immutable inspection tree.
            write_new(work / ("invented-" + language + "-snapshot-project-check.zip"), packet)
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented unrelated snapshot-project hold", "turn": 1})
        write_new(hold, hold_raw)
        manager.jdk_home = None  # Only recorded packet observations follow, never new checks.
        records_before = private_hashes(manager.data)
        git_before = {language: private_hashes(fixture["source"] / ".git") for language, fixture in fixtures.items()}

        def inspect(label, fixture, status, reconstruction):
            before = private_hashes(root)
            with saved_only_guard(manager):
                value = manager.snapshot_project_check(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
            assert before == private_hashes(root), "snapshot project check changed saved bytes"
            assert value["comparison"]["status"] == status, (label, value["comparison"])
            assert value["comparison"]["reconstruction"]["status"] == reconstruction
            assert value["config_sha256"] == sha(manager.config_raw)
            assert value["task_sha256"] == sha(manager.projects[fixture["project_id"]]["task_raw"])
            assert hold.read_bytes() == hold_raw
            observations[label] = value

        for language in ["python", "java", "mixed"]:
            inspect(language + "_baseline", fixtures[language], "BASELINE_MATCH", "VERIFIED")
            _assert_source_git(projects[language], originals[language])
        stage_tested(fixtures["python"])
        stage_tested(fixtures["java"])
        inspect("python_tested", fixtures["python"], "TESTED_MATCH", "NOT_CHECKED")
        inspect("java_tested", fixtures["java"], "TESTED_MATCH", "NOT_CHECKED")
        stage_tested(fixtures["mixed"], ["addition.py"])
        inspect("mixed", fixtures["mixed"], "MIXED_MATCH", "NOT_CHECKED")
        path = fixtures["java"]["source"] / "sample/Sum.java"
        path.write_bytes(path.read_bytes() + b"// intentional different fixture source\n")
        inspect("different", fixtures["java"], "DIFFERENT", "NOT_CHECKED")
        (fixtures["python"]["source"] / "test_arithmetic.py").unlink()
        inspect("missing", fixtures["python"], "NEEDS_INSPECTION", "NOT_CHECKED")
        assert records_before == private_hashes(manager.data)
        assert all(git_before[language] == private_hashes(fixture["source"] / ".git") for language, fixture in fixtures.items())
        assert builder_before == private_hashes(root / "bundle-builder")
        assert hold.read_bytes() == hold_raw
    finally:
        manager.close()
    (work / "snapshot-project-check-acceptance.json").write_text(json.dumps({"observations": observations,
        "fixtures_are_invented": True, "actual_initial_and_recheck_checks": True,
        "forward_baseline_reconstruction_verified": True, "tested_and_mixed_have_no_reverse_proof": True,
        "private_bytes_unchanged_per_inspection": True, "old_records_workspaces_snapshots_git_and_holds_unchanged": True,
        "source_mutations_only_between_inspections": True, "inspector_jdk_not_required": True,
        "snapshot_project_checks_executed": 0, "snapshot_project_model_requests": 0}, indent=2) + "\n")
    return {"snapshot_project_python_java_baseline_tested": True, "snapshot_project_forward_reconstruction": True,
            "snapshot_project_mixed_different_missing": True, "snapshot_project_private_bytes_unchanged": True,
            "snapshot_project_unrelated_hold_retained": True, "snapshot_project_jdk_not_required": True,
            "snapshot_project_checks_executed": 0, "snapshot_project_model_requests": 0}
