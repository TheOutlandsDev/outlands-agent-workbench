"""Owned, once-only offline workflow acceptance using the unchanged demo engine.

This QA harness is deliberately separate from production admission. It permits
one exact Python ScriptedDemo attempt, real normal history/review/export, and
separate explicit Java checks. Its private fixtures must never be published.
"""

import argparse
import copy
import http.client
import io
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
from contextlib import ExitStack, contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import agent
from agent import Refused, canonical, parse, sha, validate_task, write_new
from git_workspace import fixed_checks
from java_check import validate_jdk
from workbench import Manager, init_demo, make_handler, readiness_directory


HERE = Path(__file__).resolve().parent
REAL_POPEN = subprocess.Popen
FORMAT = "outlands-offline-workflow-v1"
ID = re.compile(r"[0-9a-f]{16}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
DATA_DIRS = {"jobs", "tasks", "runs", "state", "projects", "workspaces", "revisions", "bundle-workspaces",
             "workspace-rechecks", "snapshot-exports", "snapshot-workspaces", "snapshot-workspace-rechecks",
             "snapshot-reexports", "snapshot-workspace-edits", "task-presets"}
COUNTER_KEYS = ("start_requests", "start_attempts", "worker_launches", "history_requests", "view_requests",
                "metadata_search_requests", "metadata_open_requests", "saved_review_requests",
                "saved_review_history_requests", "saved_review_history_entry_requests", "review_requests",
                "export_requests", "parent_provider_attempts", "parent_outbound_attempts", "denied_requests")
PROTECTED = ("workspace/config.json", "workspace/task.json", "workspace/project/calculator.py",
             "workspace/project/test_calculator.py")
PLAN = ["Read the fixture", "Correct addition", "Run the fixed tests"]


def require(condition, suffix):
    if not condition:
        raise Refused("OFFLINE_WORKFLOW_" + suffix)


def new_counters():
    return {key: 0 for key in COUNTER_KEYS}


def _root(value):
    require(isinstance(value, Path) and value.is_absolute() and ".." not in value.parts, "ROOT")
    require(value != HERE and HERE not in value.parents and value not in HERE.parents, "ROOT")
    return value


def _directory(path):
    fd = None
    try:
        fd = readiness_directory(path)
        info = os.fstat(fd)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "STORE_UNSAFE")
        result, fd = fd, None
        return result
    except (OSError, ValueError):
        raise Refused("OFFLINE_WORKFLOW_STORE_UNSAFE") from None
    finally:
        if fd is not None:os.close(fd)


def _read(root, relative, limit=262144):
    parts = relative.split("/")
    require(parts and all(part not in {"", ".", ".."} for part in parts), "PATH")
    fd = _directory(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
            info = os.fstat(fd)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "STORE_UNSAFE")
        child = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                    and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, "STORE_UNSAFE")
            raw = stream.read(limit + 1)
            require(len(raw) <= limit, "LIMIT")
            identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
                                     info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            require(identity(before) == identity(os.fstat(stream.fileno()))
                    == identity(os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)), "CHANGED")
            return raw
    except (OSError, ValueError):
        raise Refused("OFFLINE_WORKFLOW_STORE_UNSAFE") from None
    finally:
        os.close(fd)


def _json(root, relative, limit=262144):
    try:
        value = parse(_read(root, relative, limit))
        require(type(value) is dict, "RECORD")
        return value
    except Refused as error:
        if str(error).startswith("OFFLINE_WORKFLOW_"):
            raise
        raise Refused("OFFLINE_WORKFLOW_RECORD") from None


def _new(path, value):
    try:
        write_new(path, canonical(value))
    except FileExistsError:
        raise Refused("OFFLINE_WORKFLOW_ALREADY_ATTEMPTED") from None


def _publish(path, value):
    """Publish one fresh receipt only after its bytes are durable; retain failures."""
    stage=path.with_name(path.name+".next")
    _new(stage,value)
    try:
        os.link(stage,path,follow_symlinks=False)
        os.unlink(stage)
    except FileExistsError:
        raise Refused("OFFLINE_WORKFLOW_ALREADY_ATTEMPTED") from None


def _names(path, limit=256):
    fd = _directory(path)
    try:
        result = []
        with os.scandir(fd) as entries:
            for entry in entries:
                require(len(result) < limit, "LIMIT")
                result.append(entry.name)
        return sorted(result)
    finally:
        os.close(fd)


def initialize(work_dir):
    root = _root(work_dir)
    require(not root.exists() and not root.is_symlink(), "ROOT_EXISTS")
    parent = readiness_directory(root.parent)
    os.close(parent)
    root.mkdir(mode=0o700, exist_ok=False)
    (root / "receipts").mkdir(mode=0o700)
    init_demo(root / "workspace", None)
    marker = {"version": 1, "format": FORMAT, "fixture_id": secrets.token_hex(16), "work_dir": str(root),
              "files": {name: sha(_read(root, name)) for name in PROTECTED}}
    _new(root / "fixture.json", marker)
    return validate_fixture(root)


def _runtime(root):
    data = root / "workspace/data"
    if not data.exists():
        return None
    require(set(_names(data)) == DATA_DIRS | {"server.lock"}, "FOREIGN_STORE")
    for name in DATA_DIRS:
        if (data / name).exists():
            os.close(_directory(data / name))
            if name not in {"jobs", "tasks", "runs", "state"}:
                require(_names(data / name) == [], "FOREIGN_STORE")
    launch = _json(root, "receipts/launch.json") if (root / "receipts/launch.json").exists() else None
    identifier = launch.get("id") if launch else None
    require(identifier is None or type(identifier) is str and ID.fullmatch(identifier) is not None, "RECORD")
    expected = {"jobs": {identifier + ".json", identifier + ".log"} if identifier else set(),
                "tasks": {identifier + ".json"} if identifier else set(),
                "runs": {identifier} if identifier else set(), "state": {"worker.lock", "hold.json"}}
    for name, allowed in expected.items():
        if (data / name).exists():
            require(set(_names(data / name)) <= allowed, "FOREIGN_STORE")
            if name!="runs":
                for leaf in _names(data/name):_read(data,name+"/"+leaf,262144)
    if (data/"server.lock").exists():require(_read(data,"server.lock")==b"","STORE_UNSAFE")
    if identifier and (data/"runs"/identifier).exists():
        for name in _names(data/"runs"/identifier):
            if name in {"baseline","work"}:
                require(set(_names(data/"runs"/identifier/name))=={"calculator.py","test_calculator.py"},"FOREIGN_STORE")
                for leaf in ["calculator.py","test_calculator.py"]:_read(data,"runs/"+identifier+"/"+name+"/"+leaf,32768)
            else:
                require(name in {"task.json","result.json","changes.diff"}
                        or re.fullmatch(r"(?:event-[0-9]{3,6}|review-[0-9]{3})[.]json",name) is not None,"FOREIGN_STORE")
                _read(data,"runs/"+identifier+"/"+name,262144)
    return identifier


def validate_fixture(work_dir):
    root = _root(work_dir)
    os.close(_directory(root)); os.close(_directory(root / "receipts"))
    require(set(_names(root)) <= {"fixture.json", "workspace", "receipts", "java"}, "FOREIGN_STORE")
    for name in _names(root/"receipts"):
        require(name in {"start-claim.json","launch.json","parent-started.json","parent-started.json.next",
                         "worker-start.json","worker-exit.json","terminal.json"}
                or re.fullmatch(r"(?:session|shutdown)-[0-9a-f]{16}[.]json",name) is not None,"FOREIGN_STORE")
        _read(root,"receipts/"+name)
    marker = _json(root, "fixture.json", 32768)
    require(set(marker) == {"version", "format", "fixture_id", "work_dir", "files"}
            and type(marker["version"]) is int and marker["version"] == 1 and marker["format"] == FORMAT
            and type(marker["fixture_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", marker["fixture_id"]) is not None
            and marker["work_dir"] == str(root) and type(marker["files"]) is dict
            and set(marker["files"]) == set(PROTECTED), "MARKER")
    for name, digest in marker["files"].items():
        require(type(digest) is str and HASH.fullmatch(digest) is not None and sha(_read(root, name)) == digest, "INPUT_CHANGED")
    require(set(_names(root / "workspace")) <= {"project", "config.json", "task.json", "data"}
            and set(_names(root / "workspace/project")) == {"calculator.py", "test_calculator.py"}, "FOREIGN_STORE")
    config = _json(root, "workspace/config.json")
    require(config == {"format": "outlands-workbench-config-v1", "models": [], "projects": [{
        "id": "arithmetic", "name": "Arithmetic demo", "source": str(root / "workspace/project"),
        "task": str(root / "workspace/task.json")}]}, "CONFIG")
    task = _json(root, "workspace/task.json")
    require(task == json.loads((HERE / "task.example.json").read_bytes()), "SCRIPTED_ONLY")
    for name, digest in task["files"].items():
        require(sha(_read(root, "workspace/project/" + name)) == digest, "INPUT_CHANGED")
    _runtime(root)
    if (root/"receipts/launch.json").exists():_launch_record(root,marker)
    if (root/"java").exists() or (root/"java").is_symlink():
        require(set(_names(root/"java"))<={"claim.json","task.json","result.json","source","check"},"FOREIGN_STORE")
        for name in _names(root/"java"):
            if name in {"source","check"}:
                require(set(_names(root/"java"/name))<={"Sum.java","SumTest.java"},"FOREIGN_STORE")
                for leaf in _names(root/"java"/name):_read(root,"java/"+name+"/"+leaf,32768)
            else:_read(root,"java/"+name)
        claim=_json(root,"java/claim.json")
        require(set(claim)=={"version","fixture_id","attempt"} and type(claim["version"]) is int and claim["version"]==1
                and claim["fixture_id"]==marker["fixture_id"] and type(claim["attempt"]) is int and claim["attempt"]==1,"CLAIM")
    return marker


def expected_command(root, identifier):
    require(type(identifier) is str and ID.fullmatch(identifier) is not None, "ARGV")
    return [sys.executable, "-B", str(HERE / "agent.py"), "--task", str(root / "workspace/data/tasks" / (identifier + ".json")),
            "--source", str(root / "workspace/project"), "--run-dir", str(root / "workspace/data/runs" / identifier),
            "--state-dir", str(root / "workspace/data/state"), "--backend", "scripted-demo"]


def _launch_record(root,marker):
    launch=_json(root,"receipts/launch.json")
    require(set(launch)=={"version","id","fixture_id","argv","task_sha256"}
            and type(launch["version"]) is int and launch["version"]==1 and launch["fixture_id"]==marker["fixture_id"]
            and type(launch["id"]) is str and ID.fullmatch(launch["id"]) is not None
            and type(launch["argv"]) is list and launch["argv"]==expected_command(root,launch["id"])
            and launch["task_sha256"]==sha(canonical(_json(root,"workspace/task.json"))),"CLAIM")
    return launch


def _inventory(root, run_id):
    base = root / "workspace/data"
    paths = ["jobs/" + run_id + ".json", "jobs/"+run_id+".log", "tasks/" + run_id + ".json",
             "server.lock","state/worker.lock"]
    run = base / "runs" / run_id
    for name in _names(run):
        if name in {"baseline", "work"}:
            require(set(_names(run / name)) == {"calculator.py", "test_calculator.py"}, "FOREIGN_STORE")
            paths += ["runs/" + run_id + "/" + name + "/" + leaf for leaf in _names(run / name)]
        else:
            require(name in {"task.json", "result.json", "changes.diff"}
                    or re.fullmatch(r"event-[0-9]{3,6}[.]json", name) is not None
                    or re.fullmatch(r"review-[0-9]{3}[.]json", name) is not None, "FOREIGN_STORE")
            if not name.startswith("review-"):
                paths.append("runs/" + run_id + "/" + name)
    total, hashes = 0, {}
    for name in sorted(paths):
        raw = _read(base, name, 262144); total += len(raw)
        require(total <= 4194304, "LIMIT")
        hashes["workspace/data/"+name] = sha(raw)
    for name in ["start-claim.json","launch.json","parent-started.json","worker-start.json","worker-exit.json"]:
        hashes["receipts/"+name]=sha(_read(root,"receipts/"+name))
    return hashes


def _metadata_matches(root, marker, identifier, meta):
    task=_json(root,"workspace/task.json")
    require(meta.get("id")==identifier and meta.get("project")=="arithmetic"
            and meta.get("project_name")=="Arithmetic demo" and meta.get("source")==str(root/"workspace/project")
            and meta.get("goal")==task["goal"] and meta.get("backend")==meta.get("model")=="scripted-demo"
            and meta.get("task_sha256")==sha(canonical(task))
            and meta.get("project_task_sha256")==marker["files"]["workspace/task.json"],"METADATA_CHANGED")


def _worker_receipts(root,marker,identifier):
    claim=_json(root,"receipts/start-claim.json")
    require(set(claim)=={"version","fixture_id","attempt"} and type(claim["version"]) is int and claim["version"]==1
            and claim["fixture_id"]==marker["fixture_id"] and type(claim["attempt"]) is int and claim["attempt"]==1,"CLAIM")
    started=_json(root,"receipts/worker-start.json");finished=_json(root,"receipts/worker-exit.json")
    parent=_json(root,"receipts/parent-started.json")
    for value in [started,parent]:
        require(set(value)=={"version","id","fixture_id","pid"} and type(value["version"]) is int and value["version"]==1
                and value["id"]==identifier and value["fixture_id"]==marker["fixture_id"]
                and type(value["pid"]) is int and 0<value["pid"]<=2147483647,"WORKER")
    require(started["pid"]==parent["pid"],"WORKER")
    require(set(finished)=={"version","id","fixture_id","pid","exit_code","provider_attempts","network_attempts","python_level_guards","os_wide_packet_audit"}
            and type(finished["version"]) is int and finished["version"]==1 and finished["id"]==identifier
            and finished["fixture_id"]==marker["fixture_id"] and type(finished["pid"]) is int and finished["pid"]==started["pid"]
            and all(type(finished[key]) is int and finished[key]==0 for key in ["exit_code","provider_attempts","network_attempts"])
            and finished["python_level_guards"] is True and finished["os_wide_packet_audit"] is False,"WORKER")
    return finished


def _python_evidence_data(root, patch_raw, require_accepted):
    marker=validate_fixture(root)
    launch = _launch_record(root,marker); identifier = launch.get("id")
    require(type(identifier) is str and ID.fullmatch(identifier) is not None, "RECORD")
    base = root / "workspace/data"; prefix = "runs/" + identifier + "/"
    meta = _json(base, "jobs/" + identifier + ".json")
    _metadata_matches(root,marker,identifier,meta)
    require(meta.get("state") == "REVIEW_READY" and meta.get("backend") == "scripted-demo"
            and meta.get("model") == "scripted-demo" and meta.get("project") == "arithmetic", "NOT_SUCCESSFUL")
    result = _json(base, prefix + "result.json")
    require(result.get("status") == "REVIEW_READY" and result.get("ai_inference") is False
            and result.get("source_adopted") is False and result.get("turns") == 6, "NOT_SUCCESSFUL")
    require(_names(base/"state")==["worker.lock"] and _read(base,"state/worker.lock")==b"","UNSETTLED")
    require(_json(base,"tasks/"+identifier+".json")==_json(root,"workspace/task.json")
            and _json(base,prefix+"task.json")==_json(root,"workspace/task.json"),"INPUT_CHANGED")
    original = _read(root, "workspace/project/calculator.py")
    expected = original.replace(b"return a - b", b"return a + b")
    require(expected != original and _read(base, prefix + "work/calculator.py") == expected, "CANDIDATE")
    for name in ["calculator.py", "test_calculator.py"]:
        require(_read(base, prefix + "baseline/" + name) == _read(root, "workspace/project/" + name), "BASELINE")
    require(_read(base, prefix + "work/test_calculator.py") == _read(root, "workspace/project/test_calculator.py"), "PROTECTED_CHANGED")
    events = [_json(base, prefix + name) for name in _names(base / prefix)
              if re.fullmatch(r"event-[0-9]{3,6}[.]json", name) is not None]
    require(1 <= len(events) <= 128 and [row.get("index") for row in events] == list(range(len(events))), "EVENTS")
    tools = [row["value"] for row in events if row.get("kind") == "tool_result"]
    require([row.get("name") for row in tools]==["set_plan","read_file","read_file","replace_text","run_check"],"TOOLS")
    require(tools[0].get("arguments")=={"steps":PLAN} and tools[0].get("result")=={"recorded":True,"steps":PLAN},"PLAN")
    require(tools[1].get("arguments")=={"path":"calculator.py"} and tools[2].get("arguments")=={"path":"test_calculator.py"}
            and tools[3].get("arguments")=={"path":"calculator.py","expected_sha256":sha(original),"old_text":"return a - b","new_text":"return a + b"},"TOOLS")
    check_sets = {}
    for kind, expected_code in [("baseline_checks", 1), ("independent_final_checks", 0)]:
        found = [row["value"] for row in events if row.get("kind") == kind]
        require(len(found) == 1 and set(found[0]) == {"unit"}, "CHECKS")
        checked = found[0]["unit"]
        require(checked.get("exit_code") == expected_code and checked.get("tests_ran") == 4
                and all(checked.get(key) is False for key in ["timed_out", "output_limited", "infrastructure_error"]), "CHECKS")
        check_sets[kind] = checked["tests_ran"]
    checked=tools[4].get("result",{})
    require(tools[4].get("arguments")=={"check_id":"unit"} and checked.get("exit_code")==0 and checked.get("tests_ran")==4
            and all(checked.get(key) is False for key in ["timed_out","output_limited","infrastructure_error"]),"CHECKS")
    require(type(result.get("files")) is dict and set(result["files"])=={"calculator.py","test_calculator.py"}
            and all(result["files"][name]=={"before":sha(_read(root,"workspace/project/"+name)),
                     "after":sha(_read(base,prefix+"work/"+name))} for name in result["files"]),"CANDIDATE")
    patch_bytes = _read(base, prefix + "changes.diff", 65536)
    require(patch_bytes == agent.review_diff("calculator.py", original, expected).encode()
            and sha(patch_bytes) == result.get("patch_sha256"), "PATCH_CHANGED")
    if patch_raw is not None:
        require(type(patch_raw) is bytes and patch_raw == patch_bytes, "DOWNLOAD_CHANGED")
    _worker_receipts(root,marker,identifier)
    reviews = [name for name in _names(base / prefix) if re.fullmatch(r"review-[0-9]{3}[.]json", name) is not None]
    accepted = False
    if reviews:
        review = _json(base, prefix + reviews[-1])
        require(set(review)=={"id","result_sha256","patch_sha256","verdict","note","recorded","source_applied"}
                and review["id"]==identifier and type(review["recorded"]) is int and 0<=review["recorded"]<=9007199254740991
                and type(review["note"]) is str and len(review["note"])<=2000 and review["source_applied"] is False,"REVIEW_CHANGED")
        accepted = review.get("verdict") == "accepted" and review.get("result_sha256") == sha(canonical(result)) and review.get("patch_sha256") == sha(patch_bytes)
    require(not require_accepted or accepted, "REVIEW_REQUIRED")
    return {"version": 1, "status": "PASS", "id": identifier, "backend": "scripted-demo", "ai_inference": False,
            "turns": 6, "baseline_tests": 4, "agent_tests":4,"final_tests": 4, "accepted": accepted,
            "result_sha256": sha(canonical(result)), "patch_sha256": sha(patch_bytes),
            "download_verified": patch_raw is not None, "source_unchanged": True, "protected_unchanged": True,
            "worker_provider_attempts": 0, "worker_network_attempts": 0}


def _python_evidence(root, patch_raw, require_accepted):
    """Finite malformed-record boundary shared by report and live settlement."""
    try:
        return _python_evidence_data(root,patch_raw,require_accepted)
    except Refused as error:
        if str(error).startswith("OFFLINE_WORKFLOW_"):raise
        raise Refused("OFFLINE_WORKFLOW_RECORD") from None
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):
        raise Refused("OFFLINE_WORKFLOW_RECORD") from None


def python_report(work_dir, patch_raw=None, require_accepted=False):
    try:
        root = _root(work_dir)
        require(type(require_accepted) is bool, "INPUT")
        result = _python_evidence(root, patch_raw, require_accepted)
        terminal = _json(root, "receipts/terminal.json")
        require(set(terminal)=={"version","id","fixture_id","files"} and type(terminal["version"]) is int and terminal["version"]==1
                and terminal["fixture_id"]==validate_fixture(root)["fixture_id"] and terminal.get("id") == result["id"]
                and terminal.get("files") == _inventory(root, result["id"]), "TERMINAL_CHANGED")
        return result
    except Refused as error:
        if str(error).startswith("OFFLINE_WORKFLOW_"):raise
        raise Refused("OFFLINE_WORKFLOW_RECORD") from None
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):
        raise Refused("OFFLINE_WORKFLOW_RECORD") from None


class WorkflowManager(Manager):
    def __init__(self, work_dir):
        self.root = _root(work_dir); self.marker = validate_fixture(self.root); self.counters = new_counters()
        self._guard_lock = threading.RLock()
        self._closed=False;self.shutdown_report=None
        identifier = _runtime(self.root)
        if identifier and (self.root / "workspace/data/jobs" / (identifier + ".json")).exists():
            state = _json(self.root, "workspace/data/jobs/" + identifier + ".json").get("state")
            require(state in {"REVIEW_READY", "FAILED", "REFUSED", "UNCERTAIN", "INTERRUPTED"}, "UNSETTLED")
            if state == "REVIEW_READY": python_report(self.root)
        super().__init__(self.root / "workspace/config.json", self.root / "workspace/data")

    def _launch(self, command, **kwargs):
        require(type(command) is list and len(command) == 13 and all(type(item) is str for item in command), "ARGV")
        identifier = Path(command[4]).stem
        require(command == expected_command(self.root, identifier), "ARGV")
        require(set(kwargs) == {"stdin", "stdout", "stderr", "start_new_session", "env"}
                and kwargs["stdin"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.STDOUT
                and kwargs["start_new_session"] is True and type(kwargs["stdout"]) is io.BufferedWriter
                and kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}, "ARGV")
        claim = _json(self.root, "receipts/start-claim.json")
        require(claim.get("fixture_id") == self.marker["fixture_id"], "CLAIM")
        require(_json(self.root, "workspace/data/tasks/" + identifier + ".json") == _json(self.root, "workspace/task.json"), "SCRIPTED_ONLY")
        meta = _json(self.root, "workspace/data/jobs/" + identifier + ".json")
        _metadata_matches(self.root,self.marker,identifier,meta)
        info=os.fstat(kwargs["stdout"].fileno());named=os.stat(self.root/"workspace/data/jobs"/(identifier+".log"),follow_symlinks=False)
        require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600
                and (info.st_dev,info.st_ino)==(named.st_dev,named.st_ino),"ARGV")
        _new(self.root / "receipts/launch.json", {"version": 1, "id": identifier, "fixture_id": self.marker["fixture_id"],
                                                  "argv": command, "task_sha256": sha(canonical(_json(self.root, "workspace/task.json")))})
        redirected = [sys.executable, "-B", str(HERE / "offline_workflow_worker.py"), "--work-dir", str(self.root),
                      "--run-id", identifier, "--"] + command[3:]
        child = REAL_POPEN(redirected, **kwargs)
        self.counters["worker_launches"] += 1
        return child

    def start(self, request):
        with self.lock:
            self.counters["start_attempts"] += 1
            validate_fixture(self.root)
            _new(self.root / "receipts/start-claim.json", {"version": 1, "fixture_id": self.marker["fixture_id"], "attempt": 1})
            task = _json(self.root, "workspace/task.json")
            require(type(request) is dict and request == {"project": "arithmetic", "model": "scripted-demo", "goal": task["goal"]}, "SCRIPTED_ONLY")
            with patch("workbench.subprocess.Popen", self._launch):
                try:result=super().start(request)
                except Refused as error:
                    if str(error).startswith("OFFLINE_WORKFLOW_"):raise
                    raise Refused("OFFLINE_WORKFLOW_ENGINE_START_FAILED" if str(error)=="ENGINE_START_FAILED" else "OFFLINE_WORKFLOW_START_REFUSED") from None
            child=self.children[result["id"]][0]
            _publish(self.root/"receipts/parent-started.json",{"version":1,"id":result["id"],"fixture_id":self.marker["fixture_id"],"pid":child.pid})
            return result

    def refresh(self, meta):
        value = super().refresh(meta)
        if value.get("state") == "REVIEW_READY" and not (self.root / "receipts/terminal.json").exists():
            _python_evidence(self.root, None, False)
            _new(self.root / "receipts/terminal.json", {"version": 1, "id": value["id"],"fixture_id":self.marker["fixture_id"], "files": _inventory(self.root, value["id"])})
        return value

    def stop(self, run_id):
        launch = _json(self.root, "receipts/launch.json")
        require(run_id == launch.get("id"), "FOREIGN_STORE")
        return super().stop(run_id)

    def close(self):
        if self._closed:return
        owned=list(self.children)
        stopping=any(child.poll() is None for child,_ in self.children.values())
        state="NEEDS_INSPECTION"
        try:
            super().close()
            with self.lock:
                for identifier in owned:
                    if identifier in self.children:self.refresh(self.metadata(identifier))
                identifier=_runtime(self.root)
                state=_json(self.root,"workspace/data/jobs/"+identifier+".json").get("state") if identifier else None
        except (Refused,OSError,ValueError,TypeError,KeyError):pass
        finally:
            self.shutdown_report={"version":1,"owned_children":len(owned),"owned_stop_requested":stopping,
                                  "saved_state":state,"acceptance_verified_by_shutdown":False}
            self._closed=True


@contextmanager
def parent_guards(manager, origin):
    def provider(*args, **kwargs):
        manager.counters["parent_provider_attempts"] += 1
        raise Refused("OFFLINE_WORKFLOW_PROVIDER_REFUSED")
    original = http.client.HTTPConnection.connect
    allowed_port = urlsplit(origin).port
    def connect(connection):
        if connection.host not in {"127.0.0.1", "localhost"} or connection.port != allowed_port:
            manager.counters["parent_outbound_attempts"] += 1
            raise Refused("OFFLINE_WORKFLOW_NETWORK_REFUSED")
        return original(connection)
    with ExitStack() as stack:
        stack.enter_context(patch("agent.Ollama.request", provider)); stack.enter_context(patch("agent.Ollama.preflight", provider))
        stack.enter_context(patch("http.client.HTTPConnection.connect", connect))
        yield


def offline_handler(manager, token, origin, counters):
    require(isinstance(manager, WorkflowManager) and type(counters) is dict and set(counters) <= set(COUNTER_KEYS)
            and all(type(value) is int and value >= 0 for value in counters.values()), "COUNTERS")
    for key in COUNTER_KEYS:counters.setdefault(key, 0)
    manager.counters = counters
    base = make_handler(manager, token, origin)
    class Handler(base):
        def _allowed(self, post=False):
            path = urlsplit(self.path).path
            routes = {"/api/start": "start_requests", "/api/review": "review_requests", "/api/stop": None,
                      "/api/run-history-search": "metadata_search_requests", "/api/run-history-open": "metadata_open_requests",
                      "/api/run-history-review": "saved_review_requests",
                      "/api/saved-review-history": "saved_review_history_requests",
                      "/api/saved-review-history-entry": "saved_review_history_entry_requests"} if post else {
                      "/": None, "/app.js": None, "/style.css": None, "/api/config": None,
                      "/api/history": "history_requests", "/api/comparison-history": None}
            if not post:
                for prefix, counter in [("/api/run/", "view_requests"), ("/api/export/", "export_requests")]:
                    if path.startswith(prefix) and ID.fullmatch(path[len(prefix):]) is not None:routes[path] = counter
            if path not in routes:
                counters["denied_requests"] += 1; self.guard(True)
                self.send(409, canonical({"error": "OFFLINE_WORKFLOW_ROUTE"})); return False
            if routes[path]:counters[routes[path]] += 1
            if post:
                self.guard(True)
                require(self.headers.get("Origin") == origin, "ORIGIN_REFUSED")
                types,lengths=self.headers.get_all("Content-Type",[]),self.headers.get_all("Content-Length",[])
                require(self.headers.get("Transfer-Encoding") is None and len(types)==len(lengths)==1
                        and types[0].split(";",1)[0].strip().lower()=="application/json"
                        and re.fullmatch(r"[0-9]{1,10}",lengths[0]) is not None and 0<int(lengths[0])<=32768,"HTTP_INPUT")
                raw=self.rfile.read(int(lengths[0]));require(len(raw)==int(lengths[0]),"HTTP_INPUT")
                self._offline_body=raw
            return True
        def _request(self, post):
            with manager._guard_lock, parent_guards(manager,origin):
                try:
                    if self._allowed(post):
                        if not post:return super().do_GET()
                        original=self.rfile;self.rfile=io.BytesIO(self._offline_body)
                        try:return super().do_POST()
                        finally:self.rfile=original
                except Refused as error:self.send(403 if str(error) in {"HOST_REFUSED","CROSS_SITE_REFUSED","SESSION_REQUIRED"} else 409,canonical({"error":str(error)}))
        def do_GET(self):return self._request(False)
        def do_POST(self):return self._request(True)
    return Handler


def java_checks(work_dir, jdk_home):
    root = _root(work_dir); marker = validate_fixture(root)
    java = root / "java"
    require(not java.exists() and not java.is_symlink(), "ALREADY_ATTEMPTED")
    java.mkdir(mode=0o700); _new(java / "claim.json", {"version":1,"fixture_id":marker["fixture_id"],"attempt":1})
    try:home = validate_jdk(jdk_home)
    except (ValueError,OSError):raise Refused("OFFLINE_WORKFLOW_JDK") from None
    files={"Sum.java":b"public class Sum { public static int add(int a,int b) { return a+b; } }\n",
           "SumTest.java":b"public class SumTest { public static void main(String[] args) { if(Sum.add(2,3)!=5 || Sum.add(-2,3)!=1) throw new AssertionError(); } }\n"}
    task={"format":"outlands-coding-agent-v2","goal":"Check this invented Java arithmetic independently of any agent.",
          "files":{name:sha(raw) for name,raw in files.items()},"editable":["Sum.java"],
          "checks":{"unit":{"kind":"java-main","sources":list(files),"main_class":"SumTest"}},"max_turns":1,"request_seconds":10}
    validate_task(task)
    for folder in ["source","check"]:
        (java/folder).mkdir(mode=0o700)
        for name,raw in files.items():write_new(java/folder/name,raw)
    _new(java/"task.json",task)
    result=fixed_checks(java/"check",task,home)
    _new(java/"result.json",{"version":1,"checks":result,"java_agent_run":False,"model_inference":False})
    require(all(_read(java,"source/"+name)==raw and _read(java,"check/"+name)==raw for name,raw in files.items()),"INPUT_CHANGED")
    require(bool(result) and all(row.get("exit_code")==0 and row.get("tests_ran")==1
            and all(row.get(key) is False for key in ["timed_out","output_limited","infrastructure_error"]) for row in result.values()),"JAVA_CHECKS_FAILED")
    return {"version":1,"status":"PASS","java_agent_run":False,"model_inference":False,"protected_mains":1,
            "receipt_sha256":sha(_read(java,"result.json")),"sources_unchanged":True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    for name in ["init","serve","inspect","java-check"]:
        item=sub.add_parser(name);item.add_argument("--work-dir",type=Path,required=True)
        if name=="serve":item.add_argument("--port",type=int,default=0)
        if name=="inspect":item.add_argument("--download",type=Path);item.add_argument("--require-accepted",action="store_true")
        if name=="java-check":item.add_argument("--jdk-home",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=="init":value=initialize(args.work_dir)
    elif args.command=="java-check":value=java_checks(args.work_dir,args.jdk_home)
    elif args.command=="inspect":
        raw=None
        if args.download is not None:
            require(args.download.is_absolute(),"PATH");raw=_read(args.download.parent,args.download.name,65536)
        value=python_report(args.work_dir,raw,args.require_accepted)
        if (args.work_dir/"java/result.json").exists():value["java_receipt_sha256"]=sha(_read(args.work_dir,"java/result.json"))
    else:
        require(0<=args.port<=65535,"PORT");manager=WorkflowManager(args.work_dir)
        server=ThreadingHTTPServer(("127.0.0.1",args.port),offline_handler(manager,secrets.token_urlsafe(32),"http://127.0.0.1:0",manager.counters))
        origin="http://127.0.0.1:"+str(server.server_address[1]);server.RequestHandlerClass=offline_handler(manager,secrets.token_urlsafe(32),origin,manager.counters)
        session=secrets.token_hex(8);_new(args.work_dir/"receipts"/("session-"+session+".json"),{"version":1,"url":origin,"pid":os.getpid(),"token_logged":False})
        print(json.dumps({"url":origin,"pid":os.getpid(),"token_logged":False}),flush=True)
        def stop(*_args):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop)
        try:server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:pass
        finally:
            server.server_close();manager.close();_new(args.work_dir/"receipts"/("shutdown-"+session+".json"),{"version":1,"counters":manager.counters,"listener_closed":True,"owned_worker":manager.shutdown_report})
        return 0 if manager.shutdown_report["saved_state"] in {None,"REVIEW_READY"} else 2
    print(json.dumps(value,sort_keys=True));return 0


if __name__=="__main__":
    try:raise SystemExit(main())
    except (Refused,OSError,ValueError,KeyError,TypeError,AttributeError,RecursionError):
        print('{"status":"REFUSED","reason":"OFFLINE_WORKFLOW_REFUSED"}');raise SystemExit(2)
