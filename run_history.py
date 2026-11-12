"""Bounded search/review of supplied saved metadata, without I/O or live inference.

The controller owns safe record reads and history/record pin verification. These
helpers neither read paths nor reconcile jobs, infer worker/provider state, run
checks, or change any supplied record. Unrecognized/private metadata is ignored.
"""

import re

from agent import Refused, canonical


ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
MAX_SAFE = 9007199254740991
MAX_RECORDS = 200
MAX_ROWS = 100
MAX_OUTPUT = 65536
STATES = frozenset({"REVIEW_READY", "RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED",
                    "FAILED", "REFUSED", "UNCERTAIN", "INTERRUPTED"})
NOTES = frozenset({"RECORD_INVALID", "LABEL_TRUNCATED", "CATALOG_TRUNCATED", "RESULT_TRUNCATED"})
CODES = frozenset("HISTORY_SEARCH_" + code for code in (
    "INPUT", "QUERY", "FILTER", "RECORD_INVALID", "LIMIT", "OUTPUT_LIMIT", "STORE_UNSAFE",
    "HISTORY_CHANGED", "RECORD_CHANGED", "NOT_FOUND"))


def _require(condition, code):
    if not condition:
        raise Refused("HISTORY_SEARCH_" + code)


def _hash(value):
    return type(value) is str and len(value) == 64 and HASH.fullmatch(value) is not None


def _text(value, chars, size):
    if type(value) is not str or len(value) > chars or "\x00" in value:
        return None
    try:
        return value if len(value.encode("utf-8")) <= size else None
    except UnicodeError:
        return None


def _clean(record):
    _require(type(record) is dict and set(record) == {"id", "metadata", "record_sha256"}, "RECORD_INVALID")
    identifier, metadata = record["id"], record["metadata"]
    _require(type(identifier) is str and len(identifier) == 16 and ID.fullmatch(identifier) is not None
             and _hash(record["record_sha256"]) and type(metadata) is dict and len(metadata) <= 64,
             "RECORD_INVALID")
    _require("id" not in metadata or type(metadata["id"]) is str and metadata["id"] == identifier,
             "RECORD_INVALID")
    cleaned = {"id": identifier, "record_sha256": record["record_sha256"]}
    notes = set()
    for name in ("project", "project_name", "goal", "state", "created"):
        raw = metadata.get(name)
        value = None
        if name == "project":
            if type(raw) is str and len(raw) <= 32 and ALIAS.fullmatch(raw) is not None:
                value = raw
        elif name == "project_name":
            value = _text(raw, 320, 320)
        elif name == "goal":
            value = _text(raw, 2000, 8000)
        elif name == "state":
            if type(raw) is str and raw in STATES:
                value = raw
        elif type(raw) is int and 0 <= raw <= MAX_SAFE:
            value = raw
        if name in metadata and value is None:
            notes.add("RECORD_INVALID")
        cleaned[name] = value
    return cleaned, notes


def _request(request):
    _require(type(request) is dict and set(request) == {"query", "project", "state"}
             and all(type(request[name]) is str for name in ("query", "project", "state")), "INPUT")
    query, project, state = request["query"], request["project"], request["state"]
    _require(_text(query, 128, 128) is not None and "\r" not in query and "\n" not in query, "QUERY")
    _require(project in {"", "UNKNOWN"} or len(project) <= 32 and ALIAS.fullmatch(project) is not None, "FILTER")
    _require(state in {"", "UNKNOWN"} or state in STATES, "FILTER")
    return query, project, state


def _clip(value):
    if value is None or len(value.encode("utf-8")) <= 160:
        return value, False
    return value.encode("utf-8")[:157].decode("utf-8", "ignore") + "…", True


def _row(cleaned, query, match_fields):
    label, label_truncated = _clip(cleaned["project_name"])
    goal, goal_truncated = _clip(cleaned["goal"])
    if goal_truncated and query and "goal" in match_fields:
        # Search examined the complete valid goal before display clipping. Keep
        # its complete matching literal visible, including a late-only match.
        goal = "…" + query + "…"
    return {"id": cleaned["id"], "project": cleaned["project"], "project_name": label,
            "goal_excerpt": goal, "goal_truncated": goal_truncated, "state": cleaned["state"],
            "created": cleaned["created"], "record_sha256": cleaned["record_sha256"],
            "match_fields": match_fields}, label_truncated or goal_truncated


def search_history(records, request, history_sha256, catalog_truncated=False):
    """Filter full supplied metadata, then return bounded labels and true counts.

    Inspection can be partial and need not contain the globally newest history.
    Saved states remain observations, including unknown/invalid legacy fields.
    """
    query, project, state = _request(request)
    _require(_hash(history_sha256) and type(catalog_truncated) is bool, "INPUT")
    _require(type(records) is list, "RECORD_INVALID")
    _require(len(records) <= MAX_RECORDS, "LIMIT")
    seen, projects, notes, matches = set(), set(), set(), []
    for record in records:
        cleaned, record_notes = _clean(record)
        _require(cleaned["id"] not in seen, "RECORD_INVALID")
        seen.add(cleaned["id"])
        projects.add(cleaned["project"])
        notes.update(record_notes)
        if project and cleaned["project"] != (None if project == "UNKNOWN" else project):
            continue
        if state and cleaned["state"] != (None if state == "UNKNOWN" else state):
            continue
        fields = []
        if query:
            if query in cleaned["id"]:
                fields.append("id")
            if cleaned["goal"] is not None and query in cleaned["goal"]:
                fields.append("goal")
            if not fields:
                continue
        matches.append((cleaned, fields))
    matches.sort(key=lambda pair: (pair[0]["created"] is not None, pair[0]["created"] or 0, pair[0]["id"]),
                 reverse=True)
    display = [_row(cleaned, query, fields) for cleaned, fields in matches[:MAX_ROWS]]
    if catalog_truncated:
        notes.add("CATALOG_TRUNCATED")
    result = {"version": 1, "query": query, "project": project, "state": state,
              "history_sha256": history_sha256, "runs": [],
              "projects": sorted(value for value in projects if value is not None)
                          + (["UNKNOWN"] if None in projects else []),
              "inspected": len(records), "matched": len(matches), "returned": 0,
              "catalog_truncated": catalog_truncated, "result_truncated": False,
              "limit": MAX_ROWS, "notes": []}
    while True:
        current_notes = set(notes)
        if any(truncated for _, truncated in display):
            current_notes.add("LABEL_TRUNCATED")
        result["runs"] = [row for row, _ in display]
        result["returned"] = len(display)
        result["result_truncated"] = len(display) < len(matches)
        if result["result_truncated"]:
            current_notes.add("RESULT_TRUNCATED")
        result["notes"] = sorted(current_notes)
        if len(canonical(result)) <= MAX_OUTPUT:
            return result
        _require(bool(display), "OUTPUT_LIMIT")
        display.pop()


def review_record(record, history_sha256):
    """Return only explicitly selected cleaned saved metadata, with no I/O."""
    _require(_hash(history_sha256), "INPUT")
    cleaned, notes = _clean(record)
    result = {"version": 1, **cleaned, "history_sha256": history_sha256, "notes": sorted(notes)}
    _require(len(canonical(result)) <= MAX_OUTPUT, "OUTPUT_LIMIT")
    return result
