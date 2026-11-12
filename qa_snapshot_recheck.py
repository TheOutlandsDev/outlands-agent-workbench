"""Actual isolated rechecks over manually edited, private invented worktrees."""

import copy
import json
import time
from pathlib import Path

from agent import Refused, canonical, sha
from qa_bundle_workspace import _assert_source_git, _invented_bundle, _manager, _source_git, _wait
from test_bundle_workspace_integration import create_request, no_provider_calls, preview_guard, private_hashes
from test_snapshot_recheck_integration import manual_comment, recheck_preview_guard, recheck_request
from qa_snapshot_workspace import _actual_packet, _wait as wait_snapshot_workspace
from test_snapshot_workspace_integration import preview_guard as snapshot_preview_guard


def _create_initial(manager, fixture):
    packet = _actual_packet(manager, fixture, "java" if any(isinstance(spec, dict) and spec.get("kind") == "java-main" for spec in manager.projects[fixture["project_id"]]["definition"]["checks"].values()) else "python")
    with snapshot_preview_guard(manager):
        preview = manager.snapshot_workspace_preview(packet["project_id"], packet["archive_raw"], packet["archive_sha256"])
    with no_provider_calls():
        started = manager.snapshot_workspace_create(create_request(preview))
        creation = wait_snapshot_workspace(manager, started["id"])
    assert creation["status"] == "VERIFIED"
    job = manager.data / "snapshot-workspaces" / creation["id"]
    return {**packet, "workspace_id": creation["id"], "job_dir": job,
            "workspace": Path(creation["path"]), "creation_sha256": sha((job / "receipt.json").read_bytes())}


def _wait_recheck(manager, attempt_id):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = manager.snapshot_recheck_view(attempt_id)
        if value["status"] != "PREPARING" and not value["owned_active"]:
            return value
        time.sleep(0.05)
    raise AssertionError("owned workspace recheck did not finish within qualification deadline")


def acceptance(jdk, work):
    root = work / "snapshot-workspace-recheck"
    manager, projects = _manager(root, jdk)
    observations = {}
    try:
        originals = {language: _source_git(manager, projects[language]) for language in ["python", "java"]}
        builder_before = private_hashes(root / "bundle-builder")
        fixtures = {language: _create_initial(manager, projects[language]) for language in ["python", "java"]}
        old_attempts = {}
        for language, fixture in fixtures.items():
            manual_comment(fixture, language)
            creation_before = private_hashes(fixture["job_dir"])
            selected = {name: sha((fixture["workspace"] / name).read_bytes()) for name in manager.projects[fixture["project_id"]]["definition"]["files"]}
            before_preview = private_hashes(root)
            with recheck_preview_guard(manager):
                preview = manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
            assert before_preview == private_hashes(root)
            with no_provider_calls():
                started = manager.snapshot_recheck_start(recheck_request(preview))
                value = _wait_recheck(manager, started["id"])
            assert value["status"] == "VERIFIED", (language, value.get("reason"))
            assert value["source_applied"] is False and value["workspace_modified"] is False
            assert value["creation_sha256"] == fixture["creation_sha256"]
            assert value["checked_files"] == selected
            assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in value["checks"].values())
            attempt = manager.data / "snapshot-workspace-rechecks" / value["id"]
            assert {name: sha((attempt / "snapshot" / name).read_bytes()) for name in selected} == selected
            assert not (attempt / "snapshot/.git").exists()
            assert sha((attempt / "checks.json").read_bytes()) == value["checks_sha256"]
            assert creation_before == private_hashes(fixture["job_dir"])
            _assert_source_git(projects[language], originals[language])
            assert all(private_hashes(path) == hashes for path, hashes in old_attempts.items())
            old_attempts[attempt] = private_hashes(attempt)
            assert manager.admission() is None
            observations[language] = value

        # Only editable worktree bytes change. The original passing creation and
        # earlier verification receipts remain immutable when this rerun fails.
        fixture = fixtures["python"]
        path = fixture["workspace"] / "arithmetic.py"
        raw = path.read_bytes()
        assert raw.count(b"a + b") == 1
        path.write_bytes(raw.replace(b"a + b", b"a * b"))
        creation_before = private_hashes(fixture["job_dir"])
        with recheck_preview_guard(manager):
            preview = manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
        with no_provider_calls():
            started = manager.snapshot_recheck_start(recheck_request(preview))
            failed = _wait_recheck(manager, started["id"])
        assert failed["status"] == "FAILED"
        assert any(row["exit_code"] != 0 and row["tests_ran"] > 0 for row in failed["checks"].values())
        assert manager.admission() == "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED"
        assert creation_before == private_hashes(fixture["job_dir"])
        assert all(private_hashes(path) == hashes for path, hashes in old_attempts.items())
        before_replay = private_hashes(root)
        try:
            manager.snapshot_recheck_start(recheck_request(preview))
        except Refused as exc:
            assert str(exc) == "SNAPSHOT_RECHECK_PREVIEW_REQUIRED"
        else:
            raise AssertionError("failed verification was silently retried")
        assert before_replay == private_hashes(root)
        for language in ["python", "java"]:
            _assert_source_git(projects[language], originals[language])
        assert builder_before == private_hashes(root / "bundle-builder")
        observations["failed"] = failed
    finally:
        manager.close()

    stop_root = work / "snapshot-workspace-recheck-stop"
    stopper, stop_projects = _manager(stop_root, jdk)
    try:
        project = stop_projects["python"]
        protected = project["source"] / "test_arithmetic.py"
        protected.write_bytes(b"import time\ntime.sleep(2)\n" + protected.read_bytes())
        task = copy.deepcopy(stopper.projects[project["project_id"]]["definition"])
        task["files"]["test_arithmetic.py"] = sha(protected.read_bytes())
        task_raw = canonical(task)
        project["task"].write_bytes(task_raw)
        stopper.projects[project["project_id"]].update(definition=task, task_raw=task_raw)
        slow_raw = _invented_bundle(stopper, project, b"a + b")
        project = {**project, "bundle_raw": slow_raw, "bundle_sha256": sha(slow_raw)}
        original = _source_git(stopper, project)
        builder_before = private_hashes(stop_root / "bundle-builder")
        fixture = _create_initial(stopper, project)
        manual_comment(fixture)
        creation_before = private_hashes(fixture["job_dir"])
        with recheck_preview_guard(stopper):
            preview = stopper.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
        with no_provider_calls():
            started = stopper.snapshot_recheck_start(recheck_request(preview))
            assert started["status"] == "PREPARING" and started["owned_active"]
            stopped = stopper.snapshot_recheck_stop(started["id"])
        assert stopped["status"] == "INTERRUPTED" and not stopped["owned_active"]
        assert stopper.admission() == "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED"
        assert creation_before == private_hashes(fixture["job_dir"])
        _assert_source_git(project, original)
        assert builder_before == private_hashes(stop_root / "bundle-builder")
        observations["stopped"] = stopped
    finally:
        stopper.close()

    (work / "snapshot-workspace-recheck-acceptance.json").write_text(json.dumps({
        "observations": observations, "fixtures_are_invented": True,
        "creation_receipts_and_prior_rechecks_unchanged": True,
        "manually_edited_worktrees_and_git_unchanged_per_recheck": True,
        "original_source_git_unchanged": True, "builder_holds_retained": True,
        "snapshot_workspace_recheck_model_requests": 0,
    }, indent=2) + "\n")
    return {"snapshot_workspace_recheck_python_java_checks_passed": True, "snapshot_workspace_recheck_fixed_snapshots": True,
            "snapshot_workspace_recheck_creation_and_history_immutable": True,
            "snapshot_workspace_recheck_worktree_git_unchanged": True, "snapshot_workspace_recheck_original_source_unchanged": True,
            "snapshot_workspace_recheck_failed_job_retained": True, "snapshot_workspace_recheck_owned_stop_retained": True,
            "snapshot_workspace_recheck_no_retry": True, "snapshot_workspace_recheck_model_requests": 0}
