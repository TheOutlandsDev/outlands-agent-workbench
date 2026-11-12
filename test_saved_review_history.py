"""Synthetic receipt catalogs; no files, workers, checks or model requests."""

import copy
import hashlib
import json
import unittest
from unittest import mock

from agent import Refused, canonical
from saved_review_decisions import summarize_review_decision
import saved_review_history as history


RUN = "0123456789abcdef"
JAVA_RUN = "fedcba9876543210"
RESULT = "a" * 64
PATCH = "b" * 64
OTHER = "c" * 64
HISTORY_KEYS = {"version", "inspected", "catalog_complete", "current", "notes"}
ROW_KEYS = {"name", "status", "sha256", "verdict", "recorded", "result_sha256", "patch_sha256", "artifact_state"}


def receipt(index=0, *, verdict="accepted", run_id=RUN, recorded=123, note="Invented private note"):
    value = {"id": run_id, "result_sha256": RESULT, "patch_sha256": PATCH,
             "verdict": verdict, "recorded": recorded, "note": note, "source_applied": False}
    return {"name": f"review-{index:03d}.json", "sha256": hashlib.sha256(canonical(value)).hexdigest(),
            "value": value, "status": "OK"}


def evidence(records=None, **updates):
    value = {"present": True, "catalog_partial": False, "catalog_invalid": False,
             "records": [receipt()] if records is None else records,
             "current": {"result_sha256": RESULT, "patch_sha256": PATCH, "result_patch_sha256": PATCH}}
    value.update(updates)
    return value


class Bomb:
    def __eq__(self, other):
        raise AssertionError("untrusted equality")

    def __iter__(self):
        raise AssertionError("untrusted traversal")

    def __str__(self):
        raise AssertionError("untrusted string")

    def __repr__(self):
        raise AssertionError("untrusted repr")


class SavedReviewHistoryTests(unittest.TestCase):
    def list(self, value, run_id=RUN):
        result = history.summarize_review_history(run_id, value)
        self.assertEqual(set(result), HISTORY_KEYS | {"entries"})
        self.common(result)
        for row in result["entries"]:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertIn(row["artifact_state"], history.ARTIFACT_STATES)
        return result

    def detail(self, value, name="review-000.json", run_id=RUN):
        result = history.inspect_review_history_entry(run_id, value, name)
        self.assertEqual(set(result), HISTORY_KEYS | {"entry"})
        self.common(result)
        self.assertEqual(set(result["entry"]), ROW_KEYS | {"note"})
        self.assertEqual({k:v for k,v in result["entry"].items() if k != "note"},
                         next(row for row in self.list(value, run_id)["entries"] if row["name"] == name))
        return result

    def common(self, result):
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["notes"], sorted(set(result["notes"])))
        self.assertTrue(set(result["notes"]) <= history.NOTES)
        self.assertNotIn("REVIEW_ARTIFACTS_CHANGED", result["notes"])
        self.assertLessEqual(len(canonical(result)), 65536)

    def test_python_java_multi_verdicts_are_relations_not_current_decisions(self):
        for run_id, language in ((RUN, "Python"), (JAVA_RUN, "Java")):
            rows = [receipt(0, run_id=run_id, note=language + " historical acceptance"),
                    receipt(1, run_id=run_id, verdict="rejected", note=language + " current rejection")]
            value = evidence(rows)
            before = summarize_review_decision(run_id, value)
            listed = self.list(value, run_id)
            self.assertEqual([row["verdict"] for row in listed["entries"]], ["accepted", "rejected"])
            self.assertEqual([row["artifact_state"] for row in listed["entries"]], ["MATCHING", "MATCHING"])
            self.assertEqual(self.detail(value, run_id=run_id)["entry"]["verdict"], "accepted")
            self.assertEqual(before["state"], "REJECTED")
            self.assertEqual(summarize_review_decision(run_id, value), before)
            self.assertNotIn("state", listed)

    def test_ascending_ordinal_order_is_independent_of_timestamp(self):
        value = evidence([receipt(0, recorded=9007199254740991), receipt(1, recorded=0), receipt(2, recorded=1)])
        listed = self.list(value)
        self.assertEqual([row["name"] for row in listed["entries"]], ["review-000.json", "review-001.json", "review-002.json"])
        self.assertEqual([row["recorded"] for row in listed["entries"]], [9007199254740991, 0, 1])

    def test_list_never_returns_any_receipt_note_or_raw_extra_field(self):
        marker = "PRIVATE NOTE ONLY IN EXPLICIT DETAIL"
        rows = [receipt(number, note=marker + str(number)) for number in range(5)]
        value = evidence(rows)
        self.assertNotIn(marker, canonical(self.list(value)).decode())
        self.assertEqual(self.detail(value, "review-003.json")["entry"]["note"], marker + "3")
        rows[0]["value"]["extra-private"] = marker
        self.assertNotIn(marker, canonical(self.list(value)).decode())
        self.assertIsNone(self.detail(value)["entry"]["note"])

    def test_old_acceptance_is_visible_but_never_promoted_after_invalid_latest(self):
        latest = receipt(1)
        latest["value"]["source_applied"] = True
        value = evidence([receipt(), latest])
        before = summarize_review_decision(RUN, value)
        self.assertEqual(before["state"], "UNKNOWN")
        self.assertIsNone(before["receipt"])
        older = self.detail(value)["entry"]
        self.assertEqual((older["status"], older["artifact_state"], older["verdict"]), ("OK", "MATCHING", "accepted"))
        self.assertEqual(self.detail(value, "review-001.json")["entry"]["status"], "INVALID")
        self.assertEqual(summarize_review_decision(RUN, value), before)

    def test_catalog_damage_does_not_erase_usable_observed_entry(self):
        variants = (evidence(catalog_partial=True), evidence(catalog_invalid=True),
                    evidence([receipt(1)]), evidence(present=False))
        for value in variants:
            listed = self.list(value)
            self.assertFalse(listed["catalog_complete"])
            self.assertEqual(listed["entries"][0]["status"], "OK")
            self.assertEqual(listed["entries"][0]["artifact_state"], "MATCHING")
            self.assertTrue(listed["notes"])
            self.assertEqual(summarize_review_decision(RUN, value)["state"], "UNKNOWN")

    def test_empty_complete_catalog_retains_absence_semantics(self):
        value = evidence([], current={key:None for key in ("result_sha256", "patch_sha256", "result_patch_sha256")})
        self.assertEqual(self.list(value), {"version":1, "inspected":0, "catalog_complete":True,
                                           "current":value["current"], "notes":[], "entries":[]})
        with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_NOT_FOUND$"):
            history.inspect_review_history_entry(RUN, value, "review-000.json")

    def test_missing_partial_or_invalid_empty_catalog_remains_explicit(self):
        for changes, note in (({"present":False}, "REVIEW_CATALOG_MISSING"),
                              ({"catalog_partial":True}, "REVIEW_CATALOG_PARTIAL"),
                              ({"catalog_invalid":True}, "REVIEW_CATALOG_INVALID")):
            listed = self.list(evidence([], **changes))
            self.assertFalse(listed["catalog_complete"])
            self.assertEqual(listed["entries"], [])
            self.assertIn(note, listed["notes"])

    def test_individual_stale_relation_does_not_depend_on_highest_verdict(self):
        rows = [receipt(0), receipt(1, verdict="rejected")]
        rows[0]["value"]["result_sha256"] = OTHER
        value = evidence(rows)
        listed = self.list(value)
        self.assertEqual([row["artifact_state"] for row in listed["entries"]], ["STALE", "MATCHING"])
        self.assertEqual(listed["notes"], [])
        self.assertEqual(summarize_review_decision(RUN, value)["state"], "REJECTED")
        self.assertEqual(self.detail(value)["entry"]["artifact_state"], "STALE")

    def test_stale_current_decision_note_is_excluded_from_history_notes(self):
        value = evidence()
        value["current"]["result_sha256"] = OTHER
        self.assertEqual(summarize_review_decision(RUN, value)["notes"], ["REVIEW_ARTIFACTS_CHANGED"])
        listed = self.list(value)
        self.assertEqual(listed["notes"], [])
        self.assertEqual(listed["entries"][0]["artifact_state"], "STALE")

    def test_each_missing_current_pin_and_patch_inconsistency_make_relation_unknown(self):
        for key in ("result_sha256", "patch_sha256", "result_patch_sha256"):
            value = evidence()
            value["current"][key] = None
            self.assertEqual(self.list(value)["entries"][0]["artifact_state"], "UNKNOWN")
            self.assertEqual(self.detail(value)["entry"]["artifact_state"], "UNKNOWN")
        value = evidence()
        value["current"]["patch_sha256"] = OTHER
        listed = self.list(value)
        self.assertEqual(listed["entries"][0]["artifact_state"], "UNKNOWN")
        self.assertIn("CURRENT_ARTIFACTS_INCONSISTENT", listed["notes"])

    def test_raw_formatting_fingerprint_does_not_change_artifact_relation(self):
        result = {"patch_sha256": PATCH, "status":"REVIEW_READY"}
        content = hashlib.sha256(canonical(result)).hexdigest()
        value = evidence()
        value["current"]["result_sha256"] = content
        row = value["records"][0]
        row["value"]["result_sha256"] = content
        raw1 = canonical(row["value"])
        raw2 = json.dumps(row["value"], ensure_ascii=False, indent=3).encode()
        self.assertNotEqual(hashlib.sha256(raw1).hexdigest(), hashlib.sha256(raw2).hexdigest())
        row["sha256"] = hashlib.sha256(raw1).hexdigest()
        first = self.list(value)["entries"][0]
        row["sha256"] = hashlib.sha256(raw2).hexdigest()
        second = self.list(value)["entries"][0]
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["artifact_state"], second["artifact_state"])
        self.assertEqual(second["artifact_state"], "MATCHING")

    def test_all_non_ok_rows_keep_status_and_fingerprint_but_hide_fields(self):
        rows = [receipt(index) for index in range(3)]
        for row, status in zip(rows, ("MISSING", "INVALID", "LIMITED")):
            row["status"], row["value"] = status, Bomb()
            if status != "INVALID": row["sha256"] = None
        listed = self.list(evidence(rows))
        self.assertEqual(listed["inspected"], 3)
        self.assertEqual([row["status"] for row in listed["entries"]], ["MISSING", "INVALID", "LIMITED"])
        for row in listed["entries"]:
            self.assertEqual(row["artifact_state"], "UNKNOWN")
            self.assertTrue(all(row[key] is None for key in ("verdict", "recorded", "result_sha256", "patch_sha256")))
            self.assertIsNone(self.detail(evidence(rows), row["name"])["entry"]["note"])
        self.assertEqual(listed["entries"][1]["sha256"], rows[1]["sha256"])

    def test_invalid_ok_receipt_uses_shared_exact_schema_and_never_echoes_note(self):
        mutations = ({"id":JAVA_RUN}, {"source_applied":0}, {"source_applied":True}, {"recorded":True},
                     {"recorded":-1}, {"recorded":9007199254740992}, {"note":"\ud800"},
                     {"note":"x"*2001}, {"verdict":"accepted\n"}, {"patch_sha256":PATCH+"\r"},
                     {"result_sha256":RESULT+"\u2028"}, {"extra-private":Bomb()})
        for updates in mutations:
            value = evidence()
            value["records"][0]["value"].update(updates)
            row = self.detail(value)["entry"]
            self.assertEqual((row["status"], row["artifact_state"]), ("INVALID", "UNKNOWN"))
            self.assertIsNone(row["note"])
        value = evidence()
        value["records"][0]["sha256"] = None
        self.assertEqual(self.list(value)["entries"][0]["status"], "INVALID")

    def test_full_unicode_control_note_and_large_safe_epoch_are_preserved(self):
        for note in ("", "\x00\r\n<script>literal</script> e\u0301 雪🦊\u2028\u2029", "🦊"*2000):
            value = evidence([receipt(note=note, recorded=9007199254740991)])
            row = self.detail(value)["entry"]
            self.assertEqual(row["note"], note)
            self.assertEqual(row["recorded"], 9007199254740991)
            self.assertEqual(json.loads(canonical(row))["note"], note)

    def test_hundred_max_notes_are_omitted_from_bounded_list_and_detail_is_full(self):
        note = "🦊"*2000
        value = evidence([receipt(index, note=note) for index in range(100)])
        listed = self.list(value)
        self.assertEqual(listed["inspected"], 100)
        self.assertEqual(len(listed["entries"]), 100)
        self.assertEqual(listed["entries"][-1]["name"], "review-099.json")
        self.assertNotIn("note", set().union(*(set(row) for row in listed["entries"])))
        self.assertEqual(self.detail(value, "review-099.json")["entry"]["note"], note)

    def test_unknown_selection_and_malformed_name_have_distinct_finite_codes(self):
        value = evidence()
        with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_NOT_FOUND$"):
            history.inspect_review_history_entry(RUN, value, "review-099.json")
        for name in (None, Bomb(), "review-100.json", "review-00.json", "review-000.json\n",
                     "review-000.json\r", "review-000.json\u2028", "review-000.json\u2029", "../review-000.json"):
            with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_INPUT$"):
                history.inspect_review_history_entry(RUN, value, name)

    def test_descriptor_validation_is_identical_for_both_existing_and_new_apis(self):
        bad = [None, evidence([receipt(), receipt()]), evidence([receipt(1), receipt(0)]),
               evidence([receipt(number) for number in range(101)]), evidence(records=()), evidence(present=1)]
        current = evidence();current["current"]["result_sha256"] = RESULT+"\n";bad.append(current)
        wrapper = evidence();wrapper["records"][0]["sha256"] = Bomb();bad.append(wrapper)
        extra = evidence();extra["private-extra"] = Bomb();bad.append(extra)
        for value in bad:
            with self.assertRaises(Refused) as original:
                summarize_review_decision(RUN, value)
            for function, args in ((history.summarize_review_history, (RUN,value)),
                                   (history.inspect_review_history_entry, (RUN,value,"review-000.json"))):
                with self.assertRaises(Refused) as caught: function(*args)
                self.assertEqual(str(caught.exception), str(original.exception))
                self.assertIn(str(caught.exception), history.CODES)

    def test_corrupt_cycles_subclasses_and_dangerous_objects_are_not_traversed(self):
        class Dict(dict):
            def __iter__(self): raise AssertionError("mapping traversal")
        cycle = {};cycle["loop"] = cycle
        for corrupt in (Bomb(), cycle, Dict(receipt()["value"]), [Bomb()], None):
            value = evidence();value["records"][0]["value"] = corrupt
            self.assertEqual(self.detail(value)["entry"]["status"], "INVALID")

    def test_output_is_deterministic_independent_and_inputs_are_unchanged(self):
        value = evidence([receipt(0),receipt(1,verdict="rejected")]);before=copy.deepcopy(value)
        listed = self.list(value);detail = self.detail(value)
        self.assertEqual(value,before)
        self.assertEqual(canonical(listed),canonical(self.list(value)))
        listed["current"]["result_sha256"] = None
        listed["entries"][0]["verdict"] = "external mutation"
        detail["entry"]["note"] = "external mutation"
        detail["notes"].append("external mutation")
        self.assertEqual(value,before)
        self.assertEqual(self.detail(value)["entry"]["note"],before["records"][0]["value"]["note"])

    def test_whole_result_cap_refuses_without_trimming_list_or_selected_note(self):
        value = evidence([receipt(note="🦊"*2000)])
        before=copy.deepcopy(value)
        with mock.patch.object(history,"MAX_OUTPUT",64):
            for function,args in ((history.summarize_review_history,(RUN,value)),
                                  (history.inspect_review_history_entry,(RUN,value,"review-000.json"))):
                with self.assertRaisesRegex(Refused,"^SAVED_REVIEW_OUTPUT_LIMIT$"):function(*args)
        self.assertEqual(value,before)
        self.assertEqual(self.detail(value)["entry"]["note"],"🦊"*2000)

    def test_pure_helpers_do_not_open_resolve_spawn_or_call_providers(self):
        with mock.patch("builtins.open",side_effect=AssertionError("I/O")), \
             mock.patch("os.open",side_effect=AssertionError("I/O")), \
             mock.patch("pathlib.Path.resolve",side_effect=AssertionError("source")), \
             mock.patch("subprocess.Popen",side_effect=AssertionError("worker")), \
             mock.patch("agent.Ollama.request",side_effect=AssertionError("provider")), \
             mock.patch("agent.Ollama.preflight",side_effect=AssertionError("provider")), \
             mock.patch("agent.ScriptedDemo.request",side_effect=AssertionError("scripted agent")):
            value=evidence([receipt(0),receipt(1,verdict="rejected")])
            self.assertEqual(len(self.list(value)["entries"]),2)
            self.assertEqual(self.detail(value)["entry"]["artifact_state"],"MATCHING")


if __name__ == "__main__":
    unittest.main()
