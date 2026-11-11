"""Read-only exports of exact verified workspace snapshots; no execution or extraction."""

import copy
import io
import json
import os
import re
import stat
import struct
import sys
import zipfile
import zlib
from pathlib import Path

from agent import Refused, canonical, object_pairs, review_diff, sha, validate_task
from bundle_project_check import ReadIssue, _path, _read_named, read_selected
from bundle_workspace import _apply, _check_results, _directory, _lines, prepare as prepare_bundle
from git_workspace import validate_files
from workspace_recheck import REQUEST_FIELDS, _history_receipt, _inventory, inspect


FORMAT = "outlands-reviewed-snapshot-export-v1"
MAX_ARCHIVE, MAX_PATCH, MAX_JSON, MAX_FULL = 2097152, 1048576, 262144, 2097152
MAX_FILE, MAX_TOTAL, MAX_SAFE = 32768, 131072, 9007199254740991
MEMBERS = ("changes.diff", "verification.json", "README.txt", "SHA256SUMS")
PERMISSIONS = (stat.S_IFREG | 0o600) << 16
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[0-9a-f]{16}\Z")
CODES = frozenset("SNAPSHOT_EXPORT_" + suffix for suffix in (
    "INPUT", "RECORD_INVALID", "LIMIT", "OUTPUT_LIMIT", "VERIFIED_REQUIRED", "STALE",
    "PROTECTED_CHANGED", "NO_CHANGES", "PATCH_INVALID", "CHECKS_INVALID", "ARCHIVE_INVALID", "ARCHIVE_CHANGED"))
HASH_FIELDS = {"receipt_sha256", "request_sha256", "creation_sha256", "snapshot_sha256", "task_sha256",
               "config_sha256", "bundle_sha256", "checks_sha256", "initial_receipt_sha256", "patch_sha256"}
CORE = ("exit_code", "tests_ran", "timed_out", "output_limited", "infrastructure_error")
INITIAL_FIELDS = {"version", "format", "id", "workspace_id", "status", "created", "source_applied",
                  "workspace_modified", "creation_sha256", "preview_sha256", "history_sha256"}
RECEIPT_FIELDS = INITIAL_FIELDS | {"finished", "checks", "snapshot_sha256", "checked_files", "task_sha256",
                                   "bundle_sha256", "config_sha256", "checks_sha256"}
NOT_CHECKED = ["CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "GIT_ADOPTION", "AUTHENTICITY"]
NOTES = ["PRIVATE_SOURCE_CONTENT", "RECORDED_CHECKS_ONLY", "UNSIGNED_INTEGRITY", "NO_AGENT_RUN_CLAIM"]
README = (
    "OUTLANDS reviewed snapshot export\n\n"
    "PRIVATE SOURCE CONTENT: this patch, relative file names and configured check\n"
    "specifications can contain private project information. Keep this packet private.\n\n"
    "The patch compares the approved selected baseline with the exact saved snapshot\n"
    "of a VERIFIED workspace recheck. It includes imported bundle changes and any\n"
    "selected editable manual changes present in that checked snapshot.\n"
    "Verification contains recorded passing check observations, not check output,\n"
    "a new check execution, a model run, or a provider-completion claim. Original\n"
    "records are represented by hashes only and are not included or authenticated.\n\n"
    "Explicit local review acceptance is stored separately and binds the exact\n"
    "archive SHA256; this packet contains no human-acceptance assertion. Embedded\n"
    "checksums provide unsigned integrity, not authenticity. Compare an independently\n"
    "trusted whole-archive SHA256 when available. No source correctness or Git\n"
    "adoption is established. Inspect scope and baseline hashes before manual use.\n"
    "The verifier never extracts, applies, executes, contacts a provider, changes\n"
    "source/workspaces, reconciles state, or changes holds.\n"
).encode("ascii")


def _require(condition, suffix="RECORD_INVALID"):
    if not condition:
        raise Refused("SNAPSHOT_EXPORT_" + suffix)


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _integer(value, low=0):
    return type(value) is int and low <= value <= MAX_SAFE


def _schema(value, keys, suffix="ARCHIVE_INVALID"):
    _require(type(value) is dict and set(value) == set(keys), suffix)


def _error(error, default="RECORD_INVALID"):
    if isinstance(error, Refused) and str(error) in CODES:
        return str(error)
    if isinstance(error, ReadIssue) and str(error) == "LIMIT":
        return "SNAPSHOT_EXPORT_LIMIT"
    return "SNAPSHOT_EXPORT_" + default


def _json(raw, limit=MAX_JSON, suffix="RECORD_INVALID"):
    _require(type(raw) is bytes and len(raw) <= limit, "LIMIT")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(type(value) is dict, suffix)
        return value
    except (UnicodeError, ValueError, RecursionError, Refused):
        raise Refused("SNAPSHOT_EXPORT_" + suffix) from None


def _checks(raw, receipt, task):
    value = _json(raw, MAX_FULL, "CHECKS_INVALID")
    full, display, passed = _check_results(value, task)
    _require(passed and canonical(full) == raw and receipt.get("checks") == display
             and sha(raw) == receipt.get("checks_sha256"), "CHECKS_INVALID")
    return [{"name": name, "spec": copy.deepcopy(task["checks"][name]),
             "observation": {key: full[name][key] for key in CORE}} for name in sorted(task["checks"])]


def _checksums(payloads):
    return "".join(sha(payloads[name]) + "  " + name + "\n"
                   for name in sorted(MEMBERS) if name != "SHA256SUMS").encode("ascii")


def _archive(payloads):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.create_version = info.extract_version = 20
            info.external_attr, info.internal_attr = PERMISSIONS, 0
            info.compress_type = zipfile.ZIP_STORED
            info.extra = info.comment = b""
            archive.writestr(info, payloads[name])
    raw = stream.getvalue()
    _require(len(raw) <= MAX_ARCHIVE, "LIMIT")
    return raw


def _members(raw):
    """Prebound every fixed stored ZIP record before reading any payload metadata."""
    _require(type(raw) is bytes, "INPUT")
    _require(len(raw) <= MAX_ARCHIVE, "LIMIT")
    _require(len(raw) >= 22, "ARCHIVE_INVALID")
    end = struct.unpack_from("<4s4H2IH", raw, len(raw) - 22)
    _require(end[0] == b"PK\x05\x06" and end[1:5] == (0, 0, 4, 4) and end[7] == 0, "ARCHIVE_INVALID")
    directory_size, directory_start = end[5], end[6]
    _require(directory_size == sum(46 + len(name) for name in MEMBERS)
             and directory_start + directory_size == len(raw) - 22, "ARCHIVE_INVALID")
    cursor, next_local, payloads = directory_start, 0, {}
    for name in MEMBERS:
        _require(cursor + 46 <= len(raw) - 22, "ARCHIVE_INVALID")
        central = struct.unpack_from("<4s6H3I5H2I", raw, cursor)
        encoded = name.encode("ascii")
        _require(central[0] == b"PK\x01\x02" and central[1:7] == (788, 20, 0, 0, 0, 33)
                 and central[8] == central[9] and central[10:15] == (len(encoded), 0, 0, 0, 0)
                 and central[15] == PERMISSIONS and central[16] == next_local, "ARCHIVE_INVALID")
        size, checksum = central[9], central[7]
        limit = MAX_PATCH if name == "changes.diff" else MAX_JSON if name == "verification.json" else len(README) if name == "README.txt" else 512
        _require(size <= limit, "LIMIT")
        _require(raw[cursor + 46:cursor + 46 + len(encoded)] == encoded
                 and next_local + 30 + len(encoded) + size <= directory_start, "ARCHIVE_INVALID")
        local = struct.unpack_from("<4s5H3I2H", raw, next_local)
        _require(local == (b"PK\x03\x04", 20, 0, 0, 0, 33, checksum, size, size, len(encoded), 0), "ARCHIVE_INVALID")
        start = next_local + 30 + len(encoded)
        _require(raw[next_local + 30:start] == encoded, "ARCHIVE_INVALID")
        payload = raw[start:start + size]
        _require(zlib.crc32(payload) & 0xffffffff == checksum, "ARCHIVE_INVALID")
        payloads[name] = payload
        next_local, cursor = start + size, cursor + 46 + len(encoded)
    _require(next_local == directory_start and cursor == len(raw) - 22, "ARCHIVE_INVALID")
    return payloads


def _patch_structure(raw, files):
    """Check finite unified-diff syntax/scope; absent baseline bytes cannot prove applicability."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PATCH, "PATCH_INVALID")
    _require(b"\x00" not in raw and raw.endswith(b"\n"), "PATCH_INVALID")
    _lines(raw)
    lines = [line + b"\n" for line in raw.split(b"\n")[:-1]]
    cursor = 0
    for row in files:
        if not row["changed"]:
            continue
        name = row["path"]
        _require(row["editable"] and lines[cursor:cursor + 2] == [b"--- a/" + name.encode() + b"\n", b"+++ b/" + name.encode() + b"\n"], "PATCH_INVALID")
        cursor += 2
        hunks, previous_old, previous_new, old_ended, new_ended = 0, 0, 0, False, False
        while cursor < len(lines) and lines[cursor].startswith(b"@@ "):
            match = re.fullmatch(rb"@@ -(0|[1-9][0-9]{0,5})(?:,([0-9]{1,6}))? \+(0|[1-9][0-9]{0,5})(?:,([0-9]{1,6}))? @@\n", lines[cursor])
            _require(match is not None, "PATCH_INVALID")
            old, old_count, new, new_count = int(match[1]), int(match[2] or b"1"), int(match[3]), int(match[4] or b"1")
            old_index, new_index = old - bool(old_count), new - bool(new_count)
            _require(max(old, old_count, new, new_count) <= MAX_FILE + 1 and old_index >= previous_old
                     and new_index >= previous_new and (old_count == 0 or old > 0) and (new_count == 0 or new > 0)
                     and old_index - previous_old == new_index - previous_new and (old_count or new_count)
                     and not old_ended and not new_ended, "PATCH_INVALID")
            cursor += 1
            used_old, used_new, edits = 0, 0, 0
            while used_old < old_count or used_new < new_count:
                _require(cursor < len(lines) and lines[cursor][:1] in {b" ", b"-", b"+"}, "PATCH_INVALID")
                kind = lines[cursor][:1]
                _require((kind == b"+" or not old_ended) and (kind == b"-" or not new_ended), "PATCH_INVALID")
                used_old += kind != b"+"
                used_new += kind != b"-"
                edits += kind != b" "
                _require(used_old <= old_count and used_new <= new_count, "PATCH_INVALID")
                cursor += 1
                if cursor < len(lines) and lines[cursor] == b"\\ No newline at end of file\n":
                    old_ended = old_ended or kind != b"+"
                    new_ended = new_ended or kind != b"-"
                    cursor += 1
            _require(edits > 0, "PATCH_INVALID")
            previous_old, previous_new = old_index + old_count, new_index + new_count
            hunks += 1
        _require(hunks > 0, "PATCH_INVALID")
    _require(cursor == len(lines), "PATCH_INVALID")


def _verification(value, patch):
    _schema(value, {"version", "format", "evidence", "hashes", "profile", "files", "checks",
                    "source_applied", "workspace_modified", "not_checked", "notes"})
    _require(type(value["version"]) is int and value["version"] == 1 and value["format"] == FORMAT
             and value["evidence"] == "RECORDED_PASSING_WORKSPACE_RECHECK" and value["source_applied"] is False
             and value["workspace_modified"] is False and value["not_checked"] == NOT_CHECKED and value["notes"] == NOTES, "ARCHIVE_INVALID")
    hashes, profile, files, checks = value["hashes"], value["profile"], value["files"], value["checks"]
    _schema(hashes, HASH_FIELDS)
    _require(all(_hash(digest) for digest in hashes.values()) and hashes["patch_sha256"] == sha(patch), "ARCHIVE_INVALID")
    _schema(profile, {"format", "max_turns", "request_seconds"})
    _require(type(files) is list and 1 <= len(files) <= 32 and type(checks) is list and 1 <= len(checks) <= 4, "ARCHIVE_INVALID")
    before, editable, names, specs = {}, [], [], {}
    for row in files:
        _schema(row, {"path", "editable", "baseline_sha256", "snapshot_sha256", "changed"})
        _require(type(row["path"]) is str and len(row["path"]) <= 128 and row["path"] not in before
                 and type(row["editable"]) is bool and type(row["changed"]) is bool
                 and _hash(row["baseline_sha256"]) and _hash(row["snapshot_sha256"])
                 and row["changed"] == (row["baseline_sha256"] != row["snapshot_sha256"])
                 and (row["editable"] or not row["changed"]), "ARCHIVE_INVALID")
        names.append(row["path"])
        before[row["path"]] = row["baseline_sha256"]
        if row["editable"]:
            editable.append(row["path"])
    _require(names == sorted(names) and any(row["changed"] for row in files), "ARCHIVE_INVALID")
    for row in checks:
        _schema(row, {"name", "spec", "observation"})
        _require(type(row["name"]) is str and row["name"] not in specs, "ARCHIVE_INVALID")
        specs[row["name"]] = row["spec"]
        observed = row["observation"]
        _schema(observed, CORE)
        _require(type(observed["exit_code"]) is int and observed["exit_code"] == 0
                 and _integer(observed["tests_ran"], 1) and all(observed[key] is False for key in CORE[2:]), "ARCHIVE_INVALID")
    _require([row["name"] for row in checks] == sorted(specs), "ARCHIVE_INVALID")
    _require(type(profile["max_turns"]) is int and type(profile["request_seconds"]) is int, "ARCHIVE_INVALID")
    task = {**profile, "goal": "Inspect a saved snapshot export.", "files": before, "editable": editable, "checks": specs}
    validate_task(task)
    validate_files(task)
    _patch_structure(patch, files)


def verify_export(raw, expected_sha256=None):
    """Validate fixed archive framing and recorded claims without extracting or executing."""
    try:
        _require(expected_sha256 is None or _hash(expected_sha256), "INPUT")
        payloads = _members(raw)
        digest = sha(raw)
        _require(expected_sha256 is None or digest == expected_sha256, "ARCHIVE_CHANGED")
        _require(payloads["README.txt"] == README and payloads["SHA256SUMS"] == _checksums(payloads), "ARCHIVE_INVALID")
        verification = _json(payloads["verification.json"], suffix="ARCHIVE_INVALID")
        _verification(verification, payloads["changes.diff"])
        _require(canonical(verification) == payloads["verification.json"] and _archive(payloads) == raw, "ARCHIVE_INVALID")
        summary = {"version": 1, "format": FORMAT, "archive_sha256": digest, "archive_bytes": len(raw),
            "patch_sha256": sha(payloads["changes.diff"]), "patch_bytes": len(payloads["changes.diff"]),
            "verification_sha256": sha(payloads["verification.json"]), "verification_bytes": len(payloads["verification.json"]),
            "member_count": 4, "members": [{"path": name, "bytes": len(payloads[name]), "sha256": sha(payloads[name])} for name in MEMBERS],
            **{key: copy.deepcopy(verification[key]) for key in ("hashes", "profile", "files", "checks", "not_checked", "notes")}}
        _require(len(canonical(summary)) <= 65536, "OUTPUT_LIMIT")
        return summary
    except (Refused, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, struct.error, UnicodeError) as error:
        raise Refused(_error(error, "ARCHIVE_INVALID")) from None


def _diff(raw):
    lines = raw.splitlines(keepends=True)
    clipped = b"".join(lines[:240])[:8192]
    text = clipped.decode("utf-8", errors="ignore")
    return {"text": text, "truncated": len(text.encode("utf-8")) != len(raw), "bytes": len(raw), "lines": len(lines)}


def _prepare(attempt, expected_receipt_sha256):
    _require(isinstance(attempt, Path), "INPUT")
    _path(attempt)
    fd = _directory(attempt, private=True)
    os.close(fd)
    _require(ID.fullmatch(attempt.name) is not None and attempt.parent.name == "workspace-rechecks", "INPUT")
    _require(expected_receipt_sha256 is None or _hash(expected_receipt_sha256), "INPUT")
    pins = {}
    def read(path, limit=MAX_JSON, text=True):
        raw = _read_named(path, limit, text=text)
        pins[path] = raw
        return raw
    receipt_raw = read(attempt / "receipt.json")
    _require(expected_receipt_sha256 is None or sha(receipt_raw) == expected_receipt_sha256, "STALE")
    receipt = _json(receipt_raw)
    _require(receipt.get("status") == "VERIFIED", "VERIFIED_REQUIRED")
    _schema(receipt, RECEIPT_FIELDS, "RECORD_INVALID")
    _history_receipt(receipt, attempt.name)
    _require(_integer(receipt["finished"]) and receipt["finished"] >= receipt["created"]
             and all(_hash(receipt[key]) for key in ("snapshot_sha256", "task_sha256", "bundle_sha256", "config_sha256", "checks_sha256")))
    request_raw, initial_raw = read(attempt / "request.json"), read(attempt / "initial-receipt.json")
    request, initial = _json(request_raw), _json(initial_raw)
    _schema(request, REQUEST_FIELDS, "RECORD_INVALID")
    _schema(initial, INITIAL_FIELDS, "RECORD_INVALID")
    _history_receipt(initial, attempt.name)
    _require(initial["status"] == "PREPARING" and initial["created"] == receipt["created"]
             and type(request["version"]) is int and request["version"] == 1
             and all(request[key] == receipt[key] == initial[key] for key in
                     ("id", "workspace_id", "creation_sha256", "preview_sha256", "history_sha256")))
    job = attempt.parent.parent / "bundle-workspaces" / receipt["workspace_id"]
    _require(type(request["job_dir"]) is str and request["job_dir"] == str(job))
    inspected = inspect(job, receipt["creation_sha256"])
    summary, task, current = inspected["summary"], inspected["task"], inspected["selected_bytes"]
    _require(summary["snapshot_sha256"] == receipt["snapshot_sha256"] and all(summary[key] == receipt[key]
             for key in ("task_sha256", "bundle_sha256", "config_sha256")), "STALE")
    _require(sha(canonical({"inspection": summary, "history_sha256": request["history_sha256"]})) == request["preview_sha256"], "STALE")
    task_raw = read(attempt / "task.json")
    _require(sha(task_raw) == receipt["task_sha256"] and read(job / "task.json") == task_raw, "STALE")
    creation_request_raw = read(job / "request.json", 32768)
    _require(sha(creation_request_raw) == summary["request_sha256"], "STALE")
    creation_request = _json(creation_request_raw)
    _require(sha(read(job / "receipt.json")) == receipt["creation_sha256"], "STALE")
    read(job / "checks.json", MAX_FULL)
    bundle = read(job / "bundle.zip", MAX_ARCHIVE, False)
    reconstructed = prepare_bundle(bundle, Path(creation_request["source"]), task_raw, receipt["bundle_sha256"])
    _require(reconstructed["task"] == task, "STALE")
    baseline = reconstructed["baseline"]
    snapshot = attempt / "snapshot"
    _inventory(snapshot, task["files"])
    selected = {name: read_selected(snapshot, name) for name in sorted(task["files"])}
    _require(sum(map(len, selected.values())) <= MAX_TOTAL, "LIMIT")
    checked = {name: sha(value) for name, value in selected.items()}
    _require(type(receipt["checked_files"]) is dict and receipt["checked_files"] == checked and selected == current, "STALE")
    for name in selected:
        _require(name in task["editable"] or selected[name] == baseline[name], "PROTECTED_CHANGED")
        _lines(baseline[name])
        _lines(selected[name])
    checks = _checks(read(attempt / "checks.json", MAX_FULL), receipt, task)
    patch = "".join(review_diff(name, baseline[name], selected[name]) for name in sorted(baseline)).encode("utf-8")
    _require(bool(patch), "NO_CHANGES")
    _require(len(patch) <= MAX_PATCH, "LIMIT")
    changed = [name for name in sorted(baseline) if baseline[name] != selected[name]]
    _require(_apply(patch, baseline, changed) == selected, "PATCH_INVALID")
    files = [{"path": name, "editable": name in task["editable"], "baseline_sha256": sha(baseline[name]),
              "snapshot_sha256": checked[name], "changed": name in changed} for name in sorted(selected)]
    hashes = {key: receipt[key] for key in ("creation_sha256", "snapshot_sha256", "task_sha256", "config_sha256", "bundle_sha256", "checks_sha256")}
    hashes.update(receipt_sha256=sha(receipt_raw), request_sha256=sha(request_raw), initial_receipt_sha256=sha(initial_raw), patch_sha256=sha(patch))
    profile = {key: task[key] for key in ("format", "max_turns", "request_seconds")}
    verification = {"version": 1, "format": FORMAT, "evidence": "RECORDED_PASSING_WORKSPACE_RECHECK",
        "hashes": hashes, "profile": profile, "files": files, "checks": checks, "source_applied": False,
        "workspace_modified": False, "not_checked": list(NOT_CHECKED), "notes": list(NOTES)}
    verification_raw = canonical(verification)
    _require(len(verification_raw) <= MAX_JSON, "OUTPUT_LIMIT")
    payloads = {"changes.diff": patch, "verification.json": verification_raw, "README.txt": README}
    payloads["SHA256SUMS"] = _checksums(payloads)
    archive = _archive(payloads)
    verify_export(archive)
    result = {"version": 1, "format": FORMAT, "attempt_id": attempt.name, "workspace_id": receipt["workspace_id"],
              **hashes, "profile": profile, "patch_bytes": len(patch), "verification_sha256": sha(verification_raw),
              "verification_bytes": len(verification_raw), "archive_sha256": sha(archive), "archive_bytes": len(archive),
              "files": files, "checks": checks, "diff": _diff(patch)}
    _require(len(canonical(result)) <= 65536, "OUTPUT_LIMIT")
    _inventory(snapshot, task["files"])
    _require(all(read_selected(snapshot, name) == value for name, value in selected.items()), "STALE")
    _require(all(_read_named(path, len(raw) or 1) == raw for path, raw in pins.items()), "STALE")
    _require(inspect(job, receipt["creation_sha256"])["summary"] == summary, "STALE")
    return {"summary": result, "patch": patch, "verification": verification, "archive": archive}


def prepare(attempt_dir, expected_receipt_sha256=None):
    """Read a verified attempt and return pinned bytes; never mutate or run checks."""
    try:
        return _prepare(attempt_dir, expected_receipt_sha256)
    except Refused as error:
        code = str(error)
        if code == "RECHECK_PROTECTED_CHANGED":
            code = "SNAPSHOT_EXPORT_PROTECTED_CHANGED"
        elif code == "BUNDLE_WORKSPACE_PATCH_INVALID":
            code = "SNAPSHOT_EXPORT_PATCH_INVALID"
        elif code.startswith("RECHECK_") or code.startswith("BUNDLE_WORKSPACE_"):
            code = "SNAPSHOT_EXPORT_STALE"
        raise Refused(code if code in CODES else "SNAPSHOT_EXPORT_RECORD_INVALID") from None
    except (ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, UnicodeError) as error:
        raise Refused(_error(error)) from None


def main(argv=None):
    """Verify one explicitly named archive, without extraction or project access."""
    try:
        args = sys.argv[1:] if argv is None else argv
        _require(type(args) is list and len(args) in {2, 4} and all(type(arg) is str for arg in args), "INPUT")
        options = {}
        for key, value in zip(args[::2], args[1::2]):
            _require(key in {"--archive", "--expected-sha256"} and key not in options, "INPUT")
            options[key] = value
        _require("--archive" in options, "INPUT")
        path = Path(options["--archive"])
        _path(path)
        raw = _read_named(path, MAX_ARCHIVE)
        result = verify_export(raw, options.get("--expected-sha256"))
        sys.stdout.write(canonical(result).decode("ascii"))
        return 0
    except (Refused, ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError) as error:
        sys.stdout.write(canonical({"error": _error(error, "INPUT")}).decode("ascii"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
