"""Read-only comparisons of verified private bundles and explicitly selected files."""

import hashlib
import os
import re
import stat
import sys
from pathlib import Path

from agent import Refused, canonical, parse, relative, validate_task
from patch_bundle import CODE_SET as BUNDLE_CODES, _members, verify_bundle


MAX_TASK = 262_144
MAX_ARCHIVE = 2_097_152
MAX_FILE = 32_768
MAX_TOTAL = 131_072
HASH = re.compile(r"[0-9a-f]{64}\Z")
CODES = frozenset({"PROJECT_CHECK_TASK_INVALID", "PROJECT_CHECK_INPUT", "PROJECT_CHECK_LIMIT", "PROJECT_CHECK_OUTPUT_LIMIT"})
NOT_CHECKED = ["TASK_GOAL", "CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "PATCH_APPLICABILITY", "GIT_ADOPTION"]
NOTES = ["PRIVATE_PROJECT_INFORMATION", "STATIC_OBSERVATIONS_ONLY", "UNSIGNED_BUNDLE"]


class ReadIssue(Exception):
    """Internal fixed per-file observation, containing no path or source text."""


def _require(condition, code="PROJECT_CHECK_INPUT"):
    if not condition:
        raise Refused(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _task(raw):
    _require(type(raw) is bytes, "PROJECT_CHECK_TASK_INVALID")
    _require(len(raw) <= MAX_TASK, "PROJECT_CHECK_LIMIT")
    try:
        value = parse(raw)
        _require(type(value) is dict and len(value) == 7, "PROJECT_CHECK_TASK_INVALID")
        _require(type(value.get("files")) is dict and 1 <= len(value["files"]) <= 32, "PROJECT_CHECK_TASK_INVALID")
        _require(all(type(path) is str and len(path) <= 128 and type(digest) is str and len(digest) == 64
                     for path, digest in value["files"].items()), "PROJECT_CHECK_TASK_INVALID")
        _require(type(value.get("editable")) is list and len(value["editable"]) <= 32
                 and all(type(path) is str and len(path) <= 128 for path in value["editable"]), "PROJECT_CHECK_TASK_INVALID")
        _require(type(value.get("checks")) is dict and len(value["checks"]) <= 4, "PROJECT_CHECK_TASK_INVALID")
        validate_task(value)
        return value
    except (Refused, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise Refused("PROJECT_CHECK_TASK_INVALID") from None


def _path(path):
    _require(isinstance(path, Path))
    name = str(path)
    _require(path.is_absolute() and 0 < len(name) <= 4096 and "\x00" not in name
             and all(part not in {".", ".."} for part in path.parts))
    _require(len(name.encode("utf-8")) <= 4096)
    parts = name.split("/")[1:]
    _require(parts and all(part for part in parts))
    return parts


def _read_named(path, limit, *, text=False):
    """Open one named file read-only, refusing links in every component."""
    parts = _path(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        child = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ReadIssue("UNREADABLE")
            if before.st_size > limit:
                raise ReadIssue("LIMIT")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > limit:
                raise ReadIssue("LIMIT")
            if (after.st_nlink != 1 or before.st_size != after.st_size or after.st_size != len(raw)
                    or before.st_mtime_ns != after.st_mtime_ns):
                raise ReadIssue("UNREADABLE")
            if text:
                if b"\x00" in raw:
                    raise ReadIssue("BINARY")
                try:
                    raw.decode("utf-8")
                except UnicodeError:
                    raise ReadIssue("UTF8") from None
            return raw
    finally:
        os.close(fd)


def read_selected(root: Path, name: str, limit=MAX_FILE) -> bytes:
    """Read only a caller-declared selected relative file, without discovery."""
    _require(type(limit) is int and 0 < limit <= MAX_FILE)
    try:
        relative(name)
    except (Refused, TypeError, ValueError):
        raise Refused("PROJECT_CHECK_INPUT") from None
    return _read_named(root / name, limit, text=True)


def _check(bundle_raw, project_root, task_raw, expected_sha256):
    verified = verify_bundle(bundle_raw, expected_sha256)
    # The public v0.9 summary intentionally omits profile format and budgets.
    # Read that member only after full archive verification; never extract it.
    manifest = parse(_members(bundle_raw)["manifest.json"])
    task = _task(task_raw)
    _path(project_root)
    bundle_files = {row["path"]: row for row in verified["files"]}
    bundle_names, project_names = set(bundle_files), set(task["files"])
    project_editable = set(task["editable"])
    permission_differences = [{"path": name, "bundle_editable": bundle_files[name]["editable"],
                               "project_editable": name in project_editable}
        for name in sorted(bundle_names & project_names)
        if bundle_files[name]["editable"] != (name in project_editable)]
    archive_profile = manifest["task_profile"]
    profile = {"format": archive_profile["format"] == task["format"], "scope": bundle_names == project_names,
        "permissions": not permission_differences, "checks": archive_profile["checks"] == task["checks"],
        "budgets": (archive_profile["max_turns"], archive_profile["request_seconds"])
                   == (task["max_turns"], task["request_seconds"])}
    reasons = {reason for key, reason in (("format", "FORMAT_MISMATCH"), ("scope", "SCOPE_MISMATCH"),
        ("permissions", "PERMISSIONS_MISMATCH"), ("checks", "CHECKS_MISMATCH"), ("budgets", "BUDGETS_MISMATCH"))
        if not profile[key]}
    files = []
    for path in sorted(bundle_names):
        archived = bundle_files[path]
        selected = path in project_names
        row = {"path": path, "editable": archived["editable"],
            "project_editable": path in project_editable if selected else None,
            "before_sha256": archived["before_sha256"], "after_sha256": archived["after_sha256"],
            "project_sha256": task["files"].get(path), "current_sha256": None, "bytes": None,
            "task_pin_match": None, "status": "NOT_CHECKED" if selected else "OUT_OF_SCOPE"}
        if all(profile.values()):
            try:
                raw = read_selected(project_root, path)
                current = _sha(raw)
                before, after = row["before_sha256"], row["after_sha256"]
                if current == before == after:
                    status = "UNCHANGED"
                elif not row["editable"]:
                    status = "CHANGED"
                elif current == before:
                    status = "BASELINE"
                elif current == after:
                    status = "CANDIDATE"
                else:
                    status = "CHANGED"
                row.update(current_sha256=current, bytes=len(raw), task_pin_match=current == row["project_sha256"], status=status)
            except FileNotFoundError:
                row["status"] = "MISSING"
            except ReadIssue as exc:
                row["status"] = str(exc) if str(exc) in {"UNREADABLE", "LIMIT", "BINARY", "UTF8"} else "UNREADABLE"
            except (OSError, ValueError, Refused):
                row["status"] = "UNREADABLE"
        reason = {"CHANGED": "SOURCE_CHANGED", "MISSING": "SOURCE_MISSING", "UNREADABLE": "SOURCE_UNREADABLE",
                  "LIMIT": "FILE_LIMIT", "BINARY": "BINARY_INPUT", "UTF8": "INVALID_UTF8"}.get(row["status"])
        if reason:
            reasons.add(reason)
        files.append(row)
    total = sum(row["bytes"] for row in files) if all(row["bytes"] is not None for row in files) else None
    if total is not None and total > MAX_TOTAL:
        reasons.add("TOTAL_INPUT_LIMIT")
    statuses = {row["status"] for row in files}
    if (not all(profile.values()) or total is None or total > MAX_TOTAL
            or not statuses <= {"UNCHANGED", "BASELINE", "CANDIDATE", "CHANGED"}):
        status = "NEEDS_INSPECTION"
    elif "CHANGED" in statuses:
        status = "DIFFERENT"
    elif statuses <= {"UNCHANGED", "BASELINE"} and "BASELINE" in statuses:
        status = "BASELINE_MATCH"
    elif statuses <= {"UNCHANGED", "CANDIDATE"} and "CANDIDATE" in statuses:
        status = "CANDIDATE_MATCH"
    elif "BASELINE" in statuses and "CANDIDATE" in statuses:
        status = "MIXED_MATCH"
        reasons.add("MIXED_BASELINE_CANDIDATE")
    else:
        raise Refused("PROJECT_CHECK_INPUT")
    pins = all(row["task_pin_match"] for row in files) if all(row["task_pin_match"] is not None for row in files) else None
    result = {"version": 1, "bundle_sha256": verified["bundle_sha256"], "task_sha256": _sha(task_raw), "status": status,
        "profile": profile, "bundle_only": sorted(bundle_names - project_names), "project_only": sorted(project_names - bundle_names),
        "permission_differences": permission_differences, "files": files, "total_bytes": total,
        "task_pins_match": pins, "reasons": sorted(reasons), "not_checked": list(NOT_CHECKED),
        "limits": {"max_files": 32, "max_file_bytes": MAX_FILE, "max_total_bytes": MAX_TOTAL, "max_archive_bytes": MAX_ARCHIVE},
        "notes": list(NOTES)}
    _require(len(canonical(result)) <= 65536, "PROJECT_CHECK_OUTPUT_LIMIT")
    return result


def _safe_error(exc):
    code = str(exc) if isinstance(exc, Refused) else None
    return code if code in CODES or code in BUNDLE_CODES else "PROJECT_CHECK_INPUT"


def check_project(bundle_raw: bytes, project_root: Path, task_raw: bytes, expected_sha256: str | None = None) -> dict:
    """Compare verified scope and observed bytes; never apply, execute, or authorize."""
    try:
        return _check(bundle_raw, project_root, task_raw, expected_sha256)
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise Refused(_safe_error(exc)) from None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv in (["--help"], ["-h"]):
            sys.stdout.write("Usage: bundle_project_check.py /absolute/private.zip --project /absolute/project --task /absolute/task.json [--expect-sha256 HASH]\n")
            return 0
        _require(type(argv) is list and len(argv) in {5, 7} and all(type(arg) is str for arg in argv))
        options = {}
        for key, value in zip(argv[1::2], argv[2::2]):
            _require(key in {"--project", "--task", "--expect-sha256"} and key not in options)
            options[key] = value
        _require({"--project", "--task"} <= set(options))
        expected = options.get("--expect-sha256")
        if expected is not None:
            _require(len(expected) == 64 and HASH.fullmatch(expected), "BUNDLE_HASH_REQUIRED")
        bundle_path, project_root, task_path = Path(argv[0]), Path(options["--project"]), Path(options["--task"])
        for path in (bundle_path, project_root, task_path):
            _path(path)
        bundle_raw = _read_named(bundle_path, MAX_ARCHIVE)
        # Validate the supplied archive before reading even the named task file.
        verify_bundle(bundle_raw, expected)
        task_raw = _read_named(task_path, MAX_TASK)
        report = check_project(bundle_raw, project_root, task_raw, expected)
        sys.stdout.write(canonical(report).decode("ascii"))
        return 0 if report["status"] in {"BASELINE_MATCH", "CANDIDATE_MATCH"} else 1
    except ReadIssue as exc:
        code = "PROJECT_CHECK_LIMIT" if str(exc) == "LIMIT" else "PROJECT_CHECK_INPUT"
        sys.stdout.write(canonical({"error": code}).decode("ascii"))
        return 2
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        sys.stdout.write(canonical({"error": _safe_error(exc)}).decode("ascii"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
