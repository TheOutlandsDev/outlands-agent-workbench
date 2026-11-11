"""Offline diagnostics summaries, compatibility, privacy and admission evidence."""

import json
import unittest
from unittest.mock import Mock

from agent import canonical, write_new
from run_diagnostics import FORMAT, summarize
from test_workbench import manager_fixture
from workbench import replace_json

TASK = {"max_turns": 12, "request_seconds": 120}


def start(turn=1, **extra):
    return {"kind": "request_started", "value": {"turn": turn, "diagnostics": {
        "format": FORMAT, "started_at_ms": 1800000000000, "timeout_seconds": 120,
        "request_bytes": 2400, **extra}}}


def finish(turn=1, **extra):
    return {"kind": "request_finished", "value": {"turn": turn, "diagnostics": {
        "format": FORMAT, "finished_at_ms": 1800000001500, "elapsed_ms": 1500,
        "phase": "HEADER", "outcome": "ERROR", "reason": "PROVIDER_HEADER_TIMEOUT",
        "error_category": "TIMEOUT", "metrics": {}, **extra}}}


def summary(events, **extra):
    arguments = {"state": "UNCERTAIN", "backend": "ollama", "hold_matches": True,
                 "result": {"status": "UNCERTAIN", "reason": "PROVIDER_HEADER_TIMEOUT", "turns": 1}}
    arguments.update(extra)
    return summarize(TASK, events=events, **arguments)


class SummaryTests(unittest.TestCase):
    def test_failed_request_retains_evidence_and_unknown_completion(self):
        value = summary([start(), finish()])
        self.assertEqual((value["state"], value["hold"], value["provider_completion"]), ("UNCERTAIN", "UNRESOLVED", "UNKNOWN"))
        row = value["requests"][0]
        self.assertEqual((row["phase"], row["elapsed_ms"], row["request_bytes"], row["timeout_seconds"]), ("HEADER", 1500, 2400, 120))
        self.assertEqual(row["status"], "ERROR")
        self.assertEqual(row["error_category"], "TIMEOUT")
        self.assertIn("HOLD_RETAINED", value["notes"])

    def test_active_request_requires_owned_live_worker(self):
        value = summary([start()], state="RUNNING", result=None, owned_active=True)
        self.assertEqual((value["state"], value["hold"], value["requests"][0]["status"]), ("ACTIVE", "ACTIVE_REQUEST", "ACTIVE"))
        self.assertIsNone(value["requests"][0]["elapsed_ms"])
        self.assertIn("REQUEST_ACTIVE", value["notes"])

    def test_response_recording_does_not_clear_hold_or_claim_task_success(self):
        events = [start(), {"kind": "response", "value": {}}, finish(outcome="RESPONSE_RECORDED", phase="COMPLETE", reason=None, error_category=None)]
        value = summary(events)
        self.assertEqual((value["state"], value["hold"], value["provider_completion"]), ("UNCERTAIN", "UNRESOLVED", "RECORDED"))

    def test_finish_claim_without_response_is_not_completion_evidence(self):
        value = summary([start(), finish(outcome="RESPONSE_RECORDED", phase="COMPLETE")])
        self.assertEqual(value["provider_completion"], "UNKNOWN")
        self.assertEqual(value["requests"][0]["status"], "UNKNOWN")
        self.assertIn("INVALID_DIAGNOSTICS", value["notes"])

    def test_legacy_missing_timings_stay_unknown(self):
        events = [{"kind": "request_started", "value": {"turn": 1}}, {"kind": "response", "value": {}}]
        before = json.dumps(events, sort_keys=True)
        value = summary(events, state="FAILED", hold_matches=False, result={"reason": "PLAN_REQUIRED", "turns": 1})
        self.assertTrue(value["legacy"])
        self.assertIsNone(value["requests"][0]["elapsed_ms"])
        self.assertIsNone(value["requests"][0]["request_bytes"])
        self.assertEqual(value["provider_completion"], "RECORDED")
        self.assertEqual(json.dumps(events, sort_keys=True), before)

    def test_missing_detailed_finish_keeps_response_proof_but_requires_inspection(self):
        value = summary([start(), {"kind": "response", "value": {}}], state="REVIEW_READY", hold_matches=False,
                        result={"reason": "CHECKS_PASSED", "turns": 1})
        self.assertEqual(value["provider_completion"], "RECORDED")
        self.assertEqual(value["state"], "NEEDS_INSPECTION")
        self.assertIn("MISSING_REQUEST_FINISH", value["notes"])

    def test_engine_parse_codes_remain_visible(self):
        for code in ["JSON_LIMIT", "INVALID_JSON", "DUPLICATE_JSON_KEY", "JSON_CONSTANT"]:
            value = summary([start(), finish(reason=code)], result={"reason": code})
            self.assertEqual(value["reason"], code)
            self.assertEqual(value["requests"][0]["reason"], code)

    def test_untrusted_diagnostics_never_surface_raw_text(self):
        secret = "private fixture detail /fictional/account"
        events = [start(request_bytes=True, timeout_seconds=secret), finish(phase=secret, reason=secret, error_category=secret,
                  metrics={"eval_count": 0, "prompt_eval_count": True, "total_duration": 9007199254740992, "extra": secret})]
        value = summary(events, result={"reason": secret})
        self.assertNotIn(secret, json.dumps(value))
        self.assertEqual(value["requests"][0]["metrics"], {"eval_count": 0})
        self.assertIsNone(value["reason"])
        self.assertIsNone(value["requests"][0]["request_bytes"])

    def test_corrupt_duplicate_and_excessive_events_are_bounded(self):
        events = [start(), start(), finish()] + [{"kind": "request_started", "value": {"turn": 999}}] * 300
        value = summary(events)
        self.assertEqual(len(value["requests"]), 1)
        self.assertIn("INVALID_DIAGNOSTICS", value["notes"])
        self.assertIn("EVENT_LIMIT", value["notes"])
        self.assertLess(len(json.dumps(value)), 4096)

    def test_scripted_and_not_started_do_not_claim_inference(self):
        value = summary([], state="RUNNING", backend="scripted-demo", result=None, hold_matches=False, owned_active=False)
        self.assertEqual(value["state"], "NEEDS_INSPECTION")
        self.assertEqual(value["provider_completion"], "NOT_APPLICABLE")
        self.assertEqual(value["budget"]["used"], 0)
        self.assertIn("SCRIPTED_NO_INFERENCE", value["notes"])


def seed_active(manager, run_id):
    task = manager.projects["arithmetic"]["definition"]
    run = manager.run_path(run_id); run.mkdir(mode=0o700)
    write_new(manager.data / "tasks" / (run_id + ".json"), canonical(task))
    write_new(run / "event-000.json", canonical({"index": 0, **start()}))
    meta = {"id": run_id, "project": "arithmetic", "project_name": "Offline request fixture",
            "source": str(manager.projects["arithmetic"]["source"]), "goal": task["goal"], "model": "fictional-model",
            "backend": "ollama", "created": 1, "state": "RUNNING", "pid": -1, "process_stamp": "fictional"}
    write_new(manager.meta_path(run_id), canonical(meta))
    write_new(manager.data / "state/hold.json", canonical({"state": "REQUEST_UNSETTLED", "run": str(run), "turn": 1}))
    return run


class ControllerTests(unittest.TestCase):
    def test_owned_active_hold_has_active_admission_and_panel(self):
        with manager_fixture() as (_, manager, run_id):
            seed_active(manager, run_id)
            child = Mock(); child.poll.return_value = None
            manager.children[run_id] = (child, Mock())
            try:
                self.assertEqual(manager.admission(), "MODEL_REQUEST_ACTIVE")
                view = manager.view(run_id)
                self.assertEqual(view["diagnostics"]["state"], "ACTIVE")
                self.assertEqual(view["diagnostics"]["hold"], "ACTIVE_REQUEST")
            finally:
                manager.children.pop(run_id)

    def test_restart_does_not_claim_ownership_or_modify_hold(self):
        with manager_fixture() as (_, manager, run_id):
            seed_active(manager, run_id)
            hold = manager.data / "state/hold.json"; raw = hold.read_bytes()
            self.assertEqual(manager.admission(), "UNCERTAIN_REQUEST_HELD")
            self.assertEqual(manager.view(run_id)["diagnostics"]["state"], "NEEDS_INSPECTION")
            self.assertEqual(hold.read_bytes(), raw)

    def test_malformed_hold_still_blocks_with_owned_child(self):
        with manager_fixture() as (_, manager, run_id):
            seed_active(manager, run_id)
            replace_json(manager.data / "state/hold.json", {"state": "REQUEST_UNSETTLED", "run": "other", "turn": True})
            child = Mock(); child.poll.return_value = None
            manager.children[run_id] = (child, Mock())
            try:
                self.assertEqual(manager.admission(), "UNCERTAIN_REQUEST_HELD")
                self.assertEqual(manager.view(run_id)["diagnostics"]["hold"], "UNASSOCIATED")
            finally:
                manager.children.pop(run_id)

    def test_corrupt_request_events_remain_inspectable(self):
        for value in [None, {}, {"turn": "private fixture text"}]:
            with self.subTest(value=value), manager_fixture() as (_, manager, run_id):
                run = seed_active(manager, run_id)
                replace_json(run / "event-000.json", {"index": 0, "kind": "request_started", "value": value})
                view = manager.view(run_id)
                self.assertIn("INVALID_DIAGNOSTICS", view["diagnostics"]["notes"])
                self.assertEqual(view["pending_events"], 1)
                self.assertNotIn("private fixture text", json.dumps(view["diagnostics"]))

    def test_finished_fixture_summary_preserves_artifacts(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            run = manager.run_path(run_id)
            before = {f.name: f.read_bytes() for f in run.glob("*.json")}
            diagnostics = manager.view(run_id)["diagnostics"]
            self.assertEqual(diagnostics["state"], "COMPLETE")
            self.assertEqual(diagnostics["provider_completion"], "NOT_APPLICABLE")
            self.assertEqual({f.name: f.read_bytes() for f in run.glob("*.json")}, before)


if __name__ == "__main__":
    unittest.main()
