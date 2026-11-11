"""Inspect imported review workspaces without Git execution; recheck pinned private copies."""

import copy
import hashlib
import os
import re
import signal
import stat
import struct
import sys
import time
import zlib
from pathlib import Path

from agent import Refused, atomic_json, canonical, parse, relative, sha, write_new
from bundle_project_check import ReadIssue, _path, _read_named, read_selected
from bundle_workspace import FORMAT as CREATION_FORMAT, REQUEST_FIELDS as CREATION_REQUEST_FIELDS
from bundle_workspace import _check_results, _directory, _pins, prepare
from git_workspace import fixed_checks


FORMAT = "outlands-workspace-recheck-v1"
MAX_FILE, MAX_TOTAL, MAX_SAFE = 32768, 131072, 9007199254740991
ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
REQUEST_FIELDS = {"version", "id", "workspace_id", "job_dir", "preview_sha256", "creation_sha256", "history_sha256"}
CODES = frozenset("RECHECK_" + suffix for suffix in ("INPUT", "RECORD_INVALID", "LIMIT", "OUTPUT_LIMIT",
    "CREATION_REQUIRED", "STALE", "PROTECTED_CHANGED", "GIT_CHANGED", "INDEX_INVALID", "CHECKS_FAILED",
    "INTERRUPTED", "EXECUTION_FAILED", "START_FAILED"))


def _require(condition, suffix="RECORD_INVALID"):
    if not condition:
        raise Refused("RECHECK_" + suffix)


def _integer(value, low=0, high=MAX_SAFE):
    return type(value) is int and low <= value <= high


def _hash(value):
    return type(value) is str and len(value) == 64 and HASH.fullmatch(value) is not None


def _id(value):
    return type(value) is str and len(value) == 16 and ID.fullmatch(value) is not None


def _reason(error):
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "RECHECK_INTERRUPTED"
    code = str(error) if isinstance(error, Refused) else None
    return code if code in CODES else "RECHECK_EXECUTION_FAILED"


def _inventory(root, names, allow_git=False):
    directories = {str(parent) for name in names for parent in Path(name).parents if str(parent) != "."}
    found, count = set(), 0
    def walk(fd, prefix):
        nonlocal count
        with os.scandir(fd) as entries:
            for entry in entries:
                count += 1
                _require(count <= 512, "LIMIT")
                name, info = prefix + entry.name, entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _require(name in directories)
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child, name + "/")
                    finally:
                        os.close(child)
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                             and (name in names or allow_git and name == ".git"))
                    _require(info.st_mode & 0o111 == 0, "GIT_CHANGED")
                    found.add(name)
    fd = _directory(root)
    try:
        walk(fd, "")
    finally:
        os.close(fd)
    _require(found == set(names) | ({".git"} if allow_git else set()))


def _target(raw, base, expected, job, prefix=b""):
    _require(type(raw) is bytes and len(raw) <= 4096 and raw.endswith(b"\n") and raw.count(b"\n") == 1
             and b"\x00" not in raw and b"\r" not in raw and raw.startswith(prefix), "GIT_CHANGED")
    text = raw[len(prefix):-1].decode("utf-8")
    _require(bool(text), "GIT_CHANGED")
    barrier = list(job.parts[1:])
    if text.startswith("/"):
        parts = text.split("/")[1:]
        _require(parts[:len(barrier)] == barrier, "GIT_CHANGED")
        stack, parts = list(barrier), parts[len(barrier):]
    else:
        stack, parts = list(base.parts[1:]), text.split("/")
    for part in parts:
        _require(bool(part), "GIT_CHANGED")
        if part == ".":
            continue
        if part == "..":
            _require(len(stack) > len(barrier), "GIT_CHANGED")
            stack.pop()
        else:
            stack.append(part)
    _require(Path("/", *stack) == expected, "GIT_CHANGED")


def _config(raw):
    text = raw.decode("ascii")
    lines = text.splitlines()
    _require(lines and lines[0] == "[core]", "GIT_CHANGED")
    values = {}
    for line in lines[1:]:
        match = re.fullmatch(r"[ \t]+([a-z]+) = (0|true|false)", line)
        _require(match is not None and match[1] not in values, "GIT_CHANGED")
        values[match[1]] = match[2]
    _require(set(values) == {"repositoryformatversion", "filemode", "bare", "logallrefupdates"}
             and values["repositoryformatversion"] == "0" and values["filemode"] in {"true", "false"}
             and values["bare"] == "false" and values["logallrefupdates"] == "true", "GIT_CHANGED")


def _objects(baseline):
    """Compute the exact selected SHA1 Git blob/tree identities independently."""
    nodes, blobs = {"": {}}, {}
    for path, raw in baseline.items():
        oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\x00" + raw).digest()
        blobs[path] = oid
        pieces = path.split("/")
        for index in range(len(pieces)):
            parent = "/".join(pieces[:index])
            if index == len(pieces) - 1:
                nodes.setdefault(parent, {})[pieces[index]] = (False, oid)
            else:
                child = "/".join(pieces[:index + 1])
                nodes.setdefault(parent, {})[pieces[index]] = (True, child)
                nodes.setdefault(child, {})
    trees = {}
    def make(path):
        content = b""
        rows = nodes[path]
        for name in sorted(rows, key=lambda name: name.encode() + (b"/" if rows[name][0] else b"")):
            directory, value = rows[name]
            oid = make(value) if directory else value
            content += (b"40000 " if directory else b"100644 ") + name.encode() + b"\x00" + oid
        framed = b"tree " + str(len(content)).encode() + b"\x00" + content
        oid = hashlib.sha1(framed).digest()
        trees[path] = {"oid": oid, "raw": framed, "subtrees": sorted(name for name in rows if rows[name][0]),
                       "entries": sum(name.startswith(path + "/") if path else True for name in baseline)}
        return oid
    make("")
    return blobs, trees


def _tree_extension(raw, trees):
    cursor, seen = 0, set()
    def entry(parent):
        nonlocal cursor
        end = raw.find(b"\x00", cursor, min(len(raw), cursor + 130))
        _require(end >= cursor, "INDEX_INVALID")
        name = raw[cursor:end].decode("ascii")
        cursor = end + 1
        path = parent + "/" + name if parent and name else name
        _require(path in trees and path not in seen, "INDEX_INVALID")
        seen.add(path)
        end = raw.find(b"\n", cursor, min(len(raw), cursor + 32))
        _require(end >= cursor, "INDEX_INVALID")
        match = re.fullmatch(rb"(-1|[0-9]{1,3}) ([0-9]{1,3})", raw[cursor:end])
        _require(match is not None, "INDEX_INVALID")
        count, children = int(match[1]), int(match[2])
        cursor = end + 1
        expected = trees[path]
        _require((count == -1 or count == expected["entries"]) and children == len(expected["subtrees"]), "INDEX_INVALID")
        if count != -1:
            _require(raw[cursor:cursor + 20] == expected["oid"], "INDEX_INVALID")
            cursor += 20
        for _ in range(children):
            entry(path)
    entry("")
    _require(cursor == len(raw) and seen == set(trees), "INDEX_INVALID")


def _fsmonitor(raw, entry_count):
    """Bound and validate cache framing; never use its token/bitmap as authority."""
    _require(17 <= len(raw) <= 2048 and struct.unpack_from(">I", raw, 0)[0] == 2, "INDEX_INVALID")
    end = raw.find(b"\x00", 4, min(len(raw), 1029))
    _require(end >= 4 and end + 5 <= len(raw), "INDEX_INVALID")
    length = struct.unpack_from(">I", raw, end + 1)[0]
    bitmap = raw[end + 5:]
    _require(length == len(bitmap) and 20 <= length <= 524, "INDEX_INVALID")
    bits, word_count = struct.unpack_from(">II", bitmap, 0)
    _require(bits <= entry_count and 1 <= word_count <= 64 and length == 12 + word_count * 8, "INDEX_INVALID")
    words = struct.unpack_from(">" + "Q" * word_count, bitmap, 8)
    last_rlw = struct.unpack_from(">I", bitmap, 8 + word_count * 8)[0]
    cursor, controls, expanded = 0, [], []
    while cursor < word_count:
        controls.append(cursor)
        word = words[cursor]
        run, literals = (word >> 1) & 0xffffffff, word >> 33
        _require(cursor + 1 + literals <= word_count and len(expanded) + run + literals <= (bits + 63) // 64, "INDEX_INVALID")
        expanded.extend([0xffffffffffffffff if word & 1 else 0] * run)
        expanded.extend(words[cursor + 1:cursor + 1 + literals])
        cursor += 1 + literals
    _require(last_rlw == controls[-1] and len(expanded) == (bits + 63) // 64, "INDEX_INVALID")
    if bits % 64:
        _require(expanded[-1] >> (bits % 64) == 0, "INDEX_INVALID")


def _index(raw, baseline, blobs, trees):
    _require(32 <= len(raw) <= 262144 and raw[:4] == b"DIRC"
             and hashlib.sha1(raw[:-20]).digest() == raw[-20:], "INDEX_INVALID")
    version, count = struct.unpack_from(">II", raw, 4)
    _require(version == 2 and count == len(baseline) and 1 <= count <= 32, "INDEX_INVALID")
    cursor, names = 12, []
    for _ in range(count):
        start = cursor
        _require(cursor + 62 < len(raw) - 20, "INDEX_INVALID")
        mode = struct.unpack_from(">I", raw, cursor + 24)[0]
        oid, flags = raw[cursor + 40:cursor + 60], struct.unpack_from(">H", raw, cursor + 60)[0]
        _require(mode == 0o100644 and flags & 0xf000 == 0, "INDEX_INVALID")
        end = raw.find(b"\x00", cursor + 62, min(len(raw) - 20, cursor + 62 + 129))
        _require(end >= cursor + 62, "INDEX_INVALID")
        name = raw[cursor + 62:end].decode("ascii")
        _require(name in baseline and name not in names and flags & 0xfff == len(name) and oid == blobs[name], "INDEX_INVALID")
        cursor = start + ((62 + len(name) + 1 + 7) // 8) * 8
        _require(cursor <= len(raw) - 20 and raw[end:cursor] == b"\x00" * (cursor - end), "INDEX_INVALID")
        names.append(name)
    _require(names == sorted(baseline), "INDEX_INVALID")
    extensions = set()
    while cursor < len(raw) - 20:
        _require(cursor + 8 <= len(raw) - 20, "INDEX_INVALID")
        signature = raw[cursor:cursor + 4]
        _require(signature in {b"TREE", b"FSMN"} and signature not in extensions, "INDEX_INVALID")
        size = struct.unpack_from(">I", raw, cursor + 4)[0]
        _require(size <= 32768 and cursor + 8 + size <= len(raw) - 20, "INDEX_INVALID")
        payload = raw[cursor + 8:cursor + 8 + size]
        if signature == b"TREE":
            _tree_extension(payload, trees)
        else:
            _fsmonitor(payload, count)
        cursor += 8 + size
        extensions.add(signature)
    _require(cursor == len(raw) - 20, "INDEX_INVALID")


def _object(common, oid, expected=None):
    path = common / "objects" / oid[:2] / oid[2:]
    compressed = _read_named(path, 262144)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, 262145)
    _require(len(raw) <= 262144 and decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data
             and hashlib.sha1(raw).hexdigest() == oid, "GIT_CHANGED")
    if expected is not None:
        _require(raw == expected, "GIT_CHANGED")
    return raw


def _git_metadata(job, branch, commit, baseline):
    work = job / "workspace/review"
    common = job / "workspace/baseline-repo/.git"
    admin = common / "worktrees/review"
    guards = []
    def read(path, limit=32768):
        value = _read_named(path, limit)
        guards.append({"path": path.relative_to(job).as_posix(), "sha256": sha(value), "bytes": len(value)})
        return value
    _target(read(work / ".git", 4096), work, admin, job, b"gitdir: ")
    common_dir = read(admin / "commondir", 4096)
    _require(common_dir == b"../..\n", "GIT_CHANGED")
    _target(common_dir, admin, common, job)
    _target(read(admin / "gitdir", 4096), admin, work / ".git", job)
    _require(read(admin / "HEAD", 256) == ("ref: refs/heads/" + branch + "\n").encode(), "GIT_CHANGED")
    _require(read(common / "HEAD", 256) == b"ref: refs/heads/baseline\n", "GIT_CHANGED")
    expected = (commit + "\n").encode()
    _require(read(common / "refs/heads/baseline", 128) == expected
             and read(common / "refs/heads" / branch, 128) == expected, "GIT_CHANGED")
    _config(read(common / "config", 32768))
    blobs, trees = _objects(baseline)
    _index(read(admin / "index", 262144), baseline, blobs, trees)
    commit_raw = _object(common, commit)
    header, separator, body = commit_raw.partition(b"\x00")
    _require(separator and header == b"commit " + str(len(body)).encode(), "GIT_CHANGED")
    headers = body.split(b"\n\n", 1)[0].split(b"\n")
    _require(len(headers) == 3 and headers[0] == b"tree " + trees[""]["oid"].hex().encode()
             and headers[1].startswith(b"author ") and headers[2].startswith(b"committer "), "GIT_CHANGED")
    for tree in trees.values():
        _object(common, tree["oid"].hex(), tree["raw"])
    for path, oid in blobs.items():
        value = baseline[path]
        _object(common, oid.hex(), b"blob " + str(len(value)).encode() + b"\x00" + value)
    return sorted(guards, key=lambda row: row["path"])


def _inspect(job, expected_creation_sha256):
    fd = _directory(job, private=True)
    os.close(fd)
    _require(_id(job.name), "INPUT")
    creation_raw = _read_named(job / "receipt.json", 262144, text=True)
    creation = parse(creation_raw)
    if expected_creation_sha256 is not None:
        _require(_hash(expected_creation_sha256), "INPUT")
        _require(sha(creation_raw) == expected_creation_sha256, "STALE")
    _require(type(creation) is dict and creation.get("status") == "VERIFIED", "CREATION_REQUIRED")
    _require(type(creation.get("version")) is int and creation["version"] == 1 and creation.get("format") == CREATION_FORMAT
             and creation.get("id") == job.name and type(creation.get("project_id")) is str
             and ALIAS.fullmatch(creation["project_id"]) and creation.get("source_applied") is False
             and creation.get("patch_applied_to_workspace") is True and _integer(creation.get("created"))
             and _integer(creation.get("finished")) and all(_hash(creation.get(key)) for key in
                 ("config_sha256", "task_sha256", "bundle_sha256", "preview_sha256", "patch_sha256", "checks_sha256")))
    branch, commit = "outlands/bundle-" + job.name, creation.get("baseline_commit")
    _require(creation.get("branch") == branch and type(commit) is str and COMMIT.fullmatch(commit)
             and creation.get("path") == str(job / "workspace/review"), "GIT_CHANGED")
    request_raw = _read_named(job / "request.json", 32768, text=True)
    request = parse(request_raw)
    _require(type(request) is dict and set(request) == CREATION_REQUEST_FIELDS and type(request["version"]) is int
             and request["version"] == 1 and request["id"] == job.name
             and all(request.get(key) == creation[key] for key in
                 ("project_id", "config_sha256", "task_sha256", "bundle_sha256", "preview_sha256")))
    for key in ("source", "config_path", "task_path"):
        _require(type(request[key]) is str)
        _path(Path(request[key]))
        _require(job not in Path(request[key]).parents and Path(request[key]) != job)
    source = Path(request["source"])
    _require(source not in job.parents)
    task_raw = _read_named(job / "task.json", 262144, text=True)
    _pins(request, task_raw)
    config = parse(_read_named(Path(request["config_path"]), 262144, text=True))
    _require(type(config) is dict and config.get("format") == "outlands-workbench-config-v1"
             and type(config.get("projects")) is list and 1 <= len(config["projects"]) <= 16)
    projects = [row for row in config["projects"] if type(row) is dict and row.get("id") == request["project_id"]]
    _require(len(projects) == 1 and projects[0].get("source") == request["source"] and projects[0].get("task") == request["task_path"])
    raw = _read_named(job / "bundle.zip", 2097152)
    prepared = prepare(raw, source, task_raw, creation["bundle_sha256"])
    task, previous = prepared["task"], prepared["summary"]
    _require(sha(raw) == creation["bundle_sha256"] and sha(task_raw) == creation["task_sha256"]
             and previous["patch_sha256"] == creation["patch_sha256"]
             and creation.get("baseline") == previous["baseline"] and creation.get("candidate") == previous["candidate"])
    binding = {"version": 1, "project_id": request["project_id"], "bundle_sha256": sha(raw),
               "task_sha256": sha(task_raw), "config_sha256": request["config_sha256"], "prepared": previous}
    _require(sha(canonical(binding)) == creation["preview_sha256"])
    _, _, passing = _check_results(creation.get("checks"), task)
    _require(passing and sha(_read_named(job / "checks.json", 2097152)) == creation["checks_sha256"])
    work = job / "workspace/review"
    _inventory(work, task["files"], allow_git=True)
    guards = _git_metadata(job, branch, commit, prepared["baseline"])
    selected = {name: read_selected(work, name) for name in sorted(task["files"])}
    _require(sum(map(len, selected.values())) <= MAX_TOTAL, "LIMIT")
    files = []
    for name, value in selected.items():
        editable = name in task["editable"]
        created_hash, current = previous["candidate"][name], sha(value)
        _require(editable or current == created_hash, "PROTECTED_CHANGED")
        files.append({"path": name, "editable": editable, "created_sha256": created_hash,
                      "current_sha256": current, "bytes": len(value), "changed": current != created_hash})
    pins = {"creation_sha256": sha(creation_raw), "request_sha256": sha(request_raw), "bundle_sha256": sha(raw),
            "task_sha256": sha(task_raw), "config_sha256": request["config_sha256"]}
    snapshot = {"files": {row["path"]: row["current_sha256"] for row in files}, "guards": guards, **pins}
    summary = {"version": 1, "workspace_id": job.name, **pins, "patch_sha256": creation["patch_sha256"],
        "baseline_commit": commit, "branch": branch, "files": files, "changed_files": sum(row["changed"] for row in files),
        "guards": guards, "snapshot_sha256": sha(canonical(snapshot)),
        "checks": [{"name": name, "spec": copy.deepcopy(spec)} for name, spec in sorted(task["checks"].items())],
        "max_turns": task["max_turns"], "request_seconds": task["request_seconds"],
        "total_bytes": sum(map(len, selected.values())), "source_applied": False}
    _require(len(canonical(summary)) <= 65536, "OUTPUT_LIMIT")
    return {"summary": summary, "task": task, "selected_bytes": selected}


def inspect(job_dir, expected_creation_sha256=None):
    """Read eligible owner edits and pinned metadata without invoking Git or writing."""
    try:
        return _inspect(job_dir, expected_creation_sha256)
    except Refused as error:
        raise Refused(str(error) if str(error) in CODES else "RECHECK_RECORD_INVALID") from None
    except (ReadIssue, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, struct.error, zlib.error):
        raise Refused("RECHECK_RECORD_INVALID") from None


def _history_receipt(value, name):
    _require(type(value) is dict and value.get("format") == FORMAT and type(value.get("version")) is int
             and value["version"] == 1 and value.get("id") == name and _id(value.get("workspace_id"))
             and type(value.get("status")) is str and value["status"] in {"PREPARING", "VERIFIED", "FAILED", "INTERRUPTED"}
             and _integer(value.get("created")) and value.get("source_applied") is False
             and value.get("workspace_modified") is False
             and all(_hash(value.get(key)) for key in ("creation_sha256", "preview_sha256", "history_sha256")))
    if value["status"] != "PREPARING":
        _require(_integer(value.get("finished")))
    if value["status"] in {"FAILED", "INTERRUPTED"}:
        _require(type(value.get("reason")) is str and value["reason"] in CODES)
    if value["status"] == "VERIFIED":
        checks = value.get("checks")
        _require(type(checks) is dict and 1 <= len(checks) <= 4 and _hash(value.get("snapshot_sha256")))
        for name, row in checks.items():
            _require(type(name) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name)
                     and type(row) is dict and type(row.get("exit_code")) is int and row["exit_code"] == 0
                     and _integer(row.get("tests_ran"), 1) and all(row.get(key) is False
                         for key in ("timed_out", "output_limited", "infrastructure_error")))


def history_pin(history_dir, exclude_id=None):
    """Hash bounded saved attempt receipts without reconciliation or mutation."""
    try:
        _require(exclude_id is None or _id(exclude_id), "INPUT")
        fd = _directory(history_dir, private=True)
        names = []
        try:
            with os.scandir(fd) as entries:
                for count, entry in enumerate(entries, 1):
                    _require(count <= 1024, "LIMIT")
                    _require(_id(entry.name) and stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode))
                    if entry.name != exclude_id:
                        names.append(entry.name)
                        _require(len(names) <= 200, "LIMIT")
        finally:
            os.close(fd)
        rows, budget = [], 2097152
        for name in sorted(names):
            _require(budget > 0, "LIMIT")
            raw = _read_named(history_dir / name / "receipt.json", min(262144, budget), text=True)
            budget -= len(raw)
            _history_receipt(parse(raw), name)
            rows.append({"id": name, "receipt_sha256": sha(raw)})
        return sha(canonical(rows))
    except Refused as error:
        raise Refused(str(error) if str(error) in CODES else "RECHECK_RECORD_INVALID") from None
    except ReadIssue as error:
        raise Refused("RECHECK_LIMIT" if str(error) == "LIMIT" else "RECHECK_RECORD_INVALID") from None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise Refused("RECHECK_RECORD_INVALID") from None


def _snapshot(root, selected):
    try:
        _inventory(root, selected)
        for name, value in selected.items():
            _require(read_selected(root, name) == value, "STALE")
    except (Refused, ReadIssue, OSError, ValueError, TypeError):
        raise Refused("RECHECK_STALE") from None


def _unchanged(job, creation_pin, summary, history, attempt_id, history_sha):
    try:
        _require(inspect(job, creation_pin)["summary"] == summary and history_pin(history, attempt_id) == history_sha, "STALE")
    except (Refused, ReadIssue, OSError, ValueError, TypeError):
        raise Refused("RECHECK_STALE") from None


def build(attempt_dir, jdk_home=None, checker=fixed_checks):
    receipt = {"version": 1, "format": FORMAT, "status": "PREPARING", "created": int(time.time()),
               "source_applied": False, "workspace_modified": False, "checks": {}}
    can_record = False
    try:
        fd = _directory(attempt_dir, private=True)
        os.close(fd)
        initial_raw = _read_named(attempt_dir / "receipt.json", 262144, text=True)
        initial = parse(initial_raw)
        _require(type(initial) is dict and initial.get("status") == "PREPARING")
        can_record = True
        for key in ("creation_sha256", "preview_sha256", "history_sha256"):
            if _hash(initial.get(key)):
                receipt[key] = initial[key]
        for key in ("id", "workspace_id"):
            if _id(initial.get(key)):
                receipt[key] = initial[key]
        if _integer(initial.get("created")):
            receipt["created"] = initial["created"]
        write_new(attempt_dir / "initial-receipt.json", initial_raw)
        request_raw = _read_named(attempt_dir / "request.json", 262144, text=True)
        request = parse(request_raw)
        _require(type(request) is dict and set(request) == REQUEST_FIELDS and type(request["version"]) is int and request["version"] == 1
                 and _id(request["id"]) and request["id"] == attempt_dir.name and _id(request["workspace_id"])
                 and all(_hash(request[key]) for key in ("creation_sha256", "preview_sha256", "history_sha256")))
        _require(type(request["job_dir"]) is str and attempt_dir.parent.name == "workspace-rechecks")
        job = Path(request["job_dir"])
        _require(job == attempt_dir.parent.parent / "bundle-workspaces" / request["workspace_id"])
        _history_receipt(initial, request["id"])
        _require(all(initial.get(key) == request[key] for key in ("id", "workspace_id", "creation_sha256", "preview_sha256", "history_sha256")))
        receipt.update({key: request[key] for key in ("id", "workspace_id", "creation_sha256", "preview_sha256", "history_sha256")})
        _require(history_pin(attempt_dir.parent, request["id"]) == request["history_sha256"], "STALE")
        inspected = inspect(job, request["creation_sha256"])
        summary, task, selected = inspected["summary"], inspected["task"], inspected["selected_bytes"]
        binding = {"inspection": summary, "history_sha256": request["history_sha256"]}
        _require(sha(canonical(binding)) == request["preview_sha256"], "STALE")
        receipt.update(snapshot_sha256=summary["snapshot_sha256"], checked_files={name: sha(raw) for name, raw in selected.items()},
            task_sha256=summary["task_sha256"], bundle_sha256=summary["bundle_sha256"], config_sha256=summary["config_sha256"])
        _require(jdk_home is not None or not any(isinstance(spec, dict) and spec.get("kind") == "java-main"
                 for spec in task["checks"].values()), "CHECKS_FAILED")
        snapshot = attempt_dir / "snapshot"
        snapshot.mkdir(mode=0o700, exist_ok=False)
        for name, raw in selected.items():
            target = snapshot / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(target, raw)
        task_raw = _read_named(job / "task.json", 262144, text=True)
        _require(sha(task_raw) == summary["task_sha256"], "STALE")
        write_new(attempt_dir / "task.json", task_raw)
        _snapshot(snapshot, selected)
        _unchanged(job, request["creation_sha256"], summary, attempt_dir.parent, request["id"], request["history_sha256"])
        full, display, passed = _check_results(checker(snapshot, task, jdk_home), task)
        full_raw = canonical(full)
        _require(len(full_raw) <= 2097152, "LIMIT")
        write_new(attempt_dir / "checks.json", full_raw)
        receipt.update(checks=display, checks_sha256=sha(full_raw))
        _snapshot(snapshot, selected)
        _require(_read_named(attempt_dir / "request.json", 262144, text=True) == request_raw
                 and _read_named(attempt_dir / "task.json", 262144, text=True) == task_raw, "STALE")
        _unchanged(job, request["creation_sha256"], summary, attempt_dir.parent, request["id"], request["history_sha256"])
        _require(passed, "CHECKS_FAILED")
        receipt.update(status="VERIFIED", finished=int(time.time()))
        _require(len(canonical(receipt)) <= 262144, "OUTPUT_LIMIT")
        atomic_json(attempt_dir / "receipt.json", receipt)
        return receipt
    except BaseException as error:
        reason = _reason(error)
        if can_record:
            receipt.update(status="INTERRUPTED" if reason == "RECHECK_INTERRUPTED" else "FAILED",
                           reason=reason, finished=int(time.time()), source_applied=False, workspace_modified=False)
            atomic_json(attempt_dir / "receipt.json", receipt)
        raise Refused(reason) from None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        _require(type(argv) is list and len(argv) in {2, 4} and all(type(arg) is str for arg in argv), "INPUT")
        options = {}
        for key, value in zip(argv[::2], argv[1::2]):
            _require(key in {"--attempt-dir", "--jdk-home"} and key not in options, "INPUT")
            options[key] = Path(value)
            _path(options[key])
        _require("--attempt-dir" in options, "INPUT")
        def interrupted(*_):
            raise KeyboardInterrupt
        previous = signal.signal(signal.SIGTERM, interrupted)
        try:
            build(options["--attempt-dir"], options.get("--jdk-home"))
        finally:
            signal.signal(signal.SIGTERM, previous)
        return 0
    except BaseException as error:
        sys.stdout.write(canonical({"error": _reason(error)}).decode("ascii"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
