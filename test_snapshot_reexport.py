"""Invented v16 evidence and strict v1/v2 packets; no check/provider/Git execution."""

import copy
import io
import json
import os
import stat
import struct
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, review_diff, sha
from bundle_workspace import _apply, _check_results
from snapshot_project_check import check_project
from snapshot_workspace import prepare as prepare_workspace
from test_snapshot_project_check import packet as v1_packet
from test_snapshot_recheck import fixture as workspace_fixture, passed, stage, tree
import snapshot_export as export
import snapshot_recheck as recheck
import snapshot_reexport as reexport


PRIVATE = "invented-private-reexport-check-output-82a6"


@contextmanager
def fixture(*, java=False, before=None, after=None, edit=None, checker=passed):
    with workspace_fixture(java=java, before=before, after=after) as (root, data, job, source, task, baseline, imported):
        if edit is not None:
            name = task["editable"][0]
            (job / "workspace/review" / name).write_bytes(edit(imported[name]))
        attempt, _, _ = stage(data, job)
        recheck.run(attempt, Path("/invented/not-executed-jdk") if java else None, checker)
        yield root, data, job, source, task, baseline, imported, attempt


def change(path, function):
    value = json.loads(path.read_bytes())
    function(value)
    path.write_bytes(canonical(value))


def rebuild(result, modify=None, patch_raw=None, readme=None):
    value = copy.deepcopy(result["verification"])
    patch_raw = result["patch"] if patch_raw is None else patch_raw
    value["hashes"]["patch_sha256"] = sha(patch_raw)
    if modify:
        modify(value)
    payloads = {"changes.diff": patch_raw, "verification.json": canonical(value),
                "README.txt": export.README_V2 if readme is None else readme}
    payloads["SHA256SUMS"] = export._checksums(payloads)
    return export._archive(payloads)


class SnapshotReexportTests(unittest.TestCase):
    def refused(self, operation, *args, suffix=None, shared=False, **kwargs):
        with self.assertRaises(Refused) as caught:
            operation(*args, **kwargs)
        self.assertIn(str(caught.exception), export.CODES if shared else reexport.CODES)
        self.assertNotIn(PRIVATE, str(caught.exception))
        if suffix:
            self.assertEqual(str(caught.exception), ("SNAPSHOT_EXPORT_" if shared else "SNAPSHOT_REEXPORT_") + suffix)

    def test_exact_complete_original_baseline_to_tested_snapshot_includes_imported_and_manual_changes(self):
        with fixture(edit=lambda raw: raw.replace(b"return 2", b"return 7") + b"# manual edit\n") as (_, _, _, _, task, before, _, attempt):
            result = reexport.prepare(attempt)
            selected = {name: (attempt / "snapshot" / name).read_bytes() for name in before}
            expected = b"".join(review_diff(name, before[name], selected[name]).encode() for name in sorted(before))
            self.assertEqual(result["patch"], expected)
            self.assertIn(b"-    return 1\n", result["patch"]);self.assertIn(b"+    return 7\n", result["patch"])
            self.assertIn(b"-OTHER = 1\n+OTHER = 2\n", result["patch"])
            changed = [name for name in sorted(before) if before[name] != selected[name]]
            self.assertEqual(_apply(result["patch"], before, changed), selected)
            self.assertEqual(set(result), {"summary", "patch", "verification", "archive"})
            self.assertEqual(result["summary"]["profile"], {key: task[key] for key in ("format", "max_turns", "request_seconds")})

    def test_v2_version_evidence_and_hashes_are_distinct_without_fake_bundle_pin(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (_, _, job, _, task, _, _, attempt):
                result = reexport.prepare(attempt)
                verified = export.verify_export(result["archive"], sha(result["archive"]))
                self.assertEqual((verified["version"], verified["format"]), (2, export.FORMAT_V2))
                self.assertEqual(result["verification"]["evidence"], "RECORDED_PASSING_SNAPSHOT_WORKSPACE_RECHECK")
                self.assertEqual(set(verified["hashes"]), export.HASH_FIELDS_V2)
                self.assertNotIn("bundle_sha256", verified["hashes"])
                self.assertNotIn("bundle_sha256", result["summary"])
                self.assertEqual(result["summary"]["import_archive_sha256"], sha((job / "snapshot.zip").read_bytes()))
                self.assertEqual(result["summary"]["archive_sha256"], sha(result["archive"]))
                self.assertNotEqual(result["summary"]["archive_sha256"], result["summary"]["import_archive_sha256"])
                self.assertEqual(verified["checks"][0]["spec"], task["checks"]["unit"])
                self.assertEqual(verified["hashes"], result["verification"]["hashes"])

    def test_v2_project_and_snapshot_workspace_in_memory_roundtrip(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java, edit=lambda raw: raw + b"// owner edit\n") as (_, _, _, source, task, before, _, attempt):
                result = reexport.prepare(attempt)
                task_raw = canonical(task)
                compared = check_project(result["archive"], source, task_raw, sha(result["archive"]))
                self.assertEqual(compared["status"], "BASELINE_MATCH")
                self.assertEqual(compared["reconstruction"]["status"], "VERIFIED")
                reconstructed = prepare_workspace(result["archive"], source, task_raw, sha(result["archive"]))
                self.assertEqual(reconstructed["baseline"], before)
                self.assertEqual(reconstructed["snapshot"], {name: (attempt / "snapshot" / name).read_bytes() for name in before})
                self.assertEqual(reconstructed["task"], task)
                self.assertEqual(reconstructed["summary"]["export_snapshot_sha256"], result["summary"]["snapshot_sha256"])

    def test_v1_packet_bytes_and_verifier_summary_stay_v1_without_union_hash_schema(self):
        before = {"main.py": b"def value():\n    return 1\n", "test_main.py": b"# protected\n"}
        after = {**before, "main.py": b"def value():\n    return 2\n"}
        raw, _ = v1_packet(before, after, ["main.py"])
        members = export._members(raw)
        verification = json.loads(members["verification.json"])
        checked = export.verify_export(raw)
        self.assertEqual((export.FORMAT, checked["format"], checked["version"]), ("outlands-reviewed-snapshot-export-v1", export.FORMAT, 1))
        self.assertEqual(members["README.txt"], export.README)
        self.assertEqual(export._archive(members), raw)
        self.assertEqual(set(verification["hashes"]), export.HASH_FIELDS)
        self.assertIn("bundle_sha256", verification["hashes"]);self.assertNotIn("import_archive_sha256", verification["hashes"])
        expected = {"version": 1, "format": export.FORMAT, "archive_sha256": sha(raw), "archive_bytes": len(raw),
            "patch_sha256": sha(members["changes.diff"]), "patch_bytes": len(members["changes.diff"]),
            "verification_sha256": sha(members["verification.json"]), "verification_bytes": len(members["verification.json"]),
            "member_count": 4, "members": [{"path": name, "bytes": len(members[name]), "sha256": sha(members[name])} for name in export.MEMBERS],
            **{key: verification[key] for key in ("hashes", "profile", "files", "checks", "not_checked", "notes")}}
        self.assertEqual(checked, expected)
        payloads = dict(members)
        verification["hashes"]["import_archive_sha256"] = verification["hashes"].pop("bundle_sha256")
        payloads["verification.json"] = canonical(verification);payloads["SHA256SUMS"] = export._checksums(payloads)
        self.refused(export.verify_export, export._archive(payloads), shared=True)

    def test_version_format_evidence_hash_and_readme_mixed_tuples_are_refused(self):
        modifications = [lambda value: value.update(version=1), lambda value: value.update(version=True),
            lambda value: value.update(version=3), lambda value: value.update(format=export.FORMAT),
            lambda value: value.update(evidence="RECORDED_PASSING_WORKSPACE_RECHECK"),
            lambda value: value["hashes"].update(bundle_sha256="a" * 64),
            lambda value: value["hashes"].update(bundle_sha256=value["hashes"].pop("import_archive_sha256")),
            lambda value: value.update(unrecognized=PRIVATE),
            lambda value: value["checks"][0]["observation"].update(exit_code=False)]
        with fixture() as (_, _, _, _, _, _, _, attempt):
            result = reexport.prepare(attempt)
            for index, modify in enumerate(modifications):
                with self.subTest(index=index):self.refused(export.verify_export, rebuild(result, modify), shared=True)
            self.refused(export.verify_export, rebuild(result, readme=export.README), shared=True)
            self.refused(export.verify_export, rebuild(result, readme=export.README_V2 + b"extra"), shared=True)

    def test_four_private_members_deterministic_bytes_and_no_acceptance_or_output_claims(self):
        def checker(*args):
            checks = passed(*args);checks["unit"]["output"] = PRIVATE;return checks
        with fixture(checker=checker) as (root, _, job, _, task, _, _, attempt):
            result = reexport.prepare(attempt)
            self.assertEqual(result, reexport.prepare(attempt))
            with zipfile.ZipFile(io.BytesIO(result["archive"])) as archive:
                self.assertEqual(archive.namelist(), list(export.MEMBERS))
                for member in archive.infolist():
                    self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(member.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(member.external_attr >> 16, stat.S_IFREG | 0o600)
                self.assertEqual(archive.read("README.txt"), export.README_V2)
            for raw in export._members(result["archive"]).values():
                for forbidden in (str(root), attempt.name, job.name, task["goal"], PRIVATE, "outlands/snapshot-", "refs/heads"):
                    self.assertNotIn(forbidden.encode(), raw)
            self.assertEqual(result["verification"]["not_checked"], export.NOT_CHECKED)
            self.assertEqual(result["verification"]["notes"], export.NOTES)
            self.assertNotIn("accepted", result["verification"])
            self.assertEqual(set(result["verification"]["checks"][0]["observation"]), set(export.CORE))

    def test_receipt_expected_raw_pin_types_status_and_original_format_are_required(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            raw = (attempt / "receipt.json").read_bytes()
            self.assertEqual(reexport.prepare(attempt, sha(raw))["summary"]["receipt_sha256"], sha(raw))
            self.refused(reexport.prepare, attempt, "f" * 64, suffix="STALE")
            for pin in (True, b"f" * 64, "bad"):
                self.refused(reexport.prepare, attempt, pin, suffix="INPUT")
        for modify in (lambda value: value.update(status="FAILED"), lambda value: value.update(version=True),
                       lambda value: value.update(format="outlands-workspace-recheck-v1"),
                       lambda value: value.update(unexpected=PRIVATE), lambda value: value.update(source_applied=True)):
            with self.subTest(modify=modify), fixture() as (_, _, _, _, _, _, _, attempt):
                change(attempt / "receipt.json", modify);self.refused(reexport.prepare, attempt)

    def test_initial_request_task_and_creation_evidence_are_bound(self):
        for kind in ("initial", "request", "task", "job-path", "creation", "creation-initial", "creation-request", "creation-checks", "import"):
            with self.subTest(kind=kind), fixture() as (_, _, job, _, _, _, _, attempt):
                if kind == "initial": change(attempt / "initial-receipt.json", lambda value: value.update(created=2))
                elif kind == "request": change(attempt / "request.json", lambda value: value.update(history_sha256="f" * 64))
                elif kind == "task": (attempt / "task.json").write_bytes(b"{}\n")
                elif kind == "job-path": change(attempt / "request.json", lambda value: value.update(job_dir="/unapproved/" + PRIVATE))
                else:
                    name = {"creation": "receipt.json", "creation-initial": "initial-receipt.json", "creation-request": "request.json",
                            "creation-checks": "checks.json", "import": "snapshot.zip"}[kind]
                    path = job / name;path.write_bytes(path.read_bytes() + b" ")
                self.refused(reexport.prepare, attempt)

    def test_source_config_approved_task_later_owner_edit_and_git_drift_need_new_evidence(self):
        for kind in ("source", "config", "task", "worktree", "git", "protected"):
            with self.subTest(kind=kind), fixture() as (_, _, job, source, task, _, _, attempt):
                request = json.loads((job / "request.json").read_bytes())
                if kind == "source": path = source / task["editable"][0]
                elif kind in {"config", "task"}: path = Path(request["config_path" if kind == "config" else "task_path"])
                elif kind == "git": path = job / "workspace/baseline-repo/.git/config"
                else:
                    name = next(name for name in task["files"] if name not in task["editable"]) if kind == "protected" else task["editable"][0]
                    path = job / "workspace/review" / name
                path.write_bytes(path.read_bytes() + b"# drift\n")
                self.refused(reexport.prepare, attempt)

    def test_full_checks_types_scope_canonical_display_and_profile_are_required(self):
        for kind in ("types", "scope", "noncanonical", "display", "profile", "unknown"):
            with self.subTest(kind=kind), fixture() as (_, _, _, _, task, _, _, attempt):
                rows = json.loads((attempt / "checks.json").read_bytes())
                if kind == "types": rows["unit"]["exit_code"] = False
                elif kind == "scope": rows["other"] = rows.pop("unit")
                elif kind == "display": change(attempt / "receipt.json", lambda value: value["checks"]["unit"].update(output=PRIVATE))
                elif kind == "profile": rows["unit"]["kind"] = "java-main"
                elif kind == "unknown": rows["unit"]["extra"] = PRIVATE
                raw = canonical(rows) + (b" " if kind == "noncanonical" else b"")
                (attempt / "checks.json").write_bytes(raw)
                change(attempt / "receipt.json", lambda value: value.update(checks_sha256=sha(raw)))
                if kind == "profile":
                    _, display, _ = _check_results(rows, task)
                    change(attempt / "receipt.json", lambda value: value.update(checks=display))
                self.refused(reexport.prepare, attempt, suffix="CHECKS_INVALID")

    def test_large_full_unicode_check_output_is_pinned_but_not_exported(self):
        output = "😀" * 65536
        def checker(*args):
            rows = passed(*args);rows["unit"]["output"] = output;return rows
        with fixture(checker=checker) as (_, _, _, _, _, _, _, attempt):
            self.assertGreater((attempt / "checks.json").stat().st_size, 262144)
            result = reexport.prepare(attempt)
            receipt = json.loads((attempt / "receipt.json").read_bytes())
            self.assertTrue(receipt["checks"]["unit"]["display_truncated"])
            self.assertEqual(result["summary"]["checks_sha256"], sha((attempt / "checks.json").read_bytes()))
            self.assertNotIn("output", result["verification"]["checks"][0]["observation"])

    def test_snapshot_scope_protected_links_modes_and_bytes_are_read_safely(self):
        for kind in ("changed", "protected", "extra", "missing", "link", "hardlink", "executable", "binary", "size"):
            with self.subTest(kind=kind), fixture() as (_, _, _, _, task, _, _, attempt):
                name = next(name for name in task["files"] if name not in task["editable"]) if kind == "protected" else task["editable"][0]
                path = attempt / "snapshot" / name
                if kind in {"changed", "protected"}: path.write_bytes(b"changed bytes\n")
                elif kind == "extra": (attempt / "snapshot/extra.py").write_bytes(b"extra\n")
                elif kind == "missing": path.unlink()
                elif kind in {"link", "hardlink"}:
                    saved = attempt / "saved";path.rename(saved)
                    if kind == "link": path.symlink_to(saved)
                    else: path.hardlink_to(saved)
                elif kind == "executable": path.chmod(0o700)
                elif kind == "binary": path.write_bytes(b"bad\x00bytes")
                else: path.write_bytes(b"x" * 32769)
                self.refused(reexport.prepare, attempt)

    def test_unicode_crlf_empty_and_missing_final_newline_patch_is_exact(self):
        cases = [(b"def value():\r\n    return 1\r\n", "def value():\r\n    return 2 # café😀\r\n".encode()),
                 (b"old", "new café😀".encode()), (b"", "# café😀\n".encode()), (b"deleted\n", b"")]
        for old, new in cases:
            before = {"main.py": old, "test_main.py": b"# protected\n"}
            after = {**before, "main.py": new}
            with self.subTest(old=old), fixture(before=before, after=after) as (_, _, _, source, task, _, _, attempt):
                result = reexport.prepare(attempt)
                self.assertEqual(_apply(result["patch"], before, ["main.py"]), after)
                self.assertEqual(prepare_workspace(result["archive"], source, canonical(task))["snapshot"], after)
                if old and not old.endswith(b"\n"):
                    self.assertIn(b"\\ No newline at end of file\n", result["patch"])

    def test_diff_preview_truncation_does_not_truncate_packet_or_invent_decoding(self):
        edited = ("# é😀 line\n" * 1900).encode()
        with fixture(edit=lambda _: edited) as (_, _, _, _, _, _, _, attempt):
            result = reexport.prepare(attempt)
            preview = result["summary"]["diff"]
            self.assertTrue(preview["truncated"])
            self.assertLessEqual(len(preview["text"].encode()), 8192)
            self.assertLessEqual(len(preview["text"].splitlines()), 240)
            self.assertNotIn("\ufffd", preview["text"])
            self.assertEqual(preview["bytes"], len(result["patch"]))
            self.assertGreater(preview["lines"], 240)
            self.assertEqual(export._members(result["archive"])["changes.diff"], result["patch"])

    def test_no_changes_after_full_manual_revert_and_unsupported_line_separators_refuse(self):
        before = {"main.py": b"def value():\n    return 1\n", "test_main.py": b"# protected\n"}
        after = {**before, "main.py": b"def value():\n    return 2\n"}
        with fixture(before=before, after=after, edit=lambda _: before["main.py"]) as (_, _, _, _, _, _, _, attempt):
            self.refused(reexport.prepare, attempt, suffix="NO_CHANGES")
        for separator in ("\r", "\u2028", "\x85", "\v"):
            with self.subTest(separator=repr(separator)), fixture(edit=lambda raw: raw + ("# a" + separator + "b\n").encode()) as (_, _, _, _, _, _, _, attempt):
                self.refused(reexport.prepare, attempt, suffix="PATCH_INVALID")

    def test_late_checks_snapshot_config_request_or_pending_sentinel_cannot_escape_final_pins(self):
        for kind in ("checks", "snapshot", "config", "request", "initial", "attempt-next", "creation-next"):
            with self.subTest(kind=kind), fixture() as (_, _, job, _, task, _, _, attempt):
                real_archive = reexport._archive
                def late(payloads):
                    raw = real_archive(payloads)
                    if kind == "checks": path = attempt / "checks.json"
                    elif kind == "snapshot": path = attempt / "snapshot" / task["editable"][0]
                    elif kind == "config": path = Path(json.loads((job / "request.json").read_bytes())["config_path"])
                    elif kind == "request": path = attempt / "request.json"
                    elif kind == "initial": path = attempt / "initial-receipt.json"
                    elif kind == "attempt-next": path = attempt / "receipt.json.next"
                    else: path = job / "receipt.json.next"
                    path.write_bytes(path.read_bytes() + b" " if path.exists() else b"retained unknown\n")
                    return raw
                with patch.object(reexport, "_archive", side_effect=late): self.refused(reexport.prepare, attempt)

    def test_changed_creation_request_is_rejected_before_following_its_external_source(self):
        with fixture() as (_, _, job, _, _, _, _, attempt):
            reader = reexport._read_named
            def changed(path, limit, **kwargs):
                raw = reader(path, limit, **kwargs)
                if path == job / "request.json":
                    value = json.loads(raw);value["source"] = "/unapproved/" + PRIVATE;return canonical(value)
                return raw
            with patch.object(reexport, "_read_named", side_effect=changed), \
                 patch.object(reexport, "prepare_workspace", side_effect=AssertionError("followed changed path")):
                self.refused(reexport.prepare, attempt, suffix="STALE")

    def test_pending_sentinels_unknown_history_and_readonly_execution_boundary(self):
        with fixture() as (root, data, _, _, _, _, _, attempt):
            baseline = reexport.prepare(attempt)
            (data / "snapshot-workspace-rechecks/unrelated-unknown-history").write_bytes(b"not this helper authority")
            hold = data / "held/hold.json";hold.parent.mkdir(mode=0o700);hold.write_bytes(b"never read or clear")
            before, real_open = tree(root), os.open
            def readonly(path, flags, *args, **kwargs):
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                self.assertNotIn("hold", str(path))
                return real_open(path, flags, *args, **kwargs)
            with patch("os.open", side_effect=readonly), patch("subprocess.run", side_effect=AssertionError("process")), \
                 patch("subprocess.Popen", side_effect=AssertionError("process")), patch("socket.socket", side_effect=AssertionError("network")), \
                 patch("git_workspace.fixed_checks", side_effect=AssertionError("checks")):
                self.assertEqual(reexport.prepare(attempt), baseline)
                export.verify_export(baseline["archive"])
            self.assertEqual(tree(root), before)
            (attempt / "receipt.json.next").write_bytes(b"retained partial\n")
            before = tree(root);self.refused(reexport.prepare, attempt);self.assertEqual(tree(root), before)

    def test_limits_archive_framing_digest_and_patch_tampering_refuse(self):
        with fixture() as (_, _, _, _, _, _, _, attempt):
            result = reexport.prepare(attempt)
            self.assertLessEqual(len(canonical(result["summary"])), 65536)
            self.assertLessEqual(len(result["archive"]), 2097152)
            self.refused(export.verify_export, result["archive"], "f" * 64, shared=True, suffix="ARCHIVE_CHANGED")
            raw = result["archive"];broken = bytearray(raw);broken[50] ^= 1
            for invalid in (bytes(broken), b"prefix" + raw, raw + b"trailing", raw[:-1]):
                self.refused(export.verify_export, invalid, shared=True)
            self.refused(export.verify_export, b"x" * 2097153, shared=True, suffix="LIMIT")
            payloads = export._members(raw)
            tampered = bytearray(raw);position = raw.index(b"PK\x01\x02")
            struct.pack_into("<I", tampered, position + 20, 1048577)
            struct.pack_into("<I", tampered, position + 24, 1048577)
            self.refused(export.verify_export, bytes(tampered), shared=True, suffix="LIMIT")
            bad_patch = result["patch"].replace(b"--- a/main.py", b"--- a/outside.py")
            self.refused(export.verify_export, rebuild(result, patch_raw=bad_patch), shared=True)
            self.assertEqual(payloads["README.txt"], export.README_V2)


if __name__ == "__main__":
    unittest.main()
