"""Fresh private Git workspaces and actual fixed checks for invented snapshot packets."""

import copy
import json
import time
from pathlib import Path

from agent import Refused, canonical, review_diff, sha, write_new
from qa_bundle_workspace import _assert_source_git, _git, _invented_bundle, _manager, _source_git
from qa_workspace_recheck import _create_initial, _wait_recheck
from test_bundle_workspace_integration import create_request, no_provider_calls, private_hashes
from test_snapshot_workspace_integration import preview_guard
from test_workspace_recheck_integration import manual_comment, recheck_preview_guard, recheck_request


def _actual_packet(manager, fixture, language):
    from snapshot_export import prepare
    fixture = _create_initial(manager, fixture)
    manual_comment(fixture, language)
    before = private_hashes(fixture["job_dir"])
    with recheck_preview_guard(manager):
        preview = manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
    with no_provider_calls():
        started = manager.recheck_start(recheck_request(preview))
        receipt = _wait_recheck(manager, started["id"])
    assert receipt["status"] == "VERIFIED"
    assert before == private_hashes(fixture["job_dir"])
    attempt = manager.data / "workspace-rechecks" / receipt["id"]
    raw = prepare(attempt)["archive"]
    return {**fixture, "attempt_id": receipt["id"], "attempt_dir": attempt,
            "archive_raw": raw, "archive_sha256": sha(raw)}


def _invented_wrong_packet(manager, fixture):
    """Unsigned invented passing observations deliberately conceal a wrong expression."""
    import snapshot_export
    members = snapshot_export._members(fixture["archive_raw"])
    verification = json.loads(members["verification.json"])
    task = manager.projects[fixture["project_id"]]["definition"]
    baseline = {name: (fixture["source"] / name).read_bytes() for name in task["files"]}
    selected = {name: (fixture["attempt_dir"] / "snapshot" / name).read_bytes() for name in task["files"]}
    editable = task["editable"][0]
    assert selected[editable].count(b"a + b") == 1
    selected[editable] = selected[editable].replace(b"a + b", b"a * b")
    patch = "".join(review_diff(name, baseline[name], selected[name]) for name in sorted(baseline)).encode()
    verification["files"] = [{"path": name, "editable": name in task["editable"],
        "baseline_sha256": sha(baseline[name]), "snapshot_sha256": sha(selected[name]), "changed": baseline[name] != selected[name]}
        for name in sorted(baseline)]
    verification["hashes"] = {key: sha(("Invented unsigned wrong-code record " + key).encode()) for key in verification["hashes"]}
    verification["hashes"]["patch_sha256"] = sha(patch)
    parts = {"changes.diff": patch, "verification.json": canonical(verification), "README.txt": members["README.txt"]}
    parts["SHA256SUMS"] = snapshot_export._checksums(parts)
    raw = snapshot_export._archive(parts)
    snapshot_export.verify_export(raw)
    return raw


def _wait(manager, identifier):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = manager.snapshot_workspace_view(identifier)
        if value["status"] != "PREPARING" and not value["owned_active"]: return value
        time.sleep(0.05)
    raise AssertionError("owned snapshot workspace did not finish within qualification deadline")


def acceptance(jdk, work):
    root = work / "snapshot-workspace"
    manager, projects = _manager(root, jdk)
    observations = {}
    try:
        originals = {language: _source_git(manager, projects[language]) for language in ["python", "java"]}
        fixtures = {language: _actual_packet(manager, projects[language], language) for language in ["python", "java"]}
        assert not (manager.data / "state/hold.json").exists()
        old = private_hashes(root)
        prefix = str((manager.data / "snapshot-workspaces").relative_to(root)) + "/"
        for language, fixture in fixtures.items():
            with preview_guard(manager):
                preview = manager.snapshot_workspace_preview(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
            assert old == {name: value for name, value in private_hashes(root).items() if not name.startswith(prefix)}
            with no_provider_calls():
                started = manager.snapshot_workspace_create(create_request(preview))
                value = _wait(manager, started["id"])
            assert value["status"] == "VERIFIED", (language, value.get("reason"))
            assert value["source_applied"] is False and value["patch_applied_to_workspace"] is True
            assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
                ["timed_out", "output_limited", "infrastructure_error"]) for row in value["checks"].values())
            task = manager.projects[fixture["project_id"]]["definition"]
            destination = Path(value["path"])
            tested = {name: sha((fixture["attempt_dir"] / "snapshot" / name).read_bytes()) for name in task["files"]}
            assert value["snapshot"] == tested
            assert {name: sha((destination / name).read_bytes()) for name in task["files"]} == tested
            assert value["baseline"] == task["files"]
            assert not (destination / "tracked-outside-scope.txt").exists() and not (destination / "untracked-private.txt").exists()
            assert _git(destination, "diff", "--exit-code", allowed=(1,))
            assert _git(destination, "rev-parse", "HEAD").decode().strip() == value["baseline_commit"]
            assert _git(destination, "symbolic-ref", "--short", "HEAD").decode().strip() == value["branch"]
            assert value["branch"] == "outlands/snapshot-" + value["id"]
            assert manager.admission() is None
            _assert_source_git(fixture, originals[language])
            observations[language] = value
        assert observations["python"]["path"] != observations["java"]["path"]
        assert old == {name: value for name, value in private_hashes(root).items() if not name.startswith(prefix)}

        wrong = _invented_wrong_packet(manager, fixtures["python"])
        with preview_guard(manager):
            preview = manager.snapshot_workspace_preview(fixtures["python"]["project_id"], wrong, sha(wrong))
        with no_provider_calls():
            started = manager.snapshot_workspace_create(create_request(preview))
            failed = _wait(manager, started["id"])
        assert failed["status"] == "FAILED"
        assert any(row["exit_code"] != 0 and row["tests_ran"] > 0 for row in failed["checks"].values())
        assert (manager.data / "snapshot-workspaces" / failed["id"] / "snapshot.zip").read_bytes() == wrong
        assert manager.admission() == "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED"
        before = private_hashes(root)
        try: manager.snapshot_workspace_create(create_request(preview))
        except Refused as error: assert str(error) == "SNAPSHOT_WORKSPACE_PREVIEW_REQUIRED"
        else: raise AssertionError("failed snapshot worker was automatically retried")
        assert before == private_hashes(root)
        assert old == {name: value for name, value in private_hashes(root).items() if not name.startswith(prefix)}
        for language in ["python", "java"]: _assert_source_git(fixtures[language], originals[language])
        observations["failed"] = failed
    finally: manager.close()

    stop_root = work / "snapshot-workspace-stop"
    stopper, stop_projects = _manager(stop_root, jdk)
    try:
        fixture = stop_projects["python"]
        protected = fixture["source"] / "test_arithmetic.py"
        protected.write_bytes(b"import time\ntime.sleep(2)\n" + protected.read_bytes())
        task = copy.deepcopy(stopper.projects[fixture["project_id"]]["definition"])
        task["files"]["test_arithmetic.py"] = sha(protected.read_bytes())
        raw = canonical(task); fixture["task"].write_bytes(raw)
        stopper.projects[fixture["project_id"]].update(definition=task, task_raw=raw)
        bundle = _invented_bundle(stopper, fixture, b"a + b")
        fixture = {**fixture, "bundle_raw": bundle, "bundle_sha256": sha(bundle)}
        original = _source_git(stopper, fixture)
        fixture = _actual_packet(stopper, fixture, "python")
        old = private_hashes(stop_root)
        with preview_guard(stopper):
            preview = stopper.snapshot_workspace_preview(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
        with no_provider_calls():
            started = stopper.snapshot_workspace_create(create_request(preview))
            assert started["status"] == "PREPARING" and started["owned_active"]
            stopped = stopper.snapshot_workspace_stop(started["id"])
        assert stopped["status"] == "INTERRUPTED" and not stopped["owned_active"]
        assert stopper.admission() == "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED"
        prefix = str((stopper.data / "snapshot-workspaces").relative_to(stop_root)) + "/"
        assert old == {name: value for name, value in private_hashes(stop_root).items() if not name.startswith(prefix)}
        _assert_source_git(fixture, original)
        observations["stopped"] = stopped
    finally: stopper.close()
    (work / "snapshot-workspace-acceptance.json").write_text(json.dumps({"observations": observations,
        "fixtures_are_invented": True, "actual_initial_snapshot_and_import_checks": True,
        "selected_snapshot_bytes_exact": True, "old_records_source_git_snapshots_and_builder_holds_unchanged": True,
        "wrong_unsigned_packet_failed_actual_checks": True, "owned_stop_retained": True,
        "no_automatic_retry": True, "snapshot_workspace_model_requests": 0}, indent=2) + "\n")
    return {"snapshot_workspace_python_java_checks_passed": True, "snapshot_workspace_exact_import": True,
            "snapshot_workspace_old_bytes_unchanged": True, "snapshot_workspace_uncommitted_diff": True,
            "snapshot_workspace_failed_job_retained": True, "snapshot_workspace_owned_stop_retained": True,
            "snapshot_workspace_no_retry": True, "snapshot_workspace_model_requests": 0}
