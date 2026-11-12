"""Prepare exact reviewed snapshot v2 packets by read-only evidence reconstruction."""

import os
from pathlib import Path

from agent import Refused, canonical, review_diff, sha
from bundle_project_check import ReadIssue, _path, _read_named, read_selected
from bundle_workspace import _apply, _directory, _lines
from snapshot_export import (CORE, FORMAT_V2, HASH_FIELDS_V2, ID, MAX_ARCHIVE, MAX_FILE, MAX_FULL,
                             MAX_JSON, MAX_PATCH, MAX_TOTAL, NOTES, NOT_CHECKED, README_V2,
                             _archive, _checks, _checksums, _diff, _hash, _json, verify_export)
from snapshot_recheck import (CORE_FIELDS, REQUEST_FIELDS, _no_pending, _saved_checks,
                              inspect, valid_receipt)
from snapshot_workspace import prepare as prepare_workspace
from workspace_recheck import _inventory


FORMAT = FORMAT_V2
HASH_FIELDS = HASH_FIELDS_V2
CODES = frozenset("SNAPSHOT_REEXPORT_" + suffix for suffix in (
    "INPUT", "RECORD_INVALID", "LIMIT", "OUTPUT_LIMIT", "VERIFIED_REQUIRED", "STALE",
    "PROTECTED_CHANGED", "NO_CHANGES", "PATCH_INVALID", "CHECKS_INVALID", "ARCHIVE_INVALID", "ARCHIVE_CHANGED"))


def _require(condition, suffix="RECORD_INVALID"):
    if not condition:
        raise Refused("SNAPSHOT_REEXPORT_" + suffix)


def _error(error):
    code = str(error) if isinstance(error, Refused) else None
    if code in CODES:
        return code
    if isinstance(error, ReadIssue) and str(error) == "LIMIT":
        return "SNAPSHOT_REEXPORT_LIMIT"
    if type(code) is str:
        if code.startswith("SNAPSHOT_EXPORT_"):
            mapped = code.replace("SNAPSHOT_EXPORT_", "SNAPSHOT_REEXPORT_", 1)
            return mapped if mapped in CODES else "SNAPSHOT_REEXPORT_RECORD_INVALID"
        if code in {"SNAPSHOT_RECHECK_PROTECTED_CHANGED"}:
            return "SNAPSHOT_REEXPORT_PROTECTED_CHANGED"
        if code in {"SNAPSHOT_RECHECK_LIMIT", "SNAPSHOT_WORKSPACE_LIMIT", "BUNDLE_WORKSPACE_LIMIT", "RECHECK_LIMIT"}:
            return "SNAPSHOT_REEXPORT_LIMIT"
        if code == "BUNDLE_WORKSPACE_PATCH_INVALID":
            return "SNAPSHOT_REEXPORT_PATCH_INVALID"
        if code.startswith(("SNAPSHOT_RECHECK_", "SNAPSHOT_WORKSPACE_", "RECHECK_")):
            return "SNAPSHOT_REEXPORT_STALE"
    return "SNAPSHOT_REEXPORT_RECORD_INVALID"


def _prepare(attempt, expected_receipt_sha256):
    _require(isinstance(attempt, Path), "INPUT")
    _path(attempt)
    fd = _directory(attempt, private=True)
    os.close(fd)
    _require(ID.fullmatch(attempt.name) is not None and attempt.parent.name == "snapshot-workspace-rechecks", "INPUT")
    _require(expected_receipt_sha256 is None or _hash(expected_receipt_sha256), "INPUT")
    _no_pending(attempt)
    pins = {}

    def read(path, limit=MAX_JSON, text=True):
        raw = _read_named(path, limit, text=text)
        pins[path] = raw
        return raw

    receipt_raw = read(attempt / "receipt.json")
    _require(expected_receipt_sha256 is None or sha(receipt_raw) == expected_receipt_sha256, "STALE")
    receipt = _json(receipt_raw)
    _require(receipt.get("status") == "VERIFIED", "VERIFIED_REQUIRED")
    _require(valid_receipt(receipt) and receipt["id"] == attempt.name)
    initial_raw, request_raw = read(attempt / "initial-receipt.json"), read(attempt / "request.json")
    initial, request = _json(initial_raw), _json(request_raw)
    _require(valid_receipt(initial) and initial["status"] == "PREPARING"
             and all(initial[key] == receipt[key] for key in CORE_FIELDS - {"status"})
             and type(request) is dict and set(request) == REQUEST_FIELDS
             and type(request["version"]) is int and request["version"] == 1
             and all(request[key] == receipt[key] for key in
                     ("id", "workspace_id", "creation_sha256", "preview_sha256", "history_sha256")))
    job = attempt.parent.parent / "snapshot-workspaces" / receipt["workspace_id"]
    _require(type(request["job_dir"]) is str and request["job_dir"] == str(job))
    inspected = inspect(job, receipt["creation_sha256"])
    summary, task, current = inspected["summary"], inspected["task"], inspected["selected_bytes"]
    _require(summary["snapshot_sha256"] == receipt["snapshot_sha256"] and all(summary[key] == receipt[key]
             for key in ("task_sha256", "archive_sha256", "config_sha256")), "STALE")
    _require(sha(canonical({"inspection": summary, "history_sha256": request["history_sha256"]}))
             == request["preview_sha256"], "STALE")
    task_raw = read(attempt / "task.json")
    _require(sha(task_raw) == receipt["task_sha256"] and read(job / "task.json") == task_raw, "STALE")
    creation_request_raw = read(job / "request.json", 32768)
    # Bind the reread raw request before following any of its external paths.
    _require(sha(creation_request_raw) == summary["request_sha256"], "STALE")
    creation_request = _json(creation_request_raw)
    _require(sha(read(job / "receipt.json")) == receipt["creation_sha256"]
             and sha(read(job / "initial-receipt.json")) == summary["initial_receipt_sha256"]
             and sha(read(job / "checks.json", MAX_FULL)) == summary["creation_checks_sha256"], "STALE")
    archive = read(job / "snapshot.zip", MAX_ARCHIVE, False)
    _require(sha(archive) == receipt["archive_sha256"], "STALE")
    reconstructed = prepare_workspace(archive, Path(creation_request["source"]), task_raw, receipt["archive_sha256"])
    _require(reconstructed["task"] == task, "STALE")
    baseline = reconstructed["baseline"]
    snapshot = attempt / "snapshot"
    _inventory(snapshot, task["files"])
    selected = {name: read_selected(snapshot, name) for name in sorted(task["files"])}
    _require(sum(map(len, selected.values())) <= MAX_TOTAL, "LIMIT")
    checked = {name: sha(value) for name, value in selected.items()}
    _require(receipt["checked_files"] == checked and selected == current, "STALE")
    for name in selected:
        _require(name in task["editable"] or selected[name] == baseline[name], "PROTECTED_CHANGED")
        _lines(baseline[name])
        _lines(selected[name])
    checks_raw = read(attempt / "checks.json", MAX_FULL)
    checks = _checks(checks_raw, receipt, task)
    try:
        _require(_saved_checks(checks_raw, task) == receipt["checks"], "CHECKS_INVALID")
    except (Refused, ValueError, TypeError, UnicodeError, RecursionError):
        raise Refused("SNAPSHOT_REEXPORT_CHECKS_INVALID") from None
    patch = "".join(review_diff(name, baseline[name], selected[name]) for name in sorted(baseline)).encode("utf-8")
    _require(bool(patch), "NO_CHANGES")
    _require(len(patch) <= MAX_PATCH, "LIMIT")
    changed = [name for name in sorted(baseline) if baseline[name] != selected[name]]
    _require(_apply(patch, dict(baseline), changed) == selected, "PATCH_INVALID")
    files = [{"path": name, "editable": name in task["editable"], "baseline_sha256": sha(baseline[name]),
              "snapshot_sha256": checked[name], "changed": name in changed} for name in sorted(selected)]
    hashes = {key: receipt[key] for key in ("creation_sha256", "snapshot_sha256", "task_sha256", "config_sha256", "checks_sha256")}
    hashes.update(import_archive_sha256=receipt["archive_sha256"], receipt_sha256=sha(receipt_raw),
                  request_sha256=sha(request_raw), initial_receipt_sha256=sha(initial_raw), patch_sha256=sha(patch))
    _require(set(hashes) == HASH_FIELDS)
    profile = {key: task[key] for key in ("format", "max_turns", "request_seconds")}
    verification = {"version": 2, "format": FORMAT, "evidence": "RECORDED_PASSING_SNAPSHOT_WORKSPACE_RECHECK",
        "hashes": hashes, "profile": profile, "files": files, "checks": checks, "source_applied": False,
        "workspace_modified": False, "not_checked": list(NOT_CHECKED), "notes": list(NOTES)}
    verification_raw = canonical(verification)
    _require(len(verification_raw) <= MAX_JSON, "OUTPUT_LIMIT")
    payloads = {"changes.diff": patch, "verification.json": verification_raw, "README.txt": README_V2}
    payloads["SHA256SUMS"] = _checksums(payloads)
    packet = _archive(payloads)
    verify_export(packet)
    result = {"version": 2, "format": FORMAT, "attempt_id": attempt.name, "workspace_id": receipt["workspace_id"],
              **hashes, "profile": profile, "patch_bytes": len(patch), "verification_sha256": sha(verification_raw),
              "verification_bytes": len(verification_raw), "archive_sha256": sha(packet), "archive_bytes": len(packet),
              "files": files, "checks": checks, "diff": _diff(patch)}
    _require(len(canonical(result)) <= 65536, "OUTPUT_LIMIT")
    _inventory(snapshot, task["files"])
    _require(all(read_selected(snapshot, name) == value for name, value in selected.items()), "STALE")
    _require(all(_read_named(path, len(raw) or 1) == raw for path, raw in pins.items()), "STALE")
    _no_pending(attempt)
    _require(inspect(job, receipt["creation_sha256"])["summary"] == summary, "STALE")
    return {"summary": result, "patch": patch, "verification": verification, "archive": packet}


def prepare(attempt_dir, expected_receipt_sha256=None):
    """Return deterministic private bytes; no writes, execution, provider or hold access."""
    try:
        return _prepare(attempt_dir, expected_receipt_sha256)
    except (Refused, ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError,
            OverflowError, RecursionError, UnicodeError) as error:
        raise Refused(_error(error)) from None
