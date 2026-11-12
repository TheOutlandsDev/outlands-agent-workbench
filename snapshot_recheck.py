"""Read-only snapshot-workspace inspection and explicit checks of a private copy."""

import copy
import json
import os
import re
import signal
import stat
import struct
import sys
import time
import zlib
from pathlib import Path

from agent import Refused, canonical, object_pairs, parse, sha, write_new
from bundle_project_check import ReadIssue, _path, _read_named, read_selected
from bundle_workspace import _check_results, _directory
from git_workspace import fixed_checks
from snapshot_workspace import (CORE_FIELDS as CREATION_CORE, REQUEST_FIELDS as CREATION_REQUEST,
                                _display_checks, _file_map, _project, prepare,
                                valid_receipt as valid_creation)
from workspace_recheck import _git_metadata, _inventory


FORMAT = "outlands-snapshot-workspace-recheck-v1"
MAX_FILE, MAX_TOTAL, MAX_JSON, MAX_ARCHIVE, MAX_CHECKS = 32768, 131072, 262144, 2097152, 2097152
MAX_SAFE = 9007199254740991
ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
REQUEST_FIELDS = {"version", "id", "workspace_id", "job_dir", "preview_sha256", "creation_sha256", "history_sha256"}
PINS = {"creation_sha256", "preview_sha256", "history_sha256"}
CORE_FIELDS = {"version", "format", "id", "workspace_id", "status", "created", "source_applied", "workspace_modified"} | PINS
SNAPSHOT_FIELDS = {"snapshot_sha256", "checked_files", "task_sha256", "archive_sha256", "config_sha256"}
PROGRESS_FIELDS = SNAPSHOT_FIELDS | {"checks", "checks_sha256"}
CODES = frozenset("SNAPSHOT_RECHECK_" + suffix for suffix in (
    "INPUT", "RECORD_INVALID", "LIMIT", "OUTPUT_LIMIT", "CREATION_REQUIRED", "STALE", "PROTECTED_CHANGED",
    "GIT_CHANGED", "INDEX_INVALID", "CHECKS_FAILED", "INTERRUPTED", "EXECUTION_FAILED", "START_FAILED"))


def _require(condition, suffix="RECORD_INVALID"):
    if not condition:
        raise Refused("SNAPSHOT_RECHECK_" + suffix)


def _integer(value, low=0, high=MAX_SAFE):
    return type(value) is int and low <= value <= high


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _id(value):
    return type(value) is str and ID.fullmatch(value) is not None


def _reason(error, default="EXECUTION_FAILED"):
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "SNAPSHOT_RECHECK_INTERRUPTED"
    code = str(error) if isinstance(error, Refused) else None
    if code in CODES:
        return code
    if type(code) is str and code.startswith("RECHECK_"):
        mapped = "SNAPSHOT_" + code
        return mapped if mapped in CODES else "SNAPSHOT_RECHECK_" + default
    if isinstance(error, ReadIssue) and str(error) == "LIMIT" or code in {
        "SNAPSHOT_WORKSPACE_LIMIT", "SNAPSHOT_WORKSPACE_OUTPUT_LIMIT", "PROJECT_CHECK_LIMIT"
    }:
        return "SNAPSHOT_RECHECK_LIMIT"
    return "SNAPSHOT_RECHECK_" + default


def _no_pending(root):
    fd = _directory(root, private=True)
    try:
        try:
            os.stat("receipt.json.next", dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        _require(False)
    finally:
        os.close(fd)


def _fresh_attempt(root):
    fd = _directory(root, private=True)
    try:
        for name in ("initial-receipt.json", "task.json", "checks.json", "snapshot"):
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            _require(False)
    finally:
        os.close(fd)


def valid_receipt(value):
    """Recognize only this finite format, including retained terminal failures."""
    try:
        if (type(value) is not dict or not CORE_FIELDS <= set(value)
                or set(value) - CORE_FIELDS - PROGRESS_FIELDS - {"finished", "reason"}
                or type(value["version"]) is not int or value["version"] != 1 or value["format"] != FORMAT
                or not _id(value["id"]) or not _id(value["workspace_id"])
                or value["source_applied"] is not False or value["workspace_modified"] is not False
                or not _integer(value["created"]) or not all(_hash(value[key]) for key in PINS)
                or type(value["status"]) is not str or value["status"] not in {"PREPARING", "VERIFIED", "FAILED", "INTERRUPTED"}):
            return False
        if value["status"] == "PREPARING":
            return set(value) == CORE_FIELDS
        if not _integer(value.get("finished")) or value["finished"] < value["created"]:
            return False
        if value["status"] in {"FAILED", "INTERRUPTED"}:
            if (type(value.get("reason")) is not str or value["reason"] not in CODES
                    or (value["status"] == "INTERRUPTED") != (value["reason"] == "SNAPSHOT_RECHECK_INTERRUPTED")):
                return False
        elif "reason" in value:
            return False
        if SNAPSHOT_FIELDS & set(value):
            if not SNAPSHOT_FIELDS <= set(value) or not _file_map(value["checked_files"]):
                return False
            if not all(_hash(value[key]) for key in SNAPSHOT_FIELDS - {"checked_files"}):
                return False
        if ("checks" in value) != ("checks_sha256" in value):
            return False
        if "checks" in value and (not SNAPSHOT_FIELDS <= set(value) or not _hash(value["checks_sha256"])
                                  or not _display_checks(value["checks"], value["status"] == "VERIFIED")):
            return False
        return value["status"] != "VERIFIED" or PROGRESS_FIELDS <= set(value)
    except (Refused, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return False


def _saved_checks(raw, task):
    _require(type(raw) is bytes and len(raw) <= MAX_CHECKS, "LIMIT")
    # Full evidence can exceed the ordinary JSON reader's 256 KiB bound.
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    full, display, passing = _check_results(value, task)
    _require(passing and canonical(full) == raw)
    for name, spec in task["checks"].items():
        expected_kind = spec["kind"] if type(spec) is dict else "python-unittest"
        _require("kind" not in full[name] or full[name]["kind"] == expected_kind)
    return display


def _inspect(job, expected_creation_sha256):
    _no_pending(job)
    _require(_id(job.name), "INPUT")
    creation_raw = _read_named(job / "receipt.json", MAX_JSON, text=True)
    if expected_creation_sha256 is not None:
        _require(_hash(expected_creation_sha256), "INPUT")
        _require(sha(creation_raw) == expected_creation_sha256, "STALE")
    creation = parse(creation_raw)
    _require(type(creation) is dict and creation.get("status") == "VERIFIED", "CREATION_REQUIRED")
    _require(valid_creation(creation) and creation["id"] == job.name)
    initial_raw = _read_named(job / "initial-receipt.json", MAX_JSON, text=True)
    initial = parse(initial_raw)
    _require(valid_creation(initial) and initial["status"] == "PREPARING"
             and all(initial[key] == creation[key] for key in CREATION_CORE - {"status"}))
    branch, commit = "outlands/snapshot-" + job.name, creation["baseline_commit"]
    _require(creation["branch"] == branch and creation["path"] == str(job / "workspace/review"), "GIT_CHANGED")
    request_raw = _read_named(job / "request.json", 32768, text=True)
    request = parse(request_raw)
    _require(type(request) is dict and set(request) == CREATION_REQUEST and type(request["version"]) is int
             and request["version"] == 1 and request["id"] == job.name and all(request[key] == creation[key] for key in
                 ("project_id", "config_sha256", "task_sha256", "archive_sha256", "preview_sha256")))
    for key in ("source", "config_path", "task_path"):
        _require(type(request[key]) is str)
        _path(Path(request[key]))
        _require(job != Path(request[key]) and job not in Path(request[key]).parents)
    source = Path(request["source"])
    _require(source not in job.parents)
    task_raw = _read_named(job / "task.json", MAX_JSON, text=True)
    _project(request, task_raw)
    raw = _read_named(job / "snapshot.zip", MAX_ARCHIVE)
    prepared = prepare(raw, source, task_raw, creation["archive_sha256"])
    task, previous = prepared["task"], prepared["summary"]
    _require(sha(task_raw) == creation["task_sha256"] and previous["patch_sha256"] == creation["patch_sha256"]
             and creation["baseline"] == previous["baseline"] and creation["snapshot"] == previous["snapshot"])
    binding = {"version": 1, "project_id": request["project_id"], "archive_sha256": sha(raw),
               "task_sha256": sha(task_raw), "config_sha256": request["config_sha256"], "prepared": previous}
    _require(sha(canonical(binding)) == creation["preview_sha256"])
    checks_raw = _read_named(job / "checks.json", MAX_CHECKS, text=True)
    _require(sha(checks_raw) == creation["checks_sha256"] and _saved_checks(checks_raw, task) == creation["checks"])
    work = job / "workspace/review"
    _inventory(work, task["files"], allow_git=True)
    # v15 stored no historical raw Git guards. Validate current baseline semantics,
    # then pin the current control/index bytes; no historical-byte claim is made.
    guards = _git_metadata(job, branch, commit, prepared["baseline"])
    selected = {name: read_selected(work, name) for name in sorted(task["files"])}
    _require(sum(map(len, selected.values())) <= MAX_TOTAL, "LIMIT")
    files = []
    for name, value in selected.items():
        editable, current, created_hash = name in task["editable"], sha(value), previous["snapshot"][name]
        _require(editable or current == created_hash, "PROTECTED_CHANGED")
        files.append({"path": name, "editable": editable, "created_sha256": created_hash,
                      "current_sha256": current, "bytes": len(value), "changed": current != created_hash})
    pins = {"creation_sha256": sha(creation_raw), "request_sha256": sha(request_raw), "archive_sha256": sha(raw),
            "task_sha256": sha(task_raw), "config_sha256": request["config_sha256"],
            "initial_receipt_sha256": sha(initial_raw), "creation_checks_sha256": sha(checks_raw)}
    snapshot = {"files": {row["path"]: row["current_sha256"] for row in files}, "guards": guards, **pins}
    summary = {"version": 1, "workspace_id": job.name, **pins, "patch_sha256": creation["patch_sha256"],
        "baseline_commit": commit, "branch": branch, "files": files, "changed_files": sum(row["changed"] for row in files),
        "guards": guards, "snapshot_sha256": sha(canonical(snapshot)),
        "checks": [{"name": name, "spec": copy.deepcopy(spec)} for name, spec in sorted(task["checks"].items())],
        "max_turns": task["max_turns"], "request_seconds": task["request_seconds"],
        "total_bytes": sum(map(len, selected.values())), "source_applied": False}
    _require(len(canonical(summary)) <= 65536, "OUTPUT_LIMIT")
    return {"summary": summary, "task": copy.deepcopy(task), "selected_bytes": selected}


def inspect(job, expected_creation_sha256=None):
    """Read eligible owner edits and saved pins without writes or Git execution."""
    try:
        return _inspect(job, expected_creation_sha256)
    except (Refused, ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError,
            RecursionError, UnicodeError, struct.error, zlib.error) as error:
        raise Refused(_reason(error, "RECORD_INVALID")) from None


def history_pin(root, exclude_id=None):
    """Pin bounded saved attempt receipts; unknown/partial evidence stays untouched."""
    try:
        _require(exclude_id is None or _id(exclude_id), "INPUT")
        fd, names = _directory(root, private=True), []
        try:
            with os.scandir(fd) as entries:
                for count, entry in enumerate(entries, 1):
                    _require(count <= 1024, "LIMIT")
                    _require(_id(entry.name) and stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode))
                    if entry.name != exclude_id:
                        names.append(entry.name)
                        _require(len(names) <= 200, "LIMIT")
        finally:
            os.close(fd)
        rows, budget = [], MAX_CHECKS
        for name in sorted(names):
            _no_pending(root / name)
            _require(budget > 0, "LIMIT")
            raw = _read_named(root / name / "receipt.json", min(MAX_JSON, budget), text=True)
            budget -= len(raw)
            value = parse(raw)
            _require(valid_receipt(value) and value["id"] == name)
            rows.append({"id": name, "receipt_sha256": sha(raw)})
        return sha(canonical(rows))
    except (Refused, ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise Refused(_reason(error, "RECORD_INVALID")) from None


def _snapshot(root, selected):
    try:
        _inventory(root, selected)
        _require(all(read_selected(root, name) == value for name, value in selected.items()), "STALE")
    except (Refused, ReadIssue, OSError, ValueError, TypeError):
        raise Refused("SNAPSHOT_RECHECK_STALE") from None


def _unchanged(job, pin, summary, history, identifier, history_sha):
    try:
        _require(inspect(job, pin)["summary"] == summary and history_pin(history, identifier) == history_sha, "STALE")
    except (Refused, ReadIssue, OSError, ValueError, TypeError):
        raise Refused("SNAPSHOT_RECHECK_STALE") from None


def _record(attempt, receipt, expected_raw, guard=None):
    _require(valid_receipt(receipt))
    raw = canonical(receipt)
    _require(len(raw) <= MAX_JSON, "OUTPUT_LIMIT")
    # O_EXCL preserves any prior partial/unknown write. Never remove or retry it.
    write_new(attempt / "receipt.json.next", raw)
    _require(_read_named(attempt / "receipt.json", MAX_JSON, text=True) == expected_raw, "STALE")
    if guard is not None:
        guard()
    _require(_read_named(attempt / "receipt.json", MAX_JSON, text=True) == expected_raw, "STALE")
    os.replace(attempt / "receipt.json.next", attempt / "receipt.json")


def run(attempt, jdk_home=None, checker=fixed_checks):
    """Check one explicitly staged copy; retain failure, interruption and partials."""
    can_record, record_attempted, receipt, initial_raw = False, False, None, None
    try:
        _no_pending(attempt)
        _fresh_attempt(attempt)
        initial_raw = _read_named(attempt / "receipt.json", MAX_JSON, text=True)
        initial = parse(initial_raw)
        _require(valid_receipt(initial) and initial["status"] == "PREPARING" and initial["id"] == attempt.name)
        receipt, can_record = copy.deepcopy(initial), True
        write_new(attempt / "initial-receipt.json", initial_raw)
        request_raw = _read_named(attempt / "request.json", MAX_JSON, text=True)
        request = parse(request_raw)
        _require(type(request) is dict and set(request) == REQUEST_FIELDS and type(request["version"]) is int
                 and request["version"] == 1 and request["id"] == attempt.name and _id(request["workspace_id"])
                 and all(_hash(request[key]) for key in PINS) and type(request["job_dir"]) is str
                 and all(initial[key] == request[key] for key in PINS | {"id", "workspace_id"}))
        _require(attempt.parent.name == "snapshot-workspace-rechecks")
        job = Path(request["job_dir"])
        _require(job == attempt.parent.parent / "snapshot-workspaces" / request["workspace_id"])
        _require(history_pin(attempt.parent, attempt.name) == request["history_sha256"], "STALE")
        inspected = inspect(job, request["creation_sha256"])
        summary, task, selected = inspected["summary"], inspected["task"], inspected["selected_bytes"]
        _require(sha(canonical({"inspection": summary, "history_sha256": request["history_sha256"]}))
                 == request["preview_sha256"], "STALE")
        receipt.update(snapshot_sha256=summary["snapshot_sha256"], checked_files={name: sha(raw) for name, raw in selected.items()},
                       task_sha256=summary["task_sha256"], archive_sha256=summary["archive_sha256"], config_sha256=summary["config_sha256"])
        _require(jdk_home is not None or not any(type(spec) is dict and spec.get("kind") == "java-main"
                 for spec in task["checks"].values()), "CHECKS_FAILED")
        snapshot = attempt / "snapshot"
        snapshot.mkdir(mode=0o700, exist_ok=False)
        for name, raw in selected.items():
            target = snapshot / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(target, raw)
        task_raw = _read_named(job / "task.json", MAX_JSON, text=True)
        _require(sha(task_raw) == summary["task_sha256"], "STALE")
        write_new(attempt / "task.json", task_raw)
        full_raw = None

        def guards():
            _snapshot(snapshot, selected)
            _require(_read_named(attempt / "request.json", MAX_JSON, text=True) == request_raw
                     and _read_named(attempt / "task.json", MAX_JSON, text=True) == task_raw
                     and _read_named(attempt / "initial-receipt.json", MAX_JSON, text=True) == initial_raw, "STALE")
            if full_raw is not None:
                _require(_read_named(attempt / "checks.json", MAX_CHECKS, text=True) == full_raw, "STALE")
            _unchanged(job, request["creation_sha256"], summary, attempt.parent, attempt.name, request["history_sha256"])

        guards()
        full, display, passed = _check_results(checker(snapshot, copy.deepcopy(task), jdk_home), task)
        full_raw = canonical(full)
        _require(len(full_raw) <= MAX_CHECKS, "LIMIT")
        write_new(attempt / "checks.json", full_raw)
        receipt.update(checks=display, checks_sha256=sha(full_raw))
        guards()
        _require(passed, "CHECKS_FAILED")
        receipt.update(status="VERIFIED", finished=max(receipt["created"], int(time.time())))
        record_attempted = True
        _record(attempt, receipt, initial_raw, guards)
        return receipt
    except BaseException as error:
        reason = _reason(error)
        if can_record and not record_attempted:
            receipt.update(status="INTERRUPTED" if reason == "SNAPSHOT_RECHECK_INTERRUPTED" else "FAILED",
                           reason=reason, finished=max(receipt["created"], int(time.time())))
            try:
                _record(attempt, receipt, initial_raw)
            except (Refused, OSError, ValueError, TypeError, UnicodeError):
                pass
        raise Refused(reason) from None


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        _require(type(args) is list and len(args) in {2, 4} and all(type(arg) is str for arg in args), "INPUT")
        options = {}
        for key, value in zip(args[::2], args[1::2]):
            _require(key in {"--attempt-dir", "--jdk-home"} and key not in options, "INPUT")
            options[key] = Path(value)
            _path(options[key])
        _require("--attempt-dir" in options, "INPUT")
        def interrupted(*_):
            raise KeyboardInterrupt
        previous = signal.signal(signal.SIGTERM, interrupted)
        try:
            run(options["--attempt-dir"], options.get("--jdk-home"))
        finally:
            signal.signal(signal.SIGTERM, previous)
        return 0
    except BaseException as error:
        sys.stdout.write(canonical({"error": _reason(error)}).decode("ascii"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
