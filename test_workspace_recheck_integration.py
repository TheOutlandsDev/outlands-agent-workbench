"""Imported-workspace recheck fixtures and immutable-history integration tests."""

import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from bundle_workspace import build as build_creation
from git_workspace import git
from test_bundle_workspace_integration import (
    create_request, fake_worker, no_provider_calls, populate_workspace_projects, private_hashes, workspace_job,
)
from workbench import Manager, init_demo, make_handler
import workbench as controller


PRIVATE_SENTINEL = "invented-private-workspace-recheck-sentinel"


def passing_checks(work, task, jdk):
    """Recorded fixture checks, never execution of project code or a compiler."""
    del work, jdk
    return {name: {"exit_code": 0, "tests_ran": 1 if isinstance(spec, dict) and spec.get("kind") == "java-main" else 4,
                   "timed_out": False, "output_limited": False, "infrastructure_error": False,
                   "output": "Invented unit-fixture check result"} for name, spec in task["checks"].items()}


def populate_recheck_workspaces(manager, root, languages=("python", "java")):
    """Create real private Git worktrees using a fake passing creation checker.

    No isolated check, provider or Java executable runs. The separate bundle
    builder retains its own synthetic hold; this target Manager stays hold-free.
    """
    projects = populate_workspace_projects(manager, root)
    fixtures = {}
    for language in languages:
        item = projects[language]
        preview = manager.bundle_workspace_preview(item["project_id"], item["bundle_raw"], item["bundle_sha256"])
        original_jdk = manager.jdk_home
        try:
            if language == "java" and manager.jdk_home is None:
                manager.jdk_home = root / "unexecuted-unit-jdk-marker"
            with fake_worker(manager):
                created = manager.bundle_workspace_create(create_request(preview))
            job = workspace_job(manager, created["id"])
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
            for attempt_id, (_, log) in list(manager.recheck_children.items()):
                log.close()
                manager.recheck_children.pop(attempt_id)
            manager.close()


@contextmanager
def recheck_preview_guard(manager):
    with no_provider_calls(), ExitStack() as stack:
        for name in ["history", "refresh", "admission", "view", "export", "verified_artifact", "request_hold", "owns_active",
                     "bundle_workspace_view", "bundle_workspaces", "recheck_view", "rechecks", "project_readiness"]:
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
            for attempt_id, (owned, log) in list(manager.recheck_children.items()):
                if owned is child:
                    log.close()
                    manager.recheck_children.pop(attempt_id)


def recheck_request(preview):
    return {"preview_id": preview["preview_id"], "preview_sha256": preview["preview_sha256"]}


def attempt_path(manager, attempt_id):
    return manager.data / "workspace-rechecks" / attempt_id


def manual_comment(fixture, language="python"):
    name = "sample/Sum.java" if language == "java" else "addition.py" if language == "mixed" else "arithmetic.py"
    path = fixture["workspace"] / name
    path.write_bytes(path.read_bytes() + ("// invented manual café refinement\n" if language == "java" else "# invented manual café refinement\n").encode())
    return name


class WorkspaceRecheckIntegrationTests(unittest.TestCase):
    def preview(self, root, manager, fixture):
        before = private_hashes(root)
        with recheck_preview_guard(manager):
            result = manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
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
            self.assertEqual(list((manager.data / "workspace-rechecks").iterdir()), [])

    def test_start_and_fake_passing_worker_preserve_creation_and_exact_checked_bytes(self):
        from workspace_recheck import build
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            manual_comment(fixture)
            selected = {name: sha((fixture["workspace"] / name).read_bytes()) for name in manager.projects[fixture["project_id"]]["definition"]["files"]}
            creation_before = private_hashes(fixture["job_dir"])
            source_before = private_hashes(fixture["source"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, launch):
                started = manager.recheck_start(recheck_request(preview))
                self.assertEqual((started["status"], started["owned_active"]), ("PREPARING", True))
                attempt = attempt_path(manager, started["id"])
                request = json.loads((attempt / "request.json").read_bytes())
                self.assertEqual(set(request), {"version", "id", "workspace_id", "job_dir", "preview_sha256", "creation_sha256", "history_sha256"})
                self.assertEqual(request["job_dir"], str(fixture["job_dir"]))
                self.assertTrue(launch.call_args.args[0][2].endswith("/workspace_recheck.py"))

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
                value = manager.recheck_view(started["id"])
                self.assertEqual((value["status"], value["owned_active"]), ("VERIFIED", False))
                self.assertEqual(manager.rechecks(fixture["workspace_id"])["rechecks"][0]["id"], started["id"])
                self.assertIsNone(manager.admission())
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(preview), codes={"RECHECK_PREVIEW_REQUIRED"})
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
                    self.assert_no_write_refusal(root, manager.recheck_preview, {"workspace_id": fixture["workspace_id"]},
                        codes={"RECHECK_PROTECTED_CHANGED"} if mode == "protected" else None)

    def test_live_edit_during_checks_cannot_verify_earlier_snapshot(self):
        self._checker_mutation_refuses("live")

    def test_snapshot_edit_during_checks_cannot_verify_pinned_bytes(self):
        self._checker_mutation_refuses("snapshot")

    def _checker_mutation_refuses(self, target):
        from workspace_recheck import build
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            manual_comment(fixture)
            original_receipt = (fixture["job_dir"] / "receipt.json").read_bytes()
            source_before = private_hashes(fixture["source"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(preview))
                attempt = attempt_path(manager, started["id"])
                calls = []

                def changing_checker(snapshot, task, jdk):
                    calls.append(snapshot)
                    path = (fixture["workspace"] if target == "live" else snapshot) / "arithmetic.py"
                    path.write_bytes(path.read_bytes() + b"# intentional concurrent refinement\n")
                    return passing_checks(snapshot, task, jdk)

                with self.assertRaisesRegex(Refused, "^RECHECK_STALE$"):
                    build(attempt, checker=changing_checker)
                self.assertEqual(calls, [attempt / "snapshot"])
                child.poll.return_value = 1
                receipt = manager.recheck_view(started["id"])
                self.assertEqual((receipt["status"], receipt["reason"]), ("FAILED", "RECHECK_STALE"))
                self.assertEqual(manager.admission(), "RECHECK_ACTIVE_OR_UNRESOLVED")
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
                    self.assert_no_write_refusal(root, manager.recheck_preview, {"workspace_id": fixture["workspace_id"]})

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
                    self.assert_no_write_refusal(root, manager.recheck_preview, {"workspace_id": fixture["workspace_id"]})

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
                    self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(preview),
                        codes={"RECHECK_PROJECT_CHANGED"} if mode in ["config", "task"] else {"RECHECK_PREVIEW_CHANGED"})
                    launch.assert_not_called()
                self.assertEqual(list((manager.data / "workspace-rechecks").iterdir()), [])

    def test_expiration_replacement_cross_workspace_and_fields_never_execute(self):
        with recheck_fixture(("python", "mixed")) as (root, manager, fixtures):
            with patch("workbench.time.monotonic", return_value=1000):
                expired = self.preview(root, manager, fixtures["python"])
            with fake_recheck(manager) as (_, launch), patch("workbench.time.monotonic", return_value=1301):
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(expired), codes={"RECHECK_PREVIEW_EXPIRED"})
                launch.assert_not_called()
            first = self.preview(root, manager, fixtures["python"])
            second = self.preview(root, manager, fixtures["mixed"])
            with fake_recheck(manager) as (_, launch):
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(first), codes={"RECHECK_PREVIEW_CHANGED"})
                self.assert_no_write_refusal(root, manager.recheck_start,
                    {"preview_id": second["preview_id"], "preview_sha256": first["preview_sha256"]}, codes={"RECHECK_PREVIEW_CHANGED"})
                for fields in [{**recheck_request(second), "path": "/fictional/outside"}, {"preview_id": second["preview_id"]}]:
                    self.assert_no_write_refusal(root, manager.recheck_start, fields, codes={"RECHECK_FIELDS"})
                launch.assert_not_called()
            with recheck_preview_guard(manager):
                self.assert_no_write_refusal(root, manager.recheck_preview, {"workspace_id": fixtures["python"]["workspace_id"], "checks": {}}, codes={"RECHECK_FIELDS"})
            with fake_recheck(manager):
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(second), codes={"RECHECK_PREVIEW_REQUIRED"})

    def test_history_completion_invalidates_preview_with_unchanged_target_bytes(self):
        from workspace_recheck import build
        with recheck_fixture(("python", "mixed")) as (root, manager, fixtures):
            target, other = fixtures["python"], fixtures["mixed"]
            manual_comment(other, "mixed")
            first = self.preview(root, manager, other)
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(first))
                waiting = self.preview(root, manager, target)
                target_before = private_hashes(target["job_dir"])
                build(attempt_path(manager, started["id"]), checker=passing_checks)
                child.poll.return_value = 0
                self.assertEqual(manager.recheck_view(started["id"])["status"], "VERIFIED")
                self.assertEqual(target_before, private_hashes(target["job_dir"]))
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(waiting), codes={"RECHECK_PREVIEW_CHANGED"})

    def test_hold_blocks_start_without_mutation_but_not_read_only_preview(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            hold = manager.data / "state/hold.json"
            write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": "invented unrelated hold", "turn": 1}))
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (_, launch), patch("workbench.inspect_recheck", side_effect=AssertionError("held execution reinspected")):
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(preview), codes={"UNCERTAIN_REQUEST_HELD"})
                launch.assert_not_called()

    def test_java_requires_jdk_before_any_persistent_attempt(self):
        with recheck_fixture(("java",)) as (root, manager, fixtures):
            self.assertIsNone(manager.jdk_home)
            preview = self.preview(root, manager, fixtures["java"])
            with fake_recheck(manager) as (_, launch):
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(preview), codes={"JDK_REQUIRED"})
                launch.assert_not_called()

    def test_start_failure_retains_pins_and_blocks_legacy_start_without_retry(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            original = private_hashes(fixture["job_dir"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager, OSError(PRIVATE_SENTINEL)) as (_, launch):
                with self.assertRaisesRegex(Refused, "^RECHECK_START_FAILED$"):
                    manager.recheck_start(recheck_request(preview))
                rows = manager.rechecks(fixture["workspace_id"])["rechecks"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "FAILED")
                self.assertEqual(rows[0]["creation_sha256"], fixture["creation_sha256"])
                self.assertEqual(manager.admission(), "RECHECK_ACTIVE_OR_UNRESOLVED")
                self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(preview), codes={"RECHECK_PREVIEW_REQUIRED"})
                self.assert_no_write_refusal(root, manager.start, {"project": "arithmetic", "model": "scripted-demo", "goal": manager.projects["arithmetic"]["definition"]["goal"]}, codes={"RECHECK_ACTIVE_OR_UNRESOLVED"})
                launch.assert_called_once()
            self.assertEqual(original, private_hashes(fixture["job_dir"]))

    def test_worker_failure_written_during_poll_is_retained_instead_of_interrupted(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(preview))
                path = attempt_path(manager, started["id"]) / "receipt.json"

                def complete():
                    value = json.loads(path.read_bytes()); value.update(status="FAILED", reason="RECHECK_CHECKS_FAILED", finished=100)
                    path.write_bytes(canonical(value))
                    return 1

                child.poll.side_effect = complete
                result = manager.recheck_view(started["id"])
                self.assertEqual((result["status"], result["reason"], result["owned_active"]), ("FAILED", "RECHECK_CHECKS_FAILED", False))
                self.assertEqual(manager.admission(), "RECHECK_ACTIVE_OR_UNRESOLVED")

    def test_owned_stop_preserves_creation_and_cannot_signal_unowned_history(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            original = private_hashes(fixture["job_dir"])
            preview = self.preview(root, manager, fixture)
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(preview))
                child.wait.side_effect = lambda **_: setattr(child.poll, "return_value", -15)
                with patch("workbench.os.killpg") as signal_group:
                    result = manager.recheck_stop(started["id"])
                    signal_group.assert_called_once()
                self.assertEqual((result["status"], result["owned_active"]), ("INTERRUPTED", False))
                with patch("workbench.os.killpg", side_effect=AssertionError("unowned process signal")):
                    self.assert_no_write_refusal(root, manager.recheck_stop, started["id"], codes={"NO_OWNED_ACTIVE_RECHECK"})
                self.assertEqual(manager.admission(), "RECHECK_ACTIVE_OR_UNRESOLVED")
            self.assertEqual(original, private_hashes(fixture["job_dir"]))

    def test_malformed_saved_recheck_receipts_block_without_rewriting_creation(self):
        for value in [[], 42, {"status": []}, {"status": "VERIFIED"}]:
            with self.subTest(value=value), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                old = private_hashes(fixture["job_dir"])
                with fake_recheck(manager):
                    started = manager.recheck_start(recheck_request(preview))
                    path = attempt_path(manager, started["id"]) / "receipt.json"
                    if isinstance(value, dict):
                        changed = json.loads(path.read_bytes()); changed.update(value)
                    else:
                        changed = value
                    path.write_bytes(canonical(changed))
                    self.assert_no_write_refusal(root, manager.recheck_view, started["id"], codes={"RECHECK_RECORD_INVALID"})
                    self.assertEqual(manager.admission(), "RECHECK_NEEDS_INSPECTION")
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
                    started = first.recheck_start(recheck_request(preview))
            finally:
                first.close()
            restarted = Manager(config, data)
            try:
                before = private_hashes(root)
                result = restarted.recheck_view(started["id"])
                self.assertEqual((result["status"], result["owned_active"]), ("PREPARING", False))
                self.assertEqual(restarted.admission(), "RECHECK_ACTIVE_OR_UNRESOLVED")
                with patch("workbench.os.killpg", side_effect=AssertionError("restart process ownership")):
                    self.assert_no_write_refusal(root, restarted.recheck_stop, started["id"], codes={"NO_OWNED_ACTIVE_RECHECK"})
                self.assertEqual(before, private_hashes(root))
            finally:
                restarted.close()

    def test_unknown_workspace_ids_and_bounded_history_never_execute(self):
        with recheck_fixture() as (root, manager, _):
            with recheck_preview_guard(manager):
                for workspace_id in [None, "../outside", "g" * 16]:
                    with self.subTest(workspace_id=workspace_id):
                        self.assert_no_write_refusal(root, manager.recheck_preview, {"workspace_id": workspace_id}, codes={"RECHECK_ID"})
                self.assert_no_write_refusal(root, manager.recheck_preview, {"workspace_id": "f" * 16}, codes={"RECHECK_CREATION_REQUIRED"})
            for number in range(201):
                (manager.data / "workspace-rechecks" / f"{number:016x}").mkdir()
            self.assert_no_write_refusal(root, manager.rechecks, "f" * 16, codes={"RECHECK_LIMIT"})
            self.assertEqual(manager.admission(), "RECHECK_NEEDS_INSPECTION")

    def test_start_reserves_history_count_and_receipt_budget_before_writing(self):
        for mode, count, padding in [("count", 200, 0), ("aggregate", 8, 235000)]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                for number in range(count):
                    attempt_id = f"{number:016x}"
                    directory = attempt_path(manager, attempt_id)
                    directory.mkdir(mode=0o700)
                    receipt = {"version": 1, "format": "outlands-workspace-recheck-v1", "id": attempt_id,
                        "workspace_id": fixture["workspace_id"], "status": "VERIFIED", "created": 1, "finished": 2,
                        "source_applied": False, "workspace_modified": False,
                        "checked_files": {"arithmetic.py": "a" * 64},
                        "checks": {"unit": {"exit_code": 0, "tests_ran": 1, "timed_out": False,
                            "output_limited": False, "infrastructure_error": False, "output": ""}},
                        **{key: "a" * 64 for key in ["creation_sha256", "preview_sha256", "history_sha256",
                            "snapshot_sha256", "task_sha256", "bundle_sha256", "config_sha256", "checks_sha256"]}}
                    if padding:
                        receipt["invented_saved_padding"] = "x" * padding
                    write_new(directory / "receipt.json", canonical(receipt))
                preview = self.preview(root, manager, fixture)
                inspected = {"summary": preview["inspection"],
                    "task": manager.projects[fixture["project_id"]]["definition"]}
                with fake_recheck(manager) as (_, launch), patch.object(manager, "_recheck_inspection", return_value=inspected):
                    self.assert_no_write_refusal(root, manager.recheck_start, recheck_request(preview), codes={"RECHECK_LIMIT"})
                    launch.assert_not_called()
                self.assertEqual(len(list((manager.data / "workspace-rechecks").iterdir())), count)


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


class WorkspaceRecheckHTTPTests(unittest.TestCase):
    def test_preview_start_history_view_contracts_are_scoped(self):
        with recheck_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]
            before = private_hashes(root)
            with recheck_preview_guard(manager):
                code, preview = request("POST", "/api/workspace-recheck-preview", {"workspace_id": fixture["workspace_id"]})
            self.assertEqual(code, 200)
            self.assertEqual(before, private_hashes(root))
            with fake_recheck(manager):
                code, started = request("POST", "/api/workspace-recheck-start", recheck_request(preview))
                self.assertEqual((code, started["status"]), (200, "PREPARING"))
                code, history = request("GET", "/api/workspace-rechecks/" + fixture["workspace_id"])
                self.assertEqual(code, 200)
                self.assertEqual(history["rechecks"][0]["id"], started["id"])
                code, view = request("GET", "/api/workspace-recheck/" + started["id"])
                self.assertEqual((code, view["owned_active"]), (200, True))

    def test_json_framing_and_security_guards_precede_manager_invocation(self):
        with recheck_http_fixture() as (root, manager, fixtures, request):
            fixture, before = fixtures["python"], private_hashes(root)
            bodies = [("preview", "recheck_preview", {"workspace_id": fixture["workspace_id"]}),
                      ("start", "recheck_start", {"preview_id": "1" * 16, "preview_sha256": "a" * 64}),
                      ("stop", "recheck_stop", {"id": "1" * 16})]
            with no_provider_calls():
                for endpoint, method, body in bodies:
                    path = "/api/workspace-recheck-" + endpoint
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
                    code, value = request("POST", "/api/workspace-recheck-preview", bodies[0][2], headers)
                    self.assertEqual((code, value["error"]), (409, reason))
            self.assertEqual(before, private_hashes(root))


class RecheckReceiptReplacementTests(unittest.TestCase):
    """Saved receipt reader regressions; all checks and child identities are invented.

    These cases run no worker, compiler, project check, provider, network or Git
    command. A temporary-file replacement models the existing atomic writer.
    """

    @contextmanager
    def receipt_fixture(self, *, java=False, exited=False):
        with tempfile.TemporaryDirectory() as directory, no_provider_calls(), ExitStack() as stack:
            guarded = []
            for name in ["workbench.subprocess.Popen", "workbench.subprocess.run", "workbench.os.killpg",
                         "workbench.process_stamp", "workbench.replace_json", "agent.Session.run",
                         "agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.git",
                         "git_workspace.fixed_checks"]:
                guarded.append(stack.enter_context(patch(name, side_effect=AssertionError("saved-reader execution or writer"))))
            root = Path(directory)
            paths = init_demo(root / "workspace", None)
            manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
            identifier, workspace_id = "a" * 16, "b" * 16
            attempt = manager.data / "workspace-rechecks" / identifier
            attempt.mkdir(mode=0o700)
            initial = {"version": 1, "format": "outlands-workspace-recheck-v1", "id": identifier,
                "workspace_id": workspace_id, "status": "PREPARING", "created": 1,
                "source_applied": False, "workspace_modified": False,
                "creation_sha256": "c" * 64, "preview_sha256": "d" * 64, "history_sha256": "e" * 64}
            spec = {"kind": "java-main", "sources": ["sample/Sum.java", "sample/SumTest.java"],
                    "main_class": "sample.SumTest"} if java else "test_arithmetic.py"
            task = {"checks": {"unit": spec}}
            checks = passing_checks(None, task, None)
            files = {name: sha(("Invented selected reader bytes: " + name).encode()) for name in
                     (["sample/Sum.java", "sample/SumTest.java"] if java else ["arithmetic.py", "test_arithmetic.py"])}
            verified = {**initial, "status": "VERIFIED", "finished": 2, "checks": checks,
                "snapshot_sha256": "f" * 64, "checked_files": files, "task_sha256": sha(canonical(task)),
                "bundle_sha256": sha(b"Invented reader bundle"), "config_sha256": sha(manager.config_raw),
                "checks_sha256": sha(canonical(checks))}
            self.assertTrue(controller.valid_recheck_receipt(initial))
            self.assertTrue(controller.valid_recheck_receipt(verified))
            path = attempt / "receipt.json"
            write_new(path, canonical(initial))
            child = Mock(); child.pid = 99999999; child.poll.return_value = 0 if exited else None
            log = io.BytesIO()
            manager.recheck_children[identifier] = (child, log)
            try:
                yield root, manager, identifier, path, verified, child, log, guarded
            finally:
                manager.recheck_children.pop(identifier, None)
                log.close()
                manager.close()
                for guard in guarded:
                    guard.assert_not_called()

    @contextmanager
    def replacement_window(self, root, path, replace):
        original_open, original_fstat = os.open, os.fstat
        evidence = {"attempts": 0, "fds": [], "last_committed": None}

        def opened(name, flags, *args, **kwargs):
            target = name == "receipt.json" and kwargs.get("dir_fd") is not None
            if target:
                evidence["attempts"] += 1
            fd = original_open(name, flags, *args, **kwargs)
            if target:
                evidence["fds"].append(fd)
                replace(evidence["attempts"])
                evidence["last_committed"] = private_hashes(root)
            return fd

        with patch.object(controller.os, "open", side_effect=opened):
            yield evidence
        for fd in set(evidence["fds"]):
            with self.assertRaises(OSError) as closed:
                original_fstat(fd)
            self.assertEqual(closed.exception.errno, 9)
        if evidence["last_committed"] is not None:
            self.assertEqual(private_hashes(root), evidence["last_committed"])

    @staticmethod
    def commit(path, raw):
        stage = path.with_name(path.name + ".next")
        write_new(stage, raw)
        os.replace(stage, path)

    def assert_custody(self, manager, identifier, child, log, *, exited):
        child.poll.assert_called_once_with()
        child.terminate.assert_not_called(); child.kill.assert_not_called(); child.wait.assert_not_called()
        self.assertEqual(identifier in manager.recheck_children, not exited)
        self.assertEqual(log.closed, exited)
        if not exited:
            self.assertIs(manager.recheck_children[identifier][0], child)

    def test_atomic_replacement_adopts_new_python_java_receipt_for_live_or_exited_child(self):
        for java in (False, True):
            for exited in (False, True):
                with self.subTest(java=java, exited=exited), self.receipt_fixture(java=java, exited=exited) as data:
                    root, manager, identifier, path, verified, child, log, _ = data
                    def replace(attempt):
                        if attempt == 1:
                            self.commit(path, canonical(verified))
                    with self.replacement_window(root, path, replace) as evidence:
                        result = manager.recheck_view(identifier)
                    self.assertEqual(evidence["attempts"], 2)
                    self.assertEqual(result, {**verified, "owned_active": not exited})
                    self.assertEqual(path.read_bytes(), canonical(verified))
                    self.assert_custody(manager, identifier, child, log, exited=exited)

    def test_reopened_invalid_and_unsafe_replacements_still_refuse_without_fallback(self):
        for kind in ("json", "schema", "id", "nul", "utf8", "limit", "hardlink", "symlink", "directory", "missing"):
            with self.subTest(kind=kind), self.receipt_fixture(exited=True) as data:
                root, manager, identifier, path, verified, child, log, _ = data
                outside = root / "invented-replacement.json"
                if kind in {"hardlink", "symlink"}:
                    write_new(outside, canonical(verified))
                def replace(attempt):
                    if attempt != 1:
                        return
                    if kind in {"hardlink", "symlink", "directory", "missing"}:
                        path.unlink()
                        if kind == "hardlink": path.hardlink_to(outside)
                        elif kind == "symlink": path.symlink_to(outside)
                        elif kind == "directory": path.mkdir(mode=0o700)
                        return
                    changed = dict(verified)
                    if kind == "schema": changed["checks"] = {"unit": {**verified["checks"]["unit"], "tests_ran": True}}
                    if kind == "id": changed["id"] = "c" * 16
                    raw = {"json": b"{", "nul": b"a\x00b", "utf8": b"\xff", "limit": b"x" * 262145}.get(kind, canonical(changed))
                    self.commit(path, raw)
                with self.replacement_window(root, path, replace) as evidence:
                    with self.assertRaisesRegex(Refused, "^RECHECK_RECORD_INVALID$"):
                        manager.recheck_view(identifier)
                self.assertEqual(evidence["attempts"], 2)
                self.assert_custody(manager, identifier, child, log, exited=True)

    def test_two_unlinked_descriptors_refuse_after_exactly_two_opens(self):
        with self.receipt_fixture() as data:
            root, manager, identifier, path, verified, child, log, _ = data
            def replace(_attempt):
                self.commit(path, canonical(verified))
            with self.replacement_window(root, path, replace) as evidence:
                with self.assertRaisesRegex(Refused, "^RECHECK_RECORD_INVALID$"):
                    manager.recheck_view(identifier)
            self.assertEqual(evidence["attempts"], 2)
            self.assertEqual(path.read_bytes(), canonical(verified))
            self.assert_custody(manager, identifier, child, log, exited=False)

    def test_default_reader_and_ordinary_invalid_original_never_retry(self):
        with self.receipt_fixture() as data:
            root, manager, identifier, path, verified, child, log, _ = data
            def replace(attempt):
                if attempt == 1:
                    self.commit(path, canonical(verified))
            with self.replacement_window(root, path, replace) as evidence:
                with self.assertRaisesRegex(Refused, "^INPUT_TYPE$"):
                    controller.readiness_read_file(path.parent, path.name, 262144)
            self.assertEqual(evidence["attempts"], 1)
            child.poll.assert_not_called()
            self.assertIs(manager.recheck_children[identifier][0], child)
            self.assertFalse(log.closed)
        for raw in (b"{", canonical({"status": "VERIFIED"})):
            with self.subTest(raw=raw[:16]), self.receipt_fixture() as data:
                root, manager, identifier, path, _verified, child, log, _ = data
                path.write_bytes(raw)
                with self.replacement_window(root, path, lambda _: None) as evidence:
                    with self.assertRaisesRegex(Refused, "^RECHECK_RECORD_INVALID$"):
                        manager.recheck_view(identifier)
                self.assertEqual(evidence["attempts"], 1)
                self.assert_custody(manager, identifier, child, log, exited=False)


if __name__ == "__main__":
    unittest.main()

