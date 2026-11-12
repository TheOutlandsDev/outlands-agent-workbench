"""Synthetic snapshot rechecks: no Git/process/provider execution in these tests."""

import copy
import hashlib
import io
import json
import os
import signal
import struct
import unittest
import zlib
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha
from bundle_workspace import _check_results
from snapshot_workspace import FORMAT as CREATION_FORMAT, prepare
from test_snapshot_project_check import fixture as project_fixture
from workspace_recheck import _objects
import snapshot_recheck as recheck


PRIVATE = "invented private snapshot recheck source goal output exception"


def passed(work, task, jdk):
    del work, jdk
    return {name: {"exit_code": 0, "tests_ran": 2, "timed_out": False, "output_limited": False,
                   "infrastructure_error": False, "output": PRIVATE} for name in task["checks"]}


def tree(root):
    return {str(path.relative_to(root)): sha(path.read_bytes()) for path in root.rglob("*") if path.is_file()}


def install(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw)


def git_fixture(job, baseline, selected):
    """Construct minimal loose objects and index in Python, without invoking Git."""
    work, common = job / "workspace/review", job / "workspace/baseline-repo/.git"
    admin = common / "worktrees/review"
    branch = "outlands/snapshot-" + job.name
    blobs, trees = _objects(baseline)
    body = (b"tree " + trees[""]["oid"].hex().encode() + b"\nauthor Invented <fixture@example.invalid> 1 +0000\n"
            b"committer Invented <fixture@example.invalid> 1 +0000\n\nInvented baseline\n")
    commit_raw = b"commit " + str(len(body)).encode() + b"\x00" + body
    commit = hashlib.sha1(commit_raw).hexdigest()
    objects = [commit_raw] + [row["raw"] for row in trees.values()] + [
        b"blob " + str(len(raw)).encode() + b"\x00" + raw for raw in baseline.values()]
    for raw in objects:
        oid = hashlib.sha1(raw).hexdigest()
        install(common / "objects" / oid[:2] / oid[2:], zlib.compress(raw))
    index = b"DIRC" + struct.pack(">II", 2, len(baseline))
    for name in sorted(baseline):
        entry = struct.pack(">10I", 0, 0, 0, 0, 0, 0, 0o100644, 0, 0, len(baseline[name]))
        entry += blobs[name] + struct.pack(">H", len(name)) + name.encode() + b"\x00"
        index += entry + b"\x00" * ((-len(entry)) % 8)
    controls = {
        work / ".git": ("gitdir: " + str(admin) + "\n").encode(),
        common / "HEAD": b"ref: refs/heads/baseline\n",
        common / "config": b"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = true\n",
        common / "refs/heads/baseline": (commit + "\n").encode(),
        common / "refs/heads" / branch: (commit + "\n").encode(),
        admin / "HEAD": ("ref: refs/heads/" + branch + "\n").encode(),
        admin / "commondir": b"../..\n",
        admin / "gitdir": (str(work / ".git") + "\n").encode(),
        admin / "index": index + hashlib.sha1(index).digest(),
    }
    for path, raw in controls.items():
        install(path, raw)
    for name, raw in selected.items():
        install(work / name, raw)
    return branch, commit


@contextmanager
def fixture(**kwargs):
    with project_fixture(**kwargs) as (root, source, task, archive, before, after, task_path, _):
        data = root / "data"
        job = data / "snapshot-workspaces" / ("a" * 16)
        job.mkdir(mode=0o700, parents=True)
        history = data / "snapshot-workspace-rechecks"
        history.mkdir(mode=0o700)
        config_path = root / "config.json"
        config_raw = canonical({"format": "outlands-workbench-config-v1", "models": [], "projects": [
            {"id": "invented", "name": "Invented project", "source": str(source), "task": str(task_path)}]})
        config_path.write_bytes(config_raw)
        task_raw = canonical(task)
        prepared = prepare(archive, source, task_raw)["summary"]
        request = {"version": 1, "id": job.name, "project_id": "invented", "source": str(source),
            "config_path": str(config_path), "config_sha256": sha(config_raw), "task_path": str(task_path),
            "task_sha256": sha(task_raw), "archive_sha256": sha(archive)}
        request["preview_sha256"] = sha(canonical({"version": 1, "project_id": request["project_id"],
            "archive_sha256": request["archive_sha256"], "task_sha256": request["task_sha256"],
            "config_sha256": request["config_sha256"], "prepared": prepared}))
        initial = {"version": 1, "format": CREATION_FORMAT, "status": "PREPARING", "created": 1,
            "source_applied": False, "patch_sha256": prepared["patch_sha256"], **{key: request[key] for key in
                ("id", "project_id", "config_sha256", "task_sha256", "archive_sha256", "preview_sha256")}}
        branch, commit = git_fixture(job, before, after)
        full, display, _ = _check_results(passed(None, task, None), task)
        checks_raw = canonical(full)
        receipt = {**initial, "status": "VERIFIED", "finished": 2, "baseline": prepared["baseline"],
            "snapshot": prepared["snapshot"], "branch": branch, "baseline_commit": commit,
            "path": str(job / "workspace/review"), "patch_applied_to_workspace": True,
            "checks": display, "checks_sha256": sha(checks_raw)}
        for name, raw in (("initial-receipt.json", canonical(initial)), ("receipt.json", canonical(receipt)),
                          ("request.json", canonical(request)), ("task.json", task_raw),
                          ("snapshot.zip", archive), ("checks.json", checks_raw)):
            (job / name).write_bytes(raw)
        yield root, data, job, source, task, before, after


def initial_receipt(identifier, workspace="a" * 16):
    return {"version": 1, "format": recheck.FORMAT, "id": identifier, "workspace_id": workspace,
        "status": "PREPARING", "created": 1, "source_applied": False, "workspace_modified": False,
        "creation_sha256": "c" * 64, "preview_sha256": "d" * 64, "history_sha256": "e" * 64}


def stage(data, job, identifier="b" * 16):
    inspected = recheck.inspect(job)["summary"]
    history = recheck.history_pin(data / "snapshot-workspace-rechecks")
    request = {"version": 1, "id": identifier, "workspace_id": job.name, "job_dir": str(job),
        "creation_sha256": inspected["creation_sha256"], "history_sha256": history,
        "preview_sha256": sha(canonical({"inspection": inspected, "history_sha256": history}))}
    attempt = data / "snapshot-workspace-rechecks" / identifier
    attempt.mkdir(mode=0o700)
    initial = initial_receipt(identifier, job.name)
    initial.update({key: request[key] for key in recheck.PINS})
    (attempt / "request.json").write_bytes(canonical(request))
    (attempt / "receipt.json").write_bytes(canonical(initial))
    return attempt, request, initial


def change(path, function):
    value = json.loads(path.read_bytes())
    function(value)
    path.write_bytes(canonical(value))


class SnapshotRecheckTests(unittest.TestCase):
    def refused(self, function, *args, suffix=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            function(*args, **kwargs)
        self.assertIn(str(caught.exception), recheck.CODES)
        self.assertNotIn(PRIVATE, str(caught.exception))
        if suffix:
            self.assertEqual(str(caught.exception), "SNAPSHOT_RECHECK_" + suffix)

    def test_inspection_is_readonly_bounded_and_accepts_current_editable_bytes(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (root, _, job, _, task, _, after):
                editable = task["editable"][0]
                (job / "workspace/review" / editable).write_bytes(after[editable] + b"// manual owner edit\n")
                original, real_open = tree(root), os.open
                def readonly(path, flags, *args, **kwargs):
                    self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                    return real_open(path, flags, *args, **kwargs)
                with patch("os.open", readonly), patch("subprocess.run", side_effect=AssertionError("process")), \
                     patch("socket.socket", side_effect=AssertionError("network")):
                    inspected = recheck.inspect(job, sha((job / "receipt.json").read_bytes()))
                self.assertEqual(set(inspected), {"summary", "task", "selected_bytes"})
                summary = inspected["summary"]
                self.assertEqual(summary["changed_files"], 1)
                self.assertEqual(summary["checks"], [{"name": name, "spec": spec} for name, spec in sorted(task["checks"].items())])
                self.assertEqual(summary["max_turns"], task["max_turns"])
                self.assertEqual(summary["request_seconds"], task["request_seconds"])
                self.assertEqual(summary["branch"], "outlands/snapshot-" + job.name)
                self.assertLessEqual(len(canonical(summary)), 65536)
                self.assertNotIn(str(root), canonical(summary).decode())
                self.assertNotIn(task["goal"], canonical(summary).decode())
                self.assertEqual(tree(root), original)

    def test_stale_raw_creation_pin_and_nonverified_legacy_creation_refuse(self):
        for kind in ("pin", "failed", "legacy", "initial", "request"):
            with self.subTest(kind=kind), fixture() as (_, _, job, _, _, _, _):
                if kind == "pin":
                    self.refused(recheck.inspect, job, "f" * 64, suffix="STALE")
                    continue
                if kind == "failed": change(job / "receipt.json", lambda value: value.update(status="FAILED"))
                elif kind == "legacy": change(job / "receipt.json", lambda value: value.update(format="outlands-bundle-workspace-v1"))
                elif kind == "initial": change(job / "initial-receipt.json", lambda value: value.update(created=2))
                else: change(job / "request.json", lambda value: value.update(version=True))
                self.refused(recheck.inspect, job)

    def test_protected_extra_executable_symlink_and_hardlink_are_ineligible(self):
        for kind in ("protected", "extra", "executable", "symlink", "hardlink"):
            with self.subTest(kind=kind), fixture() as (root, _, job, _, task, _, _):
                work = job / "workspace/review"
                protected = next(name for name in task["files"] if name not in task["editable"])
                path = work / protected
                if kind == "protected": path.write_bytes(b"changed protected\n")
                elif kind == "extra": (work / "extra.py").write_bytes(b"unapproved\n")
                elif kind == "executable": path.chmod(0o700)
                elif kind == "symlink":
                    moved = root / "outside";path.rename(moved);path.symlink_to(moved)
                else: (root / "hard").hardlink_to(path)
                self.refused(recheck.inspect, job, suffix="PROTECTED_CHANGED" if kind == "protected" else None)

    def test_source_archive_config_task_and_saved_checks_drift_refuse(self):
        for kind in ("source", "archive", "config", "task", "checks", "display", "full-types", "full-unknown", "initial"):
            with self.subTest(kind=kind), fixture() as (root, _, job, source, task, _, _):
                if kind == "source": (source / task["editable"][0]).write_bytes(b"source drift\n")
                elif kind == "archive": (job / "snapshot.zip").write_bytes(b"invalid archive")
                elif kind == "config": (root / "config.json").write_bytes(b"{}\n")
                elif kind == "task": (root / "task.json").write_bytes(b"{}\n")
                elif kind == "checks": (job / "checks.json").write_bytes(b"{}\n")
                elif kind == "display": change(job / "receipt.json", lambda value: value["checks"]["unit"].update(output="different"))
                elif kind == "initial": (job / "initial-receipt.json").write_bytes(b"{}\n")
                else:
                    checks = json.loads((job / "checks.json").read_bytes())
                    checks["unit"]["exit_code" if kind == "full-types" else "unrecognized"] = False if kind == "full-types" else PRIVATE
                    raw = canonical(checks);(job / "checks.json").write_bytes(raw)
                    change(job / "receipt.json", lambda value: value.update(checks_sha256=sha(raw)))
                self.refused(recheck.inspect, job)

    def test_clipped_creation_check_display_does_not_replace_full_evidence(self):
        with fixture() as (_, _, job, _, task, _, _):
            checks = passed(None, task, None);checks["unit"]["output"] = "x" * 6000
            full, display, _ = _check_results(checks, task)
            raw = canonical(full);(job / "checks.json").write_bytes(raw)
            change(job / "receipt.json", lambda value: value.update(checks=display, checks_sha256=sha(raw)))
            self.assertEqual(recheck.inspect(job)["summary"]["changed_files"], 0)
            checks["unit"]["output"] = "x" * 4096
            raw = canonical(checks);(job / "checks.json").write_bytes(raw)
            change(job / "receipt.json", lambda value: value.update(checks_sha256=sha(raw)))
            self.refused(recheck.inspect, job)

    def test_git_config_ref_pointer_index_and_object_changes_refuse_without_git(self):
        for kind in ("config", "ref", "pointer", "index", "object"):
            with self.subTest(kind=kind), fixture() as (_, _, job, _, _, _, _):
                common = job / "workspace/baseline-repo/.git"
                if kind == "config": (common / "config").write_bytes(b"[core]\n\thooksPath = /private\n")
                elif kind == "ref": (common / "refs/heads/baseline").write_bytes(b"f" * 40 + b"\n")
                elif kind == "pointer": (job / "workspace/review/.git").write_bytes(b"gitdir: ../../../../outside\n")
                elif kind == "index":
                    path = common / "worktrees/review/index";raw = bytearray(path.read_bytes());raw[-1] ^= 1;path.write_bytes(raw)
                else:
                    receipt = json.loads((job / "receipt.json").read_bytes());oid = receipt["baseline_commit"]
                    (common / "objects" / oid[:2] / oid[2:]).write_bytes(b"invalid object")
                with patch("subprocess.run", side_effect=AssertionError("Git execution")):
                    self.refused(recheck.inspect, job, suffix="INDEX_INVALID" if kind == "index" else None)

    def test_index_must_still_describe_original_baseline_not_imported_snapshot(self):
        with fixture() as (_, _, job, _, task, before, after):
            path = job / "workspace/baseline-repo/.git/worktrees/review/index"
            raw = bytearray(path.read_bytes()[:-20])
            cursor = 12
            for name in sorted(before):
                if name in task["editable"]:
                    framed = b"blob " + str(len(after[name])).encode() + b"\x00" + after[name]
                    raw[cursor + 40:cursor + 60] = hashlib.sha1(framed).digest()
                end = raw.index(b"\x00", cursor + 62)
                cursor += ((end - cursor + 1 + 7) // 8) * 8
            path.write_bytes(bytes(raw) + hashlib.sha1(raw).digest())
            self.refused(recheck.inspect, job, suffix="INDEX_INVALID")

    def test_full32_file_total_boundary_and_nested_git_baseline_are_supported(self):
        before = {"main.py": b"1" * 4096, "test_main.py": b"#" * 4096,
                  **{"nested/f%02d.py" % index: b"x" * 4096 for index in range(30)}}
        after = {**before, "main.py": b"2" * 4096}
        with fixture(before=before, after=after) as (_, data, job, _, _, _, _):
            summary = recheck.inspect(job)["summary"]
            self.assertEqual(summary["total_bytes"], 131072)
            self.assertEqual(len(summary["files"]), 32)
            attempt, _, _ = stage(data, job)
            self.assertEqual(recheck.run(attempt, checker=passed)["status"], "VERIFIED")

    def test_snapshot_worker_checks_new_copy_and_keeps_creation_source_worktree_immutable(self):
        for java in (False, True):
            with self.subTest(java=java), fixture(java=java) as (_, data, job, source, task, _, after):
                editable = task["editable"][0]
                current = {**after, editable: after[editable] + b"// owner edit\n"}
                (job / "workspace/review" / editable).write_bytes(current[editable])
                attempt, _, initial = stage(data, job)
                original_job, original_source, calls = tree(job), tree(source), []
                def checker(snapshot, selected, jdk):
                    calls.append(snapshot)
                    self.assertEqual(snapshot, attempt / "snapshot")
                    self.assertEqual({name: (snapshot / name).read_bytes() for name in selected["files"]}, current)
                    self.assertEqual(jdk, Path("/invented/jdk") if java else None)
                    return passed(snapshot, selected, jdk)
                with patch("subprocess.run", side_effect=AssertionError("process")), patch("socket.socket", side_effect=AssertionError("network")):
                    receipt = recheck.run(attempt, Path("/invented/jdk") if java else None, checker)
                self.assertEqual(len(calls), 1)
                self.assertTrue(recheck.valid_receipt(receipt))
                self.assertEqual(receipt["status"], "VERIFIED")
                self.assertEqual(receipt["format"], recheck.FORMAT)
                self.assertFalse(receipt["workspace_modified"]);self.assertFalse(receipt["source_applied"])
                self.assertEqual(receipt["checked_files"], {name: sha(raw) for name, raw in current.items()})
                self.assertEqual((attempt / "initial-receipt.json").read_bytes(), canonical(initial))
                self.assertEqual(tree(job), original_job);self.assertEqual(tree(source), original_source)
                self.assertFalse((attempt / "receipt.json.next").exists())

    def test_stale_preview_refuses_before_checks_and_retains_failed_attempt(self):
        with fixture() as (_, data, job, _, task, _, _):
            attempt, _, _ = stage(data, job)
            (job / "workspace/review" / task["editable"][0]).write_bytes(b"late owner edit\n")
            calls = []
            def checker(*args): calls.append(args);return passed(*args)
            self.refused(recheck.run, attempt, checker=checker, suffix="STALE")
            self.assertEqual(calls, [])
            failed = json.loads((attempt / "receipt.json").read_bytes())
            self.assertTrue(recheck.valid_receipt(failed));self.assertEqual(failed["status"], "FAILED")
            before = tree(attempt)
            self.refused(recheck.run, attempt, checker=checker)
            self.assertEqual(tree(attempt), before)

    def test_failed_check_and_owned_interrupt_are_retained_without_second_attempt(self):
        for kind in ("failure", "keyboard", "systemexit", "exception"):
            with self.subTest(kind=kind), fixture() as (_, data, job, source, task, _, _):
                attempt, _, _ = stage(data, job)
                original, calls = tree(source), []
                def checker(work, selected, jdk):
                    calls.append(work)
                    if kind == "keyboard": raise KeyboardInterrupt(PRIVATE)
                    if kind == "systemexit": raise SystemExit(PRIVATE)
                    if kind == "exception": raise RuntimeError(PRIVATE)
                    results = passed(work, selected, jdk);results["unit"]["exit_code"] = 1;return results
                suffix = "CHECKS_FAILED" if kind == "failure" else "INTERRUPTED" if kind in {"keyboard", "systemexit"} else "EXECUTION_FAILED"
                self.refused(recheck.run, attempt, checker=checker, suffix=suffix)
                receipt = json.loads((attempt / "receipt.json").read_bytes())
                self.assertTrue(recheck.valid_receipt(receipt))
                self.assertEqual(receipt["status"], "INTERRUPTED" if suffix == "INTERRUPTED" else "FAILED")
                self.assertEqual(len(calls), 1);self.assertEqual(tree(source), original)
                self.assertTrue((attempt / "snapshot").is_dir())
                before = tree(attempt);self.refused(recheck.run, attempt, checker=checker)
                self.assertEqual(tree(attempt), before);self.assertEqual(len(calls), 1)

    def test_copy_source_worktree_git_request_task_checks_and_history_drift_refuse(self):
        for kind in ("snapshot", "source", "worktree", "git", "request", "task", "history", "creation-next"):
            with self.subTest(kind=kind), fixture() as (_, data, job, source, task, _, _):
                attempt, _, _ = stage(data, job)
                def checker(snapshot, selected, jdk):
                    if kind == "snapshot": (snapshot / task["editable"][0]).write_bytes(b"checker edited copy\n")
                    elif kind == "source": (source / task["editable"][0]).write_bytes(b"external source drift\n")
                    elif kind == "worktree": (job / "workspace/review" / task["editable"][0]).write_bytes(b"external worktree drift\n")
                    elif kind == "git": (job / "workspace/baseline-repo/.git/config").write_bytes(b"bad\n")
                    elif kind == "request": (attempt / "request.json").write_bytes(b"{}\n")
                    elif kind == "task": (attempt / "task.json").write_bytes(b"{}\n")
                    elif kind == "creation-next": (job / "receipt.json.next").write_bytes(b"partial\n")
                    else:
                        other = attempt.parent / ("c" * 16);other.mkdir(mode=0o700)
                        (other / "receipt.json").write_bytes(canonical(initial_receipt(other.name)))
                    return passed(snapshot, selected, jdk)
                self.refused(recheck.run, attempt, checker=checker, suffix="STALE")
                self.assertNotEqual(json.loads((attempt / "receipt.json").read_bytes())["status"], "VERIFIED")

    def test_final_pre_replace_guards_and_exact_initial_raw_do_not_overwrite_drift(self):
        for kind in ("receipt", "checks", "worktree"):
            with self.subTest(kind=kind), fixture() as (_, data, job, _, task, _, _):
                attempt, _, initial = stage(data, job)
                real_write = recheck.write_new
                def late(path, raw):
                    real_write(path, raw)
                    if path == attempt / "receipt.json.next":
                        if kind == "receipt": (attempt / "receipt.json").write_bytes(b"external terminal record\n")
                        elif kind == "checks": (attempt / "checks.json").write_bytes(b"{}\n")
                        else: (job / "workspace/review" / task["editable"][0]).write_bytes(b"late drift\n")
                with patch.object(recheck, "write_new", side_effect=late):
                    self.refused(recheck.run, attempt, checker=passed, suffix="STALE")
                self.assertTrue((attempt / "receipt.json.next").exists())
                expected = b"external terminal record\n" if kind == "receipt" else canonical(initial)
                self.assertEqual((attempt / "receipt.json").read_bytes(), expected)

    def test_pending_sentinels_and_partial_attempts_are_never_repaired(self):
        for kind in ("creation", "history", "attempt", "partial"):
            with self.subTest(kind=kind), fixture() as (_, data, job, _, _, _, _):
                attempt, _, _ = stage(data, job)
                if kind == "creation": target = job / "receipt.json.next"
                elif kind in {"attempt", "partial"}: target = attempt / ("receipt.json.next" if kind == "attempt" else "snapshot")
                else:
                    other = attempt.parent / ("c" * 16);other.mkdir(mode=0o700)
                    (other / "receipt.json").write_bytes(canonical(initial_receipt(other.name)))
                    target = other / "receipt.json.next"
                if kind == "partial": target.mkdir(mode=0o700)
                else: target.write_bytes(b"retained unknown partial\n")
                before = tree(data)
                if kind == "creation": self.refused(recheck.inspect, job)
                elif kind == "history": self.refused(recheck.history_pin, attempt.parent)
                else: self.refused(recheck.run, attempt, checker=passed)
                self.assertEqual(tree(data), before)

    def test_history_retains_valid_failures_and_rejects_unknown_and_bounds(self):
        with fixture() as (_, data, _, _, _, _, _):
            root = data / "snapshot-workspace-rechecks"
            empty = recheck.history_pin(root)
            for index, status in enumerate(("PREPARING", "FAILED", "INTERRUPTED")):
                identifier = "%016x" % index;target = root / identifier;target.mkdir(mode=0o700)
                value = initial_receipt(identifier)
                if status != "PREPARING": value.update(status=status, finished=2, reason="SNAPSHOT_RECHECK_" + ("INTERRUPTED" if status == "INTERRUPTED" else "CHECKS_FAILED"))
                (target / "receipt.json").write_bytes(canonical(value))
            before = tree(root);self.assertNotEqual(recheck.history_pin(root), empty);self.assertEqual(tree(root), before)
            change(root / ("0" * 16) / "receipt.json", lambda value: value.update(extra=PRIVATE))
            before = tree(root);self.refused(recheck.history_pin, root);self.assertEqual(tree(root), before)
        with fixture() as (_, data, _, _, _, _, _):
            root = data / "snapshot-workspace-rechecks"
            for index in range(201): (root / ("%016x" % index)).mkdir(mode=0o700)
            self.refused(recheck.history_pin, root, suffix="LIMIT")

    def test_file_total_record_and_output_limits_are_finite(self):
        for kind in ("file", "total", "record"):
            with self.subTest(kind=kind), fixture() as (_, _, job, _, task, _, _):
                if kind == "file": (job / "workspace/review" / task["editable"][0]).write_bytes(b"x" * 32769)
                elif kind == "total":
                    with patch.object(recheck, "MAX_TOTAL", 1): self.refused(recheck.inspect, job, suffix="LIMIT")
                    continue
                else: (job / "receipt.json").write_bytes(b"x" * 262145)
                self.refused(recheck.inspect, job, suffix="LIMIT")

    def test_receipt_validation_rejects_untyped_oversized_or_unexpected_metadata(self):
        with fixture() as (_, data, job, _, _, _, _):
            attempt, _, _ = stage(data, job);receipt = recheck.run(attempt, checker=passed)
            changes = [lambda value: value.update(format="outlands-workspace-recheck-v1"),
                lambda value: value.update(extra=PRIVATE), lambda value: value.update(created=True),
                lambda value: value.update(finished=0), lambda value: value.update(source_applied=True),
                lambda value: value.update(workspace_modified=True), lambda value: value.update(reason="SNAPSHOT_RECHECK_STALE"),
                lambda value: value.update(checked_files={"../outside": "f" * 64}),
                lambda value: value["checks"]["unit"].update(exit_code=False),
                lambda value: value["checks"]["unit"].update(tests_ran=True),
                lambda value: value["checks"]["unit"].update(output="x" * 4097),
                lambda value: value.update(status="INTERRUPTED", reason="SNAPSHOT_RECHECK_CHECKS_FAILED")]
            for index, modify in enumerate(changes):
                with self.subTest(index=index):
                    invalid = copy.deepcopy(receipt);modify(invalid);self.assertFalse(recheck.valid_receipt(invalid))

    def test_worker_cli_uses_owned_sigterm_handler_and_fixed_error_only(self):
        with fixture() as (_, data, job, _, _, _, _):
            attempt, _, _ = stage(data, job)
            previous = signal.getsignal(signal.SIGTERM)
            def stop(selected, jdk=None):
                self.assertEqual(selected, attempt);self.assertIsNone(jdk)
                handler = signal.getsignal(signal.SIGTERM);self.assertTrue(callable(handler))
                handler(signal.SIGTERM, None)
            with patch.object(recheck, "run", side_effect=stop), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(recheck.main(["--attempt-dir", str(attempt)]), 1)
            self.assertEqual(json.loads(output.getvalue()), {"error": "SNAPSHOT_RECHECK_INTERRUPTED"})
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(recheck.main(["--attempt-dir", "/tmp/" + PRIVATE, "--attempt-dir", "/tmp/x"]), 1)
        self.assertNotIn(PRIVATE, output.getvalue())


if __name__ == "__main__":
    unittest.main()
