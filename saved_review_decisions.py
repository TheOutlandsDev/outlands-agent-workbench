"""Pure, bounded observations of existing private human review receipts.

Receipt pins describe saved artifacts, not authorship, live correctness, source
adoption or permission to export. No earlier receipt substitutes for an unusable
highest observed ordinal, and any incomplete evidence keeps the result unknown.
"""

import re

from agent import Refused, canonical


ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"review-0[0-9]{2}\.json\Z")
MAX_SAFE = 9007199254740991
MAX_OUTPUT = 65536
STATES = frozenset({"UNREVIEWED", "ACCEPTED", "REJECTED", "STALE", "UNKNOWN"})
NOTES = frozenset({
    "REVIEW_CATALOG_MISSING", "REVIEW_CATALOG_PARTIAL", "REVIEW_CATALOG_INVALID",
    "REVIEW_RECORD_MISSING", "REVIEW_RECORD_INVALID", "REVIEW_RECORD_LIMITED",
    "CURRENT_RESULT_UNKNOWN", "CURRENT_PATCH_UNKNOWN",
    "CURRENT_PATCH_DECLARATION_UNKNOWN", "CURRENT_ARTIFACTS_INCONSISTENT",
    "REVIEW_ARTIFACTS_CHANGED",
})
CODES = frozenset({"SAVED_REVIEW_INPUT", "SAVED_REVIEW_RECORD_INVALID", "SAVED_REVIEW_OUTPUT_LIMIT"})
CURRENT_KEYS = frozenset({"result_sha256", "patch_sha256", "result_patch_sha256"})
EVIDENCE_KEYS = frozenset({"present", "catalog_partial", "catalog_invalid", "records", "current"})
WRAPPER_KEYS = frozenset({"name", "sha256", "value", "status"})
RECEIPT_KEYS = frozenset({"id", "result_sha256", "patch_sha256", "verdict", "note", "recorded", "source_applied"})
STATUSES = frozenset({"OK", "MISSING", "INVALID", "LIMITED"})


def _exact(value, keys):
    # Reject user-defined mappings/keys before set construction or field lookup.
    return (type(value) is dict and len(value) == len(keys)
            and all(type(key) is str for key in value) and set(value) == keys)


def _matches(value, pattern, length):
    return type(value) is str and len(value) == length and pattern.fullmatch(value) is not None


def _note(value):
    if type(value) is not str or len(value) > 2000:
        return False
    try:
        return len(value.encode("utf-8")) <= 8000
    except UnicodeError:
        return False


def _receipt(value, run_id, wrapper):
    """Copy only the exact usable receipt; do not traverse corrupt extra data."""
    if not _exact(value, RECEIPT_KEYS):
        return None
    if not (_matches(value["id"], ID, 16) and value["id"] == run_id
            and _matches(value["result_sha256"], HASH, 64)
            and _matches(value["patch_sha256"], HASH, 64)
            and type(value["verdict"]) is str and value["verdict"] in {"accepted", "rejected"}
            and type(value["recorded"]) is int and 0 <= value["recorded"] <= MAX_SAFE
            and value["source_applied"] is False and _note(value["note"])
            and wrapper["sha256"] is not None):
        return None
    return {"name": wrapper["name"], "sha256": wrapper["sha256"],
            "verdict": value["verdict"], "recorded": value["recorded"],
            "note": value["note"], "result_sha256": value["result_sha256"],
            "patch_sha256": value["patch_sha256"]}


def summarize_review_decision(run_id, evidence):
    """Return the strict seven-field saved decision DTO, without I/O or mutation.

    Malformed descriptors refuse with a finite code. Observed malformed receipt
    contents are evidence of uncertainty and are never echoed into the result.
    """
    if not _matches(run_id, ID, 16) or not _exact(evidence, EVIDENCE_KEYS):
        raise Refused("SAVED_REVIEW_INPUT")
    if (any(type(evidence[key]) is not bool for key in ("present", "catalog_partial", "catalog_invalid"))
            or not _exact(evidence["current"], CURRENT_KEYS)):
        raise Refused("SAVED_REVIEW_INPUT")
    current = {}
    for key in ("result_sha256", "patch_sha256", "result_patch_sha256"):
        value = evidence["current"][key]
        if value is not None and not _matches(value, HASH, 64):
            raise Refused("SAVED_REVIEW_INPUT")
        current[key] = value
    records = evidence["records"]
    if type(records) is not list or len(records) > 100:
        raise Refused("SAVED_REVIEW_RECORD_INVALID")
    previous = None
    for wrapper in records:
        if (not _exact(wrapper, WRAPPER_KEYS)
                or not _matches(wrapper["name"], NAME, 15)
                or (wrapper["sha256"] is not None and not _matches(wrapper["sha256"], HASH, 64))
                or type(wrapper["status"]) is not str or wrapper["status"] not in STATUSES
                or (previous is not None and wrapper["name"] <= previous)):
            raise Refused("SAVED_REVIEW_RECORD_INVALID")
        previous = wrapper["name"]

    contiguous = all(wrapper["name"] == f"review-{index:03d}.json"
                     for index, wrapper in enumerate(records))
    complete = (evidence["present"] and not evidence["catalog_partial"]
                and not evidence["catalog_invalid"] and contiguous)
    notes = set()
    if not evidence["present"]:
        notes.add("REVIEW_CATALOG_MISSING")
    if evidence["catalog_partial"]:
        notes.add("REVIEW_CATALOG_PARTIAL")
    if evidence["catalog_invalid"] or not contiguous:
        notes.add("REVIEW_CATALOG_INVALID")

    latest = None
    usable = True
    for wrapper in records:
        receipt = None
        status = wrapper["status"]
        if status == "OK":
            receipt = _receipt(wrapper["value"], run_id, wrapper)
            if receipt is None:
                notes.add("REVIEW_RECORD_INVALID")
        else:
            notes.add({"MISSING": "REVIEW_RECORD_MISSING", "INVALID": "REVIEW_RECORD_INVALID",
                       "LIMITED": "REVIEW_RECORD_LIMITED"}[status])
        usable = usable and receipt is not None
        latest = receipt

    # This observes a complete absence of receipts, independently of readiness.
    if complete and not records:
        state = "UNREVIEWED"
        notes.clear()
    else:
        for key, code in (("result_sha256", "CURRENT_RESULT_UNKNOWN"),
                          ("patch_sha256", "CURRENT_PATCH_UNKNOWN"),
                          ("result_patch_sha256", "CURRENT_PATCH_DECLARATION_UNKNOWN")):
            if current[key] is None:
                notes.add(code)
        inconsistent = (current["patch_sha256"] is not None
                        and current["result_patch_sha256"] is not None
                        and current["patch_sha256"] != current["result_patch_sha256"])
        if inconsistent:
            notes.add("CURRENT_ARTIFACTS_INCONSISTENT")
        if complete and records and usable and all(value is not None for value in current.values()) and not inconsistent:
            if (latest["result_sha256"] == current["result_sha256"]
                    and latest["patch_sha256"] == current["patch_sha256"]):
                state = "ACCEPTED" if latest["verdict"] == "accepted" else "REJECTED"
            else:
                state = "STALE"
                notes.add("REVIEW_ARTIFACTS_CHANGED")
        else:
            state = "UNKNOWN"

    result = {"version": 1, "state": state, "receipt": latest, "current": current,
              "inspected": len(records), "catalog_complete": complete, "notes": sorted(notes)}
    if len(canonical(result)) > MAX_OUTPUT:
        raise Refused("SAVED_REVIEW_OUTPUT_LIMIT")
    return result
