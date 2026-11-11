"""Real local Git operations on invented copies, without inference or project adoption."""

import os
import unittest
from pathlib import Path
from subprocess import Popen as RealPopen
from unittest.mock import Mock, patch

from agent import Refused, canonical, write_new
from git_workspace import build, git, validate_files
from test_workbench import decision, manager_fixture


def seeded(manager, run_id):
    manager.review(decision(manager, run_id))
    view = manager.view(run_id)
    receipt = {"status": "PREPARING", "result_sha256": view["result_sha256"],
               "patch_sha256": view["patch_sha256"], "source_applied": False}
    write_new(manager.run_path(run_id) / "git-workspace.json", canonical(receipt))
    return receipt


def success_check(work, task, jdk):
    del work, task, jdk
    return {"unit": {"exit_code": 0, "tests_ran": 4, "timed_out": False,
                     "output_limited": False, "infrastructure_error": False}}


def create(manager, run_id, checker=success_check):
    receipt = seeded(manager, run_id)
    return build(manager.run_path(run_id), manager.data / "workspaces" / run_id,
                 manager.projects["arithmetic"]["source"], receipt["result_sha256"],
                 receipt["patch_sha256"], checker=checker)


class WorkspaceTests(unittest.TestCase):
    def test_real_worktree_preserves_existing_project_git_and_bytes(self):
        with manager_fixture(seed=True) as (root, manager, run_id):
            source = manager.projects["arithmetic"]["source"]
            empty = root / "empty"; empty.mkdir()
            git(source, "init", "--initial-branch=owner", "--template=" + str(empty))
            git(source, "add", "--", "calculator.py", "test_calculator.py")
            git(source, "commit", "--no-verify", "-m", "Invented original")
            original_head = git(source, "rev-parse", "HEAD")
            original_status = git(source, "status", "--porcelain=v1", "-z")
            original_bytes = (source / "calculator.py").read_bytes()
            result = create(manager, run_id)
            work = Path(result["path"])
            self.assertTrue((work / ".git").is_file())
            self.assertIn("return a + b", (work / "calculator.py").read_text())
            self.assertEqual((source / "calculator.py").read_bytes(), original_bytes)
            self.assertEqual(git(source, "rev-parse", "HEAD"), original_head)
            self.assertEqual(git(source, "status", "--porcelain=v1", "-z"), original_status)
            self.assertFalse(result["source_applied"])
            self.assertTrue(result["patch_applied_to_workspace"])

    def test_changed_workspace_blocks_idempotent_reuse(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            result = create(manager, run_id)
            (Path(result["path"]) / "calculator.py").write_text("changed\n")
            with self.assertRaisesRegex(Refused, "WORKSPACE_BYTES_CHANGED"):
                manager.create_workspace({"id": run_id, "result_sha256": result["result_sha256"], "patch_sha256": result["patch_sha256"]})

    def test_repeated_accepted_request_does_not_spawn_or_apply_again(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            result = create(manager, run_id)
            with patch("workbench.subprocess.Popen", wraps=RealPopen) as spawn:
                again = manager.create_workspace({"id": run_id, "result_sha256": result["result_sha256"], "patch_sha256": result["patch_sha256"]})
                self.assertTrue(all(call.args[0][0] == "/usr/bin/git" and "apply" not in call.args[0] for call in spawn.call_args_list))
            self.assertEqual(result, again)

    def test_unaccepted_and_stale_artifacts_refused_before_creation(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            view = manager.view(run_id)
            request = {"id": run_id, "result_sha256": view["result_sha256"], "patch_sha256": view["patch_sha256"]}
            with self.assertRaisesRegex(Refused, "REVIEW_REQUIRED"):
                manager.create_workspace(request)
            manager.review(decision(manager, run_id))
            request["patch_sha256"] = "0" * 64
            with self.assertRaisesRegex(Refused, "PATCH_CHANGED"):
                manager.create_workspace(request)
            self.assertFalse((manager.run_path(run_id) / "git-workspace.json").exists())

    def test_failing_recheck_retains_workspace_and_blocks_new_task(self):
        def failed(work, task, jdk):
            value = success_check(work, task, jdk); value["unit"]["exit_code"] = 1
            return value
        with manager_fixture(seed=True) as (_, manager, run_id):
            with self.assertRaisesRegex(Refused, "WORKSPACE_CHECKS_FAILED"):
                create(manager, run_id, failed)
            receipt = manager.workspace_receipt(run_id)
            self.assertEqual(receipt["status"], "FAILED")
            self.assertEqual(receipt["checks"]["unit"]["exit_code"], 1)
            self.assertTrue((manager.data / "workspaces" / run_id / "review/calculator.py").exists())
            self.assertEqual(manager.admission(), "WORKSPACE_ACTIVE_OR_UNRESOLVED")

    def test_control_files_are_refused_case_insensitively(self):
        for name in [".git/config", ".Git/HEAD", ".gitattributes", "nested/.gitmodules", ".gitconfig"]:
            with self.assertRaisesRegex(Refused, "GIT_CONTROL_FILE_REFUSED"):
                validate_files({"files": {name: "0" * 64}})
        validate_files({"files": {".gitignore": "0" * 64, "src/normal.py": "1" * 64}})

    def test_exited_worker_marks_partial_attempt_failed_without_retry(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            seeded(manager, run_id)
            child, log = Mock(), Mock(); child.poll.return_value = 1
            manager.workspace_children[run_id] = (child, log)
            self.assertEqual(manager.workspace_receipt(run_id)["status"], "FAILED")
            log.close.assert_called_once()
            self.assertNotIn(run_id, manager.workspace_children)

    def test_review_change_blocked_while_workspace_preparing(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            seeded(manager, run_id)
            with self.assertRaisesRegex(Refused, "WORKSPACE_ACTIVE_OR_UNRESOLVED"):
                manager.review(decision(manager, run_id, "rejected"))

    def test_original_change_after_review_prevents_workspace(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            receipt = seeded(manager, run_id)
            source = manager.projects["arithmetic"]["source"]
            (source / "calculator.py").write_text("owner edit\n")
            with self.assertRaisesRegex(Refused, "ORIGINAL_SOURCE_CHANGED"):
                build(manager.run_path(run_id), manager.data / "workspaces" / run_id, source,
                      receipt["result_sha256"], receipt["patch_sha256"], checker=success_check)
            self.assertFalse((manager.data / "workspaces" / run_id).exists())

    def test_git_ignores_inherited_configuration_and_template_hooks(self):
        with manager_fixture(seed=True) as (root, manager, run_id):
            marker = root / "hook-ran"
            hooks = root / "host-hooks"; hooks.mkdir()
            hook = hooks / "post-commit"
            hook.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\n"); hook.chmod(0o700)
            config = root / "host-config"
            config.write_text("[core]\n hooksPath = " + str(hooks) + "\n")
            with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config), "GIT_TEMPLATE_DIR": str(hooks)}):
                create(manager, run_id)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
