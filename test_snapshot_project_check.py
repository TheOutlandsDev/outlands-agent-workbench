"""Invented snapshot packets and selected projects; no runtime or agent execution."""

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
from snapshot_export import CODES as EXPORT_CODES, FORMAT, HASH_FIELDS, NOTES, NOT_CHECKED, README, _archive, _checksums, verify_export
from test_bundle_workspace import bundle_for
import snapshot_project_check as check


PRIVATE = "invented-private-project-goal-and-output-48b1"


def packet(before, after, editable, *, java=False, patch_raw=None, modify=None):
    specs = ({"unit": {"kind": "java-main", "sources": sorted(before), "main_class": "sample.MainTest"}}
             if java else {"unit": "test_main.py"})
    task = {"format": "outlands-coding-agent-v2" if java else "outlands-coding-agent-v1", "goal": PRIVATE,
            "files": {name: sha(raw) for name, raw in before.items()}, "editable": list(editable),
            "checks": specs, "max_turns": 4, "request_seconds": 19}
    raw = ("".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode()
           if patch_raw is None else patch_raw)
    hashes = {name: sha(("invented-record-" + name).encode()) for name in HASH_FIELDS}
    hashes["patch_sha256"] = sha(raw)
    value = {"version": 1, "format": FORMAT, "evidence": "RECORDED_PASSING_WORKSPACE_RECHECK", "hashes": hashes,
             "profile": {key: task[key] for key in ("format", "max_turns", "request_seconds")},
             "files": [{"path": name, "editable": name in editable, "baseline_sha256": sha(before[name]),
                        "snapshot_sha256": sha(after[name]), "changed": before[name] != after[name]} for name in sorted(before)],
             "checks": [{"name": name, "spec": spec, "observation": {"exit_code": 0, "tests_ran": 3,
                         "timed_out": False, "output_limited": False, "infrastructure_error": False}} for name, spec in sorted(specs.items())],
             "source_applied": False, "workspace_modified": False, "not_checked": list(NOT_CHECKED), "notes": list(NOTES)}
    if modify:
        modify(value)
    payloads = {"changes.diff": raw, "verification.json": canonical(value), "README.txt": README}
    payloads["SHA256SUMS"] = _checksums(payloads)
    return _archive(payloads), task


@contextmanager
def fixture(*, java=False, before=None, after=None, editable=None, patch_raw=None, modify=None):
    if before is None:
        before = ({"sample/Main.java": b"package sample; class Main { static int value() { return 1; } }\n",
                   "sample/MainTest.java": b"package sample; class MainTest { public static void main(String[] args) {} }\n"}
                  if java else {"main.py": b"def value():\n    return 1\n", "other.py": b"OTHER = 1\n",
                                "test_main.py": b"# invented protected tests\n"})
    editable = (["sample/Main.java"] if java else [name for name in ("main.py", "other.py") if name in before]) if editable is None else editable
    after = {name: raw.replace(b"return 1", b"return 2").replace(b"OTHER = 1", b"OTHER = 2") if name in editable else raw for name, raw in before.items()} if after is None else after
    archive, task = packet(before, after, editable, java=java, patch_raw=patch_raw, modify=modify)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "project";project.mkdir(mode=0o700)
        for name, raw in before.items():
            target = project / name;target.parent.mkdir(mode=0o700, parents=True, exist_ok=True);target.write_bytes(raw)
        task_path, archive_path = root / "task.json", root / "private.zip"
        task_path.write_bytes(canonical(task));archive_path.write_bytes(archive)
        yield root, project, task, archive, before, after, task_path, archive_path


def hashes(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}


def install(root, values):
    for name, raw in values.items():
        (root / name).write_bytes(raw)


class SnapshotProjectTests(unittest.TestCase):
    def refused(self, function, *args, code=None):
        with self.assertRaises(Refused) as caught:
            function(*args)
        self.assertIn(str(caught.exception), check.CODES | EXPORT_CODES)
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(str(caught.exception), code)

    def report(self, project, task, archive):
        return check.check_project(archive, project, canonical(task))

    def test_python_baseline_reconstruction_is_exact_bounded_and_preserves_files(self):
        with fixture() as (root, project, task, archive, before, _, _, _):
            original = hashes(root)
            report = self.report(project, task, archive)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertTrue(all(report["profile"].values()))
            self.assertTrue(report["task_pins_match"])
            self.assertEqual(report["reconstruction"], {"status": "VERIFIED", "reason": None, "files_checked": len(before),
                "patch_sha256": verify_export(archive)["patch_sha256"], "patch_bytes": verify_export(archive)["patch_bytes"]})
            self.assertEqual(report["not_checked"], check.NOT_CHECKED)
            self.assertEqual(report["total_bytes"], sum(map(len, before.values())))
            self.assertEqual(report["task_sha256"], sha(canonical(task)))
            self.assertEqual(report["archive_sha256"], sha(archive))
            self.assertEqual(report["reasons"], [])
            self.assertEqual(hashes(root), original)
            self.assertLessEqual(len(canonical(report)), 65536)

    def test_java_baseline_uses_only_selected_fixed_profile_and_protected_harness(self):
        with fixture(java=True) as (_, project, task, archive, _, _, _, _):
            report = self.report(project, task, archive)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertEqual(report["reconstruction"]["status"], "VERIFIED")
            protected = next(row for row in report["files"] if not row["editable"])
            self.assertEqual(protected["status"], "UNCHANGED")
            self.assertEqual(protected["baseline_sha256"], protected["snapshot_sha256"])

    def test_tested_match_does_not_reverse_reconstruct_or_apply(self):
        with fixture() as (_, project, task, archive, _, after, _, _):
            install(project, after)
            with patch.object(check, "_apply", side_effect=AssertionError("reverse reconstruction")):
                report = self.report(project, task, archive)
            self.assertEqual(report["status"], "TESTED_MATCH")
            self.assertFalse(report["task_pins_match"])
            self.assertEqual({r["status"] for r in report["files"]}, {"TESTED", "UNCHANGED"})
            self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")
            self.assertEqual(report["reconstruction"]["reason"], "BASELINE_MATCH_REQUIRED")
            self.assertIn("PATCH_RECONSTRUCTION", report["not_checked"])

    def test_mixed_match_is_transparent_and_does_not_reconstruct(self):
        with fixture() as (_, project, task, archive, _, after, _, _):
            (project / "other.py").write_bytes(after["other.py"])
            with patch.object(check, "_apply", side_effect=AssertionError("mixed reconstruction")):
                report = self.report(project, task, archive)
            self.assertEqual(report["status"], "MIXED_MATCH")
            self.assertIn("MIXED_BASELINE_TESTED", report["reasons"])
            self.assertEqual(report["reconstruction"]["reason"], "BASELINE_MATCH_REQUIRED")
            self.assertEqual({r["path"]: r["status"] for r in report["files"]},
                             {"main.py": "BASELINE", "other.py": "TESTED", "test_main.py": "UNCHANGED"})

    def test_different_editable_and_protected_files_never_claim_reconstruction(self):
        for name in ("main.py", "test_main.py"):
            with self.subTest(name=name), fixture() as (_, project, task, archive, _, _, _, _):
                (project / name).write_bytes(b"different selected content\n")
                report = self.report(project, task, archive)
                self.assertEqual(report["status"], "DIFFERENT")
                self.assertIn("SOURCE_CHANGED", report["reasons"])
                self.assertEqual(next(r for r in report["files"] if r["path"] == name)["status"], "CHANGED")
                self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")

    def test_missing_selected_file_requires_inspection_without_fabricated_hashes(self):
        with fixture() as (_, project, task, archive, _, _, _, _):
            (project / "other.py").unlink()
            report = self.report(project, task, archive)
            self.assertEqual(report["status"], "NEEDS_INSPECTION")
            self.assertIn("SOURCE_MISSING", report["reasons"])
            self.assertIsNone(report["total_bytes"])
            self.assertIsNone(report["task_pins_match"])
            row = next(r for r in report["files"] if r["path"] == "other.py")
            self.assertEqual(row["status"], "MISSING")
            self.assertIsNone(row["current_sha256"])

    def test_each_profile_mismatch_skips_all_selected_reads_and_reconstruction(self):
        for kind in ("format", "scope", "permissions", "checks", "budgets"):
            with self.subTest(kind=kind), fixture() as (_, project, task, archive, _, _, _, _):
                if kind == "format":task.update(format="outlands-coding-agent-v2", checks={"unit": {"kind": "python-unittest", "pattern": "test_main.py"}})
                elif kind == "scope":task["files"]["extra.py"] = sha(b"unread")
                elif kind == "permissions":task["editable"].remove("other.py")
                elif kind == "checks":task["checks"]["second"] = "test_main.py"
                else:task["request_seconds"] += 1
                with patch.object(check, "read_selected", side_effect=AssertionError("mismatched source read")), \
                     patch.object(check, "_apply", side_effect=AssertionError("mismatched reconstruction")):
                    report = self.report(project, task, archive)
                self.assertFalse(report["profile"][kind])
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertEqual(report["reconstruction"]["reason"], "PROFILE_MISMATCH")
                self.assertTrue(all(row["current_sha256"] is None for row in report["files"]))

    def test_scope_and_permission_difference_rows_expose_only_explicit_relative_paths(self):
        with fixture() as (_, project, task, archive, _, _, _, _):
            del task["files"]["other.py"];task["editable"].remove("other.py")
            task["files"]["added.py"] = sha(b"selected-only")
            task["editable"].append("test_main.py")
            # Keep the configured harness protected; change permission on a separate selected file instead.
            task["editable"].remove("test_main.py");task["editable"].append("added.py")
            report = self.report(project, task, archive)
            self.assertEqual(report["bundle_only"], ["other.py"])
            self.assertEqual(report["project_only"], ["added.py"])
            self.assertEqual(next(row for row in report["files"] if row["path"] == "other.py")["status"], "OUT_OF_SCOPE")
            self.assertTrue(all(row["status"] in {"NOT_CHECKED", "OUT_OF_SCOPE"} for row in report["files"]))
        with fixture() as (_, project, task, archive, _, _, _, _):
            task["editable"].remove("other.py")
            report = self.report(project, task, archive)
            self.assertEqual(report["permission_differences"], [{"path": "other.py", "archive_editable": True, "project_editable": False}])

    def test_invalid_archive_is_checked_before_task_and_source(self):
        for raw in (b"invalid", b"", True, b"x" * 2097153):
            with self.subTest(kind=type(raw)), patch.object(check, "_selected_task", side_effect=AssertionError("task touched")), \
                 patch.object(check, "read_selected", side_effect=AssertionError("source touched")):
                self.refused(check.check_project, raw, Path("/missing"), b"invalid task")

    def test_old_six_member_bundle_is_rejected_without_task_or_source_reads(self):
        before = {"value.py": b"value = 1\n", "test_value.py": b"# protected\n"}
        after = {**before, "value.py": b"value = 2\n"}
        _, _, archive = bundle_for(before, after, ["value.py"])
        with patch.object(check, "_selected_task", side_effect=AssertionError("old format task")), \
             patch.object(check, "read_selected", side_effect=AssertionError("old format source")):
            self.refused(check.check_project, archive, Path("/missing"), b"not read")

    def test_external_digest_is_enforced_before_all_task_and_source_reads(self):
        with fixture() as (_, project, task, archive, _, _, _, _):
            self.assertEqual(check.check_project(archive, project, canonical(task), sha(archive))["status"], "BASELINE_MATCH")
            with patch.object(check, "_selected_task", side_effect=AssertionError("pin mismatch task")):
                self.refused(check.check_project, archive, project, canonical(task), "0" * 64, code="SNAPSHOT_EXPORT_ARCHIVE_CHANGED")
                for bad in (True, "bad", b"0" * 64):
                    self.refused(check.check_project, archive, project, canonical(task), bad, code="SNAPSHOT_EXPORT_INPUT")

    def test_malformed_task_shapes_types_paths_and_limits_are_fixed_refusals(self):
        with fixture() as (_, project, task, archive, _, _, _, _):
            raws = [True, b"[]", b'{"files":{},"files":{}}', b'{"x":NaN}', b"x" * 262145]
            for change in (lambda t: t.update(max_turns=True), lambda t: t.update(request_seconds=False),
                           lambda t: t.update(files=[]), lambda t: t.update(editable=True), lambda t: t.update(checks=[]),
                           lambda t: t["files"].update({"../escape.py": "0" * 64}), lambda t: t.update(private=PRIVATE)):
                value = copy.deepcopy(task);change(value);raws.append(canonical(value))
            for raw in raws:
                with self.subTest(size=len(raw) if type(raw) is bytes else None), patch.object(check, "read_selected", side_effect=AssertionError("bad task read")):
                    self.refused(check.check_project, archive, project, raw)

    def test_task_pin_mismatch_is_reported_without_adopting_or_blocking_actual_baseline(self):
        with fixture() as (_, project, task, archive, _, after, _, _):
            task["files"]["main.py"] = sha(after["main.py"])
            report = self.report(project, task, archive)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertFalse(report["task_pins_match"])
            self.assertEqual(report["reconstruction"]["status"], "VERIFIED")
            self.assertEqual(next(row for row in report["files"] if row["path"] == "main.py")["project_sha256"], sha(after["main.py"]))

    def test_report_strips_goal_source_patch_host_paths_ids_and_private_records(self):
        with fixture() as (root, project, task, archive, before, _, _, _):
            report = self.report(project, task, archive)
            raw = canonical(report)
            for value in (str(root), PRIVATE, "def value():", "return 1", "RECORDED_PASSING_WORKSPACE_RECHECK", "invented-record-"):
                self.assertNotIn(value.encode(), raw)
            self.assertEqual(set(report), {"version", "archive_sha256", "patch_sha256", "task_sha256", "status", "profile", "bundle_only",
                "project_only", "permission_differences", "files", "total_bytes", "task_pins_match", "reasons", "not_checked", "limits", "notes", "reconstruction"})
            self.assertEqual(report["notes"], check.NOTES)
            self.assertEqual([r["path"] for r in report["files"]], sorted(before))

    def test_repeatability_and_caller_inputs_are_unchanged(self):
        with fixture() as (_, project, task, archive, _, _, _, _):
            before_task, raw = copy.deepcopy(task), canonical(task)
            first = check.check_project(archive, project, raw)
            self.assertEqual(first, check.check_project(archive, project, raw))
            first["notes"].append("caller modification")
            self.assertEqual(check.check_project(archive, project, raw)["notes"], check.NOTES)
            self.assertEqual(task, before_task)
            self.assertEqual(raw, canonical(task))

    def test_unicode_crlf_missing_final_lf_empty_and_multiple_hunks_reconstruct(self):
        old_long = b"".join(("# line %02d\n" % n).encode() for n in range(40))
        cases = [(b"VALUE = 1\r\n", "VALUE = 2 # é😀\r\n".encode()),
                 (b"VALUE = 1", "VALUE = 2 # é😀".encode()), (b"", "# é😀\n".encode()),
                 (old_long, old_long.replace(b"line 02", b"changed02").replace(b"line 35", b"changed35"))]
        for before_raw, after_raw in cases:
            before = {"main.py": before_raw, "test_main.py": b"# protected\n"};after = {**before, "main.py": after_raw}
            with self.subTest(before=before_raw[:20]), fixture(before=before, after=after) as (_, project, task, archive, _, _, _, _):
                report = self.report(project, task, archive)
                self.assertEqual(report["status"], "BASELINE_MATCH")
                self.assertEqual(report["reconstruction"]["status"], "VERIFIED")

    def test_binary_invalid_utf8_and_per_file_limit_are_disclosed(self):
        for raw, status, reason in ((b"a\x00b", "BINARY", "BINARY_INPUT"), (b"\xff", "UTF8", "INVALID_UTF8"),
                                    (b"x" * 32769, "LIMIT", "FILE_LIMIT")):
            with self.subTest(status=status), fixture() as (_, project, task, archive, _, _, _, _):
                (project / "main.py").write_bytes(raw)
                report = self.report(project, task, archive)
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertIn(reason, report["reasons"])
                row = next(row for row in report["files"] if row["path"] == "main.py")
                self.assertEqual(row["status"], status)
                self.assertIsNone(row["current_sha256"])

    def test_total_policy_limit_observes_bounded_all_files_without_reconstruction(self):
        before = {"main.py": b"1" * 5000, "test_main.py": b"#" * 5000,
                  **{"file%02d.py" % n: b"x" * 5000 for n in range(30)}}
        after = {**before, "main.py": b"2" * 5000}
        with fixture(before=before, after=after) as (_, project, task, archive, _, _, _, _):
            with patch.object(check, "_apply", side_effect=AssertionError("over-total reconstruction")):
                report = self.report(project, task, archive)
            self.assertEqual(report["total_bytes"], 160000)
            self.assertEqual(len(report["files"]), 32)
            self.assertEqual(report["status"], "NEEDS_INSPECTION")
            self.assertEqual(report["reconstruction"]["reason"], "TOTAL_INPUT_LIMIT")
            self.assertIn("TOTAL_INPUT_LIMIT", report["reasons"])

    def test_maximum_file_count_and_exact_total_bound_can_reconstruct(self):
        before = {"main.py": b"1" * 4096, "test_main.py": b"#" * 4096,
                  **{"file%02d.py" % n: b"x" * 4096 for n in range(30)}}
        after = {**before, "main.py": b"2" * 4096}
        with fixture(before=before, after=after) as (_, project, task, archive, _, _, _, _):
            report = self.report(project, task, archive)
            self.assertEqual(report["total_bytes"], 131072)
            self.assertEqual(report["reconstruction"]["files_checked"], 32)
            self.assertEqual(report["reconstruction"]["status"], "VERIFIED")
            self.assertLessEqual(len(canonical(report)), 65536)

    def test_source_symlinks_hardlinks_directories_and_ancestor_links_are_unreadable(self):
        for kind in ("symlink", "hardlink", "directory", "ancestor"):
            with self.subTest(kind=kind), fixture(java=True) as (root, project, task, archive, _, _, _, _):
                target = project / "sample/Main.java"
                if kind == "directory":target.unlink();target.mkdir()
                elif kind == "ancestor":
                    moved = root / "moved-sample";(project / "sample").rename(moved);(project / "sample").symlink_to(moved, target_is_directory=True)
                else:
                    outside = root / "outside.java";target.rename(outside)
                    if kind == "symlink":target.symlink_to(outside)
                    else:os.link(outside, target)
                report = self.report(project, task, archive)
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertEqual(next(r for r in report["files"] if r["path"] == "sample/Main.java")["status"], "UNREADABLE")

    def test_unselected_private_files_are_never_scanned_or_read(self):
        with fixture() as (_, project, task, archive, _, _, _, _):
            (project / "unselected-private.bin").write_bytes(b"\x00" * 100000)
            with patch("os.scandir", side_effect=AssertionError("scan")):
                report = self.report(project, task, archive)
            self.assertEqual(report["status"], "BASELINE_MATCH")
            self.assertNotIn("unselected-private.bin", canonical(report).decode())

    def test_validly_rehashed_wrong_patch_context_is_not_a_baseline_match(self):
        before = {"main.py": b"VALUE = 1\n", "test_main.py": b"# protected\n"};after = {**before, "main.py": b"VALUE = 2\n"}
        wrong = review_diff("main.py", before["main.py"], after["main.py"]).encode().replace(b"-VALUE = 1", b"-VALUE = 9")
        with fixture(before=before, after=after, patch_raw=wrong) as (_, project, task, archive, _, _, _, _):
            verify_export(archive)
            report = self.report(project, task, archive)
            self.assertEqual(report["status"], "NEEDS_INSPECTION")
            self.assertEqual(report["reconstruction"]["status"], "REFUSED")
            self.assertEqual(report["reconstruction"]["reason"], "PATCH_INVALID")

    def test_validly_rehashed_wrong_snapshot_hash_refuses_reconstruction(self):
        def change(value):
            row = next(r for r in value["files"] if r["path"] == "main.py")
            row["snapshot_sha256"] = sha(b"not the patch output")
        with fixture(modify=change) as (_, project, task, archive, _, _, _, _):
            verify_export(archive)
            report = self.report(project, task, archive)
            self.assertEqual(report["status"], "NEEDS_INSPECTION")
            self.assertEqual(report["reconstruction"]["reason"], "SNAPSHOT_HASH_MISMATCH")
            self.assertIn("PATCH_RECONSTRUCTION", report["not_checked"])

    def test_noncanonical_but_applicable_context_diff_is_refused(self):
        old = b"".join(("# line %02d\n" % n).encode() for n in range(20));new = old.replace(b"line 10", b"changed 10")
        before = {"main.py": old, "test_main.py": b"# protected\n"};after = {**before, "main.py": new}
        raw = "".join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile="a/main.py", tofile="b/main.py", n=0)).encode()
        with fixture(before=before, after=after, patch_raw=raw) as (_, project, task, archive, _, _, _, _):
            verify_export(archive)
            report = self.report(project, task, archive)
            self.assertEqual(report["reconstruction"]["reason"], "PATCH_INVALID")
            self.assertEqual(report["status"], "NEEDS_INSPECTION")

    def test_oversized_reconstructed_file_and_aggregate_never_verify(self):
        before = {"main.py": b"one\n", "test_main.py": b"# protected\n"};after = {**before, "main.py": b"x" * 32769}
        with fixture(before=before, after=after) as (_, project, task, archive, _, _, _, _):
            report = self.report(project, task, archive)
            self.assertEqual(report["reconstruction"]["reason"], "SNAPSHOT_LIMIT")
            self.assertEqual(report["status"], "NEEDS_INSPECTION")
        before = {"main.py": b"1" * 4096, "test_main.py": b"#" * 4096,
                  **{"file%02d.py" % n: b"x" * 4096 for n in range(30)}}
        after = {**before, "main.py": b"2" * 4097}
        with fixture(before=before, after=after) as (_, project, task, archive, _, _, _, _):
            report = self.report(project, task, archive)
            self.assertEqual(report["reconstruction"]["reason"], "SNAPSHOT_LIMIT")

    def test_coherently_changed_protected_archive_and_extra_metadata_fail_before_source(self):
        def changed(value):
            row = next(r for r in value["files"] if r["path"] == "test_main.py")
            row.update(snapshot_sha256=sha(b"changed"), changed=True)
        for modify in (changed, lambda v: v.update(private_field=PRIVATE)):
            with fixture(modify=modify) as (_, project, task, archive, _, _, _, _), \
                 patch.object(check, "read_selected", side_effect=AssertionError("invalid archive source")):
                self.refused(check.check_project, archive, project, canonical(task))

    def test_observed_drift_after_reconstruction_removes_verified_claim(self):
        for kind in ("editable", "protected", "missing"):
            with self.subTest(kind=kind), fixture() as (_, project, task, archive, _, _, _, _):
                original = check._reconstruct
                def changed(*args):
                    result = original(*args)
                    target = project / ("test_main.py" if kind == "protected" else "main.py")
                    if kind == "missing":target.unlink()
                    else:target.write_bytes(b"changed during observation\n")
                    return result
                with patch.object(check, "_reconstruct", changed):report = self.report(project, task, archive)
                self.assertEqual(report["status"], "NEEDS_INSPECTION")
                self.assertEqual(report["reconstruction"]["status"], "REFUSED")
                self.assertEqual(report["reconstruction"]["reason"], "OBSERVATION_CHANGED")
                self.assertEqual(report["reconstruction"]["files_checked"], 0)
                self.assertIsNone(report["task_pins_match"])
                self.assertIn("OBSERVATION_CHANGED", report["reasons"])

    def test_source_read_order_and_second_observation_are_sorted_and_bounded(self):
        with fixture() as (_, project, task, archive, before, _, _, _):
            real_read = check.read_selected;calls = []
            def read(root, name, limit=32768):
                calls.append((name, limit));return real_read(root, name, limit)
            with patch.object(check, "read_selected", read):self.report(project, task, archive)
            self.assertEqual(calls, [(name, 32768) for name in sorted(before)] * 2)

    def test_nonbaseline_states_never_repeat_selected_reads(self):
        with fixture() as (_, project, task, archive, before, after, _, _):
            install(project, after)
            real_read = check.read_selected;names = []
            def read(root, name, limit=32768):names.append(name);return real_read(root, name, limit)
            with patch.object(check, "read_selected", read):self.report(project, task, archive)
            self.assertEqual(names, sorted(before))

    def test_no_writes_extract_git_checks_providers_processes_or_input_mutation(self):
        with fixture() as (root, project, task, archive, _, _, _, _):
            original, real_open = hashes(root), os.open
            def readonly(path, flags, *args, **kwargs):
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC));return real_open(path, flags, *args, **kwargs)
            with patch("os.open", readonly), patch("os.scandir", side_effect=AssertionError("scan")), \
                 patch("subprocess.run", side_effect=AssertionError("process")), patch("subprocess.Popen", side_effect=AssertionError("process")), \
                 patch("socket.socket", side_effect=AssertionError("network")), patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extract")), \
                 patch("git_workspace.fixed_checks", side_effect=AssertionError("checks")):
                self.assertEqual(self.report(project, task, archive)["status"], "BASELINE_MATCH")
            self.assertEqual(hashes(root), original)

    def test_cli_baseline_tested_different_exit_codes_and_no_writes(self):
        with fixture() as (root, project, task, archive, _, after, task_path, archive_path):
            args = [str(archive_path), "--project", str(project), "--task", str(task_path), "--expect-sha256", sha(archive)]
            for status, expected in (("BASELINE_MATCH", 0), ("TESTED_MATCH", 0), ("DIFFERENT", 1)):
                if status == "TESTED_MATCH":install(project, after)
                elif status == "DIFFERENT":(project / "main.py").write_bytes(b"different\n")
                before, output = hashes(root), io.StringIO()
                with redirect_stdout(output):code = check.main(args)
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output.getvalue())["status"], status)
                self.assertEqual(hashes(root), before)

    def test_cli_verifies_archive_before_task_file_read(self):
        with fixture() as (_, project, _, _, _, _, task_path, archive_path):
            archive_path.write_bytes(b"bad")
            real_read = check._read_named
            def read(path, limit, **kwargs):
                if path == task_path:raise AssertionError("invalid archive touched task")
                return real_read(path, limit, **kwargs)
            output = io.StringIO()
            with patch.object(check, "_read_named", read), redirect_stdout(output):
                code = check.main([str(archive_path), "--project", str(project), "--task", str(task_path)])
            self.assertEqual(code, 2)
            self.assertIn(json.loads(output.getvalue())["error"], EXPORT_CODES)

    def test_cli_task_drift_after_comparison_is_refused_before_reporting(self):
        with fixture() as (_, project, task, _, _, _, task_path, archive_path):
            original = check.check_project
            def changed(*args):
                result = original(*args)
                task["goal"] = "Changed valid task after observation";task_path.write_bytes(canonical(task))
                return result
            output = io.StringIO()
            with patch.object(check, "check_project", changed), redirect_stdout(output):
                code = check.main([str(archive_path), "--project", str(project), "--task", str(task_path)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue()), {"error": "SNAPSHOT_PROJECT_PROJECT_CHANGED"})

    def test_cli_unsafe_archive_and_task_links_or_ancestors_refuse_privately(self):
        for kind in ("archive-link", "archive-hard", "task-link", "ancestor-link"):
            with self.subTest(kind=kind), fixture() as (root, project, _, _, _, _, task_path, archive_path):
                if kind.startswith("archive"):
                    saved = root / "saved.zip";archive_path.rename(saved)
                    if kind == "archive-link":archive_path.symlink_to(saved)
                    else:os.link(saved, archive_path)
                elif kind == "task-link":
                    saved = root / "saved.json";task_path.rename(saved);task_path.symlink_to(saved)
                else:
                    alias = root / "alias";alias.symlink_to(root, target_is_directory=True);archive_path = alias / archive_path.name
                output = io.StringIO()
                with redirect_stdout(output):code = check.main([str(archive_path), "--project", str(project), "--task", str(task_path)])
                self.assertEqual(code, 2)
                self.assertNotIn(str(root), output.getvalue())
                self.assertIn(json.loads(output.getvalue())["error"], check.CODES | EXPORT_CODES)

    def test_cli_bad_arguments_paths_and_errors_remain_finite(self):
        for args in ([], [True], ["relative.zip", "--project", "/tmp/project", "--task", "/tmp/task.json"],
                     ["/missing/" + PRIVATE, "--project", "/tmp/project", "--task", "/tmp/task.json"],
                     ["/tmp/x.zip", "--project", "/tmp/project", "--project", "/tmp/task.json"],
                     ["/tmp/x.zip", "--exec", "/tmp/project", "--task", "/tmp/task.json"]):
            output = io.StringIO()
            with self.subTest(args=args), redirect_stdout(output):code = check.main(args)
            self.assertEqual(code, 2)
            self.assertNotIn(PRIVATE, output.getvalue())
            self.assertIn(json.loads(output.getvalue())["error"], check.CODES | EXPORT_CODES)


if __name__ == "__main__":
    unittest.main()
