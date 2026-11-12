"""Bounded saved-only evidence review; no I/O, mutation or live-state inference.

Only built-in bounded data reaches the existing comparison/diagnostic reducers.
Private extra fields are ignored without traversal. Full valid goals are never
silently clipped; an oversized complete response is refused instead.
"""

import math
import re

from agent import Refused, canonical
from run_comparison import NOTES as COMPARISON_NOTES, _summary
from run_diagnostics import METRICS, MAX_SAFE, number, summarize


ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
MAX_OUTPUT = 65536
DIAGNOSTIC_FIELDS = ("version", "reason", "provider_completion", "budget", "requests", "legacy", "notes", "preflight")
DIAGNOSTIC_NOTES = frozenset({"EVENT_LIMIT", "INVALID_DIAGNOSTICS", "REQUEST_SIZE_REFUSED",
    "LEGACY_REQUEST_DETAILS", "UNRECOGNIZED_REASON", "MISSING_REQUEST_FINISH",
    "PROVIDER_COMPLETION_UNKNOWN", "SCRIPTED_NO_INFERENCE"})
CODES = frozenset({"SAVED_REVIEW_INPUT", "SAVED_REVIEW_RECORD_INVALID", "SAVED_REVIEW_OUTPUT_LIMIT"})


class _Invalid(Exception):
    pass


class _Limit(Exception):
    pass


def _mapping(value):
    return (type(value) is dict and len(value) <= 64
            and all(type(key) is str for key in value))


def _primitive(value, notes):
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if -MAX_SAFE <= value <= MAX_SAFE:
            return value
    elif type(value) is float:
        if math.isfinite(value) and -MAX_SAFE <= value <= MAX_SAFE:
            return value
    elif type(value) is str:
        try:
            if len(value) <= 32768 and len(value.encode("utf-8")) <= 32768:
                return value
            notes.add("RECORD_LIMIT")
            return None
        except UnicodeError:
            pass
    notes.add("RECORD_INVALID")
    return None


def _json_copy(value, budget, depth=0):
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        raise _Limit()
    if value is None or type(value) is bool:
        return value
    if type(value) is int and -MAX_SAFE <= value <= MAX_SAFE:
        return value
    if type(value) is float and math.isfinite(value) and -MAX_SAFE <= value <= MAX_SAFE:
        return value
    if type(value) is str:
        if len(value) > 32768:
            raise _Limit()
        try:
            if len(value.encode("utf-8")) > 32768:
                raise _Limit()
        except UnicodeError:
            raise _Invalid() from None
        return value
    if type(value) is list:
        if len(value) > 256:
            raise _Limit()
        return [_json_copy(item, budget, depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 64:
            raise _Limit()
        if not all(type(key) is str and len(key) <= 128 for key in value):
            raise _Invalid()
        return {_json_copy(key, budget, depth + 1): _json_copy(item, budget, depth + 1)
                for key, item in value.items()}
    raise _Invalid()


def _task(value, notes):
    if value is None:
        return None
    try:
        copied = _json_copy(value, [1024])
        if len(canonical(copied)) > 32768:
            raise _Limit()
        return copied
    except _Limit:
        notes.add("RECORD_LIMIT")
    except _Invalid:
        notes.add("RECORD_INVALID")
    return None


def _selected(value, fields, notes):
    if value is None:
        return None
    if not _mapping(value):
        notes.add("RECORD_LIMIT" if type(value) is dict and len(value) > 64 else "RECORD_INVALID")
        return None
    return {key: _primitive(value[key], notes) for key in fields if key in value}


def _metadata(value, notes):
    result = _selected(value, ("id", "project", "project_name", "goal", "state", "backend", "model",
                               "created", "finished", "task_sha256", "project_task_sha256"), notes)
    if result is None:
        return None
    goal = result.get("goal")
    if type(goal) is str and (len(goal) > 2000 or len(goal.encode("utf-8")) > 8000):
        result["goal"] = None
        notes.add("RECORD_LIMIT")
    for field in ("created", "finished"):
        if field in result and result[field] is not None and number(result[field]) is None:
            result[field] = None
            notes.add("RECORD_INVALID")
    return result


def _detail(value, notes):
    fields = ("format", "started_at_ms", "timeout_seconds", "request_bytes", "elapsed_ms", "phase",
              "outcome", "reason", "error_category", "limit_bytes", "chat_request_sent", "new_hold_created")
    result = _selected(value, fields, notes)
    if result is not None and _mapping(value) and "metrics" in value:
        metrics = _selected(value["metrics"], tuple(sorted(METRICS)), notes)
        result["metrics"] = metrics
    return result


def _event(value, notes, diagnostic_notes):
    if not _mapping(value):
        notes.add("RECORD_INVALID")
        diagnostic_notes.add("INVALID_DIAGNOSTICS")
        return None
    index = _primitive(value.get("index"), notes)
    kind = _primitive(value.get("kind"), notes)
    if number(index) is None or type(kind) is not str or not 1 <= len(kind) <= 64:
        notes.add("RECORD_INVALID")
        diagnostic_notes.add("INVALID_DIAGNOSTICS")
        return None
    raw = value.get("value")
    if not _mapping(raw):
        notes.add("RECORD_INVALID")
        diagnostic_notes.add("INVALID_DIAGNOSTICS")
        raw = {}
    admitted = {}
    if kind in {"request_started", "request_finished", "request_refused"}:
        if "turn" in raw:
            admitted["turn"] = _primitive(raw["turn"], notes)
        if "diagnostics" in raw:
            admitted["diagnostics"] = _detail(raw["diagnostics"], notes)
    elif kind in {"baseline_checks", "independent_final_checks"}:
        if len(raw) > 4:
            notes.add("RECORD_INVALID")
        else:
            for label, row in raw.items():
                if len(label) > 32:
                    notes.add("RECORD_INVALID")
                    continue
                admitted[label] = _selected(row, ("exit_code", "tests_ran", "timed_out",
                                                  "output_limited", "infrastructure_error"), notes)
    # Response/other event bodies can hold private prompts, responses, outputs
    # and exceptions. Their presence is enough for existing historical reducers.
    return {"index": index, "kind": kind, "value": admitted}


def _events(value, notes, diagnostic_notes):
    if value is None:
        return None
    if type(value) is not list:
        notes.add("RECORD_INVALID")
        diagnostic_notes.add("INVALID_DIAGNOSTICS")
        return None
    if len(value) > 256:
        notes.add("EVENT_LIMIT")
        diagnostic_notes.add("EVENT_LIMIT")
    result, remaining = [], 2097152
    for raw in value[:256]:
        event = _event(raw, notes, diagnostic_notes)
        if event is None:
            continue
        size = len(canonical(event))
        if size > 262144 or size > remaining:
            notes.update({"RECORD_LIMIT", "EVENT_LIMIT"})
            diagnostic_notes.add("EVENT_LIMIT")
            break
        remaining -= size
        result.append(event)
    return result


def _patch(value, notes):
    if value is None:
        return None
    if type(value) is str:
        try:
            if len(value) <= 65536 and len(value.encode("utf-8")) <= 65536:
                return value
            notes.add("RECORD_LIMIT")
            return None
        except UnicodeError:
            pass
    notes.add("RECORD_INVALID")
    return None


def review_saved_run(bundle, record_sha256, history_sha256, evidence_sha256):
    """Return one sanitized historical summary and diagnostics, with exact pins."""
    if (type(bundle) is not dict or len(bundle) > 32 or not all(type(key) is str for key in bundle)
            or type(bundle.get("id")) is not str or ID.fullmatch(bundle["id"]) is None
            or any(type(pin) is not str or HASH.fullmatch(pin) is None
                   for pin in (record_sha256, history_sha256, evidence_sha256))):
        raise Refused("SAVED_REVIEW_INPUT")
    notes, diagnostic_notes = set(), set()
    supplied = bundle.get("notes", [])
    if type(supplied) is not list:
        notes.add("RECORD_INVALID")
    else:
        if len(supplied) > 64:
            notes.add("RECORD_LIMIT")
        for code in supplied[:64]:
            if type(code) is str and code in COMPARISON_NOTES:
                notes.add(code)
            else:
                notes.add("RECORD_INVALID")
    safe = {"id": bundle["id"], "metadata": _metadata(bundle.get("metadata"), notes),
            "task": _task(bundle.get("task"), notes),
            "result": _selected(bundle.get("result"), ("status", "reason", "turns", "patch_sha256"), notes),
            "events": _events(bundle.get("events"), notes, diagnostic_notes),
            "patch": _patch(bundle.get("patch"), notes)}
    for field in ("task_sha256", "result_sha256", "patch_sha256"):
        safe[field] = _primitive(bundle.get(field), notes)
    safe["notes"] = sorted(notes)
    summary, task, _ = _summary(safe)
    diagnostics = summarize(task or {"max_turns": 16, "request_seconds": 120}, safe["result"],
                            safe["events"] or [], summary["state"], summary["backend"])
    diagnostics = {key: diagnostics[key] for key in DIAGNOSTIC_FIELDS}
    if task is None:
        diagnostics["budget"]["limit"] = None
        diagnostics["budget"]["per_request_seconds"] = None
    saved_turns = number((safe["result"] or {}).get("turns"), task["max_turns"] if task else 16)
    used = [row["turn"] for row in diagnostics["requests"]]
    if saved_turns is not None:
        used.append(saved_turns)
    diagnostics["budget"]["used"] = max(used) if used else None
    if task is None and bundle.get("task") is not None:
        diagnostic_notes.add("INVALID_DIAGNOSTICS")
    if not diagnostics["requests"] and summary["backend"] != "scripted-demo" and diagnostics["preflight"] is None:
        diagnostics["provider_completion"] = "UNKNOWN"
        diagnostic_notes.add("PROVIDER_COMPLETION_UNKNOWN")
    diagnostics["notes"] = sorted(set(diagnostics["notes"]) | diagnostic_notes)
    result = {"version": 1, "id": bundle["id"], "record_sha256": record_sha256,
              "history_sha256": history_sha256, "evidence_sha256": evidence_sha256,
              "summary": summary, "diagnostics": diagnostics}
    try:
        if len(canonical(result)) > MAX_OUTPUT:
            raise Refused("SAVED_REVIEW_OUTPUT_LIMIT")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise Refused("SAVED_REVIEW_RECORD_INVALID") from None
    return result
