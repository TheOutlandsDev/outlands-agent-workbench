"""Invented complete/partial saved evidence; no I/O, live workers or inference."""

import copy
import json
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, canonical
from run_comparison import _summary
from saved_run_review import CODES, DIAGNOSTIC_FIELDS, DIAGNOSTIC_NOTES, review_saved_run
from test_run_comparison import bundle, check_event, digest, request


PINS = ("1" * 64, "2" * 64, "3" * 64)
ENVELOPE = {"version", "id", "record_sha256", "history_sha256", "evidence_sha256", "summary", "diagnostics"}


@contextmanager
def pure_guard():
    with ExitStack() as stack:
        for target in ("builtins.open", "os.open", "pathlib.Path.resolve", "pathlib.Path.stat",
                       "subprocess.Popen", "subprocess.run", "agent.read_file", "agent.Ollama.request",
                       "agent.Ollama.preflight", "agent.ScriptedDemo.request", "agent.Session.checks"):
            stack.enter_context(patch(target, side_effect=AssertionError("saved review reached " + target)))
        yield


class Explosive:
    def __str__(self):
        raise AssertionError("untrusted string conversion")

    def __eq__(self, other):
        raise AssertionError("untrusted equality")

    def __hash__(self):
        raise AssertionError("untrusted hash")


class SavedRunReviewTests(unittest.TestCase):
    def refused(self, code, value, pins=PINS):
        with self.assertRaises(Refused) as caught:
            review_saved_run(value, *pins)
        self.assertEqual(str(caught.exception), "SAVED_REVIEW_" + code)
        self.assertIn(str(caught.exception), CODES)

    def test_complete_python_and_java_reuse_exact_comparison_summary(self):
        for java in (False, True):
            value = bundle(java=java)
            expected = _summary(value)[0]
            result = review_saved_run(value, *PINS)
            self.assertEqual(set(result), ENVELOPE)
            self.assertEqual(result["summary"], expected)
            self.assertEqual((result["record_sha256"], result["history_sha256"], result["evidence_sha256"]), PINS)
            self.assertEqual(set(result["diagnostics"]), set(DIAGNOSTIC_FIELDS))
            self.assertEqual(result["diagnostics"]["budget"], {"used": 1, "limit": 4, "per_request_seconds": 17})
            self.assertEqual(result["diagnostics"]["provider_completion"], "RECORDED")
            self.assertEqual(result["summary"]["final_checks"][0]["tests_ran"], 2)

    def test_no_live_state_or_hold_fields_or_notes_are_returned(self):
        value = bundle(); value.update(owned_active=True, hold_matches=True, hold_present=True, pid=Explosive())
        result = review_saved_run(value, *PINS)
        self.assertNotIn("state", result["diagnostics"])
        self.assertNotIn("hold", result["diagnostics"])
        self.assertNotIn("ACTIVE", [row["status"] for row in result["diagnostics"]["requests"]])
        self.assertTrue(set(result["diagnostics"]["notes"]) <= DIAGNOSTIC_NOTES)
        self.assertNotIn(b'"pid"', canonical(result))

    def test_failed_uncertain_running_and_interrupted_outcomes_are_preserved(self):
        for state in ("FAILED", "UNCERTAIN", "RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED", "INTERRUPTED"):
            value = bundle(); value["metadata"]["state"] = state; value["result"].update(status=state, reason="PROVIDER_HEADER_TIMEOUT")
            value["events"] = request(failed=True)
            result = review_saved_run(value, *PINS)
            self.assertEqual(result["summary"]["state"], state)
            self.assertEqual(result["summary"]["result_status"], state)
            self.assertEqual(result["summary"]["result_reason"], "PROVIDER_HEADER_TIMEOUT")
            self.assertEqual(result["diagnostics"]["provider_completion"], "UNKNOWN")
            self.assertEqual(result["diagnostics"]["requests"][0]["status"], "ERROR")

    def test_missing_legacy_evidence_is_unknown_and_budgets_are_not_invented(self):
        result = review_saved_run({"id": "b" * 16}, *PINS)
        self.assertIsNone(result["summary"]["goal"])
        self.assertIsNone(result["summary"]["state"])
        self.assertEqual(result["summary"]["files"], [])
        self.assertEqual(result["diagnostics"]["budget"], {"used": None, "limit": None, "per_request_seconds": None})
        self.assertEqual(result["diagnostics"]["requests"], [])
        self.assertEqual(result["diagnostics"]["provider_completion"], "UNKNOWN")
        self.assertIn("PROVIDER_COMPLETION_UNKNOWN", result["diagnostics"]["notes"])
        self.assertIn("RECORD_MISSING", result["summary"]["notes"])

    def test_invalid_task_keeps_saved_request_turns_without_fake_task_limits(self):
        value = bundle(); value["task"] = {"max_turns": Explosive()}; value["result"]["turns"] = 2
        value["events"] = request(turn=2, failed=True)
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["diagnostics"]["budget"], {"used": 2, "limit": None, "per_request_seconds": None})
        self.assertEqual(result["diagnostics"]["requests"][0]["turn"], 2)
        self.assertIn("INVALID_DIAGNOSTICS", result["diagnostics"]["notes"])
        self.assertIn("RECORD_INVALID", result["summary"]["notes"])

    def test_valid_task_without_request_or_turn_evidence_has_unknown_used_budget(self):
        value = bundle(); value["events"] = []; value["result"] = {}
        self.assertEqual(review_saved_run(value, *PINS)["diagnostics"]["budget"],
                         {"used": None, "limit": 4, "per_request_seconds": 17})
        value["result"] = {"turns": 0}
        self.assertEqual(review_saved_run(value, *PINS)["diagnostics"]["budget"]["used"], 0)

    def test_full_valid_unicode_goals_and_controls_are_not_normalized_or_clipped(self):
        value = bundle(); goal = "Ω🧪e\u0301\r\n\0" * 200
        value["task"]["goal"] = value["metadata"]["goal"] = goal
        value["task_sha256"] = value["metadata"]["task_sha256"] = digest(value["task"])
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["summary"]["goal"], goal)
        self.assertEqual(json.loads(canonical(result))["summary"]["goal"], goal)

    def test_oversized_metadata_goal_becomes_unknown_instead_of_a_silent_prefix(self):
        value = bundle(); value["task"] = None; value["metadata"]["goal"] = "x" * 2001
        result = review_saved_run(value, *PINS)
        self.assertIsNone(result["summary"]["goal"])
        self.assertIn("RECORD_LIMIT", result["summary"]["notes"])

    def test_private_extras_prompts_outputs_exceptions_and_paths_are_not_returned(self):
        value = bundle(); secret = "INVENTED_PRIVATE_EXTRA_NEVER_RETURN"
        value["metadata"].update(source="/absolute/" + secret, pid=9, credentials=Explosive())
        value["result"].update(raw_response=secret, exception=secret, source=secret)
        value["events"][1]["value"]["prompt"] = secret
        value["events"][2]["value"] = {"response": secret, "unknown": Explosive()}
        result = review_saved_run(value, *PINS)
        encoded = canonical(result)
        self.assertNotIn(secret.encode(), encoded)
        self.assertNotIn(b"invented checker output", encoded)
        self.assertNotIn(b'"source"', encoded)

    def test_malformed_recognized_values_are_bounded_before_existing_helpers(self):
        value = bundle(); value["metadata"].update(state=Explosive(), backend=[], model=Explosive(), created=True)
        value["result"].update(status=Explosive(), reason=Explosive(), turns=Explosive())
        value["events"][1]["value"]["diagnostics"].update(phase=Explosive(), reason=Explosive(), metrics=Explosive())
        result = review_saved_run(value, *PINS)
        self.assertIsNone(result["summary"]["state"])
        self.assertIsNone(result["summary"]["result_reason"])
        self.assertIn("RECORD_INVALID", result["summary"]["notes"])
        self.assertLessEqual(len(canonical(result)), 65536)

    def test_wrong_wrapper_identifier_and_pin_types_have_finite_input_errors(self):
        for value in (None, [], {}, {"id": 1}, {"id": "A" * 16}, {"id": "a" * 16 + "\n"},
                      {"id": "a" * 15}, {"id": "a" * 16, **{str(i): 1 for i in range(33)}}):
            self.refused("INPUT", value)
        for pin in (None, [], Explosive(), "f" * 63, "F" * 64, "f" * 64 + "\n", "g" * 64):
            for index in range(3):
                pins = list(PINS); pins[index] = pin
                self.refused("INPUT", bundle(), pins)

    def test_builtin_subclasses_and_cycles_do_not_reach_reused_helpers(self):
        class StrSubclass(str):
            pass
        class DictSubclass(dict):
            pass
        self.refused("INPUT", DictSubclass(bundle()))
        self.refused("INPUT", {"id": StrSubclass("a" * 16)})
        value = bundle(); cycle = []; cycle.append(cycle); value["task"]["extra"] = cycle
        result = review_saved_run(value, *PINS)
        self.assertIsNone(result["summary"]["max_turns"])
        self.assertIn("RECORD_LIMIT", result["summary"]["notes"])

    def test_task_result_and_patch_fingerprint_mismatches_remain_observations(self):
        value = bundle(); value["metadata"]["task_sha256"] = "f" * 64; value["result"]["patch_sha256"] = "e" * 64
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["summary"]["task_integrity"], "MISMATCH")
        self.assertFalse(result["summary"]["patch"]["matches_recorded"])
        self.assertIn("TASK_FINGERPRINT_MISMATCH", result["summary"]["notes"])
        self.assertIn("PATCH_FINGERPRINT_MISMATCH", result["summary"]["notes"])

    def test_patch_preview_is_bounded_and_truncation_explicit_without_goal_loss(self):
        value = bundle(); value["patch"] = "Ω" * 6000; value["patch_sha256"] = digest(value["patch"])
        value["result"]["patch_sha256"] = value["patch_sha256"]
        result = review_saved_run(value, *PINS)
        self.assertEqual(len(result["summary"]["patch"]["text"].encode()), 8192)
        self.assertTrue(result["summary"]["patch"]["truncated"])
        self.assertEqual(result["summary"]["goal"], value["task"]["goal"])
        self.assertIn("PATCH_TRUNCATED", result["summary"]["notes"])

    def test_oversized_or_invalid_patch_is_unknown_with_finite_notes(self):
        for text, note in (("x" * 65537, "RECORD_LIMIT"), ("🧪" * 16385, "RECORD_LIMIT"),
                           ("\ud800", "RECORD_INVALID"), (Explosive(), "RECORD_INVALID")):
            value = bundle(); value["patch"] = text
            result = review_saved_run(value, *PINS)
            self.assertIsNone(result["summary"]["patch"]["text"])
            self.assertIn(note, result["summary"]["notes"])

    def test_complete_response_over_canonical_cap_refuses_without_clipping_goal(self):
        value = bundle(); goal = "🧪" * 2000
        value["task"]["goal"] = value["metadata"]["goal"] = goal
        value["task_sha256"] = value["metadata"]["task_sha256"] = digest(value["task"])
        value["patch"] = "\u0001" * 8192; value["patch_sha256"] = digest(value["patch"])
        value["result"]["patch_sha256"] = value["patch_sha256"]
        self.refused("OUTPUT_LIMIT", value)
        self.assertEqual(value["task"]["goal"], goal)

    def test_event_limit_and_malformed_events_are_explicit_not_live_reconciled(self):
        value = bundle(); value["events"] = [{"index": i, "kind": "plan", "value": {}} for i in range(257)]
        result = review_saved_run(value, *PINS)
        self.assertIn("EVENT_LIMIT", result["summary"]["notes"])
        self.assertIn("EVENT_LIMIT", result["diagnostics"]["notes"])
        value["events"] = [Explosive(), {"index": True, "kind": "response", "value": {}}]
        result = review_saved_run(value, *PINS)
        self.assertIn("RECORD_INVALID", result["summary"]["notes"])
        self.assertIn("INVALID_DIAGNOSTICS", result["diagnostics"]["notes"])

    def test_request_preflight_is_historical_and_proves_no_sent_request(self):
        value = bundle(); value["result"].update(status="REFUSED", reason="REQUEST_SIZE_LIMIT", turns=0)
        value["metadata"]["state"] = "REFUSED"
        value["events"] = [{"index": 1, "kind": "request_refused", "value": {"diagnostics": {
            "format": "outlands-request-preflight-v1", "reason": "REQUEST_SIZE_LIMIT", "request_bytes": 131073,
            "limit_bytes": 131072, "chat_request_sent": False, "new_hold_created": False}}}]
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["diagnostics"]["budget"]["used"], 0)
        self.assertFalse(result["diagnostics"]["preflight"]["chat_request_sent"])
        self.assertEqual(result["diagnostics"]["provider_completion"], "NOT_APPLICABLE")
        self.assertEqual(result["summary"]["metrics"]["requests"], 0)
        self.assertNotIn("hold", result["diagnostics"])

    def test_missing_finish_retains_unknown_provider_completion_and_saved_running_state(self):
        value = bundle(); value["metadata"]["state"] = "RUNNING"; value["events"] = request()[:1]
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["summary"]["state"], "RUNNING")
        self.assertEqual(result["diagnostics"]["requests"][0]["status"], "UNKNOWN")
        self.assertEqual(result["diagnostics"]["provider_completion"], "UNKNOWN")
        self.assertIn("MISSING_REQUEST_FINISH", result["diagnostics"]["notes"])

    def test_scripted_evidence_is_labelled_without_claiming_inference(self):
        value = bundle(); value["metadata"]["backend"] = "scripted-demo"
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["diagnostics"]["provider_completion"], "NOT_APPLICABLE")
        self.assertIn("SCRIPTED_NO_INFERENCE", result["diagnostics"]["notes"])

    def test_no_request_evidence_is_unknown_except_scripted_or_validated_preflight(self):
        value = bundle(); value["events"] = []; value["result"]["turns"] = 0
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["diagnostics"]["provider_completion"], "UNKNOWN")
        value["metadata"]["backend"] = "scripted-demo"
        result = review_saved_run(value, *PINS)
        self.assertEqual(result["diagnostics"]["provider_completion"], "NOT_APPLICABLE")
        self.assertNotIn("PROVIDER_COMPLETION_UNKNOWN", result["diagnostics"]["notes"])

    def test_pure_review_preserves_supplied_evidence_and_is_deterministic(self):
        value = bundle(java=True); before = copy.deepcopy(value)
        with pure_guard():
            first = review_saved_run(value, *PINS)
            second = review_saved_run(value, *PINS)
        self.assertEqual(first, second)
        self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()
