"""Pure search and focused reads over one verified private workspace inspection.

The controller authorizes and rereads the filesystem inspection. These helpers
only inspect supplied bytes, selected scope and pins; they never open a path,
run Git/checks/providers or change a workspace, saved evidence or hold.
"""

import re

from agent import Refused, canonical, relative, sha
from project_context import ContextRefused, read_lines, search_text


MAX_FILES, MAX_FILE, MAX_TOTAL, MAX_OUTPUT = 32, 32768, 131072, 16384
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[0-9a-f]{16}\Z")
PINS = ("creation_sha256", "request_sha256", "archive_sha256", "task_sha256", "config_sha256",
        "initial_receipt_sha256", "creation_checks_sha256")
CODES = frozenset("WORKSPACE_SEARCH_" + suffix for suffix in (
    "INPUT", "QUERY", "SCOPE", "STALE", "RANGE", "LIMIT", "OUTPUT_LIMIT", "RECORD_INVALID", "PROTECTED"))


def _require(condition, suffix="RECORD_INVALID"):
    if not condition:
        raise Refused("WORKSPACE_SEARCH_" + suffix)


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _path(value):
    try:
        _require(type(value) is str, "SCOPE")
        relative(value)
        _require(not any(part.startswith(".git") for part in value.split("/")), "SCOPE")
        return value
    except (Refused, TypeError, ValueError):
        raise Refused("WORKSPACE_SEARCH_SCOPE") from None


def _validated(inspected):
    """Check the supplied inspection envelope, exact scope/bytes and snapshot pin.

    These structural/hash guards do not establish filesystem authorization or
    authenticity. The controller supplies an independently verified inspection.
    """
    try:
        _require(type(inspected) is dict)
        summary, task, selected = inspected["summary"], inspected["task"], inspected["selected_bytes"]
        _require(type(summary) is dict and type(task) is dict and type(selected) is dict)
        _require(type(summary["version"]) is int and summary["version"] == 1
                 and type(summary["workspace_id"]) is str and ID.fullmatch(summary["workspace_id"]) is not None
                 and summary["source_applied"] is False and _hash(summary["snapshot_sha256"]))
        _require(type(task["files"]) is dict and type(task["editable"]) is list)
        _require(1 <= len(selected) <= MAX_FILES, "LIMIT")
        _require(set(selected) == set(task["files"]) and all(_hash(value) for value in task["files"].values()))
        editable = task["editable"]
        _require(all(type(name) is str for name in editable)
                 and len(editable) == len(set(editable)) and set(editable) <= set(selected))
        editable = frozenset(editable)
        for name, raw in selected.items():
            _path(name)
            _require(type(raw) is bytes)
            _require(len(raw) <= MAX_FILE, "LIMIT")
            _require(b"\x00" not in raw)
            raw.decode("utf-8")
        total = sum(map(len, selected.values()))
        _require(total <= MAX_TOTAL, "LIMIT")
        rows = summary["files"]
        _require(type(rows) is list and len(rows) == len(selected))
        names = []
        for row in rows:
            _require(type(row) is dict and set(row) == {
                "path", "editable", "created_sha256", "current_sha256", "bytes", "changed"})
            name = row["path"]
            _require(type(name) is str and name in selected)
            names.append(name)
            current = sha(selected[name])
            _require(type(row["editable"]) is bool and row["editable"] == (name in editable)
                     and _hash(row["created_sha256"]) and _hash(row["current_sha256"])
                     and row["current_sha256"] == current and type(row["bytes"]) is int
                     and row["bytes"] == len(selected[name]) and type(row["changed"]) is bool
                     and row["changed"] == (current != row["created_sha256"]))
            _require(name in editable or current == row["created_sha256"])
        _require(names == sorted(selected) and len(set(names)) == len(selected))
        _require(type(summary["total_bytes"]) is int and summary["total_bytes"] == total
                 and type(summary["changed_files"]) is int
                 and summary["changed_files"] == sum(row["changed"] for row in rows))
        _require(all(_hash(summary[key]) for key in PINS))
        guards = summary["guards"]
        _require(type(guards) is list and 1 <= len(guards) <= 32)
        guard_names = []
        for guard in guards:
            _require(type(guard) is dict and set(guard) == {"path", "sha256", "bytes"})
            relative(guard["path"])
            _require(_hash(guard["sha256"]) and type(guard["bytes"]) is int and 0 <= guard["bytes"] <= 262144)
            guard_names.append(guard["path"])
        _require(guard_names == sorted(set(guard_names)))
        pin = {"files": {row["path"]: row["current_sha256"] for row in rows}, "guards": guards,
               **{key: summary[key] for key in PINS}}
        _require(summary["snapshot_sha256"] == sha(canonical(pin)))
        _require(len(canonical(summary)) <= 65536, "LIMIT")
        return summary, selected, editable
    except Refused as error:
        if str(error) in CODES:
            raise
        raise Refused("WORKSPACE_SEARCH_RECORD_INVALID") from None
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
        raise Refused("WORKSPACE_SEARCH_RECORD_INVALID") from None


def _context_error(error):
    suffix = {"CONTEXT_QUERY": "QUERY", "CONTEXT_RANGE": "RANGE", "CONTEXT_PATH": "SCOPE",
              "CONTEXT_SNAPSHOT_LIMIT": "LIMIT"}.get(str(error), "RECORD_INVALID")
    return Refused("WORKSPACE_SEARCH_" + suffix)


def _output(value):
    _require(len(canonical(value)) <= MAX_OUTPUT, "OUTPUT_LIMIT")
    return value


def _bound(summary, result, **extra):
    return _output({"version": 1, "workspace_id": summary["workspace_id"],
                    "snapshot_sha256": summary["snapshot_sha256"], **extra, "result": result})


def search(inspected, query):
    """Search only the supplied selected bytes; mark every hit's edit permission."""
    summary, selected, editable = _validated(inspected)
    try:
        result = search_text(selected, query)
    except ContextRefused as error:
        raise _context_error(error) from None
    for hit in result["matches"]:
        hit["editable"] = hit["path"] in editable
    # Permission labels count toward the declared helper-result ceiling too.
    # Omitted hits remain counted; order and excerpts are never reconstructed.
    while len(canonical(result)) > result["byte_limit"] and result["matches"]:
        result["matches"].pop()
        result["truncated"] = True
    _require(len(canonical(result)) <= result["byte_limit"], "OUTPUT_LIMIT")
    return _bound(summary, result)


def _selected(inspected, path, expected_sha256, snapshot_sha256):
    summary, selected, editable = _validated(inspected)
    path = _path(path)
    _require(path in selected, "SCOPE")
    _require(_hash(expected_sha256) and _hash(snapshot_sha256), "INPUT")
    _require(summary["snapshot_sha256"] == snapshot_sha256 and sha(selected[path]) == expected_sha256, "STALE")
    return summary, path, selected[path], path in editable


def read(inspected, path, expected_sha256, snapshot_sha256, start_line, end_line):
    """Read one bounded numbered range, including a protected file when selected."""
    summary, path, raw, editable = _selected(inspected, path, expected_sha256, snapshot_sha256)
    try:
        result = read_lines(path, raw, start_line, end_line)
    except ContextRefused as error:
        raise _context_error(error) from None
    return _bound(summary, result, editable=editable)


def validate_open(inspected, path, expected_sha256, snapshot_sha256):
    """Authorize an explicit current-file handoff; this function does not open it."""
    _, path, raw, editable = _selected(inspected, path, expected_sha256, snapshot_sha256)
    _require(editable, "PROTECTED")
    return {"path": path, "sha256": sha(raw), "bytes": len(raw), "editable": True}
