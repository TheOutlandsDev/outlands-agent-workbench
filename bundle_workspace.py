"""Reconstruct verified imported patches and check them in independent private Git workspaces."""

import copy
import os
import re
import signal
import stat
import sys
import time
from pathlib import Path

from agent import Refused, atomic_json, canonical, parse, review_diff, sha, write_new
from bundle_project_check import CODES as PROJECT_CODES, ReadIssue, _path, _read_named, _task, check_project, read_selected
from git_workspace import fixed_checks, git, validate_files
from patch_bundle import CODE_SET as BUNDLE_CODES, _members, verify_bundle


FORMAT = "outlands-bundle-workspace-v1"
ID = re.compile(r"[0-9a-f]{16}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
HUNK = re.compile(rb"@@ -(0|[1-9][0-9]*)(?:,([0-9]+))? \+(0|[1-9][0-9]*)(?:,([0-9]+))? @@\n\Z")
NO_NEWLINE = b"\\ No newline at end of file\n"
MAX_FILE, MAX_TOTAL, MAX_SAFE = 32768, 131072, 9007199254740991
REQUEST_FIELDS = {"version", "id", "project_id", "source", "config_path", "config_sha256",
                  "task_path", "task_sha256", "bundle_sha256", "preview_sha256"}
CODES = frozenset("BUNDLE_WORKSPACE_" + suffix for suffix in (
    "INPUT", "BASELINE_REQUIRED", "PATCH_INVALID", "CANDIDATE_CHANGED", "LIMIT", "REQUEST_CHANGED",
    "PROJECT_CHANGED", "SOURCE_CHANGED", "SCOPE_CHANGED", "GIT_CHANGED", "GIT_FAILED", "CHECKS_FAILED",
    "EXECUTION_FAILED", "INTERRUPTED"))


def _require(condition, suffix="INPUT"):
    if not condition:
        raise Refused("BUNDLE_WORKSPACE_" + suffix)


def _integer(value, low=0, high=MAX_SAFE):
    return type(value) is int and low <= value <= high


def _hash(value):
    return type(value) is str and len(value) == 64 and HASH.fullmatch(value) is not None


def _reason(error):
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "BUNDLE_WORKSPACE_INTERRUPTED"
    code = str(error) if isinstance(error, Refused) else None
    if code in CODES or code in PROJECT_CODES or code in BUNDLE_CODES or code in {"GIT_CONTROL_FILE_REFUSED", "JDK_REQUIRED"}:
        return code
    if type(code) is str and code.startswith("GIT_"):
        return "BUNDLE_WORKSPACE_GIT_FAILED"
    return "BUNDLE_WORKSPACE_EXECUTION_FAILED"


def _lines(raw):
    """Support ordinary UTF-8 LF/CRLF and unterminated last lines exactly."""
    text = raw.decode("utf-8")
    _require(not any(char in text for char in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"))
             and "\r" not in text.replace("\r\n", ""), "PATCH_INVALID")
    return raw.splitlines(keepends=True)


def _apply(patch, baseline, changed):
    _require(patch.endswith(b"\n") and patch.count(b"\n") <= 262144, "PATCH_INVALID")
    lines = [line + b"\n" for line in patch.split(b"\n")[:-1]]
    position, output = 0, dict(baseline)
    for name in changed:
        _require(position + 2 <= len(lines) and lines[position] == ("--- a/" + name + "\n").encode("ascii")
                 and lines[position + 1] == ("+++ b/" + name + "\n").encode("ascii"), "PATCH_INVALID")
        position += 2
        original = _lines(baseline[name])
        consumed, candidate, hunks = 0, [], 0
        while position < len(lines) and lines[position].startswith(b"@@ "):
            match = HUNK.fullmatch(lines[position])
            _require(match is not None and all(group is None or len(group) <= 6 for group in match.groups()), "PATCH_INVALID")
            old_start, old_count, new_start, new_count = (int(match[1]), int(match[2] or b"1"),
                                                         int(match[3]), int(match[4] or b"1"))
            _require(all(number <= MAX_FILE + 1 for number in (old_start, old_count, new_start, new_count))
                     and (old_count == 0 or old_start > 0) and (new_count == 0 or new_start > 0), "PATCH_INVALID")
            old_index = old_start - 1 if old_count else old_start
            new_index = new_start - 1 if new_count else new_start
            _require(consumed <= old_index <= len(original) and old_index + old_count <= len(original), "PATCH_INVALID")
            candidate.extend(original[consumed:old_index])
            _require(new_index == len(candidate), "PATCH_INVALID")
            consumed, used_old, used_new = old_index, 0, 0
            position += 1
            while used_old < old_count or used_new < new_count:
                _require(position < len(lines) and lines[position][:1] in {b" ", b"-", b"+"}, "PATCH_INVALID")
                kind, payload = lines[position][:1], lines[position][1:]
                position += 1
                if position < len(lines) and lines[position] == NO_NEWLINE:
                    payload = payload[:-1]
                    position += 1
                if kind != b"+":
                    _require(used_old < old_count and consumed < len(original) and original[consumed] == payload, "PATCH_INVALID")
                    consumed += 1
                    used_old += 1
                if kind != b"-":
                    _require(used_new < new_count, "PATCH_INVALID")
                    candidate.append(payload)
                    used_new += 1
            hunks += 1
        _require(hunks > 0, "PATCH_INVALID")
        candidate.extend(original[consumed:])
        _require(all(line.endswith(b"\n") for line in candidate[:-1]), "PATCH_INVALID")
        raw = b"".join(candidate)
        _require(len(raw) <= MAX_FILE and b"\x00" not in raw, "LIMIT")
        _lines(raw)
        output[name] = raw
    _require(position == len(lines), "PATCH_INVALID")
    return output


def prepare(raw, source, task_raw, expected_sha256=None):
    """Read approved baseline bytes and reconstruct every candidate without executing."""
    try:
        verified = verify_bundle(raw, expected_sha256)
        task = _task(task_raw)
        validate_files(task)
        comparison = check_project(raw, source, task_raw, expected_sha256)
        _require(comparison["status"] == "BASELINE_MATCH" and comparison["task_pins_match"] is True, "BASELINE_REQUIRED")
        rows = {row["path"]: row for row in verified["files"]}
        baseline = {name: read_selected(source, name) for name in sorted(task["files"])}
        _require(sum(map(len, baseline.values())) <= MAX_TOTAL, "LIMIT")
        _require(all(sha(value) == rows[name]["before_sha256"] == task["files"][name]
                     for name, value in baseline.items()), "SOURCE_CHANGED")
        patch = _members(raw)["changes.diff"]
        changed = [name for name in sorted(rows) if rows[name]["before_sha256"] != rows[name]["after_sha256"]]
        _require(all(name in task["editable"] for name in changed), "PATCH_INVALID")
        candidate = _apply(patch, baseline, changed)
        _require(sum(map(len, candidate.values())) <= MAX_TOTAL, "LIMIT")
        _require(all(sha(value) == rows[name]["after_sha256"] for name, value in candidate.items()), "CANDIDATE_CHANGED")
        _require(all(candidate[name] == baseline[name] for name in baseline if name not in task["editable"]), "CANDIDATE_CHANGED")
        regenerated = "".join(review_diff(name, baseline[name], candidate[name]) for name in sorted(baseline)).encode("utf-8")
        _require(regenerated == patch, "PATCH_INVALID")
        summary = {"version": 1, "archive_sha256": sha(raw), "task_sha256": sha(task_raw), "patch_sha256": sha(patch),
            "baseline": {name: sha(value) for name, value in baseline.items()},
            "candidate": {name: sha(value) for name, value in candidate.items()},
            "files": [{"path": name, "editable": name in task["editable"], "before_sha256": sha(baseline[name]),
                       "after_sha256": sha(candidate[name])} for name in sorted(baseline)],
            "checks": [{"name": name, "spec": copy.deepcopy(spec)} for name, spec in sorted(task["checks"].items())],
            "max_turns": task["max_turns"], "request_seconds": task["request_seconds"],
            "baseline_bytes": sum(map(len, baseline.values())), "candidate_bytes": sum(map(len, candidate.values())),
            "source_applied": False}
        _require(len(canonical(summary)) <= 65536, "LIMIT")
        return {"summary": summary, "task": copy.deepcopy(task), "baseline": baseline, "candidate": candidate}
    except (ReadIssue, OSError):
        raise Refused("BUNDLE_WORKSPACE_SOURCE_CHANGED") from None
    except (Refused, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
        raise Refused(_reason(error)) from None


def _directory(path, *, private=False):
    parts = _path(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        _require(not private or info.st_uid == os.getuid() and info.st_mode & 0o077 == 0)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _inventory(root, expected, control_hash):
    directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
    found, count = set(), 0
    def walk(fd, prefix):
        nonlocal count
        with os.scandir(fd) as entries:
            for entry in entries:
                count += 1
                _require(count <= 512, "SCOPE_CHANGED")
                name = prefix + entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _require(name in directories, "SCOPE_CHANGED")
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child, name + "/")
                    finally:
                        os.close(child)
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                             and (name in expected or name == ".git"), "SCOPE_CHANGED")
                    found.add(name)
    fd = _directory(root)
    try:
        walk(fd, "")
    finally:
        os.close(fd)
    _require(found == set(expected) | {".git"}, "SCOPE_CHANGED")
    _require(sha(_read_named(root / ".git", MAX_FILE, text=True)) == control_hash, "GIT_CHANGED")
    for name, digest in expected.items():
        _require(sha(read_selected(root, name)) == digest, "CANDIDATE_CHANGED")


def _install(root, name, before, after):
    fd = _directory(root / Path(name).parent)
    try:
        child = os.open(Path(name).name, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(child, "r+b") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stream.read(MAX_FILE + 1) == before, "CANDIDATE_CHANGED")
            stream.seek(0)
            stream.write(after)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _inspect(work, expected, control_hash, commit, branch, changed):
    _inventory(work, expected, control_hash)
    _require(git(work, "rev-parse", "HEAD").decode().strip() == commit
             and git(work, "symbolic-ref", "--short", "HEAD").decode().strip() == branch, "GIT_CHANGED")
    actual = {name.decode("utf-8") for name in git(work, "diff", "--name-only", "-z", "HEAD", "--").split(b"\x00") if name}
    _require(actual == changed and git(work, "diff", "--cached", "--name-only", "-z", "--") == b"", "GIT_CHANGED")


def _check_results(results, task):
    scope = type(results) is dict and set(results) == set(task["checks"])
    results = results if type(results) is dict else {}
    full, display, passed = {}, {}, scope
    for name in sorted(task["checks"]):
        raw = results.get(name)
        raw = raw if type(raw) is dict else {}
        row = {key: raw.get(key) for key in ("exit_code", "tests_ran", "timed_out", "output_limited", "infrastructure_error")}
        valid = (_integer(row["exit_code"], -255, 255) and _integer(row["tests_ran"])
                 and all(type(row[key]) is bool for key in ("timed_out", "output_limited", "infrastructure_error")))
        output = raw.get("output", "")
        if type(output) is not str or len(output) > 65536:
            output, valid = None, False
        if output is not None:
            try:
                output.encode("utf-8")
            except UnicodeError:
                output, valid = None, False
        # Keep only finite observations, including invalid/missing core values as unknown.
        for key in row:
            if key in {"exit_code", "tests_ran"}:
                if not _integer(row[key], -255 if key == "exit_code" else 0, 255 if key == "exit_code" else MAX_SAFE):
                    row[key] = None
            elif type(row[key]) is not bool:
                row[key] = None
        passed = passed and valid and row["exit_code"] == 0 and row["tests_ran"] > 0 and all(
            row[key] is False for key in ("timed_out", "output_limited", "infrastructure_error"))
        for key in ("kind", "phase"):
            if type(raw.get(key)) is str and len(raw[key]) <= 64:
                row[key] = raw[key]
        full[name] = {**row, "output": output}
        display[name] = {**row, "output": output[:4096] if output is not None else None,
                         "display_truncated": output is not None and len(output) > 4096}
    return full, display, bool(passed)


def _pins(request, task_raw):
    _require(sha(_read_named(Path(request["config_path"]), 262144, text=True)) == request["config_sha256"]
             and sha(_read_named(Path(request["task_path"]), 262144, text=True)) == request["task_sha256"]
             and sha(task_raw) == request["task_sha256"], "PROJECT_CHANGED")


def build(job_dir, jdk_home=None, checker=fixed_checks):
    """Run one staged job; retain failure receipts and partial private workspace files."""
    receipt = {"version": 1, "format": FORMAT, "status": "PREPARING", "created": int(time.time()),
               "source_applied": False, "checks": {}}
    can_record = False
    try:
        fd = _directory(job_dir, private=True)
        os.close(fd)
        initial_raw = _read_named(job_dir / "receipt.json", 262144, text=True)
        initial = parse(initial_raw)
        _require(type(initial) is dict and initial.get("status") == "PREPARING", "REQUEST_CHANGED")
        can_record = True
        # Retain the already-staged local approval pins even if request parsing,
        # config reads, source checks or archive verification subsequently fail.
        for key in ("config_sha256", "task_sha256", "bundle_sha256", "preview_sha256", "patch_sha256"):
            if _hash(initial.get(key)):
                receipt[key] = initial[key]
        if type(initial.get("id")) is str and ID.fullmatch(initial["id"]):
            receipt["id"] = initial["id"]
        if type(initial.get("project_id")) is str and ALIAS.fullmatch(initial["project_id"]):
            receipt["project_id"] = initial["project_id"]
        if _integer(initial.get("created")):
            receipt["created"] = initial["created"]
        write_new(job_dir / "initial-receipt.json", initial_raw)
        request_raw = _read_named(job_dir / "request.json", 32768, text=True)
        request = parse(request_raw)
        _require(type(request) is dict and set(request) == REQUEST_FIELDS and type(request["version"]) is int
                 and request["version"] == 1 and type(request["id"]) is str and ID.fullmatch(request["id"])
                 and request["id"] == job_dir.name and type(request["project_id"]) is str
                 and ALIAS.fullmatch(request["project_id"])
                 and all(_hash(request[key]) for key in ("config_sha256", "task_sha256", "bundle_sha256", "preview_sha256")), "REQUEST_CHANGED")
        for key in ("source", "config_path", "task_path"):
            _require(type(request[key]) is str)
            _path(Path(request[key]))
        source = Path(request["source"])
        _require(job_dir != source and job_dir not in source.parents and source not in job_dir.parents)
        _require(all(job_dir not in Path(request[key]).parents for key in ("config_path", "task_path")))
        receipt.update({key: request[key] for key in ("id", "project_id", "config_sha256", "task_sha256", "bundle_sha256", "preview_sha256")})
        _require(initial.get("id") == request["id"] and initial.get("source_applied") is False
                 and ("created" not in initial or _integer(initial["created"]))
                 and all(key not in initial or initial[key] == request[key] for key in
                         ("project_id", "config_sha256", "task_sha256", "bundle_sha256", "preview_sha256")), "REQUEST_CHANGED")
        receipt["created"] = initial.get("created", receipt["created"])
        task_raw = _read_named(job_dir / "task.json", 262144, text=True)
        raw = _read_named(job_dir / "bundle.zip", 2097152)
        _pins(request, task_raw)
        _require(sha(raw) == request["bundle_sha256"], "REQUEST_CHANGED")
        prepared = prepare(raw, source, task_raw, request["bundle_sha256"])
        summary, task = prepared["summary"], prepared["task"]
        binding = {"version": 1, "project_id": request["project_id"], "bundle_sha256": request["bundle_sha256"],
                   "task_sha256": request["task_sha256"], "config_sha256": request["config_sha256"], "prepared": summary}
        _require(sha(canonical(binding)) == request["preview_sha256"]
                 and ("patch_sha256" not in initial or initial["patch_sha256"] == summary["patch_sha256"]), "REQUEST_CHANGED")
        _require(jdk_home is not None or not any(isinstance(spec, dict) and spec.get("kind") == "java-main"
                 for spec in task["checks"].values()), "CHECKS_FAILED")
        receipt.update(patch_sha256=summary["patch_sha256"], baseline=summary["baseline"], candidate=summary["candidate"])
        destination = job_dir / "workspace"
        destination.mkdir(mode=0o700, exist_ok=False)
        repository, template, work = destination / "baseline-repo", destination / "empty-template", destination / "review"
        repository.mkdir(mode=0o700)
        template.mkdir(mode=0o700)
        for name, value in prepared["baseline"].items():
            target = repository / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(target, value)
        git(repository, "init", "--object-format=sha1", "--initial-branch=baseline", "--template=" + str(template))
        git(repository, "add", "--force", "--", *sorted(task["files"]))
        git(repository, "commit", "--no-verify", "-m", "Selected bundle baseline")
        commit = git(repository, "rev-parse", "HEAD").decode().strip()
        _require(re.fullmatch(r"[0-9a-f]{40}", commit), "GIT_CHANGED")
        branch = "outlands/bundle-" + request["id"]
        git(repository, "worktree", "add", "-b", branch, str(work), "baseline")
        control_hash = sha(_read_named(work / ".git", MAX_FILE, text=True))
        _inventory(work, summary["baseline"], control_hash)
        for name, value in prepared["candidate"].items():
            if value != prepared["baseline"][name]:
                _install(work, name, prepared["baseline"][name], value)
        changed = {name for name in task["files"] if summary["baseline"][name] != summary["candidate"][name]}
        receipt.update(branch=branch, baseline_commit=commit, path=str(work), patch_applied_to_workspace=True)
        _inspect(work, summary["candidate"], control_hash, commit, branch, changed)
        full, display, passed = _check_results(checker(work, task, jdk_home), task)
        full_raw = canonical(full)
        _require(len(full_raw) <= 2097152, "LIMIT")
        write_new(job_dir / "checks.json", full_raw)
        receipt.update(checks=display, checks_sha256=sha(full_raw))
        _pins(request, task_raw)
        _require(_read_named(job_dir / "request.json", 32768, text=True) == request_raw
                 and _read_named(job_dir / "task.json", 262144, text=True) == task_raw
                 and sha(_read_named(job_dir / "bundle.zip", 2097152)) == request["bundle_sha256"], "REQUEST_CHANGED")
        _require(all(sha(read_selected(source, name)) == digest for name, digest in summary["baseline"].items()), "SOURCE_CHANGED")
        _inspect(work, summary["candidate"], control_hash, commit, branch, changed)
        _require(passed, "CHECKS_FAILED")
        receipt.update(status="VERIFIED", finished=int(time.time()))
        _require(len(canonical(receipt)) <= 262144, "LIMIT")
        atomic_json(job_dir / "receipt.json", receipt)
        return receipt
    except BaseException as error:
        code = _reason(error)
        if can_record:
            receipt.update(status="INTERRUPTED" if code == "BUNDLE_WORKSPACE_INTERRUPTED" else "FAILED",
                           reason=code, finished=int(time.time()), source_applied=False)
            atomic_json(job_dir / "receipt.json", receipt)
        raise Refused(code) from None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        _require(type(argv) is list and len(argv) in {2, 4} and all(type(arg) is str for arg in argv))
        options = {}
        for key, value in zip(argv[::2], argv[1::2]):
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
        sys.stdout.write(canonical({"error": _reason(error)}).decode("ascii"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
