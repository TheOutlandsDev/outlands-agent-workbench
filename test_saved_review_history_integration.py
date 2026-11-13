"""Invented bounded saved-review history; no execution or decision changes."""

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from test_run_comparison_integration import seed_saved_run
from test_saved_review_decisions_integration import build_decision_fixture, write_receipt
from test_saved_run_review_integration import private_inventory, review_guard, selected_request
from workbench import Manager, make_handler


def history_pins(review, name=None):
    value = {key: review[key] for key in ["id", "record_sha256", "history_sha256", "evidence_sha256"]}
    if name is not None: value["name"] = name
    return value


def build_history_fixture(root, jdk=None):
    """Invented Python/Java catalogs; seeded receipts never represent agent runs."""
    manager, projects, original = build_decision_fixture(root, jdk)
    cases = {}
    for language_number, (language, rows) in enumerate(original.items(), 1):
        rows = copy.deepcopy(rows)
        multi = rows.pop("accepted"); multi["expected_state"] = "STALE"
        write_receipt(manager, multi["id"], 1, verdict="rejected", recorded=1,
                      note="Private-note-unique latest matching rejection — café e\u0301 🧪\x00\r\n<b>literal</b>")
        write_receipt(manager, multi["id"], 2, result_sha256="0" * 64, recorded=2,
                      note="Observed stale acceptance; never promote an earlier decision.")
        rows["multi"] = multi
        gapped = rows.pop("stale"); gapped["expected_state"] = "UNKNOWN"
        write_receipt(manager, gapped["id"], 2, verdict="rejected", note="Observed receipt after a gap.")
        rows["gapped"] = gapped
        for label, offset in [("limited", 128), ("missing", 129)]:
            identifier = format(language_number * 4096 + offset, "016x")
            project = projects[language]
            task = copy.deepcopy(manager.projects[project["project_id"]]["definition"])
            task["goal"] = "Invented " + language + " history " + label + " — café 🧪."
            seed_saved_run(manager, identifier, task, project=project["project_id"],
                           project_name="Invented " + language + " receipt history", created=300 + offset)
            if label == "limited":
                path = write_receipt(manager, identifier); raw = path.read_bytes()
                path.write_bytes(raw + b" " * (32769 - len(raw)))
            else:
                run = manager.run_path(identifier)
                for path in run.iterdir(): path.unlink()
                run.rmdir()
            rows[label] = {"id": identifier, "expected_state": "UNKNOWN", "seeded_observation": True}
        cases[language] = rows
    return manager, projects, cases


@contextmanager
def history_fixture():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "fixture"
        manager, projects, cases = build_history_fixture(root)
        try: yield root, manager, projects, cases
        finally: manager.close()


@contextmanager
def saved_history_guard(manager):
    with review_guard(manager), patch.object(manager, "run_history_review", side_effect=AssertionError("history recomputed current review")), patch(
            "workbench.review_saved_run", side_effect=AssertionError("history reduced current saved review")), patch(
            "workbench.summarize_review_decision", side_effect=AssertionError("history changed current decision")):
        yield


def current_review(manager, run_id):
    with review_guard(manager): return manager.run_history_review(selected_request(manager, run_id))


def memory_history_http(manager):
    handler_type = make_handler(manager, "invented-history-token", "http://127.0.0.1:8765")
    def request(route, value, headers=None, raw=None):
        raw = canonical(value) if raw is None else raw
        supplied = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "X-Workbench-Token": "invented-history-token",
                    "Content-Type": "application/json", "Content-Length": str(len(raw))}
        duplicates = headers if isinstance(headers, list) else []
        if isinstance(headers, dict): supplied.update(headers)
        handler = handler_type.__new__(handler_type)
        handler.command, handler.path = "POST", route
        handler.request_version, handler.requestline = "HTTP/1.1", "POST " + route + " HTTP/1.1"
        handler.headers = Message()
        for key, item in list(supplied.items()) + duplicates: handler.headers[key] = item
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.do_POST()
        head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        return int(head.split(b" ", 2)[1]), json.loads(body)
    return request


class SavedReviewHistoryIntegrationTests(unittest.TestCase):
    def unchanged(self, root, operation, request):
        before = private_inventory(root)
        value = operation(request)
        self.assertEqual(before, private_inventory(root))
        self.assertEqual(set(value), {"version", "id", "record_sha256", "history_sha256", "evidence_sha256", "history"})
        self.assertEqual(value["version"], 1)
        self.assertEqual({key: value[key] for key in request if key != "name"}, {key: request[key] for key in request if key != "name"})
        self.assertLessEqual(len(canonical(value)), 65536)
        return value

    def refusal(self, root, operation, request, code=None):
        before = private_inventory(root)
        with self.assertRaises(Refused) as caught: operation(request)
        self.assertRegex(str(caught.exception), r"^SAVED_REVIEW_[A-Z_]{1,64}$")
        if code is not None: self.assertEqual(str(caught.exception), code)
        self.assertEqual(before, private_inventory(root))

    def test_python_java_multi_history_lists_ascending_without_notes_or_decision_promotion(self):
        with history_fixture() as (root, manager, projects, cases):
            for language in projects:
                review = current_review(manager, cases[language]["multi"]["id"])
                definitions = copy.deepcopy({key: value["definition"] for key, value in manager.projects.items()})
                with saved_history_guard(manager):
                    listed = self.unchanged(root, manager.saved_review_history, history_pins(review))["history"]
                    self.assertEqual(set(listed), {"version", "inspected", "catalog_complete", "current", "notes", "entries"})
                    self.assertEqual([row["name"] for row in listed["entries"]], ["review-000.json", "review-001.json", "review-002.json"])
                    self.assertEqual([row["artifact_state"] for row in listed["entries"]], ["MATCHING", "MATCHING", "STALE"])
                    self.assertEqual([row["verdict"] for row in listed["entries"]], ["accepted", "rejected", "accepted"])
                    self.assertNotIn("Private-note-unique", json.dumps(listed))
                    self.assertNotIn("REVIEW_ARTIFACTS_CHANGED", listed["notes"])
                    for row in listed["entries"]:
                        self.assertEqual(set(row), {"name", "status", "sha256", "verdict", "recorded", "result_sha256", "patch_sha256", "artifact_state"})
                        detail = self.unchanged(root, manager.saved_review_history_entry, history_pins(review, row["name"]))["history"]
                        self.assertEqual({key: value for key, value in detail["entry"].items() if key != "note"}, row)
                self.assertEqual(current_review(manager, review["id"]), review)
                self.assertEqual(definitions, {key: value["definition"] for key, value in manager.projects.items()})

    def test_detail_preserves_full_unicode_controls_and_timestamp_but_list_omits_note(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"])
            with saved_history_guard(manager):
                detail = self.unchanged(root, manager.saved_review_history_entry, history_pins(review, "review-001.json"))["history"]
            expected = json.loads((manager.run_path(review["id"]) / "review-001.json").read_bytes())
            self.assertEqual(detail["entry"]["note"], expected["note"])
            self.assertIn("\x00\r\n<b>literal</b>", detail["entry"]["note"])
            self.assertEqual(detail["entry"]["recorded"], 1)

    def test_invalid_latest_damaged_gapped_and_limited_rows_remain_visible_without_fallback(self):
        with history_fixture() as (root, manager, projects, cases):
            for label in ["unknown", "gapped", "limited"]:
                review = current_review(manager, cases["java"][label]["id"])
                self.assertEqual(review["decision"]["state"], "UNKNOWN")
                with saved_history_guard(manager):
                    listed = self.unchanged(root, manager.saved_review_history, history_pins(review))["history"]
                    self.assertTrue(listed["entries"])
                    for row in listed["entries"]:
                        detail = self.unchanged(root, manager.saved_review_history_entry, history_pins(review, row["name"]))["history"]["entry"]
                        if row["status"] != "OK":
                            self.assertIsNone(detail["note"])
                            for key in ["verdict", "recorded", "result_sha256", "patch_sha256"]: self.assertIsNone(row[key])
                            self.assertEqual(row["artifact_state"], "UNKNOWN")
                    if label == "unknown":
                        self.assertEqual([row["status"] for row in listed["entries"]], ["OK", "INVALID"])
                        self.assertEqual(listed["entries"][0]["artifact_state"], "MATCHING")
                    if label == "gapped": self.assertFalse(listed["catalog_complete"])
                    if label == "limited": self.assertIsNone(listed["entries"][0]["sha256"])
                self.assertEqual(current_review(manager, review["id"]), review)

    def test_complete_empty_and_missing_catalogs_are_distinguished(self):
        with history_fixture() as (root, manager, projects, cases):
            for label, complete in [("unreviewed", True), ("missing", False)]:
                review = current_review(manager, cases["python"][label]["id"])
                with saved_history_guard(manager):
                    value = self.unchanged(root, manager.saved_review_history, history_pins(review))["history"]
                    self.assertEqual((value["entries"], value["inspected"], value["catalog_complete"]), ([], 0, complete))
                    self.refusal(root, manager.saved_review_history_entry, history_pins(review, "review-000.json"), "SAVED_REVIEW_NOT_FOUND")

    def test_current_artifact_pins_are_canonical_and_raw_formatting_is_not_stale(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["java"]["formatted"]["id"])
            self.assertNotEqual(review["summary"]["result_sha256"], review["decision"]["current"]["result_sha256"])
            with saved_history_guard(manager):
                value = self.unchanged(root, manager.saved_review_history, history_pins(review))["history"]
                self.assertEqual(value["current"], review["decision"]["current"])
                self.assertEqual(value["entries"][0]["artifact_state"], "MATCHING")

    def test_invalid_fields_pins_and_names_refuse_before_any_store_read(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"])
            request = history_pins(review)
            with patch.object(manager, "_run_history_inspection", side_effect=AssertionError("invalid request read jobs")), patch.object(
                    manager, "_saved_run_review_inspection", side_effect=AssertionError("invalid request read evidence")):
                for invalid in [{}, [], None, {**request, "name": "review-000.json"}, {key: value for key, value in request.items() if key != "evidence_sha256"},
                                {**request, "id": "../outside"}, {**request, "evidence_sha256": True}, {**request, "history_sha256": "0" * 64 + "\n"}]:
                    self.refusal(root, manager.saved_review_history, invalid, "SAVED_REVIEW_INPUT")
                for name in [None, True, "review-100.json", "review-000.json\n", "../review-000.json", "review-00.json"]:
                    self.refusal(root, manager.saved_review_history_entry, {**request, "name": name}, "SAVED_REVIEW_INPUT")

    def test_stale_metadata_history_evidence_and_unknown_selection_refuse_without_fallback(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"])
            request = history_pins(review)
            with saved_history_guard(manager):
                for key, code in [("record_sha256", "SAVED_REVIEW_RECORD_CHANGED"), ("history_sha256", "SAVED_REVIEW_HISTORY_CHANGED"),
                                  ("evidence_sha256", "SAVED_REVIEW_EVIDENCE_CHANGED")]:
                    self.refusal(root, manager.saved_review_history, {**request, key: "0" * 64}, code)
                self.refusal(root, manager.saved_review_history_entry, history_pins(review, "review-099.json"), "SAVED_REVIEW_NOT_FOUND")
            path = manager.run_path(review["id"]) / "review-000.json"; path.write_bytes(path.read_bytes() + b" \n")
            with saved_history_guard(manager):
                self.refusal(root, manager.saved_review_history_entry, history_pins(review, "review-000.json"), "SAVED_REVIEW_EVIDENCE_CHANGED")

    def test_successful_list_and_detail_perform_two_evidence_and_two_history_inspections(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"])
            for method, request in [(manager.saved_review_history, history_pins(review)),
                                    (manager.saved_review_history_entry, history_pins(review, "review-000.json"))]:
                with saved_history_guard(manager), patch.object(manager, "_run_history_inspection", wraps=manager._run_history_inspection) as jobs, patch.object(
                        manager, "_saved_run_review_inspection", wraps=manager._saved_run_review_inspection) as evidence:
                    self.unchanged(root, method, request)
                    self.assertEqual((jobs.call_count, evidence.call_count), (2, 2))

    def test_receipt_and_metadata_drift_during_pure_list_or_detail_refuse(self):
        import workbench
        for detail in [False, True]:
            for kind in ["receipt", "metadata"]:
                with self.subTest(detail=detail, kind=kind), history_fixture() as (root, manager, projects, cases):
                    review = current_review(manager, cases["python"]["multi"]["id"])
                    alias = "inspect_review_history_entry" if detail else "summarize_review_history"
                    original = getattr(workbench, alias)
                    def drift(*args, **kwargs):
                        value = original(*args, **kwargs)
                        path = manager.meta_path(review["id"]) if kind == "metadata" else manager.run_path(review["id"]) / "review-000.json"
                        path.write_bytes(path.read_bytes() + b" \n"); return value
                    request = history_pins(review, "review-000.json") if detail else history_pins(review)
                    with saved_history_guard(manager), patch.object(workbench, alias, side_effect=drift):
                        with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_" + ("HISTORY_CHANGED" if kind == "metadata" else "EVIDENCE_CHANGED") + "$"):
                            (manager.saved_review_history_entry if detail else manager.saved_review_history)(request)

    def test_unsafe_receipts_and_unread_unsafe_tail_refuse_even_after_budget_exhaustion(self):
        for kind in ["mode", "link", "symlink", "unread"]:
            with self.subTest(kind=kind), history_fixture() as (root, manager, projects, cases):
                run_id = cases["python"]["rejected"]["id"]
                review = current_review(manager, run_id); run = manager.run_path(run_id)
                path = run / "review-000.json"
                if kind == "unread":
                    for number in range(1, 9): write_receipt(manager, run_id, number)
                    for receipt in run.glob("review-*.json"):
                        raw = receipt.read_bytes(); receipt.write_bytes(raw + b" " * (32768 - len(raw)))
                    review = current_review(manager, run_id); path = run / "review-008.json"
                if kind in ["mode", "unread"]: path.chmod(0o640)
                elif kind == "link": os.link(path, root / "invented-review-link")
                else:
                    copy_path = root / "invented-review-copy"; write_new(copy_path, path.read_bytes()); path.unlink(); path.symlink_to(copy_path)
                with saved_history_guard(manager):
                    self.refusal(root, manager.saved_review_history, history_pins(review), "SAVED_REVIEW_STORE_UNSAFE")

    def test_partial_catalog_and_large_receipt_budget_are_reported_without_inventing_complete_history(self):
        with history_fixture() as (root, manager, projects, cases):
            run_id = cases["java"]["rejected"]["id"]; run = manager.run_path(run_id)
            for number in range(1, 9): write_receipt(manager, run_id, number)
            for receipt in run.glob("review-*.json"):
                raw = receipt.read_bytes(); receipt.write_bytes(raw + b" " * (32768 - len(raw)))
            review = current_review(manager, run_id)
            with saved_history_guard(manager):
                listed = self.unchanged(root, manager.saved_review_history, history_pins(review))["history"]
                self.assertEqual(listed["inspected"], 9)
                self.assertIn("LIMITED", [row["status"] for row in listed["entries"]])
                last = self.unchanged(root, manager.saved_review_history_entry, history_pins(review, "review-008.json"))["history"]["entry"]
                self.assertEqual((last["status"], last["sha256"], last["note"]), ("LIMITED", None, None))
        with history_fixture() as (root, manager, projects, cases):
            run_id = cases["python"]["rejected"]["id"]; run = manager.run_path(run_id)
            for number in range(1025): write_new(run / ("invented-ignored-" + str(number)), b"ignored")
            review = current_review(manager, run_id)
            with saved_history_guard(manager):
                listed = self.unchanged(root, manager.saved_review_history, history_pins(review))["history"]
                self.assertFalse(listed["catalog_complete"])
                self.assertIn("REVIEW_CATALOG_PARTIAL", listed["notes"])

    def test_unrelated_hold_source_config_and_task_changes_are_not_read(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["java"]["multi"]["id"])
            hold = manager.data / "state/hold.json"; raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented history hold", "turn": 1})
            write_new(hold, raw); manager.config_path.write_bytes(b"{invalid current config")
            projects["java"]["task"].write_bytes(b"{invalid current task")
            (projects["java"]["source"] / "sample/Sum.java").write_bytes(b"Invented changed current source")
            with saved_history_guard(manager):
                self.unchanged(root, manager.saved_review_history, history_pins(review))
                self.unchanged(root, manager.saved_review_history_entry, history_pins(review, "review-000.json"))
            self.assertEqual(hold.read_bytes(), raw)

    def test_restart_retains_saved_context_history_details_and_all_private_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"; manager, projects, cases = build_history_fixture(root)
            try:
                review = current_review(manager, cases["java"]["multi"]["id"])
                with saved_history_guard(manager):
                    listed = self.unchanged(root, manager.saved_review_history, history_pins(review))
                    detail = self.unchanged(root, manager.saved_review_history_entry, history_pins(review, "review-001.json"))
                config, data = manager.config_path, manager.data; manager.close(); manager = None
                before = private_inventory(root); manager = Manager(config, data)
                self.assertEqual(current_review(manager, review["id"]), review)
                with saved_history_guard(manager):
                    self.assertEqual(manager.saved_review_history(history_pins(review)), listed)
                    self.assertEqual(manager.saved_review_history_entry(history_pins(review, "review-001.json")), detail)
                self.assertEqual(before, private_inventory(root))
            finally:
                if manager is not None: manager.close()

    def test_prior_workflow_dependency_reads_existing_receipt_and_never_recreates_missing_fixture(self):
        from offline_workflow import WorkflowManager, initialize, python_report
        from qa_saved_review_history import existing_actual_history
        from test_offline_workflow_integration import seed_completed
        # Unit-only mocked checks and fabricated guard receipts, not execution.
        with tempfile.TemporaryDirectory() as directory, patch("offline_workflow.REAL_POPEN", side_effect=AssertionError(
                "history dependency launched a child")) as spawn:
            work = Path(directory); root = work / "offline-workflow"
            initialize(root); manager = WorkflowManager(root)
            try:
                run_id, _ = seed_completed(manager)
                view = manager.view(run_id)
                manager.review({"id": run_id, "result_sha256": view["result_sha256"], "patch_sha256": view["patch_sha256"],
                                "verdict": "accepted", "note": "Unit-only existing receipt — café 🧪."})
                write_new(work / "offline-workflow-acceptance.json", canonical({"run_id": run_id,
                    "scripted_python_agent_run": True, "real_model_qualified": False,
                    "python_report": python_report(root, require_accepted=True), "unit_only_fixture": True}))
            finally: manager.close()
            before = private_inventory(work)
            result = existing_actual_history(work)
            self.assertEqual(result["history"]["history"]["entries"][0]["artifact_state"], "MATCHING")
            self.assertEqual((result["new_workers"], result["new_checks"]), (0, 0))
            self.assertEqual(before, private_inventory(work)); spawn.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            with patch("qa_saved_review_history.Manager", side_effect=AssertionError("missing dependency instantiated Manager")):
                with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_NOT_FOUND$"): existing_actual_history(work)
            self.assertEqual(list(work.iterdir()), [])


class SavedReviewHistoryHTTPTests(unittest.TestCase):
    def test_explicit_list_detail_exact_envelopes_and_stale_selection_pins(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"]); request = memory_history_http(manager)
            before = private_inventory(root)
            with saved_history_guard(manager):
                status, listed = request("/api/saved-review-history", history_pins(review))
                self.assertEqual(status, 200)
                row = listed["history"]["entries"][0]
                status, detail = request("/api/saved-review-history-entry", history_pins(review, row["name"]))
                self.assertEqual(status, 200)
                self.assertEqual({key: value for key, value in detail["history"]["entry"].items() if key != "note"}, row)
                status, value = request("/api/saved-review-history-entry", {**history_pins(review, row["name"]), "sha256": row["sha256"]})
                self.assertEqual((status, value["error"]), (409, "SAVED_REVIEW_INPUT"))
            self.assertEqual(before, private_inventory(root))

    def test_auth_origin_framing_invalid_json_and_output_caps_refuse_before_actions(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"]); request = memory_history_http(manager)
            for route, method in [("/api/saved-review-history", "saved_review_history"), ("/api/saved-review-history-entry", "saved_review_history_entry")]:
                body = history_pins(review)
                with patch.object(manager, method, side_effect=AssertionError("bad HTTP reached history")) as action:
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"}, {"Content-Length": "32769"},
                        {"Content-Length": "9999"}, {"Content-Type": "application/zip"}, [("Content-Length", str(len(canonical(body))))], [("Content-Type", "application/json")]]:
                        before = private_inventory(root); status, value = request(route, body, headers)
                        self.assertEqual(status, 409); self.assertRegex(value["error"], r"^SAVED_REVIEW_[A-Z_]+$")
                        self.assertEqual(before, private_inventory(root))
                    for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"), ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"),
                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"), ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        status, value = request(route, body, headers); self.assertEqual((status, value["error"]), (409, error))
                    for raw in [b'{"id":"x","id":"y"}', b"\xff", b'{"id":']:
                        status, value = request(route, {}, raw=raw); self.assertEqual(status, 409)
                    action.assert_not_called()
                with patch.object(manager, method, return_value={"invented": "x" * 65536}):
                    status, value = request(route, {})
                    self.assertEqual((status, value["error"]), (409, "SAVED_REVIEW_OUTPUT_LIMIT"))

    def test_controller_whole_envelope_limit_applies_after_pure_history(self):
        with history_fixture() as (root, manager, projects, cases):
            review = current_review(manager, cases["python"]["multi"]["id"])
            with saved_history_guard(manager), patch("workbench.summarize_review_history", return_value={"invented": "x" * 65536}):
                before = private_inventory(root)
                with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_OUTPUT_LIMIT$"):
                    manager.saved_review_history(history_pins(review))
                self.assertEqual(before, private_inventory(root))


if __name__ == "__main__": unittest.main()
