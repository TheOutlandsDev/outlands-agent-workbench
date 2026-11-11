"""Compare private snapshot exports with explicit selected files; reconstruct only in memory."""

import sys
from pathlib import Path

from agent import Refused, canonical, review_diff, sha
from bundle_project_check import MAX_ARCHIVE, MAX_FILE, MAX_TASK, MAX_TOTAL, ReadIssue, _path, _read_named, _task, read_selected
from bundle_workspace import _apply, _lines
from snapshot_export import CODES as EXPORT_CODES, _members, verify_export


MAX_REPORT = 65536
CODES = frozenset("SNAPSHOT_PROJECT_" + suffix for suffix in
                  ("INPUT", "TASK_INVALID", "LIMIT", "OUTPUT_LIMIT", "PROJECT_CHANGED"))
NOT_CHECKED = ["TASK_GOAL", "CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "GIT_ADOPTION", "AUTHENTICITY"]
NOTES = ["PRIVATE_PROJECT_INFORMATION", "STATIC_OBSERVATIONS_ONLY", "UNSIGNED_SNAPSHOT_EXPORT", "BASELINE_RECONSTRUCTION_ONLY"]
REASONS = frozenset(("FORMAT_MISMATCH", "SCOPE_MISMATCH", "PERMISSIONS_MISMATCH", "CHECKS_MISMATCH", "BUDGETS_MISMATCH",
    "SOURCE_CHANGED", "SOURCE_MISSING", "SOURCE_UNREADABLE", "FILE_LIMIT", "BINARY_INPUT", "INVALID_UTF8", "TOTAL_INPUT_LIMIT",
    "MIXED_BASELINE_TESTED", "PROFILE_MISMATCH", "BASELINE_MATCH_REQUIRED", "PATCH_INVALID", "SNAPSHOT_HASH_MISMATCH",
    "PROTECTED_CHANGED", "SNAPSHOT_LIMIT", "OBSERVATION_CHANGED"))
LIMITS = {"max_files": 32, "max_file_bytes": MAX_FILE, "max_total_bytes": MAX_TOTAL,
          "max_archive_bytes": MAX_ARCHIVE, "max_report_bytes": MAX_REPORT}


def _require(condition, suffix="INPUT"):
    if not condition:
        raise Refused("SNAPSHOT_PROJECT_" + suffix)


def _safe_error(error):
    code = str(error) if isinstance(error, Refused) else None
    return code if code in CODES or code in EXPORT_CODES else "SNAPSHOT_PROJECT_INPUT"


def _selected_task(raw):
    try:
        return _task(raw)
    except Refused as error:
        raise Refused("SNAPSHOT_PROJECT_LIMIT" if str(error) == "PROJECT_CHECK_LIMIT" else "SNAPSHOT_PROJECT_TASK_INVALID") from None


def _observation(root, row):
    try:
        raw = read_selected(root, row["path"])
        current = sha(raw)
        baseline, tested = row["baseline_sha256"], row["snapshot_sha256"]
        if current == baseline == tested:
            status = "UNCHANGED"
        elif not row["editable"]:
            status = "CHANGED"
        elif current == baseline:
            status = "BASELINE"
        elif current == tested:
            status = "TESTED"
        else:
            status = "CHANGED"
        row.update(current_sha256=current, bytes=len(raw), task_pin_match=current == row["project_sha256"], status=status)
        return raw
    except FileNotFoundError:
        row["status"] = "MISSING"
    except ReadIssue as error:
        row["status"] = str(error) if str(error) in {"UNREADABLE", "LIMIT", "BINARY", "UTF8"} else "UNREADABLE"
    except (Refused, OSError, ValueError):
        row["status"] = "UNREADABLE"
    return None


def _reconstruct(patch, baseline, rows):
    """Return a finite observation; no bytes leave the in-memory reconstruction."""
    result = {"status": "REFUSED", "reason": "PATCH_INVALID", "files_checked": 0,
              "patch_sha256": sha(patch), "patch_bytes": len(patch)}
    try:
        changed = [row["path"] for row in rows if row["baseline_sha256"] != row["snapshot_sha256"]]
        for raw in baseline.values():
            _lines(raw)
        candidate = _apply(patch, dict(baseline), changed)
        if set(candidate) != set(baseline):
            return result
        if (any(type(raw) is not bytes or len(raw) > MAX_FILE for raw in candidate.values())
                or sum(map(len, candidate.values())) > MAX_TOTAL):
            result["reason"] = "SNAPSHOT_LIMIT"
            return result
        for row in rows:
            name = row["path"]
            raw = candidate[name]
            if not row["editable"] and raw != baseline[name]:
                result["reason"] = "PROTECTED_CHANGED"
                return result
            if sha(raw) != row["snapshot_sha256"]:
                result["reason"] = "SNAPSHOT_HASH_MISMATCH"
                return result
            if b"\x00" in raw:
                return result
            _lines(raw)
        regenerated = "".join(review_diff(name, baseline[name], candidate[name]) for name in sorted(baseline)).encode("utf-8")
        if regenerated != patch:
            return result
        result.update(status="VERIFIED", reason=None, files_checked=len(rows))
    except Refused as error:
        if str(error) == "BUNDLE_WORKSPACE_LIMIT":
            result["reason"] = "SNAPSHOT_LIMIT"
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        pass
    return result


def _unchanged(root, baseline):
    try:
        return all(read_selected(root, name) == raw for name, raw in baseline.items())
    except (Refused, ReadIssue, OSError, ValueError, TypeError):
        return False


def _check(archive_raw, project_root, task_raw, expected_sha256):
    # Archive verification is intentionally first, before task parsing or any selected read.
    verified = verify_export(archive_raw, expected_sha256)
    task = _selected_task(task_raw)
    _path(project_root)
    archive_files = {row["path"]: row for row in verified["files"]}
    archive_names, selected_names = set(archive_files), set(task["files"])
    editable = set(task["editable"])
    permissions = [{"path": name, "archive_editable": archive_files[name]["editable"], "project_editable": name in editable}
                   for name in sorted(archive_names & selected_names) if archive_files[name]["editable"] != (name in editable)]
    profile = {"format": verified["profile"]["format"] == task["format"], "scope": archive_names == selected_names,
               "permissions": not permissions,
               "checks": {row["name"]: row["spec"] for row in verified["checks"]} == task["checks"],
               "budgets": (verified["profile"]["max_turns"], verified["profile"]["request_seconds"])
                          == (task["max_turns"], task["request_seconds"])}
    reasons = {reason for key, reason in (("format", "FORMAT_MISMATCH"), ("scope", "SCOPE_MISMATCH"),
              ("permissions", "PERMISSIONS_MISMATCH"), ("checks", "CHECKS_MISMATCH"), ("budgets", "BUDGETS_MISMATCH")) if not profile[key]}
    matched = all(profile.values())
    files, observed = [], {}
    for name in sorted(archive_names):
        item = archive_files[name]
        selected = name in selected_names
        row = {"path": name, "editable": item["editable"], "project_editable": name in editable if selected else None,
               "baseline_sha256": item["baseline_sha256"], "snapshot_sha256": item["snapshot_sha256"],
               "project_sha256": task["files"].get(name), "current_sha256": None, "bytes": None,
               "task_pin_match": None, "status": "NOT_CHECKED" if selected else "OUT_OF_SCOPE"}
        if matched:
            raw = _observation(project_root, row)
            if raw is not None:
                observed[name] = raw
        reason = {"CHANGED": "SOURCE_CHANGED", "MISSING": "SOURCE_MISSING", "UNREADABLE": "SOURCE_UNREADABLE",
                  "LIMIT": "FILE_LIMIT", "BINARY": "BINARY_INPUT", "UTF8": "INVALID_UTF8"}.get(row["status"])
        if reason:
            reasons.add(reason)
        files.append(row)
    total = sum(row["bytes"] for row in files) if all(row["bytes"] is not None for row in files) else None
    if total is not None and total > MAX_TOTAL:
        reasons.add("TOTAL_INPUT_LIMIT")
    statuses = {row["status"] for row in files}
    if not matched or total is None or total > MAX_TOTAL or not statuses <= {"UNCHANGED", "BASELINE", "TESTED", "CHANGED"}:
        status = "NEEDS_INSPECTION"
    elif "CHANGED" in statuses:
        status = "DIFFERENT"
    elif statuses <= {"UNCHANGED", "BASELINE"} and "BASELINE" in statuses:
        status = "BASELINE_MATCH"
    elif statuses <= {"UNCHANGED", "TESTED"} and "TESTED" in statuses:
        status = "TESTED_MATCH"
    elif "BASELINE" in statuses and "TESTED" in statuses:
        status = "MIXED_MATCH"
        reasons.add("MIXED_BASELINE_TESTED")
    else:
        raise Refused("SNAPSHOT_PROJECT_INPUT")
    reconstruction = {"status": "NOT_CHECKED", "reason": "PROFILE_MISMATCH" if not matched else
                      "TOTAL_INPUT_LIMIT" if total is not None and total > MAX_TOTAL else "BASELINE_MATCH_REQUIRED",
                      "files_checked": 0, "patch_sha256": verified["patch_sha256"], "patch_bytes": verified["patch_bytes"]}
    pins = all(row["task_pin_match"] for row in files) if all(row["task_pin_match"] is not None for row in files) else None
    if status == "BASELINE_MATCH":
        patch = _members(archive_raw)["changes.diff"]
        reconstruction = _reconstruct(patch, observed, files)
        if reconstruction["status"] == "VERIFIED" and not _unchanged(project_root, observed):
            reconstruction.update(status="REFUSED", reason="OBSERVATION_CHANGED", files_checked=0)
            pins = None
        if reconstruction["status"] != "VERIFIED":
            status = "NEEDS_INSPECTION"
            reasons.add(reconstruction["reason"])
    result = {"version": 1, "archive_sha256": verified["archive_sha256"], "patch_sha256": verified["patch_sha256"],
              "task_sha256": sha(task_raw), "status": status, "profile": profile,
              "bundle_only": sorted(archive_names - selected_names), "project_only": sorted(selected_names - archive_names),
              "permission_differences": permissions, "files": files, "total_bytes": total, "task_pins_match": pins,
              "reasons": sorted(reasons), "not_checked": list(NOT_CHECKED) + ([] if reconstruction["status"] == "VERIFIED" else ["PATCH_RECONSTRUCTION"]),
              "limits": dict(LIMITS), "notes": list(NOTES), "reconstruction": reconstruction}
    _require(len(canonical(result)) <= MAX_REPORT, "OUTPUT_LIMIT")
    return result


def check_project(archive_raw, project_root: Path, task_raw: bytes, expected_sha256=None):
    """Observe declared files and baseline reconstruction; never apply or authorize changes."""
    try:
        return _check(archive_raw, project_root, task_raw, expected_sha256)
    except (Refused, ReadIssue, OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        raise Refused(_safe_error(error)) from None


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if args in (["--help"], ["-h"]):
            sys.stdout.write("Usage: snapshot_project_check.py /absolute/private.zip --project /absolute/project --task /absolute/task.json [--expect-sha256 HASH]\n")
            return 0
        _require(type(args) is list and len(args) in {5, 7} and all(type(arg) is str for arg in args))
        options = {}
        for key, value in zip(args[1::2], args[2::2]):
            _require(key in {"--project", "--task", "--expect-sha256"} and key not in options)
            options[key] = value
        _require({"--project", "--task"} <= set(options))
        archive_path, project_root, task_path = Path(args[0]), Path(options["--project"]), Path(options["--task"])
        for path in (archive_path, project_root, task_path):
            _path(path)
        raw = _read_named(archive_path, MAX_ARCHIVE)
        expected = options.get("--expect-sha256")
        verify_export(raw, expected)
        task_raw = _read_named(task_path, MAX_TASK)
        report = check_project(raw, project_root, task_raw, expected)
        _require(_read_named(task_path, MAX_TASK) == task_raw, "PROJECT_CHANGED")
        sys.stdout.write(canonical(report).decode("ascii"))
        return 0 if report["status"] in {"BASELINE_MATCH", "TESTED_MATCH"} else 1
    except ReadIssue as error:
        sys.stdout.write(canonical({"error": "SNAPSHOT_PROJECT_LIMIT" if str(error) == "LIMIT" else "SNAPSHOT_PROJECT_INPUT"}).decode("ascii"))
        return 2
    except (Refused, OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        sys.stdout.write(canonical({"error": _safe_error(error)}).decode("ascii"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
