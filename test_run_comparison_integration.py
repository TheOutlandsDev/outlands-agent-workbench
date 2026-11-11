"""Saved-evidence comparison fixtures and offline controller/HTTP regressions."""

import copy
import io
import json
import re
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from workbench import Manager, init_demo, make_handler


RUN_IDS = {
    "python_ok": "1111111111111111",
    "python_failed": "2222222222222222",
    "python_uncertain": "3333333333333333",
    "python_legacy": "4444444444444444",
    "java_ok": "5555555555555555",
    "java_failed": "6666666666666666",
    "corrupt": "7777777777777777",
    "python_running": "8888888888888888",
}
PRIVATE_SENTINEL = "invented-private-comparison-sentinel"


def python_task():
    return {
        "format": "outlands-coding-agent-v2", "goal": "Correct the invented selected sum.",
        "files": {"sum.py": sha(b"def add(a, b): return a - b\n"),
                  "test_sum.py": sha(b"# invented protected tests\n")},
        "editable": ["sum.py"],
        "checks": {"unit": {"kind": "python-unittest", "pattern": "test_sum.py"}},
        "max_turns": 12, "request_seconds": 120,
    }


def java_task():
    return {
        "format": "outlands-coding-agent-v2", "goal": "Correct the invented selected Java sum.",
        "files": {"sample/Sum.java": sha(b"package sample; class Sum {}\n"),
                  "sample/SumTest.java": sha(b"package sample; class SumTest {}\n")},
        "editable": ["sample/Sum.java"],
        "checks": {"unit": {"kind": "java-main", "sources": ["sample/Sum.java", "sample/SumTest.java"],
                            "main_class": "sample.SumTest"}},
        "max_turns": 12, "request_seconds": 120,
    }


def check_row(passed=True, java=False):
    return {"exit_code": 0 if passed else 1, "tests_ran": 1 if java else 4,
            "timed_out": False, "output_limited": False, "infrastructure_error": False,
            "kind": "java-main" if java else "python-unittest", "output": PRIVATE_SENTINEL}


def seed_saved_run(manager, run_id, task=None, *, project="arithmetic", project_name="Invented Python",
                   state="REVIEW_READY", reason=None, created=100, legacy=False, patch_text=None,
                   request_bytes=4000, elapsed_ms=250, before_send=False):
    """Write invented saved JSON directly; never run a session, check or provider.

    Returns the run directory. Public preview/QA callers may supply their own
    valid task, display names, outcome, timings and review patch text.
    """
    task = copy.deepcopy(task if task is not None else python_task())
    task_raw = canonical(task)
    java = any(isinstance(spec, dict) and spec.get("kind") == "java-main" for spec in task["checks"].values())
    if reason is None:
        reason = {"REVIEW_READY": "CHECKS_PASSED", "UNCERTAIN": "PROVIDER_HEADER_TIMEOUT"}.get(state, "FINAL_CHECKS_FAILED")
    if patch_text is None:
        patch_text = "--- a/sum.py\n+++ b/sum.py\n@@ -1 +1 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b\n" if not java else "--- a/sample/Sum.java\n+++ b/sample/Sum.java\n@@ -1 +1 @@\n-class Sum {}\n+class Sum { /* invented correction */ }\n"
    run = manager.run_path(run_id)
    run.mkdir(mode=0o700)
    write_new(manager.data / "tasks" / (run_id + ".json"), task_raw)
    metadata = {"id": run_id, "project": project, "project_name": project_name, "source": str(manager.projects["arithmetic"]["source"]),
                "goal": task["goal"], "backend": "ollama", "model": "invented-local-model",
                "created": created, "finished": created + 1, "state": state, "pid": 99999999,
                "process_stamp": PRIVATE_SENTINEL, "private_extra": PRIVATE_SENTINEL}
    if not legacy:
        metadata.update(task_sha256=sha(task_raw), project_task_sha256=sha(task_raw))
    write_new(manager.meta_path(run_id), canonical(metadata))
    result = {"format": task["format"], "status": state, "reason": reason, "backend": "ollama", "ai_inference": True,
              "turns": 0 if before_send else 1,
              "files": {name: {"before": digest, "after": digest} for name, digest in task["files"].items()},
              "patch_sha256": sha(patch_text.encode()), "source_adopted": False, "private_extra": PRIVATE_SENTINEL}
    write_new(run / "result.json", canonical(result))
    write_new(run / "changes.diff", patch_text.encode())
    events = [{"kind": "baseline_checks", "value": {"unit": check_row(False, java)}}]
    if before_send:
        events.append({"kind": "request_refused", "value": {"turn": 1, "diagnostics": {
            "format": "outlands-request-preflight-v1", "reason": "REQUEST_SIZE_LIMIT",
            "request_bytes": 131073, "limit_bytes": 131072, "chat_request_sent": False, "new_hold_created": False}}})
    else:
        started = {"turn": 1}
        if not legacy:
            started["diagnostics"] = {"format": "outlands-request-diagnostics-v1", "started_at_ms": 1800000000000,
                                      "timeout_seconds": task["request_seconds"], "request_bytes": request_bytes}
        events.append({"kind": "request_started", "value": started})
        if state != "UNCERTAIN":
            events.append({"kind": "response", "value": {"role": "assistant", "content": PRIVATE_SENTINEL}})
        if not legacy:
            events.append({"kind": "request_finished", "value": {"turn": 1, "diagnostics": {
                "format": "outlands-request-diagnostics-v1", "finished_at_ms": 1800000000000 + elapsed_ms,
                "elapsed_ms": elapsed_ms, "phase": "HEADER" if state == "UNCERTAIN" else "COMPLETE",
                "outcome": "ERROR" if state == "UNCERTAIN" else "RESPONSE_RECORDED",
                "reason": reason if state == "UNCERTAIN" else None,
                "error_category": "TIMEOUT" if state == "UNCERTAIN" else None,
                "metrics": {"eval_count": 17, "private_extra": PRIVATE_SENTINEL}}}})
    if state != "UNCERTAIN" and not before_send:
        events.append({"kind": "independent_final_checks", "value": {"unit": check_row(state == "REVIEW_READY", java)}})
    for index, event in enumerate(events):
        write_new(run / ("event-%03d.json" % index), canonical({"index": index, **event}))
    return run


def populate_saved_histories(manager):
    """Populate a fresh Manager's private store for persistent offline preview/QA.

    Files are additive. Existing IDs or hold bytes cause a failure, rather than
    being overwritten. Every record is invented; no inference is performed.
    """
    ids = dict(RUN_IDS)
    seed_saved_run(manager, ids["python_ok"], created=100)
    seed_saved_run(manager, ids["python_failed"], state="FAILED", created=101, request_bytes=5000, elapsed_ms=400)
    seed_saved_run(manager, ids["python_uncertain"], state="UNCERTAIN", created=102)
    seed_saved_run(manager, ids["python_legacy"], legacy=True, state="FAILED", created=103)
    seed_saved_run(manager, ids["java_ok"], java_task(), project="java", project_name="Invented Java", created=104)
    seed_saved_run(manager, ids["java_failed"], java_task(), project="java", project_name="Invented Java", state="FAILED", created=105)
    corrupt = seed_saved_run(manager, ids["corrupt"], state="FAILED", created=106)
    (manager.data / "tasks" / (ids["corrupt"] + ".json")).write_bytes(b"{invalid saved task\n")
    (corrupt / "result.json").write_bytes(b"{invalid saved result\n")
    (corrupt / "changes.diff").write_bytes(b"\xff")
    (corrupt / "event-000.json").write_bytes(b"{invalid saved event\n")
    running = seed_saved_run(manager, ids["python_running"], state="RUNNING", reason="UNFINISHED", created=107)
    for name in ["result.json", "changes.diff", "event-002.json", "event-003.json", "event-004.json"]:
        (running / name).unlink()
    write_new(manager.data / "state/hold.json", canonical({"state": "REQUEST_UNSETTLED",
        "run": str(manager.run_path(ids["python_uncertain"])), "turn": 1}))
    return ids


@contextmanager
def comparison_fixture(seed=True):
    """Yield (temporary root, Manager, named IDs) for saved-evidence-only QA."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", "invented-local-model")
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        ids = populate_saved_histories(manager) if seed else {}
        try:
            yield root, manager, ids
        finally:
            manager.close()


def private_hashes(root):
    return {path.relative_to(root).as_posix(): sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


@contextmanager
def saved_only_guard(manager):
    """Make every live-state, execution and provider path fail if reached."""
    with ExitStack() as stack:
        for name in ["history", "refresh", "admission", "owns_active", "request_hold", "workspace_receipt",
                     "start", "stop", "create_workspace", "project_refresh_preview", "project_refresh_save"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("comparison reached " + name)))
        for name in ["workbench.process_stamp", "workbench.subprocess.Popen", "agent.Session.checks",
                     "agent.Ollama.request", "agent.Ollama.preflight", "agent.ScriptedDemo.request",
                     "isolation.check", "java_check.check", "socket.socket"]:
            stack.enter_context(patch(name, side_effect=AssertionError("comparison reached " + name)))
        yield


def output_notes(value):
    return set(value.get("notes", [])) | set(value.get("left", {}).get("notes", [])) | set(value.get("right", {}).get("notes", []))


class ComparisonIntegrationTests(unittest.TestCase):
    def compare_pair(self, manager, ids):
        return manager.compare(ids["python_ok"], ids["python_failed"])

    def test_saved_python_and_java_outcomes_leave_all_bytes_and_hold_unchanged(self):
        with comparison_fixture() as (root, manager, ids):
            before = private_hashes(root)
            hold = (manager.data / "state/hold.json").read_bytes()
            with saved_only_guard(manager):
                inventory = manager.comparison_history()
                python = self.compare_pair(manager, ids)
                java = manager.compare(ids["java_ok"], ids["java_failed"])
                uncertain = manager.compare(ids["python_ok"], ids["python_uncertain"])
            self.assertEqual(before, private_hashes(root))
            self.assertEqual((manager.data / "state/hold.json").read_bytes(), hold)
            self.assertEqual({row["id"] for row in inventory["runs"]}, set(ids.values()))
            self.assertTrue(python["comparable"])
            self.assertTrue(java["comparable"])
            self.assertEqual(python["left"]["result_status"], "REVIEW_READY")
            self.assertEqual(python["right"]["result_status"], "FAILED")
            self.assertEqual(java["left"]["final_checks"][0]["kind"], "java-main")
            self.assertEqual(uncertain["right"]["state"], "UNCERTAIN")
            self.assertEqual(uncertain["right"]["result_reason"], "PROVIDER_HEADER_TIMEOUT")
            self.assertEqual(python["left"]["metrics"]["requests"], 1)
            self.assertEqual(python["metrics_delta"], {"requests": 0, "request_bytes": 1000, "elapsed_ms": 150})

    def test_comparison_never_reads_live_selected_or_unselected_source(self):
        import workbench
        with comparison_fixture() as (root, manager, ids):
            source = manager.projects["arithmetic"]["source"]
            for path in source.iterdir():
                path.unlink()
            source.rmdir()
            read = workbench.read_file

            def guarded_read(directory, *args, **kwargs):
                selected = Path(directory)
                self.assertFalse(selected == source or source in selected.parents)
                return read(directory, *args, **kwargs)

            before = private_hashes(root)
            with saved_only_guard(manager), patch("workbench.read_file", side_effect=guarded_read):
                value = self.compare_pair(manager, ids)
            self.assertTrue(value["comparable"])
            self.assertEqual(before, private_hashes(root))

    def test_unknown_fields_and_private_text_never_escape_selected_dtos(self):
        with comparison_fixture() as (_, manager, ids), saved_only_guard(manager):
            value = self.compare_pair(manager, ids)
            encoded = json.dumps(value)
            self.assertNotIn(PRIVATE_SENTINEL, encoded)
            self.assertNotIn(str(manager.data), encoded)
            self.assertNotIn(str(manager.projects["arithmetic"]["source"]), encoded)
            self.assertEqual(set(value), {"version", "left", "right", "comparable", "differences", "files", "patch_difference", "metrics_delta", "notes"})
            for side in [value["left"], value["right"]]:
                self.assertEqual(set(side), {"id", "project", "project_name", "goal", "state", "backend", "model", "created", "finished", "task_sha256", "recorded_task_sha256", "project_task_sha256", "task_integrity", "files", "checks", "max_turns", "request_seconds", "result_status", "result_reason", "result_sha256", "baseline_checks", "final_checks", "metrics", "patch", "notes"})
                self.assertEqual(side["task_integrity"], "MATCH")
                for row in side["baseline_checks"] + side["final_checks"]:
                    self.assertEqual(set(row), {"name", "kind", "exit_code", "tests_ran", "timed_out", "output_limited", "infrastructure_error"})

    def test_legacy_fingerprints_and_timings_stay_unknown(self):
        with comparison_fixture() as (_, manager, ids), saved_only_guard(manager):
            value = manager.compare(ids["python_ok"], ids["python_legacy"])
            side = value["right"]
            self.assertEqual(side["task_integrity"], "NOT_RECORDED")
            self.assertIsNone(side["recorded_task_sha256"])
            self.assertEqual(side["metrics"]["requests"], 1)
            self.assertIsNone(side["metrics"]["request_bytes"])
            self.assertIsNone(side["metrics"]["elapsed_ms"])
            self.assertFalse(side["metrics"]["complete"])
            self.assertIsNone(value["metrics_delta"]["request_bytes"])
            self.assertIsNone(value["metrics_delta"]["elapsed_ms"])
            self.assertIn("LEGACY_TASK_FINGERPRINT", output_notes(value))

    def test_corrupt_and_missing_optional_records_are_unknown_not_repaired(self):
        with comparison_fixture() as (root, manager, ids):
            run = manager.run_path(ids["python_failed"])
            (manager.data / "tasks" / (ids["python_failed"] + ".json")).unlink()
            for path in list(run.iterdir()):
                path.unlink()
            before = private_hashes(root)
            with saved_only_guard(manager):
                missing = self.compare_pair(manager, ids)
                corrupt = manager.compare(ids["python_ok"], ids["corrupt"])
            self.assertEqual(before, private_hashes(root))
            for value in [missing, corrupt]:
                self.assertFalse(value["comparable"])
                self.assertIn("INCOMPLETE_RECORDS", value["differences"])
                self.assertEqual(value["right"]["task_integrity"], "UNAVAILABLE")
                self.assertIsNone(value["right"]["result_status"])
                self.assertIsNone(value["right"]["result_reason"])
                self.assertIsNone(value["right"]["patch"]["text"])
            self.assertIsNone(missing["right"]["metrics"]["requests"])
            self.assertIn("RECORD_MISSING", output_notes(missing))
            self.assertIn("RECORD_INVALID", output_notes(corrupt))

    def test_unrecognized_saved_status_reason_and_check_values_stay_unknown(self):
        with comparison_fixture() as (_, manager, ids):
            meta_path = manager.meta_path(ids["python_failed"])
            metadata = json.loads(meta_path.read_bytes()); metadata.update(state=PRIVATE_SENTINEL)
            meta_path.write_bytes(canonical(metadata))
            result_path = manager.run_path(ids["python_failed"]) / "result.json"
            result = json.loads(result_path.read_bytes()); result.update(status=PRIVATE_SENTINEL, reason=PRIVATE_SENTINEL)
            result_path.write_bytes(canonical(result))
            event = manager.run_path(ids["python_failed"]) / "event-000.json"
            event.write_bytes(canonical({"index": 0, "kind": "baseline_checks", "value": {"unit": {"exit_code": True, "tests_ran": PRIVATE_SENTINEL, "timed_out": 0}}}))
            with saved_only_guard(manager):
                value = self.compare_pair(manager, ids)
            side = value["right"]
            self.assertIsNone(side["state"])
            self.assertIsNone(side["result_status"])
            self.assertIsNone(side["result_reason"])
            row = side["baseline_checks"][0]
            self.assertIsNone(row["exit_code"])
            self.assertIsNone(row["tests_ran"])
            self.assertIsNone(row["timed_out"])
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))

    def test_invalid_unknown_and_same_run_ids_refuse_without_live_actions(self):
        with comparison_fixture() as (root, manager, ids):
            before = private_hashes(root)
            with saved_only_guard(manager):
                for left, right in [("../outside", ids["python_ok"]), ("/fictional/path", ids["python_ok"]),
                                    ("g" * 16, ids["python_ok"]), (None, ids["python_ok"]),
                                    (ids["python_ok"], ids["python_ok"])]:
                    with self.subTest(left=left), self.assertRaisesRegex(Refused, "^COMPARE_IDS$"):
                        manager.compare(left, right)
                with self.assertRaisesRegex(Refused, "^COMPARE_RUN_UNKNOWN$"):
                    manager.compare(ids["python_ok"], "ffffffffffffffff")
            self.assertEqual(before, private_hashes(root))

    def test_history_inventory_is_bounded_latest_within_inspected_set(self):
        import workbench
        with comparison_fixture(seed=False) as (root, manager, _):
            for number in range(205):
                run_id = f"{number:016x}"
                write_new(manager.meta_path(run_id), canonical({"id": run_id, "project_name": "Invented inventory", "goal": "Invented goal", "created": number, "state": "FAILED"}))
            write_new(manager.data / "jobs/not-a-run.json", canonical({"private_extra": PRIVATE_SENTINEL}))
            read, inspected = workbench.read_file, []

            def count_read(directory, name, *args, **kwargs):
                if Path(directory) == manager.data and re.fullmatch(r"jobs/[0-9a-f]{16}[.]json", name):
                    inspected.append(Path(name).stem)
                return read(directory, name, *args, **kwargs)

            before = private_hashes(root)
            with saved_only_guard(manager), patch("workbench.read_file", side_effect=count_read):
                value = manager.comparison_history()
            self.assertEqual(before, private_hashes(root))
            self.assertEqual(value["limit"], 100)
            self.assertTrue(value["truncated"])
            self.assertEqual(len(value["runs"]), 100)
            self.assertLessEqual(len(inspected), 200)
            self.assertEqual([row["id"] for row in value["runs"]], sorted(set(inspected), reverse=True)[:100])
            self.assertTrue(value["notes"])
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))

    def test_event_count_limit_keeps_measurements_explicitly_incomplete(self):
        with comparison_fixture() as (root, manager, ids):
            run = manager.run_path(ids["python_failed"])
            for index in range(6, 263):
                write_new(run / ("event-%03d.json" % index), canonical({"index": index, "kind": "response", "value": {"content": PRIVATE_SENTINEL}}))
            before = private_hashes(root)
            with saved_only_guard(manager):
                value = self.compare_pair(manager, ids)
            self.assertEqual(before, private_hashes(root))
            self.assertFalse(value["comparable"])
            self.assertIn("EVENT_LIMIT", output_notes(value))
            self.assertFalse(value["right"]["metrics"]["complete"])
            self.assertIsNone(value["right"]["metrics"]["request_bytes"])
            self.assertIsNone(value["right"]["metrics"]["elapsed_ms"])

    def test_aggregate_event_byte_limit_is_bounded_and_flagged(self):
        with comparison_fixture() as (_, manager, ids):
            run = manager.run_path(ids["python_failed"])
            for index in range(6, 16):
                write_new(run / ("event-%03d.json" % index), canonical({"index": index, "kind": "response", "value": {"content": "x" * 240000}}))
            with saved_only_guard(manager):
                value = self.compare_pair(manager, ids)
            self.assertFalse(value["comparable"])
            self.assertTrue(output_notes(value) & {"RECORD_LIMIT", "EVENT_LIMIT"})
            self.assertFalse(value["right"]["metrics"]["complete"])
            self.assertIsNone(value["metrics_delta"]["request_bytes"])
            self.assertLessEqual(len(canonical(value)), 131072)

    def test_per_section_limits_make_oversized_sections_unavailable(self):
        for section in ["metadata", "task", "result", "event", "patch"]:
            with self.subTest(section=section), comparison_fixture() as (root, manager, ids):
                run = manager.run_path(ids["python_failed"])
                target = {"metadata": manager.meta_path(ids["python_failed"]),
                          "task": manager.data / "tasks" / (ids["python_failed"] + ".json"),
                          "result": run / "result.json", "event": run / "event-000.json", "patch": run / "changes.diff"}[section]
                bound = 262144 if section == "event" else 65536 if section == "patch" else 32768
                target.write_bytes(b"x" * (bound + 1))
                before = private_hashes(root)
                with saved_only_guard(manager):
                    value = self.compare_pair(manager, ids)
                self.assertEqual(before, private_hashes(root))
                self.assertIn("RECORD_LIMIT", output_notes(value))
                self.assertFalse(value["comparable"])
                if section == "patch":
                    self.assertIsNone(value["right"]["patch"]["text"])
                if section == "task":
                    self.assertEqual(value["right"]["task_integrity"], "UNAVAILABLE")

    def test_symlink_and_hardlinked_optional_records_are_not_followed(self):
        for linked in ["symlink", "hardlink"]:
            with self.subTest(linked=linked), comparison_fixture() as (root, manager, ids):
                result_path = manager.run_path(ids["python_failed"]) / "result.json"
                outside = root / "invented-external-result.json"
                outside.write_bytes(canonical({"status": "REVIEW_READY", "reason": "CHECKS_PASSED", "private_extra": PRIVATE_SENTINEL}))
                result_path.unlink()
                if linked == "symlink":
                    result_path.symlink_to(outside)
                else:
                    result_path.hardlink_to(outside)
                before = private_hashes(root)
                with saved_only_guard(manager):
                    value = self.compare_pair(manager, ids)
                self.assertEqual(before, private_hashes(root))
                self.assertIsNone(value["right"]["result_status"])
                self.assertIn("RECORD_INVALID", output_notes(value))
                self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))

    def test_substituted_ancestor_stores_are_not_followed(self):
        import workbench
        outside_sentinel = "invented-outside-store-content-must-not-be-read"
        for section in ["jobs", "tasks", "runs"]:
            with self.subTest(section=section), comparison_fixture() as (root, manager, ids):
                store = manager.data / section
                retained = root / ("retained-original-" + section)
                store.rename(retained)
                outside = root / ("outside-" + section)
                outside.mkdir()
                for run_id in [ids["python_ok"], ids["python_failed"]]:
                    if section == "jobs":
                        metadata = json.loads((retained / (run_id + ".json")).read_bytes())
                        metadata["project_name"] = outside_sentinel
                        write_new(outside / (run_id + ".json"), canonical(metadata))
                    elif section == "tasks":
                        task = json.loads((retained / (run_id + ".json")).read_bytes())
                        task["goal"] = outside_sentinel
                        write_new(outside / (run_id + ".json"), canonical(task))
                    else:
                        folder = outside / run_id
                        folder.mkdir()
                        result = json.loads((retained / run_id / "result.json").read_bytes())
                        result["private_extra"] = outside_sentinel
                        write_new(folder / "result.json", canonical(result))
                        write_new(folder / "changes.diff", outside_sentinel.encode())
                store.symlink_to(outside, target_is_directory=True)
                read = workbench.read_file

                def guarded_read(directory, name, *args, **kwargs):
                    raw = read(directory, name, *args, **kwargs)
                    self.assertNotIn(outside_sentinel.encode(), raw)
                    return raw

                before = private_hashes(root)
                hold = (manager.data / "state/hold.json").read_bytes()
                with saved_only_guard(manager), patch("workbench.read_file", side_effect=guarded_read):
                    if section == "jobs":
                        with self.assertRaisesRegex(Refused, "^COMPARE_STORE_REFUSED$"):
                            self.compare_pair(manager, ids)
                        with self.assertRaisesRegex(Refused, "^COMPARE_STORE_REFUSED$"):
                            manager.comparison_history()
                    else:
                        value = self.compare_pair(manager, ids)
                        self.assertFalse(value["comparable"])
                        self.assertIn("RECORD_INVALID", output_notes(value))
                        self.assertNotIn(outside_sentinel, json.dumps(value))
                        for side in [value["left"], value["right"]]:
                            if section == "tasks":
                                self.assertEqual(side["task_integrity"], "UNAVAILABLE")
                                self.assertIsNone(side["task_sha256"])
                            else:
                                self.assertIsNone(side["result_status"])
                                self.assertIsNone(side["patch"]["text"])
                self.assertEqual(before, private_hashes(root))
                self.assertEqual((manager.data / "state/hold.json").read_bytes(), hold)

    def test_task_and_patch_fingerprint_mismatches_are_visible(self):
        with comparison_fixture() as (_, manager, ids):
            metadata_path = manager.meta_path(ids["python_failed"])
            metadata = json.loads(metadata_path.read_bytes()); metadata["task_sha256"] = "0" * 64
            metadata_path.write_bytes(canonical(metadata))
            patch_path = manager.run_path(ids["python_failed"]) / "changes.diff"
            patch_path.write_text("invented changed review patch\n")
            with saved_only_guard(manager):
                value = self.compare_pair(manager, ids)
            self.assertFalse(value["comparable"])
            self.assertEqual(value["right"]["task_integrity"], "MISMATCH")
            self.assertIn("TASK_FINGERPRINT_MISMATCH", value["differences"])
            self.assertIs(value["right"]["patch"]["matches_recorded"], False)
            self.assertIn("PATCH_FINGERPRINT_MISMATCH", output_notes(value))

    def test_patch_display_and_difference_have_unicode_safe_hard_limits(self):
        with comparison_fixture(seed=False) as (_, manager, _):
            left, right = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"
            seed_saved_run(manager, left, patch_text="😀 café left\n" * 3000)
            seed_saved_run(manager, right, patch_text="界 café right\n" * 3000)
            with saved_only_guard(manager):
                value = manager.compare(left, right)
            for side in [value["left"], value["right"]]:
                self.assertLessEqual(len(side["patch"]["text"].encode()), 8192)
                self.assertTrue(side["patch"]["truncated"])
            difference = value["patch_difference"]
            self.assertLessEqual(len(difference["text"].encode()), 16384)
            self.assertLessEqual(len(difference["text"].splitlines()), 240)
            self.assertTrue(difference["truncated"])
            self.assertLessEqual(len(canonical(value)), 131072)

    def test_explicit_before_send_refusal_is_the_only_evidenced_zero(self):
        with comparison_fixture(seed=False) as (_, manager, _):
            left, right = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"
            seed_saved_run(manager, left, before_send=True, state="FAILED", reason="REQUEST_SIZE_LIMIT")
            run = seed_saved_run(manager, right, state="FAILED")
            for path in run.glob("event-*.json"):
                path.unlink()
            with saved_only_guard(manager):
                value = manager.compare(left, right)
            self.assertEqual(value["left"]["metrics"]["requests"], 0)
            self.assertEqual(value["left"]["metrics"]["request_bytes"], 0)
            self.assertEqual(value["left"]["metrics"]["elapsed_ms"], 0)
            self.assertIsNone(value["right"]["metrics"]["requests"])
            self.assertIsNone(value["metrics_delta"]["requests"])


@contextmanager
def comparison_http_fixture():
    """Run real HTTP handlers in memory; no sockets, threads or server startup."""
    with comparison_fixture() as (root, manager, ids):
        handler_type = make_handler(manager, "invented-comparison-token", "http://127.0.0.1:8765")

        def request(path, headers=None):
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-comparison-token"}
            supplied.update(headers or {})
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "GET", path
            handler.request_version, handler.requestline = "HTTP/1.1", "GET " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, value in supplied.items():
                handler.headers[key] = value
            handler.rfile, handler.wfile = io.BytesIO(), io.BytesIO()
            handler.do_GET()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(raw)

        yield root, manager, ids, request


class ComparisonHTTPTests(unittest.TestCase):
    def test_history_and_comparison_get_contracts_are_saved_only(self):
        with comparison_http_fixture() as (root, manager, ids, request):
            before = private_hashes(root)
            with saved_only_guard(manager):
                code, history = request("/api/comparison-history")
                self.assertEqual(code, 200)
                self.assertEqual(len(history["runs"]), len(ids))
                code, value = request("/api/compare/" + ids["python_ok"] + "/" + ids["python_failed"])
                self.assertEqual(code, 200)
                self.assertEqual(value["version"], 1)
                self.assertTrue(value["comparable"])
            self.assertEqual(before, private_hashes(root))

    def test_comparison_http_session_host_and_cross_site_guards(self):
        with comparison_http_fixture() as (root, manager, ids, request):
            before = private_hashes(root)
            with saved_only_guard(manager):
                for path in ["/api/comparison-history", "/api/compare/" + ids["python_ok"] + "/" + ids["python_failed"]]:
                    for headers, error in [({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                                           ({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                                           ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        with self.subTest(path=path, error=error):
                            code, value = request(path, headers)
                            self.assertEqual((code, value["error"]), (403, error))
                code, value = request("/api/compare/" + ids["python_ok"] + "/" + ids["python_ok"])
                self.assertEqual((code, value["error"]), (409, "COMPARE_IDS"))
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()
