"""Invented Python/Java saved metadata; no files, providers or live-state probes."""

import copy
import json
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, canonical
from run_history import CODES, MAX_SAFE, NOTES, STATES, review_record, search_history


PIN = "a" * 64
RESULT_FIELDS = {"version", "query", "project", "state", "history_sha256", "runs", "projects",
                 "inspected", "matched", "returned", "catalog_truncated", "result_truncated", "limit", "notes"}
ROW_FIELDS = {"id", "project", "project_name", "goal_excerpt", "goal_truncated", "state", "created",
              "record_sha256", "match_fields"}
REVIEW_FIELDS = {"version", "id", "project", "project_name", "goal", "state", "created", "record_sha256",
                 "history_sha256", "notes"}


def record(number=1, **metadata):
    identifier = format(number, "016x")
    value = {"id": identifier, "project": "python_old", "project_name": "Invented Python project",
             "goal": "Review invented arithmetic.", "state": "REVIEW_READY", "created": 1}
    value.update(metadata)
    return {"id": identifier, "metadata": value, "record_sha256": format(number, "064x")}


def request(query="", project="", state=""):
    return {"query": query, "project": project, "state": state}


@contextmanager
def pure_guard():
    with ExitStack() as stack:
        for target in ("builtins.open", "os.open", "pathlib.Path.resolve", "pathlib.Path.stat",
                       "subprocess.Popen", "subprocess.run", "agent.read_file", "agent.Ollama.request",
                       "agent.Ollama.preflight", "agent.ScriptedDemo.request", "agent.Session.checks"):
            stack.enter_context(patch(target, side_effect=AssertionError("history helper reached " + target)))
        yield


class RunHistoryTests(unittest.TestCase):
    def refused(self, code, operation, *args, **kwargs):
        with self.assertRaises(Refused) as caught:
            operation(*args, **kwargs)
        self.assertEqual(str(caught.exception), "HISTORY_SEARCH_" + code)
        self.assertIn(str(caught.exception), CODES)

    def test_empty_search_has_exact_schema_and_honest_zero_counts(self):
        result = search_history([], request(), PIN)
        self.assertEqual(result, {"version": 1, "query": "", "project": "", "state": "", "history_sha256": PIN,
            "runs": [], "projects": [], "inspected": 0, "matched": 0, "returned": 0,
            "catalog_truncated": False, "result_truncated": False, "limit": 100, "notes": []})
        self.assertEqual(set(result), RESULT_FIELDS)

    def test_search_matches_full_goal_beyond_prefix_and_keeps_literal_visible(self):
        goal = "x" * 300 + "Late needle Ω 🧪" + "y" * 300
        value = record(goal=goal)
        result = search_history([value], request("Late needle Ω 🧪"), PIN)
        self.assertEqual((result["inspected"], result["matched"], result["returned"]), (1, 1, 1))
        row = result["runs"][0]
        self.assertEqual(row["goal_excerpt"], "…Late needle Ω 🧪…")
        self.assertTrue(row["goal_truncated"])
        self.assertEqual(row["match_fields"], ["goal"])
        self.assertNotIn(goal, canonical(result).decode())
        self.assertEqual(set(row), ROW_FIELDS)

    def test_id_and_goal_match_fields_use_fixed_order(self):
        value = record(0xAB, goal="Check literal 00ab in invented Java.")
        row = search_history([value], request("00ab"), PIN)["runs"][0]
        self.assertEqual(row["match_fields"], ["id", "goal"])
        self.assertEqual(search_history([value], request(value["id"]), PIN)["runs"][0]["match_fields"], ["id"])
        self.assertEqual(search_history([value], request(), PIN)["runs"][0]["match_fields"], [])

    def test_unicode_combining_and_case_queries_remain_literal(self):
        values = [record(1, goal="café Ω 🧪"), record(2, goal="cafe\u0301 ω 🧪")]
        for query, expected in (("café", 1), ("cafe\u0301", 2), ("Ω", 1), ("ω", 2)):
            result = search_history(values, request(query), PIN)
            self.assertEqual([row["id"] for row in result["runs"]], [format(expected, "016x")])
        self.assertEqual(search_history(values, request("CAFÉ"), PIN)["matched"], 0)
        self.assertEqual(search_history(values, request("🧪"), PIN)["matched"], 2)

    def test_whitespace_query_is_not_trimmed_or_split_into_words(self):
        values = [record(1, goal="left  right"), record(2, goal="left right")]
        result = search_history(values, request("  "), PIN)
        self.assertEqual(result["query"], "  ")
        self.assertEqual([row["id"] for row in result["runs"]], [values[0]["id"]])

    def test_project_and_outcome_filters_isolate_python_java_and_historical_ids(self):
        values = [record(1, project="python_removed", state="FAILED"),
                  record(2, project="java_removed", state="UNCERTAIN"),
                  record(3, project="java_removed", state="REVIEW_READY")]
        result = search_history(values, request(project="java_removed", state="UNCERTAIN"), PIN)
        self.assertEqual([row["id"] for row in result["runs"]], [values[1]["id"]])
        self.assertEqual(result["projects"], ["java_removed", "python_removed"])
        self.assertEqual(search_history(values, request(project="not_configured"), PIN)["matched"], 0)

    def test_unknown_filters_keep_missing_invalid_and_new_states_unknown(self):
        unknown = {"id": "1" * 16, "metadata": {}, "record_sha256": "1" * 64}
        invalid = record(2, project="INVALID", state="FINISHED_SUCCESSFULLY")
        active = record(3, state="RUNNING")
        result = search_history([unknown, invalid, active], request(project="UNKNOWN", state="UNKNOWN"), PIN)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["projects"], ["python_old", "UNKNOWN"])
        self.assertTrue(all(row["project"] is None and row["state"] is None for row in result["runs"]))
        self.assertEqual(result["notes"], ["RECORD_INVALID"])
        self.assertEqual(search_history([active], request(state="RUNNING"), PIN)["runs"][0]["state"], "RUNNING")

    def test_legacy_missing_fields_are_nullable_without_invented_invalid_notes(self):
        value = {"id": "b" * 16, "metadata": {"legacy": "ignored"}, "record_sha256": "c" * 64}
        reviewed = review_record(value, PIN)
        self.assertEqual(set(reviewed), REVIEW_FIELDS)
        self.assertEqual(reviewed["notes"], [])
        self.assertTrue(all(reviewed[name] is None for name in ["project", "project_name", "goal", "state", "created"]))

    def test_invalid_recognized_fields_are_never_coerced_or_used_for_matching(self):
        for name, invalids in {"project": [None, 1, "A", "x" * 33],
                              "project_name": [None, [], "x" * 321, "bad\0name", "\ud800"],
                              "goal": [None, 1, "x" * 2001, "bad\0goal", "\udfff"],
                              "state": [None, True, "SUCCESS", "failed"],
                              "created": [None, True, -1, MAX_SAFE + 1, 1.5]}.items():
            for invalid in invalids:
                with self.subTest(field=name, value_type=type(invalid).__name__):
                    value = record(**{name: invalid})
                    reviewed = review_record(value, PIN)
                    self.assertIsNone(reviewed[name])
                    self.assertEqual(reviewed["notes"], ["RECORD_INVALID"])
        self.assertEqual(search_history([record(goal="x" * 2001 + "needle")], request("needle"), PIN)["matched"], 0)

    def test_private_extras_are_ignored_without_traversal_or_serialization(self):
        value = record()
        cycle = []; cycle.append(cycle)
        value["metadata"].update(source="PRIVATE_SOURCE_NEVER_RETURN", model="PRIVATE_MODEL_NEVER_RETURN",
                                 pid=999, events=cycle, provider=object())
        with pure_guard():
            found = search_history([value], request(), PIN)
            reviewed = review_record(value, PIN)
        for result in [found, reviewed]:
            encoded = canonical(result)
            self.assertNotIn(b"PRIVATE_SOURCE_NEVER_RETURN", encoded)
            self.assertNotIn(b"PRIVATE_MODEL_NEVER_RETURN", encoded)
            self.assertNotIn(b'"pid"', encoded)
            self.assertNotIn(b'"events"', encoded)

    def test_sorting_is_created_descending_unknown_last_then_id_descending(self):
        values = [record(1, created=5), record(2, created=5), record(3, created=0), record(4, created=None)]
        missing = record(5); del missing["metadata"]["created"]; values.append(missing)
        before = copy.deepcopy(values)
        result = search_history(values, request(), PIN)
        self.assertEqual([row["id"] for row in result["runs"]], [values[i]["id"] for i in [1, 0, 2, 4, 3]])
        self.assertEqual(values, before)

    def test_all_saved_outcomes_are_retained_without_state_inference(self):
        values = [record(i + 1, state=state) for i, state in enumerate(sorted(STATES))]
        for state in STATES:
            result = search_history(values, request(state=state), PIN)
            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["runs"][0]["state"], state)
        self.assertEqual(len(STATES), 8)

    def test_100_row_cap_preserves_total_inspected_and_matched(self):
        values = [record(i + 1, created=i) for i in range(200)]
        result = search_history(values, request(), PIN)
        self.assertEqual((result["inspected"], result["matched"], result["returned"]), (200, 200, 100))
        self.assertEqual(result["runs"][0]["id"], values[-1]["id"])
        self.assertEqual(result["runs"][-1]["id"], values[100]["id"])
        self.assertTrue(result["result_truncated"])
        self.assertFalse(result["catalog_truncated"])
        self.assertEqual(result["notes"], ["RESULT_TRUNCATED"])

    def test_partial_catalog_is_reported_even_when_every_match_is_returned(self):
        result = search_history([record()], request(), PIN, catalog_truncated=True)
        self.assertEqual((result["inspected"], result["matched"], result["returned"]), (1, 1, 1))
        self.assertTrue(result["catalog_truncated"])
        self.assertFalse(result["result_truncated"])
        self.assertEqual(result["notes"], ["CATALOG_TRUNCATED"])

    def test_utf8_labels_are_clipped_on_character_boundaries(self):
        value = record(project_name="Ω" * 100, goal="🧪" * 100)
        row = search_history([value], request(), PIN)["runs"][0]
        self.assertEqual(row["project_name"], "Ω" * 78 + "…")
        self.assertEqual(row["goal_excerpt"], "🧪" * 39 + "…")
        self.assertLessEqual(len(row["project_name"].encode()), 160)
        self.assertLessEqual(len(row["goal_excerpt"].encode()), 160)
        self.assertTrue(row["goal_truncated"])
        self.assertEqual(search_history([value], request(), PIN)["notes"], ["LABEL_TRUNCATED"])

    def test_maximum_query_keeps_a_late_full_literal_visible_in_clipped_goal(self):
        query = "🧪" * 32
        result = search_history([record(goal="a" * 300 + query + "b" * 300)], request(query), PIN)
        excerpt = result["runs"][0]["goal_excerpt"]
        self.assertIn(query, excerpt)
        self.assertEqual(len(excerpt.encode()), 134)
        self.assertTrue(result["runs"][0]["goal_truncated"])

    def test_adaptive_canonical_bound_drops_only_trailing_sorted_rows(self):
        values = [record(i + 1, project="historical_" + format(i, "03d"), project_name="\u0001" * 320,
                         goal="\u0002" * 1999 + "x", created=i) for i in range(200)]
        result = search_history(values, request(), PIN, catalog_truncated=True)
        self.assertEqual((result["inspected"], result["matched"]), (200, 200))
        self.assertGreater(result["returned"], 0)
        self.assertLess(result["returned"], 100)
        self.assertLessEqual(len(canonical(result)), 65536)
        self.assertEqual(result["returned"], len(result["runs"]))
        self.assertEqual([row["id"] for row in result["runs"]],
                         [value["id"] for value in reversed(values)][:(result["returned"])])
        self.assertEqual(len(result["projects"]), 200)
        self.assertEqual(result["notes"], ["CATALOG_TRUNCATED", "LABEL_TRUNCATED", "RESULT_TRUNCATED"])
        self.assertEqual(json.loads(canonical(result)), result)

    def test_review_returns_full_bounded_clean_metadata_only(self):
        value = record(project_name="Ω" * 160, goal="🧪" * 2000, created=MAX_SAFE)
        reviewed = review_record(value, PIN)
        self.assertEqual(set(reviewed), REVIEW_FIELDS)
        self.assertEqual(reviewed["project_name"], "Ω" * 160)
        self.assertEqual(reviewed["goal"], "🧪" * 2000)
        self.assertEqual(reviewed["record_sha256"], value["record_sha256"])
        self.assertEqual(reviewed["history_sha256"], PIN)
        self.assertEqual(reviewed["created"], MAX_SAFE)
        self.assertEqual(reviewed["notes"], [])
        self.assertLessEqual(len(canonical(reviewed)), 65536)

    def test_full_goal_and_label_limits_allow_empty_metadata_text_and_exact_crlf(self):
        value = record(project_name="", goal="\r\n Ω \r\n")
        reviewed = review_record(value, PIN)
        self.assertEqual(reviewed["goal"], "\r\n Ω \r\n")
        self.assertEqual(reviewed["project_name"], "")
        self.assertEqual(review_record(record(goal=""), PIN)["goal"], "")
        self.assertEqual(review_record(record(project_name="🧪" * 81), PIN)["notes"], ["RECORD_INVALID"])

    def test_selected_review_cannot_smuggle_another_filename_identity(self):
        value = record()
        for identifier in (None, 1, "2" * 16, value["id"].upper() + "A"):
            changed = copy.deepcopy(value); changed["metadata"]["id"] = identifier
            self.refused("RECORD_INVALID", review_record, changed, PIN)
        del value["metadata"]["id"]
        self.assertEqual(review_record(value, PIN)["id"], value["id"])

    def test_duplicate_ids_are_refused_instead_of_silently_deduplicated(self):
        first, second = record(), record()
        second["metadata"]["project"] = "java_other"
        second["record_sha256"] = "f" * 64
        self.refused("RECORD_INVALID", search_history, [first, second], request(), PIN)

    def test_wrapper_id_hash_container_and_key_bounds_are_exact(self):
        valid = record()
        invalids = [None, [], {}, {**valid, "extra": True}, {**valid, "metadata": []},
                    {**valid, "id": "A" * 16}, {**valid, "id": "1" * 15},
                    {**valid, "record_sha256": "F" * 64}, {**valid, "record_sha256": "f" * 63},
                    {**valid, "record_sha256": None}, {**valid, "record_sha256": "g" * 64}]
        for value in invalids:
            self.refused("RECORD_INVALID", search_history, [value], request(), PIN)
            self.refused("RECORD_INVALID", review_record, value, PIN)
        metadata = {"ignored_" + str(i): None for i in range(64)}
        self.assertEqual(review_record({**valid, "metadata": metadata}, PIN)["notes"], [])
        metadata["one_too_many"] = None
        self.refused("RECORD_INVALID", review_record, {**valid, "metadata": metadata}, PIN)
        self.refused("RECORD_INVALID", search_history, tuple([valid]), request(), PIN)
        self.refused("LIMIT", search_history, [record(i + 1) for i in range(201)], request(), PIN)

    def test_request_containers_keys_and_types_are_input_errors(self):
        for value in (None, [], {}, {"query": "", "project": ""}, {**request(), "extra": ""},
                      request(query=None), request(project=1), request(state=False)):
            self.refused("INPUT", search_history, [], value, PIN)
        for pin in (None, True, "f" * 63, "F" * 64, "g" * 64):
            self.refused("INPUT", search_history, [], request(), pin)
            self.refused("INPUT", review_record, record(), pin)
        for flag in (None, 0, 1, "false"):
            self.refused("INPUT", search_history, [], request(), PIN, catalog_truncated=flag)

    def test_query_and_filter_values_have_finite_specific_errors(self):
        for query in ("x" * 129, "🧪" * 33, "a\0b", "a\nb", "a\rb", "\ud800", "\udfff"):
            self.refused("QUERY", search_history, [], request(query), PIN)
        for project in ("Unknown", "ALL", "A", "a" * 33, "../private", "\ud800"):
            self.refused("FILTER", search_history, [], request(project=project), PIN)
        for state in ("ready", "SUCCESS", "Unknown", "RUNNING\n"):
            self.refused("FILTER", search_history, [], request(state=state), PIN)

    def test_notes_are_finite_deduplicated_sorted_and_rows_never_contain_full_goal(self):
        values = [record(1, goal="x" * 300, created=True), record(2, project_name="Ω" * 100, state="NEW")]
        result = search_history(values, request(), PIN, catalog_truncated=True)
        self.assertEqual(result["notes"], ["CATALOG_TRUNCATED", "LABEL_TRUNCATED", "RECORD_INVALID"])
        self.assertTrue(set(result["notes"]) <= NOTES)
        self.assertTrue(all(set(row) == ROW_FIELDS and "goal" not in row for row in result["runs"]))
        self.assertEqual(result["matched"], 2)

    def test_pure_search_and_review_preserve_inputs_and_do_not_access_runtime(self):
        values = [record(1), record(2, project="java_old", state="UNCERTAIN")]
        before = copy.deepcopy(values); filters = request("invented")
        with pure_guard():
            first = search_history(values, filters, PIN)
            second = search_history(values, filters, PIN)
            selected = review_record(values[1], PIN)
        self.assertEqual(first, second)
        self.assertEqual(values, before)
        self.assertEqual(filters, request("invented"))
        self.assertEqual(selected["state"], "UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
