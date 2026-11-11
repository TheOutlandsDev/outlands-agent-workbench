"""Read-only index/metadata inspection and rechecks of invented private snapshots."""

import copy
import hashlib
import io
import json
import os
import struct
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha
from bundle_workspace import build as create_workspace, prepare
from test_bundle_workspace import fixture as creation_fixture, passed, stage as creation_stage, tree
from workspace_recheck import FORMAT, build, history_pin, inspect, main


PRIVATE = "invented private recheck output and source, never a provider claim"


@contextmanager
def fixture(*, java=False):
    with creation_fixture(java=java) as (root, source, task, task_raw, archive, before, after):
        job, request, initial = creation_stage(root, source, task_raw, archive)
        data = root / "data"
        data.mkdir(mode=0o700)
        jobs = data / "bundle-workspaces"
        jobs.mkdir(mode=0o700)
        moved = jobs / job.name
        job.rename(moved)
        job = moved
        config = {"format": "outlands-workbench-config-v1", "models": [], "projects": [{
            "id": request["project_id"], "name": "Invented project", "source": str(source), "task": request["task_path"]}]}
        config_raw = canonical(config)
        Path(request["config_path"]).write_bytes(config_raw)
        request["config_sha256"] = sha(config_raw)
        summary = prepare(archive, source, task_raw)["summary"]
        request["preview_sha256"] = sha(canonical({"version": 1, "project_id": request["project_id"],
            "bundle_sha256": request["bundle_sha256"], "task_sha256": request["task_sha256"],
            "config_sha256": request["config_sha256"], "prepared": summary}))
        initial.update(config_sha256=request["config_sha256"], preview_sha256=request["preview_sha256"])
        (job / "request.json").write_bytes(canonical(request))
        (job / "receipt.json").write_bytes(canonical(initial))
        create_workspace(job, Path("/invented/not-executed-jdk") if java else None, passed)
        history = data / "workspace-rechecks"
        history.mkdir(mode=0o700)
        yield root, data, job, source, task, before, after


def initial_receipt(identifier, workspace="a" * 16):
    return {"format": FORMAT, "version": 1, "id": identifier, "workspace_id": workspace,
        "status": "PREPARING", "created": 1, "source_applied": False, "workspace_modified": False,
        "creation_sha256": "c" * 64, "preview_sha256": "d" * 64, "history_sha256": "e" * 64}


def stage(data, job, identifier="b" * 16):
    summary = inspect(job)["summary"]
    history_sha = history_pin(data / "workspace-rechecks")
    request = {"version": 1, "id": identifier, "workspace_id": job.name, "job_dir": str(job),
        "preview_sha256": sha(canonical({"inspection": summary, "history_sha256": history_sha})),
        "creation_sha256": summary["creation_sha256"], "history_sha256": history_sha}
    attempt = data / "workspace-rechecks" / identifier
    attempt.mkdir(mode=0o700)
    receipt = initial_receipt(identifier, job.name)
    receipt.update({key: request[key] for key in ("creation_sha256", "preview_sha256", "history_sha256")})
    (attempt / "request.json").write_bytes(canonical(request))
    (attempt / "receipt.json").write_bytes(canonical(receipt))
    return attempt, request, receipt


def edit_index(path, change):
    body = bytearray(path.read_bytes()[:-20])
    change(body)
    path.write_bytes(bytes(body) + hashlib.sha1(body).digest())


def replace_extension(path, name, payload):
    raw = path.read_bytes()
    count = struct.unpack_from(">I", raw, 8)[0]
    cursor = 12
    for _ in range(count):
        end = raw.index(b"\x00", cursor + 62)
        cursor += ((end - cursor + 1 + 7) // 8) * 8
    output, found = raw[:cursor], False
    while cursor < len(raw) - 20:
        signature, length = raw[cursor:cursor + 4], struct.unpack_from(">I", raw, cursor + 4)[0]
        value = payload if signature == name else raw[cursor + 8:cursor + 8 + length]
        output += signature + struct.pack(">I", len(value)) + value
        found = found or signature == name
        cursor += 8 + length
    if not found:output += name + struct.pack(">I", len(payload)) + payload
    path.write_bytes(output + hashlib.sha1(output).digest())


def fsmonitor_payload(*, bits=2, words=None, rlw=0, token=b"opaque-token"):
    words = [1 << 33, 3] if words is None else words
    bitmap = struct.pack(">II", bits, len(words)) + b"".join(struct.pack(">Q", value) for value in words) + struct.pack(">I", rlw)
    return struct.pack(">I", 2) + token + b"\x00" + struct.pack(">I", len(bitmap)) + bitmap


class RecheckTests(unittest.TestCase):
    def assert_refused(self, operation, *args, code=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            operation(*args, **kwargs)
        self.assertRegex(str(caught.exception), r"^RECHECK_[A-Z_]+$")
        self.assertNotIn(PRIVATE, str(caught.exception))
        if code:
            self.assertEqual(caught.exception.args, (code,))

    def test_python_java_inspection_allows_only_editable_manual_changes(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (root, _, job, _, task, _, after):
                receipt_before = (job / "receipt.json").read_bytes()
                before = tree(root)
                report = inspect(job)
                self.assertEqual(set(report), {"summary", "task", "selected_bytes"})
                self.assertEqual(report["selected_bytes"], after)
                summary = report["summary"]
                self.assertEqual(summary["changed_files"], 0)
                self.assertTrue(all(not row["changed"] for row in summary["files"]))
                self.assertEqual(summary["creation_sha256"], sha(receipt_before))
                self.assertEqual(summary["workspace_id"], job.name)
                self.assertNotIn(str(root), canonical(summary).decode())
                self.assertNotIn(PRIVATE, canonical(summary).decode())
                self.assertLessEqual(len(canonical(summary)), 65536)
                self.assertEqual(tree(root), before)
                editable = task["editable"][0]
                modified = after[editable] + "\n# invented é😀 owner edit\n".encode()
                (job / "workspace/review" / editable).write_bytes(modified)
                updated = inspect(job)
                self.assertEqual(updated["selected_bytes"][editable], modified)
                self.assertEqual(updated["summary"]["changed_files"], 1)
                self.assertNotEqual(updated["summary"]["snapshot_sha256"], summary["snapshot_sha256"])
                self.assertEqual((job / "receipt.json").read_bytes(), receipt_before)

    def test_inspection_has_no_subprocess_git_network_execution_or_writes(self):
        with fixture() as (root, _, job, _, _, _, _):
            before, real_open = tree(root), os.open
            def readonly(name, flags, *args, **kwargs):
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                return real_open(name, flags, *args, **kwargs)
            with patch("os.open", side_effect=readonly), patch("subprocess.run", side_effect=AssertionError("Git/process")), \
                    patch("subprocess.Popen", side_effect=AssertionError("process")), patch("socket.socket", side_effect=AssertionError("network")), \
                    patch("builtins.exec", side_effect=AssertionError("execution")), patch("builtins.eval", side_effect=AssertionError("evaluation")), \
                    patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extraction")):
                self.assertEqual(inspect(job)["summary"]["changed_files"], 0)
            self.assertEqual(tree(root), before)

    def test_protected_source_task_config_and_creation_pins_refuse_drift(self):
        for kind in ("protected", "source", "task", "config", "creation"):
            with self.subTest(kind=kind), fixture() as (_, _, job, source, task, _, _):
                pin = sha((job / "receipt.json").read_bytes())
                request = json.loads((job / "request.json").read_bytes())
                if kind == "protected":
                    name = next(name for name in task["files"] if name not in task["editable"])
                    (job / "workspace/review" / name).write_text("changed protected\n")
                elif kind == "source":(source / "value.py").write_text("changed original\n")
                elif kind == "task":Path(request["task_path"]).write_bytes((job / "task.json").read_bytes() + b" ")
                elif kind == "config":Path(request["config_path"]).write_text("changed config\n")
                else:(job / "receipt.json").write_bytes((job / "receipt.json").read_bytes() + b" ")
                self.assert_refused(inspect, job, pin)

    def test_creation_must_be_verified_and_maps_and_original_checks_must_match(self):
        changes = [lambda value: value.update(status="FAILED"), lambda value: value["candidate"].update(value_py="f" * 64),
                   lambda value: value["checks"]["unit"].update(exit_code=True), lambda value: value.update(branch="other")]
        for change in changes:
            with fixture() as (_, _, job, _, _, _, _):
                receipt = json.loads((job / "receipt.json").read_bytes());change(receipt)
                (job / "receipt.json").write_bytes(canonical(receipt))
                self.assert_refused(inspect, job)

    def test_relative_git_pointers_are_bound_lexically_inside_expected_repository(self):
        with fixture() as (_, _, job, _, _, _, _):
            old = inspect(job)["summary"]
            work = job / "workspace/review"
            admin = job / "workspace/baseline-repo/.git/worktrees/review"
            (work / ".git").write_bytes(b"gitdir: ../baseline-repo/.git/worktrees/review\n")
            (admin / "gitdir").write_bytes(b"../../../../review/.git\n")
            new = inspect(job)["summary"]
            self.assertNotEqual(old["snapshot_sha256"], new["snapshot_sha256"])
            self.assertEqual(old["creation_sha256"], new["creation_sha256"])

    def test_pointer_commondir_backlink_head_ref_and_include_config_attacks_refuse(self):
        cases = [("workspace/review/.git", b"gitdir: /private/outside\n"),
            ("workspace/review/.git", b"gitdir: ../../../../outside\n"),
            ("workspace/baseline-repo/.git/worktrees/review/commondir", b"../../../../outside\n"),
            ("workspace/baseline-repo/.git/worktrees/review/gitdir", b"/private/outside/.git\n"),
            ("workspace/baseline-repo/.git/worktrees/review/HEAD", b"ref: refs/heads/other\n"),
            ("workspace/baseline-repo/.git/HEAD", b"ref: refs/heads/other\n"),
            ("workspace/baseline-repo/.git/refs/heads/baseline", b"f" * 40 + b"\n"),
            ("workspace/baseline-repo/.git/config", b"[core]\n\tbare = false\n[include]\n\tpath = /private/outside\n")]
        for path, raw in cases:
            with self.subTest(path=path), fixture() as (_, _, job, _, _, _, _):
                (job / path).write_bytes(raw)
                with patch("subprocess.run", side_effect=AssertionError("Git")):
                    self.assert_refused(inspect, job, code="RECHECK_GIT_CHANGED")

    def test_git_metadata_symlinks_and_hardlinks_are_not_followed(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), fixture() as (root, _, job, _, _, _, _):
                path = job / "workspace/baseline-repo/.git/worktrees/review/HEAD"
                if kind == "symlink":
                    path.unlink();outside = root / "outside";outside.write_text(PRIVATE);path.symlink_to(outside)
                else:(root / "hard").hardlink_to(path)
                self.assert_refused(inspect, job)

    def test_index_checksum_version_count_flags_mode_blob_and_unknown_extension_refuse(self):
        changes = [lambda raw: struct.pack_into(">I", raw, 4, 3), lambda raw: struct.pack_into(">I", raw, 8, 33),
            lambda raw: struct.pack_into(">H", raw, 12 + 60, 0x8000 | 13),
            lambda raw: struct.pack_into(">H", raw, 12 + 60, 0x4000 | 13),
            lambda raw: struct.pack_into(">H", raw, 12 + 60, 0x1000 | 13),
            lambda raw: struct.pack_into(">I", raw, 12 + 24, 0o100755),
            lambda raw: raw.__setitem__(slice(12 + 40, 12 + 60), b"f" * 20),
            lambda raw: raw.extend(b"EOIE" + struct.pack(">I", 0))]
        for index, change in enumerate(changes):
            with self.subTest(index=index), fixture() as (_, _, job, _, _, _, _):
                path = job / "workspace/baseline-repo/.git/worktrees/review/index"
                edit_index(path, change)
                self.assert_refused(inspect, job, code="RECHECK_INDEX_INVALID")
        with fixture() as (_, _, job, _, _, _, _):
            path = job / "workspace/baseline-repo/.git/worktrees/review/index"
            raw = bytearray(path.read_bytes());raw[-1] ^= 1;path.write_bytes(raw)
            self.assert_refused(inspect, job, code="RECHECK_INDEX_INVALID")

    def test_invalidated_tree_cache_has_no_authority_over_baseline_entries(self):
        with fixture() as (_, _, job, _, _, _, _):
            path = job / "workspace/baseline-repo/.git/worktrees/review/index"
            replace_extension(path, b"TREE", b"\x00-1 0\n")
            self.assertEqual(inspect(job)["summary"]["changed_files"], 0)
            replace_extension(path, b"TREE", b"\x00-2 0\n")
            self.assert_refused(inspect, job, code="RECHECK_INDEX_INVALID")

    def test_fsmonitor_cache_is_parsed_but_never_skips_current_file_reads(self):
        with fixture() as (_, _, job, _, _, _, _):
            path = job / "workspace/baseline-repo/.git/worktrees/review/index"
            replace_extension(path, b"FSMN", fsmonitor_payload(bits=0, words=[0], token=PRIVATE.encode()))
            (job / "workspace/review/value.py").write_text("# actual changed owner bytes\n")
            with patch("subprocess.run", side_effect=AssertionError("monitor/Git hook execution")):
                summary = inspect(job)["summary"]
            self.assertEqual(summary["changed_files"], 1)
            self.assertNotIn(PRIVATE, canonical(summary).decode())

    def test_malformed_fsmonitor_versions_tokens_lengths_and_ewah_refuse(self):
        variants = [struct.pack(">I", 1) + fsmonitor_payload()[4:],
                    struct.pack(">I", 2) + b"x" * 1025,
                    fsmonitor_payload(bits=3), fsmonitor_payload(words=[]),
                    fsmonitor_payload(words=[0xffffffff << 1]),
                    fsmonitor_payload(words=[2 << 33, 3]), fsmonitor_payload(rlw=1),
                    fsmonitor_payload(words=[1 << 33, 1 << 60])]
        for index, value in enumerate(variants):
            with self.subTest(index=index), fixture() as (_, _, job, _, _, _, _):
                path = job / "workspace/baseline-repo/.git/worktrees/review/index"
                replace_extension(path, b"FSMN", value)
                self.assert_refused(inspect, job, code="RECHECK_INDEX_INVALID")

    def test_missing_or_corrupt_loose_commit_object_is_not_a_verified_repository(self):
        for missing in (False, True):
            with fixture() as (_, _, job, _, _, _, _):
                receipt = json.loads((job / "receipt.json").read_bytes())
                oid = receipt["baseline_commit"]
                path = job / "workspace/baseline-repo/.git/objects" / oid[:2] / oid[2:]
                if missing:path.unlink()
                else:path.chmod(0o600);path.write_bytes(b"invalid compressed object")
                self.assert_refused(inspect, job)

    def test_unknown_inventory_unsafe_source_encoding_mode_and_limits_refuse(self):
        for kind in ("extra", "emptydir", "binary", "utf8", "limit", "executable", "link"):
            with self.subTest(kind=kind), fixture() as (root, _, job, _, _, _, _):
                work = job / "workspace/review";path = work / "value.py"
                if kind == "extra":(work / "unselected.txt").write_text(PRIVATE)
                elif kind == "emptydir":(work / "unselected").mkdir()
                elif kind == "binary":path.write_bytes(b"x\x00y")
                elif kind == "utf8":path.write_bytes(b"\xff")
                elif kind == "limit":path.write_bytes(b"x" * 32769)
                elif kind == "executable":path.chmod(0o755)
                else:path.unlink();outside = root / "outside";outside.write_text(PRIVATE);path.symlink_to(outside)
                self.assert_refused(inspect, job)

    def test_history_hash_is_sorted_and_accepts_parent_start_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory)
            rows = []
            for identifier in ("b" * 16, "a" * 16):
                folder = history / identifier;folder.mkdir(mode=0o700)
                receipt = initial_receipt(identifier)
                if identifier.startswith("b"):
                    receipt.update(status="FAILED", finished=2, reason="RECHECK_START_FAILED")
                raw = canonical(receipt);(folder / "receipt.json").write_bytes(raw)
                rows.append({"id": identifier, "receipt_sha256": sha(raw)})
            self.assertEqual(history_pin(history), sha(canonical(sorted(rows, key=lambda row: row["id"]))))
            self.assertEqual(history_pin(history, "a" * 16), sha(canonical([rows[0]])))

    def test_history_unknown_entries_unsafe_records_and_budgets_refuse(self):
        for kind in ("unknown", "symlink", "badstatus", "hardlink", "oversize", "aggregate", "count"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                history = Path(directory)
                if kind == "unknown":(history / "private-unknown").write_text(PRIVATE)
                elif kind == "symlink":(history / ("a" * 16)).symlink_to(history, target_is_directory=True)
                else:
                    count = 9 if kind == "aggregate" else 201 if kind == "count" else 1
                    for number in range(count):
                        identifier = "%016x" % number;folder = history / identifier;folder.mkdir(mode=0o700)
                        receipt = initial_receipt(identifier)
                        if kind == "badstatus":receipt["status"] = PRIVATE
                        if kind == "aggregate":receipt["padding"] = "x" * 250000
                        path = folder / "receipt.json";path.write_bytes(canonical(receipt))
                        if kind == "oversize":path.write_bytes(b" " * 262145)
                        if kind == "hardlink":(history.parent / (history.name + "-hard")).hardlink_to(path)
                self.assert_refused(history_pin, history)
                if kind == "hardlink":(history.parent / (history.name + "-hard")).unlink()

    def test_snapshot_worker_checks_edited_copy_and_never_rewrites_creation(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (_, data, job, _, task, _, _):
                work = job / "workspace/review";editable = task["editable"][0]
                edited = (work / editable).read_bytes() + b"\n// owner edit\n" if java else (work / editable).read_bytes() + b"\n# owner edit\n"
                (work / editable).write_bytes(edited)
                attempt, _, initial = stage(data, job)
                original_creation, original_job = (job / "receipt.json").read_bytes(), tree(job)
                calls = []
                def checker(snapshot, supplied, jdk):
                    calls.append(snapshot)
                    self.assertNotEqual(snapshot, work)
                    self.assertFalse((snapshot / ".git").exists())
                    self.assertEqual((snapshot / editable).read_bytes(), edited)
                    self.assertEqual(supplied["checks"], task["checks"])
                    return passed(snapshot, supplied, jdk)
                with patch("subprocess.run", side_effect=AssertionError("Git/process from recheck")), patch("socket.socket", side_effect=AssertionError("network")):
                    receipt = build(attempt, Path("/invented/not-executed-jdk") if java else None, checker)
                self.assertEqual(receipt["status"], "VERIFIED")
                self.assertFalse(receipt["source_applied"])
                self.assertFalse(receipt["workspace_modified"])
                self.assertEqual(len(calls), 1)
                self.assertEqual((job / "receipt.json").read_bytes(), original_creation)
                self.assertEqual(tree(job), original_job)
                self.assertEqual(json.loads((attempt / "initial-receipt.json").read_bytes()), initial)
                self.assertEqual(receipt["checked_files"][editable], sha(edited))
                self.assertEqual(history_pin(attempt.parent), sha(canonical([{"id": attempt.name, "receipt_sha256": sha((attempt / "receipt.json").read_bytes())}])))

    def test_preview_or_creation_drift_refuses_before_checks_with_initial_pins_retained(self):
        for kind in ("editable", "creation", "history"):
            with self.subTest(kind=kind), fixture() as (_, data, job, _, _, _, _):
                attempt, request, initial = stage(data, job)
                if kind == "editable":(job / "workspace/review/value.py").write_text("changed after preview\n")
                elif kind == "creation":(job / "receipt.json").write_bytes((job / "receipt.json").read_bytes() + b" ")
                else:
                    identifier = "c" * 16;folder = attempt.parent / identifier;folder.mkdir(mode=0o700)
                    (folder / "receipt.json").write_bytes(canonical(initial_receipt(identifier)))
                with patch("workspace_recheck.fixed_checks", side_effect=AssertionError("checks")):
                    self.assert_refused(build, attempt, checker=lambda *_: self.fail("checker reached"), code="RECHECK_STALE")
                receipt = json.loads((attempt / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED")
                for key in ("id", "workspace_id", "creation_sha256", "preview_sha256", "history_sha256"):
                    self.assertEqual(receipt[key], initial[key])

    def test_post_check_owner_snapshot_source_and_history_changes_fail_stale_with_results(self):
        for kind in ("owner", "snapshot", "source", "history"):
            with self.subTest(kind=kind), fixture() as (_, data, job, source, _, _, _):
                attempt, _, _ = stage(data, job)
                creation_before = (job / "receipt.json").read_bytes()
                def changed(snapshot, task, jdk):
                    if kind == "owner":(job / "workspace/review/value.py").write_text("owner changed during checks\n")
                    elif kind == "snapshot":(snapshot / "value.py").write_text("copy changed\n")
                    elif kind == "source":(source / "value.py").write_text("original changed\n")
                    else:
                        identifier = "c" * 16;folder = attempt.parent / identifier;folder.mkdir(mode=0o700)
                        (folder / "receipt.json").write_bytes(canonical(initial_receipt(identifier)))
                    return passed(snapshot, task, jdk)
                self.assert_refused(build, attempt, checker=changed, code="RECHECK_STALE")
                receipt = json.loads((attempt / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "FAILED")
                self.assertEqual(receipt["checks"]["unit"]["exit_code"], 0)
                self.assertTrue((attempt / "checks.json").is_file())
                self.assertEqual((job / "receipt.json").read_bytes(), creation_before)

    def test_failed_and_interrupted_attempts_retain_outputs_and_do_not_retry(self):
        for outcome in ("failed", "interrupt", "exception"):
            with self.subTest(outcome=outcome), fixture() as (_, data, job, _, _, _, _):
                attempt, _, _ = stage(data, job)
                def checker(snapshot, task, jdk):
                    if outcome == "interrupt":raise KeyboardInterrupt
                    if outcome == "exception":raise RuntimeError(PRIVATE)
                    results = passed(snapshot, task, jdk);results["unit"].update(exit_code=1, output=PRIVATE)
                    return results
                self.assert_refused(build, attempt, checker=checker)
                receipt = json.loads((attempt / "receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "INTERRUPTED" if outcome == "interrupt" else "FAILED")
                self.assertNotIn(PRIVATE, receipt["reason"])
                if outcome == "failed":self.assertEqual(json.loads((attempt / "checks.json").read_bytes())["unit"]["output"], PRIVATE)
                before = tree(attempt)
                self.assert_refused(build, attempt, checker=lambda *_: self.fail("retry"))
                self.assertEqual(tree(attempt), before)

    def test_output_display_clipping_and_boolean_failure_preserve_execution_facts(self):
        for invalid in (False, True):
            with fixture() as (_, data, job, _, _, _, _):
                attempt, _, _ = stage(data, job)
                output = "😀" * 10000
                def checker(snapshot, task, jdk):
                    results = passed(snapshot, task, jdk);results["unit"]["output"] = output
                    if invalid:results["unit"]["tests_ran"] = True
                    return results
                if invalid:self.assert_refused(build, attempt, checker=checker, code="RECHECK_CHECKS_FAILED")
                else:self.assertEqual(build(attempt, checker=checker)["status"], "VERIFIED")
                receipt = json.loads((attempt / "receipt.json").read_bytes())
                self.assertTrue(receipt["checks"]["unit"]["display_truncated"])
                self.assertFalse(receipt["checks"]["unit"]["output_limited"])
                self.assertEqual(json.loads((attempt / "checks.json").read_bytes())["unit"]["output"], output)
                self.assertLessEqual(len((attempt / "receipt.json").read_bytes()), 262144)

    def test_cli_refuses_private_bad_paths_without_raw_exception_or_path(self):
        output = io.StringIO()
        with redirect_stdout(output):code = main(["--attempt-dir", "/missing/" + PRIVATE])
        self.assertNotEqual(code, 0)
        self.assertNotIn(PRIVATE, output.getvalue())
        self.assertRegex(json.loads(output.getvalue())["error"], r"^RECHECK_[A-Z_]+$")


if __name__ == "__main__":
    unittest.main()
