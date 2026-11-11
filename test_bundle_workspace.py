"""Invented imported-bundle preparation and private Git jobs; checks are fakes."""

import copy
import difflib
import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, review_diff, sha
from bundle_project_check import ReadIssue
from bundle_workspace import FORMAT, build, main, prepare
from git_workspace import git
from patch_bundle import build_bundle


PRIVATE = "invented private checker output, never a provider claim"


def bundle_for(before, after, editable, *, java=False, patch_raw=None):
    checks = ({"unit": {"kind": "java-main", "sources": sorted(before), "main_class": "sample.ValueTest"}}
              if java else {"unit": "test_value.py"})
    task = {"format": "outlands-coding-agent-v2" if java else "outlands-coding-agent-v1", "goal": PRIVATE,
            "files": {name: sha(raw) for name, raw in before.items()}, "editable": editable,
            "checks": checks, "max_turns": 3, "request_seconds": 17}
    diff = ("".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode()
            if patch_raw is None else patch_raw)
    result = {"format": task["format"], "status": "REVIEW_READY", "source_adopted": False,
        "files": {name: {"before": sha(before[name]), "after": sha(after[name])} for name in before}, "patch_sha256": sha(diff)}
    result_raw = canonical(result)
    review = {"id": "2" * 16, "recorded": 1, "verdict": "accepted", "source_applied": False,
              "result_sha256": sha(result_raw), "patch_sha256": sha(diff), "note": PRIVATE}
    final = {"index": 9, "kind": "independent_final_checks", "value": {name: {
        "exit_code": 0, "tests_ran": 2, "timed_out": False, "output_limited": False,
        "infrastructure_error": False, "output": PRIVATE} for name in checks}}
    task_raw = canonical(task)
    archive = build_bundle(task_raw, result_raw, canonical(review), canonical(final), diff)
    return task, task_raw, archive


@contextmanager
def fixture(*, java=False, before=None, after=None, editable=None, patch_raw=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir(mode=0o700)
        if before is None:
            before = ({"sample/Value.java": b"package sample; class Value { static int value() { return 1; } }\n",
                       "sample/ValueTest.java": b"package sample; class ValueTest { public static void main(String[] args) {} }\n"}
                      if java else {"value.py": b"def value():\n    return 1\n", "test_value.py": b"import unittest\n# invented protected fixture\n"})
        editable = editable or ["sample/Value.java" if java else "value.py"]
        if after is None:
            after = {name: raw.replace(b"return 1", b"return 2") if name in editable else raw for name, raw in before.items()}
        for name, raw in before.items():
            target = source / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(raw)
        task, task_raw, archive = bundle_for(before, after, editable, java=java, patch_raw=patch_raw)
        yield root, source, task, task_raw, archive, before, after


def stage(root, source, task_raw, archive):
    task_path, config_path = root / "approved-task.json", root / "config.json"
    task_path.write_bytes(task_raw)
    config_raw = canonical({"format": "invented-private-config", "private": PRIVATE})
    config_path.write_bytes(config_raw)
    prepared = prepare(archive, source, task_raw, sha(archive))
    request = {"version": 1, "id": "a" * 16, "project_id": "invented", "source": str(source),
        "config_path": str(config_path), "config_sha256": sha(config_raw), "task_path": str(task_path),
        "task_sha256": sha(task_raw), "bundle_sha256": sha(archive)}
    binding = {"version": 1, "project_id": request["project_id"], "bundle_sha256": request["bundle_sha256"],
        "task_sha256": request["task_sha256"], "config_sha256": request["config_sha256"], "prepared": prepared["summary"]}
    request["preview_sha256"] = sha(canonical(binding))
    job = root / "jobs" / request["id"]
    job.mkdir(mode=0o700, parents=True)
    initial = {"version": 1, "format": FORMAT, "status": "PREPARING", "created": 1,
        "source_applied": False, "patch_sha256": prepared["summary"]["patch_sha256"],
        **{key: request[key] for key in ("id", "project_id", "config_sha256", "task_sha256", "bundle_sha256", "preview_sha256")}}
    for name, raw in (("receipt.json", canonical(initial)), ("request.json", canonical(request)),
                      ("task.json", task_raw), ("bundle.zip", archive)):
        (job / name).write_bytes(raw)
    return job, request, initial


def passed(work, task, jdk):
    del work, jdk
    return {name: {"exit_code": 0, "tests_ran": 2, "timed_out": False, "output_limited": False,
                  "infrastructure_error": False, "output": PRIVATE} for name in task["checks"]}


def tree(root):
    return {str(path.relative_to(root)): sha(path.read_bytes()) for path in root.rglob('*') if path.is_file()}


class PreparationTests(unittest.TestCase):
    def assert_refused(self, operation, *args, code=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            operation(*args, **kwargs)
        self.assertRegex(str(caught.exception), r"^(BUNDLE|PROJECT_CHECK|GIT_CONTROL_FILE)_[A-Z_]+$")
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(caught.exception.args, (code,))

    def test_python_java_preparation_reconstructs_exact_bytes_and_compact_summary(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (_, source, task, task_raw, archive, before, after):
                initial = tree(source)
                result = prepare(archive, source, task_raw, sha(archive))
                self.assertEqual(set(result), {"summary", "task", "baseline", "candidate"})
                self.assertEqual(result["baseline"], before)
                self.assertEqual(result["candidate"], after)
                self.assertEqual(result["task"], task)
                summary = result["summary"]
                self.assertEqual(summary["archive_sha256"], sha(archive))
                self.assertEqual(summary["task_sha256"], sha(task_raw))
                self.assertEqual(summary["baseline"], {name: sha(raw) for name, raw in before.items()})
                self.assertEqual(summary["candidate"], {name: sha(raw) for name, raw in after.items()})
                self.assertNotIn(PRIVATE, canonical(summary).decode())
                self.assertFalse(summary["source_applied"])
                self.assertLessEqual(len(canonical(summary)), 65536)
                self.assertEqual(tree(source), initial)
                result["task"]["editable"].clear()
                self.assertTrue(prepare(archive, source, task_raw)["task"]["editable"])

    def test_utf8_crlf_and_no_final_newline_apply_exactly(self):
        cases = [(b"old", b"new"), (b"old\n", b"new"), (b"old", b"new\n"),
                 (b"first\nlast", b"changed\nlast"), (b"first\r\nlast\r\n", b"changed\r\nlast\r\n"),
                 ("é😀 old\n".encode(), "é😀 new\n".encode()), (b"", b"created line\n"), (b"deleted\n", b"")]
        for old, new in cases:
            before = {"value.py": old, "test_value.py": b"# protected\n"}
            after = {**before, "value.py": new}
            with self.subTest(old=old), fixture(before=before, after=after) as (_, source, _, task_raw, archive, _, _):
                self.assertEqual(prepare(archive, source, task_raw)["candidate"]["value.py"], new)

    def test_multiple_hunks_multiple_files_insertions_and_deletions(self):
        original = b"".join(("line %s\n" % i).encode() for i in range(30))
        before = {"value.py": original, "other.py": b"one\ntwo\nthree\n", "test_value.py": b"# protected\n"}
        after = {"value.py": original.replace(b"line 1\n", b"changed 1\n").replace(b"line 25\n", b"changed 25\n"),
                 "other.py": b"new\none\nthree\n", "test_value.py": before["test_value.py"]}
        with fixture(before=before, after=after, editable=["other.py", "value.py"]) as (_, source, _, task_raw, archive, _, _):
            self.assertEqual(prepare(archive, source, task_raw)["candidate"], after)

    def test_bare_cr_and_unicode_line_separator_changes_are_explicitly_refused(self):
        for old, new in ((b"old\r", b"new\r"), ("old\u2028line\n".encode(), "new\u2028line\n".encode())):
            before = {"value.py": old, "test_value.py": b"# protected\n"}
            after = {**before, "value.py": new}
            with fixture(before=before, after=after) as (_, source, _, task_raw, archive, _, _):
                self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_PATCH_INVALID")

    def test_extra_metadata_binary_rename_mode_and_escaped_paths_are_refused(self):
        with fixture() as (_, _, _, _, archive, before, after):
            canonical_patch = "".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode()
        patches = [b"diff --git a/value.py b/value.py\n" + canonical_patch,
            b"old mode 100644\nnew mode 100755\n" + canonical_patch,
            b"rename from value.py\nrename to outside.py\n" + canonical_patch,
            b"GIT binary patch\n" + canonical_patch, canonical_patch.replace(b"a/value.py", b"a/../../escape.py"),
            canonical_patch + b"--- a/outside.py\n+++ b/outside.py\n@@ -0,0 +1 @@\n+outside\n",
            canonical_patch + b"index deadbeef..feedbeef\n"]
        for patch_raw in patches:
            with self.subTest(prefix=patch_raw[:20]), fixture(patch_raw=patch_raw) as (_, source, _, task_raw, archive, _, _):
                with patch("subprocess.run", side_effect=AssertionError("process")):
                    self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_PATCH_INVALID")

    def test_wrong_context_coordinates_and_markers_are_refused(self):
        with fixture() as (_, _, _, _, _, before, after):
            original = "".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode()
        variants = [original.replace(b" return 1", b" return 9"), original.replace(b"@@ -1,2 +1,2 @@", b"@@ -999999999999,2 +1,2 @@"),
                    original.replace(b"@@ -1,2 +1,2 @@", b"@@ -0,2 +1,2 @@"),
                    original.replace(b"@@ -1,2 +1,2 @@", b"@@ -1,3 +1,2 @@"), b"\\ No newline at end of file\n" + original]
        for raw in variants:
            with fixture(patch_raw=raw) as (_, source, _, task_raw, archive, _, _):
                self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_PATCH_INVALID")

    def test_semantically_applicable_but_noncanonical_context_is_refused(self):
        old = b"one\ntwo\nold\nfour\nfive\n"
        new = old.replace(b"old", b"new")
        patch_raw = "".join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
            fromfile="a/value.py", tofile="b/value.py", n=0)).encode()
        before = {"value.py": old, "test_value.py": b"# protected\n"}
        after = {**before, "value.py": new}
        with fixture(before=before, after=after, patch_raw=patch_raw) as (_, source, _, task_raw, archive, _, _):
            self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_PATCH_INVALID")

    def test_candidate_digest_mismatch_is_refused_without_execution(self):
        with fixture() as (_, _, _, _, _, before, after):
            malicious = review_diff("value.py", before["value.py"], b"different claimed candidate\n").encode()
        with fixture(patch_raw=malicious) as (_, source, _, task_raw, archive, _, _):
            self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_CANDIDATE_CHANGED")

    def test_configured_candidate_pin_source_drift_and_protected_drift_do_not_create(self):
        for kind in ("pin", "source", "protected", "candidate"):
            with self.subTest(kind=kind), fixture() as (_, source, task, task_raw, archive, _, after):
                if kind == "pin":
                    task["files"]["value.py"] = sha(after["value.py"])
                    task_raw = canonical(task)
                elif kind == "source":(source / "value.py").write_text("owner change\n")
                elif kind == "protected":(source / "test_value.py").write_text("changed test\n")
                else:(source / "value.py").write_bytes(after["value.py"])
                with patch("subprocess.run", side_effect=AssertionError("process")):
                    self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_BASELINE_REQUIRED")

    def test_invalid_archive_task_and_git_control_scope_refuse_before_processes(self):
        with fixture() as (_, source, _, task_raw, archive, _, _):
            self.assert_refused(prepare, archive + b"trailing", source, task_raw)
            self.assert_refused(prepare, archive, source, b"{}")
        before = {".git/config": b"old\n", "test_value.py": b"# protected\n"}
        after = {**before, ".git/config": b"new\n"}
        with fixture(before=before, after=after, editable=[".git/config"]) as (_, source, _, task_raw, archive, _, _):
            with patch("bundle_workspace.read_selected", side_effect=AssertionError("selected read")):
                self.assert_refused(prepare, archive, source, task_raw, code="GIT_CONTROL_FILE_REFUSED")

    def test_second_source_read_guard_race_is_a_fixed_refusal(self):
        with fixture() as (_, source, _, task_raw, archive, _, _):
            # check_project has its own reader; this seam is the subsequent
            # baseline-byte acquisition after that valid observation.
            for error in (ReadIssue("BINARY"), ReadIssue("LIMIT"), OSError("private changed input")):
                with self.subTest(kind=type(error).__name__), \
                        patch("bundle_workspace.read_selected", side_effect=error), \
                        patch("subprocess.run", side_effect=AssertionError("process")):
                    self.assert_refused(prepare, archive, source, task_raw, code="BUNDLE_WORKSPACE_SOURCE_CHANGED")

    def test_prepare_is_read_only_no_discovery_process_network_execution_or_extraction(self):
        with fixture() as (root, source, _, task_raw, archive, _, _):
            before = tree(root)
            real_open = os.open
            def readonly(name, flags, *args, **kwargs):
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                return real_open(name, flags, *args, **kwargs)
            with patch("os.open", side_effect=readonly), patch("os.scandir", side_effect=AssertionError("discovery")), \
                    patch("subprocess.run", side_effect=AssertionError("process")), patch("subprocess.Popen", side_effect=AssertionError("process")), \
                    patch("socket.socket", side_effect=AssertionError("network")), patch("builtins.exec", side_effect=AssertionError("exec")), \
                    patch("builtins.eval", side_effect=AssertionError("eval")), patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extract")):
                self.assertEqual(prepare(archive, source, task_raw)["candidate"]["value.py"], b"def value():\n    return 2\n")
            self.assertEqual(tree(root), before)


class WorkerTests(unittest.TestCase):
    assert_refused = PreparationTests.assert_refused

    def test_worker_python_and_java_private_git_candidate_is_uncommitted(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (root, source, task, task_raw, archive, before, after):
                job, request, initial = stage(root, source, task_raw, archive)
                source_before = tree(source)
                calls = []
                def checker(work, supplied_task, jdk):
                    calls.append((work, copy.deepcopy(supplied_task), jdk))
                    self.assertEqual({name:(work / name).read_bytes() for name in after}, after)
                    return passed(work, supplied_task, jdk)
                with patch("bundle_workspace.git", wraps=git) as commands:
                    receipt = build(job, Path("/invented/not-executed-jdk") if java else None, checker)
                self.assertEqual(receipt["status"], "VERIFIED")
                self.assertFalse(receipt["source_applied"])
                self.assertTrue(receipt["patch_applied_to_workspace"])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1]["checks"], task["checks"])
                self.assertTrue(all(source not in call.args[0].parents and source != call.args[0] for call in commands.call_args_list))
                self.assertFalse(any("apply" in call.args for call in commands.call_args_list))
                work = Path(receipt["path"])
                self.assertEqual(git(work, "rev-list", "--all", "--count"), b"1\n")
                self.assertEqual(git(work, "diff", "--cached", "--name-only"), b"")
                self.assertTrue(git(work, "diff", "--name-only"))
                self.assertEqual(source_before, tree(source))
                self.assertEqual(json.loads((job / "initial-receipt.json").read_bytes()), initial)
                self.assertEqual(json.loads((job / "receipt.json").read_bytes()), receipt)
                self.assertEqual(receipt["config_sha256"], request["config_sha256"])

    def test_existing_original_git_head_index_branch_and_dirty_state_are_untouched(self):
        with fixture() as (root, source, task, task_raw, archive, _, _):
            template = root / "template";template.mkdir()
            git(source, "init", "--initial-branch=owner", "--template=" + str(template))
            git(source, "add", "--", *sorted(task["files"]))
            git(source, "commit", "--no-verify", "-m", "Invented owner baseline")
            (source / "unselected-private.txt").write_text(PRIVATE)
            head, status, index = git(source, "rev-parse", "HEAD"), git(source, "status", "--porcelain=v1", "-z"), (source / ".git/index").read_bytes()
            job, _, _ = stage(root, source, task_raw, archive)
            build(job, checker=passed)
            # Git status itself can refresh index cache bytes. Check worker
            # immutability before issuing any observer Git command afterward.
            self.assertEqual((source / ".git/index").read_bytes(), index)
            self.assertEqual(git(source, "rev-parse", "HEAD"), head)
            self.assertEqual(git(source, "status", "--porcelain=v1", "-z"), status)

    def test_stale_config_task_source_bundle_and_request_preserve_early_failure_pins(self):
        for kind in ("config", "task", "source", "bundle", "request"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, archive, _, _):
                job, request, initial = stage(root, source, task_raw, archive)
                if kind == "config":Path(request["config_path"]).write_bytes(b"changed config\n")
                elif kind == "task":Path(request["task_path"]).write_bytes(task_raw + b" ")
                elif kind == "source":(source / "value.py").write_text("owner drift\n")
                elif kind == "bundle":(job / "bundle.zip").write_bytes(archive + b"changed")
                else:(job / "request.json").write_bytes(b"{}")
                with patch("bundle_workspace.git", side_effect=AssertionError("Git before validated bytes")), \
                        patch("bundle_workspace.fixed_checks", side_effect=AssertionError("checks")):
                    self.assert_refused(build, job, checker=passed)
                receipt = json.loads((job / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED")
                self.assertFalse(receipt["source_applied"])
                for key in ("id", "project_id", "config_sha256", "task_sha256", "bundle_sha256", "preview_sha256", "patch_sha256"):
                    self.assertEqual(receipt[key], initial[key])
                self.assertFalse((job / "workspace").exists())

    def test_failing_checks_retain_full_output_and_partial_candidate(self):
        with fixture() as (root, source, _, task_raw, archive, _, after):
            job, _, _ = stage(root, source, task_raw, archive)
            def failed(work, task, jdk):
                results = passed(work, task, jdk)
                results["unit"].update(exit_code=1, output=PRIVATE + " failed")
                return results
            self.assert_refused(build, job, checker=failed, code="BUNDLE_WORKSPACE_CHECKS_FAILED")
            receipt = json.loads((job / "receipt.json").read_bytes())
            self.assertEqual(receipt["status"], "FAILED")
            self.assertEqual(receipt["checks"]["unit"]["exit_code"], 1)
            self.assertEqual(json.loads((job / "checks.json").read_bytes())["unit"]["output"], PRIVATE + " failed")
            self.assertEqual((job / "workspace/review/value.py").read_bytes(), after["value.py"])

    def test_display_clipping_does_not_misrepresent_execution_output_limit(self):
        with fixture() as (root, source, _, task_raw, archive, _, _):
            job, _, _ = stage(root, source, task_raw, archive)
            output = "😀" * 10000
            def loud(work, task, jdk):
                results = passed(work, task, jdk);results["unit"]["output"] = output
                return results
            receipt = build(job, checker=loud)
            self.assertEqual(receipt["status"], "VERIFIED")
            self.assertTrue(receipt["checks"]["unit"]["display_truncated"])
            self.assertFalse(receipt["checks"]["unit"]["output_limited"])
            self.assertEqual(receipt["checks"]["unit"]["output"], output[:4096])
            self.assertEqual(json.loads((job / "checks.json").read_bytes())["unit"]["output"], output)
            self.assertLessEqual(len((job / "receipt.json").read_bytes()), 262144)

    def test_boolean_and_nonpassing_check_observations_cannot_verify(self):
        for update in ({"exit_code": True}, {"tests_ran": True}, {"tests_ran": 0}, {"timed_out": True}, {"output_limited": True}):
            with self.subTest(update=update), fixture() as (root, source, _, task_raw, archive, _, _):
                job, _, _ = stage(root, source, task_raw, archive)
                def invalid(work, task, jdk):
                    results = passed(work, task, jdk);results["unit"].update(update)
                    return results
                self.assert_refused(build, job, checker=invalid, code="BUNDLE_WORKSPACE_CHECKS_FAILED")
                self.assertEqual(json.loads((job / "receipt.json").read_bytes())["status"], "FAILED")

    def test_baseexception_interruptions_are_captured_without_raw_exception_text(self):
        for error in (KeyboardInterrupt(), SystemExit(7), RuntimeError(PRIVATE)):
            with self.subTest(kind=type(error).__name__), fixture() as (root, source, _, task_raw, archive, _, _):
                job, _, _ = stage(root, source, task_raw, archive)
                def interrupted(*_):raise error
                self.assert_refused(build, job, checker=interrupted)
                receipt = json.loads((job / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED" if isinstance(error, RuntimeError) else "INTERRUPTED")
                self.assertNotIn(PRIVATE, receipt["reason"])
                self.assertTrue((job / "workspace/review/value.py").is_file())

    def test_post_check_source_and_config_task_changes_are_detected_and_retained(self):
        for kind in ("source", "config", "task", "request"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, archive, _, _):
                job, request, _ = stage(root, source, task_raw, archive)
                def owner_change(work, task, jdk):
                    target = source / "value.py" if kind == "source" else Path(request[kind + "_path"]) if kind in {"config", "task"} else job / "request.json"
                    target.write_bytes(target.read_bytes() + b" \n")
                    return passed(work, task, jdk)
                self.assert_refused(build, job, checker=owner_change)
                receipt = json.loads((job / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED")
                self.assertIn("unit", receipt["checks"])

    def test_candidate_inventory_git_pointer_and_staged_candidate_changes_refuse(self):
        for kind in ("bytes", "extra", "emptydir", "git_pointer", "stage"):
            with self.subTest(kind=kind), fixture() as (root, source, _, task_raw, archive, _, _):
                job, _, _ = stage(root, source, task_raw, archive)
                def tampered(work, task, jdk):
                    if kind == "bytes":(work / "value.py").write_text("different\n")
                    elif kind == "extra":(work / "unapproved.py").write_text(PRIVATE)
                    elif kind == "emptydir":(work / "unapproved").mkdir()
                    elif kind == "git_pointer":(work / ".git").write_text("gitdir: /private/outside\n")
                    else:git(work, "add", "--", "value.py")
                    return passed(work, task, jdk)
                self.assert_refused(build, job, checker=tampered)
                self.assertEqual(json.loads((job / "receipt.json").read_bytes())["status"], "FAILED")

    def test_terminal_failed_job_is_not_retried_or_rewritten(self):
        with fixture() as (root, source, _, task_raw, archive, _, _):
            job, _, _ = stage(root, source, task_raw, archive)
            def interrupted(*_):raise KeyboardInterrupt
            self.assert_refused(build, job, checker=interrupted)
            previous = tree(job)
            with patch("bundle_workspace.git", side_effect=AssertionError("retry Git")):
                self.assert_refused(build, job, checker=passed)
            self.assertEqual(tree(job), previous)

    def test_worker_does_not_read_or_change_unrelated_hold_or_use_network(self):
        with fixture() as (root, source, _, task_raw, archive, _, _):
            state = root / "state";state.mkdir()
            hold = state / "hold.json";hold.write_bytes(canonical({"state": "REQUEST_UNSETTLED", "run": PRIVATE, "turn": 1}))
            job, _, _ = stage(root, source, task_raw, archive)
            before = hold.read_bytes()
            with patch("socket.socket", side_effect=AssertionError("network")):
                build(job, checker=passed)
            self.assertEqual(hold.read_bytes(), before)

    def test_cli_bad_input_emits_only_fixed_code(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--job-dir", "/missing/" + PRIVATE])
        self.assertNotEqual(code, 0)
        value = json.loads(output.getvalue())
        self.assertRegex(value["error"], r"^BUNDLE_WORKSPACE_[A-Z_]+$")
        self.assertNotIn(PRIVATE, output.getvalue())


if __name__ == "__main__":
    unittest.main()
