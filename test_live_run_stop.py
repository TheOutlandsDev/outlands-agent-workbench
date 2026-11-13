"""Synthetic once-only live-stop fixtures; no native process or agent executes."""

import copy
import io
import json
import os
import signal
import tempfile
import unittest
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha
import offline_lifecycle as lifecycle
import offline_live_stop as live
from test_offline_workflow_integration import snapshot, start_request


TOKEN = "invented-live-stop-unit-token"
ORIGIN = "http://127.0.0.1:36231"
PRIVATE = "invented-private-live-stop-sentinel"


class FakeChild:
    """A local Python object whose PID is only synthetic receipt identity."""
    pid = os.getpid()
    def __init__(self):
        self.returncode = None
        self.terminations = 0
        self.kills = 0
    def poll(self): return self.returncode
    def terminate(self):
        self.terminations += 1
        self.returncode = 130
    def kill(self):
        self.kills += 1
        self.returncode = 137
    def wait(self, timeout=None):
        if self.returncode is None: raise AssertionError("fake child is not settled")
        return self.returncode


class InertThread:
    """No monitor or controller waiter runs concurrently in a fake-child test."""
    def __init__(self, *args, **kwargs): self.started = False
    def start(self): self.started = True
    def join(self, timeout=None): pass
    def is_alive(self): return False


@contextmanager
def live_fixture():
    fingerprint = {"directory": str(lifecycle.HERE), "files": {
        "offline_lifecycle.py": "1" * 64, "agent.py": "2" * 64, "workbench.py": "3" * 64,
        "offline_live_stop.py": "4" * 64}}
    with tempfile.TemporaryDirectory() as directory, patch.object(lifecycle, "_source_fingerprint", return_value=fingerprint) as source, \
            patch.object(lifecycle, "REAL_POPEN", side_effect=AssertionError("unit attempted native worker")) as spawn, \
            patch("workbench.process_stamp", return_value="invented-live-stop-process-stamp"), \
            patch("offline_live_stop.threading.Thread", InertThread):
        root = Path(directory) / "live-stop"
        control = live.initialize(root)
        manager = live.LiveStopManager(root)
        try:
            yield root, manager, control, source, spawn
        finally:
            # Fake objects may be settled for cleanup; no actual job is repaired.
            for child, _ in manager.children.values(): child.returncode = 130
            manager.close()


def memory_http(manager, token=TOKEN, origin=ORIGIN):
    """Exercise the actual new wrapper and unchanged normal handler in memory."""
    handler_type = live.offline_handler(manager, token, origin, manager.counters)
    def request(path, value=None, headers=None, raw=None, method="POST", output=None):
        raw = canonical(value) if raw is None and method == "POST" else b"" if raw is None else raw
        supplied = {"Host": origin.split("://", 1)[1], "X-Workbench-Token": token, "Origin": origin,
                    "Content-Type": "application/json", "Content-Length": str(len(raw))}
        duplicates = headers if isinstance(headers, list) else []
        if isinstance(headers, dict): supplied.update(headers)
        handler = handler_type.__new__(handler_type)
        handler.command, handler.path = method, path
        handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
        handler.headers = Message()
        for key, item in list(supplied.items()) + duplicates: handler.headers[key] = item
        handler.rfile, handler.wfile = io.BytesIO(raw), output if output is not None else io.BytesIO()
        getattr(handler, "do_" + method)()
        head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        content = next((line for line in head.split(b"\r\n") if line.lower().startswith(b"content-type:")), b"")
        return int(head.split(b" ", 2)[1]), json.loads(body) if b"application/json" in content else body
    return request


@contextmanager
def started_fake(manager):
    child = FakeChild()
    with patch.object(lifecycle, "REAL_POPEN", return_value=child) as spawn:
        request = memory_http(manager)
        code, started = request("/api/start", start_request(manager))
        assert code == 200, started
        yield request, child, started["id"], spawn


def seed_worker_arm(manager, identifier, child):
    """Explicit invented worker receipts for gate tests, never native evidence."""
    common = lifecycle._common(manager.control, identifier, child.pid)
    lifecycle._publish(manager.lifecycle_root, "worker-start.json", common)
    lifecycle._publish(manager.lifecycle_root, "armed.json", {**common, "scenario": "stop"})


def seed_worker_exit(manager, identifier, child, *, code=130, signum=signal.SIGTERM):
    common = lifecycle._common(manager.control, identifier, child.pid)
    lifecycle._publish(manager.lifecycle_root, "worker-exit.json", {**common, "scenario": "stop", "exit_code": code,
        "signal": signum, "provider_attempts": 0, "check_attempts": 0, "network_attempts": 0,
        "python_level_guards": True, "os_wide_packet_audit": False})
    child.returncode = code


class LiveRunStopTests(unittest.TestCase):
    def assert_refused_unchanged(self, root, operation, *args):
        before = snapshot(root)
        with self.assertRaises(Refused) as caught: operation(*args)
        self.assertRegex(str(caught.exception), r"^[A-Z][A-Z_]+$")
        self.assertNotIn(PRIVATE, str(caught.exception))
        self.assertEqual(before, snapshot(root))

    def test_new_root_is_private_exact_and_unattempted_not_a_success(self):
        with live_fixture() as (root, manager, control, _, spawn):
            before = snapshot(root)
            self.assertEqual(live.validate_fixture(root), control)
            self.assertEqual(manager.live_root, root)
            self.assertEqual(manager.lifecycle_root, root / "lifecycle")
            self.assertEqual({p.name for p in root.iterdir()}, {"control.json", "receipts", "lifecycle"})
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "control.json").stat().st_mode & 0o777, 0o600)
            report = live.live_stop_report(root)
            self.assertEqual((report["status"], report["outcome"]), ("UNKNOWN", "UNKNOWN"))
            self.assertIs(report["browser_observed"], False)
            self.assertFalse(report["running_response"] or report["armed_stop"] or report["explicit_stop"])
            self.assertFalse(live.armed_checkpoint(root))
            self.assertEqual(before, snapshot(root)); spawn.assert_not_called()

    def test_existing_partial_relative_source_and_linked_roots_are_not_adopted(self):
        with live_fixture() as (root, _, _, _, spawn):
            self.assert_refused_unchanged(root, live.initialize, root)
            for path in [Path("relative"), lifecycle.HERE, lifecycle.HERE.parent]:
                with self.assertRaises(Refused): live.initialize(path)
            link = root.parent / "linked-case"; link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(Refused): live.validate_fixture(link)
            partial = root.parent / "partial"; partial.mkdir(mode=0o700)
            lifecycle.base._new(partial / "control.json", {"private": PRIVATE})
            before = snapshot(partial)
            with self.assertRaises(Refused): live.initialize(partial)
            self.assertEqual(before, snapshot(partial)); spawn.assert_not_called()

    def test_control_source_mode_and_original_source_drift_refuse_without_repair(self):
        for mode in ["control", "source-pin", "mode", "input"]:
            with self.subTest(mode=mode), live_fixture() as (root, manager, _, source, spawn):
                if mode == "control":
                    path = root / "control.json"; value = json.loads(path.read_bytes()); value["extra"] = PRIVATE
                    path.write_bytes(canonical(value))
                elif mode == "source-pin": source.return_value = {"directory": "/invented-different-source", "files": {}}
                elif mode == "mode": (root / "control.json").chmod(0o640)
                else:
                    path = manager.root / "workspace/project/calculator.py"; path.write_bytes(path.read_bytes() + b"# changed input\n")
                self.assert_refused_unchanged(root, live.validate_fixture, root)
                spawn.assert_not_called()

    def test_catalog_rejects_foreign_partial_symlink_hardlink_and_oversized_receipts(self):
        for mode in ["foreign", "partial", "symlink", "hardlink", "oversized"]:
            with self.subTest(mode=mode), live_fixture() as (root, _, _, _, spawn):
                name = "foreign.json" if mode == "foreign" else "running-response.json"
                path = root / "receipts" / name
                if mode == "symlink": path.symlink_to(root / "missing-private-target")
                else:
                    path.write_bytes(b"x" * 65537 if mode == "oversized" else b'{"version":')
                    path.chmod(0o600)
                    if mode == "partial": path.rename(path.with_name(path.name + ".next"))
                    elif mode == "hardlink": os.link(path, root.parent / "extra-hardlink")
                before = snapshot(root)
                try:
                    value = live.live_stop_report(root)
                except Refused:
                    pass
                else:
                    self.assertEqual(value["status"], "UNKNOWN")
                self.assertEqual(before, snapshot(root)); spawn.assert_not_called()

    def test_logical_agent_and_native_worker_arguments_remain_fixed_and_source_bound(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (_, _, identifier, spawn):
            self.assertEqual(spawn.call_count, 1)
            argv = spawn.call_args.args[0]
            self.assertEqual(argv, lifecycle.expected_worker_command(manager.lifecycle_root, identifier))
            self.assertNotIn("--allow-local-inference", argv)
            self.assertNotIn("ollama", argv)
            self.assertEqual(argv[-1], identifier)
            self.assertTrue(argv[2].endswith("/offline_lifecycle.py"))

    def test_direct_view_and_running_history_do_not_arm_stop(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            seed_worker_arm(manager, identifier, child)
            manager.view(identifier)
            status, rows = request("/api/history", method="GET")
            self.assertEqual((status, rows[0]["state"]), (200, "RUNNING"))
            manager.poll_gate()
            self.assertFalse(live.armed_checkpoint(root, identifier))
            before = snapshot(root)
            status, denied = request("/api/stop", {"id": identifier})
            self.assertEqual(status, 409); self.assertIsInstance(denied.get("error"), str)
            self.assertEqual(before, snapshot(root)); self.assertEqual(child.terminations, 0)

    def test_successful_running_response_requires_original_checkpoint_before_arming(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            status, view = request("/api/run/" + identifier, method="GET")
            self.assertEqual((status, view["state"]), (200, "RUNNING"))
            manager.poll_gate(); self.assertFalse(live.armed_checkpoint(root, identifier))
            seed_worker_arm(manager, identifier, child)
            manager.poll_gate(); self.assertTrue(live.armed_checkpoint(root, identifier))
            before = snapshot(root); manager.poll_gate()
            self.assertEqual(before, snapshot(root))
            self.assertEqual(manager.live_counters["running_responses"], 1)
            self.assertEqual(manager.live_counters["armed_stops"], 1)

    def test_missing_worker_receipts_never_verify_live_stop_from_failed_metadata(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            child.returncode = 130
            status, rows = request("/api/history", method="GET")
            self.assertEqual((status, rows[0]["state"]), (200, "FAILED"))
            before = snapshot(root); value = live.live_stop_report(root)
            self.assertEqual((value["status"], value["outcome"]), ("UNKNOWN", "UNKNOWN"))
            self.assertEqual(value["lifecycle"]["metadata_state"], "FAILED")
            self.assertEqual(before, snapshot(root))


if __name__ == "__main__": unittest.main()
