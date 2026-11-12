"""Invented saved receipt observations; no real runs, processes or checks."""

import copy
import hashlib
import json
import unittest
from unittest import mock

from agent import Refused, canonical
import saved_review_decisions as decisions


RUN = "0123456789abcdef"
OTHER_RUN = "fedcba9876543210"
RESULT = "a" * 64
PATCH = "b" * 64
OTHER = "c" * 64


def receipt(index=0, verdict="accepted", run_id=RUN, note="Invented private review", recorded=123):
    value = {"id": run_id, "result_sha256": RESULT, "patch_sha256": PATCH,
             "verdict": verdict, "note": note, "recorded": recorded, "source_applied": False}
    return {"name": f"review-{index:03d}.json", "sha256": hashlib.sha256(canonical(value)).hexdigest(),
            "value": value, "status": "OK"}


def evidence(records=None, **changes):
    value = {"present": True, "catalog_partial": False, "catalog_invalid": False,
             "records": [receipt()] if records is None else records,
             "current": {"result_sha256": RESULT, "patch_sha256": PATCH, "result_patch_sha256": PATCH}}
    value.update(changes)
    return value


class Bomb:
    def __eq__(self, other):
        raise AssertionError("untrusted equality")

    def __str__(self):
        raise AssertionError("untrusted string")

    def __repr__(self):
        raise AssertionError("untrusted repr")

    def __iter__(self):
        raise AssertionError("untrusted traversal")


class SavedReviewDecisionTests(unittest.TestCase):
    def reduce(self, value, run_id=RUN):
        result = decisions.summarize_review_decision(run_id, value)
        self.assertEqual(set(result), {"version", "state", "receipt", "current", "inspected", "catalog_complete", "notes"})
        self.assertEqual(result["version"], 1)
        self.assertIn(result["state"], decisions.STATES)
        self.assertEqual(result["notes"], sorted(set(result["notes"])))
        self.assertTrue(set(result["notes"]) <= decisions.NOTES)
        self.assertLessEqual(len(canonical(result)), 65536)
        if result["state"] == "UNKNOWN":
            self.assertTrue(result["notes"])
        self.assertEqual("REVIEW_ARTIFACTS_CHANGED" in result["notes"], result["state"] == "STALE")
        return result

    def refuse(self, value, run_id=RUN):
        with self.assertRaises(Refused) as caught:
            decisions.summarize_review_decision(run_id, value)
        self.assertIn(str(caught.exception), decisions.CODES)

    def test_five_states_for_python_and_java_saved_observations(self):
        for language in ("Python", "Java"):
            accepted = evidence([receipt(note=f"Invented {language} decision")])
            self.assertEqual(self.reduce(accepted)["state"], "ACCEPTED")
            rejected = evidence([receipt(verdict="rejected")])
            self.assertEqual(self.reduce(rejected)["state"], "REJECTED")
            stale = copy.deepcopy(accepted)
            stale["current"]["result_sha256"] = OTHER
            self.assertEqual(self.reduce(stale)["state"], "STALE")
            self.assertEqual(self.reduce(evidence([]))["state"], "UNREVIEWED")
            self.assertEqual(self.reduce(evidence(catalog_partial=True))["state"], "UNKNOWN")

    def test_empty_complete_observes_absence_independently_of_readiness(self):
        for current in ({key: None for key in decisions.CURRENT_KEYS},
                        {"result_sha256": None, "patch_sha256": PATCH, "result_patch_sha256": OTHER}):
            result = self.reduce(evidence([], current=current))
            self.assertEqual(result, {"version": 1, "state": "UNREVIEWED", "receipt": None,
                                     "current": current, "inspected": 0, "catalog_complete": True, "notes": []})

    def test_canonical_result_content_is_distinct_from_raw_result_bytes(self):
        saved = {"status": "DONE", "patch_sha256": PATCH, "language": "Java"}
        compact = json.dumps(saved, separators=(",", ":")).encode()
        spaced = json.dumps(saved, indent=2).encode()
        self.assertNotEqual(hashlib.sha256(compact).hexdigest(), hashlib.sha256(spaced).hexdigest())
        content = hashlib.sha256(canonical(json.loads(compact))).hexdigest()
        self.assertEqual(content, hashlib.sha256(canonical(json.loads(spaced))).hexdigest())
        value = evidence()
        value["records"][0]["value"]["result_sha256"] = content
        value["current"]["result_sha256"] = content
        self.assertEqual(self.reduce(value)["state"], "ACCEPTED")
        value["current"]["result_sha256"] = hashlib.sha256(spaced).hexdigest()
        self.assertEqual(self.reduce(value)["state"], "STALE")

    def test_each_target_mismatch_stales_only_a_usable_current_chain(self):
        for changed in ("result_sha256", "patch_sha256", "both"):
            value = evidence()
            if changed in {"result_sha256", "both"}:
                value["current"]["result_sha256"] = OTHER
            if changed in {"patch_sha256", "both"}:
                value["current"]["patch_sha256"] = OTHER
                value["current"]["result_patch_sha256"] = OTHER
            result = self.reduce(value)
            self.assertEqual(result["state"], "STALE")
            self.assertEqual(result["notes"], ["REVIEW_ARTIFACTS_CHANGED"])

    def test_inconsistent_current_patch_cannot_be_meaningfully_stale(self):
        value = evidence()
        value["current"]["patch_sha256"] = OTHER
        result = self.reduce(value)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["notes"], ["CURRENT_ARTIFACTS_INCONSISTENT"])
        value["current"]["result_sha256"] = None
        self.assertEqual(self.reduce(value)["notes"], ["CURRENT_ARTIFACTS_INCONSISTENT", "CURRENT_RESULT_UNKNOWN"])

    def test_each_unknown_current_pin_has_the_corresponding_note(self):
        pairs = (("result_sha256", "CURRENT_RESULT_UNKNOWN"), ("patch_sha256", "CURRENT_PATCH_UNKNOWN"),
                 ("result_patch_sha256", "CURRENT_PATCH_DECLARATION_UNKNOWN"))
        for key, note in pairs:
            value = evidence()
            value["current"][key] = None
            result = self.reduce(value)
            self.assertEqual(result["state"], "UNKNOWN")
            self.assertEqual(result["notes"], [note])

    def test_latest_is_filename_ordinal_and_not_recorded_time(self):
        first = receipt(0, recorded=decisions.MAX_SAFE)
        latest = receipt(1, verdict="rejected", recorded=0)
        result = self.reduce(evidence([first, latest]))
        self.assertEqual(result["state"], "REJECTED")
        self.assertEqual(result["receipt"]["name"], "review-001.json")
        self.assertEqual(result["receipt"]["recorded"], 0)

    def test_latest_invalid_never_falls_back_to_earlier_acceptance(self):
        latest = receipt(1)
        latest["value"]["source_applied"] = True
        result = self.reduce(evidence([receipt(), latest]))
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["receipt"])
        self.assertEqual(result["inspected"], 2)
        self.assertEqual(result["notes"], ["REVIEW_RECORD_INVALID"])

    def test_invalid_prior_keeps_highest_valid_observation_visible_but_unknown(self):
        first = receipt()
        first["value"]["id"] = OTHER_RUN
        result = self.reduce(evidence([first, receipt(1, verdict="rejected")]))
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["receipt"]["name"], "review-001.json")
        self.assertEqual(result["receipt"]["verdict"], "rejected")
        self.assertTrue(result["catalog_complete"])

    def test_missing_partial_invalid_and_gapped_catalogs_remain_unknown(self):
        variants = ((evidence(present=False), "REVIEW_CATALOG_MISSING"),
                    (evidence(catalog_partial=True), "REVIEW_CATALOG_PARTIAL"),
                    (evidence(catalog_invalid=True), "REVIEW_CATALOG_INVALID"),
                    (evidence([receipt(1)]), "REVIEW_CATALOG_INVALID"),
                    (evidence([receipt(0), receipt(2)]), "REVIEW_CATALOG_INVALID"),
                    (evidence([], catalog_partial=True), "REVIEW_CATALOG_PARTIAL"))
        for value, note in variants:
            result = self.reduce(value)
            self.assertEqual(result["state"], "UNKNOWN")
            self.assertFalse(result["catalog_complete"])
            self.assertIn(note, result["notes"])

    def test_observed_non_ok_statuses_are_counted_and_do_not_reveal_values(self):
        rows = [receipt(index) for index in range(3)]
        for row, status in zip(rows, ("MISSING", "INVALID", "LIMITED")):
            row["status"] = status
            row["value"] = Bomb()
        result = self.reduce(evidence(rows))
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["inspected"], 3)
        self.assertIsNone(result["receipt"])
        self.assertEqual(result["notes"], ["REVIEW_RECORD_INVALID", "REVIEW_RECORD_LIMITED", "REVIEW_RECORD_MISSING"])

    def test_exact_receipt_schema_type_identity_and_adoption_requirements(self):
        bad_fields = {"id": [OTHER_RUN, RUN.upper(), RUN + "\n", None, Bomb()],
                      "result_sha256": ["A" * 64, RESULT + "\u2028", None, 0],
                      "patch_sha256": [PATCH[:-1], PATCH + "\r", [], Bomb()],
                      "verdict": ["ACCEPTED", "accepted\n", None, True],
                      "recorded": [True, False, -1, decisions.MAX_SAFE + 1, 1.0, None, Bomb()],
                      "source_applied": [True, 0, None, "false"],
                      "note": [None, 1, "a" * 2001, "\ud800", Bomb()]}
        for key, values in bad_fields.items():
            for bad in values:
                with self.subTest(field=key, type=type(bad).__name__):
                    value = evidence()
                    value["records"][0]["value"][key] = bad
                    result = self.reduce(value)
                    self.assertEqual(result["state"], "UNKNOWN")
                    self.assertIsNone(result["receipt"])
                    self.assertIn("REVIEW_RECORD_INVALID", result["notes"])
        for shape in (None, [], "private corrupt text", Bomb(), {"private-extra": Bomb()}):
            value = evidence()
            value["records"][0]["value"] = shape
            self.assertIsNone(self.reduce(value)["receipt"])
        for action in ("extra", "missing"):
            value = evidence()
            if action == "extra":
                value["records"][0]["value"]["private-extra"] = Bomb()
            else:
                del value["records"][0]["value"]["source_applied"]
            self.assertIsNone(self.reduce(value)["receipt"])

    def test_valid_unicode_controls_nul_markup_and_large_epoch_preserved(self):
        notes = ("", "line1\r\nline2\x00<script>literal</script>\u2028\u2029", "é e\u0301 雪 🦊", "🦊" * 2000)
        for note in notes:
            value = evidence([receipt(note=note, recorded=decisions.MAX_SAFE)])
            result = self.reduce(value)
            self.assertEqual(result["state"], "ACCEPTED")
            self.assertEqual(result["receipt"]["note"], note)
            self.assertEqual(result["receipt"]["recorded"], decisions.MAX_SAFE)
            self.assertEqual(json.loads(canonical(result))["receipt"]["note"], note)

    def test_hundred_receipts_are_complete_and_101_is_a_descriptor_refusal(self):
        result = self.reduce(evidence([receipt(index) for index in range(100)]))
        self.assertEqual(result["inspected"], 100)
        self.assertEqual(result["state"], "ACCEPTED")
        self.assertEqual(result["receipt"]["name"], "review-099.json")
        self.refuse(evidence([receipt(index) for index in range(101)]))

    def test_wrapper_order_duplicate_names_and_noncanonical_names_refuse(self):
        for rows in ([receipt(1), receipt(0)], [receipt(), receipt()]):
            self.refuse(evidence(rows))
        for name in ("review-100.json", "review-00.json", "review-000.JSON", "review-000.json\n",
                     "review-000.json\u2029", "../review-000.json", "review-000.json\x00", None, Bomb()):
            value = evidence()
            value["records"][0]["name"] = name
            self.refuse(value)

    def test_malformed_descriptor_types_and_extra_keys_finitely_refuse(self):
        self.refuse(None)
        for run_id in (RUN + "\n", RUN + "\u2028", RUN.upper(), None, Bomb()):
            self.refuse(evidence(), run_id)
        for key in ("present", "catalog_partial", "catalog_invalid"):
            for bad in (0, 1, None, "false", Bomb()):
                value = evidence()
                value[key] = bad
                self.refuse(value)
        for key, bad in (("current", None), ("records", ()), ("records", Bomb())):
            self.refuse(evidence(**{key: bad}))
        for key in decisions.CURRENT_KEYS:
            for bad in (RESULT + "\n", "A" * 64, True, Bomb()):
                value = evidence()
                value["current"][key] = bad
                self.refuse(value)
        for key in ("unknown",):
            value = evidence()
            value[key] = "private"
            self.refuse(value)
        for change in ("extra", "missing", "sha256", "status"):
            value = evidence()
            row = value["records"][0]
            if change == "extra":
                row["private"] = Bomb()
            elif change == "missing":
                del row["value"]
            elif change == "sha256":
                row["sha256"] = RESULT + "\r"
            else:
                row["status"] = ["OK"]
            self.refuse(value)

    def test_non_builtin_mappings_keys_and_cycles_are_not_traversed(self):
        class Dict(dict):
            def __iter__(self):
                raise AssertionError("mapping iteration")

        class Str(str):
            def __eq__(self, other):
                raise AssertionError("string equality")
            __hash__ = str.__hash__

        self.refuse(Dict(evidence()))
        value = evidence()
        value[Str("present")] = value.pop("present")
        self.refuse(value)
        cycle = {}
        cycle["loop"] = cycle
        value = evidence()
        value["records"][0]["value"] = cycle
        self.assertIsNone(self.reduce(value)["receipt"])
        value = evidence()
        value["records"][0]["value"] = Dict(receipt()["value"])
        self.assertIsNone(self.reduce(value)["receipt"])

    def test_raw_receipt_fingerprint_is_not_an_artifact_target_pin(self):
        value = evidence()
        value["records"][0]["sha256"] = OTHER
        result = self.reduce(value)
        self.assertEqual(result["state"], "ACCEPTED")
        self.assertEqual(result["receipt"]["sha256"], OTHER)
        value["records"][0]["sha256"] = None
        self.assertEqual(self.reduce(value)["state"], "UNKNOWN")

    def test_deterministic_independent_output_and_no_input_mutation(self):
        value = evidence([receipt(note="not normalized e\u0301")])
        before = copy.deepcopy(value)
        first = self.reduce(value)
        self.assertEqual(value, before)
        self.assertEqual(canonical(first), canonical(self.reduce(value)))
        first["current"]["result_sha256"] = None
        first["receipt"]["note"] = "changed DTO"
        first["notes"].append("external")
        self.assertEqual(value, before)
        self.assertEqual(self.reduce(value)["state"], "ACCEPTED")

    def test_pure_reducer_cannot_open_resolve_spawn_or_call_provider(self):
        with mock.patch("builtins.open", side_effect=AssertionError("I/O")), \
             mock.patch("os.open", side_effect=AssertionError("I/O")), \
             mock.patch("pathlib.Path.resolve", side_effect=AssertionError("source")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("process")):
            self.assertEqual(self.reduce(evidence())["state"], "ACCEPTED")
            self.assertEqual(self.reduce(evidence(catalog_partial=True))["state"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
