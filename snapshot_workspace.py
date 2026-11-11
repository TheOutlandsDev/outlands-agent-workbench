"""Reconstruct snapshot exports and check a new private selected-file Git worktree."""

import copy
import os
import re
import signal
import stat
import sys
import time
from pathlib import Path

from agent import Refused, canonical, parse, relative, review_diff, sha, write_new
from bundle_project_check import ReadIssue, _path, _read_named, _task, read_selected
from bundle_workspace import _apply, _check_results, _directory, _install, _inspect, _inventory, _lines
from git_workspace import fixed_checks, git, validate_files
from snapshot_export import _members, verify_export
from snapshot_project_check import check_project


FORMAT = "outlands-snapshot-workspace-v1"
MAX_FILE, MAX_TOTAL, MAX_JSON, MAX_ARCHIVE, MAX_CHECKS = 32768, 131072, 262144, 2097152, 2097152
MAX_SAFE = 9007199254740991
ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
REQUEST_FIELDS = {"version", "id", "project_id", "source", "config_path", "config_sha256", "task_path",
                  "task_sha256", "archive_sha256", "preview_sha256"}
PIN_FIELDS = {"config_sha256", "task_sha256", "archive_sha256", "preview_sha256", "patch_sha256"}
CORE_FIELDS = {"version", "format", "id", "project_id", "status", "created", "source_applied"} | PIN_FIELDS
PROGRESS_FIELDS = {"baseline", "snapshot", "path", "branch", "baseline_commit", "patch_applied_to_workspace", "checks", "checks_sha256"}
CODES = frozenset("SNAPSHOT_WORKSPACE_" + suffix for suffix in (
    "INPUT", "ARCHIVE_INVALID", "ARCHIVE_CHANGED", "TASK_INVALID", "BASELINE_REQUIRED", "PATCH_INVALID", "SNAPSHOT_CHANGED",
    "LIMIT", "REQUEST_CHANGED", "SOURCE_CHANGED", "SCOPE_CHANGED", "GIT_CHANGED", "GIT_FAILED", "CHECKS_FAILED", "EXECUTION_FAILED",
    "INTERRUPTED", "PROJECT_UNKNOWN", "PROJECT_CHANGED", "INPUT_LIMIT", "OUTPUT_LIMIT", "RECORD_INVALID", "RECORD_LIMIT",
    "PREVIEW_REQUIRED", "PREVIEW_EXPIRED", "PREVIEW_CHANGED", "FIELDS", "START_FAILED", "ID"))


def _require(condition, suffix="INPUT"):
    if not condition:
        raise Refused("SNAPSHOT_WORKSPACE_" + suffix)


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _integer(value, low=0, high=MAX_SAFE):
    return type(value) is int and low <= value <= high


def _reason(error, default="EXECUTION_FAILED"):
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "SNAPSHOT_WORKSPACE_INTERRUPTED"
    code = str(error) if isinstance(error, Refused) else None
    if code in CODES:
        return code
    if isinstance(error, ReadIssue):
        return "SNAPSHOT_WORKSPACE_LIMIT" if str(error) == "LIMIT" else "SNAPSHOT_WORKSPACE_SOURCE_CHANGED"
    if code in {"SNAPSHOT_EXPORT_LIMIT", "SNAPSHOT_PROJECT_LIMIT", "SNAPSHOT_PROJECT_OUTPUT_LIMIT", "PROJECT_CHECK_LIMIT", "GIT_OUTPUT_LIMIT"}:
        return "SNAPSHOT_WORKSPACE_LIMIT"
    if code == "SNAPSHOT_EXPORT_ARCHIVE_CHANGED":
        return "SNAPSHOT_WORKSPACE_ARCHIVE_CHANGED"
    if type(code) is str and code.startswith("SNAPSHOT_EXPORT_"):
        return "SNAPSHOT_WORKSPACE_ARCHIVE_INVALID"
    if code in {"SNAPSHOT_PROJECT_TASK_INVALID", "PROJECT_CHECK_TASK_INVALID"}:
        return "SNAPSHOT_WORKSPACE_TASK_INVALID"
    if code == "GIT_CONTROL_FILE_REFUSED":
        return "SNAPSHOT_WORKSPACE_SCOPE_CHANGED"
    if type(code) is str and code.startswith("BUNDLE_WORKSPACE_"):
        suffix = code.removeprefix("BUNDLE_WORKSPACE_")
        suffix = "SNAPSHOT_CHANGED" if suffix == "CANDIDATE_CHANGED" else suffix
        mapped = "SNAPSHOT_WORKSPACE_" + suffix
        return mapped if mapped in CODES else "SNAPSHOT_WORKSPACE_" + default
    if type(code) is str and code.startswith("GIT_"):
        return "SNAPSHOT_WORKSPACE_GIT_FAILED"
    return "SNAPSHOT_WORKSPACE_" + default


def _file_map(value):
    if type(value) is not dict or not 1 <= len(value) <= 32:
        return False
    try:
        for name, digest in value.items():
            if type(name) is not str or not _hash(digest):
                return False
            relative(name)
        if len({name.lower() for name in value}) != len(value) or any(other.startswith(name + "/") for name in value for other in value):
            return False
        validate_files({"files": value})
        return True
    except (Refused, ValueError, TypeError):
        return False


def _display_checks(value, passing):
    if type(value) is not dict or not (1 <= len(value) <= 4 if passing else len(value) <= 4):
        return False
    for name, row in value.items():
        if type(name) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name) is None or type(row) is not dict:
            return False
        required = {"exit_code", "tests_ran", "timed_out", "output_limited", "infrastructure_error", "output", "display_truncated"}
        if not required <= set(row) or set(row) - required - {"kind", "phase"}:
            return False
        if not ((row["exit_code"] is None or _integer(row["exit_code"], -255, 255))
                and (row["tests_ran"] is None or _integer(row["tests_ran"]))
                and all(row[key] is None or type(row[key]) is bool for key in ("timed_out", "output_limited", "infrastructure_error"))
                and type(row["display_truncated"]) is bool):
            return False
        if row["output"] is not None:
            if type(row["output"]) is not str or len(row["output"]) > 4096:
                return False
            row["output"].encode("utf-8")
        if any(type(row[key]) is not str or len(row[key]) > 64 for key in ("kind", "phase") if key in row):
            return False
        if passing and (row["exit_code"] != 0 or not _integer(row["tests_ran"], 1)
                        or row["output"] is None or any(row[key] is not False for key in ("timed_out", "output_limited", "infrastructure_error"))):
            return False
    return True


def valid_receipt(value):
    """Recognize this distinct workspace format without filesystem reads or repair."""
    try:
        if type(value) is not dict or not CORE_FIELDS <= set(value) or set(value) - CORE_FIELDS - PROGRESS_FIELDS - {"finished", "reason"}:
            return False
        status = value["status"]
        if (type(value["version"]) is not int or value["version"] != 1 or value["format"] != FORMAT
                or type(value["id"]) is not str or ID.fullmatch(value["id"]) is None
                or type(value["project_id"]) is not str or ALIAS.fullmatch(value["project_id"]) is None
                or type(status) is not str or status not in {"PREPARING", "VERIFIED", "FAILED", "INTERRUPTED"}
                or value["source_applied"] is not False or not _integer(value["created"])
                or not all(_hash(value[key]) for key in PIN_FIELDS)):
            return False
        if status == "PREPARING":
            return set(value) == CORE_FIELDS
        if not _integer(value.get("finished")) or value["finished"] < value["created"]:
            return False
        if status in {"FAILED", "INTERRUPTED"}:
            if value.get("reason") not in CODES or (status == "INTERRUPTED") != (value["reason"] == "SNAPSHOT_WORKSPACE_INTERRUPTED"):
                return False
        elif "reason" in value:
            return False
        if ("baseline" in value) != ("snapshot" in value):
            return False
        if "baseline" in value and (not _file_map(value["baseline"]) or not _file_map(value["snapshot"])
                                    or set(value["baseline"]) != set(value["snapshot"])):
            return False
        if "checks" in value and not _display_checks(value["checks"], status == "VERIFIED"):
            return False
        if "checks_sha256" in value and not _hash(value["checks_sha256"]):
            return False
        if "branch" in value and value["branch"] != "outlands/snapshot-" + value["id"]:
            return False
        if "baseline_commit" in value and (type(value["baseline_commit"]) is not str or COMMIT.fullmatch(value["baseline_commit"]) is None):
            return False
        if "path" in value:
            if type(value["path"]) is not str:
                return False
            path = Path(value["path"])
            _path(path)
            if path.parts[-3:] != (value["id"], "workspace", "review"):
                return False
        if "patch_applied_to_workspace" in value and value["patch_applied_to_workspace"] is not True:
            return False
        return status != "VERIFIED" or (PROGRESS_FIELDS <= set(value) and value["baseline"] != value["snapshot"])
    except (Refused, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return False


def prepare(raw, source: Path, task_raw: bytes, expected_sha256=None):
    """Capture approved baseline and reconstructed snapshot bytes without writes or execution."""
    try:
        verified = verify_export(raw, expected_sha256)
        task = _task(task_raw)
        validate_files(task)
        rows = {row["path"]: row for row in verified["files"]}
        _require(task["files"] == {name: row["baseline_sha256"] for name, row in rows.items()}, "BASELINE_REQUIRED")
        comparison = check_project(raw, source, task_raw, expected_sha256)
        _require(comparison["status"] == "BASELINE_MATCH" and comparison["reconstruction"]["status"] == "VERIFIED"
                 and comparison["task_pins_match"] is True, "BASELINE_REQUIRED")
        baseline = {name: read_selected(source, name) for name in sorted(task["files"])}
        _require(sum(map(len, baseline.values())) <= MAX_TOTAL, "LIMIT")
        _require(all(sha(value) == rows[name]["baseline_sha256"] == task["files"][name] for name, value in baseline.items()), "SOURCE_CHANGED")
        members = _members(raw)
        patch = members["changes.diff"]
        changed = [name for name in sorted(rows) if rows[name]["baseline_sha256"] != rows[name]["snapshot_sha256"]]
        _require(all(name in task["editable"] for name in changed), "SCOPE_CHANGED")
        snapshot = _apply(patch, dict(baseline), changed)
        _require(set(snapshot) == set(baseline), "SCOPE_CHANGED")
        _require(sum(map(len, snapshot.values())) <= MAX_TOTAL, "LIMIT")
        for name, value in snapshot.items():
            _require(type(value) is bytes and len(value) <= MAX_FILE and b"\x00" not in value, "LIMIT")
            _lines(value)
            _require(sha(value) == rows[name]["snapshot_sha256"], "SNAPSHOT_CHANGED")
            _require(name in task["editable"] or value == baseline[name], "SNAPSHOT_CHANGED")
        regenerated = "".join(review_diff(name, baseline[name], snapshot[name]) for name in sorted(baseline)).encode("utf-8")
        _require(regenerated == patch, "PATCH_INVALID")
        summary = {"version": 1, "archive_sha256": verified["archive_sha256"], "task_sha256": sha(task_raw),
            "patch_sha256": sha(patch), "verification_sha256": verified["verification_sha256"],
            "export_snapshot_sha256": verified["hashes"]["snapshot_sha256"],
            "baseline": {name: sha(value) for name, value in baseline.items()}, "snapshot": {name: sha(value) for name, value in snapshot.items()},
            "files": [{"path": name, "editable": name in task["editable"], "baseline_sha256": sha(baseline[name]),
                       "snapshot_sha256": sha(snapshot[name])} for name in sorted(baseline)],
            "checks": [{"name": name, "spec": copy.deepcopy(spec)} for name, spec in sorted(task["checks"].items())],
            "max_turns": task["max_turns"], "request_seconds": task["request_seconds"],
            "baseline_bytes": sum(map(len, baseline.values())), "snapshot_bytes": sum(map(len, snapshot.values())), "source_applied": False}
        _require(len(canonical(summary)) <= 65536, "OUTPUT_LIMIT")
        return {"summary": summary, "task": copy.deepcopy(task), "baseline": baseline, "snapshot": snapshot}
    except (Refused, ReadIssue, OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
        raise Refused(_reason(error, "INPUT")) from None


def _project(request, task_raw):
    try:
        config_raw = _read_named(Path(request["config_path"]), MAX_JSON, text=True)
        approved_raw = _read_named(Path(request["task_path"]), MAX_JSON, text=True)
        _require(sha(config_raw) == request["config_sha256"] and sha(task_raw) == request["task_sha256"]
                 and approved_raw == task_raw, "PROJECT_CHANGED")
        config = parse(config_raw)
        _require(type(config) is dict and config.get("format") == "outlands-workbench-config-v1"
                 and type(config.get("projects")) is list and 1 <= len(config["projects"]) <= 16, "PROJECT_CHANGED")
        projects = [row for row in config["projects"] if type(row) is dict and row.get("id") == request["project_id"]]
        _require(len(projects) == 1 and projects[0].get("source") == request["source"]
                 and projects[0].get("task") == request["task_path"], "PROJECT_CHANGED")
    except (ReadIssue, OSError, ValueError, UnicodeError, KeyError, TypeError, Refused):
        raise Refused("SNAPSHOT_WORKSPACE_PROJECT_CHANGED") from None


def _git_guards(job, branch):
    common = job / "workspace/baseline-repo/.git"
    admin = common / "worktrees/review"
    paths = [job / "workspace/review/.git", common / "config", common / "HEAD", common / "refs/heads/baseline",
             common / "refs/heads" / branch, admin / "HEAD", admin / "gitdir", admin / "commondir", admin / "index"]
    return {path: _read_named(path, MAX_JSON) for path in paths}


def _worktree(work, expected, control_hash, commit, branch, changed):
    for name in expected:
        fd = _directory(work / Path(name).parent)
        try:
            info = os.stat(Path(name).name, dir_fd=fd, follow_symlinks=False)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_mode & 0o111 == 0, "GIT_CHANGED")
        finally:
            os.close(fd)
    _inspect(work, expected, control_hash, commit, branch, changed)


def _git_unchanged(job, branch, guards):
    try:
        _require(_git_guards(job, branch) == guards, "GIT_CHANGED")
    except (Refused, ReadIssue, OSError, ValueError, TypeError, UnicodeError):
        raise Refused("SNAPSHOT_WORKSPACE_GIT_CHANGED") from None


def _record(job, receipt, expected_raw):
    raw = canonical(receipt)
    _require(len(raw) <= MAX_JSON, "OUTPUT_LIMIT")
    temporary = job / "receipt.json.next"
    write_new(temporary, raw)
    _require(_read_named(job / "receipt.json", MAX_JSON, text=True) == expected_raw, "REQUEST_CHANGED")
    os.replace(temporary, job / "receipt.json")


def build(job_dir, jdk_home=None, checker=fixed_checks):
    """Create/check one new worktree; preserve terminal failures and partial files."""
    receipt = {"version": 1, "format": FORMAT, "status": "PREPARING", "created": int(time.time()), "source_applied": False, "checks": {}}
    can_record, initial_raw = False, None
    try:
        fd = _directory(job_dir, private=True)
        os.close(fd)
        _require(type(job_dir.name) is str and ID.fullmatch(job_dir.name) is not None, "INPUT")
        initial_raw = _read_named(job_dir / "receipt.json", MAX_JSON, text=True)
        initial = parse(initial_raw)
        _require(type(initial) is dict and initial.get("status") == "PREPARING", "REQUEST_CHANGED")
        can_record = True
        for key in PIN_FIELDS:
            if _hash(initial.get(key)):
                receipt[key] = initial[key]
        for key, expression in (("id", ID), ("project_id", ALIAS)):
            if type(initial.get(key)) is str and expression.fullmatch(initial[key]):
                receipt[key] = initial[key]
        if _integer(initial.get("created")):
            receipt["created"] = initial["created"]
        write_new(job_dir / "initial-receipt.json", initial_raw)
        _require(valid_receipt(initial) and initial["id"] == job_dir.name, "RECORD_INVALID")
        request_raw = _read_named(job_dir / "request.json", 32768, text=True)
        request = parse(request_raw)
        _require(type(request) is dict and set(request) == REQUEST_FIELDS and type(request["version"]) is int and request["version"] == 1
                 and request.get("id") == initial["id"] and request.get("project_id") == initial["project_id"]
                 and all(request.get(key) == initial[key] for key in PIN_FIELDS - {"patch_sha256"}), "REQUEST_CHANGED")
        for key in ("source", "config_path", "task_path"):
            _require(type(request[key]) is str, "REQUEST_CHANGED")
            _path(Path(request[key]))
        source = Path(request["source"])
        _require(job_dir != source and job_dir not in source.parents and source not in job_dir.parents, "REQUEST_CHANGED")
        _require(all(job_dir != Path(request[key]) and job_dir not in Path(request[key]).parents for key in ("config_path", "task_path")), "REQUEST_CHANGED")
        task_raw = _read_named(job_dir / "task.json", MAX_JSON, text=True)
        raw = _read_named(job_dir / "snapshot.zip", MAX_ARCHIVE)
        _require(sha(task_raw) == request["task_sha256"] and sha(raw) == request["archive_sha256"], "REQUEST_CHANGED")
        _project(request, task_raw)
        prepared = prepare(raw, source, task_raw, request["archive_sha256"])
        summary, task = prepared["summary"], prepared["task"]
        binding = {"version": 1, "project_id": request["project_id"], "archive_sha256": request["archive_sha256"],
                   "task_sha256": request["task_sha256"], "config_sha256": request["config_sha256"], "prepared": summary}
        _require(sha(canonical(binding)) == request["preview_sha256"] and summary["patch_sha256"] == initial["patch_sha256"], "REQUEST_CHANGED")
        _require(jdk_home is not None or not any(type(spec) is dict and spec.get("kind") == "java-main" for spec in task["checks"].values()), "CHECKS_FAILED")
        receipt.update(baseline=summary["baseline"], snapshot=summary["snapshot"])
        destination = job_dir / "workspace"
        destination.mkdir(mode=0o700, exist_ok=False)
        repository, template, work = destination / "baseline-repo", destination / "empty-template", destination / "review"
        repository.mkdir(mode=0o700);template.mkdir(mode=0o700)
        for name, value in prepared["baseline"].items():
            target = repository / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(target, value)
        git(repository, "init", "--object-format=sha1", "--initial-branch=baseline", "--template=" + str(template))
        git(repository, "add", "--force", "--", *sorted(task["files"]))
        git(repository, "commit", "--no-verify", "-m", "Selected snapshot-export baseline")
        commit = git(repository, "rev-parse", "HEAD").decode().strip()
        _require(COMMIT.fullmatch(commit) is not None, "GIT_CHANGED")
        branch = "outlands/snapshot-" + request["id"]
        git(repository, "worktree", "add", "-b", branch, str(work), "baseline")
        control_hash = sha(_read_named(work / ".git", MAX_FILE, text=True))
        _inventory(work, summary["baseline"], control_hash)
        for name, value in prepared["snapshot"].items():
            if value != prepared["baseline"][name]:
                _install(work, name, prepared["baseline"][name], value)
        changed = {name for name in task["files"] if summary["baseline"][name] != summary["snapshot"][name]}
        receipt.update(path=str(work), branch=branch, baseline_commit=commit, patch_applied_to_workspace=True)
        _worktree(work, summary["snapshot"], control_hash, commit, branch, changed)
        guards = _git_guards(job_dir, branch)
        full, display, passed = _check_results(checker(work, task, jdk_home), task)
        full_raw = canonical(full)
        _require(len(full_raw) <= MAX_CHECKS, "LIMIT")
        write_new(job_dir / "checks.json", full_raw)
        receipt.update(checks=display, checks_sha256=sha(full_raw))
        _project(request, task_raw)
        _require(_read_named(job_dir / "request.json", 32768, text=True) == request_raw
                 and _read_named(job_dir / "task.json", MAX_JSON, text=True) == task_raw
                 and _read_named(job_dir / "snapshot.zip", MAX_ARCHIVE) == raw, "REQUEST_CHANGED")
        _require(all(sha(read_selected(source, name)) == digest for name, digest in summary["baseline"].items()), "SOURCE_CHANGED")
        _git_unchanged(job_dir, branch, guards)
        _worktree(work, summary["snapshot"], control_hash, commit, branch, changed)
        _require(passed, "CHECKS_FAILED")
        receipt.update(status="VERIFIED", finished=int(time.time()))
        _require(valid_receipt(receipt), "RECORD_INVALID")
        _record(job_dir, receipt, initial_raw)
        return receipt
    except BaseException as error:
        code = _reason(error)
        if can_record:
            receipt.update(status="INTERRUPTED" if code == "SNAPSHOT_WORKSPACE_INTERRUPTED" else "FAILED",
                           reason=code, finished=int(time.time()), source_applied=False)
            try:
                _record(job_dir, receipt, initial_raw)
            except (Refused, OSError, ValueError, TypeError, UnicodeError):
                pass
        raise Refused(code) from None


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        _require(type(args) is list and len(args) in {2, 4} and all(type(arg) is str for arg in args))
        options = {}
        for key, value in zip(args[::2], args[1::2]):
            _require(key in {"--job-dir", "--jdk-home"} and key not in options)
            options[key] = Path(value)
            _path(options[key])
        _require("--job-dir" in options)
        def interrupted(*_):
            raise KeyboardInterrupt
        previous = signal.signal(signal.SIGTERM, interrupted)
        try:
            build(options["--job-dir"], options.get("--jdk-home"))
        finally:
            signal.signal(signal.SIGTERM, previous)
        return 0
    except BaseException as error:
        sys.stdout.write(canonical({"error": _reason(error, "INPUT")}).decode("ascii"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
