"""Invented saved-run comparisons; no models, services, source reads, or holds."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from agent import Refused
from run_comparison import compare_runs
from run_diagnostics import FORMAT, MAX_SAFE


def digest(value):
    raw = value.encode("utf-8") if isinstance(value, str) else (
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def request(turn=1, size=1000, elapsed=200, *, failed=False):
    started = {"kind": "request_started", "value": {"turn": turn, "diagnostics": {
        "format": FORMAT, "started_at_ms": 1000, "request_bytes": size, "timeout_seconds": 17}}}
    finish = {"kind": "request_finished", "value": {"turn": turn, "diagnostics": {
        "format": FORMAT, "elapsed_ms": elapsed, "phase": "HEADER" if failed else "COMPLETE",
        "outcome": "ERROR" if failed else "RESPONSE_RECORDED",
        "reason": "PROVIDER_HEADER_TIMEOUT" if failed else None,
        "error_category": "TIMEOUT" if failed else None, "metrics": {}}}}
    rows = [started, finish] if failed else [started, {"kind": "response", "value": {}}, finish]
    return [{"index": turn * 10 + index, **row} for index, row in enumerate(rows)]


def check_event(kind, code):
    return {"index": 0 if kind == "baseline_checks" else 100, "kind": kind, "value": {"unit": {"exit_code": code, "tests_ran": 2,
        "timed_out": False, "output_limited": False, "infrastructure_error": False,
        "output": "invented checker output which must not be displayed"}}}


def bundle(run_id="a" * 16, *, java=False):
    if java:
        files = {"sample/Value.java": "a" * 64, "sample/ValueTest.java": "b" * 64}
        editable = ["sample/Value.java"]
        checks = {"unit": {"kind": "java-main", "sources": list(files), "main_class": "sample.ValueTest"}}
    else:
        files = {"module.py": "a" * 64, "test_module.py": "b" * 64}
        editable = ["module.py"]
        checks = {"unit": "test_module.py"}
    task = {"format": "outlands-coding-agent-v2" if java else "outlands-coding-agent-v1",
        "goal": "Fix the invented value.", "files": files, "editable": editable,
        "checks": checks, "max_turns": 4, "request_seconds": 17}
    patch_text = "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-return 1\n+return 2\n"
    result = {"status": "REVIEW_READY", "reason": "CHECKS_PASSED", "turns": 1,
              "patch_sha256": digest(patch_text), "source_adopted": False}
    metadata = {"id": run_id, "project": "invented", "project_name": "Invented project",
        "goal": task["goal"], "state": "REVIEW_READY", "backend": "ollama", "model": "fictional-a",
        "created": 1, "finished": 2, "task_sha256": digest(task), "project_task_sha256": "c" * 64}
    return {"id": run_id, "metadata": metadata, "task": task, "task_sha256": digest(task),
        "result": result, "result_sha256": digest(result),
        "events": [check_event("baseline_checks", 1), *request(), check_event("independent_final_checks", 0)],
        "patch": patch_text, "patch_sha256": digest(patch_text), "notes": []}


def repin(value):
    value["task_sha256"] = digest(value["task"])
    value["metadata"]["task_sha256"] = value["task_sha256"]
    value["metadata"]["goal"] = value["task"]["goal"]
    return value


def patch_text(value, text):
    value["patch"] = text
    value["patch_sha256"] = digest(text)
    value["result"]["patch_sha256"] = value["patch_sha256"]
    value["result_sha256"] = digest(value["result"])


class ComparisonTests(unittest.TestCase):
    def pair(self, *, java=False):
        return bundle(java=java), bundle("b" * 16, java=java)

    def test_successful_python_runs_have_exact_dto_and_known_metrics(self):
        left, right = self.pair()
        right["metadata"]["model"] = "fictional-b"
        right["events"] = [*request(size=1400, elapsed=250),
                           check_event("baseline_checks", 1), check_event("independent_final_checks", 0)]
        value = compare_runs(left, right)
        self.assertEqual(set(value), {"version", "left", "right", "comparable", "differences", "files",
                                      "patch_difference", "metrics_delta", "notes"})
        self.assertEqual(set(value["left"]), {"id", "project", "project_name", "goal", "state", "backend", "model",
            "created", "finished", "task_sha256", "recorded_task_sha256", "project_task_sha256", "task_integrity",
            "files", "checks", "max_turns", "request_seconds", "result_status", "result_reason", "result_sha256",
            "baseline_checks", "final_checks", "metrics", "patch", "notes"})
        self.assertTrue(value["comparable"])
        self.assertEqual(value["differences"], [])
        self.assertEqual(value["left"]["task_integrity"], "MATCH")
        self.assertEqual(value["left"]["metrics"], {"requests": 1, "request_bytes": 1000,
            "elapsed_ms": 200, "measured_requests": 1, "elapsed_requests": 1, "complete": True})
        self.assertEqual(value["metrics_delta"], {"requests": 0, "request_bytes": 400, "elapsed_ms": 50})
        self.assertEqual(value["patch_difference"], {"text": "", "truncated": False})
        self.assertEqual(value["left"]["baseline_checks"][0], {"name": "unit", "kind": "python-unittest",
            "exit_code": 1, "tests_ran": 2, "timed_out": False, "output_limited": False, "infrastructure_error": False})
        self.assertNotIn("invented checker output", json.dumps(value))

    def test_java_v2_nested_specs_and_check_kinds_are_preserved(self):
        left, right = self.pair(java=True)
        value = compare_runs(left, right)
        self.assertTrue(value["comparable"])
        self.assertEqual(value["left"]["checks"][0]["spec"], left["task"]["checks"]["unit"])
        self.assertEqual(value["left"]["final_checks"][0]["kind"], "java-main")
        self.assertEqual(value["files"][1]["left_editable"], False)

    def test_failed_uncertain_and_different_backend_are_outcomes_not_rankings(self):
        left, right = self.pair()
        right["metadata"].update(state="UNCERTAIN", backend="scripted-demo", model="fictional-other")
        right["result"].update(status="UNCERTAIN", reason="PROVIDER_HEADER_TIMEOUT")
        right["result_sha256"] = digest(right["result"])
        right["events"] = request(failed=True)
        value = compare_runs(left, right)
        self.assertTrue(value["comparable"])
        self.assertEqual(value["right"]["result_status"], "UNCERTAIN")
        self.assertEqual(value["right"]["result_reason"], "PROVIDER_HEADER_TIMEOUT")
        self.assertTrue(value["right"]["metrics"]["complete"])
        self.assertNotIn("ranking", json.dumps(value))
        self.assertNotIn("hold", value["right"])

    def test_comparability_reports_each_changed_scope_component(self):
        left, right = self.pair()
        right["metadata"]["project"] = "another"
        right["task"]["goal"] = "Different goal."
        right["task"]["files"]["module.py"] = "d" * 64
        right["task"]["files"]["extra.py"] = "e" * 64
        right["task"]["editable"] = ["extra.py"]
        right["task"]["checks"] = {"other": "test_module.py"}
        right["task"]["max_turns"] = 5
        repin(right)
        right["events"] = request()
        value = compare_runs(left, right)
        self.assertFalse(value["comparable"])
        self.assertEqual(value["differences"], ["PROJECT_DIFFERS", "GOAL_DIFFERS", "FILE_SCOPE_DIFFERS",
            "BASELINE_DIFFERS", "EDIT_SCOPE_DIFFERS", "CHECKS_DIFFER", "BUDGETS_DIFFER"])
        row = next(row for row in value["files"] if row["path"] == "extra.py")
        self.assertIsNone(row["left_sha256"])
        self.assertIsNone(row["left_editable"])
        self.assertTrue(row["right_editable"])

    def test_same_task_fingerprint_cannot_override_different_goal_or_scope(self):
        left, right = self.pair()
        right["task"]["goal"] = "Another actual task goal."
        right["metadata"]["goal"] = right["task"]["goal"]
        value = compare_runs(left, right)
        self.assertIn("GOAL_DIFFERS", value["differences"])
        self.assertFalse(value["comparable"])

    def test_task_fingerprint_mismatch_blocks_comparability(self):
        left, right = self.pair()
        right["metadata"]["task_sha256"] = "f" * 64
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["task_integrity"], "MISMATCH")
        self.assertIn("TASK_FINGERPRINT_MISMATCH", value["differences"])
        self.assertIn("TASK_FINGERPRINT_MISMATCH", value["notes"])

    def test_legacy_fingerprint_is_not_reconstructed_from_project_fingerprint(self):
        left, right = self.pair()
        del right["metadata"]["task_sha256"]
        right["metadata"]["project_task_sha256"] = right["task_sha256"]
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["task_integrity"], "NOT_RECORDED")
        self.assertIsNone(value["right"]["recorded_task_sha256"])
        self.assertIn("LEGACY_TASK_FINGERPRINT", value["notes"])
        self.assertTrue(value["comparable"])

    def test_legacy_request_measurements_are_unknown_without_fake_counters(self):
        left, right = self.pair()
        right["events"] = [{"index": 0, "kind": "request_started", "value": {"turn": 1}},
                           {"index": 1, "kind": "response", "value": {}}]
        value = compare_runs(left, right)
        metrics = value["right"]["metrics"]
        self.assertEqual(metrics["requests"], 1)
        self.assertEqual(metrics["measured_requests"], 0)
        self.assertIsNone(metrics["request_bytes"])
        self.assertIsNone(metrics["elapsed_ms"])
        self.assertFalse(metrics["complete"])
        self.assertIsNone(value["metrics_delta"]["request_bytes"])
        self.assertIsNone(value["metrics_delta"]["elapsed_ms"])
        right["events"] = []
        right["result"]["turns"] = 4
        value = compare_runs(left, right)
        self.assertIsNone(value["right"]["metrics"]["requests"])
        self.assertIsNone(value["metrics_delta"]["requests"])

    def test_request_count_counts_starts_instead_of_highest_turn(self):
        left, right = self.pair()
        right["events"] = [*request(turn=1, size=100, elapsed=10), *request(turn=3, size=200, elapsed=20)]
        right["result"]["turns"] = 2
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["metrics"]["requests"], 2)
        self.assertIsNone(value["right"]["metrics"]["request_bytes"])
        self.assertIsNone(value["right"]["metrics"]["elapsed_ms"])
        self.assertIn("RECORD_INVALID", value["notes"])
        right["events"] = [*request(turn=1, size=100, elapsed=10), *request(turn=2, size=200, elapsed=20)]
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["metrics"]["request_bytes"], 300)
        self.assertEqual(value["right"]["metrics"]["elapsed_ms"], 30)

    def test_fully_evidenced_before_send_refusal_has_zero_attempt_totals(self):
        left, right = self.pair()
        right["metadata"]["state"] = "REFUSED"
        right["result"].update(status="REFUSED", reason="REQUEST_SIZE_LIMIT", turns=0)
        right["result_sha256"] = digest(right["result"])
        right["events"] = [{"index": 0, "kind": "request_refused", "value": {"turn": 1, "diagnostics": {
            "format": "outlands-request-preflight-v1", "reason": "REQUEST_SIZE_LIMIT", "request_bytes": 131073,
            "limit_bytes": 131072, "chat_request_sent": False, "new_hold_created": False}}}]
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["metrics"], {"requests": 0, "request_bytes": 0,
            "elapsed_ms": 0, "measured_requests": 0, "elapsed_requests": 0, "complete": True})
        self.assertEqual(value["metrics_delta"], {"requests": -1, "request_bytes": -1000, "elapsed_ms": -200})
        right["metadata"]["state"] = "FAILED"
        right["result"]["status"] = "FAILED"
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["metrics"]["requests"], 0)
        self.assertTrue(value["right"]["metrics"]["complete"])
        right["events"][0]["value"]["diagnostics"]["chat_request_sent"] = True
        value = compare_runs(left, right)
        self.assertIsNone(value["right"]["metrics"]["requests"])
        self.assertFalse(value["right"]["metrics"]["complete"])

    def test_missing_finish_withholds_elapsed_and_all_measurement_deltas(self):
        left, right = self.pair()
        right["events"] = request()[:2]
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["metrics"]["request_bytes"], 1000)
        self.assertIsNone(value["right"]["metrics"]["elapsed_ms"])
        self.assertFalse(value["right"]["metrics"]["complete"])
        self.assertIsNone(value["metrics_delta"]["request_bytes"])

    def test_event_corruption_and_duplicate_starts_preserve_known_counts_only(self):
        left, right = self.pair()
        right["events"] = [request()[0], *request()]
        value = compare_runs(left, right)
        metrics = value["right"]["metrics"]
        self.assertEqual((metrics["requests"], metrics["measured_requests"], metrics["elapsed_requests"]), (1, 1, 1))
        self.assertIsNone(metrics["request_bytes"])
        self.assertIsNone(metrics["elapsed_ms"])
        self.assertIn("RECORD_INVALID", value["notes"])
        self.assertIn("INCOMPLETE_RECORDS", value["differences"])

    def test_event_limit_marks_partial_totals_and_never_reads_past_limit(self):
        left, right = self.pair()
        right["events"] = [*request(), *[{"index": index + 200, "kind": "other", "value": {}} for index in range(254)]]
        value = compare_runs(left, right)
        self.assertIn("EVENT_LIMIT", value["notes"])
        self.assertIsNone(value["right"]["metrics"]["request_bytes"])
        self.assertEqual(value["right"]["metrics"]["requests"], 1)

    def test_event_envelope_corruption_and_duplicate_indexes_are_not_complete(self):
        changes = [lambda event: event.pop("index"), lambda event: event.update(index=True),
                   lambda event: event.update(index=-1), lambda event: event.update(kind=7),
                   lambda event: event.update(value=[])]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                left, right = self.pair()
                change(right["events"][1])
                value = compare_runs(left, right)
                self.assertIn("RECORD_INVALID", value["notes"])
                self.assertFalse(value["right"]["metrics"]["complete"])
                self.assertIsNone(value["right"]["metrics"]["request_bytes"])
        left, right = self.pair()
        right["events"][-1]["index"] = right["events"][0]["index"]
        self.assertIn("RECORD_INVALID", compare_runs(left, right)["notes"])

    def test_valid_unknown_event_kind_is_ignored_without_leaking_its_fields(self):
        left, right = self.pair()
        right["events"].append({"index": 200, "kind": "invented_future_event", "value": {"source": "private-hidden-value"}})
        value = compare_runs(left, right)
        self.assertTrue(value["comparable"])
        self.assertTrue(value["right"]["metrics"]["complete"])
        self.assertNotIn("private-hidden-value", json.dumps(value))

    def test_result_counter_and_request_turn_gaps_withhold_metric_totals(self):
        for events, count in ((request(turn=2), 1), (request(), 2)):
            left, right = self.pair()
            right["events"] = events
            right["result"]["turns"] = count
            value = compare_runs(left, right)
            self.assertEqual(value["right"]["metrics"]["requests"], 1)
            self.assertIsNone(value["right"]["metrics"]["elapsed_ms"])
            self.assertFalse(value["right"]["metrics"]["complete"])
            self.assertIn("RECORD_INVALID", value["notes"])

    def test_metric_aggregate_above_safe_integer_is_unknown(self):
        left, right = self.pair()
        right["events"] = [*request(turn=1, elapsed=MAX_SAFE), *request(turn=2, elapsed=MAX_SAFE)]
        right["result"]["turns"] = 2
        value = compare_runs(left, right)
        self.assertIsNone(value["right"]["metrics"]["elapsed_ms"])
        self.assertFalse(value["right"]["metrics"]["complete"])

    def test_missing_sections_are_unknown_even_when_actual_raw_hash_survives(self):
        left, right = self.pair()
        right.update(task=None, metadata=None, result=None, events=[], patch=None, notes=["RECORD_INVALID"])
        value = compare_runs(left, right)
        summary = value["right"]
        self.assertEqual(summary["task_integrity"], "UNAVAILABLE")
        self.assertIsNotNone(summary["task_sha256"])
        self.assertIsNone(summary["goal"])
        self.assertEqual(summary["files"], [])
        self.assertEqual(summary["checks"], [])
        self.assertIsNone(value["patch_difference"]["text"])
        self.assertIn("INCOMPLETE_RECORDS", value["differences"])

    def test_metadata_identity_goal_and_loader_corruption_block_comparability(self):
        for change in (lambda side: side["metadata"].update(id="c" * 16),
                       lambda side: side["metadata"].update(goal="Not the saved task goal."),
                       lambda side: side.update(notes=["RECORD_LIMIT"])):
            left, right = self.pair()
            change(right)
            value = compare_runs(left, right)
            self.assertFalse(value["comparable"])
            self.assertIn("INCOMPLETE_RECORDS", value["differences"])

    def test_unknown_fields_reasons_statuses_and_private_exception_text_never_pass_through(self):
        left, right = self.pair()
        secret = "private-secret /invented/account/source.py"
        right["metadata"].update(source=secret, process_stamp=secret, state=secret)
        right["result"].update(reason=secret, exception=secret, response=secret)
        right["events"].append({"kind": "provider_failure", "value": {"error": secret, "prompt": secret}})
        right["notes"].append(secret)
        value = compare_runs(left, right)
        self.assertNotIn(secret, json.dumps(value))
        self.assertIsNone(value["right"]["state"])
        self.assertIsNone(value["right"]["result_reason"])
        self.assertNotIn("source", value["right"])
        self.assertNotIn("output", value["right"]["final_checks"][0])

    def test_check_rows_missing_values_are_null_and_invalid_values_are_flagged(self):
        left, right = self.pair()
        right["events"] = [{"index": 0, "kind": "baseline_checks", "value": {"unit": {"exit_code": -9}}},
            {"index": 1, "kind": "independent_final_checks", "value": {"unit": {"tests_ran": True, "timed_out": "private"}}}]
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["baseline_checks"][0]["exit_code"], -9)
        self.assertIsNone(value["right"]["baseline_checks"][0]["tests_ran"])
        self.assertIsNone(value["right"]["final_checks"][0]["tests_ran"])
        self.assertIsNone(value["right"]["final_checks"][0]["timed_out"])
        self.assertIn("RECORD_INVALID", value["notes"])

    def test_patch_fingerprint_mismatch_is_explicit(self):
        left, right = self.pair()
        right["result"]["patch_sha256"] = "f" * 64
        value = compare_runs(left, right)
        self.assertFalse(value["right"]["patch"]["matches_recorded"])
        self.assertIn("PATCH_FINGERPRINT_MISMATCH", value["notes"])
        self.assertFalse(value["comparable"])

    def test_loader_truncation_note_remains_visible_when_patch_is_unavailable(self):
        left, right = self.pair()
        right.update(patch=None, patch_sha256=None, notes=["PATCH_TRUNCATED", "RECORD_LIMIT"])
        value = compare_runs(left, right)
        self.assertIsNone(value["right"]["patch"]["text"])
        self.assertTrue(value["right"]["patch"]["truncated"])

    def test_unreconciled_saved_metadata_and_result_status_are_both_preserved(self):
        left, right = self.pair()
        right["metadata"]["state"] = "RUNNING"
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["state"], "RUNNING")
        self.assertEqual(value["right"]["result_status"], "REVIEW_READY")
        self.assertTrue(value["comparable"])

    def test_unicode_patch_clipping_preserves_complete_code_points(self):
        left, right = self.pair()
        patch_text(left, "界" * 3000)
        patch_text(right, "界" * 3000)
        value = compare_runs(left, right)
        self.assertEqual(value["left"]["patch"]["text"], "界" * 2730)
        self.assertTrue(value["left"]["patch"]["truncated"])
        self.assertIn("PATCH_TRUNCATED", value["notes"])
        self.assertTrue(value["comparable"])
        self.assertEqual(value["patch_difference"]["text"], "")

    def test_difference_uses_full_patch_even_when_display_prefixes_are_equal(self):
        left, right = self.pair()
        patch_text(left, "x" * 9000 + "\nold\n")
        patch_text(right, "x" * 9000 + "\nnew\n")
        value = compare_runs(left, right)
        self.assertEqual(value["left"]["patch"]["text"], value["right"]["patch"]["text"])
        self.assertIn("-old", value["patch_difference"]["text"])
        self.assertIn("+new", value["patch_difference"]["text"])

    def test_difference_byte_and_line_bounds_and_no_newline_marker(self):
        left, right = self.pair()
        patch_text(left, "".join("left😀 %s\n" % i for i in range(1000)))
        patch_text(right, "".join("right😀 %s\n" % i for i in range(1000)))
        value = compare_runs(left, right)
        difference = value["patch_difference"]
        self.assertTrue(difference["truncated"])
        self.assertLessEqual(len(difference["text"].encode("utf-8")), 16384)
        self.assertLessEqual(len(difference["text"].splitlines()), 240)
        for side in (value["left"], value["right"]):
            self.assertLessEqual(len(side["patch"]["text"].encode("utf-8")), 8192)
        self.assertLessEqual(len((json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")), 131072)
        patch_text(left, "same")
        patch_text(right, "same\n")
        value = compare_runs(left, right)
        self.assertIn("No newline at end of file", value["patch_difference"]["text"])

    def test_oversized_invalid_unicode_and_missing_patch_are_unavailable(self):
        for raw in ("x" * 65537, "😀" * 20000, "\ud800", None):
            with self.subTest(raw_type=type(raw).__name__):
                left, right = self.pair()
                right["patch"] = raw
                value = compare_runs(left, right)
                self.assertIsNone(value["right"]["patch"]["text"])
                self.assertIsNone(value["patch_difference"]["text"])
                self.assertFalse(value["comparable"])

    def test_global_serialized_output_limit_refuses_with_fixed_code(self):
        left, right = self.pair()
        patch_text(left, "\x7f" * 16000 + "\n")
        patch_text(right, "\x7f" * 16000 + "z\n")
        with self.assertRaises(Refused) as caught:
            compare_runs(left, right)
        self.assertEqual(caught.exception.args, ("COMPARE_OUTPUT_LIMIT",))

    def test_file_union_is_sorted_and_at_most_64_rows(self):
        left, right = self.pair()
        for side, prefix in ((left, "left"), (right, "right")):
            protected = "test_" + prefix + ".py"
            side["task"]["files"] = {protected: "a" * 64, **{prefix + str(i) + ".py": "b" * 64 for i in range(31)}}
            side["task"]["editable"] = [prefix + "0.py"]
            side["task"]["checks"] = {"unit": protected}
            repin(side)
        value = compare_runs(left, right)
        self.assertEqual(len(value["files"]), 64)
        self.assertEqual([row["path"] for row in value["files"]], sorted(row["path"] for row in value["files"]))

    def test_invalid_tasks_and_history_shaped_inputs_cannot_become_valid_evidence(self):
        left, right = self.pair()
        right["task"]["files"] = {"../outside.py": "a" * 64}
        value = compare_runs(left, right)
        self.assertEqual(value["right"]["task_integrity"], "UNAVAILABLE")
        self.assertEqual(value["right"]["files"], [])
        history_row = {"id": "b" * 16, "project_name": "History label", "goal": "History goal", "state": "FAILED", "created": 1}
        value = compare_runs(left, history_row)
        self.assertIsNone(value["right"]["goal"])
        self.assertEqual(value["right"]["files"], [])
        self.assertIn("INCOMPLETE_RECORDS", value["differences"])

    def test_ids_are_distinct_lowercase_saved_run_ids(self):
        left, right = self.pair()
        for bad in (None, True, "x", "a" * 17, "A" * 16, "../outside"):
            with self.subTest(bad=bad), self.assertRaises(Refused) as caught:
                compare_runs(left, {**right, "id": bad})
            self.assertEqual(caught.exception.args, ("COMPARE_IDS",))
        with self.assertRaisesRegex(Refused, "COMPARE_IDS"):
            compare_runs(left, left)

    def test_results_and_nested_specs_do_not_mutate_inputs(self):
        left, right = self.pair(java=True)
        before = copy.deepcopy((left, right))
        value = compare_runs(left, right)
        self.assertEqual((left, right), before)
        value["left"]["checks"][0]["spec"]["sources"].append("not-original.java")
        value["left"]["files"][0]["path"] = "changed result"
        self.assertEqual((left, right), before)

    def test_comparison_makes_no_filesystem_network_process_or_execution_calls(self):
        left, right = self.pair()
        with patch("builtins.open", side_effect=AssertionError("filesystem")), \
                patch("os.open", side_effect=AssertionError("filesystem")), \
                patch("pathlib.Path.open", side_effect=AssertionError("filesystem")), \
                patch("subprocess.Popen", side_effect=AssertionError("process")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("builtins.exec", side_effect=AssertionError("execution")):
            self.assertTrue(compare_runs(left, right)["comparable"])


if __name__ == "__main__":
    unittest.main()
