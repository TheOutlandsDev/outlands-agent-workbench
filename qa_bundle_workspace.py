"""Actual fixed-check workspace qualification over private invented bundles."""

import copy
import json
import subprocess
import time
from pathlib import Path

from agent import Refused, canonical, review_diff, sha, write_new
from patch_bundle import build_bundle
from test_bundle_workspace_integration import (
    create_request, no_provider_calls, populate_workspace_projects, preview_guard, private_hashes,
)
from workbench import Manager, init_demo


def _git(source, *arguments, allowed=(0,)):
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-c", "user.name=Invented Workspace Fixture", "-c", "user.email=fixture@example.invalid",
        "-C", str(source), *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=20, env=env, check=False)
    assert result.returncode in allowed, "invented Git fixture operation failed"
    return result.stdout


def _source_git(manager, fixture):
    source = fixture["source"]
    selected = list(manager.projects[fixture["project_id"]]["definition"]["files"])
    write_new(source / "tracked-outside-scope.txt", b"invented unrelated tracked baseline\n")
    _git(source, "init", "--quiet")
    _git(source, "add", "--", *selected, "tracked-outside-scope.txt")
    _git(source, "commit", "--quiet", "-m", "Invented original baseline")
    (source / "tracked-outside-scope.txt").write_bytes(b"invented pre-existing uncommitted private change\n")
    write_new(source / "untracked-private.txt", b"invented untracked private sentinel\n")
    return {"head": _git(source, "rev-parse", "HEAD").decode().strip(),
            "status": _git(source, "status", "--porcelain", "--untracked-files=all").decode(),
            "hashes": private_hashes(source)}


def _assert_source_git(fixture, before):
    source = fixture["source"]
    assert private_hashes(source) == before["hashes"], "original source/Git bytes changed"
    assert _git(source, "rev-parse", "HEAD").decode().strip() == before["head"]
    assert _git(source, "status", "--porcelain", "--untracked-files=all").decode() == before["status"]
    assert private_hashes(source) == before["hashes"]


def _wait(manager, workspace_id):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = manager.bundle_workspace_view(workspace_id)
        if value["status"] != "PREPARING" and not value["owned_active"]:
            return value
        time.sleep(0.05)
    raise AssertionError("owned bundle workspace did not finish within qualification deadline")


def _invented_bundle(manager, fixture, new_expression):
    """Save plausible recorded evidence without executing it; worker rechecks it."""
    task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
    before = {name: (fixture["source"] / name).read_bytes() for name in task["files"]}
    after = dict(before)
    editable = task["editable"][0]
    assert before[editable].count(b"a - b") == 1
    after[editable] = before[editable].replace(b"a - b", new_expression)
    patch = "".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode()
    result = {"format": task["format"], "status": "REVIEW_READY", "reason": "CHECKS_PASSED", "backend": "scripted-demo",
        "ai_inference": False, "turns": 1, "source_adopted": False, "patch_sha256": sha(patch),
        "files": {name: {"before": sha(before[name]), "after": sha(after[name])} for name in before}}
    result_raw = canonical(result)
    review = {"id": "ffffffffffffffff", "verdict": "accepted", "recorded": 1, "source_applied": False,
        "result_sha256": sha(result_raw), "patch_sha256": sha(patch), "note": "Invented recorded fixture; fresh checks are required."}
    final = {"index": 0, "kind": "independent_final_checks", "value": {name: {
        "exit_code": 0, "tests_ran": 4, "timed_out": False, "output_limited": False,
        "infrastructure_error": False, "output": "Invented historical passing record"} for name in task["checks"]}}
    return build_bundle(canonical(task), result_raw, canonical(review), canonical(final), patch)


def _manager(root, jdk):
    root.mkdir(mode=0o700)
    paths = init_demo(root / "workspace", None)
    manager = Manager(Path(paths["config"]), Path(paths["data_dir"]), jdk)
    return manager, populate_workspace_projects(manager, root)


def acceptance(jdk, work):
    root = work / "bundle-workspace"
    manager, fixtures = _manager(root, jdk)
    observations = {}
    try:
        originals = {language: _source_git(manager, fixtures[language]) for language in ["python", "java"]}
        builder_before = private_hashes(root / "bundle-builder")
        assert not (manager.data / "state/hold.json").exists()
        for language in ["python", "java"]:
            fixture = fixtures[language]
            with preview_guard(manager):
                preview = manager.bundle_workspace_preview(fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"])
            with no_provider_calls():
                created = manager.bundle_workspace_create(create_request(preview))
                value = _wait(manager, created["id"])
            assert value["status"] == "VERIFIED", (language, value.get("reason"))
            assert value["source_applied"] is False and value["patch_applied_to_workspace"] is True
            assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in value["checks"].values())
            destination = Path(value["path"])
            assert destination != fixture["source"] and manager.data in destination.parents
            assert not (destination / "tracked-outside-scope.txt").exists()
            assert not (destination / "untracked-private.txt").exists()
            assert _git(destination, "diff", "--exit-code", allowed=(1,))
            assert _git(destination, "rev-parse", "HEAD").decode().strip() == value["baseline_commit"]
            assert _git(destination, "symbolic-ref", "--short", "HEAD").decode().strip() == value["branch"]
            _assert_source_git(fixture, originals[language])
            assert manager.admission() is None
            observations[language] = value
        assert observations["python"]["path"] != observations["java"]["path"]

        # A valid unsigned bundle can contain invented passing records. Actual
        # fixed checks must catch its deliberately incorrect candidate.
        fixture = fixtures["python"]
        failed_raw = _invented_bundle(manager, fixture, b"a * b")
        with preview_guard(manager):
            preview = manager.bundle_workspace_preview(fixture["project_id"], failed_raw, sha(failed_raw))
        with no_provider_calls():
            created = manager.bundle_workspace_create(create_request(preview))
            failed = _wait(manager, created["id"])
        assert failed["status"] == "FAILED"
        assert any(row["exit_code"] != 0 and row["tests_ran"] > 0 for row in failed["checks"].values())
        assert (manager.data / "bundle-workspaces" / failed["id"] / "bundle.zip").exists()
        assert manager.admission() == "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED"
        before_replay = private_hashes(root)
        try:
            manager.bundle_workspace_create(create_request(preview))
        except Refused as exc:
            assert str(exc) == "BUNDLE_WORKSPACE_PREVIEW_REQUIRED"
        else:
            raise AssertionError("failed job was silently retried")
        assert before_replay == private_hashes(root)
        for language in ["python", "java"]:
            _assert_source_git(fixtures[language], originals[language])
        assert builder_before == private_hashes(root / "bundle-builder")
        observations["failed"] = failed
    finally:
        manager.close()

    stop_root = work / "bundle-workspace-stop"
    stopper, stop_fixtures = _manager(stop_root, jdk)
    try:
        fixture = stop_fixtures["python"]
        protected = fixture["source"] / "test_arithmetic.py"
        protected.write_bytes(b"import time\ntime.sleep(2)\n" + protected.read_bytes())
        task = copy.deepcopy(stopper.projects[fixture["project_id"]]["definition"])
        task["files"]["test_arithmetic.py"] = sha(protected.read_bytes())
        task_raw = canonical(task)
        fixture["task"].write_bytes(task_raw)
        stopper.projects[fixture["project_id"]].update(definition=task, task_raw=task_raw)
        slow_raw = _invented_bundle(stopper, fixture, b"a + b")
        original = _source_git(stopper, fixture)
        builder_before = private_hashes(stop_root / "bundle-builder")
        with preview_guard(stopper):
            preview = stopper.bundle_workspace_preview(fixture["project_id"], slow_raw, sha(slow_raw))
        with no_provider_calls():
            created = stopper.bundle_workspace_create(create_request(preview))
            assert created["status"] == "PREPARING" and created["owned_active"]
            stopped = stopper.bundle_workspace_stop(created["id"])
        assert stopped["status"] == "INTERRUPTED" and not stopped["owned_active"]
        assert (stopper.data / "bundle-workspaces" / stopped["id"] / "bundle.zip").exists()
        assert stopper.admission() == "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED"
        _assert_source_git(fixture, original)
        assert builder_before == private_hashes(stop_root / "bundle-builder")
        observations["stopped"] = stopped
    finally:
        stopper.close()

    (work / "bundle-workspace-acceptance.json").write_text(json.dumps({
        "observations": observations, "fixtures_are_invented": True,
        "original_source_git_bytes_unchanged": True, "unrelated_files_excluded": True,
        "builder_holds_retained": True, "bundle_workspace_model_requests": 0,
    }, indent=2) + "\n")
    return {"bundle_workspace_python_java_checks_passed": True, "bundle_workspace_uncommitted_diff": True,
            "bundle_workspace_original_git_unchanged": True, "bundle_workspace_selected_files_only": True,
            "bundle_workspace_failed_job_retained": True, "bundle_workspace_owned_stop_retained": True,
            "bundle_workspace_no_retry": True, "bundle_workspace_model_requests": 0}
