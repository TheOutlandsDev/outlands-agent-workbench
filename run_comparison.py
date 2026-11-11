"""Bounded comparisons of supplied saved-run evidence; no I/O or live-state inference."""

import difflib
import json
import re

from agent import Refused, validate_task
from run_diagnostics import MAX_SAFE, reason, summarize


IDS = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
MODEL = re.compile(r"[A-Za-z0-9_.:/-]{1,96}\Z")
CHECK = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
STATES = frozenset({"RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED", "REVIEW_READY",
                    "FAILED", "REFUSED", "INTERRUPTED", "UNCERTAIN"})
NOTES = frozenset({"RECORD_MISSING", "RECORD_INVALID", "RECORD_LIMIT", "EVENT_LIMIT",
                   "PATCH_TRUNCATED", "LEGACY_TASK_FINGERPRINT", "INCOMPLETE_METRICS",
                   "TASK_FINGERPRINT_MISMATCH", "PATCH_FINGERPRINT_MISMATCH"})
INCOMPLETE = frozenset({"RECORD_MISSING", "RECORD_INVALID", "RECORD_LIMIT", "EVENT_LIMIT",
                        "PATCH_FINGERPRINT_MISMATCH"})


def _note(notes, code):
    if code not in notes:
        notes.append(code)


def _number(value, minimum=0, maximum=MAX_SAFE):
    return value if type(value) is int and minimum <= value <= maximum else None


def _hash(value):
    return value if type(value) is str and len(value) == 64 and HASH.fullmatch(value) else None


def _clip(text, size):
    return text.encode("utf-8")[:size].decode("utf-8", "ignore")


def _display(value, chars, notes, pattern=None):
    if value is None:
        return None
    if type(value) is not str:
        _note(notes, "RECORD_INVALID")
        return None
    if len(value) > chars:
        _note(notes, "RECORD_LIMIT")
        value = value[:chars]
    try:
        value.encode("utf-8")
    except UnicodeError:
        _note(notes, "RECORD_INVALID")
        return None
    if pattern is not None and pattern.fullmatch(value) is None:
        _note(notes, "RECORD_INVALID")
        return None
    return value


def _task(value, notes):
    if value is None:
        _note(notes, "RECORD_MISSING")
        return None
    # Bound structural work before invoking the shared validator. In particular,
    # never traverse arbitrary extra fields or arbitrarily long path collections.
    try:
        if (type(value) is not dict or len(value) != 7
                or type(value.get("files")) is not dict or not 1 <= len(value["files"]) <= 32
                or any(type(n) is not str or len(n) > 128 for n in value["files"])
                or type(value.get("editable")) is not list or len(value["editable"]) > 32
                or any(type(n) is not str or len(n) > 128 for n in value["editable"])
                or type(value.get("checks")) is not dict or len(value["checks"]) > 4
                or type(value.get("goal")) is not str or len(value["goal"]) > 2000):
            raise Refused("COMPARE_RECORD_LIMIT")
        for name, spec in value["checks"].items():
            if type(name) is not str or len(name) > 32:
                raise Refused("COMPARE_RECORD_LIMIT")
            if isinstance(spec, dict):
                if len(spec) > 3:
                    raise Refused("COMPARE_RECORD_LIMIT")
                sources = spec.get("sources", [])
                if (type(sources) is not list or len(sources) > 32
                        or any(type(n) is not str or len(n) > 128 for n in sources)):
                    raise Refused("COMPARE_RECORD_LIMIT")
        validate_task(value)
        value["goal"].encode("utf-8")
        return value
    except Refused as exc:
        _note(notes, "RECORD_LIMIT" if str(exc) == "COMPARE_RECORD_LIMIT" else "RECORD_INVALID")
    except (TypeError, ValueError, AttributeError, RecursionError):
        _note(notes, "RECORD_INVALID")
    return None


def _spec(spec):
    if isinstance(spec, str):
        return spec
    if spec["kind"] == "python-unittest":
        return {"kind": "python-unittest", "pattern": spec["pattern"]}
    return {"kind": "java-main", "sources": list(spec["sources"]), "main_class": spec["main_class"]}


def _check_rows(events, task, event_kind, notes):
    values = [event.get("value") for event in events
              if isinstance(event, dict) and event.get("kind") == event_kind]
    if not values:
        return []
    if len(values) != 1 or type(values[0]) is not dict or len(values[0]) > 4:
        _note(notes, "RECORD_INVALID")
        return []
    rows = []
    for name in sorted(n for n in values[0] if type(n) is str and len(n) <= 32 and CHECK.fullmatch(n)):
        raw = values[0][name]
        if type(raw) is not dict or (task is not None and name not in task["checks"]):
            _note(notes, "RECORD_INVALID")
            continue
        spec = task["checks"].get(name) if task is not None else None
        kind = ("python-unittest" if isinstance(spec, str) else spec["kind"]
                if isinstance(spec, dict) else None)
        row = {"name": name, "kind": kind}
        for key in ("exit_code", "tests_ran", "timed_out", "output_limited", "infrastructure_error"):
            value = raw.get(key)
            cleaned = (value if type(value) is bool else None) if key in {
                "timed_out", "output_limited", "infrastructure_error"} else _number(
                    value, -255 if key == "exit_code" else 0, 255 if key == "exit_code" else MAX_SAFE)
            if value is not None and cleaned is None:
                _note(notes, "RECORD_INVALID")
            row[key] = cleaned
        rows.append(row)
    if len(rows) != len(values[0]):
        _note(notes, "RECORD_INVALID")
    return rows


def _metrics(task, result, events, state, backend, notes):
    diagnostics = summarize(task or {}, result, events, state, backend,
                            owned_active=False, hold_matches=False, hold_present=False)
    diagnostic_notes = set(diagnostics["notes"])
    if "INVALID_DIAGNOSTICS" in diagnostic_notes or "UNRECOGNIZED_REASON" in diagnostic_notes:
        _note(notes, "RECORD_INVALID")
    if "EVENT_LIMIT" in diagnostic_notes:
        _note(notes, "EVENT_LIMIT")
    rows = diagnostics["requests"][:16]
    if rows and [row["turn"] for row in rows] != list(range(1, len(rows) + 1)):
        _note(notes, "RECORD_INVALID")
    if isinstance(result, dict) and result.get("turns") is not None:
        recorded_count = _number(result["turns"], maximum=16)
        if recorded_count is None or recorded_count != len(rows):
            _note(notes, "RECORD_INVALID")
    measured = sum(row["request_bytes"] is not None for row in rows)
    elapsed = sum(row["elapsed_ms"] is not None for row in rows)
    bad = bool({"RECORD_INVALID", "RECORD_LIMIT", "EVENT_LIMIT"}.intersection(notes))
    zero = (not rows and diagnostics["preflight"] is not None and not bad
            and isinstance(result, dict) and result.get("reason") == "REQUEST_SIZE_LIMIT"
            and state in {"FAILED", "REFUSED"} and result.get("status") == state
            and _number(result.get("turns"), maximum=16) == 0
            and not any(isinstance(event, dict) and event.get("kind") in {
                "request_started", "request_finished", "response"} for event in events)
            and sum(isinstance(event, dict) and event.get("kind") == "request_refused" for event in events) == 1
            and not diagnostic_notes.intersection({"INVALID_DIAGNOSTICS", "EVENT_LIMIT", "LEGACY_REQUEST_DETAILS"}))
    count = len(rows) if rows else 0 if zero else None
    byte_total = sum(row["request_bytes"] for row in rows) if not bad and measured == len(rows) and count is not None else None
    elapsed_total = sum(row["elapsed_ms"] for row in rows) if not bad and elapsed == len(rows) and count is not None else None
    if byte_total is not None and byte_total > MAX_SAFE:
        byte_total = None
    if elapsed_total is not None and elapsed_total > MAX_SAFE:
        elapsed_total = None
    complete = (count is not None and byte_total is not None and elapsed_total is not None
                and not diagnostic_notes.intersection({"INVALID_DIAGNOSTICS", "EVENT_LIMIT",
                    "LEGACY_REQUEST_DETAILS", "MISSING_REQUEST_FINISH", "UNRECOGNIZED_REASON"}))
    if not complete:
        _note(notes, "INCOMPLETE_METRICS")
    return {"requests": count, "request_bytes": byte_total, "elapsed_ms": elapsed_total,
            "measured_requests": measured, "elapsed_requests": elapsed, "complete": complete}


def _summary(bundle):
    notes = []
    supplied_notes = bundle.get("notes", [])
    if type(supplied_notes) is list:
        for code in supplied_notes[:64]:
            if type(code) is str and len(code) <= 64 and code in NOTES:
                _note(notes, code)
            else:
                _note(notes, "RECORD_INVALID")
        if len(supplied_notes) > 64:
            _note(notes, "RECORD_LIMIT")
    else:
        _note(notes, "RECORD_INVALID")
    task = _task(bundle.get("task"), notes)
    metadata, result = bundle.get("metadata"), bundle.get("result")
    if type(metadata) is not dict:
        _note(notes, "RECORD_MISSING" if metadata is None else "RECORD_INVALID")
        metadata = {}
    elif metadata.get("id") != bundle["id"]:
        _note(notes, "RECORD_INVALID")
    if type(result) is not dict:
        _note(notes, "RECORD_MISSING" if result is None else "RECORD_INVALID")
        result = {}
    events = bundle.get("events")
    if type(events) is not list:
        _note(notes, "RECORD_MISSING" if events is None else "RECORD_INVALID")
        events = []
    if len(events) > 256:
        _note(notes, "EVENT_LIMIT")
    events = events[:256]
    seen_indexes = set()
    for event in events:
        if (type(event) is not dict or _number(event.get("index")) is None
                or type(event.get("kind")) is not str or not 1 <= len(event["kind"]) <= 64
                or type(event.get("value")) is not dict):
            _note(notes, "RECORD_INVALID")
            continue
        if event["index"] in seen_indexes:
            _note(notes, "RECORD_INVALID")
        seen_indexes.add(event["index"])
    project = _display(metadata.get("project"), 32, notes, ALIAS)
    project_name = _display(metadata.get("project_name"), 80, notes)
    meta_goal = _display(metadata.get("goal"), 2000, notes)
    if project is None or meta_goal is None:
        _note(notes, "RECORD_MISSING")
    if task is not None and meta_goal is not None and task["goal"] != meta_goal:
        _note(notes, "RECORD_INVALID")
    state = metadata.get("state")
    if type(state) is not str or state not in STATES:
        if state is not None:
            _note(notes, "RECORD_INVALID")
        state = None
    backend = metadata.get("backend")
    if type(backend) is not str or backend not in {"ollama", "scripted-demo"}:
        if backend is not None:
            _note(notes, "RECORD_INVALID")
        backend = None
    model = _display(metadata.get("model"), 96, notes, MODEL)
    task_hash = _hash(bundle.get("task_sha256"))
    recorded_hash = _hash(metadata.get("task_sha256"))
    project_hash = _hash(metadata.get("project_task_sha256"))
    if task is None or task_hash is None:
        integrity = "UNAVAILABLE"
        if task_hash is None:
            _note(notes, "RECORD_MISSING" if bundle.get("task_sha256") is None else "RECORD_INVALID")
    elif metadata.get("task_sha256") is None:
        integrity = "NOT_RECORDED"
        _note(notes, "LEGACY_TASK_FINGERPRINT")
    elif recorded_hash is None:
        integrity = "UNAVAILABLE"
        _note(notes, "RECORD_INVALID")
    elif task_hash == recorded_hash:
        integrity = "MATCH"
    else:
        integrity = "MISMATCH"
        _note(notes, "TASK_FINGERPRINT_MISMATCH")
    if metadata.get("project_task_sha256") is not None and project_hash is None:
        _note(notes, "RECORD_INVALID")
    result_hash = _hash(bundle.get("result_sha256"))
    if result and result_hash is None:
        _note(notes, "RECORD_MISSING" if bundle.get("result_sha256") is None else "RECORD_INVALID")
    result_status = result.get("status")
    if type(result_status) is not str or result_status not in STATES:
        if result_status is not None:
            _note(notes, "RECORD_INVALID")
        result_status = None
    result_reason = reason(result.get("reason"))
    if result.get("reason") is not None and result_reason is None:
        _note(notes, "RECORD_INVALID")
    patch = bundle.get("patch")
    if type(patch) is not str:
        _note(notes, "RECORD_MISSING" if patch is None else "RECORD_INVALID")
        patch = None
    else:
        try:
            if len(patch) > 65536 or len(patch.encode("utf-8")) > 65536:
                _note(notes, "RECORD_LIMIT")
                patch = None
        except UnicodeError:
            _note(notes, "RECORD_INVALID")
            patch = None
    patch_hash, recorded_patch = _hash(bundle.get("patch_sha256")), _hash(result.get("patch_sha256"))
    for supplied, cleaned in ((bundle.get("patch_sha256"), patch_hash),
                              (result.get("patch_sha256"), recorded_patch)):
        if supplied is not None and cleaned is None:
            _note(notes, "RECORD_INVALID")
    if patch is not None and patch_hash is None:
        _note(notes, "RECORD_MISSING")
    patch_match = patch_hash == recorded_patch if patch_hash is not None and recorded_patch is not None else None
    if patch_match is False:
        _note(notes, "PATCH_FINGERPRINT_MISMATCH")
    patch_text = _clip(patch, 8192) if patch is not None else None
    patch_truncated = "PATCH_TRUNCATED" in notes or (patch is not None and len(patch_text) != len(patch))
    if patch_truncated:
        _note(notes, "PATCH_TRUNCATED")
    files = ([{"path": path, "sha256": task["files"][path], "editable": path in task["editable"]}
              for path in sorted(task["files"])] if task is not None else [])
    baseline = _check_rows(events, task, "baseline_checks", notes)
    final = _check_rows(events, task, "independent_final_checks", notes)
    metrics = _metrics(task, result, events, state, backend, notes)
    value = {"id": bundle["id"], "project": project, "project_name": project_name,
        "goal": task["goal"] if task is not None else meta_goal, "state": state,
        "backend": backend, "model": model, "created": _number(metadata.get("created")),
        "finished": _number(metadata.get("finished")), "task_sha256": task_hash,
        "recorded_task_sha256": recorded_hash, "project_task_sha256": project_hash,
        "task_integrity": integrity, "files": files,
        "checks": [{"name": name, "spec": _spec(spec)} for name, spec in sorted(task["checks"].items())] if task else [],
        "max_turns": task["max_turns"] if task else None,
        "request_seconds": task["request_seconds"] if task else None,
        "result_status": result_status, "result_reason": result_reason, "result_sha256": result_hash,
        "baseline_checks": baseline, "final_checks": final, "metrics": metrics,
        "patch": {"sha256": patch_hash, "recorded_sha256": recorded_patch,
                  "matches_recorded": patch_match, "text": patch_text, "truncated": patch_truncated},
        "notes": sorted(notes)}
    return value, task, patch


def _patch_difference(left, right):
    if left is None or right is None:
        return {"text": None, "truncated": False}
    chunks = difflib.unified_diff(left.splitlines(keepends=True), right.splitlines(keepends=True),
                                  fromfile="left/changes.diff", tofile="right/changes.diff", n=3)
    pieces, size, line_count, truncated = [], 0, 0, False
    for chunk in chunks:
        if not chunk.endswith("\n"):
            chunk += "\n\\ No newline at end of file\n"
        for line in chunk.splitlines(keepends=True):
            if line_count == 240 or size == 16384:
                truncated = True
                break
            clipped = _clip(line, 16384 - size)
            pieces.append(clipped)
            size += len(clipped.encode("utf-8"))
            line_count += 1
            if clipped != line:
                truncated = True
                break
        if truncated:
            break
    return {"text": "".join(pieces), "truncated": truncated}


def compare_runs(left, right):
    """Compare two distinct saved snapshots without reading source or changing state."""
    if (type(left) is not dict or type(right) is not dict
            or any(type(side.get("id")) is not str or len(side["id"]) != 16 or IDS.fullmatch(side["id"]) is None
                   for side in (left, right)) or left["id"] == right["id"]):
        raise Refused("COMPARE_IDS")
    a, a_task, a_patch = _summary(left)
    b, b_task, b_patch = _summary(right)
    differences = []
    if a["project"] is not None and b["project"] is not None and a["project"] != b["project"]:
        differences.append("PROJECT_DIFFERS")
    if a["goal"] is not None and b["goal"] is not None and a["goal"] != b["goal"]:
        differences.append("GOAL_DIFFERS")
    if a_task is not None and b_task is not None:
        a_names, b_names = set(a_task["files"]), set(b_task["files"])
        if a_names != b_names:
            differences.append("FILE_SCOPE_DIFFERS")
        if any(a_task["files"][name] != b_task["files"][name] for name in a_names & b_names):
            differences.append("BASELINE_DIFFERS")
        if set(a_task["editable"]) != set(b_task["editable"]):
            differences.append("EDIT_SCOPE_DIFFERS")
        if a["checks"] != b["checks"]:
            differences.append("CHECKS_DIFFER")
        if (a["max_turns"], a["request_seconds"]) != (b["max_turns"], b["request_seconds"]):
            differences.append("BUDGETS_DIFFER")
    if (a_task is None or b_task is None or a["project"] is None or b["project"] is None
            or any(INCOMPLETE.intersection(side["notes"]) or side["task_integrity"] == "UNAVAILABLE" for side in (a, b))):
        differences.append("INCOMPLETE_RECORDS")
    if any("TASK_FINGERPRINT_MISMATCH" in side["notes"] for side in (a, b)):
        differences.append("TASK_FINGERPRINT_MISMATCH")
    a_files = {row["path"]: row for row in a["files"]}
    b_files = {row["path"]: row for row in b["files"]}
    files = [{"path": path, "left_sha256": a_files.get(path, {}).get("sha256"),
              "right_sha256": b_files.get(path, {}).get("sha256"),
              "left_editable": a_files.get(path, {}).get("editable"),
              "right_editable": b_files.get(path, {}).get("editable")}
             for path in sorted(a_files.keys() | b_files.keys())]
    delta = {}
    for key in ("requests", "request_bytes", "elapsed_ms"):
        known = a["metrics"][key] is not None and b["metrics"][key] is not None
        if key != "requests":
            known = known and a["metrics"]["complete"] and b["metrics"]["complete"]
        delta[key] = b["metrics"][key] - a["metrics"][key] if known else None
    result = {"version": 1, "left": a, "right": b, "comparable": not differences,
              "differences": differences, "files": files,
              "patch_difference": _patch_difference(a_patch, b_patch), "metrics_delta": delta,
              "notes": sorted(set(a["notes"]) | set(b["notes"]))}
    if len((json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")) > 131072:
        raise Refused("COMPARE_OUTPUT_LIMIT")
    return result
