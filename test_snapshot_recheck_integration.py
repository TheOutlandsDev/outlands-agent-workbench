"""Snapshot-workspace recheck fixtures and independent immutable-history tests."""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from snapshot_workspace import build as build_creation
from test_snapshot_workspace_integration import populate_snapshot_workspace_projects, fake_worker as fake_creation_worker, workspace_job as snapshot_job
from git_workspace import git
from test_bundle_workspace_integration import (
    create_request, fake_worker, no_provider_calls, populate_workspace_projects, private_hashes, workspace_job,
)
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-snapshot-workspace-recheck-sentinel"


def passing_checks(work, task, jdk):
    """Recorded fixture checks, never execution of project code or a compiler."""
    del work, jdk
    return {name: {"exit_code": 0, "tests_ran": 1 if isinstance(spec, dict) and spec.get("kind") == "java-main" else 4,
                   "timed_out": False, "output_limited": False, "infrastructure_error": False,
                   "output": "Invented unit-fixture check result"} for name, spec in task["checks"].items()}


def populate_recheck_workspaces(manager, root, languages=("python", "java")):
    """Real private snapshot Git creation; check rows are invented unit observations."""
    projects = populate_snapshot_workspace_projects(manager, root, languages)
    fixtures = {}
    for language, item in projects.items():
        preview = manager.snapshot_workspace_preview(item["project_id"], item["archive_raw"], item["archive_sha256"])
        original_jdk = manager.jdk_home
        try:
            if language == "java" and manager.jdk_home is None:
                manager.jdk_home = root / "unexecuted-unit-jdk-marker"
            with fake_creation_worker(manager):
                created = manager.snapshot_workspace_create(create_request(preview))
            job = snapshot_job(manager, created["id"])
            with no_provider_calls():
                receipt = build_creation(job, manager.jdk_home, passing_checks)
            assert receipt["status"] == "VERIFIED"
        finally:
            manager.jdk_home = original_jdk
        fixtures[language] = {**item, "workspace_id": created["id"], "job_dir": job,
            "workspace": Path(receipt["path"]), "creation_sha256": sha((job / "receipt.json").read_bytes())}
    return fixtures


@contextmanager
def recheck_fixture(languages=("python",)):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        fixtures = populate_recheck_workspaces(manager, root, languages)
        try:
            yield root, manager, fixtures
        finally:
            for attempt_id, (_, log) in list(manager.snapshot_recheck_children.items()):
                log.close()
                manager.snapshot_recheck_children.pop(attempt_id)
            manager.close()


@contextmanager
def recheck_preview_guard(manager):
    with no_provider_calls(), ExitStack() as stack:
        for name in ["history", "refresh", "admission", "view", "export", "verified_artifact", "request_hold", "owns_active",
                     "bundle_workspace_view", "bundle_workspaces", "snapshot_recheck_view", "snapshot_rechecks", "snapshot_workspace_view", "snapshot_workspaces", "project_readiness"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("recheck preview reached " + name)))
        for name in ["workbench.subprocess.Popen", "workbench.subprocess.run", "workbench.process_stamp",
                     "agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.git"]:
            stack.enter_context(patch(name, side_effect=AssertionError("recheck preview reached " + name)))
        yield


@contextmanager
def fake_recheck(manager, start_error=None):
    child = Mock(); child.pid = 99999999; child.poll.return_value = None
    with no_provider_calls(), patch("workbench.subprocess.run", side_effect=AssertionError("parent executed command")), \
            patch("workbench.subprocess.Popen", side_effect=start_error, return_value=child) as launch:
        try:
            yield child, launch
        finally:
            for attempt_id, (owned, log) in list(manager.snapshot_recheck_children.items()):
                if owned is child:
                    log.close()
                    manager.snapshot_recheck_children.pop(attempt_id)


def recheck_request(preview):
    return {"preview_id": preview["preview_id"], "preview_sha256": preview["preview_sha256"]}


def attempt_path(manager, attempt_id):
    return manager.data / "snapshot-workspace-rechecks" / attempt_id


def manual_comment(fixture, language="python"):
    name = "sample/Sum.java" if language == "java" else "addition.py" if language == "mixed" else "arithmetic.py"
    path = fixture["workspace"] / name
    path.write_bytes(path.read_bytes() + ("// invented manual café refinement\n" if language == "java" else "# invented manual café refinement\n").encode())
    return name


class SnapshotWorkspaceRecheckIntegrationTests(unittest.TestCase):
    def preview(self, root, manager, fixture):
        before = private_hashes(root)
        with recheck_preview_guard(manager):
            result = manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
        self.assertEqual(before, private_hashes(root))
        self.assertEqual(result["workspace_id"], fixture["workspace_id"])
        self.assertEqual(result["inspection"]["creation_sha256"], fixture["creation_sha256"])
        self.assertEqual(result["preview_sha256"], sha(canonical({"inspection": result["inspection"], "history_sha256": result["history_sha256"]})))
        self.assertNotIn(str(root), json.dumps(result))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result))
        self.assertLessEqual(len(canonical(result)), 131072)
        return result

    def assert_no_write_refusal(self, root, operation, *args, codes=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(*args)
        value = str(caught.exception)
        self.assertRegex(value, r"^[A-Z][A-Z0-9_]{1,64}$")
        self.assertNotIn(PRIVATE_SENTINEL, value)
        if codes:
            self.assertIn(value, codes)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_preview_observes_manual_edit_without_execution_or_mutation(self):
        with recheck_fixture(("python", "java")) as (root, manager, fixtures):
            self.assertIsNone(manager.jdk_home)
            for language, fixture in fixtures.items():
                with self.subTest(language=language):
                    name = manual_comment(fixture, language)
                    result = self.preview(root, manager, fixture)
                    self.assertIn(name, {row["path"] for row in result["inspection"]["files"]})
                    self.assertEqual((fixture["job_dir"] / "receipt.json").read_bytes(), canonical(json.loads((fixture["job_dir"] / "receipt.json").read_bytes())))
            self.assertEqual(list((manager.data / "snapshot-workspace-rechecks").iterdir()), [])

    def test_start_and_fake_passing_worker_preserve_creation_and_exact_checked_bytes(self):
        from snapshot_recheck import run as build
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            manual_comment(fixture)
            selected = {name: sha((fixture["workspace"] / name).read_bytes()) for name in manager.projects[fixture["project_id"]]["definition"]["files"]}
            creation_before = private_hashes(fixture["job_dir"])
            source_before = private_hashes(fixture["source"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, launch):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                self.assertEqual((started["status"], started["owned_active"]), ("PREPARING", True))
                attempt = attempt_path(manager, started["id"])
                request = json.loads((attempt / "request.json").read_bytes())
                self.assertEqual(set(request), {"version", "id", "workspace_id", "job_dir", "preview_sha256", "creation_sha256", "history_sha256"})
                self.assertEqual(request["job_dir"], str(fixture["job_dir"]))
                self.assertTrue(launch.call_args.args[0][2].endswith("/snapshot_recheck.py"))

                def checked_snapshot(snapshot, task, jdk):
                    self.assertEqual(snapshot, attempt / "snapshot")
                    self.assertEqual({name: sha((snapshot / name).read_bytes()) for name in task["files"]}, selected)
                    self.assertFalse((snapshot / ".git").exists())
                    return passing_checks(snapshot, task, jdk)

                receipt = build(attempt, checker=checked_snapshot)
                self.assertEqual(receipt["status"], "VERIFIED")
                self.assertEqual(receipt["checked_files"], selected)
                self.assertIs(receipt["source_applied"], False)
                self.assertIs(receipt["workspace_modified"], False)
                child.poll.return_value = 0
                value = manager.snapshot_recheck_view(started["id"])
                self.assertEqual((value["status"], value["owned_active"]), ("VERIFIED", False))
                self.assertEqual(manager.snapshot_rechecks(fixture["workspace_id"])["rechecks"][0]["id"], started["id"])
                self.assertIsNone(manager.admission())
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(preview), codes={"SNAPSHOT_RECHECK_PREVIEW_REQUIRED"})
                old_attempt = private_hashes(attempt)
                with self.assertRaises(Refused):
                    build(attempt, checker=lambda *_: (_ for _ in ()).throw(AssertionError("retried old checks")))
                self.assertEqual(old_attempt, private_hashes(attempt))
            self.assertEqual(creation_before, private_hashes(fixture["job_dir"]))
            self.assertEqual(source_before, private_hashes(fixture["source"]))

    def test_protected_source_and_creation_evidence_changes_refuse_read_only(self):
        for mode in ["protected", "source", "creation_failed", "old_checks"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                if mode == "protected":
                    path = fixture["workspace"] / "test_arithmetic.py"
                    path.write_bytes(path.read_bytes() + b"# intentional protected edit\n")
                elif mode == "source":
                    path = fixture["source"] / "arithmetic.py"
                    path.write_bytes(path.read_bytes() + b"# intentional original-source edit\n")
                elif mode == "creation_failed":
                    path = fixture["job_dir"] / "receipt.json"
                    value = json.loads(path.read_bytes()); value["status"] = "FAILED"
                    path.write_bytes(canonical(value))
                else:
                    path = fixture["job_dir"] / "checks.json"
                    path.write_bytes(path.read_bytes() + b" \n")
                with recheck_preview_guard(manager):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]},
                        codes={"SNAPSHOT_RECHECK_PROTECTED_CHANGED"} if mode == "protected" else None)

    def test_live_edit_during_checks_cannot_verify_earlier_snapshot(self):
        self._checker_mutation_refuses("live")

    def test_snapshot_edit_during_checks_cannot_verify_pinned_bytes(self):
        self._checker_mutation_refuses("snapshot")

    def _checker_mutation_refuses(self, target):
        from snapshot_recheck import run as build
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            manual_comment(fixture)
            original_receipt = (fixture["job_dir"] / "receipt.json").read_bytes()
            source_before = private_hashes(fixture["source"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                attempt = attempt_path(manager, started["id"])
                calls = []

                def changing_checker(snapshot, task, jdk):
                    calls.append(snapshot)
                    path = (fixture["workspace"] if target == "live" else snapshot) / "arithmetic.py"
                    path.write_bytes(path.read_bytes() + b"# intentional concurrent refinement\n")
                    return passing_checks(snapshot, task, jdk)

                with self.assertRaisesRegex(Refused, "^SNAPSHOT_RECHECK_STALE$"):
                    build(attempt, checker=changing_checker)
                self.assertEqual(calls, [attempt / "snapshot"])
                child.poll.return_value = 1
                receipt = manager.snapshot_recheck_view(started["id"])
                self.assertEqual((receipt["status"], receipt["reason"]), ("FAILED", "SNAPSHOT_RECHECK_STALE"))
                self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED")
            self.assertEqual(original_receipt, (fixture["job_dir"] / "receipt.json").read_bytes())
            self.assertEqual(source_before, private_hashes(fixture["source"]))

    def test_staged_commit_branch_pointer_index_and_extra_file_changes_refuse(self):
        for mode in ["staged", "head", "branch", "pointer", "index", "extra"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                work = fixture["workspace"]
                if mode in ["staged", "head"]:
                    manual_comment(fixture)
                    git(work, "add", "--", "arithmetic.py")
                    if mode == "head":
                        git(work, "commit", "--no-verify", "-m", "Invented manual commit")
                elif mode == "branch":
                    git(work, "branch", "-m", "invented-other-branch")
                elif mode == "pointer":
                    path = work / ".git"; path.write_bytes(path.read_bytes() + b"invalid extra pointer line\n")
                elif mode == "index":
                    pointer = (work / ".git").read_text().strip().removeprefix("gitdir: ")
                    path = Path(pointer) / "index"
                    raw = path.read_bytes(); path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                else:
                    write_new(work / "unselected-private.txt", PRIVATE_SENTINEL.encode())
                with recheck_preview_guard(manager):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]})

    def test_workspace_symlinks_and_hardlinks_never_enter_snapshot_scope(self):
        for mode in ["symlink", "hardlink", "root"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                if mode == "root":
                    work = fixture["workspace"]
                    work.rename(root / "retained-real-worktree")
                    outside = root / "outside-worktree"; outside.mkdir()
                    write_new(outside / "arithmetic.py", PRIVATE_SENTINEL.encode())
                    work.symlink_to(outside, target_is_directory=True)
                else:
                    path = fixture["workspace"] / "arithmetic.py"
                    outside = root / "outside-selected.py"; outside.write_bytes(path.read_bytes())
                    path.unlink()
                    if mode == "symlink":
                        path.symlink_to(outside)
                    else:
                        path.hardlink_to(outside)
                with recheck_preview_guard(manager):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]})

    def test_config_task_and_stale_preview_bytes_refuse_before_attempts(self):
        for mode in ["config", "task", "editable"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                if mode == "config":
                    manager.config_path.write_bytes(manager.config_raw + b" \n")
                elif mode == "task":
                    fixture["task"].write_bytes(fixture["task"].read_bytes() + b" \n")
                else:
                    manual_comment(fixture)
                with fake_recheck(manager) as (_, launch):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(preview),
                        codes={"SNAPSHOT_RECHECK_PROJECT_CHANGED"} if mode in ["config", "task"] else {"SNAPSHOT_RECHECK_PREVIEW_CHANGED"})
                    launch.assert_not_called()
                self.assertEqual(list((manager.data / "snapshot-workspace-rechecks").iterdir()), [])

    def test_expiration_replacement_cross_workspace_and_fields_never_execute(self):
        with recheck_fixture(("python", "mixed")) as (root, manager, fixtures):
            with patch("workbench.time.monotonic", return_value=1000):
                expired = self.preview(root, manager, fixtures["python"])
            with fake_recheck(manager) as (_, launch), patch("workbench.time.monotonic", return_value=1301):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(expired), codes={"SNAPSHOT_RECHECK_PREVIEW_EXPIRED"})
                launch.assert_not_called()
            first = self.preview(root, manager, fixtures["python"])
            second = self.preview(root, manager, fixtures["mixed"])
            with fake_recheck(manager) as (_, launch):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(first), codes={"SNAPSHOT_RECHECK_PREVIEW_CHANGED"})
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start,
                    {"preview_id": second["preview_id"], "preview_sha256": first["preview_sha256"]}, codes={"SNAPSHOT_RECHECK_PREVIEW_CHANGED"})
                for fields in [{**recheck_request(second), "path": "/fictional/outside"}, {"preview_id": second["preview_id"]}]:
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_start, fields, codes={"SNAPSHOT_RECHECK_FIELDS"})
                launch.assert_not_called()
            with recheck_preview_guard(manager):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixtures["python"]["workspace_id"], "checks": {}}, codes={"SNAPSHOT_RECHECK_FIELDS"})
            with fake_recheck(manager):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(second), codes={"SNAPSHOT_RECHECK_PREVIEW_REQUIRED"})

    def test_history_completion_invalidates_preview_with_unchanged_target_bytes(self):
        from snapshot_recheck import run as build
        with recheck_fixture(("python", "mixed")) as (root, manager, fixtures):
            target, other = fixtures["python"], fixtures["mixed"]
            manual_comment(other, "mixed")
            first = self.preview(root, manager, other)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(first))
                waiting = self.preview(root, manager, target)
                target_before = private_hashes(target["job_dir"])
                build(attempt_path(manager, started["id"]), checker=passing_checks)
                child.poll.return_value = 0
                self.assertEqual(manager.snapshot_recheck_view(started["id"])["status"], "VERIFIED")
                self.assertEqual(target_before, private_hashes(target["job_dir"]))
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(waiting), codes={"SNAPSHOT_RECHECK_PREVIEW_CHANGED"})

    def test_hold_blocks_start_without_mutation_but_not_read_only_preview(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            hold = manager.data / "state/hold.json"
            write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": "invented unrelated hold", "turn": 1}))
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (_, launch), patch("workbench.inspect_snapshot_recheck", side_effect=AssertionError("held execution reinspected")):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(preview), codes={"UNCERTAIN_REQUEST_HELD"})
                launch.assert_not_called()

    def test_java_requires_jdk_before_any_persistent_attempt(self):
        with recheck_fixture(("java",)) as (root, manager, fixtures):
            self.assertIsNone(manager.jdk_home)
            preview = self.preview(root, manager, fixtures["java"])
            with fake_recheck(manager) as (_, launch):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(preview), codes={"JDK_REQUIRED"})
                launch.assert_not_called()

    def test_start_failure_retains_pins_and_blocks_legacy_start_without_retry(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            original = private_hashes(fixture["job_dir"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager, OSError(PRIVATE_SENTINEL)) as (_, launch):
                with self.assertRaisesRegex(Refused, "^SNAPSHOT_RECHECK_START_FAILED$"):
                    manager.snapshot_recheck_start(recheck_request(preview))
                rows = manager.snapshot_rechecks(fixture["workspace_id"])["rechecks"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "FAILED")
                self.assertEqual(rows[0]["creation_sha256"], fixture["creation_sha256"])
                self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED")
                self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(preview), codes={"SNAPSHOT_RECHECK_PREVIEW_REQUIRED"})
                self.assert_no_write_refusal(root, manager.start, {"project": "arithmetic", "model": "scripted-demo", "goal": manager.projects["arithmetic"]["definition"]["goal"]}, codes={"SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED"})
                launch.assert_called_once()
            self.assertEqual(original, private_hashes(fixture["job_dir"]))

    def test_worker_failure_written_during_poll_is_retained_instead_of_interrupted(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                path = attempt_path(manager, started["id"]) / "receipt.json"

                def complete():
                    value = json.loads(path.read_bytes()); value.update(status="FAILED", reason="SNAPSHOT_RECHECK_CHECKS_FAILED", finished=value["created"] + 1)
                    path.write_bytes(canonical(value))
                    return 1

                child.poll.side_effect = complete
                result = manager.snapshot_recheck_view(started["id"])
                self.assertEqual((result["status"], result["reason"], result["owned_active"]), ("FAILED", "SNAPSHOT_RECHECK_CHECKS_FAILED", False))
                self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED")

    def test_owned_stop_preserves_creation_and_cannot_signal_unowned_history(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            original = private_hashes(fixture["job_dir"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                child.wait.side_effect = lambda **_: setattr(child.poll, "return_value", -15)
                with patch("workbench.os.killpg") as signal_group:
                    result = manager.snapshot_recheck_stop(started["id"])
                    signal_group.assert_called_once()
                self.assertEqual((result["status"], result["owned_active"]), ("INTERRUPTED", False))
                with patch("workbench.os.killpg", side_effect=AssertionError("unowned process signal")):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_stop, started["id"], codes={"NO_OWNED_ACTIVE_SNAPSHOT_RECHECK"})
                self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED")
            self.assertEqual(original, private_hashes(fixture["job_dir"]))

    def test_malformed_saved_recheck_receipts_block_without_rewriting_creation(self):
        for value in [[], 42, {"status": []}, {"status": "VERIFIED"}]:
            with self.subTest(value=value), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                old = private_hashes(fixture["job_dir"])
                with fake_recheck(manager):
                    started = manager.snapshot_recheck_start(recheck_request(preview))
                    path = attempt_path(manager, started["id"]) / "receipt.json"
                    if isinstance(value, dict):
                        changed = json.loads(path.read_bytes()); changed.update(value)
                    else:
                        changed = value
                    path.write_bytes(canonical(changed))
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_view, started["id"], codes={"SNAPSHOT_RECHECK_RECORD_INVALID"})
                    self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_NEEDS_INSPECTION")
                self.assertEqual(old, private_hashes(fixture["job_dir"]))

    def test_restart_does_not_claim_unknown_preparing_attempt_or_clear_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = init_demo(root / "workspace", None)
            config, data = Path(paths["config"]), Path(paths["data_dir"])
            first = Manager(config, data)
            try:
                fixtures = populate_recheck_workspaces(first, root, ("python",))
                fixture = fixtures["python"]
                preview = self.preview(root, first, fixture)
                with fake_recheck(first):
                    started = first.snapshot_recheck_start(recheck_request(preview))
            finally:
                first.close()
            restarted = Manager(config, data)
            try:
                before = private_hashes(root)
                result = restarted.snapshot_recheck_view(started["id"])
                self.assertEqual((result["status"], result["owned_active"]), ("PREPARING", False))
                self.assertEqual(restarted.admission(), "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED")
                with patch("workbench.os.killpg", side_effect=AssertionError("restart process ownership")):
                    self.assert_no_write_refusal(root, restarted.snapshot_recheck_stop, started["id"], codes={"NO_OWNED_ACTIVE_SNAPSHOT_RECHECK"})
                self.assertEqual(before, private_hashes(root))
            finally:
                restarted.close()

    def test_unknown_workspace_ids_and_bounded_history_never_execute(self):
        with recheck_fixture() as (root, manager, _):
            with recheck_preview_guard(manager):
                for workspace_id in [None, "../outside", "g" * 16]:
                    with self.subTest(workspace_id=workspace_id):
                        self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": workspace_id}, codes={"SNAPSHOT_RECHECK_ID"})
                self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": "f" * 16}, codes={"SNAPSHOT_RECHECK_CREATION_REQUIRED"})
            for number in range(201):
                (manager.data / "snapshot-workspace-rechecks" / f"{number:016x}").mkdir()
            self.assert_no_write_refusal(root, manager.snapshot_rechecks, "f" * 16, codes={"SNAPSHOT_RECHECK_LIMIT"})
            self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_NEEDS_INSPECTION")

    def test_start_reserves_history_count_and_receipt_budget_before_writing(self):
        for mode, count, padding in [("count", 200, 0), ("aggregate", 8, 235000)]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                for number in range(count):
                    attempt_id = f"{number:016x}"
                    directory = attempt_path(manager, attempt_id)
                    directory.mkdir(mode=0o700)
                    receipt = {"version": 1, "format": "outlands-snapshot-workspace-recheck-v1", "id": attempt_id,
                        "workspace_id": fixture["workspace_id"], "status": "VERIFIED", "created": 1, "finished": 2,
                        "source_applied": False, "workspace_modified": False,
                        "checked_files": {"arithmetic.py": "a" * 64},
                        "checks": {"unit": {"exit_code": 0, "tests_ran": 1, "timed_out": False,
                            "output_limited": False, "infrastructure_error": False, "output": "", "display_truncated": False}},
                        **{key: "a" * 64 for key in ["creation_sha256", "preview_sha256", "history_sha256",
                            "snapshot_sha256", "task_sha256", "archive_sha256", "config_sha256", "checks_sha256"]}}
                    write_new(directory / "receipt.json", canonical(receipt) + b" " * padding)
                preview = self.preview(root, manager, fixture)
                inspected = {"summary": preview["inspection"],
                    "task": manager.projects[fixture["project_id"]]["definition"]}
                with fake_recheck(manager) as (_, launch), patch.object(manager, "_snapshot_recheck_inspection", return_value=inspected):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_start, recheck_request(preview), codes={"SNAPSHOT_RECHECK_LIMIT"})
                    launch.assert_not_called()
                self.assertEqual(len(list((manager.data / "snapshot-workspace-rechecks").iterdir())), count)


    def test_creation_next_marker_refuses_without_repair_or_reconciliation(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            write_new(fixture["job_dir"] / "receipt.json.next", b"invented interrupted creation evidence")
            with recheck_preview_guard(manager):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]}, codes={"SNAPSHOT_RECHECK_RECORD_INVALID"})
            self.assertIn("ADMISSION_RECORD_INVALID", manager.readiness_admission()["reasons"])

    def test_attempt_next_marker_blocks_history_and_readiness_without_overwrite(self):
        from snapshot_recheck import run
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                attempt = attempt_path(manager, started["id"])
                run(attempt, checker=passing_checks); child.poll.return_value = 0
                manager.snapshot_recheck_view(started["id"])
            write_new(attempt / "receipt.json.next", b"invented retained terminal fragment")
            before = private_hashes(root)
            self.assert_no_write_refusal(root, manager.snapshot_recheck_view, started["id"], codes={"SNAPSHOT_RECHECK_RECORD_INVALID"})
            self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_NEEDS_INSPECTION")
            self.assertIn("ADMISSION_RECORD_INVALID", manager.readiness_admission()["reasons"])
            self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]})
            self.assertEqual(before, private_hashes(root))

    def test_new_format_rejects_legacy_creation_without_conversion(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; path = fixture["job_dir"] / "receipt.json"
            value = json.loads(path.read_bytes()); value["format"] = "outlands-bundle-workspace-v1"; path.write_bytes(canonical(value))
            with recheck_preview_guard(manager):
                self.assert_no_write_refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]})
            self.assertEqual(list((manager.data / "snapshot-workspace-rechecks").iterdir()), [])

    def test_readiness_of_preparing_attempt_is_static_and_blocks_execution(self):
        with recheck_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_recheck(manager) as (child, _):
                manager.snapshot_recheck_start(recheck_request(preview)); before = private_hashes(root)
                with patch.object(manager, "snapshot_recheck_view", side_effect=AssertionError("readiness reconciled worker")):
                    self.assertIn("WORKSPACE_ACTIVE_OR_UNRESOLVED", manager.readiness_admission()["reasons"])
                self.assertEqual(before, private_hashes(root)); self.assertEqual(child.poll.call_count, 1)

    def test_close_stops_owned_recheck_only_and_leaves_no_owned_handles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); paths = init_demo(root / "workspace", None)
            manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
            fixtures = populate_recheck_workspaces(manager, root, ("python",))
            fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                child.wait.side_effect = lambda **_: setattr(child.poll, "return_value", -15)
                with patch("workbench.os.killpg") as signals: manager.close()
                self.assertEqual(signals.call_count, 1)
                self.assertEqual(manager.snapshot_recheck_children, {})
                receipt = json.loads((attempt_path(manager, started["id"]) / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "INTERRUPTED")


    def test_owned_live_attempt_pending_transition_never_claims_verified(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                attempt = attempt_path(manager, started["id"])
                write_new(attempt / "receipt.json.next", b"invented live final write")
                before = private_hashes(root)
                value = manager.snapshot_recheck_view(started["id"])
                self.assertEqual((value["status"], value["owned_active"]), ("PREPARING", True))
                self.assertEqual(manager.admission(), "SNAPSHOT_RECHECK_ACTIVE_OR_UNRESOLVED")
                self.assertIn("ADMISSION_RECORD_INVALID", manager.readiness_admission()["reasons"])
                self.assertEqual(before, private_hashes(root))
                child.poll.return_value = 1
                self.assert_no_write_refusal(root, manager.snapshot_recheck_view, started["id"], codes={"SNAPSHOT_RECHECK_RECORD_INVALID"})
                self.assertEqual(before, private_hashes(root))

    def test_owned_live_creation_pending_transition_preserves_old_receipt(self):
        from test_snapshot_workspace_integration import workspace_fixture, fake_worker, workspace_job
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            preview = manager.snapshot_workspace_preview(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
            with fake_worker(manager) as (child, _):
                started = manager.snapshot_workspace_create(create_request(preview))
                job = workspace_job(manager, started["id"])
                write_new(job / "receipt.json.next", b"invented live creation final write")
                before = private_hashes(root)
                value = manager.snapshot_workspace_view(started["id"])
                self.assertEqual((value["status"], value["owned_active"]), ("PREPARING", True))
                self.assertEqual(manager.admission(), "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED")
                self.assertIn("ADMISSION_RECORD_INVALID", manager.readiness_admission()["reasons"])
                self.assertEqual(before, private_hashes(root))
                child.poll.return_value = 1
                self.assert_no_write_refusal(root, manager.snapshot_workspace_view, started["id"], codes={"SNAPSHOT_WORKSPACE_RECORD_INVALID"})
                self.assertEqual(before, private_hashes(root))


    def test_terminal_replacement_during_receipt_read_has_no_stale_marker_error(self):
        import os
        from workbench import readiness_read_file
        from snapshot_recheck import run
        with recheck_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_recheck(manager):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                attempt = attempt_path(manager, started["id"]); initial = (attempt / "receipt.json").read_bytes()
                terminal = run(attempt, checker=passing_checks)
                final_raw = (attempt / "receipt.json").read_bytes()
                (attempt / "receipt.json").write_bytes(initial)
                write_new(attempt / "receipt.json.next", final_raw)
                def complete(path, name, limit):
                    if path == attempt and name == "receipt.json" and (attempt / "receipt.json.next").exists():
                        os.replace(attempt / "receipt.json.next", attempt / "receipt.json")
                    return readiness_read_file(path, name, limit)
                with patch("workbench.readiness_read_file", side_effect=complete):
                    value = manager.snapshot_recheck_view(started["id"])
                self.assertEqual(value["status"], "VERIFIED"); self.assertEqual(value["snapshot_sha256"], terminal["snapshot_sha256"])

    def test_creation_terminal_replacement_during_receipt_read_is_observed(self):
        import os
        from workbench import readiness_read_file
        from snapshot_workspace import build
        from test_snapshot_workspace_integration import workspace_fixture, fake_worker, workspace_job
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            preview = manager.snapshot_workspace_preview(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
            with fake_worker(manager):
                started = manager.snapshot_workspace_create(create_request(preview))
            job = workspace_job(manager, started["id"]); initial = (job / "receipt.json").read_bytes()
            # Real fixture Git setup must run outside the parent's no-command stub.
            build(job, checker=passing_checks); final_raw = (job / "receipt.json").read_bytes()
            (job / "receipt.json").write_bytes(initial); write_new(job / "receipt.json.next", final_raw)
            def complete(path, name, limit):
                if path == job and name == "receipt.json" and (job / "receipt.json.next").exists():
                    os.replace(job / "receipt.json.next", job / "receipt.json")
                return readiness_read_file(path, name, limit)
            with fake_worker(manager) as (child, _):
                manager.snapshot_workspace_children[started["id"]] = (child, io.BytesIO())
                with patch("workbench.readiness_read_file", side_effect=complete):
                    value = manager.snapshot_workspace_view(started["id"])
                self.assertEqual(value["status"], "VERIFIED")

    def test_marker_read_failure_is_fixed_code_without_reconciliation_or_repair(self):
        with recheck_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_recheck(manager):
                started = manager.snapshot_recheck_start(recheck_request(preview))
                with patch.object(manager, "readiness_entries", side_effect=OSError(PRIVATE_SENTINEL)):
                    self.assert_no_write_refusal(root, manager.snapshot_recheck_view, started["id"], codes={"SNAPSHOT_RECHECK_RECORD_INVALID"})


@contextmanager
def recheck_http_fixture():
    with recheck_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-recheck-token", "http://127.0.0.1:8765")

        def request(method, path, value=None, headers=None):
            raw = canonical(value) if value is not None else b""
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-recheck-token"}
            if method == "POST":
                supplied.update({"Origin": "http://127.0.0.1:8765", "Content-Type": "application/json", "Content-Length": str(len(raw))})
            duplicate = headers if isinstance(headers, list) else []
            if isinstance(headers, dict):
                supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = method, path
            handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in list(supplied.items()) + duplicate:
                handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
            getattr(handler, "do_" + method)()
            head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(body)

        yield root, manager, fixtures, request


class SnapshotWorkspaceRecheckHTTPTests(unittest.TestCase):
    def test_preview_start_history_view_contracts_are_scoped(self):
        with recheck_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]
            before = private_hashes(root)
            with recheck_preview_guard(manager):
                code, preview = request("POST", "/api/snapshot-workspace-recheck-preview", {"workspace_id": fixture["workspace_id"]})
            self.assertEqual(code, 200)
            self.assertEqual(before, private_hashes(root))
            with fake_recheck(manager):
                code, started = request("POST", "/api/snapshot-workspace-recheck-start", recheck_request(preview))
                self.assertEqual((code, started["status"]), (200, "PREPARING"))
                code, history = request("GET", "/api/snapshot-workspace-rechecks/" + fixture["workspace_id"])
                self.assertEqual(code, 200)
                self.assertEqual(history["rechecks"][0]["id"], started["id"])
                code, view = request("GET", "/api/snapshot-workspace-recheck/" + started["id"])
                self.assertEqual((code, view["owned_active"]), (200, True))

    def test_json_framing_and_security_guards_precede_manager_invocation(self):
        with recheck_http_fixture() as (root, manager, fixtures, request):
            fixture, before = fixtures["python"], private_hashes(root)
            bodies = [("preview", "snapshot_recheck_preview", {"workspace_id": fixture["workspace_id"]}),
                      ("start", "snapshot_recheck_start", {"preview_id": "1" * 16, "preview_sha256": "a" * 64}),
                      ("stop", "snapshot_recheck_stop", {"id": "1" * 16})]
            with no_provider_calls():
                for endpoint, method, body in bodies:
                    path = "/api/snapshot-workspace-recheck-" + endpoint
                    with patch.object(manager, method, side_effect=AssertionError("bad HTTP reached manager")) as invoke:
                        for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": str(len(canonical(body)) + 1)},
                                        [("Content-Length", str(len(canonical(body))))]]:
                            with self.subTest(endpoint=endpoint, headers=headers):
                                code, value = request("POST", path, body, headers)
                                self.assertEqual(code, 409)
                                self.assertRegex(value["error"], r"^[A-Z_]+$")
                        invoke.assert_not_called()
                for headers, reason in [({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                                        ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"),
                                        ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                    code, value = request("POST", "/api/snapshot-workspace-recheck-preview", bodies[0][2], headers)
                    self.assertEqual((code, value["error"]), (409, reason))
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()

