"""Bounded, read-only summaries of private request evidence, including old runs."""

FORMAT = "outlands-request-diagnostics-v1"
MAX_SAFE = 9007199254740991
PHASES = {"PREPARE", "SEND", "HEADER", "BODY", "VALIDATE", "COMPLETE", "UNKNOWN"}
CATEGORIES = {"TIMEOUT", "CONNECTION", "HTTP_PROTOCOL", "REFUSED", "OS_ERROR", "EXECUTION", "INTERRUPTED"}
METRICS = {"prompt_eval_count", "eval_count", "total_duration", "load_duration", "prompt_eval_duration", "eval_duration"}
REASONS = {
    "EXECUTION_ERROR", "PLAN_REQUIRED", "PLAN_ONCE", "PLAN_LIMIT", "PROVIDER_SEND_TIMEOUT",
    "PROVIDER_HEADER_TIMEOUT", "PROVIDER_BODY_TIMEOUT", "PROVIDER_HTTP", "PROVIDER_INCOMPLETE",
    "RESPONSE_LIMIT", "MODEL_MESSAGE", "MODEL_CONTENT", "MODEL_CALL", "ONE_TOOL_PER_TURN",
    "UNKNOWN_TOOL", "FINAL_REQUIRED", "FINAL_CHECKS_FAILED", "CHECK_EXECUTION_FAILED",
    "OWNER_INTERRUPT", "TURN_BUDGET_EXHAUSTED", "SESSION_TIME_LIMIT", "CONTEXT_LIMIT", "CHECKS_PASSED",
    "SOURCE_HASH_CHANGED", "ORIGINAL_SOURCE_CHANGED", "READ_SCOPE", "WRITE_SCOPE", "TOOL_ARGUMENTS",
    "PROTECTED_FILE_CHANGED", "WORK_TREE_CHANGED", "REPLACEMENT_NOT_UNIQUE", "FILE_HASH_CHANGED",
    "REPLACEMENT_LIMIT", "UNKNOWN_CHECK", "JDK_REQUIRED", "UNFINISHED",
    "JSON_LIMIT", "INVALID_JSON", "DUPLICATE_JSON_KEY", "JSON_CONSTANT",
}


def number(value, maximum=MAX_SAFE):
    return value if type(value) is int and 0 <= value <= maximum else None


def reason(value):
    return value if isinstance(value, str) and value in REASONS else None


def summarize(task, result, events, state, backend, owned_active=False, hold_matches=False, hold_present=False):
    """Never return raw exception text, source, prompts, paths, or unknown fields."""
    limit = number(task.get("max_turns"), 16) or 1
    timeout = number(task.get("request_seconds"), 120) or 1
    notes, rows, current = [], {}, None

    def note(code):
        if code not in notes:
            notes.append(code)

    if len(events) > 256:
        note("EVENT_LIMIT")
    for event in events[:256]:
        if not isinstance(event, dict):
            note("INVALID_DIAGNOSTICS")
            continue
        kind, value = event.get("kind"), event.get("value")
        if kind == "response":
            if current in rows:
                rows[current]["responded"] = True
            continue
        if kind not in ["request_started", "request_finished"]:
            continue
        if not isinstance(value, dict):
            note("INVALID_DIAGNOSTICS")
            continue
        turn = number(value.get("turn"), limit)
        if not turn:
            note("INVALID_DIAGNOSTICS")
            continue
        detail = value.get("diagnostics")
        detailed = isinstance(detail, dict) and detail.get("format") == FORMAT
        if kind == "request_started":
            if turn in rows:
                note("INVALID_DIAGNOSTICS")
                continue
            current = turn
            row = {"turn": turn, "started_at_ms": None, "elapsed_ms": None, "timeout_seconds": None,
                   "request_bytes": None, "phase": "UNKNOWN", "status": "UNKNOWN", "reason": None,
                   "error_category": None, "provider_completion": "UNKNOWN", "metrics": {},
                   "responded": False, "finished": False, "detailed": detailed}
            rows[turn] = row
            if detailed:
                for key, maximum in [("started_at_ms", 8640000000000000), ("timeout_seconds", 120), ("request_bytes", 262144)]:
                    row[key] = number(detail.get(key), maximum)
                    if detail.get(key) is not None and row[key] is None:
                        note("INVALID_DIAGNOSTICS")
                if row["started_at_ms"] is None or not row["timeout_seconds"]:
                    note("INVALID_DIAGNOSTICS")
            else:
                note("LEGACY_REQUEST_DETAILS")
            continue
        if turn not in rows or rows[turn]["finished"] or not detailed:
            note("INVALID_DIAGNOSTICS")
            continue
        row = rows[turn]
        row["finished"] = True
        row["elapsed_ms"] = number(detail.get("elapsed_ms"))
        phase, category = detail.get("phase"), detail.get("error_category")
        row["phase"] = phase if isinstance(phase, str) and phase in PHASES else "UNKNOWN"
        row["error_category"] = category if isinstance(category, str) and category in CATEGORIES else None
        row["reason"] = reason(detail.get("reason"))
        if detail.get("reason") is not None and row["reason"] is None:
            note("UNRECOGNIZED_REASON")
        if row["elapsed_ms"] is None or row["phase"] == "UNKNOWN" and phase != "UNKNOWN":
            note("INVALID_DIAGNOSTICS")
        outcome = detail.get("outcome")
        if outcome == "RESPONSE_RECORDED" and row["responded"]:
            row["status"] = "RECORDED"
        elif outcome in ["ERROR", "INTERRUPTED"]:
            row["status"] = outcome
        else:
            note("INVALID_DIAGNOSTICS")
        metrics = detail.get("metrics")
        if isinstance(metrics, dict):
            row["metrics"] = {key: metrics[key] for key in METRICS if number(metrics.get(key)) is not None}

    requests = []
    for turn in sorted(rows):
        row = rows[turn]
        if not row["finished"]:
            if turn == current and owned_active:
                row["status"] = "ACTIVE"
            else:
                if row["responded"]:
                    row["status"] = "RECORDED"
                if row["detailed"]:
                    note("MISSING_REQUEST_FINISH")
        row["provider_completion"] = ("NOT_APPLICABLE" if backend == "scripted-demo" else
                                      "RECORDED" if row["responded"] else "UNKNOWN")
        requests.append({key: value for key, value in row.items() if key not in ["responded", "finished", "detailed"]})
    result = result if isinstance(result, dict) else {}
    terminal_reason = reason(result.get("reason"))
    if result.get("reason") is not None and terminal_reason is None:
        note("UNRECOGNIZED_REASON")
    held = ("ACTIVE_REQUEST" if hold_matches and owned_active else "UNRESOLVED" if hold_matches
            else "UNASSOCIATED" if hold_present else "ABSENT")
    if state == "RECOVERY_REQUIRED":
        status = "NEEDS_INSPECTION"
    elif state == "UNCERTAIN" or held == "UNRESOLVED":
        status = "UNCERTAIN"
    elif owned_active:
        status = "ACTIVE"
    elif state in ["RUNNING", "STOP_REQUESTED"]:
        status = "NEEDS_INSPECTION"
    elif state == "REVIEW_READY":
        status = "NEEDS_INSPECTION" if any(n in notes for n in ["INVALID_DIAGNOSTICS", "EVENT_LIMIT", "MISSING_REQUEST_FINISH"]) else "COMPLETE"
    elif state in ["FAILED", "REFUSED", "INTERRUPTED"]:
        status = "FAILED"
    else:
        status = "NOT_STARTED"
    completion = requests[-1]["provider_completion"] if requests else "NOT_APPLICABLE"
    if held == "UNRESOLVED":
        note("HOLD_RETAINED")
    if held == "ACTIVE_REQUEST":
        note("REQUEST_ACTIVE")
    if held == "UNASSOCIATED":
        note("HOLD_UNASSOCIATED")
    if completion == "UNKNOWN" and requests:
        note("PROVIDER_COMPLETION_UNKNOWN")
    if backend == "scripted-demo":
        note("SCRIPTED_NO_INFERENCE")
    return {"version": 1, "state": status, "reason": terminal_reason, "hold": held,
            "provider_completion": completion,
            "budget": {"used": max([r["turn"] for r in requests] + [number(result.get("turns"), limit) or 0]),
                       "limit": limit, "per_request_seconds": timeout},
            "requests": requests, "legacy": "LEGACY_REQUEST_DETAILS" in notes, "notes": notes}
