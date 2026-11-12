"""Invented decision receipts and read-only controller/HTTP qualification."""

import copy
import io
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from saved_run_review import review_saved_run
from test_run_comparison_integration import seed_saved_run
from test_saved_run_review_integration import private_inventory, review_fixture, review_guard, selected_request
from test_task_presets_integration import build_presets_manager
from workbench import Manager, make_handler


def receipt_value(manager, run_id, **updates):
    run = manager.run_path(run_id)
    result = json.loads((run / "result.json").read_bytes())
    return {"id": run_id, "result_sha256": sha(canonical(result)), "patch_sha256": sha((run / "changes.diff").read_bytes()),
            "verdict": "accepted", "note": "Invented saved decision — café e\u0301 🧪.\r\n<b>literal</b>\x00", "recorded": 100,
            "source_applied": False, **updates}


def write_receipt(manager, run_id, ordinal=0, **updates):
    path = manager.run_path(run_id) / ("review-%03d.json" % ordinal)
    write_new(path, canonical(receipt_value(manager, run_id, **updates)))
    return path


def populate_decision_histories(manager, fixtures):
    """Six invented cases per language; no worker/check/provider is executed."""
    cases = {}
    labels = [("unreviewed", "UNREVIEWED"), ("accepted", "ACCEPTED"), ("rejected", "REJECTED"),
              ("stale", "STALE"), ("unknown", "UNKNOWN"), ("formatted", "ACCEPTED")]
    for language_number, (language, fixture) in enumerate(fixtures.items(), 1):
        rows = {}
        for number, (label, expected) in enumerate(labels):
            identifier = format(language_number * 4096 + number, "016x")
            task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
            task["goal"] = "Invented " + language + " decision " + label + " — café e\u0301 🧪 <b>literal</b>."
            seed_saved_run(manager, identifier, task, project=fixture["project_id"],
                           project_name="Invented " + language + " decisions", created=200 + number)
            if label != "unreviewed":
                write_receipt(manager, identifier, verdict="rejected" if label == "rejected" else "accepted",
                              result_sha256="0" * 64 if label == "stale" else receipt_value(manager, identifier)["result_sha256"])
            if label == "unknown":
                write_receipt(manager, identifier, 1, source_applied=True, note="Invalid latest receipt; no older fallback.")
            if label == "formatted":
                path = manager.run_path(identifier) / "result.json"
                path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=2, ensure_ascii=False).encode())
            rows[label] = {"id": identifier, "expected_state": expected,
                           "seeded_observation": True, "latest_invalid_no_fallback": label == "unknown"}
        cases[language] = rows
    return cases


def build_decision_fixture(root, jdk=None):
    """Fresh owner-private invented projects for tests or guarded browser QA."""
    manager, fixtures = build_presets_manager(root, jdk)
    return manager, fixtures, populate_decision_histories(manager, fixtures)


def memory_review_http(manager):
    handler_type = make_handler(manager, "invented-decision-token", "http://127.0.0.1:8765")
    def request(value):
        raw = canonical(value)
        handler = handler_type.__new__(handler_type)
        handler.command, handler.path = "POST", "/api/run-history-review"
        handler.request_version, handler.requestline = "HTTP/1.1", "POST /api/run-history-review HTTP/1.1"
        handler.headers = Message()
        for key, item in {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "X-Workbench-Token": "invented-decision-token",
                          "Content-Type": "application/json", "Content-Length": str(len(raw))}.items(): handler.headers[key] = item
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.do_POST()
        head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        return int(head.split(b" ", 2)[1]), json.loads(body)
    return request


class SavedReviewDecisionIntegrationTests(unittest.TestCase):
    def response(self, root, manager, run_id):
        before = private_inventory(root)
        value = manager.run_history_review(selected_request(manager, run_id))
        self.assertEqual(set(value), {"version", "id", "record_sha256", "history_sha256", "evidence_sha256", "summary", "diagnostics", "decision"})
        self.assertEqual(value["version"], 2)
        self.assertEqual(before, private_inventory(root))
        self.assertLessEqual(len(canonical(value)), 65536)
        return value

    def test_invented_python_java_cases_cover_five_states_and_formatting_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manager, fixtures, cases = build_decision_fixture(root)
            try:
                with review_guard(manager):
                    for language, rows in cases.items():
                        for label, row in rows.items():
                            with self.subTest(language=language, label=label):
                                value = self.response(root, manager, row["id"])
                                self.assertEqual(value["decision"]["state"], row["expected_state"])
                                if label == "unknown": self.assertIsNone(value["decision"]["receipt"])
                                if label == "formatted":
                                    self.assertNotEqual(value["decision"]["current"]["result_sha256"], value["summary"]["result_sha256"])
            finally:
                manager.close()

    def test_latest_ordinal_controls_decision_and_preserves_full_unicode_control_note(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["python_ok"]
            write_receipt(manager, run_id, recorded=9007199254740991)
            note = " café e\u0301 🧪\x00\r\n<script>literal</script>\t "
            latest = write_receipt(manager, run_id, 1, verdict="rejected", recorded=1, note=note)
            value = self.response(root, manager, run_id)["decision"]
            self.assertEqual(value["state"], "REJECTED")
            self.assertEqual(value["receipt"]["name"], latest.name)
            self.assertEqual(value["receipt"]["note"], note)
            self.assertEqual(value["receipt"]["recorded"], 1)
            self.assertEqual(value["receipt"]["sha256"], sha(latest.read_bytes()))

    def test_invalid_latest_never_falls_back_to_an_older_valid_acceptance(self):
        for updates in [{"id": "f" * 16}, {"source_applied": True}, {"source_applied": 0}, {"recorded": True},
                        {"result_sha256": "bad"}, {"verdict": "Accepted"}, {"note": "\ud800"}, {"extra": True}]:
            with self.subTest(updates=updates), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]
                write_receipt(manager, run_id); write_receipt(manager, run_id, 1, **updates)
                value = self.response(root, manager, run_id)["decision"]
                self.assertEqual(value["state"], "UNKNOWN")
                self.assertIsNone(value["receipt"])
                self.assertIn("REVIEW_RECORD_INVALID", value["notes"])

    def test_invalid_older_record_keeps_valid_highest_observed_receipt_but_state_unknown(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["python_ok"]
            write_receipt(manager, run_id, source_applied=True)
            latest = write_receipt(manager, run_id, 1)
            value = self.response(root, manager, run_id)["decision"]
            self.assertEqual(value["state"], "UNKNOWN")
            self.assertEqual(value["receipt"]["name"], latest.name)

    def test_canonical_result_content_binding_is_distinct_from_raw_file_hash(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["python_ok"]
            write_receipt(manager, run_id)
            original = self.response(root, manager, run_id)
            path = manager.run_path(run_id) / "result.json"
            path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=3).encode())
            formatted = self.response(root, manager, run_id)
            self.assertEqual(formatted["decision"]["state"], "ACCEPTED")
            self.assertEqual(formatted["decision"]["current"], original["decision"]["current"])
            self.assertNotEqual(formatted["summary"]["result_sha256"], original["summary"]["result_sha256"])
            self.assertNotEqual(formatted["evidence_sha256"], original["evidence_sha256"])

    def test_stale_valid_pins_and_unknown_or_inconsistent_current_artifacts_are_distinct(self):
        for kind in ["stale-result", "stale-patch", "declaration", "missing-result", "invalid-patch"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]; run = manager.run_path(run_id)
                write_receipt(manager, run_id, **({"result_sha256": "0" * 64} if kind == "stale-result" else
                              {"patch_sha256": "0" * 64} if kind == "stale-patch" else {}))
                if kind == "declaration":
                    path = run / "result.json"; result = json.loads(path.read_bytes()); result["patch_sha256"] = "0" * 64
                    path.write_bytes(canonical(result))
                elif kind == "missing-result": (run / "result.json").unlink()
                elif kind == "invalid-patch": (run / "changes.diff").write_bytes(b"\xff")
                value = self.response(root, manager, run_id)["decision"]
                self.assertEqual(value["state"], "STALE" if kind.startswith("stale") else "UNKNOWN")
                if kind == "declaration": self.assertIn("CURRENT_ARTIFACTS_INCONSISTENT", value["notes"])

    def test_gapped_malformed_missing_and_partial_catalogs_never_claim_unreviewed(self):
        for kind in ["gap", "bad-extension", "over-range", "missing-run", "partial"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]; run = manager.run_path(run_id)
                if kind == "gap": write_receipt(manager, run_id, 1)
                elif kind in ["bad-extension", "over-range"]:
                    write_new(run / ("review-000.backup" if kind == "bad-extension" else "review-100.json"), b"private invalid name")
                elif kind == "missing-run":
                    for path in run.iterdir(): path.unlink()
                    run.rmdir()
                else:
                    for number in range(1025): write_new(run / ("invented-ignored-" + str(number)), b"ignored")
                    write_receipt(manager, run_id)
                value = self.response(root, manager, run_id)["decision"]
                self.assertEqual(value["state"], "UNKNOWN")
                self.assertFalse(value["catalog_complete"])

    def test_event_admission_limit_does_not_hide_a_later_decision_receipt(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["python_ok"]; run = manager.run_path(run_id)
            for number in range(300, 557):
                write_new(run / ("event-%03d.json" % number), canonical({"index": number, "kind": "invented", "value": {}}))
            write_receipt(manager, run_id)
            value = self.response(root, manager, run_id)
            self.assertIn("EVENT_LIMIT", value["summary"]["notes"])
            self.assertEqual(value["decision"]["state"], "ACCEPTED")
            self.assertTrue(value["decision"]["catalog_complete"])

    def test_malformed_and_limited_receipt_contents_remain_unknown_without_repair(self):
        for raw in [b'{"id":', b"[]", b"\xff", b"{}" + b" " * 32767]:
            with self.subTest(raw=raw[:20]), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                write_new(manager.run_path(ids["python_ok"]) / "review-000.json", raw)
                value = self.response(root, manager, ids["python_ok"])["decision"]
                self.assertEqual(value["state"], "UNKNOWN")
                self.assertEqual(value["inspected"], 1)
                self.assertIsNone(value["receipt"])

    def test_receipt_aggregate_reads_are_bounded_and_unread_receipts_are_safety_checked(self):
        for unsafe in [False, True]:
            with self.subTest(unsafe=unsafe), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]
                for number in range(9):
                    path = write_receipt(manager, run_id, number)
                    raw = path.read_bytes(); path.write_bytes(raw + b" " * (32768 - len(raw)))
                unread = manager.run_path(run_id) / "review-008.json"
                if unsafe: unread.chmod(0o640)
                original, inspections = manager._saved_run_review_file, []
                def observe(fd, name, limit):
                    value = original(fd, name, limit)
                    if name.startswith("review-"):
                        inspections.append((name, limit, 0 if value[0] is None else len(value[0])))
                    return value
                before = private_inventory(root)
                with patch.object(manager, "_saved_run_review_file", side_effect=observe):
                    if unsafe:
                        with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_STORE_UNSAFE$"):
                            manager.run_history_review(selected_request(manager, run_id))
                    else:
                        value = manager.run_history_review(selected_request(manager, run_id))["decision"]
                        self.assertEqual((value["state"], value["inspected"]), ("UNKNOWN", 9))
                        self.assertTrue(value["catalog_complete"])
                        self.assertIn("REVIEW_RECORD_LIMITED", value["notes"])
                        self.assertEqual(len(inspections), 18)
                        for rows in [inspections[:9], inspections[9:]]:
                            self.assertLessEqual(sum(actual for _, _, actual in rows), 262144)
                            self.assertTrue(all(actual <= limit + 1 for _, limit, actual in rows))
                            self.assertIn((unread.name, 0, 0), rows)
                self.assertEqual(before, private_inventory(root))

    def test_unsafe_admitted_receipt_modes_links_and_directories_refuse(self):
        for kind in ["mode", "symlink", "hardlink", "directory"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]; path = write_receipt(manager, run_id)
                if kind == "mode": path.chmod(0o640)
                elif kind == "hardlink": os.link(path, root / "invented-receipt-link")
                elif kind == "symlink":
                    other = root / "invented-receipt-copy"; write_new(other, path.read_bytes()); path.unlink(); path.symlink_to(other)
                else: path.unlink(); path.mkdir(mode=0o700)
                before = private_inventory(root)
                with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_STORE_UNSAFE$"):
                    manager.run_history_review(selected_request(manager, run_id))
                self.assertEqual(before, private_inventory(root))

    def test_receipt_add_edit_delete_rename_and_unread_drift_after_classifier_refuse(self):
        import workbench
        for kind in ["add", "edit", "delete", "rename", "unread"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]
                path = write_receipt(manager, run_id) if kind != "add" else manager.run_path(run_id) / "review-000.json"
                if kind == "unread":
                    for number in range(1, 9): write_receipt(manager, run_id, number)
                    for name in manager.run_path(run_id).glob("review-*.json"):
                        raw = name.read_bytes(); name.write_bytes(raw + b" " * (32768 - len(raw)))
                    path = manager.run_path(run_id) / "review-008.json"
                original = workbench.summarize_review_decision
                def drift(*args, **kwargs):
                    value = original(*args, **kwargs)
                    if kind == "add": write_receipt(manager, run_id)
                    elif kind == "delete": path.unlink()
                    elif kind == "rename": path.rename(path.with_name("review-001.json"))
                    else: path.write_bytes(path.read_bytes() + b" \n")
                    return value
                with patch("workbench.summarize_review_decision", side_effect=drift):
                    with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_EVIDENCE_CHANGED$"):
                        manager.run_history_review(selected_request(manager, run_id))

    def test_equal_byte_directory_swap_during_decision_classification_refuses(self):
        import workbench
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["python_ok"]; write_receipt(manager, run_id)
            directory = manager.run_path(run_id); original = workbench.summarize_review_decision
            def swap(*args, **kwargs):
                value = original(*args, **kwargs)
                retained = root / "invented-retained-run"; directory.rename(retained); directory.mkdir(mode=0o700)
                for path in retained.iterdir(): write_new(directory / path.name, path.read_bytes())
                return value
            with patch("workbench.summarize_review_decision", side_effect=swap):
                with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_EVIDENCE_CHANGED$"):
                    manager.run_history_review(selected_request(manager, run_id))

    def test_new_decision_does_not_silently_drop_full_goal_to_fit_response(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["python_ok"]; run = manager.run_path(run_id)
            task_path = manager.data / "tasks" / (run_id + ".json"); task = json.loads(task_path.read_bytes())
            task["goal"] = "🧪" * 2000; task_path.write_bytes(canonical(task))
            meta_path = manager.meta_path(run_id); metadata = json.loads(meta_path.read_bytes())
            metadata.update(goal=task["goal"], task_sha256=sha(task_path.read_bytes()), project_task_sha256=sha(task_path.read_bytes()))
            meta_path.write_bytes(canonical(metadata))
            (run / "changes.diff").write_bytes(b"\x01" * 4096)
            result = json.loads((run / "result.json").read_bytes()); result["patch_sha256"] = sha((run / "changes.diff").read_bytes())
            (run / "result.json").write_bytes(canonical(result))
            write_receipt(manager, run_id, note="🧪" * 2000)
            request = selected_request(manager, run_id)
            bundle, digest = manager._saved_run_review_inspection(run_id, metadata)
            self.assertLessEqual(len(canonical(review_saved_run(bundle, request["record_sha256"], request["history_sha256"], digest))), 65536)
            before = private_inventory(root)
            with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_OUTPUT_LIMIT$"): manager.run_history_review(request)
            self.assertEqual(before, private_inventory(root))

    def test_http_v2_decision_uses_existing_pins_and_no_new_writer_or_override_fields(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            run_id = ids["java_ok"]; write_receipt(manager, run_id, verdict="rejected")
            request = selected_request(manager, run_id); http = memory_review_http(manager)
            before = private_inventory(root)
            status, value = http(request)
            self.assertEqual((status, value["version"], value["decision"]["state"]), (200, 2, "REJECTED"))
            self.assertEqual({key: value[key] for key in request}, request)
            status, value = http({**request, "decision": "accepted"})
            self.assertEqual((status, value["error"]), (409, "SAVED_REVIEW_INPUT"))
            self.assertEqual(before, private_inventory(root))

    def test_restart_decision_and_all_private_bytes_modes_remain_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"; manager, fixtures, cases = build_decision_fixture(root)
            try:
                run_id = cases["java"]["accepted"]["id"]
                with review_guard(manager): value = self.response(root, manager, run_id)
                config, data = manager.config_path, manager.data
                manager.close(); manager = None
                before = private_inventory(root); manager = Manager(config, data)
                with review_guard(manager): self.assertEqual(self.response(root, manager, run_id), value)
                self.assertEqual(before, private_inventory(root))
            finally:
                if manager is not None: manager.close()

    def test_earlier_workflow_dependency_is_read_only_and_missing_evidence_is_not_recreated(self):
        from offline_workflow import WorkflowManager, initialize, python_report
        from qa_saved_review_decisions import existing_actual_decision
        from test_offline_workflow_integration import seed_completed
        # This exercises the dependency reader with explicitly fabricated unit
        # guard receipts and fake checks. It is not actual worker acceptance.
        with tempfile.TemporaryDirectory() as directory, patch("offline_workflow.REAL_POPEN", side_effect=AssertionError(
                "decision dependency launched a child")) as spawn:
            work = Path(directory); root = work / "offline-workflow"
            initialize(root); manager = WorkflowManager(root)
            try:
                run_id, _ = seed_completed(manager)
                view = manager.view(run_id)
                manager.review({"id": run_id, "result_sha256": view["result_sha256"], "patch_sha256": view["patch_sha256"],
                                "verdict": "accepted", "note": "Unit-only prior receipt, no actual worker."})
                prior = {"run_id": run_id, "scripted_python_agent_run": True, "real_model_qualified": False,
                         "python_report": python_report(root, require_accepted=True), "unit_only_fixture": True}
                write_new(work / "offline-workflow-acceptance.json", canonical(prior))
            finally:
                manager.close()
            before = private_inventory(work)
            value = existing_actual_decision(work)
            self.assertEqual(value["review"]["decision"]["state"], "ACCEPTED")
            self.assertEqual((value["new_worker_starts"], value["new_checks"]), (0, 0))
            self.assertEqual(before, private_inventory(work))
            spawn.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            with patch("qa_saved_review_decisions.Manager", side_effect=AssertionError("missing dependency created runtime")):
                with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_NOT_FOUND$"):
                    existing_actual_decision(work)
            self.assertEqual(list(work.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
