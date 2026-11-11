"""Invented file snapshots exercise read-only bundle/project comparisons."""

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import Refused, canonical
from bundle_project_check import check_project, main, read_selected
from patch_bundle import build_bundle


PRIVATE = "invented-private-source-and-goal-that-must-not-appear"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def fixture(*, java=False, modules=2, size=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "selected"
        project.mkdir()
        names = ["sample/Value%s.java" % i if java else "value%s.py" % i for i in range(modules)]
        protected = "sample/ValueTest.java" if java else "test_value.py"
        before = {name: ((b"x" * (size - 1) + b"\n") if size else
                  ("package sample; class Value%s { static int value() { return 1; } }\n" % i).encode()
                  if java else ("def value%s(): return 1\n" % i).encode()) for i, name in enumerate(names)}
        before[protected] = b"z" * size if size else (b"package sample; class ValueTest { public static void main(String[] args) {} }\n"
            if java else b"import unittest\n# invented protected check\n")
        after = {name: (b"y" + raw[1:] if size else raw.replace(b"return 1", b"return 2"))
                 if name in names else raw for name, raw in before.items()}
        task = {"format": "outlands-coding-agent-v2" if java else "outlands-coding-agent-v1",
            "goal": PRIVATE, "files": {name: sha(raw) for name, raw in before.items()}, "editable": names,
            "checks": {"unit": {"kind": "java-main", "sources": list(before), "main_class": "sample.ValueTest"}
                       if java else protected}, "max_turns": 3, "request_seconds": 17}
        diff = b"".join(("--- a/" + name + "\n+++ b/" + name + "\n@@ -1 +1 @@\n-").encode() + before[name]
                        + b"+" + after[name] for name in names)
        result = {"format": task["format"], "status": "REVIEW_READY", "source_adopted": False,
            "files": {name: {"before": sha(before[name]), "after": sha(after[name])} for name in before},
            "patch_sha256": sha(diff)}
        result_raw = canonical(result)
        review = {"id": "1" * 16, "recorded": 1, "verdict": "accepted", "source_applied": False,
                  "result_sha256": sha(result_raw), "patch_sha256": sha(diff), "note": PRIVATE}
        final = {"index": 7, "kind": "independent_final_checks", "value": {"unit": {"exit_code": 0,
            "tests_ran": 2, "timed_out": False, "output_limited": False, "infrastructure_error": False, "output": PRIVATE}}}
        archive = build_bundle(canonical(task), result_raw, canonical(review), canonical(final), diff)
        for name, raw in before.items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        yield root, project, task, archive, before, after


def observe(project, task, archive, expected=None):
    return check_project(archive, project, canonical(task), expected)


class ProjectCheckTests(unittest.TestCase):
    def assert_refused(self, operation, *args, code=None):
        with self.assertRaises(Refused) as caught:
            operation(*args)
        self.assertRegex(str(caught.exception), r"^(PROJECT_CHECK|BUNDLE)_[A-Z_]+$")
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(caught.exception.args, (code,))

    def test_python_java_baseline_and_candidate_matches_have_exact_report(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (_, project, task, archive, before, after):
                report = observe(project, task, archive, sha(archive))
                self.assertEqual(set(report), {"version", "bundle_sha256", "task_sha256", "status", "profile", "bundle_only",
                    "project_only", "permission_differences", "files", "total_bytes", "task_pins_match", "reasons", "not_checked", "limits", "notes"})
                self.assertEqual(report["status"], "BASELINE_MATCH")
                self.assertTrue(all(report["profile"].values()))
                self.assertEqual(report["bundle_sha256"], sha(archive))
                self.assertEqual(report["task_sha256"], sha(canonical(task)))
                self.assertEqual(report["total_bytes"], sum(map(len, before.values())))
                self.assertTrue(report["task_pins_match"])
                self.assertEqual(report["reasons"], [])
                self.assertEqual(report["not_checked"], ["TASK_GOAL", "CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "PATCH_APPLICABILITY", "GIT_ADOPTION"])
                for row in report["files"]:
                    self.assertEqual(set(row), {"path", "editable", "project_editable", "before_sha256", "after_sha256",
                        "project_sha256", "current_sha256", "bytes", "task_pin_match", "status"})
                    self.assertEqual(row["current_sha256"], sha(before[row["path"]]))
                    self.assertEqual(row["status"], "BASELINE" if row["editable"] else "UNCHANGED")
                for name, raw in after.items():
                    (project / name).write_bytes(raw)
                candidate = observe(project, task, archive)
                self.assertEqual(candidate["status"], "CANDIDATE_MATCH")
                self.assertFalse(candidate["task_pins_match"])
                self.assertEqual(candidate["reasons"], [])

    def test_mixed_and_arbitrary_drift_are_different_observations(self):
        with fixture() as (_, project, task, archive, _, after):
            first = task["editable"][0]
            (project / first).write_bytes(after[first])
            report = observe(project, task, archive)
            self.assertEqual(report["status"], "MIXED_MATCH")
            self.assertEqual(report["reasons"], ["MIXED_BASELINE_CANDIDATE"])
            (project / first).write_text("unrelated owner change\n")
            report = observe(project, task, archive)
            self.assertEqual(report["status"], "DIFFERENT")
            self.assertEqual(report["reasons"], ["SOURCE_CHANGED"])

    def test_protected_drift_is_changed_never_candidate(self):
        with fixture(java=True) as (_, project, task, archive, before, _):
            protected = next(name for name in before if name not in task["editable"])
            (project / protected).write_bytes(b"changed protected bytes\n")
            report = observe(project, task, archive)
            row = next(row for row in report["files"] if row["path"] == protected)
            self.assertEqual(report["status"], "DIFFERENT")
            self.assertEqual(row["status"], "CHANGED")
            self.assertFalse(row["editable"])
            self.assertFalse(row["project_editable"])
            self.assertFalse(row["task_pin_match"])

    def test_configured_pins_may_name_baseline_candidate_or_other_bytes(self):
        with fixture() as (_, project, task, archive, before, after):
            first = task["editable"][0]
            for configured in (sha(before[first]), sha(after[first]), sha(b"other configured revision")):
                task["files"][first] = configured
                report = observe(project, task, archive)
                row = next(row for row in report["files"] if row["path"] == first)
                self.assertEqual(report["status"], "BASELINE_MATCH")
                self.assertEqual(row["project_sha256"], configured)
                self.assertEqual(row["task_pin_match"], configured == sha(before[first]))
                self.assertEqual(report["reasons"], [])
            for name, raw in after.items():
                (project / name).write_bytes(raw)
                task["files"][name] = sha(raw)
            self.assertTrue(observe(project, task, archive)["task_pins_match"])
            self.assertEqual(observe(project, task, archive)["status"], "CANDIDATE_MATCH")

    def test_goal_differences_are_explicitly_not_compared(self):
        with fixture() as (_, project, task, archive, _, _):
            task["goal"] = "An unrelated but valid selected task goal."
            report = observe(project, task, archive)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertNotIn(task["goal"], canonical(report).decode())

    def test_each_profile_mismatch_skips_all_source_reads(self):
        changes = [lambda task: task.update(format="outlands-coding-agent-v2", checks={"unit": {"kind": "python-unittest", "pattern": "test_value.py"}}),
            lambda task: task["files"].update(extra_py="f" * 64),
            lambda task: task["editable"].pop(), lambda task: task.update(checks={"other": "test_value.py"}),
            lambda task: task.update(max_turns=4), lambda task: task.update(request_seconds=18)]
        for index, change in enumerate(changes):
            with self.subTest(index=index), fixture() as (_, project, task, archive, _, _):
                change(task)
                with patch("bundle_project_check.read_selected", side_effect=AssertionError("selected source read")), \
                        patch("os.open", side_effect=AssertionError("filesystem read")):
                    report = observe(project, task, archive)
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertFalse(all(report["profile"].values()))
                self.assertTrue(all(row["status"] == "NOT_CHECKED" for row in report["files"]))
                self.assertIsNone(report["total_bytes"])
                self.assertIsNone(report["task_pins_match"])

    def test_scope_difference_never_adopts_bundle_paths_into_selection(self):
        with fixture() as (_, project, task, archive, _, _):
            omitted = task["editable"].pop()
            task["files"].pop(omitted)
            task["files"]["task_only.py"] = sha(b"not read")
            with patch("bundle_project_check.read_selected", side_effect=AssertionError("source read")):
                report = observe(project, task, archive)
            self.assertEqual(report["bundle_only"], [omitted])
            self.assertEqual(report["project_only"], ["task_only.py"])
            row = next(row for row in report["files"] if row["path"] == omitted)
            self.assertEqual(row["status"], "OUT_OF_SCOPE")
            self.assertIsNone(row["project_editable"])
            self.assertIsNone(row["project_sha256"])
            self.assertIn("SCOPE_MISMATCH", report["reasons"])

    def test_permission_differences_are_exact_and_remain_unread(self):
        with fixture() as (_, project, task, archive, _, _):
            omitted = task["editable"].pop()
            report = observe(project, task, archive)
            self.assertEqual(report["permission_differences"], [{"path": omitted, "bundle_editable": True, "project_editable": False}])
            self.assertFalse(report["profile"]["permissions"])
            self.assertTrue(all(row["current_sha256"] is None for row in report["files"]))

    def test_invalid_archive_and_external_pin_refuse_before_any_source_read(self):
        with fixture() as (_, project, task, archive, _, _):
            for raw, expected in ((archive + b"trailing", None), (b"bad archive", None),
                                  (archive, "f" * 64), (archive, "invalid"), (b"x" * (2097152 + 1), None)):
                with self.subTest(expected=expected), patch("bundle_project_check.read_selected", side_effect=AssertionError("source read")), \
                        patch("os.open", side_effect=AssertionError("filesystem read")):
                    self.assert_refused(check_project, raw, project, canonical(task), expected)

    def test_invalid_or_partial_task_records_have_fixed_codes_and_no_source_reads(self):
        with fixture() as (_, project, task, archive, _, _):
            for raw in (b"{", b"[]", b"null", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", None, bytearray(b"{}")):
                with patch("bundle_project_check.read_selected", side_effect=AssertionError("source read")):
                    self.assert_refused(check_project, archive, project, raw, code="PROJECT_CHECK_TASK_INVALID")
            changes = [{"files": {3: "a" * 64}}, {"files": {"../private.py": "a" * 64}},
                       {"editable": ["test_value.py"]}, {"max_turns": True}, {"request_seconds": 0}, {"extra": PRIVATE}]
            for update in changes:
                changed = {**task, **update}
                with patch("bundle_project_check.read_selected", side_effect=AssertionError("source read")):
                    self.assert_refused(check_project, archive, project, canonical(changed), code="PROJECT_CHECK_TASK_INVALID")
            self.assert_refused(check_project, archive, project, b" " * (262144 + 1), code="PROJECT_CHECK_LIMIT")

    def test_raw_task_bytes_are_hashed_without_json_normalization(self):
        with fixture() as (_, project, task, archive, _, _):
            raw = json.dumps(task, indent=3).encode()
            report = check_project(archive, project, raw)
            self.assertEqual(report["task_sha256"], sha(raw))
            self.assertEqual(report["status"], "BASELINE_MATCH")

    def test_unicode_empty_and_line_ending_bytes_are_observed_without_normalization(self):
        with fixture() as (_, project, task, archive, before, _):
            first = task["editable"][0]
            for raw in ("# invented é😀 source\n".encode("utf-8"), b"", before[first].replace(b"\n", b"\r\n")):
                with self.subTest(length=len(raw)):
                    (project / first).write_bytes(raw)
                    report = observe(project, task, archive)
                    row = next(row for row in report["files"] if row["path"] == first)
                    self.assertEqual(report["status"], "DIFFERENT")
                    self.assertEqual(row["current_sha256"], sha(raw))
                    self.assertEqual(row["bytes"], len(raw))
                    self.assertIsNotNone(report["total_bytes"])
                    self.assertNotIn("invented é", canonical(report).decode())

    def test_maximum_selected_scope_and_raw_task_size_stay_bounded(self):
        with fixture(modules=31) as (_, project, task, archive, _, _):
            raw = canonical(task)
            raw += b" " * (262144 - len(raw))
            report = check_project(archive, project, raw)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertEqual(len(report["files"]), 32)
            self.assertEqual(report["task_sha256"], sha(raw))
            self.assertLessEqual(len(canonical(report)), 65536)

    def test_missing_and_unsafe_file_values_stay_unknown(self):
        for raw, status, reason in ((None, "MISSING", "SOURCE_MISSING"), (b"x\x00y", "BINARY", "BINARY_INPUT"),
                                   (b"\xff", "UTF8", "INVALID_UTF8"), (b"x" * 32769, "LIMIT", "FILE_LIMIT")):
            with self.subTest(status=status), fixture() as (_, project, task, archive, _, _):
                name = task["editable"][0]
                (project / name).unlink()
                if raw is not None:
                    (project / name).write_bytes(raw)
                report = observe(project, task, archive)
                row = next(row for row in report["files"] if row["path"] == name)
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertEqual(row["status"], status)
                self.assertIsNone(row["bytes"])
                self.assertIsNone(row["current_sha256"])
                self.assertIsNone(row["task_pin_match"])
                self.assertIsNone(report["total_bytes"])
                self.assertIsNone(report["task_pins_match"])
                self.assertIn(reason, report["reasons"])

    def test_source_links_fifo_directory_and_ancestor_links_are_not_followed(self):
        for kind in ("symlink", "hardlink", "fifo", "directory", "parent", "root"):
            with self.subTest(kind=kind), fixture(java=True) as (root, project, task, archive, _, _):
                path = project / task["editable"][0]
                if kind == "symlink":
                    outside = root / "private-outside"
                    outside.write_text(PRIVATE)
                    path.unlink();path.symlink_to(outside)
                elif kind == "hardlink":
                    (root / "hard").hardlink_to(path)
                elif kind == "fifo":
                    path.unlink();os.mkfifo(path)
                elif kind == "directory":
                    path.unlink();path.mkdir()
                elif kind == "parent":
                    original = project / "real"
                    (project / "sample").rename(original)
                    (project / "sample").symlink_to(original, target_is_directory=True)
                else:
                    alias = root / "alias"
                    alias.symlink_to(project, target_is_directory=True)
                    project = alias
                report = observe(project, task, archive)
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertIn("SOURCE_UNREADABLE", report["reasons"])
                self.assertNotIn(PRIVATE, canonical(report).decode())

    def test_size_mtime_instability_is_not_reported_as_a_match(self):
        with fixture() as (_, project, task, archive, _, _):
            real_fstat, calls = os.fstat, 0
            def unstable(fd):
                nonlocal calls
                value = real_fstat(fd);calls += 1
                if calls == 2:
                    return SimpleNamespace(st_mode=value.st_mode, st_nlink=value.st_nlink, st_size=value.st_size,
                                           st_mtime_ns=value.st_mtime_ns + 1)
                return value
            with patch("bundle_project_check.os.fstat", side_effect=unstable):
                report = observe(project, task, archive)
            self.assertEqual(report["status"], "NEEDS_INSPECTION")
            self.assertIn("SOURCE_UNREADABLE", report["reasons"])

    def test_exact_and_excess_aggregate_source_sizes_are_visible(self):
        for modules, status in ((3, "BASELINE_MATCH"), (4, "NEEDS_INSPECTION")):
            with fixture(modules=modules, size=32768) as (_, project, task, archive, _, _):
                report = observe(project, task, archive)
                self.assertEqual(report["total_bytes"], (modules + 1) * 32768)
                self.assertEqual(report["status"], status)
                if modules == 4:
                    self.assertIn("TOTAL_INPUT_LIMIT", report["reasons"])
                    self.assertTrue(report["task_pins_match"])

    def test_no_discovery_extraction_execution_process_network_or_writes(self):
        with fixture() as (root, project, task, archive, _, _):
            (project / "unselected-private.py").write_text(PRIVATE)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch("os.scandir", side_effect=AssertionError("discovery")), \
                    patch("os.listdir", side_effect=AssertionError("discovery")), \
                    patch("pathlib.Path.glob", side_effect=AssertionError("discovery")), \
                    patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extraction")), \
                    patch("zipfile.ZipFile.extract", side_effect=AssertionError("extraction")), \
                    patch("subprocess.Popen", side_effect=AssertionError("process")), \
                    patch("socket.socket", side_effect=AssertionError("network")), \
                    patch("builtins.exec", side_effect=AssertionError("execution")), \
                    patch("builtins.eval", side_effect=AssertionError("evaluation")):
                report = observe(project, task, archive)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertEqual(before, {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_report_strips_private_fields_and_does_not_mutate_inputs(self):
        with fixture(java=True) as (root, project, task, archive, _, _):
            original = copy.deepcopy(task)
            archive_before = bytes(archive)
            report = observe(project, task, archive)
            self.assertNotIn(PRIVATE, canonical(report).decode())
            self.assertNotIn(str(root), canonical(report).decode())
            self.assertLessEqual(len(canonical(report)), 65536)
            report["files"][0]["path"] = "modified result"
            report["not_checked"].clear()
            self.assertEqual(task, original)
            self.assertEqual(archive, archive_before)
            self.assertEqual(len(observe(project, task, archive)["not_checked"]), 6)

    def test_invalid_project_roots_and_reader_requests_are_fixed(self):
        with fixture() as (_, project, task, archive, _, _):
            for root in ("/absolute-as-string", Path("relative"), project / "..", None):
                self.assert_refused(check_project, archive, root, canonical(task), code="PROJECT_CHECK_INPUT")
            for path in ("../outside", "/outside", "a//b"):
                self.assert_refused(read_selected, project, path)


class CliTests(unittest.TestCase):
    def call(self, args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def named_inputs(self, root, task, archive):
        bundle_path, task_path = root / "private-input.zip", root / "selected-task.json"
        bundle_path.write_bytes(archive);task_path.write_bytes(canonical(task))
        return bundle_path, task_path

    def test_cli_match_candidate_mixed_drift_and_profile_exit_codes(self):
        with fixture() as (root, project, task, archive, _, after):
            bundle_path, task_path = self.named_inputs(root, task, archive)
            args = [str(bundle_path), "--project", str(project), "--task", str(task_path), "--expect-sha256", sha(archive)]
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            code, report = self.call(args)
            self.assertEqual((code, report["status"]), (0, "BASELINE_MATCH"))
            self.assertEqual(before, {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
            (project / task["editable"][0]).write_bytes(after[task["editable"][0]])
            code, report = self.call(args)
            self.assertEqual((code, report["status"]), (1, "MIXED_MATCH"))
            for name, raw in after.items():
                (project / name).write_bytes(raw)
            self.assertEqual(self.call(args)[0], 0)
            (project / task["editable"][0]).write_text("unrelated drift")
            self.assertEqual(self.call(args)[0], 1)
            task["request_seconds"] += 1;task_path.write_bytes(canonical(task))
            code, report = self.call(args)
            self.assertEqual((code, report["status"]), (1, "NEEDS_INSPECTION"))

    def test_cli_symlink_hardlink_nonregular_and_oversized_named_inputs_refuse(self):
        for kind in ("bundle_link", "task_link", "task_hard", "parent_link", "fifo", "large_bundle", "large_task"):
            with self.subTest(kind=kind), fixture() as (root, project, task, archive, _, _):
                bundle_path, task_path = self.named_inputs(root, task, archive)
                if kind in {"bundle_link", "task_link"}:
                    link = root / "alias"
                    link.symlink_to(bundle_path if kind == "bundle_link" else task_path)
                    if kind == "bundle_link":bundle_path = link
                    else:task_path = link
                elif kind == "task_hard":
                    (root / "hard").hardlink_to(task_path)
                elif kind == "parent_link":
                    alias = root / "alias"
                    alias.symlink_to(root, target_is_directory=True)
                    task_path = alias / task_path.name
                elif kind == "fifo":
                    task_path.unlink();os.mkfifo(task_path)
                else:
                    target, size = (bundle_path, 2097153) if kind == "large_bundle" else (task_path, 262145)
                    with target.open("wb") as stream:stream.truncate(size)
                code, value = self.call([str(bundle_path), "--project", str(project), "--task", str(task_path)])
                self.assertEqual(code, 2)
                self.assertEqual(set(value), {"error"})
                self.assertNotIn(str(root), json.dumps(value))

    def test_cli_invalid_archive_is_refused_before_named_task_is_opened(self):
        with fixture() as (root, project, task, _, _, _):
            bundle_path = root / "bad.zip"
            bundle_path.write_bytes(b"malformed archive")
            task_path = root / PRIVATE
            code, value = self.call([str(bundle_path), "--project", str(project), "--task", str(task_path)])
            self.assertEqual(code, 2)
            self.assertTrue(value["error"].startswith("BUNDLE_"))
            self.assertNotIn(PRIVATE, json.dumps(value))

    def test_cli_bad_arguments_pins_and_private_errors_are_bounded(self):
        for args in ([], ["relative.zip"], ["/missing", "--project", "/private", "--task", "/" + PRIVATE],
            ["/missing", "--project", "/private", "--project", "/duplicate"],
            ["/missing", "--project", "/private", "--task", "/task", "--expect-sha256", PRIVATE]):
            code, value = self.call(args)
            self.assertEqual(code, 2)
            self.assertRegex(value["error"], r"^(PROJECT_CHECK|BUNDLE)_[A-Z_]+$")
            self.assertNotIn(PRIVATE, json.dumps(value))


if __name__ == "__main__":
    unittest.main()
