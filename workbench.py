"""Local OUTLANDS Agent Workbench; configured projects, one task, reviewed exports."""

import argparse
import copy
import fcntl
import hmac
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from java_check import validate_jdk
from project_setup import prepare
from project_revisions import refresh_task
from run_diagnostics import summarize as summarize_diagnostics
from run_comparison import compare_runs
from project_readiness import summarize as summarize_readiness
from patch_bundle import MAX_ARCHIVE, build_bundle, verify_bundle
from bundle_project_check import check_project
from bundle_workspace import prepare as prepare_bundle_workspace
from workspace_recheck import inspect as inspect_recheck
from workspace_recheck import history_pin as recheck_history_pin
from snapshot_export import prepare as prepare_snapshot_export
from snapshot_export import verify_export as verify_snapshot_export
from snapshot_project_check import check_project as check_snapshot_project
from snapshot_workspace import prepare as prepare_snapshot_workspace
from snapshot_workspace import valid_receipt as valid_snapshot_workspace_receipt
from git_workspace import inspect as inspect_workspace
from git_workspace import validate_files as validate_workspace_files

from agent import (
    Refused,
    canonical,
    parse,
    read_file,
    require,
    review_diff,
    relative,
    sha,
    validate_task,
    write_new,
)

HERE = Path(__file__).resolve().parent
ID = re.compile(r"[0-9a-f]{16}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
EXPORT_FORMAT = "outlands-snapshot-export-acceptance-v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def snapshot_export_note(value):
    try:
        return (type(value) is str and len(value) <= 1000 and "\0" not in value
                and len(value.encode("utf-8")) <= 2000)
    except UnicodeError:
        return False


def valid_snapshot_acceptance(value):
    """Validate private review metadata without interpreting it as execution proof."""
    base = {"version", "format", "id", "attempt_id", "workspace_id", "status", "created",
            "source_applied", "workspace_modified", "preview_sha256", "prepared_sha256", "review_sha256",
            "recheck_history_sha256", "parent_acceptance_history_sha256", "recheck_receipt_sha256",
            "snapshot_sha256", "patch_sha256", "verification_sha256", "archive_sha256", "note"}
    if type(value) is not dict or type(value.get("status")) is not str:
        return False
    status = value["status"]
    keys = base | ({"finished"} if status in {"ACCEPTED", "FAILED"} else set()) | ({"reason"} if status == "FAILED" else set())
    if (set(value) != keys or status not in {"PREPARING", "ACCEPTED", "FAILED"}
            or type(value.get("version")) is not int or value["version"] != 1
            or value.get("format") != EXPORT_FORMAT or value.get("source_applied") is not False
            or value.get("workspace_modified") is not False or not snapshot_export_note(value.get("note"))):
        return False
    if not all(type(value[k]) is str and ID.fullmatch(value[k]) for k in ["id", "attempt_id", "workspace_id"]):
        return False
    hashes = [key for key in base if key.endswith("sha256")]
    if not all(type(value[k]) is str and SHA256.fullmatch(value[k]) for k in hashes):
        return False
    if not all(type(value[k]) is int and 0 <= value[k] <= 9007199254740991
               for k in ["created"] + (["finished"] if "finished" in keys else [])):
        return False
    return status != "FAILED" or value["reason"] == "SNAPSHOT_EXPORT_ACCEPT_FAILED"


def valid_snapshot_review(value, receipt):
    keys = {"version", "preview_id", "preview_sha256", "expires_at_ms", "recheck_history_sha256",
            "acceptance_history_sha256", "artifact"}
    if (type(value) is not dict or set(value) != keys or type(value["version"]) is not int or value["version"] != 1
            or type(value["preview_id"]) is not str or ID.fullmatch(value["preview_id"]) is None
            or type(value["expires_at_ms"]) is not int or not 0 <= value["expires_at_ms"] <= 9007199254740991
            or type(value["artifact"]) is not dict):
        return False
    summary = value["artifact"]
    return (len(canonical(summary)) <= 65536 and sha(canonical(summary)) == receipt["prepared_sha256"]
            and value["preview_sha256"] == receipt["preview_sha256"]
            and value["recheck_history_sha256"] == receipt["recheck_history_sha256"]
            and value["acceptance_history_sha256"] == receipt["parent_acceptance_history_sha256"]
            and all(summary.get(k) == receipt[k] for k in ["attempt_id", "workspace_id", "snapshot_sha256",
                                                           "patch_sha256", "verification_sha256", "archive_sha256"])
            and summary.get("receipt_sha256") == receipt["recheck_receipt_sha256"]
            and sha(canonical({"prepared": summary, "recheck_history_sha256": value["recheck_history_sha256"],
                              "acceptance_history_sha256": value["acceptance_history_sha256"]})) == receipt["preview_sha256"])


def private_dir(path):
    require(path.is_absolute() and not path.is_symlink(), "PRIVATE_DIRECTORY_REQUIRED")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    require(
        info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
        "PRIVATE_DIRECTORY_REQUIRED",
    )


def json_file(path):
    return parse(read_file(path.parent, path.name, 262144))


def context_evidence(kind, value, files):
    """Select bounded source fields from known tool results; ignore damaged records."""
    if not isinstance(value, dict) or len(canonical(value)) > 8192:
        return None
    def text(v, size):
        try:
            return isinstance(v, str) and len(v.encode("utf-8")) <= size
        except UnicodeError:
            return False
    def integer(v):
        return type(v) is int and 0 <= v <= 1000000
    def file_row(v):
        return isinstance(v, dict) and isinstance(v.get("path"), str) and v["path"] in files and isinstance(v.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", v["sha256"])
    if kind == "search_text":
        matches = value.get("matches")
        if (not text(value.get("query"), 128) or not isinstance(matches, list) or len(matches) > 20
                or not all(file_row(row) and integer(row.get("line_number")) and integer(row.get("column"))
                           and text(row.get("text"), 512) and type(row.get("truncated")) is bool for row in matches)):
            return None
        keys = ["query", "files_searched", "total_matches", "truncated", "limit", "byte_limit"]
        if not all(key in value for key in keys) or not all(integer(value[k]) for k in ["files_searched", "total_matches", "limit", "byte_limit"]):
            return None
        cleaned = {key: value[key] for key in keys}
        cleaned["matches"] = [{key: row[key] for key in ["path", "line_number", "column", "text", "sha256", "truncated"]} for row in matches]
    elif kind == "read_lines":
        lines = value.get("lines")
        keys = ["path", "sha256", "requested_start", "requested_end", "start_line", "end_line", "total_lines", "truncated", "end_of_file", "byte_limit"]
        if (not file_row(value) or not isinstance(lines, list) or len(lines) > 80 or not all(key in value for key in keys)
                or not all(integer(value[k]) for k in ["requested_start", "requested_end", "total_lines", "byte_limit"])
                or not all(value[k] is None or integer(value[k]) for k in ["start_line", "end_line"])
                or type(value["end_of_file"]) is not bool
                or not all(isinstance(row, dict) and integer(row.get("line_number")) and text(row.get("text"), 1024)
                           and type(row.get("truncated")) is bool for row in lines)):
            return None
        cleaned = {key: value[key] for key in keys}
        cleaned["lines"] = [{key: row[key] for key in ["line_number", "text", "truncated"]} for row in lines]
    else:
        return None
    return cleaned if type(value.get("truncated")) is bool else None


def replace_json(path, value, expected_raw=None):
    temporary = path.with_name(path.name + ".next")
    write_new(temporary, canonical(value))
    if expected_raw is not None:
        require(read_file(path.parent, path.name, 262144) == expected_raw, "CONFIG_CHANGED")
    os.replace(temporary, path)


def verified_workspace_receipt(value):
    """Recognize a completed receipt without executing its workspace."""
    if not isinstance(value, dict) or value.get("status") != "VERIFIED":
        return False
    if (value.get("source_applied") is not False or value.get("patch_applied_to_workspace") is not True
            or not all(isinstance(value.get(k), str) and re.fullmatch(r"[0-9a-f]{64}", value[k])
                       for k in ["result_sha256", "patch_sha256"])
            or not isinstance(value.get("baseline_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}", value["baseline_commit"]) is None
            or not all(isinstance(value.get(k), str) and 1 <= len(value[k]) <= 4096 for k in ["branch", "path"])
            or type(value.get("finished")) is not int):
        return False
    checks = value.get("checks")
    return (isinstance(checks, dict) and 1 <= len(checks) <= 4
            and all(isinstance(row, dict) and type(row.get("exit_code")) is int and row["exit_code"] == 0
                    and type(row.get("tests_ran")) is int and row["tests_ran"] > 0
                    and all(row.get(k) is False for k in ["timed_out", "output_limited", "infrastructure_error"])
                    for row in checks.values()))


def valid_recheck_receipt(value):
    if (type(value) is not dict or type(value.get("version")) is not int or value["version"] != 1
            or value.get("format") != "outlands-workspace-recheck-v1"
            or value.get("source_applied") is not False or value.get("workspace_modified") is not False
            or type(value.get("status")) is not str
            or value["status"] not in {"PREPARING", "VERIFIED", "FAILED", "INTERRUPTED"}
            or type(value.get("created")) is not int or not 0 <= value["created"] <= 9007199254740991
            or not all(type(value.get(k)) is str and ID.fullmatch(value[k]) is not None
                       for k in ["id", "workspace_id"])
            or not all(type(value.get(k)) is str and re.fullmatch(r"[0-9a-f]{64}", value[k]) is not None
                       for k in ["creation_sha256", "preview_sha256", "history_sha256"])):
        return False
    if value["status"] != "VERIFIED":
        return True
    checks, files = value.get("checks"), value.get("checked_files")
    return (type(value.get("finished")) is int and 0 <= value["finished"] <= 9007199254740991
            and all(type(value.get(k)) is str and re.fullmatch(r"[0-9a-f]{64}", value[k]) is not None
                    for k in ["snapshot_sha256", "task_sha256", "bundle_sha256", "config_sha256", "checks_sha256"])
            and type(files) is dict and 1 <= len(files) <= 32
            and all(type(name) is str and type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                    for name, digest in files.items())
            and type(checks) is dict and 1 <= len(checks) <= 4
            and all(type(row) is dict and type(row.get("exit_code")) is int and row["exit_code"] == 0
                    and type(row.get("tests_ran")) is int and row["tests_ran"] > 0
                    and all(row.get(k) is False for k in ["timed_out", "output_limited", "infrastructure_error"])
                    for row in checks.values()))


def readiness_presence(path):
    """Observe executable presence only; never execute or inspect version output."""
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def readiness_directory(root):
    """Open an absolute directory without following any path-component link."""
    root = Path(os.path.normpath(root))
    require(root.is_absolute(), "READINESS_PROJECT_UNKNOWN")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in root.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def readiness_read_file(root, name, limit=32768):
    """Read one approved relative file using guarded directory descriptors."""
    relative(name)
    fd = readiness_directory(root)
    try:
        parts = name.split("/")
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        child = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "INPUT_TYPE")
            raw = stream.read(limit + 1)
            require(len(raw) <= limit, "FILE_LIMIT")
            require(b"\x00" not in raw, "BINARY_INPUT")
            raw.decode("utf-8")
            return raw
    finally:
        os.close(fd)


def process_stamp(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return raw[raw.rfind(")") + 2 :].split()[19]
    except (OSError, IndexError):
        return None


def load_config(path):
    require(
        path.is_absolute() and HERE not in path.resolve().parents,
        "CONFIG_OUTSIDE_SOURCE",
    )
    value = json_file(path)
    require(
        isinstance(value, dict) and set(value) == {"format", "projects", "models"},
        "CONFIG_FIELDS",
    )
    require(value["format"] == "outlands-workbench-config-v1", "CONFIG_FORMAT")
    require(
        isinstance(value["projects"], list) and 1 <= len(value["projects"]) <= 16,
        "PROJECT_LIMIT",
    )
    projects = {}
    for row in value["projects"]:
        require(
            isinstance(row, dict) and set(row) == {"id", "name", "source", "task"},
            "PROJECT_FIELDS",
        )
        require(
            isinstance(row["id"], str)
            and ALIAS.fullmatch(row["id"])
            and row["id"] not in projects,
            "PROJECT_ID",
        )
        require(
            isinstance(row["name"], str) and 1 <= len(row["name"]) <= 80, "PROJECT_NAME"
        )
        require(
            isinstance(row["source"], str) and isinstance(row["task"], str),
            "PROJECT_PATH",
        )
        source, task = Path(row["source"]), Path(row["task"])
        require(
            source.is_absolute()
            and task.is_absolute()
            and not source.is_symlink()
            and not task.is_symlink(),
            "PROJECT_PATH",
        )
        require(source.is_dir(), "PROJECT_SOURCE")
        task_raw = read_file(task.parent, task.name, 262144)
        definition = validate_task(parse(task_raw))
        projects[row["id"]] = {
            **row,
            "source": source.resolve(),
            "task": task.resolve(),
            "definition": definition,
            "task_raw": task_raw,
        }
    require(
        isinstance(value["models"], list) and len(value["models"]) <= 8, "MODEL_LIMIT"
    )
    models = []
    for model in value["models"]:
        require(
            isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", model),
            "MODEL_NAME",
        )
        require(model not in models, "MODEL_DUPLICATE")
        models.append(model)
    return projects, models


class Manager:
    def __init__(self, config, data, jdk_home=None):
        self.projects, self.models = load_config(config)
        self.config_path = config
        self.config_raw = read_file(config.parent, config.name, 262144)
        self.jdk_home = validate_jdk(jdk_home) if jdk_home is not None else None
        self.drafts = {}
        require(data.is_absolute() and not data.is_symlink(), "DATA_DIRECTORY")
        self.data = data.resolve()
        for source in [HERE] + [p["source"] for p in self.projects.values()]:
            require(
                self.data != source
                and source not in self.data.parents
                and self.data not in source.parents,
                "DATA_OUTSIDE_SOURCE",
            )
        private_dir(self.data)
        for name in ["jobs", "tasks", "runs", "state", "projects", "workspaces", "revisions", "bundle-workspaces", "workspace-rechecks", "snapshot-exports", "snapshot-workspaces"]:
            private_dir(self.data / name)
        self.server_lock = os.open(
            self.data / "server.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        require(os.fstat(self.server_lock).st_nlink == 1, "SERVER_LOCK_TYPE")
        try:
            fcntl.flock(self.server_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.server_lock)
            raise Refused("SERVER_ALREADY_RUNNING") from None
        self.lock = threading.RLock()
        self.children = {}
        self.workspace_children = {}
        self.bundle_workspace_children = {}
        self.bundle_workspace_draft = None
        self.recheck_children = {}
        self.recheck_draft = None
        self.snapshot_export_draft = None
        self.snapshot_workspace_draft = None
        self.snapshot_workspace_children = {}

    @staticmethod
    def readiness_fingerprint(path, expected):
        try:
            raw = readiness_read_file(path.parent, path.name, 262144)
            return {"expected_sha256": sha(expected), "sha256": sha(raw),
                    "status": "MATCH" if raw == expected else "CHANGED"}
        except FileNotFoundError:
            status = "MISSING"
        except Refused as exc:
            status = "LIMIT" if str(exc) == "FILE_LIMIT" else "UNREADABLE"
        except (OSError, UnicodeError, ValueError):
            status = "UNREADABLE"
        return {"expected_sha256": sha(expected), "sha256": None, "status": status}

    @staticmethod
    def readiness_entries(root, predicate, limit):
        fd = readiness_directory(root)
        names, truncated = [], False
        try:
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1024:
                        truncated = True
                        break
                    if predicate(entry.name):
                        if len(names) == limit:
                            truncated = True
                            break
                        names.append(entry.name)
        finally:
            os.close(fd)
        return sorted(names), truncated

    def readiness_admission(self):
        """Inspect saved admission evidence without reconciling any worker."""
        reasons, budget = [], 2097152
        def note(code):
            if code not in reasons:
                reasons.append(code)
        def record(root, name, ceiling=32768):
            nonlocal budget
            if budget <= 1:
                note("ADMISSION_RECORD_LIMIT")
                return None
            limit = min(ceiling, budget - 1)
            raw = None
            try:
                raw = readiness_read_file(root, name, limit)
                value = parse(raw)
                if not isinstance(value, dict):
                    raise Refused("INVALID_JSON")
                return value
            except Refused as exc:
                note("ADMISSION_RECORD_LIMIT" if str(exc) in ["FILE_LIMIT", "JSON_LIMIT"] else "ADMISSION_RECORD_INVALID")
            except (OSError, UnicodeError, ValueError):
                note("ADMISSION_RECORD_INVALID")
            finally:
                budget -= len(raw) if raw is not None else limit + 1
            return None
        hold, jobs, workspaces, truncated = "ABSENT", 0, 0, False
        try:
            fd = readiness_directory(self.data / "state")
            try:
                try:
                    os.stat("hold.json", dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    hold = "PRESENT"
            finally:
                os.close(fd)
        except OSError:
            hold = "UNAVAILABLE"
            note("HOLD_UNREADABLE")
        if hold == "PRESENT":
            note("HOLD_PRESENT")
            value = record(self.data, "state/hold.json", 4096)
            if (value is None or value.get("state") != "REQUEST_UNSETTLED"
                    or type(value.get("turn")) is not int or not 1 <= value["turn"] <= 16
                    or not isinstance(value.get("run"), str) or not 1 <= len(value["run"]) <= 4096):
                note("HOLD_UNREADABLE")
        try:
            names, truncated = self.readiness_entries(self.data / "jobs",
                lambda name: name.endswith(".json") or name.endswith(".next"), 200)
        except OSError:
            names, truncated = [], False
            note("ADMISSION_UNAVAILABLE")
        if truncated:
            note("ADMISSION_RECORD_LIMIT")
        terminal = {"REVIEW_READY", "FAILED", "REFUSED", "INTERRUPTED"}
        for name in names:
            if budget <= 1:
                truncated = True
                note("ADMISSION_RECORD_LIMIT")
                break
            if not name.endswith(".json") or ID.fullmatch(name[:-5]) is None:
                note("ADMISSION_RECORD_INVALID")
                continue
            run_id = name[:-5]
            jobs += 1
            value = record(self.data, "jobs/" + name)
            if value is None or value.get("id") != run_id or not isinstance(value.get("state"), str):
                note("ADMISSION_RECORD_INVALID")
            elif value["state"] in {"RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED"}:
                note("TASK_ACTIVE_OR_UNRESOLVED")
            elif value["state"] == "UNCERTAIN":
                note("TASK_UNCERTAIN")
            elif value["state"] not in terminal:
                note("ADMISSION_RECORD_INVALID")
            try:
                fd = readiness_directory(self.data / "runs" / run_id)
                try:
                    os.stat("git-workspace.json", dir_fd=fd, follow_symlinks=False)
                finally:
                    os.close(fd)
            except FileNotFoundError:
                continue
            except OSError:
                note("ADMISSION_RECORD_INVALID")
                continue
            workspaces += 1
            receipt = record(self.data, "runs/" + run_id + "/git-workspace.json")
            if (isinstance(receipt, dict) and isinstance(receipt.get("status"), str)
                    and receipt["status"] in {"PREPARING", "FAILED"}):
                note("WORKSPACE_ACTIVE_OR_UNRESOLVED")
                max_safe = 9007199254740991
                valid = (type(receipt.get("created")) is int and 0 <= receipt["created"] <= max_safe
                         and receipt.get("source_applied") is False
                         and all(type(receipt.get(key)) is str
                                 and re.fullmatch(r"[0-9a-f]{64}", receipt[key]) is not None
                                 for key in ["result_sha256", "patch_sha256"]))
                if "reason" in receipt:
                    valid = valid and type(receipt["reason"]) is str and 1 <= len(receipt["reason"]) <= 128
                if "finished" in receipt:
                    valid = valid and type(receipt["finished"]) is int and 0 <= receipt["finished"] <= max_safe
                if "checks" in receipt:
                    checks = receipt["checks"]
                    valid_checks = (type(checks) is dict and 1 <= len(checks) <= 4
                        and all(type(name) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name) is not None
                            and type(row) is dict
                            and type(row.get("exit_code")) is int and -255 <= row["exit_code"] <= 255
                            and type(row.get("tests_ran")) is int and 0 <= row["tests_ran"] <= max_safe
                            and all(type(row.get(key)) is bool for key in ["timed_out", "output_limited", "infrastructure_error"])
                            and ("output" not in row or type(row["output"]) is str and len(row["output"]) <= 65536)
                            for name, row in checks.items()))
                    valid = valid and valid_checks
                if not valid:
                    note("ADMISSION_RECORD_INVALID")
            elif not verified_workspace_receipt(receipt):
                note("ADMISSION_RECORD_INVALID")
        try:
            names, bundle_truncated = self.readiness_entries(self.data / "bundle-workspaces", lambda _: True, 200)
        except OSError:
            names, bundle_truncated = [], False
            note("ADMISSION_UNAVAILABLE")
        if bundle_truncated:
            truncated = True
            note("ADMISSION_RECORD_LIMIT")
        for name in names:
            if ID.fullmatch(name) is None:
                note("ADMISSION_RECORD_INVALID")
                continue
            workspaces += 1
            receipt = record(self.data / "bundle-workspaces", name + "/receipt.json", 262144)
            if (type(receipt) is not dict or receipt.get("id") != name
                    or receipt.get("source_applied") is not False):
                note("ADMISSION_RECORD_INVALID")
            elif type(receipt.get("status")) is str and receipt["status"] in {"PREPARING", "FAILED", "INTERRUPTED"}:
                note("WORKSPACE_ACTIVE_OR_UNRESOLVED")
            elif not verified_workspace_receipt({**receipt, "result_sha256": receipt.get("bundle_sha256")}):
                note("ADMISSION_RECORD_INVALID")
        try:
            names, recheck_truncated = self.readiness_entries(self.data / "workspace-rechecks", lambda _: True, 200)
        except OSError:
            names, recheck_truncated = [], False
            note("ADMISSION_UNAVAILABLE")
        if recheck_truncated:
            truncated = True
            note("ADMISSION_RECORD_LIMIT")
        for name in names:
            if ID.fullmatch(name) is None:
                note("ADMISSION_RECORD_INVALID")
                continue
            workspaces += 1
            receipt = record(self.data / "workspace-rechecks", name + "/receipt.json", 262144)
            if not valid_recheck_receipt(receipt) or receipt["id"] != name:
                note("ADMISSION_RECORD_INVALID")
            elif receipt["status"] != "VERIFIED":
                note("WORKSPACE_ACTIVE_OR_UNRESOLVED")
        try:
            names, snapshot_truncated = self.readiness_entries(self.data / "snapshot-workspaces", lambda _: True, 200)
        except OSError:
            names, snapshot_truncated = [], False
            note("ADMISSION_UNAVAILABLE")
        if snapshot_truncated:
            truncated = True
            note("ADMISSION_RECORD_LIMIT")
        for name in names:
            if ID.fullmatch(name) is None:
                note("ADMISSION_RECORD_INVALID")
                continue
            workspaces += 1
            try:
                pending, pending_limited = self.readiness_entries(self.data / "snapshot-workspaces" / name,
                                                                  lambda item: item == "receipt.json.next", 1)
                if pending or pending_limited:
                    note("ADMISSION_RECORD_INVALID")
            except (OSError, Refused):
                note("ADMISSION_RECORD_INVALID")
            receipt = record(self.data / "snapshot-workspaces", name + "/receipt.json", 262144)
            if not valid_snapshot_workspace_receipt(receipt) or receipt["id"] != name:
                note("ADMISSION_RECORD_INVALID")
            elif receipt["status"] != "VERIFIED":
                note("WORKSPACE_ACTIVE_OR_UNRESOLVED")
        return {"hold": hold, "jobs_inspected": jobs, "workspaces_inspected": workspaces,
                "truncated": truncated, "reasons": reasons}

    def project_readiness(self, project_id):
        with self.lock:
            require(isinstance(project_id, str) and project_id in self.projects, "READINESS_PROJECT_UNKNOWN")
            project = self.projects[project_id]
            task = copy.deepcopy(project["definition"])
            valid_task = True
            try:
                validate_task(task)
            except (Refused, OSError, ValueError, TypeError, KeyError):
                valid_task = False
            config = self.readiness_fingerprint(self.config_path, self.config_raw)
            fingerprint = self.readiness_fingerprint(project["task"], project["task_raw"])
            files = []
            if valid_task:
                for path, digest in sorted(task["files"].items()):
                    row = {"path": path, "editable": path in task["editable"],
                           "expected_sha256": digest, "sha256": None, "bytes": None, "status": "NOT_CHECKED"}
                    if config["status"] == fingerprint["status"] == "MATCH":
                        try:
                            raw = readiness_read_file(project["source"], path)
                            row.update(sha256=sha(raw), bytes=len(raw), status="MATCH" if sha(raw) == digest else "CHANGED")
                        except FileNotFoundError:
                            row["status"] = "MISSING"
                        except UnicodeError:
                            row["status"] = "UTF8"
                        except Refused as exc:
                            row["status"] = {"FILE_LIMIT": "LIMIT", "BINARY_INPUT": "BINARY"}.get(str(exc), "UNREADABLE")
                        except (OSError, ValueError):
                            row["status"] = "UNREADABLE"
                    files.append(row)
            java = valid_task and any(isinstance(spec, dict) and spec.get("kind") == "java-main" for spec in task["checks"].values())
            prerequisites = [{"id": key, "required": key != "git", "status": "AVAILABLE" if readiness_presence(Path(path)) else "MISSING"}
                for key, path in [("python", "/usr/bin/python3"), ("git", "/usr/bin/git"), ("bwrap", "/usr/bin/bwrap"), ("prlimit", "/usr/bin/prlimit")]]
            jdk_status = ("NOT_REQUIRED" if not java else "NOT_CONFIGURED" if self.jdk_home is None else
                "AVAILABLE" if all(readiness_presence(self.jdk_home / "bin" / name) for name in ["java", "javac"]) else "MISSING")
            prerequisites.append({"id": "jdk", "required": bool(java), "status": jdk_status})
            snapshot = {"project": project_id, "name": project["name"], "checked_at_ms": time.time_ns() // 1000000,
                        "definition": task if valid_task else None, "config": config, "task": fingerprint,
                        "files": files, "prerequisites": prerequisites, "admission": self.readiness_admission(),
                        "notes": [] if valid_task else ["DEFINITION_INVALID"]}
            return summarize_readiness(snapshot)

    def comparison_directory(self, root):
        """Open each private-store path component relative to the data root."""
        parts = root.relative_to(self.data).parts
        fd = os.open(self.data, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except BaseException:
            os.close(fd)
            raise

    def comparison_names(self, root, predicate, limit):
        """Bound directory inspection without following a substituted root link."""
        fd = self.comparison_directory(root)
        names, truncated = [], False
        try:
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1024:
                        truncated = True
                        break
                    if predicate(entry.name):
                        if len(names) == limit:
                            truncated = True
                            break
                        names.append(entry.name)
        finally:
            os.close(fd)
        return sorted(names), truncated

    def comparison_record(self, root, name, notes, limit=32768):
        raw = None
        try:
            raw = read_file(self.data, (root / name).relative_to(self.data).as_posix(), limit)
            value = parse(raw)
            if not isinstance(value, dict):
                raise Refused("INVALID_JSON")
            return value, raw
        except FileNotFoundError:
            note = "RECORD_MISSING"
        except Refused as exc:
            note = "RECORD_LIMIT" if str(exc) in ["FILE_LIMIT", "JSON_LIMIT"] else "RECORD_INVALID"
        except (OSError, UnicodeError, ValueError):
            note = "RECORD_INVALID"
        if note not in notes:
            notes.append(note)
        return None, raw

    def comparison_history(self):
        """Read saved rows only; never reconcile workers or rewrite metadata."""
        with self.lock:
            try:
                names, truncated = self.comparison_names(self.data / "jobs",
                    lambda name: name.endswith(".json") and ID.fullmatch(name[:-5]) is not None, 200)
            except OSError:
                raise Refused("COMPARE_STORE_REFUSED") from None
            rows, notes = [], []
            def text(value, limit):
                return value if isinstance(value, str) and len(value.encode("utf-8")) <= limit else None
            states = {"REVIEW_READY", "RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED", "FAILED", "REFUSED", "UNCERTAIN", "INTERRUPTED"}
            for name in names:
                value, _ = self.comparison_record(self.data / "jobs", name, notes)
                value = value or {}
                try:
                    project_name = text(value.get("project_name"), 320)
                    goal = text(value.get("goal"), 8000)
                except UnicodeError:
                    project_name, goal = None, None
                    if "RECORD_INVALID" not in notes:
                        notes.append("RECORD_INVALID")
                labels = []
                for label in [project_name, goal]:
                    if label is not None and len(label.encode("utf-8")) > 160:
                        label = label.encode("utf-8")[:157].decode("utf-8", "ignore") + "…"
                        if "HISTORY_LABEL_TRUNCATED" not in notes:
                            notes.append("HISTORY_LABEL_TRUNCATED")
                    labels.append(label)
                project_name, goal = labels
                state, created = value.get("state"), value.get("created")
                rows.append({"id": name[:-5], "project_name": project_name, "goal": goal,
                    "state": state if isinstance(state, str) and state in states else None,
                    "created": created if type(created) is int and 0 <= created <= 9007199254740991 else None})
            rows.sort(key=lambda row: (row["created"] if row["created"] is not None else -1, row["id"]), reverse=True)
            truncated = truncated or len(rows) > 100
            if truncated and "RECORD_LIMIT" not in notes:
                notes.append("RECORD_LIMIT")
            result = {"runs": rows[:100], "limit": 100, "truncated": truncated, "notes": notes}
            require(len(canonical(result)) <= 131072, "COMPARE_OUTPUT_LIMIT")
            return result

    def comparison_bundle(self, run_id):
        metadata_path = self.meta_path(run_id)
        try:
            fd = self.comparison_directory(self.data / "jobs")
            try:
                os.stat(metadata_path.name, dir_fd=fd, follow_symlinks=False)
            finally:
                os.close(fd)
        except FileNotFoundError:
            raise Refused("COMPARE_RUN_UNKNOWN") from None
        except OSError:
            raise Refused("COMPARE_STORE_REFUSED") from None
        notes = []
        metadata, _ = self.comparison_record(metadata_path.parent, metadata_path.name, notes)
        task, task_raw = self.comparison_record(self.data / "tasks", run_id + ".json", notes)
        run = self.run_path(run_id)
        result, result_raw = self.comparison_record(run, "result.json", notes)
        try:
            names, truncated = self.comparison_names(run,
                lambda name: name.startswith("event-") and name.endswith(".json"), 256)
        except FileNotFoundError:
            names, truncated = [], False
            if "RECORD_MISSING" not in notes:
                notes.append("RECORD_MISSING")
        except OSError:
            names, truncated = [], False
            if "RECORD_INVALID" not in notes:
                notes.append("RECORD_INVALID")
        if truncated:
            notes.append("EVENT_LIMIT")
        events, total = [], 0
        for name in names:
            if re.fullmatch(r"event-[0-9]{3,6}[.]json", name) is None:
                if "RECORD_INVALID" not in notes:
                    notes.append("RECORD_INVALID")
                continue
            remaining = 2097152 - total
            if remaining <= 1:
                if "EVENT_LIMIT" not in notes:
                    notes.append("EVENT_LIMIT")
                break
            limit = min(262144, remaining - 1)
            value, raw = self.comparison_record(run, name, notes, limit)
            if raw is not None:
                total += len(raw)
                if value is not None:
                    events.append(value)
            else:
                # A refused oversized read consumes at most limit+1 bytes. Count
                # that worst case so repeated damaged records cannot bypass the
                # aggregate read bound; no retry or second read is performed.
                total += limit + 1
        patch, patch_sha = None, None
        try:
            raw = read_file(self.data, "runs/" + run_id + "/changes.diff", 65536)
            patch, patch_sha = raw.decode("utf-8"), sha(raw)
        except FileNotFoundError:
            if "RECORD_MISSING" not in notes:
                notes.append("RECORD_MISSING")
        except Refused as exc:
            note = "RECORD_LIMIT" if str(exc) == "FILE_LIMIT" else "RECORD_INVALID"
            if note not in notes:
                notes.append(note)
            if str(exc) == "FILE_LIMIT":
                notes.append("PATCH_TRUNCATED")
        except (OSError, UnicodeError, ValueError):
            if "RECORD_INVALID" not in notes:
                notes.append("RECORD_INVALID")
        return {"id": run_id, "metadata": metadata, "task": task,
                "task_sha256": sha(task_raw) if task_raw is not None else None,
                "result": result, "result_sha256": sha(result_raw) if result_raw is not None else None,
                "events": events, "patch": patch, "patch_sha256": patch_sha, "notes": notes}

    def compare(self, left_id, right_id):
        with self.lock:
            require(isinstance(left_id, str) and isinstance(right_id, str)
                    and ID.fullmatch(left_id) is not None and ID.fullmatch(right_id) is not None
                    and left_id != right_id, "COMPARE_IDS")
            return compare_runs(self.comparison_bundle(left_id), self.comparison_bundle(right_id))

    def workspace_receipt(self, run_id):
        path = self.run_path(run_id) / "git-workspace.json"
        entry = self.workspace_children.get(run_id)
        receipt = json_file(path) if path.exists() else None
        if entry is not None and entry[0].poll() is not None:
            child, log = self.workspace_children.pop(run_id)
            log.close()
            if receipt is not None and receipt["status"] == "PREPARING":
                receipt.update(status="FAILED", reason="WORKSPACE_INTERRUPTED", finished=int(time.time()))
                replace_json(path, receipt)
        return receipt

    def create_workspace(self, request):
        with self.lock:
            require(isinstance(request, dict) and set(request) == {"id", "result_sha256", "patch_sha256"}, "WORKSPACE_FIELDS")
            run_id = request["id"]
            self.export(run_id)
            self.verified_artifact(run_id, request["result_sha256"], request["patch_sha256"])
            run = self.run_path(run_id)
            task = json_file(self.data / "tasks" / (run_id + ".json"))
            validate_workspace_files(task)
            existing = self.workspace_receipt(run_id)
            destination = self.data / "workspaces" / run_id
            if existing is not None:
                require(existing["result_sha256"] == request["result_sha256"] and existing["patch_sha256"] == request["patch_sha256"], "WORKSPACE_ARTIFACT_CHANGED")
                require(existing["status"] in ["PREPARING", "VERIFIED"], "WORKSPACE_NEEDS_INSPECTION")
                if existing["status"] == "VERIFIED":
                    inspect_workspace(destination, task, self.result(run_id), existing)
                return existing
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            receipt = {"status": "PREPARING", "created": int(time.time()), "source_applied": False,
                       "result_sha256": request["result_sha256"], "patch_sha256": request["patch_sha256"]}
            self.recheck_draft = None
            self.snapshot_export_draft = None
            self.snapshot_workspace_draft = None
            write_new(run / "git-workspace.json", canonical(receipt))
            meta = self.metadata(run_id)
            command = [sys.executable, "-B", str(HERE / "git_workspace.py"), "--run-dir", str(run),
                       "--source", meta["source"], "--destination", str(destination),
                       "--result-sha256", request["result_sha256"], "--patch-sha256", request["patch_sha256"]]
            if self.jdk_home is not None:
                command += ["--jdk-home", str(self.jdk_home)]
            fd = os.open(run / "workspace-worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            log = os.fdopen(fd, "wb")
            try:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})
            except OSError:
                log.close()
                receipt.update(status="FAILED", reason="WORKSPACE_START_FAILED")
                replace_json(run / "git-workspace.json", receipt)
                raise Refused("WORKSPACE_START_FAILED") from None
            self.workspace_children[run_id] = (child, log)
            return receipt

    def stop_workspace(self, run_id):
        with self.lock:
            self.meta_path(run_id)
            entry = self.workspace_children.get(run_id)
            require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_WORKSPACE")
            child = entry[0]
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            self.workspace_receipt(run_id)
            return {"status": "STOP_REQUESTED"}

    def project_preview(self, request):
        with self.lock:
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            source, task, rows = prepare(request, self.jdk_home is not None)
            require(request["id"] not in self.projects and len(self.projects) < 16, "PROJECT_EXISTS_OR_LIMIT")
            for root in [HERE, self.data]:
                require(source != root and source not in root.parents and root not in source.parents, "PROJECT_OVERLAP")
            self.drafts = {key: value for key, value in self.drafts.items() if value["expires"] > time.monotonic()}
            require(len(self.drafts) < 16, "DRAFT_LIMIT")
            draft_id = secrets.token_hex(8)
            self.drafts[draft_id] = {"kind": "setup", "request": copy.deepcopy(request), "task": task,
                                     "source": source, "expires": time.monotonic() + 300}
            return {"draft": draft_id, "name": request["name"], "files": rows,
                    "checks": task["checks"], "max_turns": task["max_turns"], "total_bytes": sum(r["bytes"] for r in rows)}

    def project_save(self, request):
        with self.lock:
            require(isinstance(request, dict) and set(request) == {"draft"}
                    and isinstance(request["draft"], str), "DRAFT_REQUIRED")
            draft = self.drafts.get(request["draft"])
            require(draft is not None and draft.get("kind") == "setup"
                    and draft["expires"] > time.monotonic(), "DRAFT_EXPIRED")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            source, task, _ = prepare(draft["request"], self.jdk_home is not None)
            require(source == draft["source"] and task == draft["task"], "SETUP_SOURCE_CHANGED")
            require(read_file(self.config_path.parent, self.config_path.name, 262144) == self.config_raw, "CONFIG_CHANGED")
            name = draft["request"]["id"]
            require(name not in self.projects and len(self.projects) < 16, "PROJECT_EXISTS_OR_LIMIT")
            task_path = self.data / "projects" / (name + ".json")
            row = {"id": name, "name": draft["request"]["name"], "source": str(source), "task": str(task_path)}
            config = parse(self.config_raw)
            config["projects"].append(row)
            write_new(task_path, canonical(task))
            replace_json(self.config_path, config)
            self.config_raw = canonical(config)
            self.projects[name] = {**row, "source": source, "task": task_path,
                                   "definition": task, "task_raw": canonical(task)}
            del self.drafts[request["draft"]]
            return {"id": name, "name": row["name"]}

    def current_project(self, project_id):
        require(isinstance(project_id, str) and project_id in self.projects, "PROJECT_UNKNOWN")
        require(read_file(self.config_path.parent, self.config_path.name, 262144)
                == self.config_raw, "CONFIG_CHANGED")
        project = self.projects[project_id]
        raw = read_file(project["task"].parent, project["task"].name, 262144)
        require(raw == project["task_raw"], "PROJECT_TASK_CHANGED")
        return project

    def revision_chain(self, project):
        """Follow only revisions committed by the current config pointer."""
        root = self.data / "revisions" / project["id"]
        path = project["task"]
        if path.name != "task.json" or path.parent.parent != root:
            return []
        revision = path.parent.name
        require(ID.fullmatch(revision) is not None, "REVISION_RECORD_CHANGED")
        rows, seen = [], set()
        expected_sha = sha(project["task_raw"])
        fields = {"format", "project", "id", "created", "parent_revision",
                  "parent_task_sha256", "task_sha256", "files_changed", "goal_changed"}
        while revision is not None:
            require(isinstance(revision, str) and ID.fullmatch(revision) is not None
                    and revision not in seen and len(seen) < 64, "REVISION_RECORD_CHANGED")
            seen.add(revision)
            folder = root / revision
            receipt = json_file(folder / "receipt.json")
            require(isinstance(receipt, dict) and set(receipt) == fields
                    and receipt["format"] == "outlands-project-revision-v1"
                    and receipt["project"] == project["id"] and receipt["id"] == revision
                    and type(receipt["created"]) is int and receipt["created"] >= 0
                    and type(receipt["files_changed"]) is int and 0 <= receipt["files_changed"] <= 32
                    and type(receipt["goal_changed"]) is bool
                    and (receipt["parent_revision"] is None or isinstance(receipt["parent_revision"], str)),
                    "REVISION_RECORD_CHANGED")
            task_raw = read_file(folder, "task.json", 262144)
            parent_raw = read_file(folder, "parent-task.json", 262144)
            require(sha(task_raw) == expected_sha == receipt["task_sha256"]
                    and sha(parent_raw) == receipt["parent_task_sha256"], "REVISION_RECORD_CHANGED")
            task, parent = validate_task(parse(task_raw)), validate_task(parse(parent_raw))
            require(set(task["files"]) == set(parent["files"])
                    and task != parent
                    and all(task[k] == parent[k] for k in ["format", "editable", "checks", "max_turns", "request_seconds"])
                    and receipt["files_changed"] == sum(task["files"][n] != parent["files"][n] for n in task["files"])
                    and receipt["goal_changed"] == (task["goal"] != parent["goal"]), "REVISION_RECORD_CHANGED")
            rows.append({k: receipt[k] for k in ["id", "created", "parent_task_sha256", "task_sha256", "files_changed", "goal_changed"]})
            rows[-1]["current"] = len(rows) == 1
            expected_sha, revision = receipt["parent_task_sha256"], receipt["parent_revision"]
        return rows

    def project_revisions(self, project_id):
        with self.lock:
            project = self.current_project(project_id)
            rows = self.revision_chain(project)
            return {"project": project_id, "name": project["name"], "task_sha256": sha(project["task_raw"]),
                    "revisions": rows[:20], "limit": 20, "truncated": len(rows) > 20}

    def project_refresh_preview(self, request):
        with self.lock:
            require(isinstance(request, dict) and set(request) == {"project", "goal"}, "REFRESH_FIELDS")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            project = self.current_project(request["project"])
            chain = self.revision_chain(project)
            require(len(chain) < 64, "REVISION_LIMIT")
            task, rows = refresh_task(project["source"], project["definition"], request["goal"])
            self.drafts = {key: value for key, value in self.drafts.items() if value["expires"] > time.monotonic()}
            require(len(self.drafts) < 16, "DRAFT_LIMIT")
            draft_id = secrets.token_hex(8)
            self.drafts[draft_id] = {"kind": "refresh", "project": project["id"],
                "task": task, "parent_raw": project["task_raw"], "parent_path": project["task"],
                "parent_revision": chain[0]["id"] if chain else None,
                "config_raw": self.config_raw, "expires": time.monotonic() + 300}
            return {"draft": draft_id, "project": project["id"], "name": project["name"],
                "parent_task_sha256": sha(project["task_raw"]), "task_sha256": sha(canonical(task)),
                "goal": task["goal"], "files": rows, "checks": copy.deepcopy(task["checks"]),
                "max_turns": task["max_turns"], "request_seconds": task["request_seconds"],
                "total_bytes": sum(row["bytes"] for row in rows),
                "files_changed": sum(row["changed"] for row in rows),
                "goal_changed": task["goal"] != project["definition"]["goal"]}

    def project_refresh_save(self, request):
        with self.lock:
            require(isinstance(request, dict) and set(request) == {"draft"}
                    and isinstance(request["draft"], str), "DRAFT_REQUIRED")
            draft = self.drafts.get(request["draft"])
            require(draft is not None and draft.get("kind") == "refresh"
                    and draft["expires"] > time.monotonic(), "DRAFT_EXPIRED")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            project = self.current_project(draft["project"])
            require(self.config_raw == draft["config_raw"], "CONFIG_CHANGED")
            require(project["task"] == draft["parent_path"] and project["task_raw"] == draft["parent_raw"], "PROJECT_TASK_CHANGED")
            chain = self.revision_chain(project)
            require(len(chain) < 64, "REVISION_LIMIT")
            try:
                task, rows = refresh_task(project["source"], project["definition"], draft["task"]["goal"])
            except Refused as exc:
                if str(exc) == "REFRESH_NO_CHANGES":
                    raise Refused("REFRESH_SOURCE_CHANGED") from None
                raise
            require(task == draft["task"], "REFRESH_SOURCE_CHANGED")
            revision = secrets.token_hex(8)
            project_root = self.data / "revisions" / project["id"]
            private_dir(project_root)
            folder = project_root / revision
            folder.mkdir(mode=0o700, exist_ok=False)
            task_path, task_raw = folder / "task.json", canonical(task)
            receipt = {"format": "outlands-project-revision-v1", "project": project["id"],
                "id": revision, "created": int(time.time()), "parent_revision": draft["parent_revision"],
                "parent_task_sha256": sha(draft["parent_raw"]), "task_sha256": sha(task_raw),
                "files_changed": sum(row["changed"] for row in rows),
                "goal_changed": task["goal"] != project["definition"]["goal"]}
            write_new(folder / "parent-task.json", draft["parent_raw"])
            write_new(task_path, task_raw)
            write_new(folder / "receipt.json", canonical(receipt))
            config = parse(self.config_raw)
            for row in config["projects"]:
                if row["id"] == project["id"]:
                    row["task"] = str(task_path)
            self.current_project(project["id"])
            try:
                final_task, _ = refresh_task(project["source"], project["definition"], task["goal"])
            except Refused as exc:
                if str(exc) == "REFRESH_NO_CHANGES":
                    raise Refused("REFRESH_SOURCE_CHANGED") from None
                raise
            require(final_task == task, "REFRESH_SOURCE_CHANGED")
            self.current_project(project["id"])
            # The atomic config pointer is the commit boundary. Prepared files from
            # an interrupted save are retained; history follows only committed links.
            replace_json(self.config_path, config, expected_raw=self.config_raw)
            self.config_raw = canonical(config)
            self.projects[project["id"]] = {**project, "task": task_path, "task_raw": task_raw, "definition": task}
            del self.drafts[request["draft"]]
            return {"id": project["id"], "name": project["name"], "revision": revision, "task_sha256": sha(task_raw)}

    def meta_path(self, run_id):
        require(isinstance(run_id, str) and ID.fullmatch(run_id), "RUN_ID")
        return self.data / "jobs" / (run_id + ".json")

    def metadata(self, run_id):
        return json_file(self.meta_path(run_id))

    def run_path(self, run_id):
        self.meta_path(run_id)
        return self.data / "runs" / run_id

    def result(self, run_id):
        path = self.run_path(run_id) / "result.json"
        if not path.exists():
            return None
        try:
            return json_file(path)
        except (Refused, OSError, ValueError):
            return None

    def refresh(self, meta):
        run_id = meta["id"]
        entry = self.children.get(run_id)
        if entry is not None:
            child, log = entry
            code = child.poll()
            if code is None:
                return meta
            log.close()
            del self.children[run_id]
            meta["exit_code"] = code
        elif meta["state"] in ["RUNNING", "STOP_REQUESTED"]:
            stamp = process_stamp(meta.get("pid", -1))
            if stamp is not None and stamp == meta.get("process_stamp"):
                return {**meta, "state": "RECOVERY_REQUIRED"}
        else:
            return meta
        result = self.result(run_id)
        meta["state"] = (
            result.get("status", "FAILED")
            if isinstance(result, dict)
            else "FAILED"
            if "exit_code" in meta
            else "RECOVERY_REQUIRED"
        )
        meta["finished"] = int(time.time())
        replace_json(self.meta_path(run_id), meta)
        return meta

    def history(self, limit=100):
        with self.lock:
            rows = []
            for path in sorted((self.data / "jobs").glob("*.json")):
                require(ID.fullmatch(path.stem), "HISTORY_ID")
                meta = self.refresh(json_file(path))
                rows.append(
                    {
                        k: meta.get(k)
                        for k in [
                            "id",
                            "project_name",
                            "backend",
                            "model",
                            "goal",
                            "created",
                            "finished",
                            "state",
                        ]
                    }
                )
            rows = sorted(rows, key=lambda x: (x["created"], x["id"]), reverse=True)
            return rows if limit is None else rows[:limit]

    def request_hold(self):
        path = self.data / "state/hold.json"
        present = path.exists() or path.is_symlink()
        try:
            value = json_file(path) if present else None
        except (Refused, OSError, ValueError):
            value = None
        valid = (isinstance(value, dict) and value.get("state") == "REQUEST_UNSETTLED"
                 and type(value.get("turn")) is int and 1 <= value["turn"] <= 16
                 and isinstance(value.get("run"), str))
        return present, value["run"] if valid else None

    def owns_active(self, run_id):
        entry = self.children.get(run_id)
        return entry is not None and entry[0].poll() is None

    def admission(self):
        rows = self.history(limit=None)
        present, held_run = self.request_hold()
        if present:
            if any(held_run == str(self.run_path(row["id"])) and self.owns_active(row["id"]) for row in rows):
                return "MODEL_REQUEST_ACTIVE"
            return "UNCERTAIN_REQUEST_HELD"
        for row in rows:
            receipt = self.workspace_receipt(row["id"])
            if receipt is not None and not verified_workspace_receipt(receipt):
                return "WORKSPACE_ACTIVE_OR_UNRESOLVED"
        try:
            for receipt in self.bundle_workspaces()["workspaces"]:
                if receipt["status"] != "VERIFIED" or receipt.get("owned_active") is True:
                    return "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED"
        except (Refused, OSError, ValueError, KeyError, TypeError):
            return "BUNDLE_WORKSPACE_NEEDS_INSPECTION"
        try:
            if any(row["status"] != "VERIFIED" or row.get("owned_active") is True for row in self._recheck_rows()):
                return "RECHECK_ACTIVE_OR_UNRESOLVED"
        except (Refused, OSError, ValueError, KeyError, TypeError):
            return "RECHECK_NEEDS_INSPECTION"
        try:
            if any(row["status"] != "VERIFIED" or row.get("owned_active") is True
                   for row in self._snapshot_workspace_rows()):
                return "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED"
        except (Refused, OSError, ValueError, KeyError, TypeError):
            return "SNAPSHOT_WORKSPACE_NEEDS_INSPECTION"
        if any(
            r["state"] in ["RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED"]
            for r in rows
        ):
            return "TASK_ACTIVE_OR_UNRESOLVED"
        return None

    def start(self, request):
        with self.lock:
            require(
                isinstance(request, dict)
                and set(request) == {"project", "model", "goal"},
                "START_FIELDS",
            )
            require(
                isinstance(request["project"], str)
                and request["project"] in self.projects,
                "PROJECT_UNKNOWN",
            )
            require(
                isinstance(request["model"], str)
                and request["model"] in ["scripted-demo"] + self.models,
                "MODEL_NOT_CONFIGURED",
            )
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            project = self.current_project(request["project"])
            task = copy.deepcopy(project["definition"])
            self.recheck_draft = None
            self.snapshot_export_draft = None
            self.snapshot_workspace_draft = None
            require(self.jdk_home is not None or not any(
                isinstance(spec, dict) and spec.get("kind") == "java-main"
                for spec in task["checks"].values()), "JDK_REQUIRED")
            require(
                isinstance(request["goal"], str) and 1 <= len(request["goal"]) <= 2000,
                "GOAL_LIMIT",
            )
            if request["model"] == "scripted-demo":
                require(
                    task == json_file(HERE / "task.example.json")
                    and request["goal"] == task["goal"],
                    "SCRIPTED_DEMO_ONLY",
                )
            task["goal"] = request["goal"]
            validate_task(task)
            for name, digest in task["files"].items():
                require(
                    sha(read_file(project["source"], name)) == digest,
                    "SOURCE_HASH_CHANGED",
                )
            run_id = secrets.token_hex(8)
            task_path = self.data / "tasks" / (run_id + ".json")
            write_new(task_path, canonical(task))
            backend = (
                "scripted-demo" if request["model"] == "scripted-demo" else "ollama"
            )
            meta = {
                "id": run_id,
                "project": project["id"],
                "project_name": project["name"],
                "source": str(project["source"]),
                "project_task_sha256": sha(project["task_raw"]),
                "task_sha256": sha(canonical(task)),
                "goal": task["goal"],
                "model": request["model"],
                "backend": backend,
                "created": int(time.time()),
                "state": "RECOVERY_REQUIRED",
            }
            write_new(self.meta_path(run_id), canonical(meta))
            command = [
                sys.executable,
                "-B",
                str(HERE / "agent.py"),
                "--task",
                str(task_path),
                "--source",
                str(project["source"]),
                "--run-dir",
                str(self.run_path(run_id)),
                "--state-dir",
                str(self.data / "state"),
                "--backend",
                backend,
            ]
            if backend == "ollama":
                command += ["--model", request["model"], "--allow-local-inference"]
            if self.jdk_home is not None:
                command += ["--jdk-home", str(self.jdk_home)]
            log_path = self.data / "jobs" / (run_id + ".log")
            fd = os.open(
                log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            log = os.fdopen(fd, "wb")
            try:
                child = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C.UTF-8",
                        "PYTHONNOUSERSITE": "1",
                    },
                )
            except OSError:
                log.close()
                meta.update(state="FAILED", finished=int(time.time()))
                replace_json(self.meta_path(run_id), meta)
                raise Refused("ENGINE_START_FAILED") from None
            self.children[run_id] = (child, log)
            meta.update(
                state="RUNNING", pid=child.pid, process_stamp=process_stamp(child.pid)
            )
            replace_json(self.meta_path(run_id), meta)
            return {"id": run_id}

    def view(self, run_id):
        with self.lock:
            meta = self.refresh(self.metadata(run_id))
            run = self.run_path(run_id)
            task = json_file(self.data / "tasks" / (run_id + ".json"))
            events, plans, checks, diagnostic_events, context = [], [], [], [], []
            turns, pending = 0, 0
            for path in sorted(run.glob("event-*.json")):
                try:
                    event = json_file(path)
                except (Refused, OSError, ValueError):
                    pending += 1
                    continue
                if len(diagnostic_events) <= 256:
                    diagnostic_events.append(event)
                if (not isinstance(event, dict) or not isinstance(event.get("kind"), str)
                        or not isinstance(event.get("value"), dict) or type(event.get("index")) is not int):
                    pending += 1
                    continue
                kind, value = event["kind"], event["value"]
                if kind == "request_started":
                    if type(value.get("turn")) is not int or not 1 <= value["turn"] <= task["max_turns"]:
                        pending += 1
                        continue
                    turns = max(turns, value["turn"])
                    text = "Model turn " + str(value["turn"])
                elif kind == "tool_result":
                    text = value["name"].replace("_", " ")
                    if value["name"] in ["search_text", "read_lines"] and isinstance(value.get("result"), dict):
                        evidence = context_evidence(value["name"], value["result"], task["files"])
                        if evidence is not None:
                            context.append({"kind": value["name"], "index": event["index"], "result": evidence})
                    if value["name"] == "set_plan":
                        plans = value["result"]["steps"]
                    if value["name"] == "run_check":
                        checks.append({"label": "Agent check", **value["result"]})
                elif kind in ["baseline_checks", "independent_final_checks"]:
                    text = (
                        "Baseline checks"
                        if kind == "baseline_checks"
                        else "Independent final checks"
                    )
                    checks.extend(
                        {"label": text + " · " + name, **result}
                        for name, result in value.items()
                    )
                elif kind == "completion":
                    text = value["summary"][:2000]
                else:
                    continue
                events.append({"kind": kind, "text": text, "index": event["index"]})
            result = self.result(run_id)
            patch_path = run / "changes.diff"
            patch_text = (
                read_file(run, "changes.diff", 1048576).decode()
                if patch_path.is_file()
                else ""
            )
            result_hash = sha(canonical(result)) if result else None
            reviews = sorted(run.glob("review-*.json"))
            last_review = json_file(reviews[-1]) if reviews else None
            for entry in checks:
                entry["output"] = entry.get("output", "")[:8192]
            workspace = self.workspace_receipt(run_id)
            hold_present, held_run = self.request_hold()
            diagnostics = summarize_diagnostics(task, result, diagnostic_events, meta["state"], meta["backend"],
                                                self.owns_active(run_id), held_run == str(run), hold_present)
            return {
                "id": run_id,
                "project_name": meta["project_name"],
                "goal": meta["goal"],
                "model": meta["model"],
                "backend": meta["backend"],
                "state": meta["state"],
                "turns": turns,
                "max_turns": task["max_turns"],
                "plan": plans,
                "events": events[-100:],
                "checks": checks,
                "result": result,
                "result_sha256": result_hash,
                "patch_sha256": sha(patch_text.encode())
                if patch_path.is_file()
                else None,
                "patch": patch_text,
                "review": last_review,
                "pending_events": pending,
                "workspace": {**workspace, "owned_active": run_id in self.workspace_children}
                if workspace is not None else None,
                "diagnostics": diagnostics,
                "context": context[-8:],
                "admission_block": self.admission(),
            }

    def verified_artifact(self, run_id, result_hash, patch_hash):
        meta = self.refresh(self.metadata(run_id))
        require(meta["state"] == "REVIEW_READY", "TASK_NOT_REVIEW_READY")
        run = self.run_path(run_id)
        result = self.result(run_id)
        require(
            isinstance(result, dict)
            and result["status"] == "REVIEW_READY"
            and sha(canonical(result)) == result_hash,
            "RESULT_CHANGED",
        )
        evidence = [json_file(path) for path in sorted(run.glob("event-*.json"))]
        final = [
            e["value"] for e in evidence if e["kind"] == "independent_final_checks"
        ]
        require(
            len(final) == 1
            and final[0]
            and all(
                r["exit_code"] == 0
                and r["tests_ran"] > 0
                and not any(
                    r[key]
                    for key in ["timed_out", "output_limited", "infrastructure_error"]
                )
                for r in final[0].values()
            ),
            "FINAL_EVIDENCE_REQUIRED",
        )
        task = json_file(self.data / "tasks" / (run_id + ".json"))
        project = self.projects.get(meta["project"])
        require(
            project is not None and str(project["source"]) == meta["source"],
            "PROJECT_SCOPE_CHANGED",
        )
        require(set(result["files"]) == set(task["files"]), "RESULT_SCOPE_CHANGED")
        patch_text = ""
        for name, digest in sorted(task["files"].items()):
            before = read_file(run / "baseline", name)
            after = read_file(run / "work", name)
            require(
                sha(before) == digest == result["files"][name]["before"],
                "BASELINE_CHANGED",
            )
            require(sha(after) == result["files"][name]["after"], "CANDIDATE_CHANGED")
            require(
                sha(read_file(project["source"], name)) == digest,
                "ORIGINAL_SOURCE_CHANGED",
            )
            if name not in task["editable"]:
                require(sha(after) == digest, "PROTECTED_FILE_CHANGED")
            patch_text += review_diff(name, before, after)
        raw = patch_text.encode()
        require(sha(raw) == patch_hash == result["patch_sha256"], "PATCH_CHANGED")
        require(read_file(run, "changes.diff", 1048576) == raw, "PATCH_CHANGED")
        return raw

    def review(self, request):
        with self.lock:
            require(
                isinstance(request, dict)
                and set(request)
                == {"id", "result_sha256", "patch_sha256", "verdict", "note"},
                "REVIEW_FIELDS",
            )
            require(request["verdict"] in ["accepted", "rejected"], "REVIEW_VERDICT")
            workspace = self.workspace_receipt(request["id"])
            require(workspace is None or workspace["status"] != "PREPARING", "WORKSPACE_ACTIVE_OR_UNRESOLVED")
            require(
                isinstance(request["note"], str) and len(request["note"]) <= 2000,
                "REVIEW_NOTE",
            )
            self.verified_artifact(
                request["id"], request["result_sha256"], request["patch_sha256"]
            )
            run = self.run_path(request["id"])
            reviews = list(run.glob("review-*.json"))
            require(len(reviews) < 100, "REVIEW_LIMIT")
            record = {**request, "recorded": int(time.time()), "source_applied": False}
            write_new(run / f"review-{len(reviews):03d}.json", canonical(record))
            return record

    def export(self, run_id):
        with self.lock:
            view = self.view(run_id)
            review = view["review"]
            require(
                review is not None and review["verdict"] == "accepted",
                "REVIEW_REQUIRED",
            )
            return self.verified_artifact(
                run_id, review["result_sha256"], review["patch_sha256"]
            )

    def bundle_project_check(self, project_id, bundle_raw, expected_sha256=None):
        """Compare private archive bytes with one cached approved project."""
        with self.lock:
            require(type(project_id) is str and project_id in self.projects, "PROJECT_CHECK_PROJECT_UNKNOWN")
            require(type(bundle_raw) is bytes and len(bundle_raw) > 0, "PROJECT_CHECK_INPUT")
            require(len(bundle_raw) <= MAX_ARCHIVE, "PROJECT_CHECK_LIMIT")
            project = self.projects[project_id]
            for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
                fingerprint = self.readiness_fingerprint(path, expected)
                require(fingerprint["status"] != "LIMIT", "PROJECT_CHECK_LIMIT")
                require(fingerprint["status"] == "MATCH", "PROJECT_CHECK_PROJECT_CHANGED")
            report = check_project(bundle_raw, project["source"], project["task_raw"], expected_sha256)
            result = {"version": 1, "project": {"id": project_id, "name": project["name"]},
                      "checked_at_ms": time.time_ns() // 1000000,
                      "config_sha256": sha(self.config_raw), "task_sha256": sha(project["task_raw"]),
                      "comparison": report}
            require(len(canonical(result)) <= 131072, "PROJECT_CHECK_OUTPUT_LIMIT")
            return result

    def snapshot_project_check(self, project_id, archive_raw, expected_sha256=None):
        """Observe a private snapshot export against one approved selected project."""
        with self.lock:
            require(type(project_id) is str and project_id in self.projects, "SNAPSHOT_PROJECT_PROJECT_UNKNOWN")
            require(type(archive_raw) is bytes and len(archive_raw) > 0, "SNAPSHOT_PROJECT_INPUT")
            require(len(archive_raw) <= MAX_ARCHIVE, "SNAPSHOT_PROJECT_LIMIT")
            # Reject unverified archives before opening any configured task/source.
            verify_snapshot_export(archive_raw, expected_sha256)
            project = self.projects[project_id]
            def guard_project():
                for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
                    fingerprint = self.readiness_fingerprint(path, expected)
                    require(fingerprint["status"] != "LIMIT", "SNAPSHOT_PROJECT_LIMIT")
                    require(fingerprint["status"] == "MATCH", "SNAPSHOT_PROJECT_PROJECT_CHANGED")
            guard_project()
            report = check_snapshot_project(archive_raw, project["source"], project["task_raw"], expected_sha256)
            guard_project()
            result = {"version": 1, "project": {"id": project_id, "name": project["name"]},
                      "checked_at_ms": time.time_ns() // 1000000,
                      "config_sha256": sha(self.config_raw), "task_sha256": sha(project["task_raw"]),
                      "comparison": report}
            require(len(canonical(result)) <= 131072, "SNAPSHOT_PROJECT_OUTPUT_LIMIT")
            return result

    def _snapshot_workspace_prepare(self, project_id, raw, expected_sha256=None):
        require(type(project_id) is str and project_id in self.projects, "SNAPSHOT_WORKSPACE_PROJECT_UNKNOWN")
        require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE, "SNAPSHOT_WORKSPACE_INPUT_LIMIT")
        verify_snapshot_export(raw, expected_sha256)
        project = self.projects[project_id]
        def guard_project():
            for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
                require(self.readiness_fingerprint(path, expected)["status"] == "MATCH",
                        "SNAPSHOT_WORKSPACE_PROJECT_CHANGED")
        guard_project()
        prepared = prepare_snapshot_workspace(raw, project["source"], project["task_raw"], expected_sha256)
        guard_project()
        binding = {"version": 1, "project_id": project_id, "archive_sha256": sha(raw),
                   "task_sha256": sha(project["task_raw"]), "config_sha256": sha(self.config_raw),
                   "prepared": prepared["summary"]}
        return project, prepared, sha(canonical(binding))

    def snapshot_workspace_preview(self, project_id, raw, expected_sha256=None):
        """Read-only eligibility and a single memory preview; no admission/worker calls."""
        with self.lock:
            self.snapshot_workspace_draft = None
            project, prepared, pin = self._snapshot_workspace_prepare(project_id, raw, expected_sha256)
            comparison = check_snapshot_project(raw, project["source"], project["task_raw"], sha(raw))
            require(comparison["status"] == "BASELINE_MATCH" and comparison["task_pins_match"] is True
                    and comparison["reconstruction"]["status"] == "VERIFIED", "SNAPSHOT_WORKSPACE_BASELINE_REQUIRED")
            for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
                require(self.readiness_fingerprint(path, expected)["status"] == "MATCH",
                        "SNAPSHOT_WORKSPACE_PROJECT_CHANGED")
            result = {"version": 1, "preview_id": secrets.token_hex(8), "preview_sha256": pin,
                      "project": {"id": project_id, "name": project["name"]},
                      "archive_sha256": sha(raw), "task_sha256": sha(project["task_raw"]),
                      "config_sha256": sha(self.config_raw), "expires_at_ms": time.time_ns() // 1000000 + 300000,
                      "workspace_ready": True, "patch_sha256": prepared["summary"]["patch_sha256"],
                      "files": prepared["summary"]["files"], "comparison": comparison,
                      "java_required": any(isinstance(spec, dict) and spec.get("kind") == "java-main"
                                           for spec in prepared["task"]["checks"].values()),
                      "java_available": self.jdk_home is not None}
            require(len(canonical(result)) <= 131072, "SNAPSHOT_WORKSPACE_OUTPUT_LIMIT")
            self.snapshot_workspace_draft = {"response": result, "raw": raw, "deadline": time.monotonic() + 300}
            return copy.deepcopy(result)

    def snapshot_workspace_create(self, request):
        with self.lock:
            require(type(request) is dict and set(request) == {"preview_id", "preview_sha256"}, "SNAPSHOT_WORKSPACE_FIELDS")
            draft = self.snapshot_workspace_draft
            require(draft is not None, "SNAPSHOT_WORKSPACE_PREVIEW_REQUIRED")
            value = draft["response"]
            require(request["preview_id"] == value["preview_id"] and request["preview_sha256"] == value["preview_sha256"],
                    "SNAPSHOT_WORKSPACE_PREVIEW_CHANGED")
            if time.monotonic() >= draft["deadline"] or time.time_ns() // 1000000 >= value["expires_at_ms"]:
                self.snapshot_workspace_draft = None
                raise Refused("SNAPSHOT_WORKSPACE_PREVIEW_EXPIRED")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            project_id = value["project"]["id"]
            project, prepared, pin = self._snapshot_workspace_prepare(project_id, draft["raw"], value["archive_sha256"])
            require(pin == value["preview_sha256"], "SNAPSHOT_WORKSPACE_PREVIEW_CHANGED")
            require(self.jdk_home is not None or not any(isinstance(spec, dict) and spec.get("kind") == "java-main"
                    for spec in prepared["task"]["checks"].values()), "JDK_REQUIRED")
            require(len(self._snapshot_workspace_rows(reserve_bytes=262144)) < 200, "SNAPSHOT_WORKSPACE_RECORD_LIMIT")
            # Consume before persistent work. A partial creation is retained, never a retry token.
            self.snapshot_workspace_draft = None
            self.bundle_workspace_draft = None
            self.recheck_draft = None
            self.snapshot_export_draft = None
            identifier = secrets.token_hex(8)
            job = self.data / "snapshot-workspaces" / identifier
            job.mkdir(mode=0o700, exist_ok=False)
            receipt = {"version": 1, "format": "outlands-snapshot-workspace-v1", "id": identifier,
                       "project_id": project_id, "status": "PREPARING", "created": int(time.time()),
                       "archive_sha256": value["archive_sha256"], "preview_sha256": pin,
                       "config_sha256": value["config_sha256"], "task_sha256": value["task_sha256"],
                       "patch_sha256": prepared["summary"]["patch_sha256"], "source_applied": False}
            initial_raw = canonical(receipt)
            write_new(job / "receipt.json", initial_raw)
            try:
                write_new(job / "task.json", project["task_raw"])
                write_new(job / "snapshot.zip", draft["raw"])
                worker_request = {"version": 1, "id": identifier, "project_id": project_id,
                                  "source": str(project["source"]), "config_path": str(self.config_path),
                                  "config_sha256": value["config_sha256"], "task_path": str(project["task"]),
                                  "task_sha256": value["task_sha256"], "archive_sha256": value["archive_sha256"],
                                  "preview_sha256": pin}
                write_new(job / "request.json", canonical(worker_request))
                command = [sys.executable, "-B", str(HERE / "snapshot_workspace.py"), "--job-dir", str(job)]
                if self.jdk_home is not None:
                    command += ["--jdk-home", str(self.jdk_home)]
                fd = os.open(job / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                log = os.fdopen(fd, "wb")
                try:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                             start_new_session=True,
                                             env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})
                except BaseException:
                    log.close()
                    raise
                self.snapshot_workspace_children[identifier] = (child, log)
            except (OSError, ValueError, Refused, subprocess.SubprocessError):
                receipt.update(status="FAILED", reason="SNAPSHOT_WORKSPACE_START_FAILED", finished=int(time.time()))
                try:
                    replace_json(job / "receipt.json", receipt, initial_raw)
                except (OSError, ValueError, Refused):
                    pass
                raise Refused("SNAPSHOT_WORKSPACE_START_FAILED") from None
            return self.snapshot_workspace_view(identifier)

    def _snapshot_workspace_record(self, identifier):
        try:
            job = self.data / "snapshot-workspaces" / identifier
            extras, limited = self.readiness_entries(job, lambda name: name == "receipt.json.next", 1)
            require(not limited and not extras, "SNAPSHOT_WORKSPACE_RECORD_INVALID")
            raw = readiness_read_file(job, "receipt.json", 262144)
            value = parse(raw)
            require(valid_snapshot_workspace_receipt(value) and value["id"] == identifier,
                    "SNAPSHOT_WORKSPACE_RECORD_INVALID")
            return raw, value
        except Refused as exc:
            if str(exc).startswith("SNAPSHOT_WORKSPACE_"):
                raise
            raise Refused("SNAPSHOT_WORKSPACE_RECORD_LIMIT" if str(exc) in {"FILE_LIMIT", "JSON_LIMIT"}
                          else "SNAPSHOT_WORKSPACE_RECORD_INVALID") from None
        except (OSError, ValueError, UnicodeError, TypeError, KeyError, RecursionError, AttributeError, OverflowError):
            raise Refused("SNAPSHOT_WORKSPACE_RECORD_INVALID") from None

    def snapshot_workspace_view(self, identifier):
        with self.lock:
            require(type(identifier) is str and ID.fullmatch(identifier) is not None, "SNAPSHOT_WORKSPACE_ID")
            entry = self.snapshot_workspace_children.get(identifier)
            exited = entry is not None and entry[0].poll() is not None
            if exited:
                child, log = self.snapshot_workspace_children.pop(identifier)
                log.close()
            raw, receipt = self._snapshot_workspace_record(identifier)
            if exited and receipt["status"] == "PREPARING":
                receipt.update(status="INTERRUPTED", reason="SNAPSHOT_WORKSPACE_INTERRUPTED", finished=int(time.time()))
                replace_json(self.data / "snapshot-workspaces" / identifier / "receipt.json", receipt, raw)
            return {**receipt, "owned_active": identifier in self.snapshot_workspace_children}

    def _snapshot_workspace_rows(self, reserve_bytes=0):
        try:
            names, limited = self.readiness_entries(self.data / "snapshot-workspaces", lambda _: True, 200)
            require(not limited, "SNAPSHOT_WORKSPACE_RECORD_LIMIT")
            rows, total = [], 0
            for name in names:
                require(ID.fullmatch(name) is not None, "SNAPSHOT_WORKSPACE_RECORD_INVALID")
                row = self.snapshot_workspace_view(name)
                raw, _ = self._snapshot_workspace_record(name)
                total += len(raw)
                require(total <= 2097152 - reserve_bytes, "SNAPSHOT_WORKSPACE_RECORD_LIMIT")
                rows.append({key: row[key] for key in ["version", "format", "id", "project_id", "status", "created",
                             "archive_sha256", "preview_sha256", "source_applied", "owned_active", "finished", "reason",
                             "path", "branch", "baseline_commit"] if key in row})
            return rows
        except Refused:
            raise
        except (OSError, ValueError, UnicodeError, TypeError, KeyError, RecursionError, AttributeError, OverflowError):
            raise Refused("SNAPSHOT_WORKSPACE_RECORD_INVALID") from None

    def snapshot_workspaces(self):
        with self.lock:
            response = {"version": 1, "workspaces": self._snapshot_workspace_rows()}
            require(len(canonical(response)) <= 262144, "SNAPSHOT_WORKSPACE_OUTPUT_LIMIT")
            return response

    def snapshot_workspace_stop(self, identifier):
        with self.lock:
            self.snapshot_workspace_view(identifier)
            entry = self.snapshot_workspace_children.get(identifier)
            require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_SNAPSHOT_WORKSPACE")
            child = entry[0]
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            return self.snapshot_workspace_view(identifier)

    def _bundle_workspace_prepare(self, project_id, raw, expected_sha256=None):
        require(type(project_id) is str and project_id in self.projects, "BUNDLE_WORKSPACE_PROJECT_UNKNOWN")
        require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE, "BUNDLE_WORKSPACE_INPUT_LIMIT")
        project = self.projects[project_id]
        for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
            require(self.readiness_fingerprint(path, expected)["status"] == "MATCH",
                    "BUNDLE_WORKSPACE_PROJECT_CHANGED")
        prepared = prepare_bundle_workspace(raw, project["source"], project["task_raw"], expected_sha256)
        binding = {"version": 1, "project_id": project_id, "bundle_sha256": sha(raw),
                   "task_sha256": sha(project["task_raw"]), "config_sha256": sha(self.config_raw),
                   "prepared": prepared["summary"]}
        return project, prepared, sha(canonical(binding))

    def bundle_workspace_preview(self, project_id, raw, expected_sha256=None):
        """One memory-only, expiring review; no admission reconciliation or execution."""
        with self.lock:
            self.bundle_workspace_draft = None
            project, prepared, pin = self._bundle_workspace_prepare(project_id, raw, expected_sha256)
            now = time.time_ns() // 1000000
            result = {"version": 1, "preview_id": secrets.token_hex(8), "preview_sha256": pin,
                      "project": {"id": project_id, "name": project["name"]},
                      "bundle_sha256": sha(raw), "task_sha256": sha(project["task_raw"]),
                      "config_sha256": sha(self.config_raw), "expires_at_ms": now + 300000,
                      "workspace_ready": True, "patch_sha256": prepared["summary"]["patch_sha256"],
                      "files": prepared["summary"]["files"],
                      "comparison": check_project(raw, project["source"], project["task_raw"], sha(raw))}
            require(result["comparison"]["status"] == "BASELINE_MATCH", "BUNDLE_WORKSPACE_BASELINE_REQUIRED")
            require(len(canonical(result)) <= 131072, "BUNDLE_WORKSPACE_OUTPUT_LIMIT")
            self.bundle_workspace_draft = {"response": result, "raw": raw,
                                           "deadline": time.monotonic() + 300}
            return copy.deepcopy(result)

    def bundle_workspace_create(self, request):
        with self.lock:
            require(type(request) is dict and set(request) == {"preview_id", "preview_sha256"},
                    "BUNDLE_WORKSPACE_FIELDS")
            draft = self.bundle_workspace_draft
            require(draft is not None, "BUNDLE_WORKSPACE_PREVIEW_REQUIRED")
            value = draft["response"]
            require(request["preview_id"] == value["preview_id"]
                    and request["preview_sha256"] == value["preview_sha256"], "BUNDLE_WORKSPACE_PREVIEW_CHANGED")
            if time.monotonic() >= draft["deadline"] or time.time_ns() // 1000000 >= value["expires_at_ms"]:
                self.bundle_workspace_draft = None
                raise Refused("BUNDLE_WORKSPACE_PREVIEW_EXPIRED")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            project_id = value["project"]["id"]
            project, prepared, pin = self._bundle_workspace_prepare(project_id, draft["raw"], value["bundle_sha256"])
            require(pin == value["preview_sha256"], "BUNDLE_WORKSPACE_PREVIEW_CHANGED")
            require(self.jdk_home is not None or not any(isinstance(spec, dict) and spec.get("kind") == "java-main"
                    for spec in project["definition"]["checks"].values()), "JDK_REQUIRED")
            # Consume the draft before any persistent work. A partial failure is never a retry token.
            self.bundle_workspace_draft = None
            self.recheck_draft = None
            self.snapshot_export_draft = None
            self.snapshot_workspace_draft = None
            workspace_id = secrets.token_hex(8)
            job = self.data / "bundle-workspaces" / workspace_id
            job.mkdir(mode=0o700, exist_ok=False)
            receipt = {"version": 1, "format": "outlands-bundle-workspace-v1", "id": workspace_id,
                       "project_id": project_id, "status": "PREPARING", "created": int(time.time()),
                       "bundle_sha256": value["bundle_sha256"], "preview_sha256": pin,
                       "config_sha256": value["config_sha256"], "task_sha256": value["task_sha256"],
                       "patch_sha256": prepared["summary"]["patch_sha256"], "source_applied": False}
            write_new(job / "receipt.json", canonical(receipt))
            try:
                write_new(job / "task.json", project["task_raw"])
                write_new(job / "bundle.zip", draft["raw"])
                worker_request = {"version": 1, "id": workspace_id, "project_id": project_id,
                                  "source": str(project["source"]), "config_path": str(self.config_path),
                                  "config_sha256": value["config_sha256"], "task_path": str(project["task"]),
                                  "task_sha256": value["task_sha256"], "bundle_sha256": value["bundle_sha256"],
                                  "preview_sha256": pin}
                write_new(job / "request.json", canonical(worker_request))
                command = [sys.executable, "-B", str(HERE / "bundle_workspace.py"), "--job-dir", str(job)]
                if self.jdk_home is not None:
                    command += ["--jdk-home", str(self.jdk_home)]
                fd = os.open(job / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                log = os.fdopen(fd, "wb")
                try:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                             start_new_session=True,
                                             env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})
                except BaseException:
                    log.close()
                    raise
                self.bundle_workspace_children[workspace_id] = (child, log)
            except (OSError, ValueError, Refused, subprocess.SubprocessError):
                receipt.update(status="FAILED", reason="BUNDLE_WORKSPACE_START_FAILED", finished=int(time.time()))
                replace_json(job / "receipt.json", receipt)
                raise Refused("BUNDLE_WORKSPACE_START_FAILED") from None
            return self.bundle_workspace_view(workspace_id)

    def bundle_workspace_view(self, workspace_id):
        with self.lock:
            require(type(workspace_id) is str and ID.fullmatch(workspace_id) is not None,
                    "BUNDLE_WORKSPACE_ID")
            job = self.data / "bundle-workspaces" / workspace_id
            entry = self.bundle_workspace_children.get(workspace_id)
            exited = entry is not None and entry[0].poll() is not None
            if exited:
                child, log = self.bundle_workspace_children.pop(workspace_id)
                log.close()
            raw = readiness_read_file(job, "receipt.json", 262144)
            receipt = parse(raw)
            require(type(receipt) is dict and receipt.get("id") == workspace_id
                    and type(receipt.get("version")) is int and receipt["version"] == 1
                    and receipt.get("source_applied") is False and type(receipt.get("status")) is str
                    and receipt["status"] in {"PREPARING", "VERIFIED", "FAILED", "INTERRUPTED"},
                    "BUNDLE_WORKSPACE_RECORD_INVALID")
            require(all(type(receipt.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", receipt[key]) is not None
                        for key in ["bundle_sha256", "preview_sha256", "config_sha256", "task_sha256", "patch_sha256"]),
                    "BUNDLE_WORKSPACE_RECORD_INVALID")
            require(type(receipt.get("project_id")) is str and ALIAS.fullmatch(receipt["project_id"]) is not None,
                    "BUNDLE_WORKSPACE_RECORD_INVALID")
            if receipt["status"] == "VERIFIED":
                require(verified_workspace_receipt({**receipt, "result_sha256": receipt["bundle_sha256"]}),
                        "BUNDLE_WORKSPACE_RECORD_INVALID")
            if exited:
                if receipt["status"] == "PREPARING":
                    receipt.update(status="INTERRUPTED", reason="BUNDLE_WORKSPACE_INTERRUPTED", finished=int(time.time()))
                    replace_json(job / "receipt.json", receipt, raw)
            return {**receipt, "owned_active": workspace_id in self.bundle_workspace_children}

    def bundle_workspaces(self):
        with self.lock:
            names, truncated = self.readiness_entries(self.data / "bundle-workspaces", lambda _: True, 200)
            require(not truncated, "BUNDLE_WORKSPACE_RECORD_LIMIT")
            result = []
            for name in names:
                require(ID.fullmatch(name) is not None, "BUNDLE_WORKSPACE_RECORD_INVALID")
                row = self.bundle_workspace_view(name)
                result.append({key: row[key] for key in ["version", "id", "project_id", "status", "created",
                              "bundle_sha256", "preview_sha256", "source_applied", "owned_active", "finished", "reason",
                              "path", "branch", "baseline_commit"] if key in row})
            response = {"version": 1, "workspaces": result}
            require(len(canonical(response)) <= 262144, "BUNDLE_WORKSPACE_OUTPUT_LIMIT")
            return response

    def bundle_workspace_stop(self, workspace_id):
        with self.lock:
            self.bundle_workspace_view(workspace_id)
            entry = self.bundle_workspace_children.get(workspace_id)
            require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_BUNDLE_WORKSPACE")
            child = entry[0]
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            return self.bundle_workspace_view(workspace_id)

    def _snapshot_acceptances(self, exclude_id=None, reserve_bytes=0):
        """Hash bounded raw receipts; never reconcile, repair or skip damaged records."""
        try:
            names, limited = self.readiness_entries(self.data / "snapshot-exports", lambda _: True, 200)
            require(not limited, "SNAPSHOT_EXPORT_LIMIT")
            rows, pins, total, unresolved = [], [], 0, False
            for name in names:
                require(ID.fullmatch(name) is not None, "SNAPSHOT_EXPORT_RECORD_INVALID")
                directory = self.data / "snapshot-exports" / name
                entries, limited = self.readiness_entries(directory, lambda _: True, 3)
                require(not limited and set(entries) <= {"receipt.json", "review.json", "receipt.json.next"},
                        "SNAPSHOT_EXPORT_RECORD_INVALID")
                raw = readiness_read_file(directory, "receipt.json", 32768)
                total += len(raw)
                require(total <= 2097152 - reserve_bytes, "SNAPSHOT_EXPORT_LIMIT")
                value = parse(raw)
                require(valid_snapshot_acceptance(value) and value["id"] == name, "SNAPSHOT_EXPORT_RECORD_INVALID")
                if value["status"] == "ACCEPTED":
                    review_raw = readiness_read_file(directory, "review.json", 131072)
                    require(sha(review_raw) == value["review_sha256"]
                            and valid_snapshot_review(parse(review_raw), value), "SNAPSHOT_EXPORT_RECORD_INVALID")
                if name == exclude_id:
                    continue
                unresolved |= value["status"] != "ACCEPTED" or "receipt.json.next" in entries
                require(value["status"] != "ACCEPTED" or "review.json" in entries, "SNAPSHOT_EXPORT_RECORD_INVALID")
                digest = sha(raw)
                pins.append({"id": name, "receipt_sha256": digest})
                rows.append({**value, "receipt_sha256": digest})
            return rows, sha(canonical(pins)), unresolved
        except Refused as exc:
            if str(exc).startswith("SNAPSHOT_EXPORT_"):
                raise
            raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None
        except (OSError, ValueError, UnicodeError):
            raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None

    def _snapshot_prepared(self, attempt_id, expected_receipt_sha256=None):
        require(type(attempt_id) is str and ID.fullmatch(attempt_id) is not None, "SNAPSHOT_EXPORT_ID")
        try:
            attempt = self.data / "workspace-rechecks" / attempt_id
            raw = readiness_read_file(attempt, "receipt.json", 262144)
            receipt = parse(raw)
            require(valid_recheck_receipt(receipt) and receipt["id"] == attempt_id, "SNAPSHOT_EXPORT_RECORD_INVALID")
            require(receipt["status"] == "VERIFIED", "SNAPSHOT_EXPORT_VERIFIED_REQUIRED")
            self._recheck_inspection(receipt["workspace_id"])
            return prepare_snapshot_export(attempt, expected_receipt_sha256 or sha(raw))
        except Refused as exc:
            if str(exc).startswith("SNAPSHOT_EXPORT_"):
                raise
            if str(exc) == "RECHECK_PROJECT_CHANGED":
                raise Refused("SNAPSHOT_EXPORT_PROJECT_CHANGED") from None
            raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None
        except (OSError, ValueError, UnicodeError, KeyError, TypeError):
            raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None

    def _snapshot_recheck_history(self):
        try:
            return recheck_history_pin(self.data / "workspace-rechecks")
        except (Refused, OSError, ValueError):
            raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None

    @staticmethod
    def _snapshot_preview_pin(summary, rechecks, acceptances):
        return sha(canonical({"prepared": summary, "recheck_history_sha256": rechecks,
                              "acceptance_history_sha256": acceptances}))

    def snapshot_export_preview(self, request):
        """Prepare a short-lived read-only review; no worker or admission inspection."""
        with self.lock:
            self.snapshot_export_draft = None
            require(type(request) is dict and set(request) == {"attempt_id"}, "SNAPSHOT_EXPORT_FIELDS")
            prepared = self._snapshot_prepared(request["attempt_id"])
            rechecks = self._snapshot_recheck_history()
            _, acceptances, _ = self._snapshot_acceptances()
            result = {"version": 1, "preview_id": secrets.token_hex(8),
                      "preview_sha256": self._snapshot_preview_pin(prepared["summary"], rechecks, acceptances),
                      "expires_at_ms": time.time_ns() // 1000000 + 300000,
                      "recheck_history_sha256": rechecks, "acceptance_history_sha256": acceptances,
                      "artifact": prepared["summary"]}
            require(len(canonical(result)) <= 131072, "SNAPSHOT_EXPORT_OUTPUT_LIMIT")
            self.snapshot_export_draft = {"response": result, "deadline": time.monotonic() + 300}
            return copy.deepcopy(result)

    def snapshot_export_accept(self, request):
        """Persist only explicit local acceptance metadata, never patch application."""
        with self.lock:
            require(type(request) is dict and set(request) == {"preview_id", "preview_sha256", "note"},
                    "SNAPSHOT_EXPORT_FIELDS")
            require(snapshot_export_note(request["note"]), "SNAPSHOT_EXPORT_NOTE_INVALID")
            draft = self.snapshot_export_draft
            require(draft is not None, "SNAPSHOT_EXPORT_PREVIEW_REQUIRED")
            value = draft["response"]
            require(request["preview_id"] == value["preview_id"] and request["preview_sha256"] == value["preview_sha256"],
                    "SNAPSHOT_EXPORT_PREVIEW_CHANGED")
            if time.monotonic() >= draft["deadline"] or time.time_ns() // 1000000 >= value["expires_at_ms"]:
                self.snapshot_export_draft = None
                raise Refused("SNAPSHOT_EXPORT_PREVIEW_EXPIRED")
            summary = value["artifact"]
            prepared = self._snapshot_prepared(summary["attempt_id"], summary["receipt_sha256"])
            rows, parent, unresolved = self._snapshot_acceptances(reserve_bytes=32768)
            require(not unresolved, "SNAPSHOT_EXPORT_HISTORY_UNRESOLVED")
            require(len(rows) < 200, "SNAPSHOT_EXPORT_LIMIT")
            rechecks = self._snapshot_recheck_history()
            require(self._snapshot_preview_pin(prepared["summary"], rechecks, parent) == value["preview_sha256"],
                    "SNAPSHOT_EXPORT_PREVIEW_CHANGED")
            self.snapshot_export_draft = None
            identifier = secrets.token_hex(8)
            directory = self.data / "snapshot-exports" / identifier
            directory.mkdir(mode=0o700, exist_ok=False)
            review_raw = canonical(value)
            receipt = {"version": 1, "format": EXPORT_FORMAT, "id": identifier,
                       "attempt_id": summary["attempt_id"], "workspace_id": summary["workspace_id"],
                       "status": "PREPARING", "created": int(time.time()), "source_applied": False,
                       "workspace_modified": False, "preview_sha256": value["preview_sha256"],
                       "prepared_sha256": sha(canonical(summary)), "review_sha256": sha(review_raw),
                       "recheck_history_sha256": rechecks, "parent_acceptance_history_sha256": parent,
                       "recheck_receipt_sha256": summary["receipt_sha256"], "snapshot_sha256": summary["snapshot_sha256"],
                       "patch_sha256": summary["patch_sha256"], "verification_sha256": summary["verification_sha256"],
                       "archive_sha256": summary["archive_sha256"], "note": request["note"]}
            initial_raw = canonical(receipt)
            try:
                write_new(directory / "receipt.json", initial_raw)
                write_new(directory / "review.json", review_raw)
                fresh = self._snapshot_prepared(summary["attempt_id"], summary["receipt_sha256"])
                _, after_parent, after_unresolved = self._snapshot_acceptances(exclude_id=identifier)
                require(not after_unresolved and after_parent == parent
                        and self._snapshot_recheck_history() == rechecks
                        and fresh["summary"] == summary
                        and readiness_read_file(directory, "review.json", 131072) == review_raw,
                        "SNAPSHOT_EXPORT_PREVIEW_CHANGED")
                receipt.update(status="ACCEPTED", finished=int(time.time()))
                replace_json(directory / "receipt.json", receipt, initial_raw)
            except (Refused, OSError, ValueError, UnicodeError, KeyError, TypeError):
                # Preserve this attempt. A failed/partial record blocks later export acceptance.
                receipt.update(status="FAILED", finished=int(time.time()), reason="SNAPSHOT_EXPORT_ACCEPT_FAILED")
                try:
                    replace_json(directory / "receipt.json", receipt, initial_raw)
                except (Refused, OSError, ValueError):
                    pass
                raise Refused("SNAPSHOT_EXPORT_ACCEPT_FAILED") from None
            raw = canonical(receipt)
            require(len(raw) <= 32768, "SNAPSHOT_EXPORT_LIMIT")
            return {"version": 1, "acceptance_id": identifier, "receipt_sha256": sha(raw), "receipt": receipt}

    def snapshot_export_history(self, attempt_id):
        with self.lock:
            require(type(attempt_id) is str and ID.fullmatch(attempt_id) is not None, "SNAPSHOT_EXPORT_ID")
            rows, pin, _ = self._snapshot_acceptances()
            result = {"version": 1, "attempt_id": attempt_id, "history_sha256": pin,
                      "acceptances": [row for row in rows if row["attempt_id"] == attempt_id]}
            require(len(canonical(result)) <= 262144, "SNAPSHOT_EXPORT_OUTPUT_LIMIT")
            return result

    def snapshot_export_download(self, request):
        """Rebuild an unchanged accepted packet in memory; no record writes or execution."""
        with self.lock:
            require(type(request) is dict and set(request) == {"acceptance_id", "receipt_sha256", "archive_sha256"},
                    "SNAPSHOT_EXPORT_FIELDS")
            require(type(request["acceptance_id"]) is str and ID.fullmatch(request["acceptance_id"]) is not None,
                    "SNAPSHOT_EXPORT_ID")
            require(all(type(request[k]) is str and SHA256.fullmatch(request[k]) is not None
                        for k in ["receipt_sha256", "archive_sha256"]), "SNAPSHOT_EXPORT_FIELDS")
            identifier = request["acceptance_id"]
            rows, _, unresolved = self._snapshot_acceptances()
            require(not unresolved, "SNAPSHOT_EXPORT_HISTORY_UNRESOLVED")
            row = next((row for row in rows if row["id"] == identifier), None)
            require(row is not None and row["status"] == "ACCEPTED", "SNAPSHOT_EXPORT_ACCEPT_REQUIRED")
            require(row["receipt_sha256"] == request["receipt_sha256"]
                    and row["archive_sha256"] == request["archive_sha256"], "SNAPSHOT_EXPORT_ARCHIVE_CHANGED")
            _, parent, unresolved = self._snapshot_acceptances(exclude_id=identifier)
            require(not unresolved and parent == row["parent_acceptance_history_sha256"]
                    and self._snapshot_recheck_history() == row["recheck_history_sha256"], "SNAPSHOT_EXPORT_HISTORY_CHANGED")
            try:
                review_raw = readiness_read_file(self.data / "snapshot-exports" / identifier, "review.json", 131072)
                require(sha(review_raw) == row["review_sha256"], "SNAPSHOT_EXPORT_RECORD_INVALID")
                review = parse(review_raw)
                require(type(review) is dict and set(review) == {"version", "preview_id", "preview_sha256",
                        "expires_at_ms", "recheck_history_sha256", "acceptance_history_sha256", "artifact"},
                        "SNAPSHOT_EXPORT_RECORD_INVALID")
                fresh = self._snapshot_prepared(row["attempt_id"], row["recheck_receipt_sha256"])
                summary = fresh["summary"]
                require(review["artifact"] == summary and sha(canonical(summary)) == row["prepared_sha256"]
                        and self._snapshot_preview_pin(summary, row["recheck_history_sha256"], parent) == row["preview_sha256"]
                        and review["preview_sha256"] == row["preview_sha256"]
                        and review["recheck_history_sha256"] == row["recheck_history_sha256"]
                        and review["acceptance_history_sha256"] == parent
                        and all(row[key] == summary[key] for key in ["workspace_id", "snapshot_sha256", "patch_sha256",
                                                                   "verification_sha256", "archive_sha256"]),
                        "SNAPSHOT_EXPORT_PREVIEW_CHANGED")
                require(sha(fresh["archive"]) == request["archive_sha256"], "SNAPSHOT_EXPORT_ARCHIVE_CHANGED")
                # History is checked again after reconstruction to catch concurrent external changes.
                _, end_parent, end_unresolved = self._snapshot_acceptances(exclude_id=identifier)
                end_raw = readiness_read_file(self.data / "snapshot-exports" / identifier, "receipt.json", 32768)
                require(not end_unresolved and end_parent == parent and sha(end_raw) == request["receipt_sha256"]
                        and self._snapshot_recheck_history() == row["recheck_history_sha256"]
                        and readiness_read_file(self.data / "snapshot-exports" / identifier, "review.json", 131072) == review_raw,
                        "SNAPSHOT_EXPORT_HISTORY_CHANGED")
                return fresh["archive"]
            except Refused as exc:
                if str(exc).startswith("SNAPSHOT_EXPORT_"):
                    raise
                raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None
            except (OSError, ValueError, UnicodeError, KeyError, TypeError):
                raise Refused("SNAPSHOT_EXPORT_RECORD_INVALID") from None

    def _recheck_inspection(self, workspace_id):
        require(type(workspace_id) is str and ID.fullmatch(workspace_id) is not None, "RECHECK_ID")
        job = self.data / "bundle-workspaces" / workspace_id
        try:
            creation_raw = readiness_read_file(job, "receipt.json", 262144)
            creation = parse(creation_raw)
            request = parse(readiness_read_file(job, "request.json", 32768))
        except FileNotFoundError:
            raise Refused("RECHECK_CREATION_REQUIRED") from None
        except (Refused, OSError, ValueError):
            raise Refused("RECHECK_RECORD_INVALID") from None
        require(type(creation) is dict and type(request) is dict
                and type(creation.get("project_id")) is str and creation["project_id"] in self.projects,
                "RECHECK_CREATION_REQUIRED")
        project = self.projects[creation["project_id"]]
        require(request.get("project_id") == project["id"] and request.get("id") == workspace_id
                and request.get("source") == str(project["source"])
                and request.get("task_path") == str(project["task"])
                and request.get("config_path") == str(self.config_path)
                and request.get("task_sha256") == sha(project["task_raw"])
                and request.get("config_sha256") == sha(self.config_raw), "RECHECK_PROJECT_CHANGED")
        for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
            require(self.readiness_fingerprint(path, expected)["status"] == "MATCH", "RECHECK_PROJECT_CHANGED")
        inspected = inspect_recheck(job, sha(creation_raw))
        return inspected

    def recheck_preview(self, request):
        """Read only saved creation evidence, current selected bytes and Git metadata."""
        with self.lock:
            self.recheck_draft = None
            self.snapshot_export_draft = None
            self.snapshot_workspace_draft = None
            require(type(request) is dict and set(request) == {"workspace_id"}, "RECHECK_FIELDS")
            inspected = self._recheck_inspection(request["workspace_id"])
            history = recheck_history_pin(self.data / "workspace-rechecks")
            pin = sha(canonical({"inspection": inspected["summary"], "history_sha256": history}))
            result = {"version": 1, "workspace_id": request["workspace_id"], "preview_id": secrets.token_hex(8),
                      "preview_sha256": pin, "expires_at_ms": time.time_ns() // 1000000 + 300000,
                      "history_sha256": history, "inspection": inspected["summary"]}
            require(len(canonical(result)) <= 131072, "RECHECK_OUTPUT_LIMIT")
            self.recheck_draft = {"response": result, "deadline": time.monotonic() + 300}
            return copy.deepcopy(result)

    def recheck_start(self, request):
        with self.lock:
            require(type(request) is dict and set(request) == {"preview_id", "preview_sha256"}, "RECHECK_FIELDS")
            draft = self.recheck_draft
            require(draft is not None, "RECHECK_PREVIEW_REQUIRED")
            value = draft["response"]
            require(request["preview_id"] == value["preview_id"]
                    and request["preview_sha256"] == value["preview_sha256"], "RECHECK_PREVIEW_CHANGED")
            if time.monotonic() >= draft["deadline"] or time.time_ns() // 1000000 >= value["expires_at_ms"]:
                self.recheck_draft = None
                raise Refused("RECHECK_PREVIEW_EXPIRED")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            inspected = self._recheck_inspection(value["workspace_id"])
            require(len(self._recheck_rows(reserve_bytes=262144)) < 200, "RECHECK_LIMIT")
            history = recheck_history_pin(self.data / "workspace-rechecks")
            pin = sha(canonical({"inspection": inspected["summary"], "history_sha256": history}))
            require(pin == value["preview_sha256"], "RECHECK_PREVIEW_CHANGED")
            require(self.jdk_home is not None or not any(isinstance(spec, dict) and spec.get("kind") == "java-main"
                    for spec in inspected["task"]["checks"].values()), "JDK_REQUIRED")
            self.recheck_draft = None
            self.bundle_workspace_draft = None
            self.snapshot_export_draft = None
            self.snapshot_workspace_draft = None
            attempt_id = secrets.token_hex(8)
            attempt = self.data / "workspace-rechecks" / attempt_id
            attempt.mkdir(mode=0o700, exist_ok=False)
            receipt = {"version": 1, "format": "outlands-workspace-recheck-v1", "id": attempt_id,
                       "workspace_id": value["workspace_id"], "status": "PREPARING", "created": int(time.time()),
                       "source_applied": False, "workspace_modified": False,
                       "creation_sha256": inspected["summary"]["creation_sha256"],
                       "preview_sha256": pin, "history_sha256": history}
            write_new(attempt / "receipt.json", canonical(receipt))
            try:
                worker_request = {"version": 1, "id": attempt_id, "workspace_id": value["workspace_id"],
                                  "job_dir": str(self.data / "bundle-workspaces" / value["workspace_id"]),
                                  "preview_sha256": pin, "creation_sha256": receipt["creation_sha256"],
                                  "history_sha256": history}
                write_new(attempt / "request.json", canonical(worker_request))
                command = [sys.executable, "-B", str(HERE / "workspace_recheck.py"), "--attempt-dir", str(attempt)]
                if self.jdk_home is not None:
                    command += ["--jdk-home", str(self.jdk_home)]
                fd = os.open(attempt / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                log = os.fdopen(fd, "wb")
                try:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                             start_new_session=True,
                                             env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})
                except BaseException:
                    log.close()
                    raise
                self.recheck_children[attempt_id] = (child, log)
            except (OSError, ValueError, Refused, subprocess.SubprocessError):
                receipt.update(status="FAILED", reason="RECHECK_START_FAILED", finished=int(time.time()))
                replace_json(attempt / "receipt.json", receipt)
                raise Refused("RECHECK_START_FAILED") from None
            return self.recheck_view(attempt_id)

    def recheck_view(self, attempt_id):
        with self.lock:
            require(type(attempt_id) is str and ID.fullmatch(attempt_id) is not None, "RECHECK_ID")
            attempt = self.data / "workspace-rechecks" / attempt_id
            entry = self.recheck_children.get(attempt_id)
            exited = entry is not None and entry[0].poll() is not None
            if exited:
                child, log = self.recheck_children.pop(attempt_id)
                log.close()
            try:
                raw = readiness_read_file(attempt, "receipt.json", 262144)
                receipt = parse(raw)
            except (Refused, OSError, ValueError):
                raise Refused("RECHECK_RECORD_INVALID") from None
            require(valid_recheck_receipt(receipt) and receipt["id"] == attempt_id, "RECHECK_RECORD_INVALID")
            if exited and receipt["status"] == "PREPARING":
                receipt.update(status="INTERRUPTED", reason="RECHECK_INTERRUPTED", finished=int(time.time()))
                replace_json(attempt / "receipt.json", receipt, raw)
            return {**receipt, "owned_active": attempt_id in self.recheck_children}

    def _recheck_rows(self, reserve_bytes=0):
        names, truncated = self.readiness_entries(self.data / "workspace-rechecks", lambda _: True, 200)
        require(not truncated, "RECHECK_LIMIT")
        rows, record_bytes = [], 0
        for name in names:
            require(ID.fullmatch(name) is not None, "RECHECK_RECORD_INVALID")
            row = self.recheck_view(name)
            record_bytes += len(readiness_read_file(self.data / "workspace-rechecks" / name, "receipt.json", 262144))
            require(record_bytes <= 2097152 - reserve_bytes, "RECHECK_LIMIT")
            rows.append({key: row[key] for key in ["version", "id", "workspace_id", "status", "created", "finished",
                        "reason", "source_applied", "workspace_modified", "owned_active", "creation_sha256",
                        "preview_sha256", "history_sha256", "snapshot_sha256"] if key in row})
        return rows

    def rechecks(self, workspace_id):
        with self.lock:
            require(type(workspace_id) is str and ID.fullmatch(workspace_id) is not None, "RECHECK_ID")
            rows = self._recheck_rows()
            result = {"version": 1, "workspace_id": workspace_id,
                      "history_sha256": recheck_history_pin(self.data / "workspace-rechecks"),
                      "rechecks": [row for row in rows if row["workspace_id"] == workspace_id]}
            require(len(canonical(result)) <= 262144, "RECHECK_OUTPUT_LIMIT")
            return result

    def recheck_stop(self, attempt_id):
        with self.lock:
            self.recheck_view(attempt_id)
            entry = self.recheck_children.get(attempt_id)
            require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_RECHECK")
            child = entry[0]
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            return self.recheck_view(attempt_id)

    def _bundle_bytes(self, run_id):
        """Verify saved accepted artifacts without live reconciliation or writes."""
        require(type(run_id) is str and ID.fullmatch(run_id) is not None, "BUNDLE_RUN_UNKNOWN")
        require(run_id not in self.children and run_id not in self.workspace_children, "BUNDLE_NOT_REVIEW_READY")

        def record(root, name, limit=262144):
            raw = readiness_read_file(root, name, limit)
            value = parse(raw)
            require(type(value) is dict, "BUNDLE_RECORD_INVALID")
            return raw, value

        try:
            _, meta = record(self.data, "jobs/" + run_id + ".json", 32768)
        except FileNotFoundError:
            raise Refused("BUNDLE_RUN_UNKNOWN") from None
        require(meta.get("id") == run_id, "BUNDLE_RECORD_INVALID")
        require(meta.get("state") == "REVIEW_READY", "BUNDLE_NOT_REVIEW_READY")
        project = self.projects.get(meta.get("project")) if type(meta.get("project")) is str else None
        require(project is not None and meta.get("source") == str(project["source"]), "BUNDLE_PROJECT_CHANGED")
        for path, expected in [(self.config_path, self.config_raw), (project["task"], project["task_raw"])]:
            fingerprint = self.readiness_fingerprint(path, expected)
            require(fingerprint["status"] != "LIMIT", "BUNDLE_RECORD_LIMIT")
            require(fingerprint["status"] == "MATCH", "BUNDLE_PROJECT_CHANGED")
        task_raw, task = record(self.data, "tasks/" + run_id + ".json")
        validate_task(task)
        require(meta.get("task_sha256") == sha(task_raw)
                and meta.get("project_task_sha256") == sha(project["task_raw"]), "BUNDLE_PIN_REQUIRED")
        approved = project["definition"]
        require(all(task[key] == approved[key] for key in
                    ["format", "files", "editable", "checks", "max_turns", "request_seconds"]), "BUNDLE_PROJECT_CHANGED")
        run = self.data / "runs" / run_id
        result_raw, result = record(run, "result.json")
        require(result.get("status") == "REVIEW_READY", "BUNDLE_NOT_REVIEW_READY")
        require(type(result.get("files")) is dict and set(result["files"]) == set(task["files"]), "BUNDLE_ARTIFACT_CHANGED")

        reviews, limited = self.readiness_entries(run, lambda name: name.startswith("review-"), 100)
        require(not limited, "BUNDLE_RECORD_LIMIT")
        require(reviews, "BUNDLE_REVIEW_REQUIRED")
        require(reviews == [f"review-{i:03d}.json" for i in range(len(reviews))], "BUNDLE_RECORD_INVALID")
        fd = readiness_directory(run)
        try:
            for name in reviews:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "BUNDLE_RECORD_INVALID")
                require(info.st_size <= 32768, "BUNDLE_RECORD_LIMIT")
        finally:
            os.close(fd)
        review_raw, review = record(run, reviews[-1], 32768)
        require(review.get("id") == run_id, "BUNDLE_RECORD_INVALID")
        require(review.get("verdict") == "accepted", "BUNDLE_REVIEW_REQUIRED")
        require(review.get("result_sha256") == sha(result_raw), "BUNDLE_ARTIFACT_CHANGED")

        events, limited = self.readiness_entries(run, lambda name: name.startswith("event-"), 256)
        require(not limited, "BUNDLE_RECORD_LIMIT")
        require(events == [f"event-{i:03d}.json" for i in range(len(events))], "BUNDLE_RECORD_INVALID")
        final, budget = [], 8 * 1048576
        for index, name in enumerate(events):
            require(budget > 1, "BUNDLE_RECORD_LIMIT")
            raw, event = record(run, name, min(262144, budget - 1))
            budget -= len(raw)
            require(type(event.get("index")) is int and event["index"] == index
                    and type(event.get("kind")) is str and type(event.get("value")) is dict, "BUNDLE_RECORD_INVALID")
            if event["kind"] == "independent_final_checks":
                final.append(raw)
        require(len(final) == 1, "BUNDLE_FINAL_REQUIRED")

        patch = readiness_read_file(run, "changes.diff", 1048576)
        expected_patch, totals = "", [0, 0, 0]
        for name, digest in sorted(task["files"].items()):
            before = readiness_read_file(run / "baseline", name)
            after = readiness_read_file(run / "work", name)
            original = readiness_read_file(project["source"], name)
            totals = [total + len(raw) for total, raw in zip(totals, [before, after, original])]
            require(max(totals) <= 131072, "BUNDLE_RECORD_LIMIT")
            row = result["files"][name]
            require(type(row) is dict and sha(before) == digest == row.get("before")
                    and sha(after) == row.get("after"), "BUNDLE_ARTIFACT_CHANGED")
            require(sha(original) == digest, "BUNDLE_SOURCE_CHANGED")
            if name not in task["editable"]:
                require(sha(after) == digest, "BUNDLE_ARTIFACT_CHANGED")
            expected_patch += review_diff(name, before, after)
        require(expected_patch.encode() == patch and sha(patch) == review.get("patch_sha256")
                == result.get("patch_sha256"), "BUNDLE_ARTIFACT_CHANGED")
        return build_bundle(task_raw, result_raw, review_raw, final[0], patch)

    def _guarded_bundle(self, run_id):
        try:
            return self._bundle_bytes(run_id)
        except Refused as exc:
            if str(exc).startswith("BUNDLE_"):
                raise
            raise Refused("BUNDLE_RECORD_LIMIT" if str(exc) in ["FILE_LIMIT", "JSON_LIMIT"]
                          else "BUNDLE_RECORD_INVALID") from None
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            raise Refused("BUNDLE_RECORD_INVALID") from None

    def bundle_preview(self, run_id):
        with self.lock:
            return verify_bundle(self._guarded_bundle(run_id))

    def bundle_export(self, run_id, expected_sha256):
        with self.lock:
            require(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
                    "BUNDLE_HASH_REQUIRED")
            raw = self._guarded_bundle(run_id)
            verify_bundle(raw, expected_sha256)
            return raw

    def stop(self, run_id):
        with self.lock:
            self.meta_path(run_id)
            entry = self.children.get(run_id)
            require(
                entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_TASK"
            )
            child = entry[0]
            meta = self.metadata(run_id)
            meta["state"] = "STOP_REQUESTED"
            replace_json(self.meta_path(run_id), meta)
            child.terminate()

            def finish_stop():
                try:
                    child.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                with self.lock:
                    self.refresh(self.metadata(run_id))

            threading.Thread(target=finish_stop, daemon=True).start()
            return {"state": "STOP_REQUESTED"}

    def config_view(self):
        return {
            "projects": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "goal": p["definition"]["goal"],
                    "files": sorted(p["definition"]["files"]),
                    "editable": p["definition"]["editable"],
                    "checks": sorted(p["definition"]["checks"]),
                    "task_sha256": sha(p["task_raw"]),
                    "scripted_available": p["definition"] == json_file(HERE / "task.example.json"),
                }
                for p in self.projects.values()
            ],
            "models": self.models,
            "java_available": self.jdk_home is not None,
            "admission_block": self.admission(),
        }

    def close(self):
        self.recheck_draft = None
        self.snapshot_export_draft = None
        self.snapshot_workspace_draft = None
        for identifier in list(self.snapshot_workspace_children):
            try:
                self.snapshot_workspace_stop(identifier)
            except Refused:
                pass
        for identifier in list(self.snapshot_workspace_children):
            self.snapshot_workspace_view(identifier)
        for attempt_id in list(self.recheck_children):
            try:
                self.recheck_stop(attempt_id)
            except Refused:
                pass
        for attempt_id in list(self.recheck_children):
            self.recheck_view(attempt_id)
        self.bundle_workspace_draft = None
        for workspace_id in list(self.bundle_workspace_children):
            try:
                self.bundle_workspace_stop(workspace_id)
            except Refused:
                pass
        for workspace_id in list(self.bundle_workspace_children):
            self.bundle_workspace_view(workspace_id)
        for run_id in list(self.workspace_children):
            try:
                self.stop_workspace(run_id)
            except Refused:
                pass
        for run_id in list(self.workspace_children):
            self.workspace_receipt(run_id)
        for run_id in list(self.children):
            try:
                self.stop(run_id)
            except Refused:
                pass
        for child, log in list(self.children.values()):
            try:
                child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            log.close()
        os.close(self.server_lock)


def make_handler(manager, token, origin):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

        def send(
            self, code, raw, kind="application/json; charset=utf-8", attachment=None
        ):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'",
            )
            if attachment:
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{attachment}"'
                )
            self.end_headers()
            self.wfile.write(raw)

        def guard(self, api=False):
            require(
                self.headers.get("Host") == origin.split("://", 1)[1], "HOST_REFUSED"
            )
            require(
                self.headers.get("Sec-Fetch-Site", "none") in ["none", "same-origin"],
                "CROSS_SITE_REFUSED",
            )
            if api:
                supplied = self.headers.get("X-Workbench-Token", "")
                require(hmac.compare_digest(supplied, token), "SESSION_REQUIRED")

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                self.guard(path.startswith("/api/"))
                if path == "/":
                    raw = (
                        (HERE / "static/index.html")
                        .read_bytes()
                        .replace(b"__SESSION_TOKEN__", token.encode())
                    )
                    self.send(200, raw, "text/html; charset=utf-8")
                elif path in ["/app.js", "/style.css"]:
                    self.send(
                        200,
                        (HERE / "static" / path[1:]).read_bytes(),
                        "text/javascript; charset=utf-8"
                        if path.endswith(".js")
                        else "text/css; charset=utf-8",
                    )
                elif path == "/api/config":
                    self.send(200, canonical(manager.config_view()))
                elif path == "/api/history":
                    self.send(200, canonical(manager.history()))
                elif path == "/api/comparison-history":
                    self.send(200, canonical(manager.comparison_history()))
                elif path.startswith("/api/project-readiness/"):
                    self.send(200, canonical(manager.project_readiness(path.removeprefix("/api/project-readiness/"))))
                elif path.startswith("/api/compare/"):
                    pair = path.removeprefix("/api/compare/").split("/")
                    require(len(pair) == 2, "COMPARE_IDS")
                    self.send(200, canonical(manager.compare(*pair)))
                elif path.startswith("/api/project-revisions/"):
                    self.send(200, canonical(manager.project_revisions(path.removeprefix("/api/project-revisions/"))))
                elif path.startswith("/api/run/"):
                    self.send(
                        200, canonical(manager.view(path.removeprefix("/api/run/")))
                    )
                elif path.startswith("/api/export/"):
                    run_id = path.removeprefix("/api/export/")
                    raw = manager.export(run_id)
                    self.send(
                        200,
                        raw,
                        "text/plain; charset=utf-8",
                        f"outlands-patch-{run_id}.diff",
                    )
                elif path.startswith("/api/bundle-preview/"):
                    run_id = path.removeprefix("/api/bundle-preview/")
                    self.send(200, canonical(manager.bundle_preview(run_id)))
                elif path == "/api/bundle-workspaces":
                    self.send(200, canonical(manager.bundle_workspaces()))
                elif path.startswith("/api/bundle-workspace/"):
                    self.send(200, canonical(manager.bundle_workspace_view(path.removeprefix("/api/bundle-workspace/"))))
                elif path.startswith("/api/workspace-rechecks/"):
                    self.send(200, canonical(manager.rechecks(path.removeprefix("/api/workspace-rechecks/"))))
                elif path.startswith("/api/workspace-recheck/"):
                    self.send(200, canonical(manager.recheck_view(path.removeprefix("/api/workspace-recheck/"))))
                elif path.startswith("/api/snapshot-export-history/"):
                    self.send(200, canonical(manager.snapshot_export_history(path.removeprefix("/api/snapshot-export-history/"))))
                elif path == "/api/snapshot-workspaces":
                    self.send(200, canonical(manager.snapshot_workspaces()))
                elif path.startswith("/api/snapshot-workspace/"):
                    self.send(200, canonical(manager.snapshot_workspace_view(path.removeprefix("/api/snapshot-workspace/"))))
                else:
                    self.send(404, canonical({"error": "NOT_FOUND"}))
            except (Refused, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                self.send(
                    403
                    if isinstance(exc, Refused)
                    and str(exc)
                    in ["HOST_REFUSED", "CROSS_SITE_REFUSED", "SESSION_REQUIRED"]
                    else 409,
                    canonical(
                        {
                            "error": str(exc)
                            if isinstance(exc, Refused)
                            else "REQUEST_REFUSED"
                        }
                    ),
                )

        def do_POST(self):
            try:
                self.guard(True)
                require(self.headers.get("Origin") == origin, "ORIGIN_REFUSED")
                path = urlsplit(self.path).path
                if path.startswith("/api/snapshot-workspace-preview/"):
                    require(self.headers.get("Transfer-Encoding") is None, "SNAPSHOT_WORKSPACE_INPUT")
                    types = self.headers.get_all("Content-Type", [])
                    require(len(types) == 1 and types[0].split(";", 1)[0].strip().lower() == "application/zip",
                            "SNAPSHOT_WORKSPACE_INPUT")
                    lengths = self.headers.get_all("Content-Length", [])
                    require(len(lengths) == 1 and re.fullmatch(r"[0-9]{1,10}", lengths[0]) is not None,
                            "SNAPSHOT_WORKSPACE_INPUT")
                    length = int(lengths[0])
                    require(0 < length <= MAX_ARCHIVE, "SNAPSHOT_WORKSPACE_INPUT_LIMIT")
                    hashes = self.headers.get_all("X-Snapshot-SHA256", [])
                    require(len(hashes) <= 1 and (not hashes or re.fullmatch(r"[0-9a-f]{64}", hashes[0]) is not None),
                            "SNAPSHOT_WORKSPACE_INPUT")
                    raw = self.rfile.read(length)
                    require(len(raw) == length, "SNAPSHOT_WORKSPACE_INPUT")
                    result = manager.snapshot_workspace_preview(path.removeprefix("/api/snapshot-workspace-preview/"),
                                                                raw, hashes[0] if hashes else None)
                    self.send(200, canonical(result))
                    return
                if path.startswith("/api/snapshot-project-check/"):
                    require(self.headers.get("Transfer-Encoding") is None, "SNAPSHOT_PROJECT_INPUT")
                    types = self.headers.get_all("Content-Type", [])
                    require(len(types) == 1 and types[0].split(";", 1)[0].strip().lower() == "application/zip",
                            "SNAPSHOT_PROJECT_INPUT")
                    lengths = self.headers.get_all("Content-Length", [])
                    require(len(lengths) == 1 and re.fullmatch(r"[0-9]{1,10}", lengths[0]) is not None,
                            "SNAPSHOT_PROJECT_INPUT")
                    length = int(lengths[0])
                    require(length > 0, "SNAPSHOT_PROJECT_INPUT")
                    require(length <= MAX_ARCHIVE, "SNAPSHOT_PROJECT_LIMIT")
                    hashes = self.headers.get_all("X-Snapshot-SHA256", [])
                    require(len(hashes) <= 1 and (not hashes or re.fullmatch(r"[0-9a-f]{64}", hashes[0]) is not None),
                            "SNAPSHOT_PROJECT_INPUT")
                    raw = self.rfile.read(length)
                    require(len(raw) == length, "SNAPSHOT_PROJECT_INPUT")
                    result = manager.snapshot_project_check(path.removeprefix("/api/snapshot-project-check/"),
                                                            raw, hashes[0] if hashes else None)
                    self.send(200, canonical(result))
                    return
                if path.startswith("/api/bundle-project-check/") or path.startswith("/api/bundle-workspace-preview/"):
                    require(self.headers.get("Transfer-Encoding") is None, "PROJECT_CHECK_INPUT")
                    require(self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                            == "application/zip", "PROJECT_CHECK_INPUT")
                    lengths = self.headers.get_all("Content-Length", [])
                    require(len(lengths) == 1 and re.fullmatch(r"[0-9]{1,10}", lengths[0]) is not None,
                            "PROJECT_CHECK_INPUT")
                    length = int(lengths[0])
                    require(length > 0, "PROJECT_CHECK_INPUT")
                    require(length <= MAX_ARCHIVE, "PROJECT_CHECK_LIMIT")
                    hashes = self.headers.get_all("X-Bundle-SHA256", [])
                    require(len(hashes) <= 1 and (not hashes or re.fullmatch(r"[0-9a-f]{64}", hashes[0]) is not None),
                            "PROJECT_CHECK_INPUT")
                    raw = self.rfile.read(length)
                    require(len(raw) == length, "PROJECT_CHECK_INPUT")
                    if path.startswith("/api/bundle-project-check/"):
                        result = manager.bundle_project_check(path.removeprefix("/api/bundle-project-check/"),
                                                              raw, hashes[0] if hashes else None)
                    else:
                        result = manager.bundle_workspace_preview(path.removeprefix("/api/bundle-workspace-preview/"),
                                                                  raw, hashes[0] if hashes else None)
                    self.send(200, canonical(result))
                    return
                if path in {"/api/snapshot-workspace-create", "/api/snapshot-workspace-stop"}:
                    types = self.headers.get_all("Content-Type", [])
                    require(len(types) == 1 and types[0].split(";", 1)[0].strip().lower() == "application/json",
                            "SNAPSHOT_WORKSPACE_INPUT")
                require(
                    self.headers.get("Content-Type", "").split(";", 1)[0]
                    == "application/json",
                    "JSON_REQUIRED",
                )
                if path in {"/api/bundle-workspace-create", "/api/bundle-workspace-stop", "/api/workspace-recheck-preview",
                            "/api/workspace-recheck-start", "/api/workspace-recheck-stop", "/api/snapshot-export-preview",
                            "/api/snapshot-export-accept", "/api/snapshot-export-download",
                            "/api/snapshot-workspace-create", "/api/snapshot-workspace-stop"}:
                    lengths = self.headers.get_all("Content-Length", [])
                    require(self.headers.get("Transfer-Encoding") is None and len(lengths) == 1
                            and re.fullmatch(r"[0-9]{1,10}", lengths[0]) is not None,
                            "SNAPSHOT_WORKSPACE_INPUT" if path.startswith("/api/snapshot-workspace-") else "BUNDLE_WORKSPACE_INPUT")
                length = int(self.headers.get("Content-Length", "0"))
                require(0 < length <= 32768, "REQUEST_LIMIT")
                raw = self.rfile.read(length)
                if path in {"/api/bundle-workspace-create", "/api/bundle-workspace-stop", "/api/workspace-recheck-preview",
                            "/api/workspace-recheck-start", "/api/workspace-recheck-stop", "/api/snapshot-export-preview",
                            "/api/snapshot-export-accept", "/api/snapshot-export-download",
                            "/api/snapshot-workspace-create", "/api/snapshot-workspace-stop"}:
                    require(len(raw) == length, "SNAPSHOT_WORKSPACE_INPUT" if path.startswith("/api/snapshot-workspace-")
                            else "BUNDLE_WORKSPACE_INPUT")
                request = parse(raw)
                if path == "/api/start":
                    result = manager.start(request)
                elif path == "/api/project-preview":
                    result = manager.project_preview(request)
                elif path == "/api/project-save":
                    result = manager.project_save(request)
                elif path == "/api/project-refresh-preview":
                    result = manager.project_refresh_preview(request)
                elif path == "/api/project-refresh-save":
                    result = manager.project_refresh_save(request)
                elif path == "/api/workspace":
                    result = manager.create_workspace(request)
                elif path == "/api/workspace-stop":
                    require(isinstance(request, dict) and set(request) == {"id"}, "STOP_FIELDS")
                    result = manager.stop_workspace(request["id"])
                elif path == "/api/bundle-workspace-create":
                    result = manager.bundle_workspace_create(request)
                elif path == "/api/bundle-workspace-stop":
                    require(type(request) is dict and set(request) == {"id"}, "STOP_FIELDS")
                    result = manager.bundle_workspace_stop(request["id"])
                elif path == "/api/workspace-recheck-preview":
                    result = manager.recheck_preview(request)
                elif path == "/api/workspace-recheck-start":
                    result = manager.recheck_start(request)
                elif path == "/api/workspace-recheck-stop":
                    require(type(request) is dict and set(request) == {"id"}, "RECHECK_FIELDS")
                    result = manager.recheck_stop(request["id"])
                elif path == "/api/snapshot-export-preview":
                    result = manager.snapshot_export_preview(request)
                elif path == "/api/snapshot-export-accept":
                    result = manager.snapshot_export_accept(request)
                elif path == "/api/snapshot-export-download":
                    raw = manager.snapshot_export_download(request)
                    self.send(200, raw, "application/zip", "outlands-reviewed-snapshot.zip")
                    return
                elif path == "/api/snapshot-workspace-create":
                    result = manager.snapshot_workspace_create(request)
                elif path == "/api/snapshot-workspace-stop":
                    require(type(request) is dict and set(request) == {"id"}, "SNAPSHOT_WORKSPACE_FIELDS")
                    result = manager.snapshot_workspace_stop(request["id"])
                elif path == "/api/stop":
                    require(
                        isinstance(request, dict) and set(request) == {"id"},
                        "STOP_FIELDS",
                    )
                    result = manager.stop(request["id"])
                elif path == "/api/review":
                    result = manager.review(request)
                elif path == "/api/bundle-export":
                    require(type(request) is dict and set(request) == {"id", "bundle_sha256"}, "BUNDLE_RECORD_INVALID")
                    raw = manager.bundle_export(request["id"], request["bundle_sha256"])
                    self.send(200, raw, "application/zip", f"outlands-reviewed-bundle-{request['id']}.zip")
                    return
                else:
                    raise Refused("NOT_FOUND")
                self.send(200, canonical(result))
            except (Refused, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                self.send(
                    409,
                    canonical(
                        {
                            "error": str(exc)
                            if isinstance(exc, Refused)
                            else "REQUEST_REFUSED"
                        }
                    ),
                )

    return Handler


def init_demo(workspace, model):
    require(
        workspace.is_absolute() and not workspace.is_symlink(),
        "ABSOLUTE_WORKSPACE_REQUIRED",
    )
    workspace = workspace.resolve()
    require(workspace != HERE and HERE not in workspace.parents, "DEMO_OUTSIDE_SOURCE")
    workspace.mkdir(mode=0o700, exist_ok=False)
    project = workspace / "project"
    project.mkdir(mode=0o700)
    for name in ["calculator.py", "test_calculator.py"]:
        write_new(project / name, (HERE / name).read_bytes())
    write_new(workspace / "task.json", (HERE / "task.example.json").read_bytes())
    config = {
        "format": "outlands-workbench-config-v1",
        "projects": [
            {
                "id": "arithmetic",
                "name": "Arithmetic demo",
                "source": str(project),
                "task": str(workspace / "task.json"),
            }
        ],
        "models": [model] if model else [],
    }
    write_new(workspace / "config.json", canonical(config))
    return {
        "config": str(workspace / "config.json"),
        "data_dir": str(workspace / "data"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("init-demo")
    demo.add_argument("--workspace", type=Path, required=True)
    demo.add_argument("--model")
    serve = sub.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--data-dir", type=Path, required=True)
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--jdk-home", type=Path)
    args = parser.parse_args()
    if args.command == "init-demo":
        print(json.dumps(init_demo(args.workspace, args.model)))
        return
    require(0 <= args.port <= 65535, "PORT_RANGE")
    manager = Manager(args.config, args.data_dir, args.jdk_home)
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler)
    server.daemon_threads = True
    origin = "http://127.0.0.1:" + str(server.server_address[1])
    server.RequestHandlerClass = make_handler(manager, token, origin)
    replace_json(manager.data / "server-info.json", {"url": origin, "pid": os.getpid()})
    print("OUTLANDS Agent Workbench: " + origin, flush=True)

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "REFUSED",
                    "reason": str(error)
                    if isinstance(error, Refused)
                    else "STARTUP_FAILED",
                }
            )
        )
        raise SystemExit(2) from None
