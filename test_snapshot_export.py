"""Invented Python/Java snapshot exports, strict evidence, and non-extracting archives."""

import copy
import io
import json
import os
import stat
import struct
import unittest
import zipfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, review_diff, sha
from bundle_workspace import _apply
from test_bundle_workspace import fixture as creation_fixture, passed, tree
from test_workspace_recheck import fixture as workspace_fixture, stage
from workspace_recheck import build
import snapshot_export as export


PRIVATE = "private-check-output-sentinel-94ea"


@contextmanager
def fixture(*, java=False, edit=None, before=None, after=None, checker=passed):
    original = creation_fixture
    def factory(**kwargs):
        return original(before=before, after=after, **kwargs)
    with patch("test_workspace_recheck.creation_fixture", factory), workspace_fixture(java=java) as data:
        root, state, job, source, task, baseline, candidate = data
        if edit is not None:
            name = task["editable"][0]
            (job / "workspace/review" / name).write_bytes(edit(candidate[name]))
        attempt, _, _ = stage(state, job)
        build(attempt, Path("/invented/not-used-jdk") if java else None, checker)
        yield root, state, job, source, task, baseline, candidate, attempt


def change_json(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(canonical(value))


def replace_checks(attempt, raw, display=None):
    (attempt / "checks.json").write_bytes(raw)
    def update(receipt):
        receipt["checks_sha256"] = sha(raw)
        if display is not None:
            receipt["checks"] = display
    change_json(attempt / "receipt.json", update)


def rebuild(result, modify=None, patch_raw=None):
    value = copy.deepcopy(result["verification"])
    patch_raw = result["patch"] if patch_raw is None else patch_raw
    value["hashes"]["patch_sha256"] = sha(patch_raw)
    if modify:
        modify(value)
    payloads = {"changes.diff": patch_raw, "verification.json": canonical(value), "README.txt": export.README}
    payloads["SHA256SUMS"] = export._checksums(payloads)
    return export._archive(payloads)


class SnapshotExportTests(unittest.TestCase):
    def refused(self, operation, *args, code=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            operation(*args, **kwargs)
        self.assertIn(str(caught.exception), export.CODES)
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(str(caught.exception), "SNAPSHOT_EXPORT_" + code)

    def test_python_diff_includes_imported_patch_and_manual_edits_from_baseline(self):
        with fixture(edit=lambda raw: raw.replace(b"return 2", b"return 7") + b"# manual change\n") as (_, _, _, _, task, baseline, _, attempt):
            result = export.prepare(attempt)
            expected = {name: (attempt / "snapshot" / name).read_bytes() for name in baseline}
            changed = [name for name in sorted(baseline) if baseline[name] != expected[name]]
            self.assertEqual(result["patch"], b"".join(review_diff(name, baseline[name], expected[name]).encode() for name in sorted(baseline)))
            self.assertIn(b"-    return 1\n", result["patch"])
            self.assertIn(b"+    return 7\n", result["patch"])
            self.assertEqual(_apply(result["patch"], baseline, changed), expected)
            self.assertEqual(result["summary"]["profile"]["format"], task["format"])
            self.assertEqual(result["summary"]["archive_sha256"], sha(result["archive"]))
            self.assertEqual(set(result), {"summary", "patch", "verification", "archive"})

    def test_java_export_has_fixed_configured_specs_and_positive_saved_observations(self):
        with fixture(java=True, edit=lambda raw: raw + b"// manual Java edit\n") as (_, _, _, _, task, _, _, attempt):
            result = export.prepare(attempt)
            checked = export.verify_export(result["archive"], sha(result["archive"]))
            self.assertEqual(checked["profile"]["format"], "outlands-coding-agent-v2")
            self.assertEqual(checked["checks"][0]["spec"], task["checks"]["unit"])
            self.assertEqual(checked["checks"][0]["observation"], {"exit_code": 0, "tests_ran": 2,
                "timed_out": False, "output_limited": False, "infrastructure_error": False})
            self.assertIn(b"return 1", result["patch"])
            self.assertIn(b"return 2", result["patch"])

    def test_deterministic_fixed_four_members_and_no_human_acceptance_claim(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            first, second = export.prepare(attempt), export.prepare(attempt)
            self.assertEqual(first, second)
            with zipfile.ZipFile(io.BytesIO(first["archive"])) as archive:
                self.assertEqual(archive.namelist(), list(export.MEMBERS))
                for item in archive.infolist():
                    self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(item.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(item.external_attr >> 16, stat.S_IFREG | 0o600)
                readme = archive.read("README.txt")
                self.assertIn(b"contains no human-acceptance assertion", readme)
            self.assertNotIn("accepted", first["verification"])

    def test_private_paths_identifiers_goals_outputs_and_git_refs_are_absent(self):
        def checker(work, task, jdk):
            value = passed(work, task, jdk)
            value["unit"]["output"] = PRIVATE
            return value
        with fixture(checker=checker) as (root, _, job, _, task, _, _, attempt):
            result = export.prepare(attempt)
            members = export._members(result["archive"])
            for raw in members.values():
                for forbidden in (str(root), attempt.name, job.name, PRIVATE, task["goal"], "outlands/bundle-", "refs/heads"):
                    self.assertNotIn(forbidden.encode(), raw)
            self.assertEqual(result["verification"]["not_checked"], export.NOT_CHECKED)
            self.assertFalse(result["verification"]["source_applied"])
            self.assertFalse(result["verification"]["workspace_modified"])

    def test_expected_receipt_hash_refuses_changes_and_invalid_types(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            raw = (attempt / "receipt.json").read_bytes()
            self.assertEqual(export.prepare(attempt, sha(raw))["summary"]["receipt_sha256"], sha(raw))
            self.refused(export.prepare, attempt, "0" * 64, code="STALE")
            for bad in (True, b"0" * 64, "bad"):
                self.refused(export.prepare, attempt, bad, code="INPUT")

    def test_nonverified_and_malformed_receipt_core_fail_closed(self):
        changes = [lambda r: r.update(status="FAILED"), lambda r: r.update(finished=True),
                   lambda r: r.update(version=True), lambda r: r.update(unrecognized="hidden"),
                   lambda r: r.update(snapshot_sha256="bad"), lambda r: r.update(checked_files={}),
                   lambda r: r.update(source_applied=True)]
        for change in changes:
            with self.subTest(change=change), fixture() as (_, _, _, _, _, _, _, attempt):
                change_json(attempt / "receipt.json", change)
                self.refused(export.prepare, attempt)

    def test_request_initial_receipt_and_staged_task_are_required_and_pinned(self):
        for kind in ("request", "initial", "task", "job-path"):
            with self.subTest(kind=kind), fixture() as (_, _, _, _, _, _, _, attempt):
                if kind == "request":change_json(attempt / "request.json", lambda r: r.update(history_sha256="f" * 64))
                elif kind == "initial":change_json(attempt / "initial-receipt.json", lambda r: r.update(created=2))
                elif kind == "task":change_json(attempt / "task.json", lambda r: r.update(goal=PRIVATE))
                else:change_json(attempt / "request.json", lambda r: r.update(job_dir="/private/" + PRIVATE))
                self.refused(export.prepare, attempt)

    def test_full_check_scope_booleans_failures_and_display_disagreement_refuse(self):
        changes = [lambda rows: rows["unit"].update(tests_ran=True), lambda rows: rows["unit"].update(exit_code=1),
                   lambda rows: rows["unit"].update(output_limited=True), lambda rows: rows.update(extra=rows["unit"]),
                   lambda rows: rows.clear(), lambda rows: rows["unit"].update(output=123),
                   lambda rows: rows["unit"].update(private_field=PRIVATE)]
        for change in changes:
            with self.subTest(change=change), fixture() as (_, _, _, _, _, _, _, attempt):
                rows = json.loads((attempt / "checks.json").read_bytes())
                change(rows)
                replace_checks(attempt, canonical(rows))
                self.refused(export.prepare, attempt, code="CHECKS_INVALID")
        with fixture() as (_, _, _, _, _, _, _, attempt):
            change_json(attempt / "receipt.json", lambda r: r["checks"]["unit"].update(output=PRIVATE))
            self.refused(export.prepare, attempt, code="CHECKS_INVALID")

    def test_large_full_unicode_checks_are_not_subject_to_agent_json_display_limit(self):
        output = "😀" * 65536
        def checker(work, task, jdk):
            rows = passed(work, task, jdk)
            rows["unit"]["output"] = output
            return rows
        with fixture(checker=checker) as (_, _, _, _, _, _, _, attempt):
            self.assertGreater((attempt / "checks.json").stat().st_size, 262144)
            receipt = json.loads((attempt / "receipt.json").read_bytes())
            self.assertTrue(receipt["checks"]["unit"]["display_truncated"])
            self.assertFalse(receipt["checks"]["unit"]["output_limited"])
            result = export.prepare(attempt)
            self.assertNotIn("output", result["verification"]["checks"][0]["observation"])
            self.assertEqual(result["summary"]["checks_sha256"], sha((attempt / "checks.json").read_bytes()))

    def test_duplicate_nonfinite_noncanonical_and_oversized_check_records_refuse(self):
        for raw in (b'{"unit":{},"unit":{}}', b'{"unit":NaN}', b'{"unit":Infinity}', b'[]', b'{' + b' ' * 2097152):
            with self.subTest(size=len(raw)), fixture() as (_, _, _, _, _, _, _, attempt):
                replace_checks(attempt, raw)
                self.refused(export.prepare, attempt)
        with fixture() as (_, _, _, _, _, _, _, attempt):
            replace_checks(attempt, (attempt / "checks.json").read_bytes() + b" ")
            self.refused(export.prepare, attempt, code="CHECKS_INVALID")

    def test_original_source_task_config_creation_and_bundle_drift_refuse(self):
        for kind in ("source", "task", "config", "creation", "bundle"):
            with self.subTest(kind=kind), fixture() as (_, _, job, source, task, _, _, attempt):
                if kind == "source":target = source / task["editable"][0]
                elif kind == "task":target = Path(json.loads((job / "request.json").read_bytes())["task_path"])
                elif kind == "config":target = Path(json.loads((job / "request.json").read_bytes())["config_path"])
                elif kind == "creation":target = job / "receipt.json"
                else:target = job / "bundle.zip"
                target.write_bytes(target.read_bytes() + b" ")
                self.refused(export.prepare, attempt)

    def test_later_owner_edit_or_git_metadata_change_requires_fresh_recheck(self):
        for kind in ("editable", "git"):
            with self.subTest(kind=kind), fixture() as (_, _, job, _, task, _, _, attempt):
                target = (job / "workspace/review" / task["editable"][0] if kind == "editable"
                          else job / "workspace/baseline-repo/.git/config")
                target.write_bytes(target.read_bytes() + b"# changed\n")
                self.refused(export.prepare, attempt, code="STALE")

    def test_protected_owner_and_snapshot_changes_refuse(self):
        for owner in (False, True):
            with self.subTest(owner=owner), fixture() as (_, _, job, _, task, _, _, attempt):
                protected = next(name for name in task["files"] if name not in task["editable"])
                target = (job / "workspace/review" if owner else attempt / "snapshot") / protected
                target.write_bytes(b"changed protected source\n")
                self.refused(export.prepare, attempt, code="PROTECTED_CHANGED" if owner else "STALE")

    def test_snapshot_changed_extra_missing_link_hardlink_and_executable_refuse(self):
        for kind in ("changed", "extra", "missing", "symlink", "hardlink", "executable"):
            with self.subTest(kind=kind), fixture() as (_, _, _, _, task, _, _, attempt):
                target = attempt / "snapshot" / task["editable"][0]
                if kind == "changed":target.write_bytes(b"different\n")
                elif kind == "extra":(attempt / "snapshot/extra.txt").write_bytes(b"unexpected")
                elif kind == "missing":target.unlink()
                elif kind == "executable":target.chmod(0o700)
                else:
                    saved = attempt / "saved-source";target.rename(saved)
                    if kind == "symlink":target.symlink_to(saved)
                    else:os.link(saved, target)
                self.refused(export.prepare, attempt)

    def test_binary_invalid_utf8_and_oversized_saved_snapshot_refuse(self):
        for raw in (b"a\x00b", b"\xff", b"x" * 32769):
            with self.subTest(raw=raw[:5]), fixture() as (_, _, _, _, task, _, _, attempt):
                (attempt / "snapshot" / task["editable"][0]).write_bytes(raw)
                self.refused(export.prepare, attempt)

    def test_no_changes_after_manually_reverting_imported_bundle_refuses(self):
        with fixture(edit=lambda _: b"def value():\n    return 1\n") as (_, _, _, _, _, _, _, attempt):
            self.refused(export.prepare, attempt, code="NO_CHANGES")

    def test_unicode_crlf_and_missing_final_newline_roundtrip_exactly(self):
        cases = [(b"def value():\r\n    return 1\r\n", "def value():\r\n    return 2 # é😀\r\n".encode()),
                 (b"def value():\n    return 1", "def value():\n    return 2 # é😀".encode()),
                 (b"", "# é😀\n".encode())]
        for old, new in cases:
            before = {"value.py": old, "test_value.py": b"# protected\n"}
            after = {**before, "value.py": new}
            with self.subTest(old=old), fixture(before=before, after=after) as (_, _, _, _, _, baseline, _, attempt):
                result = export.prepare(attempt)
                self.assertEqual(_apply(result["patch"], baseline, ["value.py"]), after)
                self.assertEqual(export.verify_export(result["archive"])["patch_sha256"], sha(result["patch"]))
                if old and not old.endswith(b"\n"):
                    self.assertIn(b"\\ No newline at end of file\n", result["patch"])

    def test_unsupported_bare_cr_and_unicode_separators_are_explicitly_refused(self):
        for separator in ("\r", "\u2028", "\x85", "\v"):
            with self.subTest(separator=repr(separator)), fixture(edit=lambda raw: raw + ("# first" + separator + "second\n").encode()) as (_, _, _, _, _, _, _, attempt):
                self.refused(export.prepare, attempt, code="PATCH_INVALID")

    def test_diff_preview_clips_unicode_at_byte_and_line_bounds_only_display(self):
        edited = ("# é😀 line\n" * 1900).encode()
        with fixture(edit=lambda _: edited) as (_, _, _, _, _, _, _, attempt):
            result = export.prepare(attempt)
            diff = result["summary"]["diff"]
            self.assertTrue(diff["truncated"])
            self.assertLessEqual(len(diff["text"].encode()), 8192)
            self.assertLessEqual(len(diff["text"].splitlines()), 240)
            self.assertNotIn("\ufffd", diff["text"])
            self.assertEqual(diff["bytes"], len(result["patch"]))
            self.assertGreater(diff["lines"], 240)
            self.assertLessEqual(len(canonical(result["summary"])), 65536)
            self.assertLessEqual(len(result["archive"]), 2097152)

    def test_helper_does_not_treat_global_history_as_its_own_authority(self):
        with fixture() as (_, data, _, _, _, _, _, attempt):
            first = export.prepare(attempt)
            (data / "workspace-rechecks/unrelated-malformed-history").write_bytes(b"not helper authority")
            self.assertEqual(export.prepare(attempt), first)

    def test_readonly_no_subprocess_provider_git_checks_writes_or_source_mutation(self):
        with fixture() as (root, _, _, _, _, _, _, attempt):
            before, real_open = tree(root), os.open
            def readonly(path, flags, *args, **kwargs):
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                return real_open(path, flags, *args, **kwargs)
            with patch("os.open", side_effect=readonly), patch("subprocess.run", side_effect=AssertionError("execution")), \
                 patch("subprocess.Popen", side_effect=AssertionError("execution")), patch("socket.socket", side_effect=AssertionError("network")), \
                 patch("git_workspace.fixed_checks", side_effect=AssertionError("checks")):
                result = export.prepare(attempt)
                export.verify_export(result["archive"])
            self.assertEqual(tree(root), before)

    def test_change_during_preparation_is_caught_by_final_evidence_and_snapshot_pins(self):
        for kind in ("checks", "snapshot"):
            with self.subTest(kind=kind), fixture() as (_, _, _, _, task, _, _, attempt):
                real_archive = export._archive
                changed = False
                def archive(payloads):
                    nonlocal changed
                    raw = real_archive(payloads)
                    if not changed:
                        changed = True
                        target = attempt / ("checks.json" if kind == "checks" else "snapshot/" + task["editable"][0])
                        target.write_bytes(target.read_bytes() + b" ")
                    return raw
                with patch.object(export, "_archive", archive):
                    self.refused(export.prepare, attempt)

    def test_changed_creation_request_is_refused_before_following_its_source_path(self):
        with fixture() as (_, _, job, _, _, _, _, attempt):
            reader = export._read_named
            def changed_request(path, limit, **kwargs):
                raw = reader(path, limit, **kwargs)
                if path == job / "request.json":
                    value = json.loads(raw)
                    value["source"] = "/unapproved/" + PRIVATE
                    return canonical(value)
                return raw
            with patch.object(export, "_read_named", changed_request), \
                 patch.object(export, "prepare_bundle", side_effect=AssertionError("followed changed request")):
                self.refused(export.prepare, attempt, code="STALE")

    def test_tampered_archive_crc_prefix_trailing_records_and_external_digest_refuse(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            raw = export.prepare(attempt)["archive"]
            tampered = bytearray(raw);tampered[50] ^= 1
            for bad in (bytes(tampered), b"prefix" + raw, raw + b"extra", raw[:-1], b"not a ZIP"):
                self.refused(export.verify_export, bad)
            self.refused(export.verify_export, raw, "0" * 64, code="ARCHIVE_CHANGED")
            for pin in (True, "bad", b"0" * 64):self.refused(export.verify_export, raw, pin, code="INPUT")

    def test_unsafe_zip_entries_compression_extra_metadata_and_permissions_refuse(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            result = export.prepare(attempt)
            payloads = export._members(result["archive"])
            for kind in ("compression", "traversal", "duplicate", "extra", "directory", "symlink", "comment", "date"):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    for name in export.MEMBERS:
                        info = zipfile.ZipInfo("../changes.diff" if kind == "traversal" and name == "changes.diff" else name,
                                               (2000, 1, 1, 0, 0, 0) if kind == "date" else (1980, 1, 1, 0, 0, 0))
                        info.create_system = 3
                        info.external_attr = ((stat.S_IFLNK | 0o600) if kind == "symlink" else (stat.S_IFREG | 0o600)) << 16
                        info.compress_type = zipfile.ZIP_DEFLATED if kind == "compression" else zipfile.ZIP_STORED
                        info.extra = b"\x01\x00\x00\x00" if kind == "extra" else b""
                        archive.writestr(info, payloads[name])
                    if kind == "duplicate":archive.writestr("duplicate.diff", b"extra")
                    if kind == "directory":archive.writestr("folder/", b"")
                    if kind == "comment":archive.comment = b"private comment"
                with self.subTest(kind=kind):self.refused(export.verify_export, stream.getvalue())

    def test_verification_schema_privacy_scope_and_positive_counter_checks_are_strict(self):
        changes = [lambda v: v.update(private_field=PRIVATE), lambda v: v.update(version=True),
                   lambda v: v["checks"][0]["observation"].update(tests_ran=True),
                   lambda v: v["checks"][0]["observation"].update(exit_code=False),
                   lambda v: v["checks"][0]["observation"].update(tests_ran=0),
                   lambda v: v["files"][0].update(path="../escape.py"),
                   lambda v: v["files"].reverse(), lambda v: v["profile"].update(max_turns=True),
                   lambda v: v["checks"][0].update(spec={"kind": "shell", "command": PRIVATE}),
                   lambda v: v["files"].extend([v["files"][0]] * 32)]
        with fixture() as (_, _, _, _, _, _, _, attempt):
            result = export.prepare(attempt)
            for change in changes:
                with self.subTest(change=change):self.refused(export.verify_export, rebuild(result, change))

    def test_forged_patch_metadata_scope_counts_and_binary_data_refuse(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            result = export.prepare(attempt)
            for bad in (b"diff --git a/value.py b/value.py\n" + result["patch"],
                        result["patch"].replace(b"a/value.py", b"a/other.py"),
                        result["patch"].replace(b"@@ -1,2 +1,2 @@", b"@@ -1,999999 +1,2 @@"),
                        result["patch"].replace(b"@@ -1,2 +1,2 @@", b"@@ -1,2 +2,2 @@"),
                        b"--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n unchanged context\n",
                        b"--- a/value.py\n+++ b/value.py\n@@ -1,2 +1,2 @@\n-old\n\\ No newline at end of file\n-old again\n+new\n+new again\n",
                        result["patch"] + b"GIT binary patch\n", result["patch"] + b"\x00"):
                self.refused(export.verify_export, rebuild(result, patch_raw=bad))

    def test_archive_and_member_bounds_checked_before_payload_allocations(self):
        self.refused(export.verify_export, b"x" * (2097152 + 1), code="LIMIT")
        with fixture() as (_, _, _, _, _, _, _, attempt):
            raw = bytearray(export.prepare(attempt)["archive"])
            start = struct.unpack_from("<I", raw, len(raw) - 6)[0]
            struct.pack_into("<I", raw, start + 20, 0xffffffff)
            struct.pack_into("<I", raw, start + 24, 0xffffffff)
            self.refused(export.verify_export, bytes(raw), code="LIMIT")

    def test_cli_verifies_explicit_safe_file_without_extracting_or_writing(self):
        with fixture() as (root, _, _, _, _, _, _, attempt):
            raw = export.prepare(attempt)["archive"]
            target = root / "private-packet.zip";target.write_bytes(raw)
            before, output = tree(root), io.StringIO()
            with redirect_stdout(output), patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extract")), \
                 patch("subprocess.run", side_effect=AssertionError("execution")):
                code = export.main(["--archive", str(target), "--expected-sha256", sha(raw)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["archive_sha256"], sha(raw))
            self.assertEqual(tree(root), before)

    def test_cli_paths_links_bad_arguments_and_private_errors_are_fixed(self):
        with fixture() as (root, _, _, _, _, _, _, attempt):
            target = root / "packet.zip";target.write_bytes(export.prepare(attempt)["archive"])
            link = root / "link.zip";link.symlink_to(target)
            hard = root / "hard.zip";os.link(target, hard)
            alias = root / "alias";alias.symlink_to(root, target_is_directory=True)
            cases = [["--archive", "relative.zip"], ["--archive", str(link)], ["--archive", str(hard)],
                     ["--archive", str(alias / "packet.zip")], ["--archive", str(root)],
                     ["--archive", "/missing/" + PRIVATE], ["--extract", str(target)],
                     ["--archive", str(target), "--archive", str(target)]]
            for args in cases:
                output = io.StringIO()
                with self.subTest(args=args), redirect_stdout(output):code = export.main(args)
                self.assertNotEqual(code, 0)
                self.assertIn(json.loads(output.getvalue())["error"], export.CODES)
                self.assertNotIn(PRIVATE, output.getvalue())

    def test_maximum_32_file_scope_and_total_byte_policy_are_preserved(self):
        before = {"value.py": b"1" * 4096, "test_value.py": b"#" * 4096,
                  **{"file%02d.py" % index: b"x" * 4096 for index in range(30)}}
        after = {**before, "value.py": b"2" * 4096}
        with fixture(before=before, after=after) as (_, _, _, _, _, _, _, attempt):
            result = export.prepare(attempt)
            self.assertEqual(len(result["summary"]["files"]), 32)
            self.assertEqual(len(result["verification"]["files"]), 32)
            self.assertLessEqual(len(canonical(result["summary"])), 65536)
            self.assertEqual(export.verify_export(result["archive"])["files"], result["summary"]["files"])


if __name__ == "__main__":
    unittest.main()
