"""Pure, advisory summaries of bounded static project observations."""

import json
import re

from agent import Refused, validate_task


MAX_SAFE = 9_007_199_254_740_991
HASH = re.compile(r"[0-9a-f]{64}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
FINGERPRINT_STATUSES = frozenset({"MATCH", "CHANGED", "MISSING", "UNREADABLE", "LIMIT"})
FILE_STATUSES = FINGERPRINT_STATUSES | {"BINARY", "UTF8", "NOT_CHECKED"}
PREREQUISITE_IDS = ("python", "git", "bwrap", "prlimit", "jdk")
PREREQUISITE_STATUSES = frozenset({"AVAILABLE", "MISSING", "NOT_CONFIGURED", "NOT_REQUIRED", "NOT_CHECKED"})
INSPECTION_REASONS = frozenset({"CONFIG_CHANGED", "CONFIG_UNREADABLE", "TASK_CHANGED", "TASK_UNREADABLE",
    "DEFINITION_INVALID", "HOLD_UNREADABLE", "ADMISSION_RECORD_INVALID", "ADMISSION_RECORD_LIMIT", "ADMISSION_UNAVAILABLE"})
BLOCK_REASONS = frozenset({"SOURCE_MISSING", "SOURCE_UNREADABLE", "FILE_LIMIT", "TOTAL_INPUT_LIMIT",
    "BINARY_INPUT", "INVALID_UTF8", "PREREQUISITE_MISSING", "JDK_NOT_CONFIGURED", "HOLD_PRESENT",
    "TASK_ACTIVE_OR_UNRESOLVED", "TASK_UNCERTAIN", "WORKSPACE_ACTIVE_OR_UNRESOLVED"})
REASONS = INSPECTION_REASONS | BLOCK_REASONS | {"SOURCE_CHANGED"}
ADMISSION_REASONS = frozenset({"HOLD_PRESENT", "HOLD_UNREADABLE", "TASK_ACTIVE_OR_UNRESOLVED",
    "TASK_UNCERTAIN", "WORKSPACE_ACTIVE_OR_UNRESOLVED", "ADMISSION_RECORD_INVALID",
    "ADMISSION_RECORD_LIMIT", "ADMISSION_UNAVAILABLE"})
NOT_CHECKED = ("PROVIDER_AVAILABILITY", "CHECK_EXECUTION", "ISOLATION_CAPABILITY", "JAVA_VERSION",
               "MODEL_CONTEXT_FIT", "PROCESS_OWNERSHIP", "WORKSPACE_FRESHNESS", "SOURCE_CORRECTNESS")


def _hash(value):
    return value if type(value) is str and len(value) == 64 and HASH.fullmatch(value) else None


def _number(value, maximum=MAX_SAFE):
    return value if type(value) is int and 0 <= value <= maximum else None


def _text(value, maximum, reasons):
    if type(value) is not str:
        reasons.add("DEFINITION_INVALID")
        return None
    if not value or len(value) > maximum:
        reasons.add("DEFINITION_INVALID")
        value = value[:maximum]
    try:
        value.encode("utf-8")
    except UnicodeError:
        reasons.add("DEFINITION_INVALID")
        return None
    return value or None


def _definition(value, reasons):
    """Bound structural work before the shared task validator handles semantics."""
    try:
        if (type(value) is not dict or len(value) != 7
                or type(value.get("files")) is not dict or not 1 <= len(value["files"]) <= 32
                or any(type(name) is not str or len(name) > 128 for name in value["files"])
                or any(type(digest) is not str or len(digest) != 64 for digest in value["files"].values())
                or type(value.get("editable")) is not list or len(value["editable"]) > 32
                or any(type(name) is not str or len(name) > 128 for name in value["editable"])
                or type(value.get("checks")) is not dict or not 1 <= len(value["checks"]) <= 4
                or type(value.get("goal")) is not str or len(value["goal"]) > 2000):
            raise Refused("DEFINITION_INVALID")
        for name, spec in value["checks"].items():
            if type(name) is not str or len(name) > 32:
                raise Refused("DEFINITION_INVALID")
            if type(spec) is dict:
                if len(spec) > 3:
                    raise Refused("DEFINITION_INVALID")
                sources = spec.get("sources", [])
                if (type(sources) is not list or len(sources) > 32
                        or any(type(path) is not str or len(path) > 128 for path in sources)
                        or any(type(spec.get(key)) is not str or len(spec[key]) > 128
                               for key in ("kind", "pattern", "main_class") if key in spec)):
                    raise Refused("DEFINITION_INVALID")
            elif type(spec) is not str or len(spec) > 128:
                raise Refused("DEFINITION_INVALID")
        validate_task(value)
        value["goal"].encode("utf-8")
        return value
    except (Refused, TypeError, ValueError, AttributeError, RecursionError):
        reasons.add("DEFINITION_INVALID")
        return None


def _fingerprint(raw, label, reasons):
    raw = raw if type(raw) is dict else {}
    expected, actual = _hash(raw.get("expected_sha256")), _hash(raw.get("sha256"))
    status = raw.get("status")
    if type(status) is not str or len(status) > 16 or status not in FINGERPRINT_STATUSES or expected is None:
        status = "UNREADABLE"
    if status in {"MATCH", "CHANGED"}:
        if actual is None or (status == "CHANGED" and actual == expected):
            status = "UNREADABLE"
        else:
            status = "MATCH" if actual == expected else "CHANGED"
    if status not in {"MATCH", "CHANGED"}:
        actual = None
    if status != "MATCH":
        reasons.add(label + ("_CHANGED" if status == "CHANGED" else "_UNREADABLE"))
    return {"expected_sha256": expected, "sha256": actual, "status": status}


def _files(raw_rows, task, may_read, reasons):
    if task is None:
        return []
    rows = {}
    if type(raw_rows) is not list:
        reasons.add("DEFINITION_INVALID")
        raw_rows = []
    if len(raw_rows) > 32:
        reasons.update({"FILE_LIMIT", "DEFINITION_INVALID"})
    for row in raw_rows[:32]:
        if (type(row) is not dict or type(row.get("path")) is not str or len(row["path"]) > 128
                or row["path"] not in task["files"]):
            reasons.add("DEFINITION_INVALID")
            continue
        path = row["path"]
        if path in rows:
            reasons.add("DEFINITION_INVALID")
            rows[path] = None
        else:
            rows[path] = row
    output = []
    for path in sorted(task["files"]):
        expected = task["files"][path]
        editable = path in task["editable"]
        row = rows.get(path)
        item = {"path": path, "editable": editable, "expected_sha256": expected,
                "sha256": None, "bytes": None, "status": "NOT_CHECKED"}
        if not may_read:
            output.append(item)
            continue
        if row is None:
            reasons.add("SOURCE_UNREADABLE")
            output.append(item)
            continue
        if (type(row.get("editable")) is not bool or row["editable"] != editable
                or _hash(row.get("expected_sha256")) != expected):
            reasons.update({"DEFINITION_INVALID", "SOURCE_UNREADABLE"})
            output.append(item)
            continue
        status = row.get("status")
        if type(status) is not str or len(status) > 16 or status not in FILE_STATUSES:
            status = "UNREADABLE"
        size = _number(row.get("bytes"))
        actual = _hash(row.get("sha256"))
        if status in {"MATCH", "CHANGED"}:
            if size is None or actual is None or (status == "CHANGED" and actual == expected):
                status = "UNREADABLE"
            else:
                status = "MATCH" if actual == expected else "CHANGED"
        if size is not None and size > 32768:
            status = "LIMIT"
        if status == "MISSING":
            size = None
        if status not in {"MATCH", "CHANGED"}:
            actual = None
        reason = {"CHANGED": "SOURCE_CHANGED", "MISSING": "SOURCE_MISSING",
                  "UNREADABLE": "SOURCE_UNREADABLE", "NOT_CHECKED": "SOURCE_UNREADABLE",
                  "LIMIT": "FILE_LIMIT", "BINARY": "BINARY_INPUT", "UTF8": "INVALID_UTF8"}.get(status)
        if reason:
            reasons.add(reason)
        item.update(sha256=actual, bytes=size, status=status)
        output.append(item)
    return output


def _prerequisites(raw_rows, task, reasons):
    rows = {}
    if type(raw_rows) is not list or len(raw_rows) != len(PREREQUISITE_IDS):
        reasons.add("DEFINITION_INVALID")
    if type(raw_rows) is list:
        for row in raw_rows[:len(PREREQUISITE_IDS)]:
            if (type(row) is not dict or type(row.get("id")) is not str or len(row["id"]) > 16
                    or row["id"] not in PREREQUISITE_IDS):
                reasons.add("DEFINITION_INVALID")
                continue
            if row["id"] in rows:
                reasons.add("DEFINITION_INVALID")
                rows[row["id"]] = None
            else:
                rows[row["id"]] = row
    java = task is not None and any(isinstance(spec, dict) and spec["kind"] == "java-main"
                                   for spec in task["checks"].values())
    output = []
    for identifier in PREREQUISITE_IDS:
        required = identifier in {"python", "bwrap", "prlimit"} or identifier == "jdk" and java
        row = rows.get(identifier)
        if row is None or type(row.get("required")) is not bool or row["required"] != required:
            reasons.add("DEFINITION_INVALID")
        status = row.get("status") if row is not None else "NOT_CHECKED"
        if type(status) is not str or len(status) > 16 or status not in PREREQUISITE_STATUSES:
            reasons.add("DEFINITION_INVALID")
            status = "NOT_CHECKED"
        if required and status != "AVAILABLE":
            reasons.add("JDK_NOT_CONFIGURED" if identifier == "jdk" and status == "NOT_CONFIGURED"
                        else "PREREQUISITE_MISSING")
        output.append({"id": identifier, "required": required, "status": status})
    return output


def _admission(raw, reasons):
    observed = set()
    if type(raw) is not dict:
        observed.add("ADMISSION_UNAVAILABLE")
        raw = {}
    hold = raw.get("hold")
    if type(hold) is not str or len(hold) > 16 or hold not in {"ABSENT", "PRESENT", "UNAVAILABLE"}:
        hold = "UNAVAILABLE"
        observed.add("ADMISSION_UNAVAILABLE")
    if hold == "PRESENT":
        observed.add("HOLD_PRESENT")
    elif hold == "UNAVAILABLE":
        observed.add("HOLD_UNREADABLE")
    counts = {}
    for key in ("jobs_inspected", "workspaces_inspected"):
        value = raw.get(key)
        counts[key] = _number(value, 200)
        if counts[key] is None:
            observed.add("ADMISSION_RECORD_LIMIT" if type(value) is int and value > 200 else "ADMISSION_RECORD_INVALID")
    if (counts["jobs_inspected"] is not None and counts["workspaces_inspected"] is not None
            and counts["workspaces_inspected"] > counts["jobs_inspected"]):
        observed.add("ADMISSION_RECORD_INVALID")
    truncated = raw.get("truncated")
    if type(truncated) is not bool:
        truncated = True
        observed.add("ADMISSION_RECORD_INVALID")
    if truncated:
        observed.add("ADMISSION_RECORD_LIMIT")
    codes = raw.get("reasons")
    if type(codes) is not list or len(codes) > 32:
        observed.add("ADMISSION_RECORD_INVALID")
        codes = codes[:32] if type(codes) is list else []
    for code in codes:
        if type(code) is str and len(code) <= 64 and code in ADMISSION_REASONS:
            observed.add(code)
        else:
            observed.add("ADMISSION_RECORD_INVALID")
    reasons.update(observed)
    return {"hold": hold, **counts, "truncated": truncated, "reasons": sorted(observed)}


def _spec(value):
    if isinstance(value, str):
        return value
    if value["kind"] == "python-unittest":
        return {"kind": "python-unittest", "pattern": value["pattern"]}
    return {"kind": "java-main", "sources": list(value["sources"]), "main_class": value["main_class"]}


def summarize(snapshot):
    """Summarize supplied static evidence without reading or reconciling anything."""
    reasons = set()
    if type(snapshot) is not dict:
        snapshot = {}
        reasons.add("DEFINITION_INVALID")
    project = _text(snapshot.get("project"), 32, reasons)
    if project is not None and ALIAS.fullmatch(project) is None:
        project = None
        reasons.add("DEFINITION_INVALID")
    name = _text(snapshot.get("name"), 80, reasons)
    checked_at = _number(snapshot.get("checked_at_ms"), 8_640_000_000_000_000)
    if checked_at is None:
        reasons.add("DEFINITION_INVALID")
    supplied = snapshot.get("notes", [])
    if type(supplied) is not list or len(supplied) > 32:
        reasons.add("DEFINITION_INVALID")
        supplied = supplied[:32] if type(supplied) is list else []
    for code in supplied:
        if type(code) is str and len(code) <= 64 and code in REASONS:
            reasons.add(code)
        else:
            reasons.add("DEFINITION_INVALID")
    task = _definition(snapshot.get("definition"), reasons)
    config = _fingerprint(snapshot.get("config"), "CONFIG", reasons)
    task_fingerprint = _fingerprint(snapshot.get("task"), "TASK", reasons)
    may_read = config["status"] == task_fingerprint["status"] == "MATCH"
    files = _files(snapshot.get("files"), task, may_read, reasons)
    total = sum(row["bytes"] for row in files) if task is not None and files and all(row["bytes"] is not None for row in files) else None
    if total is not None and total > 131072:
        reasons.add("TOTAL_INPUT_LIMIT")
    prerequisites = _prerequisites(snapshot.get("prerequisites"), task, reasons)
    admission = _admission(snapshot.get("admission"), reasons)
    if reasons & INSPECTION_REASONS:
        status = "NEEDS_INSPECTION"
    elif reasons & BLOCK_REASONS:
        status = "BLOCKED"
    elif reasons == {"SOURCE_CHANGED"}:
        status = "REFRESH_REQUIRED"
    elif not reasons:
        status = "STATIC_CHECKS_PASSED"
    else:
        status = "NEEDS_INSPECTION"
    result = {"version": 1, "project": project, "name": name, "checked_at_ms": checked_at,
        "status": status, "goal": task["goal"] if task else None,
        "fingerprints": {"config": config, "task": task_fingerprint}, "files": files,
        "total_bytes": total, "limits": {"max_files": 32, "max_file_bytes": 32768,
            "max_total_bytes": 131072, "max_turns": task["max_turns"] if task else None,
            "request_seconds": task["request_seconds"] if task else None},
        "checks": [{"name": name, "spec": _spec(spec)} for name, spec in sorted(task["checks"].items())] if task else [],
        "prerequisites": prerequisites, "admission": admission,
        "reasons": sorted(reasons), "not_checked": list(NOT_CHECKED)}
    if len((json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")) > 131072:
        raise Refused("READINESS_OUTPUT_LIMIT")
    return result
