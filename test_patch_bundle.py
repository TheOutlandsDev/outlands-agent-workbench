"""Offline bundle and read-only CLI tests using invented Python/Java records."""

import copy
import hashlib
import io
import json
import os
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical
from patch_bundle import MAX_ARCHIVE, MAX_JSON, MAX_PATCH, MEMBERS, build_bundle, main, verify_bundle


PRIVATE = "invented-private-record-field-that-must-not-be-exported"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def records(*, java=False):
    if java:
        module, protected = "sample/Value.java", "sample/ValueTest.java"
        before = b"package sample; class Value { static int value() { return 1; } }\n"
        after = before.replace(b"return 1", b"return 2")
        spec = {"kind": "java-main", "sources": [module, protected], "main_class": "sample.ValueTest"}
        task_format = "outlands-coding-agent-v2"
    else:
        module, protected = "module.py", "test_module.py"
        before, after = b"def value(): return 1\n", b"def value(): return 2\n"
        spec, task_format = "test_module.py", "outlands-coding-agent-v1"
    baseline = {module: sha(before), protected: sha(b"invented protected test\n")}
    task = {"format": task_format, "goal": PRIVATE, "files": baseline, "editable": [module],
            "checks": {"unit": spec}, "max_turns": 3, "request_seconds": 17}
    diff = ("--- a/" + module + "\n+++ b/" + module + "\n@@ -1 +1 @@\n-" + before.decode() + "+" + after.decode()).encode()
    result = {"format": task_format, "status": "REVIEW_READY", "reason": "CHECKS_PASSED",
        "source_adopted": False, "files": {name: {"before": digest, "after": sha(after) if name == module else digest}
                                          for name, digest in baseline.items()},
        "patch_sha256": sha(diff), "backend": PRIVATE, "prompt": PRIVATE, "source": "/private/" + PRIVATE}
    result_raw = canonical(result)
    review = {"id": "1" * 16, "verdict": "accepted", "source_applied": False, "recorded": 1234,
              "result_sha256": sha(result_raw), "patch_sha256": sha(diff), "note": PRIVATE, "identity": PRIVATE}
    final = {"index": 7, "kind": "independent_final_checks", "value": {"unit": {
        "exit_code": 0, "tests_ran": 2, "timed_out": False, "output_limited": False,
        "infrastructure_error": False, "output": PRIVATE}}, "raw_exception": PRIVATE}
    return [canonical(task), result_raw, canonical(review), canonical(final), diff]


def change_record(inputs, position, change, *, repin=True):
    value = json.loads(inputs[position])
    change(value)
    inputs[position] = canonical(value)
    if position == 1 and repin:
        review = json.loads(inputs[2])
        review["result_sha256"] = sha(inputs[1])
        inputs[2] = canonical(review)


def contents(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def rewrite(raw, replacements=None, *, checksum=True, info_change=None, extra=None, order=None,
            compression=zipfile.ZIP_STORED, comment=b""):
    with zipfile.ZipFile(io.BytesIO(raw)) as original:
        data = {name: original.read(name) for name in original.namelist()}
        infos = {name: copy.copy(original.getinfo(name)) for name in original.namelist()}
    data.update(replacements or {})
    if checksum:
        data["SHA256SUMS"] = "".join(sha(data[name]) + "  " + name + "\n"
            for name in sorted(data) if name != "SHA256SUMS").encode("ascii")
    target = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(target, "w", compression=compression, allowZip64=False) as archive:
            for name in order or MEMBERS:
                info = infos[name]
                info.compress_type = compression
                if info_change:
                    info_change(info)
                archive.writestr(info, data[name])
            if extra:
                archive.writestr(*extra)
            archive.comment = comment
    return target.getvalue()


class BundleTests(unittest.TestCase):
    def assert_refused(self, operation, *args, code=None):
        with self.assertRaises(Refused) as caught:
            operation(*args)
        self.assertRegex(str(caught.exception), r"^BUNDLE_[A-Z_]+$")
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(caught.exception.args, (code,))

    def test_python_and_java_roundtrip_preserves_only_selected_evidence(self):
        for java in (False, True):
            with self.subTest(java=java):
                inputs = records(java=java)
                raw = build_bundle(*inputs)
                value = verify_bundle(raw, sha(raw))
                self.assertEqual(set(value), {"version", "bundle_sha256", "archive_bytes", "member_count", "members",
                    "hashes", "files", "checks", "review", "not_checked", "notes"})
                self.assertEqual(value["bundle_sha256"], sha(raw))
                self.assertEqual(value["archive_bytes"], len(raw))
                self.assertEqual(value["member_count"], 6)
                self.assertEqual([row["path"] for row in value["members"]], list(MEMBERS))
                self.assertEqual(value["hashes"], dict(zip(
                    ("task_sha256", "result_sha256", "review_record_sha256", "final_event_sha256", "patch_sha256"), map(sha, inputs))))
                self.assertEqual(value["review"], {"verdict": "accepted", "source_applied": False})
                self.assertEqual(value["checks"][0]["tests_ran"], 2)
                self.assertEqual(value["not_checked"], ["CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "GIT_ADOPTION"])
                self.assertEqual(value["notes"], ["PRIVATE_SOURCE_CONTENT", "RECORDED_CHECKS_ONLY", "UNSIGNED_BUNDLE"])
                self.assertEqual(contents(raw)["changes.diff"], inputs[4])
                self.assertNotIn(PRIVATE, b"\n".join(contents(raw).values()).decode())
                self.assertNotIn(PRIVATE, canonical(value).decode())
                self.assertLessEqual(len(canonical(value)), 65536)

    def test_exact_inputs_produce_identical_archives_and_summaries(self):
        inputs = records(java=True)
        first, second = build_bundle(*inputs), build_bundle(*inputs)
        self.assertEqual(first, second)
        self.assertEqual(verify_bundle(first), verify_bundle(second))
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o600)
                self.assertEqual(info.extra, b"")
                self.assertEqual(info.comment, b"")

    def test_checksums_cover_exactly_five_other_members_in_sorted_order(self):
        raw = build_bundle(*records())
        data = contents(raw)
        expected = "".join(sha(data[name]) + "  " + name + "\n" for name in sorted(data) if name != "SHA256SUMS")
        self.assertEqual(data["SHA256SUMS"], expected.encode())
        self.assertEqual(len(expected.splitlines()), 5)

    def test_raw_task_review_and_final_hashes_preserve_original_json_bytes(self):
        inputs = records()
        for position in (0, 2, 3):
            inputs[position] = json.dumps(json.loads(inputs[position]), indent=3).encode()
        value = verify_bundle(build_bundle(*inputs))
        self.assertEqual(value["hashes"]["task_sha256"], sha(inputs[0]))
        self.assertEqual(value["hashes"]["review_record_sha256"], sha(inputs[2]))
        self.assertEqual(value["hashes"]["final_event_sha256"], sha(inputs[3]))

    def test_noncanonical_result_identity_is_refused(self):
        inputs = records()
        inputs[1] = json.dumps(json.loads(inputs[1]), indent=2).encode()
        change_record(inputs, 2, lambda value: value.update(result_sha256=sha(inputs[1])))
        self.assert_refused(build_bundle, *inputs, code="BUNDLE_RECORD_INVALID")

    def test_unaccepted_uncertain_and_adopted_records_refuse(self):
        for position, update, code in ((2, {"verdict": "rejected"}, "BUNDLE_REVIEW_REQUIRED"),
            (1, {"status": "UNCERTAIN"}, "BUNDLE_NOT_REVIEW_READY"),
            (1, {"status": "FAILED"}, "BUNDLE_NOT_REVIEW_READY"),
            (1, {"source_adopted": True}, "BUNDLE_RECORD_INVALID"),
            (2, {"source_applied": True}, "BUNDLE_RECORD_INVALID")):
            inputs = records()
            change_record(inputs, position, lambda value: value.update(update))
            self.assert_refused(build_bundle, *inputs, code=code)

    def test_missing_pins_and_tampered_result_patch_and_baseline_refuse(self):
        cases = [(2, lambda value: value.pop("result_sha256"), "BUNDLE_PIN_REQUIRED"),
                 (2, lambda value: value.update(result_sha256="f" * 64), "BUNDLE_ARTIFACT_CHANGED"),
                 (2, lambda value: value.update(patch_sha256="f" * 64), "BUNDLE_ARTIFACT_CHANGED"),
                 (1, lambda value: value["files"]["module.py"].update(before="f" * 64), "BUNDLE_ARTIFACT_CHANGED"),
                 (1, lambda value: value["files"]["test_module.py"].update(after="f" * 64), "BUNDLE_ARTIFACT_CHANGED")]
        for position, change, code in cases:
            inputs = records()
            change_record(inputs, position, change)
            self.assert_refused(build_bundle, *inputs, code=code)

    def test_review_id_timestamp_and_final_index_require_exact_integer_types(self):
        for position, update in ((2, {"recorded": True}), (2, {"recorded": -1}),
                (2, {"recorded": 9007199254740992}), (2, {"id": "../private"}),
                (3, {"index": True}), (3, {"index": 256}), (3, {"index": -1})):
            inputs = records()
            change_record(inputs, position, lambda value: value.update(update))
            self.assert_refused(build_bundle, *inputs)

    def test_final_check_scope_and_passing_observations_are_strict(self):
        for update in ({"exit_code": True}, {"exit_code": 1}, {"tests_ran": True}, {"tests_ran": 0},
                {"tests_ran": 9007199254740992}, {"timed_out": True}, {"timed_out": 0},
                {"output_limited": True}, {"infrastructure_error": True}):
            inputs = records()
            change_record(inputs, 3, lambda value: value["value"]["unit"].update(update))
            self.assert_refused(build_bundle, *inputs, code="BUNDLE_FINAL_REQUIRED")
        for update in ({"kind": "baseline_checks"}, {"value": {}}, {"value": []}):
            inputs = records()
            change_record(inputs, 3, lambda value: value.update(update))
            self.assert_refused(build_bundle, *inputs, code="BUNDLE_FINAL_REQUIRED")

    def test_malformed_raw_records_and_task_profiles_have_fixed_refusals(self):
        for malformed in (b"{", b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b"\xff", b"null", bytearray(b"{}"), None):
            for position in range(4):
                inputs = records()
                inputs[position] = malformed
                self.assert_refused(build_bundle, *inputs)
        for update in ({"max_turns": True}, {"request_seconds": 121}, {"editable": ["test_module.py"]},
                       {"files": {"../outside.py": "a" * 64}}, {"extra": PRIVATE}):
            inputs = records()
            change_record(inputs, 0, lambda value: value.update(update))
            self.assert_refused(build_bundle, *inputs)

    def test_result_format_scope_and_final_extra_check_are_not_silently_accepted(self):
        for update in ({"format": "unknown"}, {"format": True}, {"files": []}, {"files": {}}):
            inputs = records()
            change_record(inputs, 1, lambda value: value.update(update))
            self.assert_refused(build_bundle, *inputs, code="BUNDLE_RECORD_INVALID")
        inputs = records()
        change_record(inputs, 3, lambda value: value["value"].update(unselected={"exit_code": 0}))
        self.assert_refused(build_bundle, *inputs, code="BUNDLE_FINAL_REQUIRED")

    def test_empty_binary_invalid_utf8_and_oversized_patch_refuse(self):
        for raw in (b"", b"a\x00b", b"\xff", b"x" * (MAX_PATCH + 1)):
            inputs = records()
            inputs[4] = raw
            self.assert_refused(build_bundle, *inputs)
        inputs = records()
        inputs[0] = b" " * (MAX_JSON + 1)
        self.assert_refused(build_bundle, *inputs, code="BUNDLE_LIMIT")

    def test_patch_boundary_and_unicode_bytes_roundtrip(self):
        inputs = records()
        inputs[4] = ("+" + "界" * ((MAX_PATCH - 1) // 3)).encode()
        change_record(inputs, 1, lambda value: value.update(patch_sha256=sha(inputs[4])))
        change_record(inputs, 2, lambda value: value.update(patch_sha256=sha(inputs[4])))
        raw = build_bundle(*inputs)
        self.assertEqual(contents(raw)["changes.diff"], inputs[4])
        self.assertLessEqual(len(raw), MAX_ARCHIVE)
        self.assertEqual(verify_bundle(raw)["hashes"]["patch_sha256"], sha(inputs[4]))

    def test_exact_raw_task_record_limit_is_preserved_without_copying_raw_record(self):
        inputs = records()
        inputs[0] += b" " * (MAX_JSON - len(inputs[0]))
        value = verify_bundle(build_bundle(*inputs))
        self.assertEqual(value["hashes"]["task_sha256"], sha(inputs[0]))
        self.assertLess(value["archive_bytes"], 10000)

    def test_external_pin_is_optional_but_exact_when_given(self):
        raw = build_bundle(*records())
        self.assertEqual(verify_bundle(raw), verify_bundle(raw, sha(raw)))
        self.assert_refused(verify_bundle, raw, "f" * 64, code="BUNDLE_CHANGED")
        for pin in (True, "F" * 64, "bad", 1):
            self.assert_refused(verify_bundle, raw, pin, code="BUNDLE_HASH_REQUIRED")

    def test_trailing_prefix_truncated_and_oversized_archives_refuse(self):
        raw = build_bundle(*records())
        for altered in (raw + b"private trailing", b"prefix" + raw, raw[:-1], b"", b"PK\x03\x04", bytearray(raw)):
            self.assert_refused(verify_bundle, altered)
        self.assert_refused(verify_bundle, b"x" * (MAX_ARCHIVE + 1), code="BUNDLE_LIMIT")

    def test_eocd_member_bombs_are_rejected_before_zip_metadata_allocation(self):
        raw = bytearray(build_bundle(*records()))
        struct.pack_into("<H", raw, len(raw) - 12, 65535)
        with patch("zipfile.ZipFile", side_effect=AssertionError("metadata allocation")):
            self.assert_refused(verify_bundle, bytes(raw))

    def test_compressed_encrypted_extra_commented_and_reordered_archives_refuse(self):
        raw = build_bundle(*records())
        candidates = [rewrite(raw, compression=zipfile.ZIP_DEFLATED), rewrite(raw, comment=b"private comment"),
            rewrite(raw, order=tuple(reversed(MEMBERS))), rewrite(raw, info_change=lambda info: setattr(info, "extra", b"\x01\x00\x00\x00")),
            rewrite(raw, info_change=lambda info: setattr(info, "comment", b"private")),
            rewrite(raw, info_change=lambda info: setattr(info, "date_time", (2026, 1, 1, 0, 0, 0)))]
        encrypted = bytearray(raw)
        struct.pack_into("<H", encrypted, 6, 1)
        candidates.append(bytes(encrypted))
        for altered in candidates:
            self.assert_refused(verify_bundle, altered)

    def test_extra_duplicate_traversal_directory_and_link_entries_refuse(self):
        raw = build_bundle(*records())
        for name in ("extra.txt", "changes.diff", "../escape", "/absolute", "nested/file", "directory/"):
            self.assert_refused(verify_bundle, rewrite(raw, extra=(name, b"invented")))
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFDIR | 0o700, stat.S_IFREG | 0o644):
            self.assert_refused(verify_bundle, rewrite(raw, info_change=lambda info: setattr(info, "external_attr", mode << 16)))

    def test_zip64_is_rejected_even_for_small_stored_members(self):
        raw = build_bundle(*records())
        target = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as original, \
                zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for name in MEMBERS:
                info = copy.copy(original.getinfo(name))
                with archive.open(info, "w", force_zip64=True) as destination:
                    destination.write(original.read(name))
        self.assert_refused(verify_bundle, target.getvalue())

    def test_crc_and_checksum_tampering_are_detected(self):
        raw = build_bundle(*records())
        corrupted = bytearray(raw)
        start = raw.index(b"--- a/module.py")
        corrupted[start] ^= 1
        self.assert_refused(verify_bundle, bytes(corrupted))
        self.assert_refused(verify_bundle, rewrite(raw, {"changes.diff": b"changed patch\n"}, checksum=False))
        self.assert_refused(verify_bundle, rewrite(raw, {"SHA256SUMS": b""}, checksum=False))
        self.assert_refused(verify_bundle, rewrite(raw, {"README.txt": b"execute private commands\n"}))

    def test_declared_oversize_and_overlapping_local_offsets_refuse(self):
        raw = build_bundle(*records())
        end = struct.unpack_from("<4s4H2IH", raw, len(raw) - 22)
        central = end[6]
        altered = bytearray(raw)
        struct.pack_into("<I", altered, central + 24, MAX_JSON + 1)
        struct.pack_into("<I", altered, central + 20, MAX_JSON + 1)
        self.assert_refused(verify_bundle, bytes(altered), code="BUNDLE_LIMIT")
        second = central + 46 + len(MEMBERS[0])
        altered = bytearray(raw)
        struct.pack_into("<I", altered, second + 42, 0)
        self.assert_refused(verify_bundle, bytes(altered))

    def test_archive_json_is_strict_canonical_and_exact_schema(self):
        raw = build_bundle(*records())
        data = contents(raw)
        for payload in (b'{"format":1,"format":2}', b'{"format":NaN}',
                        json.dumps(json.loads(data["manifest.json"]), indent=2).encode()):
            self.assert_refused(verify_bundle, rewrite(raw, {"manifest.json": payload}))
        manifest = json.loads(data["manifest.json"])
        manifest["private"] = PRIVATE
        self.assert_refused(verify_bundle, rewrite(raw, {"manifest.json": canonical(manifest)}))

    def test_manifest_scope_hash_budget_and_protection_tampering_refuse(self):
        raw = build_bundle(*records())
        for change in (lambda value: value["files"][0].update(path="../escape.py"),
            lambda value: value["files"][1].update(after_sha256="f" * 64),
            lambda value: value["task_profile"].update(max_turns=True),
            lambda value: value["hashes"].update(patch_sha256="f" * 64),
            lambda value: value["files"][0].update(editable=1)):
            manifest = json.loads(contents(raw)["manifest.json"])
            change(manifest)
            self.assert_refused(verify_bundle, rewrite(raw, {"manifest.json": canonical(manifest)}))

    def test_review_and_check_summary_hash_and_pass_claim_tampering_refuse(self):
        raw = build_bundle(*records(java=True))
        for name, change in (("review.json", lambda value: value.update(verdict="rejected")),
            ("review.json", lambda value: value["hashes"].update(result_sha256="f" * 64)),
            ("checks.json", lambda value: value["checks"][0].update(tests_ran=True)),
            ("checks.json", lambda value: value["checks"][0].update(output_limited=True)),
            ("checks.json", lambda value: value["checks"][0].update(output=PRIVATE)),
            ("checks.json", lambda value: value.update(not_checked=[])),
            ("checks.json", lambda value: value["checks"][0]["spec"]["sources"].append("unselected.java"))):
            value = json.loads(contents(raw)[name])
            change(value)
            self.assert_refused(verify_bundle, rewrite(raw, {name: canonical(value)}))

    def test_build_verify_no_filesystem_extraction_execution_network_or_process(self):
        inputs = records()
        before = tuple(inputs)
        with patch("builtins.open", side_effect=AssertionError("filesystem")), \
                patch("os.open", side_effect=AssertionError("filesystem")), \
                patch("zipfile.ZipFile.extract", side_effect=AssertionError("extraction")), \
                patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extraction")), \
                patch("subprocess.Popen", side_effect=AssertionError("process")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("builtins.exec", side_effect=AssertionError("execution")), \
                patch("builtins.eval", side_effect=AssertionError("evaluation")):
            raw = build_bundle(*inputs)
            self.assertEqual(verify_bundle(raw)["member_count"], 6)
        self.assertEqual(tuple(inputs), before)

    def test_summary_nested_mutation_does_not_change_archive_or_future_summary(self):
        raw = build_bundle(*records(java=True))
        before = bytes(raw)
        value = verify_bundle(raw)
        value["checks"][0]["spec"]["sources"].append("private.java")
        value["files"][0]["path"] = "changed"
        self.assertEqual(raw, before)
        self.assertNotIn("private.java", canonical(verify_bundle(raw)).decode())


class CliTests(unittest.TestCase):
    def call(self, args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_read_only_success_external_pin_and_no_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.zip"
            raw = build_bundle(*records())
            path.write_bytes(raw)
            before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
            with patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extract")), \
                    patch("zipfile.ZipFile.extract", side_effect=AssertionError("extract")):
                code, value = self.call([str(path), "--expect-sha256", sha(raw)])
            self.assertEqual(code, 0)
            self.assertEqual(value, verify_bundle(raw))
            self.assertEqual(before, {p.name: p.read_bytes() for p in path.parent.iterdir()})
            code, value = self.call([str(path), "--expect-sha256", "f" * 64])
            self.assertEqual((code, value), (2, {"error": "BUNDLE_CHANGED"}))

    def test_cli_refuses_symlink_hardlink_parent_link_fifo_directory_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "private.zip"
            original.write_bytes(build_bundle(*records()))
            link = root / "link.zip"
            link.symlink_to(original)
            hard = root / "hard.zip"
            hard.hardlink_to(original)
            fifo = root / "fifo.zip"
            os.mkfifo(fifo)
            nested = root / "nested"
            nested.mkdir()
            (nested / "private.zip").write_bytes(original.read_bytes())
            alias = root / "alias"
            alias.symlink_to(nested, target_is_directory=True)
            large = root / "large.zip"
            with large.open("wb") as stream:
                stream.truncate(MAX_ARCHIVE + 1)
            for path in (link, hard, original, fifo, root, alias / "private.zip", large):
                with self.subTest(kind=path.name):
                    code, value = self.call([str(path)])
                    self.assertEqual(code, 2)
                    self.assertEqual(set(value), {"error"})
                    self.assertNotIn(str(root), json.dumps(value))

    def test_cli_bad_arguments_missing_corrupt_file_and_private_errors_are_fixed(self):
        for args in ([], ["relative.zip"], ["/private/nonexistent-" + PRIVATE],
                     ["/private/nonexistent", "--wrong", PRIVATE],
                     ["/private/nonexistent", "--expect-sha256", PRIVATE]):
            code, value = self.call(args)
            self.assertEqual(code, 2)
            self.assertRegex(value["error"], r"^BUNDLE_[A-Z_]+$")
            self.assertNotIn(PRIVATE, json.dumps(value))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.zip"
            path.write_bytes(b"private garbage " + PRIVATE.encode())
            code, value = self.call([str(path)])
            self.assertEqual(code, 2)
            self.assertNotIn(PRIVATE, json.dumps(value))


if __name__ == "__main__":
    unittest.main()
