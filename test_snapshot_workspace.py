"""Invented snapshot exports and private Git workspaces; unit checkers are fakes."""

import copy
import io
import json
import os
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha
from bundle_project_check import ReadIssue
from git_workspace import git
from test_bundle_workspace import passed, tree
from test_snapshot_project_check import fixture as project_fixture, packet
import snapshot_workspace as workspace


PRIVATE = "invented-private-snapshot-workspace-output-18f2"


@contextmanager
def fixture(**kwargs):
    with project_fixture(**kwargs) as (root, source, task, raw, before, after, task_path, _):
        yield root, source, task, canonical(task), raw, before, after, task_path


def stage(root, source, task_raw, raw, task_path, identifier="a" * 16):
    config_path = root / "config.json"
    config_raw = canonical({"format": "outlands-workbench-config-v1", "models": [], "projects": [{
        "id": "invented", "name": "Invented private snapshot project", "source": str(source), "task": str(task_path)}]})
    config_path.write_bytes(config_raw)
    summary = workspace.prepare(raw, source, task_raw)["summary"]
    request = {"version": 1, "id": identifier, "project_id": "invented", "source": str(source),
        "config_path": str(config_path), "config_sha256": sha(config_raw), "task_path": str(task_path),
        "task_sha256": sha(task_raw), "archive_sha256": sha(raw)}
    binding = {"version": 1, "project_id": request["project_id"], "archive_sha256": request["archive_sha256"],
               "task_sha256": request["task_sha256"], "config_sha256": request["config_sha256"], "prepared": summary}
    request["preview_sha256"] = sha(canonical(binding))
    initial = {"version": 1, "format": workspace.FORMAT, "status": "PREPARING", "created": 1, "source_applied": False,
               "patch_sha256": summary["patch_sha256"], **{key: request[key] for key in
                   ("id", "project_id", "config_sha256", "task_sha256", "archive_sha256", "preview_sha256")}}
    job = root / "jobs" / identifier;job.mkdir(mode=0o700, parents=True)
    for name, content in (("receipt.json", canonical(initial)), ("request.json", canonical(request)),
                          ("task.json", task_raw), ("snapshot.zip", raw)):
        (job / name).write_bytes(content)
    return job, request, initial


def change(path, function):
    value = json.loads(path.read_bytes());function(value);path.write_bytes(canonical(value))


class SnapshotWorkspaceTests(unittest.TestCase):
    def refused(self, operation, *args, code=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            operation(*args, **kwargs)
        self.assertIn(str(caught.exception), workspace.CODES)
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(str(caught.exception), "SNAPSHOT_WORKSPACE_" + code)

    def test_python_java_prepare_exact_baseline_snapshot_and_compact_private_summary(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (root, source, task, task_raw, raw, before, after, _):
                prior = tree(root)
                result = workspace.prepare(raw, source, task_raw, sha(raw))
                self.assertEqual(set(result), {"summary", "task", "baseline", "snapshot"})
                self.assertEqual(result["baseline"], before);self.assertEqual(result["snapshot"], after);self.assertEqual(result["task"], task)
                summary = result["summary"]
                self.assertEqual(summary["baseline"], {name: sha(value) for name, value in before.items()})
                self.assertEqual(summary["snapshot"], {name: sha(value) for name, value in after.items()})
                self.assertEqual(summary["archive_sha256"], sha(raw));self.assertEqual(summary["task_sha256"], sha(task_raw))
                self.assertFalse(summary["source_applied"])
                self.assertLessEqual(len(canonical(summary)), 65536)
                self.assertNotIn(str(root), canonical(summary).decode());self.assertNotIn(task["goal"], canonical(summary).decode())
                self.assertEqual(tree(root), prior)
                result["task"]["editable"].clear()
                self.assertTrue(workspace.prepare(raw, source, task_raw)["task"]["editable"])

    def test_utf8_crlf_no_final_lf_empty_files_and_multiple_hunks_are_exact(self):
        long = b"".join(("# line %02d\n" % n).encode() for n in range(35))
        cases = [(b"old", b"new"), (b"old\n", "new café😀".encode()),
                 (b"first\r\nlast\r\n", "café😀\r\nlast\r\n".encode()), (b"", b"new\n"),
                 (b"deleted\n", b""), (long, long.replace(b"line 02", b"change02").replace(b"line 30", b"change30"))]
        for old, new in cases:
            before = {"main.py": old, "test_main.py": b"# protected\n"};after = {**before, "main.py": new}
            with self.subTest(old=old[:12]), fixture(before=before, after=after) as (_, source, _, task_raw, raw, _, _, _):
                self.assertEqual(workspace.prepare(raw, source, task_raw)["snapshot"], after)

    def test_execution_requires_actual_and_configured_baseline_not_tested_mixed_or_different(self):
        for kind in ("tested", "mixed", "different", "task-pin"):
            with self.subTest(kind=kind), fixture() as (_, source, task, task_raw, raw, _, after, _):
                if kind == "tested":
                    for name, value in after.items():(source / name).write_bytes(value)
                elif kind == "mixed":(source / "other.py").write_bytes(after["other.py"])
                elif kind == "different":(source / "main.py").write_bytes(b"different\n")
                else:task["files"]["main.py"] = sha(after["main.py"]);task_raw = canonical(task)
                self.refused(workspace.prepare, raw, source, task_raw, code="BASELINE_REQUIRED")

    def test_profile_mismatch_refuses_before_any_selected_source_read(self):
        for kind in ("scope", "permissions", "checks", "budgets"):
            with self.subTest(kind=kind), fixture() as (_, source, task, _, raw, _, _, _):
                if kind == "scope":task["files"]["extra.py"] = sha(b"not approved")
                elif kind == "permissions":task["editable"].remove("other.py")
                elif kind == "checks":task["checks"]["other"] = "test_main.py"
                else:task["request_seconds"] += 1
                with patch("snapshot_project_check.read_selected", side_effect=AssertionError("profile source")), \
                     patch.object(workspace, "read_selected", side_effect=AssertionError("profile source")):
                    self.refused(workspace.prepare, raw, source, canonical(task))

    def test_invalid_archive_or_external_digest_is_checked_before_task_and_source(self):
        with fixture() as (_, source, _, task_raw, raw, _, _, _):
            with patch.object(workspace, "_task", side_effect=AssertionError("task read")), \
                 patch.object(workspace, "read_selected", side_effect=AssertionError("source read")):
                self.refused(workspace.prepare, b"not a snapshot", source, task_raw, code="ARCHIVE_INVALID")
                self.refused(workspace.prepare, raw, source, task_raw, "0" * 64, code="ARCHIVE_CHANGED")

    def test_second_baseline_read_drift_and_unsafe_read_issue_are_fixed(self):
        for kind in ("changed", "link"):
            with self.subTest(kind=kind), fixture() as (_, source, _, task_raw, raw, _, _, _):
                real_read = workspace.read_selected
                def changed(root, name, limit=32768):
                    if kind == "link":raise ReadIssue("UNREADABLE")
                    return real_read(root, name, limit) + b"# changed\n"
                with patch.object(workspace, "read_selected", changed):
                    self.refused(workspace.prepare, raw, source, task_raw, code="SOURCE_CHANGED")

    def test_protected_archive_wrong_patch_unsafe_source_and_over_limit_are_ineligible(self):
        for kind in ("protected", "patch", "source-link", "binary", "limit"):
            with self.subTest(kind=kind), fixture() as (root, source, task, task_raw, raw, before, after, _):
                if kind == "protected":
                    def modify(value):
                        row = next(row for row in value["files"] if row["path"] == "test_main.py")
                        row.update(snapshot_sha256=sha(b"bad"), changed=True)
                    raw, _ = packet(before, after, task["editable"], modify=modify)
                elif kind == "patch":
                    from agent import review_diff
                    bad = "".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode().replace(b"-    return 1", b"-    return 9")
                    raw, _ = packet(before, after, task["editable"], patch_raw=bad)
                elif kind == "source-link":
                    target = source / "main.py";saved = root / "saved";target.rename(saved);target.symlink_to(saved)
                elif kind == "binary":(source / "main.py").write_bytes(b"x\0y")
                else:(source / "main.py").write_bytes(b"x" * 32769)
                self.refused(workspace.prepare, raw, source, task_raw)

    def test_prepare_has_no_filesystem_mutation_scan_git_checks_network_or_hold_access(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, _):
            prior, real_open = tree(root), os.open
            def readonly(path, flags, *args, **kwargs):
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC));return real_open(path, flags, *args, **kwargs)
            with patch("os.open", readonly), patch("os.scandir", side_effect=AssertionError("scan")), \
                 patch("subprocess.run", side_effect=AssertionError("Git/process")), patch("socket.socket", side_effect=AssertionError("provider")), \
                 patch("git_workspace.fixed_checks", side_effect=AssertionError("checks")):
                workspace.prepare(raw, source, task_raw)
            self.assertEqual(tree(root), prior)

    def test_maximum32_file_scope_and_exact_total_are_preserved(self):
        before = {"main.py": b"1" * 4096, "test_main.py": b"#" * 4096, **{"f%02d.py" % n: b"x" * 4096 for n in range(30)}}
        after = {**before, "main.py": b"2" * 4096}
        with fixture(before=before, after=after) as (_, source, _, task_raw, raw, _, _, _):
            prepared = workspace.prepare(raw, source, task_raw)
            self.assertEqual(len(prepared["snapshot"]), 32)
            self.assertEqual(prepared["summary"]["baseline_bytes"], 131072)
            self.assertEqual(prepared["summary"]["snapshot_bytes"], 131072)
            self.assertLessEqual(len(canonical(prepared["summary"])), 65536)

    def test_python_java_worker_creates_distinct_selected_git_workspace_and_preserves_original(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (root, source, task, task_raw, raw, before, after, task_path):
                git(source, "init", "--object-format=sha1", "--initial-branch=original")
                git(source, "add", "--", *sorted(task["files"]));git(source, "commit", "--no-verify", "-m", "Invented original source")
                (source / "unrelated-private.txt").write_bytes(PRIVATE.encode())
                original = tree(source)
                job, _, _ = stage(root, source, task_raw, raw, task_path)
                def checker(work, selected, jdk):
                    self.assertEqual({name: (work / name).read_bytes() for name in selected["files"]}, after)
                    self.assertEqual(jdk, Path("/invented/jdk") if java else None)
                    return passed(work, selected, jdk)
                receipt = workspace.build(job, Path("/invented/jdk") if java else None, checker)
                self.assertTrue(workspace.valid_receipt(receipt));self.assertEqual(receipt["status"], "VERIFIED")
                self.assertEqual(receipt["format"], "outlands-snapshot-workspace-v1")
                self.assertEqual(receipt["branch"], "outlands/snapshot-" + job.name)
                self.assertEqual(receipt["baseline"], {name: sha(value) for name, value in before.items()})
                self.assertEqual(receipt["snapshot"], {name: sha(value) for name, value in after.items()})
                self.assertFalse(receipt["source_applied"]);self.assertTrue(receipt["patch_applied_to_workspace"])
                self.assertEqual(tree(source), original)
                work = Path(receipt["path"])
                self.assertEqual(git(work, "rev-parse", "HEAD").decode().strip(), receipt["baseline_commit"])
                self.assertEqual(git(work, "diff", "--cached", "--name-only"), b"")
                names = {p.relative_to(work).as_posix() for p in work.rglob('*') if p.is_file()}
                self.assertEqual(names, set(task["files"]) | {".git"})
                self.assertEqual((job / "initial-receipt.json").read_bytes(), canonical(json.loads((job / "initial-receipt.json").read_bytes())))

    def test_missing_java_prerequisite_refuses_before_git_or_workspace_creation(self):
        with fixture(java=True) as (root, source, _, task_raw, raw, _, _, task_path):
            job, _, initial = stage(root, source, task_raw, raw, task_path)
            with patch.object(workspace, "git", side_effect=AssertionError("Git before prerequisite")):
                self.refused(workspace.build, job, checker=passed, code="CHECKS_FAILED")
            self.assertFalse((job / "workspace").exists())
            failed = json.loads((job / "receipt.json").read_bytes())
            self.assertTrue(workspace.valid_receipt(failed))
            for key in workspace.PIN_FIELDS:self.assertEqual(failed[key], initial[key])

    def test_early_request_errors_keep_initial_identity_pins_and_do_not_read_new_paths_or_git(self):
        for kind in ("malformed", "unknown", "version", "id", "pin", "private-path"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, _, initial = stage(root, source, task_raw, raw, task_path)
                if kind == "malformed":(job / "request.json").write_bytes(b"[]")
                elif kind == "unknown":change(job / "request.json", lambda r: r.update(private=PRIVATE))
                elif kind == "version":change(job / "request.json", lambda r: r.update(version=True))
                elif kind == "id":change(job / "request.json", lambda r: r.update(id="b" * 16))
                elif kind == "pin":change(job / "request.json", lambda r: r.update(archive_sha256="f" * 64))
                else:change(job / "request.json", lambda r: r.update(config_sha256="f" * 64, config_path="/unapproved/" + PRIVATE))
                reader = workspace._read_named
                def guarded(path, limit, **kwargs):
                    self.assertTrue(path.is_relative_to(job), "unvalidated external path")
                    return reader(path, limit, **kwargs)
                with patch.object(workspace, "_read_named", guarded), patch.object(workspace, "git", side_effect=AssertionError("early Git")):
                    self.refused(workspace.build, job, checker=passed)
                failed = json.loads((job / "receipt.json").read_bytes())
                self.assertEqual(failed["status"], "FAILED");self.assertTrue(workspace.valid_receipt(failed))
                for key in workspace.PIN_FIELDS | {"id", "project_id"}:self.assertEqual(failed[key], initial[key])

    def test_config_task_staged_archive_preview_and_patch_pins_refuse_before_git(self):
        for kind in ("config", "task", "staged-task", "archive", "preview", "patch"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, request, _ = stage(root, source, task_raw, raw, task_path)
                if kind == "config":Path(request["config_path"]).write_bytes(b"{}")
                elif kind == "task":task_path.write_bytes(task_raw + b" ")
                elif kind == "staged-task":(job / "task.json").write_bytes(task_raw + b" ")
                elif kind == "archive":(job / "snapshot.zip").write_bytes(raw[:-1])
                elif kind == "preview":
                    change(job / "request.json", lambda r: r.update(preview_sha256="f" * 64))
                    change(job / "receipt.json", lambda r: r.update(preview_sha256="f" * 64))
                else:change(job / "receipt.json", lambda r: r.update(patch_sha256="f" * 64))
                with patch.object(workspace, "git", side_effect=AssertionError("invalid pinned input reached Git")):
                    self.refused(workspace.build, job, checker=passed)
                self.assertTrue(workspace.valid_receipt(json.loads((job / "receipt.json").read_bytes())))
                self.assertFalse((job / "workspace").exists())

    def test_request_source_must_match_hash_pinned_config_before_following_source(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, task_path):
            job, _, _ = stage(root, source, task_raw, raw, task_path)
            change(job / "request.json", lambda r: r.update(source="/unapproved/" + PRIVATE))
            with patch.object(workspace, "prepare", side_effect=AssertionError("unapproved source")), \
                 patch.object(workspace, "git", side_effect=AssertionError("Git")):
                self.refused(workspace.build, job, checker=passed, code="PROJECT_CHANGED")

    def test_failed_checker_preserves_full_results_and_partial_workspace_without_retry(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, task_path):
            job, _, _ = stage(root, source, task_raw, raw, task_path)
            original = tree(source)
            def failing(work, task, jdk):
                rows = passed(work, task, jdk);rows["unit"].update(exit_code=1, output=PRIVATE);return rows
            self.refused(workspace.build, job, checker=failing, code="CHECKS_FAILED")
            failed = json.loads((job / "receipt.json").read_bytes())
            self.assertTrue(workspace.valid_receipt(failed));self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(json.loads((job / "checks.json").read_bytes())["unit"]["output"], PRIVATE)
            self.assertTrue(Path(failed["path"]).is_dir());self.assertEqual(tree(source), original)
            old = tree(job)
            with patch.object(workspace, "git", side_effect=AssertionError("retry")):
                self.refused(workspace.build, job, checker=lambda *_: self.fail("retried checker"))
            self.assertEqual(tree(job), old)

    def test_interrupt_systemexit_and_unexpected_errors_retain_fixed_early_pins(self):
        for error in (KeyboardInterrupt(), SystemExit(4), RuntimeError(PRIVATE)):
            with self.subTest(error=type(error)), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, _, initial = stage(root, source, task_raw, raw, task_path)
                def checker(*_):raise error
                self.refused(workspace.build, job, checker=checker)
                receipt = json.loads((job / "receipt.json").read_bytes())
                self.assertTrue(workspace.valid_receipt(receipt))
                self.assertEqual(receipt["status"], "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED")
                for key in workspace.PIN_FIELDS:self.assertEqual(receipt[key], initial[key])

    def test_large_unicode_output_is_privately_full_and_display_clipping_is_not_execution_limit(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, task_path):
            job, _, _ = stage(root, source, task_raw, raw, task_path)
            output = "😀" * 65536
            def checker(work, task, jdk):
                rows = passed(work, task, jdk);rows["unit"]["output"] = output;return rows
            receipt = workspace.build(job, checker=checker)
            self.assertEqual(len(receipt["checks"]["unit"]["output"]), 4096)
            self.assertTrue(receipt["checks"]["unit"]["display_truncated"])
            self.assertFalse(receipt["checks"]["unit"]["output_limited"])
            self.assertGreater((job / "checks.json").stat().st_size, 262144)
            self.assertEqual(json.loads((job / "checks.json").read_bytes())["unit"]["output"], output)
            self.assertLessEqual(len((job / "receipt.json").read_bytes()), 262144)

    def test_boolean_or_missing_metrics_cannot_verify(self):
        for change_row in (lambda rows: rows["unit"].update(tests_ran=True), lambda rows: rows["unit"].update(exit_code=False),
                           lambda rows: rows["unit"].update(output_limited=True), lambda rows: rows.clear()):
            with self.subTest(change=change_row), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, _, _ = stage(root, source, task_raw, raw, task_path)
                def checker(work, task, jdk):
                    rows = passed(work, task, jdk);change_row(rows);return rows
                self.refused(workspace.build, job, checker=checker, code="CHECKS_FAILED")
                self.assertTrue(workspace.valid_receipt(json.loads((job / "receipt.json").read_bytes())))

    def test_postcheck_source_config_task_request_and_archive_drift_retain_results(self):
        for kind in ("source", "config", "task", "request", "archive"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, request, _ = stage(root, source, task_raw, raw, task_path)
                def checker(work, task, jdk):
                    target = {"source": source / "main.py", "config": Path(request["config_path"]), "task": task_path,
                              "request": job / "request.json", "archive": job / "snapshot.zip"}[kind]
                    target.write_bytes(target.read_bytes() + b" ")
                    return passed(work, task, jdk)
                self.refused(workspace.build, job, checker=checker)
                receipt = json.loads((job / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED");self.assertTrue(workspace.valid_receipt(receipt))
                self.assertEqual(receipt["checks"]["unit"]["exit_code"], 0)
                self.assertTrue((job / "checks.json").is_file())

    def test_postcheck_snapshot_protected_extra_and_executable_drift_refuse(self):
        for kind in ("snapshot", "protected", "extra", "executable"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, _, _ = stage(root, source, task_raw, raw, task_path)
                def checker(work, task, jdk):
                    if kind == "extra":(work / "unexpected.txt").write_bytes(b"extra")
                    elif kind == "executable":(work / "main.py").chmod(0o700)
                    else:(work / ("test_main.py" if kind == "protected" else "main.py")).write_bytes(b"changed\n")
                    return passed(work, task, jdk)
                self.refused(workspace.build, job, checker=checker)
                receipt = json.loads((job / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED");self.assertTrue(workspace.valid_receipt(receipt))

    def test_modified_git_configuration_index_or_ref_is_refused_before_postcheck_git(self):
        for kind in ("config", "index", "ref", "pointer", "pointer-link"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, _, _ = stage(root, source, task_raw, raw, task_path)
                original_git = workspace.git;after_checks = False
                def guarded_git(*args):
                    self.assertFalse(after_checks, "unsafe altered Git metadata reached a Git command")
                    return original_git(*args)
                def checker(work, task, jdk):
                    nonlocal after_checks
                    common = job / "workspace/baseline-repo/.git"
                    target = {"config": common / "config", "index": common / "worktrees/review/index",
                              "ref": common / "refs/heads/baseline", "pointer": work / ".git", "pointer-link": work / ".git"}[kind]
                    if kind == "pointer-link":
                        saved = job / "saved-control";target.rename(saved);target.symlink_to(saved)
                    else:target.write_bytes(target.read_bytes() + b"# altered private control\n")
                    after_checks = True
                    return passed(work, task, jdk)
                with patch.object(workspace, "git", guarded_git), patch("bundle_workspace.git", guarded_git):
                    self.refused(workspace.build, job, checker=checker, code="GIT_CHANGED")

    def test_own_receipt_changed_during_checks_is_not_overwritten_and_next_is_retained(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, task_path):
            job, _, initial = stage(root, source, task_raw, raw, task_path)
            changed = {**initial, "created": 2}
            def checker(work, task, jdk):
                (job / "receipt.json").write_bytes(canonical(changed));return passed(work, task, jdk)
            self.refused(workspace.build, job, checker=checker, code="REQUEST_CHANGED")
            self.assertEqual((job / "receipt.json").read_bytes(), canonical(changed))
            self.assertTrue((job / "receipt.json.next").is_file())
            self.assertEqual((job / "initial-receipt.json").read_bytes(), canonical(initial))

    def test_valid_receipt_strict_shape_types_path_branch_and_checks(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, task_path):
            job, _, initial = stage(root, source, task_raw, raw, task_path)
            self.assertTrue(workspace.valid_receipt(initial))
            terminal = workspace.build(job, checker=passed)
            changes = [lambda r: r.update(version=True), lambda r: r.update(created=True), lambda r: r.update(source_applied=True),
                       lambda r: r.update(archive_sha256="bad"), lambda r: r.update(branch="outlands/bundle-" + job.name),
                       lambda r: r.update(path="relative/workspace/review"), lambda r: r.update(private=PRIVATE),
                       lambda r: r.update(baseline={}), lambda r: r.update(checks_sha256="bad"),
                       lambda r: r.update(baseline={".git/config": "f" * 64}, snapshot={".git/config": "e" * 64}),
                       lambda r: r.update(baseline={"x": "f" * 64, "x/a": "f" * 64}, snapshot={"x": "e" * 64, "x/a": "f" * 64}),
                       lambda r: r.update(snapshot=copy.deepcopy(r["baseline"])),
                       lambda r: r["checks"]["unit"].update(tests_ran=True), lambda r: r["checks"]["unit"].update(exit_code=False),
                       lambda r: r["checks"]["unit"].update(output_limited=True)]
            with patch("os.open", side_effect=AssertionError("receipt predicate performed IO")):
                for mutation in changes:
                    damaged = copy.deepcopy(terminal);mutation(damaged)
                    self.assertFalse(workspace.valid_receipt(damaged))
                self.assertFalse(workspace.valid_receipt({**initial, "checks": {}}))
                self.assertFalse(workspace.valid_receipt([]))

    def test_parent_start_failure_and_interruption_receipts_remain_inspectable(self):
        with fixture() as (root, source, _, task_raw, raw, _, _, task_path):
            _, _, initial = stage(root, source, task_raw, raw, task_path)
            failed = {**initial, "status": "FAILED", "finished": 2, "reason": "SNAPSHOT_WORKSPACE_START_FAILED"}
            self.assertTrue(workspace.valid_receipt(failed))
            self.assertTrue(workspace.valid_receipt({**failed, "status": "INTERRUPTED", "reason": "SNAPSHOT_WORKSPACE_INTERRUPTED"}))
            self.assertFalse(workspace.valid_receipt({**failed, "reason": PRIVATE}))
            self.assertFalse(workspace.valid_receipt({**failed, "status": "INTERRUPTED"}))

    def test_staged_binary_archive_links_and_nonprivate_job_refuse_without_git(self):
        for kind in ("archive-link", "archive-hard", "task-link", "job-mode"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, raw, _, _, task_path):
                job, _, _ = stage(root, source, task_raw, raw, task_path)
                if kind == "job-mode":job.chmod(0o755)
                else:
                    target = job / ("task.json" if kind == "task-link" else "snapshot.zip")
                    saved = root / "saved";target.rename(saved)
                    if kind == "archive-hard":os.link(saved, target)
                    else:target.symlink_to(saved)
                with patch.object(workspace, "git", side_effect=AssertionError("unsafe staging reached Git")):
                    self.refused(workspace.build, job, checker=passed)

    def test_cli_fixed_private_failures_and_signal_handler_success_path(self):
        for args in ([], ["--job-dir", "relative"], ["--job-dir", "/missing/" + PRIVATE],
                     ["--job-dir", "/tmp/job", "--job-dir", "/tmp/other"]):
            output = io.StringIO()
            with self.subTest(args=args), redirect_stdout(output):code = workspace.main(args)
            self.assertNotEqual(code, 0)
            self.assertNotIn(PRIVATE, output.getvalue())
            self.assertIn(json.loads(output.getvalue())["error"], workspace.CODES)
        with patch.object(workspace, "build", return_value={"status": "VERIFIED"}) as build:
            self.assertEqual(workspace.main(["--job-dir", "/tmp/invented-job"]), 0)
            build.assert_called_once_with(Path("/tmp/invented-job"), None)


if __name__ == "__main__":
    unittest.main()
