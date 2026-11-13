"""Normal HTTP live-stop gate tests with fake children and explicit synthetic receipts."""

import copy
import io
import json
import os
import signal
import unittest
from unittest.mock import patch

from agent import Refused, canonical
import offline_lifecycle as lifecycle
import offline_live_stop as live
from offline_workflow import new_counters
from qa_failed_stopped_workflow import inspect_terminal
from qa_live_run_stop import execution_guards, refuse_terminal_outputs, setup_manager, verified_report, wait_for_armed
from test_live_run_stop import (
    ORIGIN, PRIVATE, TOKEN, live_fixture, memory_http, seed_worker_arm, seed_worker_exit,
    snapshot, start_request, started_fake,
)


def finish_synthetic_stop(root, manager, request, child, identifier):
    """Fabricated worker identity/exit; only fake-object controller behavior is proved."""
    seed_worker_arm(manager, identifier, child)
    status, running = request("/api/run/" + identifier, method="GET")
    assert status == 200 and running["state"] == "RUNNING"
    manager.poll_gate()
    assert live.armed_checkpoint(root, identifier)
    status, returned = request("/api/stop", {"id": identifier})
    assert status == 200 and returned == {"state": "STOP_REQUESTED"}
    seed_worker_exit(manager, identifier, child)
    status, rows = request("/api/history", method="GET")
    assert status == 200 and len(rows) == 1 and rows[0]["state"] == "FAILED"
    return verified_report(root)


class BoundedMonitorEvent:
    """Drive the real monitor synchronously; no Python thread or child runs."""
    def __init__(self, now, *, finished=lambda: False, on_wait=lambda _: None, maximum=10):
        self.now, self.finished, self.on_wait, self.maximum = now, finished, on_wait, maximum
        self.waits, self.stopped = 0, False
    def wait(self, seconds):
        self.waits += 1
        if self.waits > self.maximum: raise AssertionError("monitor exceeded its synthetic bound")
        if self.stopped or self.finished(): return True
        if seconds != 0.02: raise AssertionError("unexpected monitor interval")
        self.now[0] += seconds
        self.on_wait(self.waits)
        return False
    def set(self): self.stopped = True


class LiveRunStopIntegrationTests(unittest.TestCase):
    def test_setup_baseline_allows_new_data_directory_and_pins_existing_files_before_run(self):
        with live_fixture() as (existing, _, _, _, native):
            root = existing.parent / "invented-setup-only"
            live.initialize(root)
            before = snapshot(root)
            manager, initialized, evidence = setup_manager(root)
            try:
                workspace = "lifecycle/workflow/workspace"
                self.assertEqual(initialized[workspace]["links"], before[workspace]["links"] + 1)
                self.assertEqual(initialized[workspace]["mode"], before[workspace]["mode"])
                self.assertEqual(initialized[workspace]["uid"], before[workspace]["uid"])
                files = {name: row for name, row in before.items() if "sha256" in row}
                self.assertEqual(len(files), 7)
                self.assertTrue(all(initialized[name] == row for name, row in files.items()))
                self.assertTrue((root / workspace / "data/server.lock").is_file())
                self.assertEqual(initialized, snapshot(root)); self.assertEqual(evidence["initial_regular_files"], 7)
                self.assertTrue(evidence["initial_file_bytes_modes_links_unchanged"])
                self.assertTrue(evidence["existing_directory_modes_owners_unchanged"])
                self.assertTrue(evidence["full_run_baseline_after_manager_setup"])
                self.assertEqual(manager.counters["start_requests"], 0); self.assertEqual(manager.children, {})
                self.assertEqual(list((root / "receipts").iterdir()), [])
                self.assertEqual(list((root / "lifecycle/receipts").iterdir()), [])
            finally: manager.close()
            self.assertEqual(initialized, snapshot(root)); native.assert_not_called()

    def test_setup_baseline_rejects_initialized_file_bytes_modes_links_and_directory_mode_drift(self):
        for change in ["bytes", "file-mode", "file-links", "directory-mode"]:
            with self.subTest(change=change), live_fixture() as (existing, _, _, _, native):
                root = existing.parent / "invented-tampered-setup"
                live.initialize(root)
                original_manager = live.LiveStopManager
                created = []
                def changed_constructor(directory):
                    manager = original_manager(directory); created.append(manager)
                    source = directory / "lifecycle/workflow/workspace/project/calculator.py"
                    if change == "bytes": source.write_bytes(source.read_bytes() + b"# setup mutation\n")
                    elif change == "file-mode": source.chmod(0o640)
                    elif change == "file-links": os.link(source, existing.parent / "invented-extra-source-link")
                    else: (directory / "lifecycle/workflow/workspace").chmod(0o750)
                    return manager
                with patch.object(live, "LiveStopManager", side_effect=changed_constructor):
                    with self.assertRaises(AssertionError): setup_manager(root)
                self.assertEqual(len(created), 1); self.assertTrue(created[0]._closed)
                self.assertEqual(created[0].counters["start_requests"], 0)
                self.assertEqual(list((root / "receipts").iterdir()), [])
                native.assert_not_called()

    def test_normal_run_running_then_once_only_owned_stop_keeps_failed_metadata(self):
        with live_fixture() as (root, manager, _, _, native):
            initial = snapshot(root)
            request = memory_http(manager)
            self.assertEqual(request("/api/history", method="GET"), (200, []))
            self.assertEqual(initial, snapshot(root))
            with started_fake(manager) as (request, child, identifier, spawn):
                self.assertEqual(manager.metadata(identifier)["state"], "RUNNING")
                report = finish_synthetic_stop(root, manager, request, child, identifier)
                self.assertEqual(report["lifecycle"]["metadata_state"], "FAILED")
                self.assertEqual((report["lifecycle"]["exit_code"], report["lifecycle"]["signal"]), (130, signal.SIGTERM))
                self.assertFalse(report["browser_observed"])
                self.assertEqual(child.terminations, 1); self.assertEqual(child.kills, 0)
                self.assertEqual(manager.lifecycle_counters, {"native_launches": 1, "explicit_stops": 1, "containment_stops": 0})
                self.assertEqual(manager.live_counters, {"running_responses": 1, "armed_stops": 1, "explicit_stops": 1, "containment_stops": 0})
                self.assertEqual(manager.counters["start_attempts"], 1); self.assertEqual(manager.counters["worker_launches"], 1)
                self.assertFalse(manager.run_path(identifier).exists()); self.assertEqual(manager.children, {})
                settled = snapshot(root)
                for route, body in [("/api/start", start_request(manager)), ("/api/stop", {"id": identifier})]:
                    code, denied = request(route, body)
                    self.assertEqual(code, 409); self.assertIsInstance(denied.get("error"), str)
                self.assertEqual(settled, snapshot(root)); spawn.assert_called_once()
                self.assertTrue(all(settled.get(name) == row for name, row in initial.items()))
            native.assert_not_called()

    def test_second_running_response_does_not_overwrite_or_double_arm(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            seed_worker_arm(manager, identifier, child)
            code, first = request("/api/run/" + identifier, method="GET")
            self.assertEqual((code, first["state"]), (200, "RUNNING")); manager.poll_gate()
            before = snapshot(root)
            code, second = request("/api/run/" + identifier, method="GET")
            self.assertEqual((code, second["state"]), (200, "RUNNING"))
            manager.poll_gate(); self.assertEqual(before, snapshot(root))
            self.assertEqual(manager.live_counters["running_responses"], 1); self.assertEqual(manager.live_counters["armed_stops"], 1)

    def test_one_stop_waits_for_original_arm_then_signals_exactly_once(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, spawn):
            code, running = request("/api/run/" + identifier, method="GET")
            self.assertEqual((code, running["state"]), (200, "RUNNING"))
            self.assertTrue((root / "receipts/running-response.json").is_file())
            self.assertFalse(lifecycle.armed_checkpoint(manager.lifecycle_root, identifier))
            now = [max(manager._started_time + 0.1, live.time.monotonic())]
            def arm_during_readiness_wait(seconds):
                self.assertEqual(seconds, 0.02)
                self.assertEqual(child.terminations, 0)
                now[0] += seconds
                seed_worker_arm(manager, identifier, child)
            with patch.object(live.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(live.time, "sleep", side_effect=arm_during_readiness_wait) as sleep:
                code, stopped = request("/api/stop", {"id": identifier})
            self.assertEqual((code, stopped), (200, {"state": "STOP_REQUESTED"}))
            sleep.assert_called_once_with(0.02)
            self.assertEqual(child.terminations, 1); self.assertEqual(child.kills, 0)
            self.assertEqual(manager.live_counters, {"running_responses": 1, "armed_stops": 1, "explicit_stops": 1, "containment_stops": 0})
            self.assertEqual(manager.lifecycle_counters["explicit_stops"], 1); spawn.assert_called_once()
            seed_worker_exit(manager, identifier, child); request("/api/history", method="GET")
            self.assertEqual(verified_report(root)["outcome"], "OWNED_STOP")

    def test_original_arm_missing_for_whole_readiness_budget_never_signals(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            code, running = request("/api/run/" + identifier, method="GET")
            self.assertEqual((code, running["state"]), (200, "RUNNING"))
            before = snapshot(root)
            now = [max(manager._started_time + 0.1, live.time.monotonic())]
            began = now[0]
            def advance(seconds):
                self.assertEqual(seconds, 0.02)
                now[0] += seconds
            with patch.object(live.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(live.time, "sleep", side_effect=advance) as sleep, \
                    patch.object(manager, "poll_gate", wraps=manager.poll_gate) as readiness:
                code, denied = request("/api/stop", {"id": identifier})
            self.assertEqual((code, denied), (409, {"error": "LIVE_STOP_STOP_UNARMED"}))
            self.assertGreater(readiness.call_count, 0); self.assertLessEqual(sleep.call_count, 51)
            self.assertGreaterEqual(now[0] - began, 1); self.assertLessEqual(now[0] - began, 1.021)
            self.assertFalse(manager._armed_claimed or manager._stop_claimed)
            self.assertEqual(child.terminations, 0); self.assertEqual(child.kills, 0)
            self.assertEqual(manager.live_counters["explicit_stops"], 0)
            self.assertEqual(before, snapshot(root))
            self.assertEqual(live.live_stop_report(root)["status"], "UNKNOWN")

    def test_partial_gate_publication_consumes_claim_without_signal_or_overwrite(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            request("/api/run/" + identifier, method="GET")
            now = [max(manager._started_time + 0.1, live.time.monotonic())]
            original_publish = live._publish
            staged = root / "receipts/armed-stop.json.next"
            def interrupted_publish(directory, name, value):
                if name == "armed-stop.json":
                    lifecycle.base._new(staged, {"interrupted": PRIVATE})
                    raise OSError(PRIVATE)
                return original_publish(directory, name, value)
            def advance_and_arm(seconds):
                now[0] += seconds
                if not (manager.lifecycle_root / "receipts/armed.json").exists():
                    seed_worker_arm(manager, identifier, child)
            with patch.object(live.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(live.time, "sleep", side_effect=advance_and_arm), \
                    patch.object(live, "_publish", side_effect=interrupted_publish) as publish:
                code, denied = request("/api/stop", {"id": identifier})
                self.assertEqual(code, 409); self.assertNotIn(PRIVATE, json.dumps(denied))
                self.assertTrue(manager._armed_claimed); self.assertFalse(manager._stop_claimed)
                self.assertTrue(staged.is_file()); before = snapshot(root)
                self.assertFalse(manager.poll_gate()); self.assertFalse(manager.poll_gate())
                code, denied = request("/api/stop", {"id": identifier})
                self.assertEqual((code, denied), (409, {"error": "LIVE_STOP_STOP_UNARMED"}))
                published = [call.args[1] for call in publish.call_args_list]
                self.assertEqual(published, ["armed-stop.json", "gate-failed.json"])
                failure = json.loads((root / "receipts/gate-failed.json").read_bytes())
                self.assertEqual((failure["reason"], failure["stage"], failure["failure_type"]),
                                 ("GATE_FAILED", "GATE_PUBLICATION", "OS_ERROR"))
                self.assertTrue(manager._gate_failed); self.assertEqual(before, snapshot(root))
            self.assertEqual(child.terminations, 0); self.assertEqual(child.kills, 0)
            self.assertEqual(manager.live_counters["armed_stops"], 0)
            self.assertEqual(manager.live_counters["explicit_stops"], 0)
            self.assertFalse((root / "receipts/armed-stop.json").exists())
            self.assertFalse((root / "receipts/stop-intent.json").exists())
            self.assertEqual(live.live_stop_report(root)["status"], "UNKNOWN")

    def test_real_monitor_awaits_pending_original_worker_receipts_without_execution(self):
        for pending in ["worker-start.json", "armed.json"]:
            with self.subTest(pending=pending), live_fixture() as (root, manager, _, _, _), \
                    started_fake(manager) as (request, child, identifier, spawn):
                request("/api/run/" + identifier, method="GET")
                common = lifecycle._common(manager.control, identifier, child.pid)
                if pending == "armed.json": lifecycle._publish(manager.lifecycle_root, "worker-start.json", common)
                staged = manager.lifecycle_root / "receipts" / (pending + ".next")
                value = common if pending == "worker-start.json" else {**common, "scenario": "stop"}
                lifecycle.base._new(staged, value)
                def finish_publication(wait):
                    if wait == 2:
                        os.link(staged, staged.with_name(pending)); staged.unlink()
                        if pending == "worker-start.json":
                            lifecycle._publish(manager.lifecycle_root, "armed.json", {**common, "scenario": "stop"})
                now = [max(manager._started_time + 0.1, live.time.monotonic())]
                event = BoundedMonitorEvent(now, finished=lambda: manager.live_counters["armed_stops"] == 1,
                                            on_wait=finish_publication)
                manager._monitor_stop = event
                with patch.object(live.time, "monotonic", side_effect=lambda: now[0]): manager._monitor()
                self.assertGreaterEqual(event.waits, 3)
                self.assertTrue(live.armed_checkpoint(root, identifier))
                self.assertEqual(manager.live_counters["armed_stops"], 1)
                self.assertEqual(child.terminations, 0); spawn.assert_called_once()
                self.assertFalse((root / "receipts/gate-failed.json").exists())
                before = snapshot(root); manager.poll_gate(); self.assertEqual(before, snapshot(root))

    def test_real_monitor_survives_completed_original_publication_read_windows(self):
        for window in ["two-links", "listed-stage-removed"]:
            with self.subTest(window=window), live_fixture() as (root, manager, _, _, _), \
                    started_fake(manager) as (request, child, identifier, spawn):
                request("/api/run/" + identifier, method="GET")
                common = lifecycle._common(manager.control, identifier, child.pid)
                lifecycle._publish(manager.lifecycle_root, "worker-start.json", common)
                receipts = manager.lifecycle_root / "receipts"
                staged, committed = receipts / "armed.json.next", receipts / "armed.json"
                original_catalog, original_names = lifecycle._catalog, lifecycle.base._names
                injected, full_catalog_ticks = [], []
                def publish_during_wait(wait):
                    if wait == 1:
                        lifecycle.base._new(staged, {**common, "scenario": "stop"})
                        os.link(staged, committed)
                    elif wait == 2 and staged.exists(): staged.unlink()
                def observed_listing(path, *args, **kwargs):
                    names = original_names(path, *args, **kwargs)
                    if path == receipts and not injected:
                        injected.append(window)
                        if window == "two-links":
                            # A directory enumeration can omit the staged name
                            # while the committed inode still has both links.
                            return [name for name in names if name != "armed.json.next"]
                        # The returned scan predates the publisher's unlink.
                        staged.unlink()
                    return names
                def full_catalog(directory, control):
                    if directory == manager.lifecycle_root:
                        full_catalog_ticks.append(event.waits)
                        self.assertGreaterEqual(event.waits, 2, "strict catalogue entered a pending publication")
                    return original_catalog(directory, control)
                now = [max(manager._started_time + 0.1, live.time.monotonic())]
                event = BoundedMonitorEvent(now, finished=lambda: manager.live_counters["armed_stops"] == 1,
                                            on_wait=publish_during_wait)
                manager._monitor_stop = event
                with patch.object(live.time, "monotonic", side_effect=lambda: now[0]), \
                        patch.object(lifecycle.base, "_names", side_effect=observed_listing), \
                        patch.object(lifecycle, "_catalog", side_effect=full_catalog):
                    manager._monitor()
                self.assertEqual(injected, [window])
                self.assertTrue(full_catalog_ticks)
                self.assertTrue(lifecycle.armed_checkpoint(manager.lifecycle_root, identifier))
                self.assertTrue(live.armed_checkpoint(root, identifier))
                self.assertEqual(manager.live_counters["armed_stops"], 1)
                self.assertGreaterEqual(event.waits, 2)
                self.assertEqual(child.terminations, 0); spawn.assert_called_once()
                self.assertFalse((root / "receipts/gate-failed.json").exists())

    def test_real_monitor_marks_genuine_unsafe_gate_once_and_keeps_deadline_bounded(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, spawn):
            request("/api/run/" + identifier, method="GET")
            seed_worker_arm(manager, identifier, child)
            unsafe = manager.lifecycle_root / "receipts/armed.json"
            unsafe.chmod(0o640)
            unsafe_raw = unsafe.read_bytes()
            with self.assertRaises(Refused): lifecycle.armed_checkpoint(manager.lifecycle_root, identifier)
            now = [manager._deadline - 0.1]
            event = BoundedMonitorEvent(now)
            manager._monitor_stop = event
            with patch.object(live.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(live, "_publish", wraps=live._publish) as publish:
                manager._monitor()
            published = [call.args[1] for call in publish.call_args_list]
            self.assertEqual(published.count("gate-failed.json"), 1)
            self.assertTrue(manager._gate_failed)
            self.assertTrue((root / "receipts/deadline.json").is_file())
            self.assertTrue((root / "receipts/containment.json").is_file())
            self.assertGreater(event.waits, 1); self.assertLessEqual(event.waits, 7)
            self.assertLessEqual(now[0] - manager._started_time, live.RUN_SECONDS + 0.021)
            self.assertEqual(unsafe.read_bytes(), unsafe_raw); self.assertEqual(unsafe.stat().st_mode & 0o777, 0o640)
            self.assertEqual(manager.live_counters["armed_stops"], 0)
            self.assertEqual(manager.live_counters["explicit_stops"], 0)
            self.assertFalse((root / "receipts/armed-stop.json").exists())
            self.assertFalse((root / "receipts/stop-intent.json").exists())
            self.assertEqual(child.terminations, 0); spawn.assert_called_once()

    def test_initial_monitor_poll_error_is_durable_finite_and_never_signals_unknown_ownership(self):
        for error, kind in [(OSError(PRIVATE), "OS_ERROR"), (ValueError(PRIVATE), "VALUE_ERROR"),
                            (TypeError(PRIVATE), "TYPE_ERROR"), (KeyError(PRIVATE), "KEY_ERROR"),
                            (Refused(PRIVATE), "REFUSED")]:
            with self.subTest(kind=kind), live_fixture() as (root, manager, _, _, _), \
                    started_fake(manager) as (request, child, identifier, spawn):
                request("/api/run/" + identifier, method="GET")
                now = [max(manager._started_time + 0.1, live.time.monotonic())]
                event = BoundedMonitorEvent(now, maximum=2)
                manager._monitor_stop = event
                with patch.object(live.time, "monotonic", side_effect=lambda: now[0]), \
                        patch.object(child, "poll", side_effect=error) as poll, \
                        patch.object(live, "_publish", wraps=live._publish) as publish:
                    manager._monitor()
                self.assertEqual(event.waits, 1); poll.assert_called_once_with()
                self.assertEqual([call.args[1] for call in publish.call_args_list], ["gate-failed.json"])
                raw = (root / "receipts/gate-failed.json").read_bytes()
                failure = json.loads(raw)
                self.assertEqual((failure["reason"], failure["stage"], failure["failure_type"]),
                                 ("GATE_FAILED", "OWNERSHIP", kind))
                self.assertNotIn(PRIVATE, raw.decode()); self.assertTrue(manager._gate_failed)
                self.assertFalse(manager._armed_claimed or manager._stop_claimed)
                self.assertEqual(child.terminations, 0); self.assertEqual(child.kills, 0)
                self.assertEqual(manager.live_counters["explicit_stops"], 0); spawn.assert_called_once()
                self.assertFalse((root / "receipts/deadline.json").exists())
                self.assertFalse((root / "receipts/containment.json").exists())
                self.assertEqual(live.live_stop_report(root)["status"], "UNKNOWN")

    def test_readiness_preflight_requires_staged_two_links_to_match_the_committed_inode(self):
        for link in ["missing-final", "different-final", "same-final"]:
            with self.subTest(link=link), live_fixture() as (root, manager, _, _, _), \
                    started_fake(manager) as (request, child, identifier, _):
                request("/api/run/" + identifier, method="GET")
                common = lifecycle._common(manager.control, identifier, child.pid)
                lifecycle._publish(manager.lifecycle_root, "worker-start.json", common)
                receipts = manager.lifecycle_root / "receipts"
                staged, committed = receipts / "armed.json.next", receipts / "armed.json"
                value = {**common, "scenario": "stop"}
                lifecycle.base._new(staged, value)
                if link == "same-final": os.link(staged, committed)
                else:
                    os.link(staged, root.parent / "invented-unrelated-hardlink")
                    if link == "different-final": lifecycle.base._new(committed, value)
                before = snapshot(root)
                if link == "same-final":
                    self.assertIs(live._worker_receipts_stable(manager.lifecycle_root), False)
                    self.assertEqual(before, snapshot(root)); self.assertFalse(live.armed_checkpoint(root, identifier))
                    staged.unlink()
                    self.assertIs(live._worker_receipts_stable(manager.lifecycle_root), True)
                    manager.poll_gate(); self.assertTrue(live.armed_checkpoint(root, identifier))
                    self.assertEqual(manager.live_counters["armed_stops"], 1)
                else:
                    with self.assertRaises(Refused) as caught: live._worker_receipts_stable(manager.lifecycle_root)
                    self.assertEqual(str(caught.exception), "LIVE_STOP_STORE_UNSAFE")
                    self.assertEqual(before, snapshot(root)); self.assertEqual(manager.live_counters["armed_stops"], 0)
                self.assertEqual(child.terminations, 0); self.assertEqual(child.kills, 0)

    def test_driver_readiness_holds_publication_lock_and_does_not_retry_refusals(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            request("/api/run/" + identifier, method="GET")
            seed_worker_arm(manager, identifier, child)
            original_checkpoint = live.armed_checkpoint
            def locked_read(directory, run_id):
                self.assertTrue(manager.lock._is_owned())
                return original_checkpoint(directory, run_id)
            def simulated_monitor_publication(seconds):
                self.assertEqual(seconds, 0.02); self.assertFalse(manager.lock._is_owned())
                manager.poll_gate()
            with patch.object(live, "armed_checkpoint", side_effect=locked_read) as observed, \
                    patch.object(live.time, "sleep", side_effect=simulated_monitor_publication) as sleep:
                wait_for_armed(root, manager, identifier, live.time.monotonic() + 1)
            self.assertEqual(observed.call_count, 2); sleep.assert_called_once_with(0.02)
            self.assertTrue(original_checkpoint(root, identifier))
            before = snapshot(root)
            with patch.object(live, "armed_checkpoint", side_effect=Refused("LIVE_STOP_STORE_UNSAFE")) as refused, \
                    patch.object(live.time, "sleep", side_effect=AssertionError("driver retried a refusal")) as sleep:
                with self.assertRaises(Refused): wait_for_armed(root, manager, identifier, live.time.monotonic() + 1)
            refused.assert_called_once_with(root, identifier); sleep.assert_not_called()
            self.assertEqual(before, snapshot(root)); self.assertEqual(child.terminations, 0)

    def test_invalid_session_host_origin_and_fetch_never_reach_run_or_stop(self):
        for action in ["start", "stop"]:
            with self.subTest(action=action), live_fixture() as (root, manager, _, _, native):
                request = memory_http(manager)
                body = start_request(manager) if action == "start" else {"id": "1" * 16}
                with patch.object(manager, action, side_effect=AssertionError("unauthenticated action")) as method:
                    for headers in [{"Host": "private.untrusted.invalid"}, {"Origin": "https://untrusted.invalid"},
                        {"X-Workbench-Token": ""}, {"Sec-Fetch-Site": "cross-site"}]:
                        before = snapshot(root); code, denied = request("/api/" + action, body, headers)
                        self.assertIn(code, [403, 409]); self.assertIsInstance(denied.get("error"), str)
                        self.assertNotIn(TOKEN, json.dumps(denied)); self.assertEqual(before, snapshot(root))
                    method.assert_not_called()
                native.assert_not_called()

    def test_invalid_running_view_tokens_hosts_paths_or_queries_never_publish_gate(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            seed_worker_arm(manager, identifier, child)
            for path, headers in [("/api/run/" + identifier, {"X-Workbench-Token": "wrong-old-token"}),
                ("/api/run/" + identifier, {"Host": "untrusted.invalid"}),
                ("/api/run/" + identifier + "?ignored=1", {}), ("/api/run/" + "f" * 16, {})]:
                before = snapshot(root)
                request(path, method="GET", headers=headers)
                manager.poll_gate(); self.assertEqual(before, snapshot(root))
                self.assertFalse(live.armed_checkpoint(root, identifier))

    def test_framing_is_checked_before_start_or_stop_and_preserves_fresh_state(self):
        with live_fixture() as (root, manager, _, _, native):
            request = memory_http(manager)
            for action, body in [("start", start_request(manager)), ("stop", {"id": "1" * 16})]:
                with patch.object(manager, action, side_effect=AssertionError("bad framing reached action")) as method:
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                        {"Content-Length": "32769"}, {"Content-Length": str(len(canonical(body)) + 1)},
                        {"Content-Type": "application/zip"}, [("Content-Type", "application/json")],
                        [("Content-Length", str(len(canonical(body))))]]:
                        before = snapshot(root); code, denied = request("/api/" + action, body, headers)
                        self.assertIn(code, [403, 409]); self.assertIsInstance(denied.get("error"), str)
                        self.assertEqual(before, snapshot(root))
                    method.assert_not_called()
            native.assert_not_called()

    def test_unauthenticated_or_failed_body_write_is_not_a_running_observation(self):
        class BrokenBody(io.BytesIO):
            def write(self, raw):
                if self.getvalue().endswith(b"\r\n\r\n"): raise BrokenPipeError(PRIVATE)
                return super().write(raw)
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            seed_worker_arm(manager, identifier, child)
            before = snapshot(root)
            with self.assertRaises(BrokenPipeError): request("/api/run/" + identifier, method="GET", output=BrokenBody())
            manager.poll_gate()
            self.assertFalse(live.armed_checkpoint(root, identifier)); self.assertEqual(before, snapshot(root))

    def test_changed_goal_model_or_extra_fields_do_not_launch_a_native_child(self):
        for change in [{"goal": "different goal"}, {"model": "private-local-model"}, {"project": "unknown"}, {"extra": True}]:
            with self.subTest(change=change), live_fixture() as (root, manager, _, _, native):
                inputs = {name: (manager.root / name).read_bytes() for name in manager.marker["files"]}
                request = memory_http(manager); code, denied = request("/api/start", {**start_request(manager), **change})
                self.assertEqual(code, 409); self.assertIsInstance(denied.get("error"), str)
                self.assertEqual(inputs, {name: (manager.root / name).read_bytes() for name in inputs})
                native.assert_not_called(); self.assertFalse(live.armed_checkpoint(root))

    def test_source_task_or_store_mode_drift_blocks_http_start_without_launch(self):
        for mode in ["source", "task", "file-mode", "directory-mode"]:
            with self.subTest(mode=mode), live_fixture() as (root, manager, _, _, native):
                path = manager.root / ("workspace/task.json" if mode == "task" else "workspace/project/calculator.py")
                if mode == "file-mode": path.chmod(0o640)
                elif mode == "directory-mode": (root / "receipts").chmod(0o750)
                else: path.write_bytes(path.read_bytes() + b" \n")
                before = snapshot(root); code, _ = memory_http(manager)("/api/start", start_request(manager))
                self.assertEqual(code, 409); self.assertEqual(before, snapshot(root)); native.assert_not_called()

    def test_expired_gate_and_stale_running_receipt_never_stop_or_qualify(self):
        for mode in ["deadline", "receipt"]:
            with self.subTest(mode=mode), live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
                seed_worker_arm(manager, identifier, child)
                request("/api/run/" + identifier, method="GET"); manager.poll_gate()
                if mode == "deadline": manager._deadline = 0
                else:
                    path = root / "receipts/running-response.json"; path.write_bytes(path.read_bytes() + b"\n")
                before = snapshot(root); code, denied = request("/api/stop", {"id": identifier})
                self.assertEqual(code, 409); self.assertIsInstance(denied.get("error"), str)
                self.assertEqual(child.terminations, 0); self.assertEqual(before, snapshot(root))
                self.assertNotEqual(live.live_stop_report(root)["status"], "VERIFIED")

    def test_containment_close_is_retained_but_cannot_qualify_as_explicit_stop(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            seed_worker_arm(manager, identifier, child)
            request("/api/run/" + identifier, method="GET"); manager.poll_gate()
            manager.close(); seed_worker_exit(manager, identifier, child)
            # Settle via original controller observation, never a rewritten success.
            manager.history()
            value = live.live_stop_report(root)
            self.assertEqual((value["status"], value["outcome"]), ("UNKNOWN", "UNKNOWN"))
            self.assertTrue(value["containment"]); self.assertFalse(value["explicit_stop"])
            self.assertEqual(manager.live_counters["containment_stops"], 1)

    def test_foreign_id_stop_never_signals_and_normal_review_export_remain_refused(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            seed_worker_arm(manager, identifier, child); request("/api/run/" + identifier, method="GET"); manager.poll_gate()
            before = snapshot(root)
            code, _ = request("/api/stop", {"id": "f" * 16 if identifier != "f" * 16 else "e" * 16})
            self.assertEqual(code, 409); self.assertEqual(child.terminations, 0); self.assertEqual(before, snapshot(root))
            code, _ = request("/api/stop", {"id": identifier}); self.assertEqual(code, 200)
            seed_worker_exit(manager, identifier, child); request("/api/history", method="GET")
            before = snapshot(root)
            with execution_guards(): refusals = refuse_terminal_outputs(root, manager, request, identifier)
            self.assertEqual(refusals["review_writes"], 0); self.assertEqual(refusals["export_outputs"], 0)
            self.assertEqual(before, snapshot(root)); self.assertFalse(manager.run_path(identifier).exists())

    def test_readonly_restart_rotates_token_preserves_all_bytes_and_has_no_worker_authority(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, spawn):
            report = finish_synthetic_stop(root, manager, request, child, identifier)
            with execution_guards(read_only=True): first = inspect_terminal(manager, {"run_id": identifier}, TOKEN)
            manager.close(); before = snapshot(root)
            with execution_guards(read_only=True) as counts:
                restarted = live.LiveStopManager(root)
                try:
                    second_http = memory_http(restarted, token="invented-restarted-live-stop-token")
                    code, denied = second_http("/api/history", method="GET", headers={"X-Workbench-Token": TOKEN})
                    self.assertEqual((code, denied), (403, {"error": "SESSION_REQUIRED"}))
                    restarted.counters = new_counters()
                    second = inspect_terminal(restarted, {"run_id": identifier}, "invented-new-live-stop-token")
                    self.assertEqual(first, second); self.assertEqual(verified_report(root), report)
                    self.assertTrue(restarted.read_only)
                    self.assertFalse(any(restarted.lifecycle_counters.values()) or any(restarted.live_counters.values()))
                    self.assertEqual(restarted.counters["worker_launches"], 0)
                finally: restarted.close()
                self.assertFalse(any(counts["inherited"].values()) or any(counts["readonly"].values()))
            self.assertEqual(before, snapshot(root)); spawn.assert_called_once()

    def test_typed_report_validator_rejects_missing_boolean_or_inconsistent_success_claims(self):
        with live_fixture() as (root, manager, _, _, _), started_fake(manager) as (request, child, identifier, _):
            valid = finish_synthetic_stop(root, manager, request, child, identifier)
            for updates in [{"status": "UNKNOWN"}, {"outcome": "UNKNOWN"}, {"version": True}, {"browser_observed": True},
                {"containment": True}, {"running_response": 1}, {"armed_stop": False}, {"extra": PRIVATE},
                {"counts": {"running_responses": True, "armed_stops": 1, "explicit_stops": 1, "containment_stops": 0}}]:
                with self.subTest(updates=updates), patch.object(live, "live_stop_report", return_value={**valid, **updates}):
                    with self.assertRaises(AssertionError): verified_report(root)
            for updates in [{"metadata_state": "REVIEW_READY"}, {"exit_code": False}, {"signal": None},
                {"guard_attempts": {"provider": False, "checks": 0, "network": 0}}, {"agent_executed": None}]:
                value = copy.deepcopy(valid); value["lifecycle"].update(updates)
                with self.subTest(updates=updates), patch.object(live, "live_stop_report", return_value=value):
                    with self.assertRaises(AssertionError): verified_report(root)


if __name__ == "__main__": unittest.main()
