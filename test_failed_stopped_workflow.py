"""Explicitly synthetic lifecycle receipts/mocked children; never native QA.

Source fingerprints are mocked only inside these unit fixtures so concurrent
drafting cannot masquerade as an actual source-bound worker qualification.
"""

import copy
import json
import os
import signal
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha
import offline_lifecycle as lifecycle
import offline_workflow as base
from test_offline_workflow_integration import snapshot, start_request


@contextmanager
def synthetic_fixture(scenario="fail"):
    fingerprint = {"directory": str(lifecycle.HERE), "files": {"offline_lifecycle.py": "1" * 64,
                   "agent.py": "2" * 64, "workbench.py": "3" * 64}}
    with tempfile.TemporaryDirectory() as directory, patch.object(lifecycle, "_source_fingerprint", return_value=fingerprint), patch.object(
            lifecycle, "REAL_POPEN", side_effect=AssertionError("unit attempted a native child")) as spawn:
        root = Path(directory) / "case"
        lifecycle.initialize(root, scenario)
        manager = lifecycle.LifecycleManager(root)
        try:
            yield root, manager, spawn
        finally:
            manager.close()


def seed_terminal(manager, identifier="1" * 16, complete=True, containment=False, code=None):
    """Fabricated chain for pure verifier branches; not native process evidence."""
    outer, inner, control = manager.lifecycle_root, manager.root, manager.control
    pid = os.getpid()
    code = (23 if control["scenario"] == "fail" else 130) if code is None else code
    task = manager.projects["arithmetic"]["definition"]
    base._new(inner / "receipts/start-claim.json", {"version": 1, "fixture_id": control["fixture_id"], "attempt": 1})
    base._new(inner / "workspace/data/tasks" / (identifier + ".json"), task)
    base._new(inner / "receipts/launch.json", {"version": 1, "id": identifier, "fixture_id": control["fixture_id"],
              "argv": base.expected_command(inner, identifier), "task_sha256": sha(canonical(task))})
    common = lifecycle._common(control, identifier, pid)
    base._new(inner / "receipts/parent-started.json", common)
    meta = {"id": identifier, "project": "arithmetic", "project_name": "Arithmetic demo", "source": str(inner / "workspace/project"),
            "goal": task["goal"], "backend": "scripted-demo", "model": "scripted-demo", "task_sha256": sha(canonical(task)),
            "project_task_sha256": manager.marker["files"]["workspace/task.json"], "state": "FAILED", "pid": pid,
            "process_stamp": "unit-only", "created": 1, "finished": 2, "exit_code": code}
    base._new(inner / "workspace/data/jobs" / (identifier + ".json"), meta)
    (inner / "workspace/data/jobs" / (identifier + ".log")).write_bytes(b"explicitly synthetic; no child\n")
    os.chmod(inner / "workspace/data/jobs" / (identifier + ".log"), 0o600)
    lifecycle._publish(outer, "attempt.json", {"version": 1, "fixture_id": control["fixture_id"], "scenario": control["scenario"]})
    lifecycle._publish(outer, "actual-launch.json", {"version": 1, "fixture_id": control["fixture_id"], "id": identifier,
                       "argv": lifecycle.expected_worker_command(outer, identifier), "control_sha256": sha(lifecycle._read(outer, "control.json"))})
    lifecycle._publish(outer, "spawned.json", common)
    if complete:
        lifecycle._publish(outer, "worker-start.json", common)
        lifecycle._publish(outer, "armed.json", {**common, "scenario": control["scenario"]})
        lifecycle._publish(outer, "worker-exit.json", {**common, "scenario": control["scenario"], "exit_code": code,
                           "signal": None if control["scenario"] == "fail" else signal.SIGTERM,
                           "provider_attempts": 0, "check_attempts": 0, "network_attempts": 0,
                           "python_level_guards": True, "os_wide_packet_audit": False})
        if control["scenario"] == "stop" or containment:
            kind = "containment" if containment else "explicit"
            prefix = "containment" if containment else "stop"
            intent = {**common, "scenario": control["scenario"], "kind": kind,
                      "armed_sha256": None if containment else sha(lifecycle._read(outer, "receipts/armed.json")),
                      "launch_sha256": sha(lifecycle._read(outer, "receipts/actual-launch.json"))}
            lifecycle._publish(outer, prefix + "-intent.json", intent)
            lifecycle._publish(outer, prefix + "-return.json", {**intent, "state": "STOP_REQUESTED"})
    return identifier


class FakeChild:
    """A fake in-memory child. No OS process or signal is used."""
    def __init__(self):
        self.pid = os.getpid(); self.returncode = None; self.terminations = 0
    def poll(self): return self.returncode
    def terminate(self): self.terminations += 1; self.returncode = 130
    def wait(self, timeout=None): return self.returncode
    def kill(self): raise AssertionError("unit must not escalate")


class FailedStoppedWorkflowTests(unittest.TestCase):
    def report(self, root):
        value = lifecycle.lifecycle_report(root)
        self.assertEqual(set(value), {"version", "scenario", "fixture_id", "run_id", "status", "outcome", "metadata_state",
                         "exit_code", "signal", "guard_attempts", "source_unchanged", "original_inputs_unchanged",
                         "run_directory_present", "agent_executed", "notes"})
        self.assertLessEqual(len(canonical(value)), 65536)
        self.assertEqual(value["notes"], sorted(set(value["notes"])))
        self.assertTrue(set(value["notes"]) <= lifecycle.NOTES)
        return value

    def test_initialize_is_new_private_source_bound_and_does_not_adopt(self):
        with synthetic_fixture() as (root, manager, spawn):
            before = snapshot(root)
            self.assertEqual(manager.root, root / "workflow")
            self.assertEqual(lifecycle.validate_fixture(root), manager.control)
            with self.assertRaises(Refused): lifecycle.initialize(root, "fail")
            self.assertEqual(before, snapshot(root)); spawn.assert_not_called()

    def test_invalid_scenario_and_relative_or_source_roots_refuse(self):
        for scenario in [None, True, "FAIL", "stop\n", "other"]:
            with self.assertRaises(Refused): lifecycle.initialize(Path("/tmp/unused-lifecycle-unit"), scenario)
        for root in [Path("relative"), lifecycle.HERE, lifecycle.HERE.parent, Path("/tmp/../tmp/unused")]:
            with self.assertRaises(Refused): lifecycle.initialize(root, "fail")

    def test_unattempted_and_partial_evidence_have_unknown_not_zero_counters(self):
        with synthetic_fixture() as (root, manager, spawn):
            value = self.report(root)
            self.assertEqual((value["status"], value["outcome"]), ("UNKNOWN", "UNKNOWN"))
            self.assertEqual(value["guard_attempts"], {"provider": None, "checks": None, "network": None})
            seed_terminal(manager, complete=False)
            value = self.report(root)
            self.assertEqual(value["status"], "UNKNOWN")
            self.assertIsNone(value["agent_executed"]); self.assertIn("INCOMPLETE_EVIDENCE", value["notes"])
            spawn.assert_not_called()

    def test_synthetic_verifier_keeps_both_original_metadata_states_failed(self):
        for scenario, outcome, code in [("fail", "CONTROLLED_FAILURE", 23), ("stop", "OWNED_STOP", 130)]:
            with synthetic_fixture(scenario) as (root, manager, spawn):
                identifier = seed_terminal(manager); before = snapshot(root); value = self.report(root)
                self.assertEqual((value["status"], value["outcome"], value["metadata_state"], value["exit_code"]), ("VERIFIED", outcome, "FAILED", code))
                self.assertFalse(value["run_directory_present"]); self.assertIs(value["agent_executed"], False)
                self.assertEqual(value["guard_attempts"], {"provider": 0, "checks": 0, "network": 0})
                self.assertFalse((manager.root / "workspace/data/runs" / identifier).exists())
                self.assertEqual(before, snapshot(root)); spawn.assert_not_called()

    def test_timeout_containment_and_invalid_typed_exit_never_verify_owned_stop(self):
        for kind in ["timeout", "containment", "bool-counter", "bool-version", "bad-signal", "bad-pid"]:
            with synthetic_fixture("stop") as (root, manager, spawn):
                seed_terminal(manager, containment=kind == "containment", code=24 if kind == "timeout" else None)
                path = root / "receipts/worker-exit.json"; value = json.loads(path.read_bytes())
                if kind == "bool-counter": value["check_attempts"] = False
                elif kind == "bool-version": value["version"] = True
                elif kind == "bad-signal": value["signal"] = None
                elif kind == "bad-pid": value["pid"] += 1
                path.write_bytes(canonical(value)); before = snapshot(root)
                self.assertEqual(self.report(root)["status"], "UNKNOWN")
                self.assertEqual(before, snapshot(root)); spawn.assert_not_called()

    def test_pinned_armed_or_launch_changes_invalidate_stop_evidence(self):
        for name in ["armed.json", "actual-launch.json", "stop-return.json", "attempt.json"]:
            with synthetic_fixture("stop") as (root, manager, spawn):
                seed_terminal(manager); path = root / "receipts" / name
                if name in {"armed.json", "actual-launch.json"}: path.write_bytes(path.read_bytes() + b"\n")
                else:
                    value = json.loads(path.read_bytes()); value["version"] = True; path.write_bytes(canonical(value))
                self.assertEqual(self.report(root)["status"], "UNKNOWN"); spawn.assert_not_called()

    def test_optional_missing_refuses_unsafe_parent_and_dangling_or_multiple_links(self):
        with synthetic_fixture() as (root, manager, spawn):
            self.assertIsNone(lifecycle._json(root, "receipts/missing.json", True))
            path = root / "receipts/missing.json"; path.symlink_to(root / "absent-target")
            with self.assertRaises(Refused): lifecycle._json(root, "receipts/missing.json", True)
            path.unlink(); base._new(path, {"version": 1}); os.link(path, root / "duplicate")
            with self.assertRaises(Refused): lifecycle._json(root, "receipts/missing.json", True)
            (root / "duplicate").unlink(); path.unlink(); (root / "receipts").chmod(0o750)
            with self.assertRaises(Refused): lifecycle._json(root, "receipts/missing.json", True)
            (root / "receipts").chmod(0o700); spawn.assert_not_called()

    def test_control_source_change_foreign_names_and_unsafe_receipts_refuse(self):
        with synthetic_fixture() as (root, manager, spawn):
            with patch.object(lifecycle, "_source_fingerprint", return_value={"directory": "/different-source", "files": {}}):
                with self.assertRaises(Refused): lifecycle.validate_fixture(root)
            base._new(root / "receipts/foreign.json", {})
            with self.assertRaises(Refused): lifecycle.validate_fixture(root)
            (root / "receipts/foreign.json").unlink(); base._new(root / "receipts/attempt.json", {})
            (root / "receipts/attempt.json").chmod(0o640)
            with self.assertRaises(Refused): lifecycle.validate_fixture(root)
            (root / "receipts/attempt.json").chmod(0o600); spawn.assert_not_called()

    def test_source_traversal_counts_ignored_entries_and_refuses_symlink_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["offline_lifecycle.py", "agent.py", "workbench.py"]: base._new(root / name, {})
            for number in range(510): (root / (str(number) + ".txt")).write_bytes(b"ignored")
            with patch.object(lifecycle, "HERE", root):
                with self.assertRaisesRegex(Refused, "^LIFECYCLE_SOURCE_LIMIT$"): lifecycle._source_fingerprint()
            for path in root.glob("*.txt"): path.unlink()
            (root / "static").symlink_to(root, target_is_directory=True)
            with patch.object(lifecycle, "HERE", root):
                with self.assertRaisesRegex(Refused, "^LIFECYCLE_SOURCE$"): lifecycle._source_fingerprint()

    def test_source_depth_and_selected_file_budgets_are_finite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["offline_lifecycle.py", "agent.py", "workbench.py"]: base._new(root / name, {})
            path = root / "static"
            for _ in range(5): path.mkdir(mode=0o700); path = path / "nested"
            with patch.object(lifecycle, "HERE", root):
                with self.assertRaisesRegex(Refused, "^LIFECYCLE_SOURCE_LIMIT$"): lifecycle._source_fingerprint()

    def test_public_checkout_source_permissions_are_accepted_without_private_fixture_weakening(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); root.chmod(0o755)
            for name in ["offline_lifecycle.py", "agent.py", "workbench.py"]:
                (root / name).write_bytes(b"# synthetic source\n"); (root / name).chmod(0o644)
            (root / ".git").mkdir(mode=0o755)
            with patch.object(lifecycle, "HERE", root):
                result = lifecycle._source_fingerprint()
            self.assertEqual(set(result["files"]), {"offline_lifecycle.py", "agent.py", "workbench.py"})
        with synthetic_fixture() as (root, manager, spawn):
            (root / "receipts").chmod(0o755)
            with self.assertRaises(Refused): lifecycle.validate_fixture(root)
            (root / "receipts").chmod(0o700)

    def test_group_or_world_writable_source_and_linked_files_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["offline_lifecycle.py", "agent.py", "workbench.py"]: base._new(root / name, {})
            with patch.object(lifecycle, "HERE", root):
                for mode in [0o660, 0o666]:
                    (root / "agent.py").chmod(mode)
                    with self.assertRaises(Refused): lifecycle._source_fingerprint()
                (root / "agent.py").chmod(0o600); root.chmod(0o777)
                with self.assertRaises(Refused): lifecycle._source_fingerprint()
                root.chmod(0o700); os.link(root / "agent.py", root / "duplicate.txt")
                with self.assertRaises(Refused): lifecycle._source_fingerprint()

    def test_direct_callback_outside_launch_context_and_invalid_engine_argv_refuse(self):
        with synthetic_fixture() as (root, manager, spawn):
            with self.assertRaisesRegex(Refused, "^LIFECYCLE_ARGV$"): manager._controlled_popen(["arbitrary"])
            with self.assertRaises(Refused): manager._launch(["arbitrary"], env={})
            self.assertIsNone(manager._launch_context)
            self.assertTrue((root / "receipts/attempt.json").is_file()); spawn.assert_not_called()
        # Reach the inherited kwargs/log identity guards with a complete,
        # explicitly synthetic logical launch, rather than failing argv first.
        for changed in ["env", "session", "foreign-log"]:
            with self.subTest(changed=changed), synthetic_fixture() as (root, manager, spawn):
                identifier = seed_terminal(manager)
                (root / "receipts/attempt.json").unlink()
                target = (root.parent / "unit-foreign-log" if changed == "foreign-log" else
                          manager.root / "workspace/data/jobs" / (identifier + ".log"))
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "ab") as stream:
                    kwargs = {"stdin": subprocess.DEVNULL, "stdout": stream, "stderr": subprocess.STDOUT,
                              "start_new_session": True,
                              "env": {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}}
                    if changed == "env": kwargs["env"]["PATH"] = "/invented-not-admitted"
                    elif changed == "session": kwargs["start_new_session"] = False
                    with self.assertRaisesRegex(Refused, "^OFFLINE_WORKFLOW_ARGV$"):
                        manager._launch(base.expected_command(manager.root, identifier), **kwargs)
                self.assertIsNone(manager._launch_context); spawn.assert_not_called()

    def test_mocked_exact_start_consumes_once_and_missing_worker_stays_unknown(self):
        with synthetic_fixture() as (root, manager, spawn):
            child = FakeChild()
            with patch.object(lifecycle, "REAL_POPEN", return_value=child) as launch, patch("workbench.process_stamp", return_value="unit-only"):
                identifier = manager.start(start_request(manager))["id"]
            self.assertEqual(launch.call_args.args[0], lifecycle.expected_worker_command(root, identifier))
            self.assertEqual(manager.lifecycle_counters["native_launches"], 1)
            child.returncode = 23
            self.assertEqual(manager.history()[0]["state"], "FAILED")
            before = snapshot(root)
            with self.assertRaises(Refused): manager.start(start_request(manager))
            self.assertEqual(before, snapshot(root)); self.assertEqual(self.report(root)["status"], "UNKNOWN")

    def test_unarmed_foreign_and_double_stop_do_not_send_extra_signal(self):
        with synthetic_fixture("stop") as (root, manager, spawn):
            child = FakeChild()
            with patch.object(lifecycle, "REAL_POPEN", return_value=child), patch("workbench.process_stamp", return_value="unit-only"):
                identifier = manager.start(start_request(manager))["id"]
            with self.assertRaises(Refused): manager.stop("f" * 16)
            with self.assertRaisesRegex(Refused, "^LIFECYCLE_STOP_UNARMED$"): manager.stop(identifier)
            self.assertEqual(child.terminations, 0)
            common = lifecycle._common(manager.control, identifier, child.pid)
            lifecycle._publish(root, "worker-start.json", common); lifecycle._publish(root, "armed.json", {**common, "scenario": "stop"})
            thread = lambda target, **kwargs: Mock(start=target)
            with patch("workbench.threading.Thread", side_effect=thread):
                self.assertEqual(manager.stop(identifier), {"state": "STOP_REQUESTED"})
            with self.assertRaises(Refused): manager.stop(identifier)
            self.assertEqual(child.terminations, 1); self.assertEqual(manager.lifecycle_counters["explicit_stops"], 1)
            self.assertEqual(self.report(root)["status"], "UNKNOWN")

    def test_close_records_containment_without_qualifying_planned_stop(self):
        with synthetic_fixture("stop") as (root, manager, spawn):
            child = FakeChild()
            with patch.object(lifecycle, "REAL_POPEN", return_value=child), patch("workbench.process_stamp", return_value="unit-only"):
                manager.start(start_request(manager))
            with patch("workbench.threading.Thread", side_effect=lambda target, **kwargs: Mock(start=target)):
                manager.close()
            self.assertEqual(manager.lifecycle_counters["containment_stops"], 1)
            value = self.report(root); self.assertEqual(value["status"], "UNKNOWN")
            self.assertIn("CONTAINMENT_STOP", value["notes"])

    def test_worker_guards_block_agent_execution_checks_and_network(self):
        import agent
        import socket
        with lifecycle.worker_guards() as counts:
            for operation in [lambda: agent.main(), lambda: agent.Session.run(None, None, None, None),
                              lambda: agent.ScriptedDemo.request(None, None), lambda: socket.getaddrinfo("invalid.example", 1)]:
                with self.assertRaises(Refused): operation()
        self.assertEqual(counts, {"provider": 1, "checks": 2, "network": 1})

    def test_cli_receipt_pairs_preserve_report_but_validate_schema_and_custody(self):
        with synthetic_fixture("stop") as (root, manager, spawn):
            seed_terminal(manager); before = self.report(root); tag = "a" * 16
            lifecycle._publish(root, "session-" + tag + ".json", {"version": 1, "fixture_id": manager.control["fixture_id"],
                               "scenario": "stop", "pid": os.getpid(), "port": 36230})
            lifecycle._publish(root, "shutdown-" + tag + ".json", {"version": 1, "listener_closed": True,
                               "counters": base.new_counters(), "lifecycle_counters": dict.fromkeys(lifecycle.LIFECYCLE_COUNTER_KEYS, 0)})
            self.assertEqual(self.report(root), before)
            path = root / "receipts" / ("shutdown-" + tag + ".json")
            value = json.loads(path.read_bytes()); value["counters"]["start_requests"] = False; path.write_bytes(canonical(value))
            with self.assertRaises(Refused): lifecycle.validate_fixture(root)

    def test_unknown_report_never_echoes_malformed_metadata_values(self):
        with synthetic_fixture() as (root, manager, spawn):
            identifier = seed_terminal(manager)
            path = manager.root / "workspace/data/jobs" / (identifier + ".json")
            value = json.loads(path.read_bytes()); value["state"] = {"private": "do not echo"}; value["exit_code"] = True
            path.write_bytes(canonical(value)); result = self.report(root)
            self.assertEqual(result["status"], "UNKNOWN"); self.assertIsNone(result["metadata_state"]); self.assertIsNone(result["exit_code"])
            self.assertNotIn("do not echo", canonical(result).decode())


if __name__ == "__main__":
    unittest.main()
