"""Pure bounded views of observed saved receipts, without decision promotion.

An entry's artifact relation describes its own saved pins. Selecting an older
receipt never makes it the current decision or grants execution/export authority.
"""

from agent import Refused, canonical
from saved_review_decisions import (
    CODES as DECISION_CODES,
    MAX_OUTPUT,
    NAME,
    NOTES as DECISION_NOTES,
    _matches,
    _receipt,
    summarize_review_decision,
)


NOTES = DECISION_NOTES - {"REVIEW_ARTIFACTS_CHANGED"}
CODES = DECISION_CODES | {"SAVED_REVIEW_NOT_FOUND"}
ARTIFACT_STATES = frozenset({"MATCHING", "STALE", "UNKNOWN"})


def _entry(run_id, wrapper, current, include_note=False):
    # The shared reducer validates every descriptor before this helper runs.
    receipt = _receipt(wrapper["value"], run_id, wrapper) if wrapper["status"] == "OK" else None
    state = "UNKNOWN"
    if (receipt is not None and all(value is not None for value in current.values())
            and current["patch_sha256"] == current["result_patch_sha256"]):
        state = ("MATCHING" if receipt["result_sha256"] == current["result_sha256"]
                 and receipt["patch_sha256"] == current["patch_sha256"] else "STALE")
    result = {"name": wrapper["name"],
              "status": ("OK" if receipt is not None else "INVALID") if wrapper["status"] == "OK" else wrapper["status"],
              "sha256": wrapper["sha256"],
              "verdict": receipt["verdict"] if receipt is not None else None,
              "recorded": receipt["recorded"] if receipt is not None else None,
              "result_sha256": receipt["result_sha256"] if receipt is not None else None,
              "patch_sha256": receipt["patch_sha256"] if receipt is not None else None,
              "artifact_state": state}
    if include_note:
        result["note"] = receipt["note"] if receipt is not None else None
    return result


def _history(decision):
    return {"version": 1, "inspected": decision["inspected"],
            "catalog_complete": decision["catalog_complete"],
            "current": dict(decision["current"]),
            "notes": [code for code in decision["notes"] if code in NOTES]}


def _bounded(value):
    if len(canonical(value)) > MAX_OUTPUT:
        raise Refused("SAVED_REVIEW_OUTPUT_LIMIT")
    return value


def summarize_review_history(run_id, evidence):
    """List ascending observed receipt ordinals, omitting every private note."""
    decision = summarize_review_decision(run_id, evidence)
    result = _history(decision)
    result["entries"] = [_entry(run_id, wrapper, result["current"]) for wrapper in evidence["records"]]
    return _bounded(result)


def inspect_review_history_entry(run_id, evidence, name):
    """Inspect one explicitly selected observed receipt, including a valid note."""
    decision = summarize_review_decision(run_id, evidence)
    if not _matches(name, NAME, 15):
        raise Refused("SAVED_REVIEW_INPUT")
    wrapper = next((row for row in evidence["records"] if row["name"] == name), None)
    if wrapper is None:
        raise Refused("SAVED_REVIEW_NOT_FOUND")
    result = _history(decision)
    result["entry"] = _entry(run_id, wrapper, result["current"], include_note=True)
    return _bounded(result)
