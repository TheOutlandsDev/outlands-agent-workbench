"""Fixed QA-only native process failure/owned-stop exercises; no agent runs.

Original workflow validation, launch checks and Manager lifecycle remain in use.
The logical agent command is intercepted only after its exact validation, then
one fixed source-bound lifecycle worker is spawned. It writes no agent artifacts.
"""

import argparse
import hashlib
import http.client
import io
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import offline_workflow as base
from agent import Refused, canonical, parse, sha


HERE = Path(__file__).resolve().parent
REAL_POPEN = subprocess.Popen
FORMAT = "outlands-offline-lifecycle-v1"
SCENARIOS = {"fail", "stop"}
PORTS = {"fail": 36229, "stop": 36230}
HANDSHAKE_SECONDS = 5
ARMED_SECONDS = 30
LIFECYCLE_COUNTER_KEYS = ("native_launches", "explicit_stops", "containment_stops")
RECEIPTS = {"attempt.json", "actual-launch.json", "spawned.json", "worker-start.json", "armed.json",
            "worker-exit.json", "stop-intent.json", "stop-return.json", "containment-intent.json", "containment-return.json"}
SESSION = re.compile(r"(?:session|shutdown)-[0-9a-f]{16}[.]json\Z")
COMMON = {"version", "fixture_id", "id", "pid"}
NOTES = {"NOT_ATTEMPTED", "INCOMPLETE_EVIDENCE", "EVIDENCE_INVALID", "UNEXPECTED_AGENT_ARTIFACTS",
         "CONTAINMENT_STOP", "EXIT_NOT_EXPECTED"}


def require(condition, suffix):
    if not condition:
        raise Refused("LIFECYCLE_" + suffix)


def _exact(value, keys):
    return type(value) is dict and len(value) == len(keys) and all(type(k) is str for k in value) and set(value) == keys


def _root(value):
    require(type(value) is Path or isinstance(value, Path), "ROOT")
    return base._root(value)


def _read(root, name, limit=65536):
    return base._read(root, name, limit)


def _json(root, name, optional=False):
    if optional:
        parts = name.split("/")
        require(parts and all(part not in {"", ".", ".."} for part in parts), "PATH")
        fd = base._directory(root)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = child
                info = os.fstat(fd)
                require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "STORE_UNSAFE")
            try:
                os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
        except OSError:
            raise Refused("LIFECYCLE_STORE_UNSAFE") from None
        finally:
            os.close(fd)
    return parse(_read(root, name))


def _publish(root, name, value):
    require(name in RECEIPTS or SESSION.fullmatch(name) is not None, "RECEIPT")
    try:
        base._publish(root / "receipts" / name, value)
    except FileExistsError:
        raise Refused("LIFECYCLE_ALREADY_ATTEMPTED") from None


def _source_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) in {0o700, 0o755}, "SOURCE")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _source_read(relative):
    parts = relative.split("/")
    require(parts and all(part not in {"", ".", ".."} for part in parts), "SOURCE")
    fd = _source_directory(HERE)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
            info = os.fstat(fd)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) in {0o700, 0o755}, "SOURCE")
        child = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                    and stat.S_IMODE(info.st_mode) in {0o600, 0o644}, "SOURCE")
            raw = stream.read(524289)
            require(len(raw) <= 524288 and base.Manager._task_preset_identity(info)
                    == base.Manager._task_preset_identity(os.fstat(stream.fileno()))
                    == base.Manager._task_preset_identity(os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)), "SOURCE")
            return raw
    finally:
        os.close(fd)


def _source_fingerprint():
    files, total = {}, 0
    visited, pending = 0, [(HERE, 0)]
    while pending:
        folder, depth = pending.pop()
        os.close(_source_directory(folder))
        with os.scandir(folder) as entries:
            for entry in entries:
                visited += 1
                require(visited <= 512, "SOURCE_LIMIT")
                info = entry.stat(follow_symlinks=False)
                require(not stat.S_ISLNK(info.st_mode), "SOURCE")
                path = folder / entry.name; relative = path.relative_to(HERE)
                if stat.S_ISDIR(info.st_mode):
                    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) in {0o700, 0o755}, "SOURCE")
                    if depth or entry.name in {"static", "examples"}:
                        require(depth < 4, "SOURCE_LIMIT")
                        pending.append((path, depth + 1))
                    continue
                selected = (path.suffix in {".py", ".java", ".json"} and depth == 0
                            or depth > 0 and path.suffix in {".py", ".java", ".json", ".js", ".html", ".css"})
                if selected:
                    require(stat.S_ISREG(info.st_mode) and len(files) < 128, "SOURCE")
                    raw = _source_read(relative.as_posix())
                    total += len(raw)
                    require(total <= 4194304, "SOURCE")
                    files[relative.as_posix()] = sha(raw)
    require("offline_lifecycle.py" in files and "agent.py" in files and "workbench.py" in files, "SOURCE")
    return {"directory": str(HERE), "files": dict(sorted(files.items()))}


def _control(root):
    root = _root(root)
    os.close(base._directory(root)); os.close(base._directory(root / "receipts"))
    require(set(base._names(root)) == {"control.json", "receipts", "workflow"}, "FOREIGN_STORE")
    control = _json(root, "control.json")
    require(_exact(control, {"version", "format", "scenario", "fixture_id", "root", "workflow", "source"})
            and type(control["version"]) is int and control["version"] == 1 and control["format"] == FORMAT
            and type(control["scenario"]) is str and control["scenario"] in SCENARIOS
            and type(control["fixture_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", control["fixture_id"]) is not None
            and control["root"] == str(root) and control["workflow"] == str(root / "workflow")
            and control["source"] == _source_fingerprint(), "CONTROL")
    return control


def _catalog(root, control):
    names = base._names(root / "receipts")
    require(len(names) <= 64, "LIMIT")
    for name in names:
        original = name[:-5] if name.endswith(".next") else name
        require(original in RECEIPTS or SESSION.fullmatch(original) is not None, "FOREIGN_STORE")
        # Staged receipt bytes are safety-checked but never treated as committed.
        raw = _read(root, "receipts/" + name)
        if SESSION.fullmatch(name) is not None:
            value = parse(raw)
            if name.startswith("session-"):
                require(_exact(value, {"version", "fixture_id", "scenario", "pid", "port"})
                        and type(value["version"]) is int and value["version"] == 1
                        and value["fixture_id"] == control["fixture_id"] and value["scenario"] == control["scenario"]
                        and type(value["pid"]) is int and 0 < value["pid"] <= 2147483647
                        and type(value["port"]) is int and value["port"] == PORTS[control["scenario"]], "RECEIPT")
            else:
                require(_exact(value, {"version", "listener_closed", "counters", "lifecycle_counters"})
                        and type(value["version"]) is int and value["version"] == 1 and value["listener_closed"] is True
                        and _exact(value["counters"], set(base.COUNTER_KEYS))
                        and _exact(value["lifecycle_counters"], set(LIFECYCLE_COUNTER_KEYS))
                        and all(type(n) is int and 0 <= n <= 9007199254740991 for group in [value["counters"], value["lifecycle_counters"]] for n in group.values()), "RECEIPT")
    return names


def initialize(root, scenario):
    require(type(scenario) is str and scenario in SCENARIOS, "SCENARIO")
    root = _root(root)
    require(not root.exists() and not root.is_symlink(), "ROOT_EXISTS")
    os.close(base._directory(root.parent))
    root.mkdir(mode=0o700)
    (root / "receipts").mkdir(mode=0o700)
    marker = base.initialize(root / "workflow")
    value = {"version": 1, "format": FORMAT, "scenario": scenario, "fixture_id": marker["fixture_id"],
             "root": str(root), "workflow": str(root / "workflow"), "source": _source_fingerprint()}
    base._new(root / "control.json", value)
    return validate_fixture(root)


def validate_fixture(root):
    try:
        control = _control(root)
        marker = base.validate_fixture(root / "workflow")
        require(marker["fixture_id"] == control["fixture_id"], "CONTROL")
        _catalog(root, control)
        return control
    except Refused as error:
        if str(error).startswith("LIFECYCLE_"):
            raise
        raise Refused("LIFECYCLE_STORE_UNSAFE") from None
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise Refused("LIFECYCLE_STORE_UNSAFE") from None


def expected_worker_command(root, identifier):
    require(type(identifier) is str and base.ID.fullmatch(identifier) is not None, "ARGV")
    return [sys.executable, "-B", str(HERE / "offline_lifecycle.py"), "worker", "--work-dir", str(_root(root)), "--run-id", identifier]


def _common(control, identifier, pid):
    return {"version": 1, "fixture_id": control["fixture_id"], "id": identifier, "pid": pid}


def _valid_common(value, control, identifier, pid, keys=COMMON):
    return (_exact(value, keys) and type(value["version"]) is int and value["version"] == 1
            and value["fixture_id"] == control["fixture_id"] and value["id"] == identifier
            and type(value["pid"]) is int and 0 < value["pid"] <= 2147483647 and value["pid"] == pid)


def _valid_attempt(value, control):
    return (_exact(value, {"version", "fixture_id", "scenario"}) and type(value["version"]) is int
            and value["version"] == 1 and value["fixture_id"] == control["fixture_id"] and value["scenario"] == control["scenario"])


def armed_checkpoint(root, identifier):
    if any(name.endswith(".next") for name in base._names(root / "receipts")):
        return False
    control = validate_fixture(root)
    path = root / "receipts/armed.json"
    if not path.exists() or path.with_name(path.name + ".next").exists():
        return False
    spawned = _json(root, "receipts/spawned.json", True)
    armed = _json(root, "receipts/armed.json")
    return (type(spawned) is dict and _valid_common(spawned, control, identifier, spawned.get("pid"))
            and _valid_common(armed, control, identifier, spawned["pid"], COMMON | {"scenario"})
            and armed["scenario"] == control["scenario"])


class LifecycleManager(base.WorkflowManager):
    def __init__(self, root):
        self.lifecycle_root = _root(root)
        self.control = validate_fixture(self.lifecycle_root)
        self.lifecycle_counters = dict.fromkeys(LIFECYCLE_COUNTER_KEYS, 0)
        self._lifecycle_closing = False
        self._launch_context = None
        super().__init__(self.lifecycle_root / "workflow")

    def _launch(self, command, **kwargs):
        # BaseManager has prepared the job/task but the inherited _launch has
        # not published its launch record yet. Validate outer custody here;
        # the original _launch validates this exact transient launch state.
        control = _control(self.lifecycle_root)
        _catalog(self.lifecycle_root, control)
        _publish(self.lifecycle_root, "attempt.json", {"version": 1, "fixture_id": self.control["fixture_id"], "scenario": self.control["scenario"]})
        require(self._launch_context is None, "ARGV")
        self._launch_context = (command, kwargs)
        try:
            with patch("offline_workflow.REAL_POPEN", self._controlled_popen):
                return super()._launch(command, **kwargs)
        finally:
            self._launch_context = None

    def _controlled_popen(self, command, **kwargs):
        require(self._launch_context is not None, "ARGV")
        control = validate_fixture(self.lifecycle_root)
        launch = base._launch_record(self.root, self.marker)
        identifier = launch["id"]
        logical = base.expected_command(self.root, identifier)
        require(self._launch_context[0] == logical and kwargs == self._launch_context[1], "ARGV")
        expected = [sys.executable, "-B", str(HERE / "offline_workflow_worker.py"), "--work-dir", str(self.root), "--run-id", identifier, "--"] + logical[3:]
        require(type(command) is list and command == expected, "ARGV")
        require(set(kwargs) == {"stdin", "stdout", "stderr", "start_new_session", "env"}
                and kwargs["stdin"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.STDOUT
                and kwargs["start_new_session"] is True and type(kwargs["stdout"]) is io.BufferedWriter
                and kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}, "ARGV")
        info = os.fstat(kwargs["stdout"].fileno())
        named = os.stat(self.root / "workspace/data/jobs" / (identifier + ".log"), follow_symlinks=False)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino), "ARGV")
        require(_valid_attempt(_json(self.lifecycle_root, "receipts/attempt.json"), control), "CLAIM")
        actual = expected_worker_command(self.lifecycle_root, identifier)
        _publish(self.lifecycle_root, "actual-launch.json", {"version": 1, "fixture_id": control["fixture_id"], "id": identifier,
                 "argv": actual, "control_sha256": sha(_read(self.lifecycle_root, "control.json"))})
        child = REAL_POPEN(actual, **kwargs)
        require(type(child.pid) is int and 0 < child.pid <= 2147483647, "PID")
        _publish(self.lifecycle_root, "spawned.json", _common(control, identifier, child.pid))
        self.lifecycle_counters["native_launches"] += 1
        return child

    def stop(self, identifier):
        with self.lock:
            validate_fixture(self.lifecycle_root)
            entry = self.children.get(identifier)
            require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_TASK")
            control, child = self.control, entry[0]
            spawned = _json(self.lifecycle_root, "receipts/spawned.json")
            require(_valid_common(spawned, control, identifier, child.pid), "OWNERSHIP")
            kind = "containment" if self._lifecycle_closing else "explicit"
            if kind == "explicit":
                require(control["scenario"] == "stop" and armed_checkpoint(self.lifecycle_root, identifier), "STOP_UNARMED")
            launch = _json(self.lifecycle_root, "receipts/actual-launch.json")
            require(launch.get("argv") == expected_worker_command(self.lifecycle_root, identifier)
                    and launch.get("control_sha256") == sha(_read(self.lifecycle_root, "control.json")), "OWNERSHIP")
            prefix = "containment" if kind == "containment" else "stop"
            intent = {**_common(control, identifier, child.pid), "scenario": control["scenario"], "kind": kind,
                      "armed_sha256": sha(_read(self.lifecycle_root, "receipts/armed.json")) if kind == "explicit" else None,
                      "launch_sha256": sha(_read(self.lifecycle_root, "receipts/actual-launch.json"))}
            _publish(self.lifecycle_root, prefix + "-intent.json", intent)
            self.lifecycle_counters["containment_stops" if kind == "containment" else "explicit_stops"] += 1
            result = super().stop(identifier)
            _publish(self.lifecycle_root, prefix + "-return.json", {**intent, "state": result["state"]})
            return result

    def close(self):
        self._lifecycle_closing = True
        try:
            return super().close()
        finally:
            self._lifecycle_closing = False


def lifecycle_report(root):
    control = validate_fixture(root)
    names = _catalog(root, control)
    launch = _json(root, "receipts/actual-launch.json", True)
    identifier = launch.get("id") if type(launch) is dict else None
    require(identifier is None or type(identifier) is str and base.ID.fullmatch(identifier) is not None, "RECEIPT")
    meta = _json(root / "workflow", "workspace/data/jobs/" + identifier + ".json", True) if identifier else None
    exit_receipt = _json(root, "receipts/worker-exit.json", True)
    run_present = bool(identifier and (root / "workflow/workspace/data/runs" / identifier).exists())
    notes = []
    states = {"RUNNING", "STOP_REQUESTED", "FAILED", "REFUSED", "UNCERTAIN", "INTERRUPTED", "RECOVERY_REQUIRED", "REVIEW_READY"}
    state = meta.get("state") if type(meta) is dict else None
    code = meta.get("exit_code") if type(meta) is dict else None
    result = {"version": 1, "scenario": control["scenario"], "fixture_id": control["fixture_id"], "run_id": identifier,
              "status": "UNKNOWN", "outcome": "UNKNOWN", "metadata_state": state if type(state) is str and state in states else None,
              "exit_code": code if type(code) is int and -2147483648 <= code <= 2147483647 else None,
              "signal": None, "guard_attempts": {"provider": None, "checks": None, "network": None},
              "source_unchanged": True, "original_inputs_unchanged": True, "run_directory_present": run_present,
              "agent_executed": None, "notes": notes}
    if launch is None:
        notes.append("NOT_ATTEMPTED")
        return result
    try:
        require(not any(name.endswith(".next") for name in names), "INCOMPLETE")
        require(_valid_attempt(_json(root, "receipts/attempt.json"), control), "EVIDENCE")
        claim = _json(root / "workflow", "receipts/start-claim.json")
        require(_exact(claim, {"version", "fixture_id", "attempt"}) and type(claim["version"]) is int and claim["version"] == 1
                and type(claim["attempt"]) is int and claim["attempt"] == 1 and claim["fixture_id"] == control["fixture_id"], "EVIDENCE")
        require(base._launch_record(root / "workflow", base.validate_fixture(root / "workflow"))["id"] == identifier, "EVIDENCE")
        require(_exact(launch, {"version", "fixture_id", "id", "argv", "control_sha256"}) and type(launch["version"]) is int
                and launch["version"] == 1 and launch["fixture_id"] == control["fixture_id"]
                and launch["argv"] == expected_worker_command(root, identifier)
                and launch["control_sha256"] == sha(_read(root, "control.json")), "EVIDENCE")
        spawned = _json(root, "receipts/spawned.json")
        require(type(spawned) is dict and _valid_common(spawned, control, identifier, spawned.get("pid")), "EVIDENCE")
        pid = spawned["pid"]
        require(_valid_common(_json(root, "receipts/worker-start.json"), control, identifier, pid)
                and armed_checkpoint(root, identifier), "EVIDENCE")
        parent = _json(root / "workflow", "receipts/parent-started.json")
        require(_valid_common(parent, control, identifier, pid), "EVIDENCE")
        base._metadata_matches(root / "workflow", base.validate_fixture(root / "workflow"), identifier, meta)
        keys = COMMON | {"scenario", "exit_code", "signal", "provider_attempts", "check_attempts", "network_attempts", "python_level_guards", "os_wide_packet_audit"}
        require(_valid_common(exit_receipt, control, identifier, pid, keys) and exit_receipt["scenario"] == control["scenario"]
                and type(exit_receipt["exit_code"]) is int and exit_receipt["python_level_guards"] is True
                and exit_receipt["os_wide_packet_audit"] is False
                and all(type(exit_receipt[key]) is int and exit_receipt[key] == 0 for key in ["provider_attempts", "check_attempts", "network_attempts"]), "EVIDENCE")
        require(type(meta) is dict and meta.get("state") == "FAILED" and type(meta.get("exit_code")) is int
                and meta["exit_code"] == exit_receipt["exit_code"] and type(meta.get("pid")) is int and meta["pid"] == pid and not run_present, "EVIDENCE")
        require("containment-intent.json" not in names and "containment-return.json" not in names, "CONTAINMENT")
        if control["scenario"] == "fail":
            require(exit_receipt["exit_code"] == 23 and exit_receipt["signal"] is None
                    and "stop-intent.json" not in names and "stop-return.json" not in names, "EXIT")
            outcome = "CONTROLLED_FAILURE"
        else:
            intent, returned = _json(root, "receipts/stop-intent.json"), _json(root, "receipts/stop-return.json")
            require(_valid_common(intent, control, identifier, pid, COMMON | {"scenario", "kind", "armed_sha256", "launch_sha256"})
                    and intent["scenario"] == "stop" and intent["kind"] == "explicit"
                    and intent["armed_sha256"] == sha(_read(root, "receipts/armed.json"))
                    and intent["launch_sha256"] == sha(_read(root, "receipts/actual-launch.json"))
                    and _valid_common(returned, control, identifier, pid, COMMON | {"scenario", "kind", "armed_sha256", "launch_sha256", "state"})
                    and returned == {**intent, "state": "STOP_REQUESTED"}
                    and type(exit_receipt["signal"]) is int and exit_receipt["signal"] == signal.SIGTERM
                    and exit_receipt["exit_code"] == 130, "EXIT")
            outcome = "OWNED_STOP"
        result.update(status="VERIFIED", outcome=outcome, signal=exit_receipt["signal"], agent_executed=False,
                      guard_attempts={"provider": 0, "checks": 0, "network": 0})
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError):
        notes.append("INCOMPLETE_EVIDENCE" if exit_receipt is None else "EVIDENCE_INVALID")
        if run_present:
            notes.append("UNEXPECTED_AGENT_ARTIFACTS")
        if "containment-intent.json" in names:
            notes.append("CONTAINMENT_STOP")
    result["notes"] = sorted(set(notes))
    require(len(canonical(result)) <= 65536, "LIMIT")
    return result


@contextmanager
def worker_guards():
    counts = {"provider": 0, "checks": 0, "network": 0}
    def blocked(kind):
        def refuse(*_args, **_kwargs):
            counts[kind] += 1
            raise Refused("LIFECYCLE_WORKER_GUARD")
        return refuse
    with ExitStack() as stack:
        for target in ["agent.Ollama.request", "agent.Ollama.preflight", "agent.ScriptedDemo.request"]:
            stack.enter_context(patch(target, side_effect=blocked("provider")))
        for target in ["agent.main", "agent.Session.run", "agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.fixed_checks", "offline_workflow.fixed_checks", "offline_workflow.java_checks", "subprocess.Popen", "subprocess.run"]:
            stack.enter_context(patch(target, side_effect=blocked("checks")))
        for owner, names in [(socket, ["create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"]),
                             (socket.socket, ["connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"]),
                             (http.client.HTTPConnection, ["connect"]), (http.client.HTTPSConnection, ["connect"])]:
            for name in names:
                if hasattr(owner, name):
                    stack.enter_context(patch.object(owner, name, side_effect=blocked("network")))
        yield counts


def run_worker(root, identifier):
    observed_signal = [None]
    def stopped(signum, _frame):
        observed_signal[0] = signum
    signal.signal(signal.SIGTERM, stopped)
    control = _control(root)
    pid = os.getpid()
    deadline = time.monotonic() + HANDSHAKE_SECONDS
    parent = root / "workflow/receipts/parent-started.json"
    while time.monotonic() < deadline:
        if parent.exists() and not parent.with_name(parent.name + ".next").exists() and (root / "receipts/spawned.json").exists() and not any(name.endswith(".next") for name in base._names(root / "receipts")):
            break
        time.sleep(0.01)
    else:
        raise Refused("LIFECYCLE_HANDSHAKE")
    validate_fixture(root)
    common = _common(control, identifier, pid)
    require(_json(root, "receipts/spawned.json") == common and _json(root / "workflow", "receipts/parent-started.json") == common, "OWNERSHIP")
    launch = _json(root, "receipts/actual-launch.json")
    require(launch["argv"] == expected_worker_command(root, identifier), "ARGV")
    code = 24
    with worker_guards() as counts:
        try:
            _publish(root, "worker-start.json", common)
            _publish(root, "armed.json", {**common, "scenario": control["scenario"]})
            if control["scenario"] == "fail":
                code = 23 if observed_signal[0] is None else 130
            else:
                deadline = time.monotonic() + ARMED_SECONDS
                while observed_signal[0] is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                code = 130 if observed_signal[0] == signal.SIGTERM else 24
        finally:
            _publish(root, "worker-exit.json", {**common, "scenario": control["scenario"], "exit_code": code,
                     "signal": observed_signal[0], "provider_attempts": counts["provider"], "check_attempts": counts["checks"],
                     "network_attempts": counts["network"], "python_level_guards": True, "os_wide_packet_audit": False})
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["init", "serve", "inspect", "worker"]:
        child = sub.add_parser(command); child.add_argument("--work-dir", type=Path, required=True)
        if command == "init": child.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
        if command == "serve": child.add_argument("--port", type=int, required=True)
        if command == "worker": child.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.command == "init":
        print(canonical(initialize(args.work_dir, args.scenario)).decode(), end=""); return 0
    if args.command == "inspect":
        print(canonical(lifecycle_report(args.work_dir)).decode(), end=""); return 0
    if args.command == "worker":
        return run_worker(args.work_dir, args.run_id)
    control = validate_fixture(args.work_dir)
    require(args.port == PORTS[control["scenario"]], "PORT")
    manager = LifecycleManager(args.work_dir)
    session = secrets.token_hex(8)
    _publish(args.work_dir, "session-" + session + ".json", {"version": 1, "fixture_id": control["fixture_id"],
             "scenario": control["scenario"], "pid": os.getpid(), "port": args.port})
    server = None
    def stop(_signum, _frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    try:
        origin = "http://127.0.0.1:" + str(args.port)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), base.offline_handler(manager, secrets.token_urlsafe(32), origin, manager.counters))
        server.daemon_threads = True
        print(canonical({"url": origin, "scenario": control["scenario"], "pid": os.getpid()}).decode(), end="", flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None: server.server_close()
        manager.close()
        _publish(args.work_dir, "shutdown-" + session + ".json", {"version": 1, "listener_closed": True,
                 "counters": manager.counters, "lifecycle_counters": manager.lifecycle_counters})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, TypeError, KeyError):
        print('{"status":"REFUSED","reason":"LIFECYCLE_REFUSED"}', flush=True)
        raise SystemExit(2) from None
