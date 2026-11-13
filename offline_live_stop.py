"""Once-only live Run/Stop QA around the unchanged offline lifecycle harness.

A successful normal RUNNING response write is server evidence, not proof of
client delivery or browser rendering. Browser observation must be independent.
The original 30-second controlled child and its guards are never replaced.
"""

import argparse
import hmac
import os
import re
import secrets
import signal
import stat
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import offline_lifecycle as lifecycle
import offline_workflow as base
from agent import Refused, canonical, parse, sha


FORMAT = "outlands-offline-live-stop-v1"
PORT = 36231
RUN_SECONDS = 25
LIVE_COUNTER_KEYS = ("running_responses", "armed_stops", "explicit_stops", "containment_stops")
RECEIPTS = {"start-intent.json", "running-response.json", "armed-stop.json", "stop-intent.json", "stop-return.json",
            "deadline.json", "containment.json", "gate-failed.json"}
SESSION = re.compile(r"(?:session|shutdown)-[0-9a-f]{16}[.]json\Z")
COMMON = {"version", "fixture_id", "id", "pid", "control_sha256"}
MAX_SAFE = 9007199254740991
FAILURE_STAGES = {"RUNNING_RESPONSE", "READINESS", "GATE_PUBLICATION", "OWNERSHIP", "DEADLINE", "CONTAINMENT"}
FAILURE_TYPES = {"REFUSED", "OS_ERROR", "VALUE_ERROR", "TYPE_ERROR", "KEY_ERROR", "UNKNOWN"}


def require(condition, suffix):
    if not condition:
        raise Refused("LIVE_STOP_" + suffix)


def _integer(value, low=0, high=MAX_SAFE):
    return type(value) is int and low <= value <= high


def _read(root, name):
    return base._read(root, name, 65536)


def _json(root, name, optional=False):
    return lifecycle._json(root, name, optional)


def _publish(root, name, value):
    require(name in RECEIPTS or SESSION.fullmatch(name) is not None, "RECEIPT")
    try:
        base._publish(root / "receipts" / name, value)
    except FileExistsError:
        raise Refused("LIVE_STOP_ALREADY_ATTEMPTED") from None


def _common(control, control_sha, identifier, pid):
    return {"version": 1, "fixture_id": control["fixture_id"], "id": identifier, "pid": pid,
            "control_sha256": control_sha}


def _valid_common(value, control, control_sha, keys):
    return (lifecycle._exact(value, COMMON | keys) and type(value["version"]) is int and value["version"] == 1
            and value["fixture_id"] == control["fixture_id"] and value["control_sha256"] == control_sha
            and type(value["id"]) is str and base.ID.fullmatch(value["id"]) is not None
            and _integer(value["pid"], 1, 2147483647))


def _catalog(root, control):
    names = base._names(root / "receipts", 64)
    control_sha = sha(_read(root, "control.json"))
    for name in names:
        original = name[:-5] if name.endswith(".next") else name
        require(original in RECEIPTS or SESSION.fullmatch(original) is not None, "FOREIGN_STORE")
        raw = _read(root, "receipts/" + name)
        if name.endswith(".next"):
            continue
        value = parse(raw)
        if name == "start-intent.json":
            require(lifecycle._exact(value, {"version", "fixture_id", "control_sha256", "attempt", "started_at_ms"})
                    and type(value["version"]) is int and value["version"] == 1
                    and value["fixture_id"] == control["fixture_id"] and value["control_sha256"] == control_sha
                    and type(value["attempt"]) is int and value["attempt"] == 1 and _integer(value["started_at_ms"]), "RECEIPT")
        elif name.startswith("session-"):
            require(lifecycle._exact(value, {"version", "format", "fixture_id", "control_sha256", "pid", "port", "read_only"})
                    and type(value["version"]) is int and value["version"] == 1 and value["format"] == FORMAT
                    and value["fixture_id"] == control["fixture_id"] and value["control_sha256"] == control_sha
                    and _integer(value["pid"], 1, 2147483647) and type(value["port"]) is int and value["port"] == PORT
                    and type(value["read_only"]) is bool, "RECEIPT")
        elif name.startswith("shutdown-"):
            require(lifecycle._exact(value, {"version", "format", "fixture_id", "port", "listener_closed", "read_only",
                                             "counters", "lifecycle_counters", "live_counters"})
                    and type(value["version"]) is int and value["version"] == 1 and value["format"] == FORMAT
                    and value["fixture_id"] == control["fixture_id"] and type(value["port"]) is int and value["port"] == PORT
                    and value["listener_closed"] is True and type(value["read_only"]) is bool
                    and all(lifecycle._exact(value[key], set(fields)) and all(_integer(n) for n in value[key].values())
                            for key, fields in (("counters", base.COUNTER_KEYS), ("lifecycle_counters", lifecycle.LIFECYCLE_COUNTER_KEYS),
                                                ("live_counters", LIVE_COUNTER_KEYS))), "RECEIPT")
        else:
            extra = {"elapsed_ms"}
            if name == "running-response.json": extra |= {"response_sha256", "response_bytes", "state", "http_status", "delivery"}
            elif name == "armed-stop.json": extra |= {"running_response_sha256", "lifecycle_armed_sha256"}
            elif name in {"stop-intent.json", "stop-return.json"}: extra |= {"armed_stop_sha256"}
            elif name in {"containment.json", "gate-failed.json"}: extra |= {"reason"}
            if name == "gate-failed.json": extra |= {"stage", "failure_type"}
            if name == "stop-return.json": extra |= {"state"}
            require(_valid_common(value, control, control_sha, extra) and _integer(value["elapsed_ms"]), "RECEIPT")
            for key in {"response_sha256", "running_response_sha256", "lifecycle_armed_sha256", "armed_stop_sha256"} & set(value):
                require(type(value[key]) is str and base.HASH.fullmatch(value[key]) is not None, "RECEIPT")
            if name == "running-response.json":
                require(_integer(value["response_bytes"], 1, 262144) and value["state"] == "RUNNING"
                        and type(value["http_status"]) is int and value["http_status"] == 200
                        and value["delivery"] == "SERVER_WRITE_RETURNED", "RECEIPT")
            elif name == "stop-return.json": require(value["state"] == "STOP_REQUESTED", "RECEIPT")
            elif name == "containment.json": require(value["reason"] in {"DEADLINE", "SERVER_CLOSE"}, "RECEIPT")
            elif name == "gate-failed.json":
                require(value["reason"] == "GATE_FAILED" and value["stage"] in FAILURE_STAGES
                        and value["failure_type"] in FAILURE_TYPES, "RECEIPT")
    return names


def _control(root):
    """Validate source and inputs without walking a publishing worker's receipts."""
    try:
        root = base._root(root)
        os.close(base._directory(root)); os.close(base._directory(root / "receipts"))
        require(set(base._names(root)) == {"control.json", "receipts", "lifecycle"}, "FOREIGN_STORE")
        inner = lifecycle._control(root / "lifecycle")
        marker = base.validate_fixture(root / "lifecycle/workflow")
        require(marker["fixture_id"] == inner["fixture_id"], "CONTROL")
        value = _json(root, "control.json")
        require(lifecycle._exact(value, {"version", "format", "fixture_id", "root", "lifecycle", "port", "run_seconds",
                                         "source_sha256", "lifecycle_control_sha256"})
                and type(value["version"]) is int and value["version"] == 1 and value["format"] == FORMAT
                and value["fixture_id"] == inner["fixture_id"] and value["root"] == str(root)
                and value["lifecycle"] == str(root / "lifecycle") and inner["scenario"] == "stop"
                and type(value["port"]) is int and value["port"] == PORT
                and type(value["run_seconds"]) is int and value["run_seconds"] == RUN_SECONDS
                and value["source_sha256"] == sha(canonical(inner["source"]))
                and value["lifecycle_control_sha256"] == sha(lifecycle._read(root / "lifecycle", "control.json")), "CONTROL")
        _catalog(root, value)
        return value
    except Refused as error:
        if str(error).startswith("LIVE_STOP_"):
            raise
        raise Refused("LIVE_STOP_STORE_UNSAFE") from None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise Refused("LIVE_STOP_STORE_UNSAFE") from None


def validate_fixture(root):
    value = _control(root)
    try:
        lifecycle.validate_fixture(root / "lifecycle")
        return value
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise Refused("LIVE_STOP_STORE_UNSAFE") from None


def _worker_receipts_stable(root):
    """Recognize publication-in-progress, without relaxing final custody checks.

    Only missing final worker-start/armed records, staged records, and the exact
    same-inode two-link commit window are pending. Unsafe facts still refuse.
    No receipt payload is trusted here; full inherited validation follows.
    """
    receipts = root / "receipts"
    fd = base._directory(receipts)
    pending = False
    required = {"worker-start.json", "armed.json"}
    try:
        names = set(base._names(receipts, 64))
        for name in sorted(names):
            original = name[:-5] if name.endswith(".next") else name
            require(original in lifecycle.RECEIPTS or lifecycle.SESSION.fullmatch(original) is not None, "FOREIGN_STORE")
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                require(name.endswith(".next") or name in required, "STORE_UNSAFE")
                pending = True
                continue
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 65536, "STORE_UNSAFE")
            if name.endswith(".next"):
                require(info.st_nlink in {1, 2}, "STORE_UNSAFE")
                if info.st_nlink == 2:
                    try:
                        committed = os.stat(original, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError:
                        raise Refused("LIVE_STOP_STORE_UNSAFE") from None
                    require((committed.st_dev, committed.st_ino) == (info.st_dev, info.st_ino)
                            and committed.st_nlink in {1, 2}, "STORE_UNSAFE")
                pending = True
            elif info.st_nlink != 1:
                require(name in required and info.st_nlink == 2, "STORE_UNSAFE")
                try:
                    stage = os.stat(name + ".next", dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    after = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    require((after.st_dev, after.st_ino) == (info.st_dev, info.st_ino) and after.st_nlink == 1, "STORE_UNSAFE")
                else:
                    require((stage.st_dev, stage.st_ino) == (info.st_dev, info.st_ino), "STORE_UNSAFE")
                pending = True
        return required <= names and not pending
    finally:
        os.close(fd)


def initialize(root):
    root = base._root(root)
    require(not root.exists() and not root.is_symlink(), "ROOT_EXISTS")
    os.close(base._directory(root.parent))
    root.mkdir(mode=0o700)
    (root / "receipts").mkdir(mode=0o700)
    inner = lifecycle.initialize(root / "lifecycle", "stop")
    base._new(root / "control.json", {"version": 1, "format": FORMAT, "fixture_id": inner["fixture_id"],
        "root": str(root), "lifecycle": str(root / "lifecycle"), "port": PORT, "run_seconds": RUN_SECONDS,
        "source_sha256": sha(canonical(inner["source"])),
        "lifecycle_control_sha256": sha(lifecycle._read(root / "lifecycle", "control.json"))})
    return validate_fixture(root)


def armed_checkpoint(root, identifier=None):
    control = _control(root)
    names = _catalog(root, control)
    if any(name.endswith(".next") for name in names) or {"deadline.json", "containment.json", "gate-failed.json"} & set(names):
        return False
    running = _json(root, "receipts/running-response.json", True)
    armed = _json(root, "receipts/armed-stop.json", True)
    if running is None or armed is None:
        return False
    if not _worker_receipts_stable(root / "lifecycle"):
        return False
    validate_fixture(root)
    run_id = running["id"]
    return (identifier in {None, run_id} and armed["id"] == run_id and armed["pid"] == running["pid"]
            and running["elapsed_ms"] <= armed["elapsed_ms"] <= RUN_SECONDS * 1000
            and armed["running_response_sha256"] == sha(_read(root, "receipts/running-response.json"))
            and lifecycle.armed_checkpoint(root / "lifecycle", run_id)
            and armed["lifecycle_armed_sha256"] == sha(lifecycle._read(root / "lifecycle", "receipts/armed.json")))


class LiveStopManager(lifecycle.LifecycleManager):
    def __init__(self, root):
        self.live_root = base._root(root)
        self.live_control = validate_fixture(self.live_root)
        self.live_control_sha256 = sha(_read(self.live_root, "control.json"))
        names = _catalog(self.live_root, self.live_control)
        self.read_only = bool(names)
        self.live_counters = dict.fromkeys(LIVE_COUNTER_KEYS, 0)
        self._live_started = self._running_claimed = self._armed_claimed = self._stop_claimed = self._gate_failed = False
        self._failure_claimed = self._containment_claimed = False
        self._gate_stage = "READINESS"
        self._started_time = self._deadline = self._live_id = None
        self._monitor_stop = threading.Event()
        self._monitor_thread = None
        super().__init__(self.live_root / "lifecycle")

    def _elapsed(self):
        return max(0, int((time.monotonic() - self._started_time) * 1000)) if self._started_time is not None else 0

    def _owned(self, identifier):
        require(type(identifier) is str and base.ID.fullmatch(identifier) is not None and identifier == self._live_id, "OWNERSHIP")
        entry = self.children.get(identifier)
        require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_TASK")
        spawned = lifecycle._json(self.lifecycle_root, "receipts/spawned.json")
        require(lifecycle._valid_common(spawned, self.control, identifier, entry[0].pid), "OWNERSHIP")
        return entry[0]

    def _common(self, child):
        return _common(self.live_control, self.live_control_sha256, self._live_id, child.pid)

    def _fail_gate(self, stage, error, child):
        """Retain one finite failure claim; never retry its publication or arm."""
        self._gate_failed = True
        if self._failure_claimed:
            return
        self._failure_claimed = True
        category = next((label for kind, label in ((Refused, "REFUSED"), (OSError, "OS_ERROR"),
            (ValueError, "VALUE_ERROR"), (TypeError, "TYPE_ERROR"), (KeyError, "KEY_ERROR")) if isinstance(error, kind)), "UNKNOWN")
        try:
            _publish(self.live_root, "gate-failed.json", {**self._common(child), "reason": "GATE_FAILED",
                "elapsed_ms": self._elapsed(), "stage": stage if stage in FAILURE_STAGES else "READINESS", "failure_type": category})
        except (Refused, OSError, ValueError, TypeError, KeyError):
            pass

    def start(self, request):
        with self.lock:
            require(not self.read_only and not self._live_started, "ALREADY_ATTEMPTED")
            validate_fixture(self.live_root)
            require(_catalog(self.live_root, self.live_control) == [] or all(SESSION.fullmatch(name) for name in _catalog(self.live_root, self.live_control)), "ALREADY_ATTEMPTED")
            self._live_started = True
            self._started_time = time.monotonic()
            self._deadline = self._started_time + RUN_SECONDS
            _publish(self.live_root, "start-intent.json", {"version": 1, "fixture_id": self.live_control["fixture_id"],
                "control_sha256": self.live_control_sha256, "attempt": 1, "started_at_ms": time.time_ns() // 1000000})
            result = super().start(request)
            self._live_id = result["id"]
            self._owned(self._live_id)
            self._monitor_thread = threading.Thread(target=self._monitor, name="live-stop-deadline", daemon=True)
            self._monitor_thread.start()
            return result

    def running_response(self, identifier, raw):
        """Called only after the authenticated normal handler's body write returns."""
        with self.lock:
            if self._running_claimed or self.read_only:
                return
            self._running_claimed = True
            child = self._owned(identifier)
            try:
                self._gate_stage = "RUNNING_RESPONSE"
                _control(self.live_root)
                require(time.monotonic() < self._deadline and type(raw) is bytes and 0 < len(raw) <= 262144, "EXPIRED")
                value = parse(raw)
                require(type(value) is dict and value.get("id") == identifier and value.get("state") == "RUNNING"
                        and value.get("backend") == value.get("model") == "scripted-demo", "RUNNING_RESPONSE")
                _publish(self.live_root, "running-response.json", {**self._common(child), "response_sha256": sha(raw),
                    "response_bytes": len(raw), "state": "RUNNING", "http_status": 200,
                    "delivery": "SERVER_WRITE_RETURNED", "elapsed_ms": self._elapsed()})
                self.live_counters["running_responses"] += 1
                self.poll_gate()
            except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                self._fail_gate(self._gate_stage, error, child)

    def poll_gate(self):
        """Bounded readiness only; never starts, retries or stops a child."""
        with self.lock:
            if self.read_only or self._gate_failed or self._armed_claimed or self._stop_claimed or self._live_id is None:
                return False
            self._gate_stage = "READINESS"
            child = self._owned(self._live_id)
            require(time.monotonic() < self._deadline, "EXPIRED")
            _control(self.live_root)
            running = _json(self.live_root, "receipts/running-response.json", True)
            if running is None or not _worker_receipts_stable(self.lifecycle_root):
                return False
            validate_fixture(self.live_root)
            require(lifecycle.armed_checkpoint(self.lifecycle_root, self._live_id), "STOP_UNARMED")
            require(running["id"] == self._live_id and running["pid"] == child.pid, "OWNERSHIP")
            running_sha = sha(_read(self.live_root, "receipts/running-response.json"))
            original_armed_sha = sha(lifecycle._read(self.lifecycle_root, "receipts/armed.json"))
            self._gate_stage = "GATE_PUBLICATION"
            self._armed_claimed = True
            _publish(self.live_root, "armed-stop.json", {**self._common(child), "elapsed_ms": self._elapsed(),
                "running_response_sha256": running_sha, "lifecycle_armed_sha256": original_armed_sha})
            self.live_counters["armed_stops"] += 1
            return True

    def _monitor(self):
        while not self._monitor_stop.wait(0.02):
            with self.lock:
                entry = self.children.get(self._live_id)
                if self._closed or entry is None:
                    return
                child = entry[0]
                try:
                    if child.poll() is not None:
                        return
                except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                    self._fail_gate("OWNERSHIP", error, child)
                    # A failed process-status probe cannot establish continuing
                    # owned liveness. Do not probe or signal again to qualify it;
                    # the unchanged child's own 30-second bound remains in force.
                    return
                if time.monotonic() >= self._deadline:
                    try:
                        self._owned(self._live_id)
                    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                        self._fail_gate("DEADLINE", error, child)
                        return
                    try:
                        _publish(self.live_root, "deadline.json", {**self._common(child), "elapsed_ms": self._elapsed()})
                    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                        self._fail_gate("DEADLINE", error, child)
                    self._lifecycle_closing = True
                    try:
                        self.stop(self._live_id)
                    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                        self._fail_gate("CONTAINMENT", error, child)
                    finally:
                        self._lifecycle_closing = False
                    return
                if self._gate_failed or self._stop_claimed:
                    continue
                try:
                    self.poll_gate()
                except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                    self._fail_gate(self._gate_stage, error, child)

    def stop(self, identifier):
        with self.lock:
            if self._lifecycle_closing:
                child = self._owned(identifier)
                require(not self._containment_claimed, "ALREADY_ATTEMPTED")
                self._containment_claimed = True
                self.live_counters["containment_stops"] += 1
                try:
                    _publish(self.live_root, "containment.json", {**self._common(child), "elapsed_ms": self._elapsed(),
                        "reason": "DEADLINE" if _json(self.live_root, "receipts/deadline.json", True) is not None else "SERVER_CLOSE"})
                except (Refused, OSError, ValueError, TypeError):
                    pass
                return super().stop(identifier)
            require(not self.read_only and not self._stop_claimed, "ALREADY_ATTEMPTED")
            require(not self._gate_failed, "STOP_UNARMED")
            child = self._owned(identifier)
            require(time.monotonic() < self._deadline, "EXPIRED")
            # A first Running response can precede the original worker's short
            # handshake. Read readiness for at most one second, without another
            # Run, Stop signal, or diagnostic publication retry.
            require(_json(self.live_root, "receipts/running-response.json", True) is not None, "STOP_UNARMED")
            ready_until = min(self._deadline, time.monotonic() + 1)
            while not armed_checkpoint(self.live_root, identifier) and time.monotonic() < ready_until:
                try:
                    self.poll_gate()
                except (Refused, OSError, ValueError, TypeError, KeyError) as error:
                    self._fail_gate(self._gate_stage, error, child)
                    raise Refused("LIVE_STOP_STOP_UNARMED") from None
                if armed_checkpoint(self.live_root, identifier):
                    break
                self._owned(identifier)
                time.sleep(0.02)
            require(armed_checkpoint(self.live_root, identifier), "STOP_UNARMED")
            child = self._owned(identifier)
            require(time.monotonic() < self._deadline, "EXPIRED")
            self._stop_claimed = True
            intent = {**self._common(child), "elapsed_ms": self._elapsed(),
                      "armed_stop_sha256": sha(_read(self.live_root, "receipts/armed-stop.json"))}
            _publish(self.live_root, "stop-intent.json", intent)
            self.live_counters["explicit_stops"] += 1
            result = super().stop(identifier)
            _publish(self.live_root, "stop-return.json", {**intent, "state": result["state"]})
            return result

    def close(self):
        self._monitor_stop.set()
        result = super().close()
        if self._monitor_thread is not None and self._monitor_thread is not threading.current_thread():
            self._monitor_thread.join(timeout=1)
        return result


def offline_handler(manager, token, origin, counters):
    require(isinstance(manager, LiveStopManager) and origin == "http://127.0.0.1:" + str(PORT), "ORIGIN")
    normal = base.offline_handler(manager, token, origin, counters)
    class Handler(normal):
        def send(self, code, raw, kind="application/json; charset=utf-8", attachment=None):
            result = super().send(code, raw, kind, attachment)
            path = urlsplit(self.path).path
            if (self.command == "GET" and code == 200 and self.path == path and path.startswith("/api/run/")
                    and base.ID.fullmatch(path[len("/api/run/"):]) is not None
                    and self.headers.get("Host") == origin.split("://", 1)[1]
                    and hmac.compare_digest(self.headers.get("X-Workbench-Token", ""), token)):
                try:
                    value = parse(raw)
                    if type(value) is dict and value.get("state") == "RUNNING":
                        manager.running_response(path[len("/api/run/"):], raw)
                except (Refused, OSError, ValueError, TypeError, KeyError):
                    pass
            return result
    return Handler


def live_stop_report(root):
    control = validate_fixture(root)
    names = _catalog(root, control)
    original = lifecycle.lifecycle_report(root / "lifecycle")
    identifier = original["run_id"]
    result = {"version": 1, "format": FORMAT, "fixture_id": control["fixture_id"], "run_id": identifier,
        "status": "UNKNOWN", "outcome": "UNKNOWN", "lifecycle": original,
        "running_response": "running-response.json" in names, "armed_stop": "armed-stop.json" in names,
        "explicit_stop": "stop-intent.json" in names and "stop-return.json" in names,
        "containment": "containment.json" in names, "browser_observed": False, "notes": []}
    result["counts"] = {"running_responses": int(result["running_response"]), "armed_stops": int(result["armed_stop"]),
                        "explicit_stops": int("stop-intent.json" in names), "containment_stops": int(result["containment"])}
    if "start-intent.json" not in names:
        result["notes"].append("NOT_ATTEMPTED")
        return result
    try:
        require(not any(name.endswith(".next") for name in names), "INCOMPLETE")
        require(not {"deadline.json", "containment.json", "gate-failed.json"} & set(names), "CONTAINMENT")
        require(original["status"] == "VERIFIED" and original["outcome"] == "OWNED_STOP" and armed_checkpoint(root, identifier), "EVIDENCE")
        running = _json(root, "receipts/running-response.json")
        armed = _json(root, "receipts/armed-stop.json")
        intent = _json(root, "receipts/stop-intent.json")
        returned = _json(root, "receipts/stop-return.json")
        spawned = lifecycle._json(root / "lifecycle", "receipts/spawned.json")
        require(all(value["id"] == identifier and value["pid"] == spawned["pid"] for value in (running, armed, intent, returned))
                and intent["armed_stop_sha256"] == sha(_read(root, "receipts/armed-stop.json"))
                and returned == {**intent, "state": "STOP_REQUESTED"}
                and running["elapsed_ms"] <= armed["elapsed_ms"] <= intent["elapsed_ms"] <= RUN_SECONDS * 1000, "EVIDENCE")
        result.update(status="VERIFIED", outcome="OWNED_STOP")
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError):
        result["notes"].append("INCOMPLETE_EVIDENCE")
    if "deadline.json" in names: result["notes"].append("EXPIRED")
    if "containment.json" in names: result["notes"].append("CONTAINMENT_STOP")
    if "gate-failed.json" in names: result["notes"].append("GATE_FAILED")
    result["notes"] = sorted(set(result["notes"]))
    require(len(canonical(result)) <= 65536, "LIMIT")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "serve", "inspect"):
        item = sub.add_parser(name); item.add_argument("--work-dir", type=Path, required=True)
        if name == "serve": item.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    if args.command == "init":
        print(canonical(initialize(args.work_dir)).decode(), end=""); return 0
    if args.command == "inspect":
        print(canonical(live_stop_report(args.work_dir)).decode(), end=""); return 0
    require(args.port == PORT, "PORT")
    manager = LiveStopManager(args.work_dir)
    session = secrets.token_hex(8)
    _publish(args.work_dir, "session-" + session + ".json", {"version": 1, "format": FORMAT,
        "fixture_id": manager.live_control["fixture_id"], "control_sha256": manager.live_control_sha256,
        "pid": os.getpid(), "port": PORT, "read_only": manager.read_only})
    server = None
    def stopped(*_): raise KeyboardInterrupt
    previous_term, previous_int = signal.signal(signal.SIGTERM, stopped), signal.signal(signal.SIGINT, stopped)
    try:
        origin = "http://127.0.0.1:" + str(PORT)
        server = ThreadingHTTPServer(("127.0.0.1", PORT), offline_handler(manager, secrets.token_urlsafe(32), origin, manager.counters))
        server.daemon_threads = True
        print(canonical({"url": origin, "pid": os.getpid(), "read_only": manager.read_only, "run_seconds": RUN_SECONDS,
                         "token_logged": False}).decode(), end="", flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None: server.server_close()
        manager.close()
        _publish(args.work_dir, "shutdown-" + session + ".json", {"version": 1, "format": FORMAT,
            "fixture_id": manager.live_control["fixture_id"], "port": PORT, "listener_closed": True,
            "read_only": manager.read_only, "counters": manager.counters,
            "lifecycle_counters": manager.lifecycle_counters, "live_counters": manager.live_counters})
        signal.signal(signal.SIGTERM, previous_term); signal.signal(signal.SIGINT, previous_int)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print('{"status":"REFUSED","reason":"LIVE_STOP_REFUSED"}', flush=True)
        raise SystemExit(2) from None
