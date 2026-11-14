"""Deterministic supervisor/worker protocol tests using no processes or pipes.

The clock, child, selector and byte channels below are in-memory fakes. Actual
blocked-read/slow-trickle subprocess acceptance is a separate qualification.
"""

import io
import json
import selectors
import subprocess
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import launch
import preflight_worker as worker
from agent import Refused
from test_model_preflight import MODEL, OTHER, OfflineCase, QUERY, payload


FORMAT = "outlands-preflight-worker-v1"
WORKER = "PROVIDER_PREFLIGHT_WORKER"
DEADLINE = "PROVIDER_PREFLIGHT_DEADLINE"
PASS_RESULT = {"installed_models": 1, "loaded_approved_models": 0, "inference_requests": 0}


def frame(**fields):
    return (json.dumps({"format": FORMAT, **fields}, separators=(",", ":")) + "\n").encode()


def passed(result=None):
    return frame(kind="final", status="PASS", result=PASS_RESULT if result is None else result)


def primary(reason="MODEL_NOT_INSTALLED"):
    return frame(kind="primary", reason=reason)


def refused(reason="MODEL_NOT_INSTALLED"):
    return frame(kind="final", status="REFUSED", reason=reason)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now = round(self.now + seconds, 12)


class Pipe:
    def __init__(self, fd):
        self.fd = fd
        self.closed = False
        self.close_calls = 0
        self.close_error = None
        self.close_action = None

    def fileno(self):
        return self.fd

    def close(self):
        self.close_calls += 1
        if self.close_action is not None:
            self.close_action()
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


class Child:
    def __init__(self, clock, exit_at=0.01, exit_code=0):
        self.clock = clock
        self.exit_at = exit_at
        self.exit_code = exit_code
        self.stdin = Pipe(101)
        self.stdout = Pipe(102)
        self.pid = 12345  # Invented; never passed to an OS operation.
        self.returncode = None
        self.poll_calls = 0
        self.kill_calls = 0
        self.wait_timeouts = []
        self.killed = False
        self.poll_error = None
        self.kill_error = None
        self.wait_error = None
        self.wait_delay = 0.0

    def poll(self):
        self.poll_calls += 1
        if self.poll_error is not None:
            raise self.poll_error
        if self.returncode is not None:
            return self.returncode
        if self.exit_at is not None and self.clock.now >= self.exit_at:
            self.returncode = self.exit_code
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        if self.kill_error is not None:
            raise self.kill_error
        self.killed = True

    def wait(self, timeout=None):
        if timeout is None or not 0 < timeout <= 1.000000001:
            raise AssertionError("unbounded or invalid reap wait")
        self.wait_timeouts.append(timeout)
        if self.wait_error is not None:
            self.clock.advance(timeout)
            raise self.wait_error
        self.clock.advance(min(self.wait_delay, timeout))
        if self.killed:
            self.returncode = -9
        elif self.poll() is None:
            self.clock.advance(timeout)
            raise subprocess.TimeoutExpired("invented worker", timeout)
        return self.returncode


class Channels:
    def __init__(self, clock, child, chunks):
        self.clock = clock
        self.child = child
        self.chunks = list(chunks)
        self.writes = []
        self.read_limits = []
        self.write_limit = None
        self.read_error = None
        self.write_error = None

    def read(self, fd, limit):
        if fd != self.child.stdout.fd or not 0 < limit <= 4097:
            raise AssertionError("unexpected read descriptor or bound")
        self.read_limits.append(limit)
        if self.read_error is not None:
            raise self.read_error
        if not self.chunks or self.chunks[0][0] > self.clock.now:
            raise BlockingIOError()
        at, raw = self.chunks.pop(0)
        if len(raw) > limit:
            self.chunks.insert(0, (at, raw[limit:]))
            raw = raw[:limit]
        return raw

    def write(self, fd, raw):
        if fd != self.child.stdin.fd or not raw:
            raise AssertionError("unexpected write descriptor or empty packet")
        if self.write_error is not None:
            raise self.write_error
        count = len(raw) if self.write_limit is None else min(len(raw), self.write_limit)
        self.writes.append(bytes(raw[:count]))
        return count


class Selector:
    def __init__(self, clock, channels):
        self.clock = clock
        self.channels = channels
        self.keys = {}
        self.select_timeouts = []
        self.close_calls = 0
        self.select_error = None
        self.close_error = None

    def register(self, fileobj, events, data=None):
        fd = fileobj.fileno()
        if fd in self.keys:
            raise AssertionError("duplicate selector registration")
        key = selectors.SelectorKey(fileobj, fd, events, data)
        self.keys[fd] = key
        return key

    def unregister(self, fileobj):
        return self.keys.pop(fileobj.fileno())

    def select(self, timeout=None):
        if timeout is None or not 0 < timeout <= 0.050000001:
            raise AssertionError("unbounded selector wait")
        self.select_timeouts.append(timeout)
        if len(self.select_timeouts) > 3000:
            raise AssertionError("supervisor did not honor fake deadline")
        if self.select_error is not None:
            raise self.select_error
        writable = [key for key in self.keys.values() if key.data == "stdin"]
        readable = [key for key in self.keys.values() if key.data == "stdout"]
        due = self.channels.chunks[0][0] if self.channels.chunks else None
        if writable:
            return [(key, selectors.EVENT_WRITE) for key in writable] + [
                (key, selectors.EVENT_READ) for key in readable if due is not None and due <= self.clock.now]
        if readable and due is not None and due <= self.clock.now + timeout:
            self.clock.now = max(self.clock.now, due)
            return [(key, selectors.EVENT_READ) for key in readable]
        self.clock.advance(timeout)
        return []

    def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class SupervisorTests(OfflineCase):
    def setUp(self):
        super().setUp()
        for target in ("os.kill", "os.killpg", "os.pipe", "os.pipe2"):
            forbidden = self.stack.enter_context(patch(target, side_effect=AssertionError("real signals/pipes forbidden")))
            self.denied.append(forbidden)

    @contextmanager
    def rig(self, chunks=None, exit_at=0.01, exit_code=0, spawn_delay=0.0, spawn_error=None):
        clock = Clock()
        child = Child(clock, exit_at, exit_code)
        channels = Channels(clock, child, [(0.01, passed()), (0.01, b"")] if chunks is None else chunks)
        selector = Selector(clock, channels)
        def spawn(*args, **kwargs):
            clock.advance(spawn_delay)
            if spawn_error is not None:
                raise spawn_error
            return child
        with ExitStack() as stack:
            factory = stack.enter_context(patch("preflight_worker.subprocess.Popen", side_effect=spawn))
            select_factory = stack.enter_context(patch("preflight_worker.selectors.DefaultSelector", return_value=selector))
            stack.enter_context(patch("preflight_worker.time.monotonic", side_effect=clock.monotonic))
            stack.enter_context(patch("preflight_worker.os.read", side_effect=channels.read))
            stack.enter_context(patch("preflight_worker.os.write", side_effect=channels.write))
            blocking = stack.enter_context(patch("preflight_worker.os.set_blocking"))
            yield SimpleNamespace(clock=clock, child=child, channels=channels, selector=selector,
                                  factory=factory, select_factory=select_factory, blocking=blocking)
            self.assertLessEqual(factory.call_count, 1)
            self.assertLessEqual(child.kill_calls, 1)
            self.assertLessEqual(len(child.wait_timeouts), 1)
            self.assertTrue(all(0 < value <= 1.000000001 for value in child.wait_timeouts))
            self.assertLessEqual(selector.close_calls, 1)

    def refusal(self, code, models=None):
        with self.assertRaises(Refused) as caught:
            worker.supervise([MODEL] if models is None else models)
        self.assertEqual(str(caught.exception), code)
        diagnostics = caught.exception.preflight_diagnostics
        self.assertEqual(set(diagnostics), {"deadline_expired", "forced_stop", "worker_reaped"})
        self.assertTrue(all(type(value) is bool for value in diagnostics.values()))
        return diagnostics

    def assert_spawn(self, rig):
        rig.factory.assert_called_once()
        args, kwargs = rig.factory.call_args
        command = args[0]
        self.assertEqual(command[:3], [sys.executable, "-I", "-B"])
        self.assertEqual(command[3:], [str(Path(worker.__file__).resolve()), "--worker"])
        self.assertNotIn(MODEL, command)
        self.assertEqual(kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(kwargs["bufsize"], 0)
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(kwargs["cwd"], Path(worker.__file__).resolve().parent)
        self.assertEqual(kwargs["env"], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})

    def test_success_requires_final_eof_and_observed_exit(self):
        with self.rig() as rig:
            self.assertEqual(worker.supervise([MODEL]), PASS_RESULT)
            self.assert_spawn(rig)
            self.assertEqual(json.loads(b"".join(rig.channels.writes)), {"format": FORMAT, "models": [MODEL]})
            self.assertEqual(rig.child.kill_calls, 0)
            self.assertEqual(rig.child.wait_timeouts, [])
            self.assertTrue(rig.child.stdin.closed and rig.child.stdout.closed)

    def test_final_before_exit_cannot_pass_or_trigger_retry(self):
        with self.rig(chunks=[(0.01, passed()), (0.01, b"")], exit_at=None) as rig:
            diagnostic = self.refusal(DEADLINE)
            self.assertEqual(diagnostic, {"deadline_expired": True, "forced_stop": True, "worker_reaped": True})
            self.assertEqual(rig.child.kill_calls, 1)
            self.assertEqual(rig.clock.now, 10.0)

    def test_just_before_deadline_can_pass(self):
        with self.rig(chunks=[(9.999, passed()), (9.999, b"")], exit_at=9.999):
            self.assertEqual(worker.supervise([MODEL]), PASS_RESULT)

    def test_exact_deadline_wins_even_when_exit_and_result_are_visible(self):
        with self.rig(chunks=[(10.0, passed()), (10.0, b"")], exit_at=10.0) as rig:
            diagnostic = self.refusal(DEADLINE)
            self.assertTrue(diagnostic["deadline_expired"])
            self.assertTrue(diagnostic["worker_reaped"])
            self.assertEqual(rig.child.kill_calls, 0)

    def test_late_spawn_gets_no_model_input(self):
        for delay in (10.0, 12.0):
            with self.subTest(delay=delay), self.rig(spawn_delay=delay, chunks=[], exit_at=None) as rig:
                diagnostic = self.refusal(DEADLINE)
                self.assertEqual(rig.channels.writes, [])
                self.assertEqual(rig.blocking.call_count, 0)
                rig.select_factory.assert_not_called()
                self.assertTrue(diagnostic["forced_stop"] and diagnostic["worker_reaped"])

    def test_provisional_success_without_eof_is_not_accepted(self):
        with self.rig(chunks=[(0.01, passed())], exit_at=0.01):
            self.assertTrue(self.refusal(DEADLINE)["deadline_expired"])

    def test_pass_with_nonzero_or_untyped_exit_is_worker_failure(self):
        for exit_code in (1, 2, -9, True, 0.0, "0"):
            with self.subTest(exit_code=exit_code), self.rig(exit_code=exit_code):
                diagnostic = self.refusal(WORKER)
                self.assertEqual(diagnostic, {"deadline_expired": False, "forced_stop": False, "worker_reaped": True})

    def test_complete_refusal_requires_primary_and_matching_exit(self):
        raw = primary() + refused()
        with self.rig(chunks=[(0.01, raw), (0.01, b"")], exit_code=2):
            self.assertEqual(self.refusal("MODEL_NOT_INSTALLED"),
                             {"deadline_expired": False, "forced_stop": False, "worker_reaped": True})

    def test_primary_survives_cleanup_stall_and_owned_stop(self):
        with self.rig(chunks=[(0.01, primary())], exit_at=None) as rig:
            diagnostic = self.refusal("MODEL_NOT_INSTALLED")
            self.assertEqual(diagnostic, {"deadline_expired": True, "forced_stop": True, "worker_reaped": True})
            self.assertEqual(rig.child.kill_calls, 1)

    def test_known_primary_and_unexpected_exit_remains_refusal(self):
        with self.rig(chunks=[(0.01, primary()), (0.01, b"")], exit_code=1):
            self.assertEqual(self.refusal("MODEL_NOT_INSTALLED"),
                             {"deadline_expired": False, "forced_stop": False, "worker_reaped": True})

    def test_primary_cannot_be_overridden_by_pass_or_malformed_stream(self):
        for raw in (primary() + passed(), primary() + b"malformed\n", primary() + refused(OTHER)):
            with self.subTest(raw_length=len(raw)), self.rig(chunks=[(0.01, raw), (0.01, b"")], exit_code=2):
                self.refusal(WORKER)

    def test_invalid_frame_schemas_are_not_results(self):
        invalid = [
            b"[]\n", frame(kind="unknown"), frame(kind="final", status="OTHER", reason="MODEL_NOT_INSTALLED"),
            frame(kind="primary", reason="invented-private-text"), frame(kind="primary", reason=DEADLINE),
            frame(kind="primary", reason="MODEL_NOT_INSTALLED", extra=False),
            frame(kind="final", status="PASS", result=PASS_RESULT, extra=False), refused(),
            primary() + primary() + refused(), passed() + passed(), primary() + refused() + b"{}\n",
        ]
        for index, raw in enumerate(invalid):
            with self.subTest(case=index), self.rig(chunks=[(0.01, raw), (0.01, b"")]):
                self.refusal(WORKER)

    def test_invalid_json_utf8_duplicate_keys_and_constants_are_refused(self):
        invalid = [b"{\n", b"\xff\n", b'{"format":"a","format":"b"}\n',
                   b'{"format":"a","other":NaN}\n', b'{"format":"a","other":Infinity}\n',
                   b'{"other":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}\n"]
        for index, raw in enumerate(invalid):
            with self.subTest(case=index), self.rig(chunks=[(0.01, raw), (0.01, b"")]):
                self.refusal(WORKER)

    def test_partial_last_line_blank_or_trailing_bytes_are_refused(self):
        for raw in (passed().rstrip(b"\n"), passed() + b"\n", passed() + b"extra"):
            with self.subTest(raw_length=len(raw)), self.rig(chunks=[(0.01, raw), (0.01, b"")]):
                self.refusal(WORKER)

    def test_output_limit_accepts_exact_bound_and_refuses_one_byte_more(self):
        raw = passed().rstrip(b"\n")
        for extra in (0, 1):
            padded = raw + b" " * (4096 + extra - len(raw) - 1) + b"\n"
            with self.subTest(extra=extra), self.rig(chunks=[(0.01, padded), (0.01, b"")]) as rig:
                if extra:
                    self.refusal(WORKER)
                else:
                    self.assertEqual(worker.supervise([MODEL]), PASS_RESULT)
                self.assertTrue(all(limit <= 4097 for limit in rig.channels.read_limits))

    def test_result_counts_have_exact_types_and_configured_bounds(self):
        bad = [
            {**PASS_RESULT, "installed_models": True}, {**PASS_RESULT, "installed_models": 2},
            {**PASS_RESULT, "installed_models": 0}, {**PASS_RESULT, "loaded_approved_models": -1},
            {**PASS_RESULT, "loaded_approved_models": 2}, {**PASS_RESULT, "loaded_approved_models": 0.0},
            {**PASS_RESULT, "inference_requests": True}, {**PASS_RESULT, "inference_requests": 1},
            {**PASS_RESULT, "extra": 0}, {"installed_models": 1, "inference_requests": 0},
        ]
        for index, value in enumerate(bad):
            with self.subTest(case=index), self.rig(chunks=[(0.01, passed(value)), (0.01, b"")]):
                self.refusal(WORKER)

    def test_fragmented_output_and_partial_input_writes_preserve_protocol(self):
        raw = passed()
        chunks = [(0.01, bytes([byte])) for byte in raw] + [(0.01, b"")]
        with self.rig(chunks=chunks) as rig:
            rig.channels.write_limit = 7
            self.assertEqual(worker.supervise([MODEL]), PASS_RESULT)
            self.assertGreater(len(rig.channels.writes), 1)
            self.assertEqual(json.loads(b"".join(rig.channels.writes)), {"format": FORMAT, "models": [MODEL]})

    def test_spawn_failure_has_no_child_or_signal(self):
        with self.rig(spawn_error=OSError("invented private spawn detail")) as rig:
            self.assertEqual(self.refusal(WORKER),
                             {"deadline_expired": False, "forced_stop": False, "worker_reaped": False})
            self.assertEqual(rig.child.kill_calls, 0)
            self.assertEqual(rig.child.poll_calls, 0)
            self.assertEqual(rig.channels.writes, [])

    def test_read_write_and_selector_errors_are_finite_owned_failures(self):
        for operation in ("read", "write", "select"):
            with self.subTest(operation=operation), self.rig(exit_at=None) as rig:
                if operation == "read":
                    rig.channels.read_error = OSError("invented private read detail")
                elif operation == "write":
                    rig.channels.write_error = BrokenPipeError("invented private write detail")
                else:
                    rig.selector.select_error = OSError("invented private selector detail")
                diagnostic = self.refusal(WORKER)
                self.assertTrue(diagnostic["forced_stop"] and diagnostic["worker_reaped"])
                self.assertEqual(rig.child.kill_calls, 1)

    def test_stop_wait_timeout_is_bounded_and_never_success(self):
        with self.rig(chunks=[], exit_at=None) as rig:
            rig.child.wait_error = subprocess.TimeoutExpired("invented worker", 1)
            diagnostic = self.refusal(DEADLINE)
            self.assertEqual(diagnostic, {"deadline_expired": True, "forced_stop": True, "worker_reaped": False})
            self.assertEqual(rig.child.kill_calls, 1)
            self.assertEqual(len(rig.child.wait_timeouts), 1)
            self.assertEqual(rig.clock.now, 11.0)

    def test_primary_remains_truthful_if_owned_worker_cannot_be_reaped(self):
        with self.rig(chunks=[(0.01, primary())], exit_at=None) as rig:
            rig.child.wait_error = subprocess.TimeoutExpired("invented worker", 1)
            diagnostic = self.refusal("MODEL_NOT_INSTALLED")
            self.assertEqual(diagnostic, {"deadline_expired": True, "forced_stop": True, "worker_reaped": False})

    def test_kill_failure_does_not_claim_worker_reaped(self):
        with self.rig(chunks=[], exit_at=None) as rig:
            rig.child.kill_error = OSError("invented private signal detail")
            rig.child.wait_error = subprocess.TimeoutExpired("invented worker", 1)
            diagnostic = self.refusal(DEADLINE)
            self.assertFalse(diagnostic["worker_reaped"])
            self.assertEqual(rig.child.kill_calls, 1)

    def test_poll_failure_never_qualifies_unknown_liveness(self):
        with self.rig(exit_at=None) as rig:
            rig.child.poll_error = OSError("invented private poll detail")
            diagnostic = self.refusal(WORKER)
            self.assertFalse(diagnostic["worker_reaped"])

    def test_parent_cleanup_failure_prevents_success(self):
        for target in ("selector", "stdout"):
            with self.subTest(target=target), self.rig() as rig:
                if target == "selector":
                    rig.selector.close_error = OSError("invented cleanup detail")
                else:
                    rig.child.stdout.close_error = OSError("invented cleanup detail")
                diagnostic = self.refusal("PROVIDER_PREFLIGHT_CLEANUP")
                self.assertTrue(diagnostic["worker_reaped"])

    def test_deadline_is_checked_after_parent_cleanup(self):
        with self.rig() as rig:
            rig.child.stdout.close_action = lambda: rig.clock.advance(10.0)
            diagnostic = self.refusal(DEADLINE)
            self.assertEqual(diagnostic, {"deadline_expired": True, "forced_stop": False, "worker_reaped": True})

    def test_input_close_failure_is_not_retried_or_accepted(self):
        with self.rig(exit_at=None) as rig:
            rig.child.stdin.close_error = OSError("invented input cleanup detail")
            self.refusal(WORKER)
            self.assertEqual(rig.child.stdin.close_calls, 1)
            self.assertEqual(rig.child.stdout.close_calls, 1)

    def test_invalid_models_refuse_before_child_creation(self):
        for value in (None, [], MODEL, [MODEL, MODEL], ["x" * 97]):
            with self.subTest(value=value), self.rig() as rig:
                with self.assertRaises(Refused) as caught:
                    launch.provider(value)
                self.assertEqual(str(caught.exception), "PROVIDER_PREFLIGHT_SHAPE")
                rig.factory.assert_not_called()

    def test_public_bridge_uses_fixed_budget_without_query_in_parent(self):
        self.assertEqual(worker.supervise.__defaults__, (10.0, 1.0))
        self.assertIs(launch.supervise, worker.supervise)
        with patch("launch.supervise", return_value=PASS_RESULT) as supervise, \
                patch("launch._provider_query", side_effect=AssertionError("HTTP query must stay in child")):
            self.assertEqual(launch.provider([MODEL]), PASS_RESULT)
        supervise.assert_called_once()
        args, kwargs = supervise.call_args
        self.assertEqual(args, ([MODEL],))
        self.assertLessEqual(set(kwargs), {"seconds", "stop_seconds"})
        self.assertEqual(kwargs.get("seconds", worker.supervise.__defaults__[0]), 10.0)
        self.assertEqual(kwargs.get("stop_seconds", worker.supervise.__defaults__[1]), 1.0)


class PrimaryNotificationTests(OfflineCase):
    def test_primary_is_finite_and_published_before_failing_response_cleanup(self):
        cases = [({"statuses": {"/api/tags": 503}}, "PROVIDER_PREFLIGHT_HTTP"),
                 ({"tags": b"{"}, "PROVIDER_PREFLIGHT_SHAPE"),
                 ({"tags": payload([])}, "MODEL_NOT_INSTALLED"),
                 ({"faults": {("read", "/api/tags"): OSError("invented private detail")}}, "PROVIDER_PREFLIGHT_CONNECTION")]
        for options, expected in cases:
            with self.subTest(expected=expected), self.transport(**options) as (connection, _):
                notices = []
                def notify(reason):
                    notices.append(reason)
                    connection.events.append(("primary", reason))
                with self.assertRaises(Refused) as caught:
                    QUERY([MODEL], notify_primary=notify)
                self.assertEqual(str(caught.exception), expected)
                self.assertEqual(notices, [expected])
                self.assertLess(connection.events.index(("primary", expected)), connection.events.index(("response_close", "/api/tags")))

    def test_cleanup_secondary_cannot_publish_over_primary(self):
        faults = {("response_close", "/api/tags"): OSError("invented secondary"),
                  ("connection_close", None): OSError("invented secondary")}
        with self.transport(tags=payload([]), faults=faults):
            notices = []
            with self.assertRaises(Refused) as caught:
                QUERY([MODEL], notify_primary=notices.append)
            self.assertEqual(str(caught.exception), "MODEL_NOT_INSTALLED")
            self.assertEqual(notices, ["MODEL_NOT_INSTALLED"])


class WorkerProtocolTests(OfflineCase):
    def invoke_worker(self, raw, query):
        emitted = []
        stdin = SimpleNamespace(buffer=io.BytesIO(raw))
        stdout = SimpleNamespace(fileno=lambda: 201)
        def write(fd, data):
            self.assertEqual(fd, 201)
            emitted.append(bytes(data))
            return len(data)
        with patch("preflight_worker.sys.stdin", stdin), patch("preflight_worker.sys.stdout", stdout), \
                patch("preflight_worker.sys.path", list(sys.path)), patch("preflight_worker.os.write", side_effect=write), \
                patch("launch._provider_query", side_effect=query) as queried:
            code = worker.worker_main()
        return code, [json.loads(raw) for raw in emitted], queried

    def test_worker_valid_input_emits_one_typed_final(self):
        request = json.dumps({"format": FORMAT, "models": [MODEL]}).encode()
        code, frames, queried = self.invoke_worker(request, lambda models, notify_primary: PASS_RESULT)
        self.assertEqual(code, 0)
        self.assertEqual(frames, [{"format": FORMAT, "kind": "final", "status": "PASS", "result": PASS_RESULT}])
        self.assertEqual(queried.call_args.args, ([MODEL],))

    def test_worker_primary_precedes_refused_final(self):
        def query(models, notify_primary):
            notify_primary("MODEL_NOT_INSTALLED")
            raise Refused("MODEL_NOT_INSTALLED")
        request = json.dumps({"format": FORMAT, "models": [MODEL]}).encode()
        code, frames, _ = self.invoke_worker(request, query)
        self.assertEqual(code, 2)
        self.assertEqual([row["kind"] for row in frames], ["primary", "final"])
        self.assertEqual([row["reason"] for row in frames], ["MODEL_NOT_INSTALLED"] * 2)

    def test_worker_invalid_or_oversized_input_never_calls_query(self):
        bad = [b"{", b"\xff", b" " * 1025, b"[]", b'{"format":"a","format":"b"}',
               json.dumps({"format": FORMAT, "models": []}).encode(),
               json.dumps({"format": FORMAT, "models": [MODEL], "extra": False}).encode()]
        for index, raw in enumerate(bad):
            with self.subTest(case=index):
                code, frames, queried = self.invoke_worker(raw, lambda *args, **kwargs: self.fail("invalid input reached query"))
                self.assertEqual(code, 2)
                queried.assert_not_called()
                self.assertEqual([row["reason"] for row in frames], ["PROVIDER_PREFLIGHT_SHAPE"] * 2)

    def test_unexpected_child_exception_never_exposes_exception_text(self):
        def query(models, notify_primary):
            raise RuntimeError("invented private exception detail")
        raw = json.dumps({"format": FORMAT, "models": [MODEL]}).encode()
        code, frames, _ = self.invoke_worker(raw, query)
        self.assertNotEqual(code, 0)
        self.assertEqual(frames[0], {"format": FORMAT, "kind": "primary", "reason": WORKER})
        self.assertNotIn("invented private exception detail", json.dumps(frames))

    def test_unexpected_error_after_primary_does_not_emit_false_final(self):
        def query(models, notify_primary):
            notify_primary("MODEL_NOT_INSTALLED")
            raise RuntimeError("invented private cleanup failure")
        raw = json.dumps({"format": FORMAT, "models": [MODEL]}).encode()
        code, frames, _ = self.invoke_worker(raw, query)
        self.assertEqual(code, 1)
        self.assertEqual(frames, [{"format": FORMAT, "kind": "primary", "reason": "MODEL_NOT_INSTALLED"}])


if __name__ == "__main__":
    unittest.main()
