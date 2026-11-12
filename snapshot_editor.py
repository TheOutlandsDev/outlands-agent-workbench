"""Exact, explicit edits of selected files in a private snapshot review worktree.

Reads and previews are pure operations on an already verified inspection. Saving
reinspects the trusted single-owner store, retains original/candidate bytes and
replaces one pinned existing file. Sequential guards are not multiwriter CAS.
No check, Git command, provider, worker or hold operation is performed here.
"""

import copy
import os
import re
import stat
from pathlib import Path

from agent import Refused, canonical, relative, review_diff, sha
from bundle_project_check import ReadIssue
from bundle_workspace import _directory
from snapshot_recheck import inspect as inspect_workspace


MAX_FILE, MAX_TOTAL, MAX_DISPLAY, MAX_LINES = 32768, 131072, 8192, 240
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[0-9a-f]{16}\Z")
CODES = frozenset("SNAPSHOT_EDITOR_" + value for value in (
    "INPUT", "SCOPE", "PROTECTED", "STALE", "LIMIT", "OUTPUT_LIMIT", "TEXT_INVALID",
    "SEARCH_REQUIRED", "SEARCH_NOT_UNIQUE", "NO_CHANGE", "RECORD_INVALID",
    "WRITE_FAILED", "WRITE_UNCERTAIN"))
PINS = ("creation_sha256", "request_sha256", "archive_sha256", "task_sha256", "config_sha256",
        "initial_receipt_sha256", "creation_checks_sha256")


def _require(condition, suffix="INPUT"):
    if not condition:
        raise Refused("SNAPSHOT_EDITOR_" + suffix)


def _text(value):
    _require(type(value) is str and "\x00" not in value, "TEXT_INVALID")
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        raise Refused("SNAPSHOT_EDITOR_TEXT_INVALID") from None
    _require(len(raw) <= MAX_FILE, "LIMIT")
    return raw


def _selected(inspected, path):
    _require(type(path) is str, "SCOPE")
    try:
        relative(path)
    except (Refused, ValueError, TypeError):
        raise Refused("SNAPSHOT_EDITOR_SCOPE") from None
    _require(not any(part.startswith(".git") for part in path.split("/")), "SCOPE")
    try:
        summary, task, selected = inspected["summary"], inspected["task"], inspected["selected_bytes"]
        _require(type(summary) is dict and type(task) is dict and type(selected) is dict, "RECORD_INVALID")
        _require(path in task["files"] and path in selected, "SCOPE")
        _require(path in task["editable"], "PROTECTED")
        _require(set(selected) == set(task["files"]) and 1 <= len(selected) <= 32, "RECORD_INVALID")
        _require(all(type(raw) is bytes and len(raw) <= MAX_FILE for raw in selected.values()), "LIMIT")
        _require(sum(map(len, selected.values())) <= MAX_TOTAL, "LIMIT")
        raw = selected[path]
        _text(raw.decode("utf-8"))
        rows = [row for row in summary["files"] if row["path"] == path]
        _require(len(rows) == 1 and rows[0]["editable"] is True and rows[0]["bytes"] == len(raw)
                 and rows[0]["current_sha256"] == sha(raw), "RECORD_INVALID")
        _require(type(summary["workspace_id"]) is str and ID.fullmatch(summary["workspace_id"]) is not None
                 and type(summary["snapshot_sha256"]) is str and HASH.fullmatch(summary["snapshot_sha256"]) is not None,
                 "RECORD_INVALID")
        return raw
    except (KeyError, TypeError, AttributeError, ValueError, UnicodeError, RecursionError):
        raise Refused("SNAPSHOT_EDITOR_RECORD_INVALID") from None


def _line_endings(raw):
    crlf = raw.count(b"\r\n")
    lf, cr = raw.count(b"\n") - crlf, raw.count(b"\r") - crlf
    # A lone CR is deliberately displayed as MIXED, never normalized or hidden.
    if cr or crlf and lf:
        return "MIXED"
    return "CRLF" if crlf else "LF" if lf else "NONE"


def read(inspected, path):
    """Return exact full UTF-8 text for one approved editable existing file."""
    raw = _selected(inspected, path)
    result = {"version": 1, "workspace_id": inspected["summary"]["workspace_id"], "path": path,
              "text": raw.decode("utf-8"), "sha256": sha(raw), "bytes": len(raw),
              "line_endings": _line_endings(raw), "snapshot_sha256": inspected["summary"]["snapshot_sha256"],
              "editable": True, "source_applied": False}
    _require(len(canonical(result)) <= 262144, "OUTPUT_LIMIT")
    return result


def _diff(path, original, candidate):
    text = review_diff(path, original, candidate)
    lines = text.splitlines(keepends=True)
    clipped = len(lines) > MAX_LINES
    raw = "".join(lines[:MAX_LINES]).encode("utf-8")
    if len(raw) > MAX_DISPLAY:
        clipped = True
        text = raw[:MAX_DISPLAY].decode("utf-8", errors="ignore")
    else:
        text = raw.decode("utf-8")
    return {"text": text, "clipped": clipped}


def _summary(inspected, path, original, candidate):
    total = sum(map(len, inspected["selected_bytes"].values())) - len(original) + len(candidate)
    _require(len(candidate) <= MAX_FILE and total <= MAX_TOTAL, "LIMIT")
    _text(candidate.decode("utf-8"))
    result = {"version": 1, "workspace_id": inspected["summary"]["workspace_id"], "path": path,
              "snapshot_sha256": inspected["summary"]["snapshot_sha256"],
              "before_sha256": sha(original), "after_sha256": sha(candidate),
              "before_bytes": len(original), "after_bytes": len(candidate), "total_bytes": total,
              "diff": _diff(path, original, candidate), "source_applied": False, "requires_recheck": True}
    _require(len(canonical(result)) <= 65536, "OUTPUT_LIMIT")
    return result


def prepare(inspected, path, expected_sha256, old_text, new_text):
    """Preview one unique exact byte span. Surrounding bytes remain untouched."""
    original = _selected(inspected, path)
    _require(type(expected_sha256) is str and HASH.fullmatch(expected_sha256) is not None, "INPUT")
    _require(sha(original) == expected_sha256, "STALE")
    old, new = _text(old_text), _text(new_text)
    _require(bool(old), "SEARCH_REQUIRED")
    _require(original.find(old) >= 0 and original.find(old) == original.rfind(old), "SEARCH_NOT_UNIQUE")
    _require(old != new, "NO_CHANGE")
    candidate = original.replace(old, new, 1)
    return {"summary": _summary(inspected, path, original, candidate), "original": original,
            "candidate": candidate, "inspection": copy.deepcopy(inspected["summary"])}


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private_file(info, modes=(0o600, 0o644, 0o664)):
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) in modes, "STALE")


def _target(parent_fd, name, modes=(0o600, 0o644, 0o664)):
    child = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        before = os.fstat(child)
        _private_file(before, modes)
        _require(before.st_size <= MAX_FILE, "LIMIT")
        with os.fdopen(child, "rb", closefd=False) as stream:
            raw = stream.read(MAX_FILE + 1)
        after = os.fstat(child)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_identity(before) == _identity(after) == _identity(named)
                 and len(raw) == before.st_size, "STALE")
        return before, raw
    finally:
        os.close(child)


def _stage(fd, name, raw, mode=0o600):
    child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(child, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())


def _expected_after(inspected, path, candidate):
    result = copy.deepcopy(inspected)
    for row in result["files"]:
        if row["path"] == path:
            row.update(current_sha256=sha(candidate), bytes=len(candidate), changed=sha(candidate) != row["created_sha256"])
    result["total_bytes"] = sum(row["bytes"] for row in result["files"])
    result["changed_files"] = sum(row["changed"] for row in result["files"])
    snapshot = {"files": {row["path"]: row["current_sha256"] for row in result["files"]},
                "guards": result["guards"], **{key: result[key] for key in PINS}}
    result["snapshot_sha256"] = sha(canonical(snapshot))
    return result


def save(job, prepared, edit_dir, guard):
    """Save once; retain all partials. Failure after replacement is uncertain.

    ``guard`` performs the controller's final saved-admission/history checks.
    The newly created edit directory must be in DATA/snapshot-workspace-edits/ID.
    Only original.bin, candidate.bin and replacement.next are written here.
    The last file is consumed by the one atomic replacement on success.
    """
    replaced, parent_fd, edit_fd = False, None, None
    try:
        _require(isinstance(job, Path) and isinstance(edit_dir, Path) and callable(guard))
        _require(job.parent.name == "snapshot-workspaces" and ID.fullmatch(job.name) is not None
                 and edit_dir.parent.name == "snapshot-workspace-edits" and ID.fullmatch(edit_dir.name) is not None
                 and edit_dir.parent.parent == job.parent.parent, "SCOPE")
        # Git checkout may create 0644 or host-umask 0664 files. Their verified
        # owner-only job ancestor is the access boundary; preserve those modes.
        private_job = _directory(job, private=True)
        os.close(private_job)
        _require(type(prepared) is dict and set(prepared) == {"summary", "original", "candidate", "inspection"}, "RECORD_INVALID")
        value, original, candidate = prepared["summary"], prepared["original"], prepared["candidate"]
        _require(type(value) is dict and type(original) is bytes and type(candidate) is bytes, "RECORD_INVALID")
        inspected = inspect_workspace(job, prepared["inspection"]["creation_sha256"])
        _require(inspected["summary"] == prepared["inspection"], "STALE")
        path = value["path"]
        _require(_selected(inspected, path) == original and original != candidate, "STALE")
        _require(_summary(inspected, path, original, candidate) == value, "RECORD_INVALID")
        work, pieces = job / "workspace/review", path.split("/")
        parent = work.joinpath(*pieces[:-1])
        parent_fd = _directory(parent)
        parent_info = os.fstat(parent_fd)
        before, current = _target(parent_fd, pieces[-1])
        _require(current == original, "STALE")
        edit_fd = _directory(edit_dir, private=True)
        _require(os.fstat(edit_fd).st_dev == before.st_dev, "WRITE_FAILED")
        _stage(edit_fd, "original.bin", original)
        _stage(edit_fd, "candidate.bin", candidate)
        target_mode = stat.S_IMODE(before.st_mode)
        _stage(edit_fd, "replacement.next", candidate, target_mode)
        os.fsync(edit_fd)
        _require(inspect_workspace(job, prepared["inspection"]["creation_sha256"])["summary"] == prepared["inspection"], "STALE")
        guard()
        # Keep the final target check adjacent to replace. This is still a
        # sequential check, not an atomic compare-and-swap against other writers.
        current_info, current = _target(parent_fd, pieces[-1])
        _require(_identity(current_info) == _identity(before) and current == original, "STALE")
        for name, expected in (("original.bin", original), ("candidate.bin", candidate), ("replacement.next", candidate)):
            _, staged = _target(edit_fd, name, (target_mode,) if name == "replacement.next" else (0o600,))
            _require(staged == expected, "STALE")
        fresh_parent = _directory(parent)
        try:
            info = os.fstat(fresh_parent)
            _require((info.st_dev, info.st_ino) == (parent_info.st_dev, parent_info.st_ino), "STALE")
        finally:
            os.close(fresh_parent)
        fresh_edit = _directory(edit_dir, private=True)
        try:
            here, fresh = os.fstat(edit_fd), os.fstat(fresh_edit)
            _require((here.st_dev, here.st_ino) == (fresh.st_dev, fresh.st_ino), "STALE")
        finally:
            os.close(fresh_edit)
        os.replace("replacement.next", pieces[-1], src_dir_fd=edit_fd, dst_dir_fd=parent_fd)
        replaced = True
        os.fsync(parent_fd)
        os.fsync(edit_fd)
        _, current = _target(parent_fd, pieces[-1])
        _require(current == candidate, "WRITE_UNCERTAIN")
        after = inspect_workspace(job, prepared["inspection"]["creation_sha256"])["summary"]
        _require(after == _expected_after(prepared["inspection"], path, candidate), "WRITE_UNCERTAIN")
        return {"path": path, "before_sha256": sha(original), "after_sha256": sha(candidate),
                "snapshot_sha256": after["snapshot_sha256"], "source_applied": False, "requires_recheck": True}
    except (Refused, ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError,
            UnicodeError, RecursionError, KeyboardInterrupt, SystemExit) as error:
        if replaced:
            raise Refused("SNAPSHOT_EDITOR_WRITE_UNCERTAIN") from None
        code = str(error) if isinstance(error, Refused) else None
        raise Refused(code if code in CODES else "SNAPSHOT_EDITOR_WRITE_FAILED") from None
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        if edit_fd is not None:
            os.close(edit_fd)
