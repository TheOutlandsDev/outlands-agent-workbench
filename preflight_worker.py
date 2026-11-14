"""Bounded supervision of one metadata-only provider query in an owned worker.

The work deadline includes both GETs, validation and normal cleanup. Process
creation and OS scheduling are not hard-real-time guarantees. Forced stop has
one separate bounded reap grace and targets only the Popen child created here.
"""

import json
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time

WORK_SECONDS = 10.0
STOP_SECONDS = 1.0
MAX_INPUT_BYTES = 1024
MAX_OUTPUT_BYTES = 4096
FORMAT = "outlands-preflight-worker-v1"
CORE_REASONS = frozenset({"MODEL_NOT_INSTALLED", "OTHER_MODEL_LOADED", "PROVIDER_PREFLIGHT_HTTP",
    "PROVIDER_PREFLIGHT_SHAPE", "PROVIDER_PREFLIGHT_LIMIT", "PROVIDER_PREFLIGHT_TIMEOUT",
    "PROVIDER_PREFLIGHT_CONNECTION", "PROVIDER_PREFLIGHT_PROTOCOL", "PROVIDER_PREFLIGHT_CLEANUP"})
WORKER_REASON = "PROVIDER_PREFLIGHT_WORKER"
DEADLINE_REASON = "PROVIDER_PREFLIGHT_DEADLINE"
_REASONS = CORE_REASONS | {WORKER_REASON}


class _WorkerError(Exception):
    pass


def _need(value):
    if not value:
        raise _WorkerError()


def _models(value):
    return (type(value) is list and 1 <= len(value) <= 8
            and all(type(name) is str and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", name) is not None for name in value)
            and len(set(value)) == len(value))


def _pairs(rows):
    value = {}
    for key, item in rows:
        _need(key not in value)
        value[key] = item
    return value


def _invalid_constant(_value):
    raise _WorkerError()


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _WorkerError() from None


def _encode(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _refuse(reason, diagnostics):
    from agent import Refused
    error = Refused(reason)
    error.preflight_diagnostics = dict(diagnostics)
    raise error


class _Frames:
    def __init__(self, configured_count):
        self.configured_count = configured_count
        self.total = 0
        self.pending = b""
        self.primary = None
        self.final = None
        self.count = 0

    def feed(self, raw):
        _need(type(raw) is bytes)
        self.total += len(raw)
        _need(self.total <= MAX_OUTPUT_BYTES)
        self.pending += raw
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            value = _json(line)
            self.count += 1
            _need(self.count <= 2 and type(value) is dict and value.get("format") == FORMAT and self.final is None)
            if value.get("kind") == "primary":
                _need(set(value) == {"format", "kind", "reason"} and self.primary is None
                      and type(value["reason"]) is str and value["reason"] in _REASONS)
                self.primary = value["reason"]
                continue
            _need(value.get("kind") == "final")
            if value.get("status") == "PASS":
                _need(set(value) == {"format", "kind", "status", "result"} and self.primary is None)
                result = value["result"]
                _need(type(result) is dict and set(result) == {"installed_models", "loaded_approved_models", "inference_requests"}
                      and all(type(item) is int for item in result.values())
                      and result["installed_models"] == self.configured_count
                      and 0 <= result["loaded_approved_models"] <= self.configured_count
                      and result["inference_requests"] == 0)
            else:
                _need(value.get("status") == "REFUSED" and set(value) == {"format", "kind", "status", "reason"}
                      and self.primary is not None and value["reason"] == self.primary)
            self.final = value

    def ended(self):
        _need(not self.pending)

    def outcome(self, returncode):
        self.ended()
        _need(type(returncode) is int)
        if self.final is None:
            if self.primary is not None and returncode != 0:
                return None, self.primary
            raise _WorkerError()
        if self.final["status"] == "PASS":
            _need(returncode == 0)
            return self.final["result"], None
        _need(returncode == 2)
        return None, self.primary


def _stop(child, stop_seconds, diagnostics):
    """One direct-child kill attempt and one shared finite reap deadline."""
    deadline = time.monotonic() + stop_seconds
    cleanup_failed = False
    try:
        code = child.poll()
    except (OSError, ValueError, subprocess.SubprocessError):
        code = None
        cleanup_failed = True
    if code is not None:
        diagnostics["worker_reaped"] = True
        return False
    diagnostics["forced_stop"] = True
    try:
        child.kill()
    except (OSError, ValueError, subprocess.SubprocessError):
        cleanup_failed = True
    remaining = deadline - time.monotonic()
    try:
        if remaining > 0:
            child.wait(timeout=remaining)
        diagnostics["worker_reaped"] = child.poll() is not None
    except (OSError, ValueError, subprocess.SubprocessError):
        cleanup_failed = True
    return cleanup_failed or not diagnostics["worker_reaped"]


def supervise(models, seconds=WORK_SECONDS, stop_seconds=STOP_SECONDS):
    """One worker, no retry. Optional smaller budgets support offline tests."""
    diagnostics = {"deadline_expired": False, "forced_stop": False, "worker_reaped": False}
    if not _models(models):
        _refuse("PROVIDER_PREFLIGHT_SHAPE", diagnostics)
    if not (type(seconds) in {int, float} and 0 < seconds <= WORK_SECONDS and math.isfinite(seconds)
            and type(stop_seconds) in {int, float} and 0 < stop_seconds <= STOP_SECONDS and math.isfinite(stop_seconds)):
        raise ValueError("invalid preflight budget")
    packet = _encode({"format": FORMAT, "models": models})
    _need(len(packet) <= MAX_INPUT_BYTES)
    frames = _Frames(len(models))
    child, selector, result, reason = None, None, None, None
    eof, input_done, input_close_attempted, invalid_stream = False, False, False, False
    deadline = time.monotonic() + seconds
    try:
        here = Path(__file__).resolve().parent
        child = subprocess.Popen([sys.executable, "-I", "-B", str(here / "preflight_worker.py"), "--worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            cwd=here, start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})
        # No model input or HTTP authorization is sent if process creation was late.
        if time.monotonic() >= deadline:
            diagnostics["deadline_expired"] = True
            reason = DEADLINE_REASON
        else:
            _need(child.stdin is not None and child.stdout is not None)
            os.set_blocking(child.stdin.fileno(), False)
            os.set_blocking(child.stdout.fileno(), False)
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stdin, selectors.EVENT_WRITE, "stdin")
            written = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    diagnostics["deadline_expired"] = True
                    reason = frames.primary or DEADLINE_REASON
                    break
                for key, _mask in selector.select(min(0.05, remaining)):
                    if time.monotonic() >= deadline:
                        break
                    if key.data == "stdin":
                        try:
                            count = os.write(key.fileobj.fileno(), packet[written:])
                        except BlockingIOError:
                            continue
                        _need(type(count) is int and 0 < count <= len(packet) - written)
                        written += count
                        if written == len(packet):
                            selector.unregister(child.stdin)
                            input_close_attempted = True
                            child.stdin.close()
                            input_done = True
                    elif key.data == "stdout":
                        try:
                            raw = os.read(key.fileobj.fileno(), MAX_OUTPUT_BYTES - frames.total + 1)
                        except BlockingIOError:
                            continue
                        if raw:
                            frames.feed(raw)
                        else:
                            _need(type(raw) is bytes)
                            frames.ended()
                            eof = True
                            selector.unregister(child.stdout)
                    else:
                        raise _WorkerError()
                # Deadline wins even when exit or a complete frame is already visible.
                if time.monotonic() >= deadline:
                    diagnostics["deadline_expired"] = True
                    reason = frames.primary or DEADLINE_REASON
                    break
                code = child.poll()
                if eof and code is not None:
                    _need(input_done)
                    result, reason = frames.outcome(code)
                    break
    except _WorkerError:
        invalid_stream = True
        reason = WORKER_REASON
    except (OSError, ValueError, subprocess.SubprocessError):
        reason = frames.primary or WORKER_REASON
    finally:
        try:
            if child is not None and _stop(child, stop_seconds, diagnostics) and reason is None:
                reason = frames.primary or "PROVIDER_PREFLIGHT_CLEANUP"
        finally:
            try:
                if selector is not None:
                    try:
                        selector.close()
                    except (OSError, ValueError):
                        reason = reason or frames.primary or "PROVIDER_PREFLIGHT_CLEANUP"
            finally:
                if child is not None:
                    for stream in (child.stdin, child.stdout):
                        if stream is not None and not (stream is child.stdin and input_close_attempted):
                            try:
                                stream.close()
                            except (OSError, ValueError):
                                reason = reason or frames.primary or "PROVIDER_PREFLIGHT_CLEANUP"
    if time.monotonic() >= deadline:
        diagnostics["deadline_expired"] = True
    if diagnostics["deadline_expired"] and not invalid_stream:
        reason = frames.primary or DEADLINE_REASON
    if reason is not None or result is None or not diagnostics["worker_reaped"]:
        _refuse(reason or "PROVIDER_PREFLIGHT_CLEANUP", diagnostics)
    return result


def _emit(value):
    raw = _encode(value)
    _need(len(raw) <= MAX_OUTPUT_BYTES)
    _need(os.write(sys.stdout.fileno(), raw) == len(raw))


def worker_main():
    """Fixed child entry; only validated metadata query, never doctor or tasks."""
    first = None
    def primary(reason):
        nonlocal first
        _need(reason in _REASONS)
        if first is None:
            first = reason
            _emit({"format": FORMAT, "kind": "primary", "reason": reason})
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        _need(len(raw) <= MAX_INPUT_BYTES)
        request = _json(raw)
        _need(type(request) is dict and set(request) == {"format", "models"}
              and request["format"] == FORMAT and _models(request["models"]))
    except (_WorkerError, OSError, ValueError):
        primary("PROVIDER_PREFLIGHT_SHAPE")
        _emit({"format": FORMAT, "kind": "final", "status": "REFUSED", "reason": first})
        return 2
    # -I excludes the script directory: add only this fixed trusted source root.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from agent import Refused
    from launch import _provider_query
    try:
        result = _provider_query(request["models"], notify_primary=primary)
    except Refused as error:
        primary(str(error) if str(error) in CORE_REASONS else WORKER_REASON)
        _emit({"format": FORMAT, "kind": "final", "status": "REFUSED", "reason": first})
        return 2
    except Exception:
        # This process boundary emits no exception text. Direct query tests retain
        # the original programming exception; the parent also checks this exit.
        primary(WORKER_REASON)
        return 1
    _need(first is None)
    _emit({"format": FORMAT, "kind": "final", "status": "PASS", "result": result})
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit(2)
    raise SystemExit(worker_main())
