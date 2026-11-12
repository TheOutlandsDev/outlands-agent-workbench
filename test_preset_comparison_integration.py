"""Private invented preset comparisons: read-only planning, no inference."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_bundle_workspace_integration import private_hashes
from test_task_presets_integration import (
    build_presets_manager, close_and_reload, list_request, load_request, preset_fixture, preset_guard,
    preset_http_fixture, preset_path, save_one, save_request,
)


def preview_request(listed, draft, row=None):
    return {**load_request(listed, row), "draft_goal": draft}


def assert_comparison(test, result, listed, draft, saved, prefix=None, suffix=None):
    test.assertEqual(set(result), {"version", "project_id", "preset_id", "name", "binding_sha256",
                                   "record_sha256", "history_sha256", "comparison"})
    row = next(row for row in listed["presets"] if row["id"] == result["preset_id"])
    test.assertEqual({key: result[key] for key in ["version", "project_id", "binding_sha256", "history_sha256"]},
                     {key: listed[key] for key in ["version", "project_id", "binding_sha256", "history_sha256"]})
    test.assertEqual((result["name"], result["record_sha256"]), (row["name"], row["record_sha256"]))
    value = result["comparison"]
    test.assertEqual(set(value), {"version", "format", "draft_goal", "saved_goal", "draft_sha256", "saved_sha256",
                                  "identical", "prefix_chars", "suffix_chars"})
    test.assertEqual((value["version"], value["format"]), (1, "outlands-task-preset-comparison-v1"))
    test.assertEqual((value["draft_goal"], value["saved_goal"]), (draft, saved))
    test.assertEqual((value["draft_sha256"], value["saved_sha256"]), (sha(draft.encode()), sha(saved.encode())))
    test.assertIs(value["identical"], draft == saved)
    common, tail = value["prefix_chars"], value["suffix_chars"]
    test.assertIs(type(common), int); test.assertIs(type(tail), int)
    test.assertTrue(0 <= common <= min(len(draft), len(saved)))
    test.assertTrue(0 <= tail <= min(len(draft), len(saved)) - common)
    test.assertEqual(draft[:common], saved[:common])
    if tail: test.assertEqual(draft[-tail:], saved[-tail:])
    if draft == saved:
        test.assertEqual((common, tail), (len(draft), 0))
    if prefix is not None: test.assertEqual(common, prefix)
    if suffix is not None: test.assertEqual(tail, suffix)
    test.assertLessEqual(len(canonical(result)), 65536)


class PresetComparisonIntegrationTests(unittest.TestCase):
    def refusal(self, root, manager, request, code=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            manager.task_preset_preview(request)
        self.assertRegex(str(caught.exception), r"^TASK_PRESET_[A-Z_]{1,48}$")
        if code is not None: self.assertEqual(str(caught.exception), code)
        self.assertNotIn(str(root), str(caught.exception))
        self.assertEqual(before, private_hashes(root))

    def test_python_java_exact_preview_changes_no_task_selection_or_private_bytes(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            for language, fixture in fixtures.items():
                goal = "Invented " + language + " saved goal — café Ω.\r\nPreserve permissions."
                draft = "Invented " + language + " current draft — 🧪.\nDo not replace Task."
                listed, _ = save_one(manager, fixture, "Compare " + language, goal)
                definitions = copy.deepcopy({key: project["definition"] for key, project in manager.projects.items()})
                drafts = copy.deepcopy(manager.drafts)
                before = private_hashes(root)
                result = manager.task_preset_preview(preview_request(listed, draft))
                assert_comparison(self, result, listed, draft, goal)
                self.assertNotIn("goal", result)
                self.assertEqual(definitions, {key: project["definition"] for key, project in manager.projects.items()})
                self.assertEqual(drafts, manager.drafts)
                self.assertEqual(before, private_hashes(root))
                self.assertNotIn(str(root), json.dumps(result))

    def test_each_preview_uses_exact_current_supplied_draft_including_empty_and_blank(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            saved = "This invented saved goal stays private and fixed."
            listed, _ = save_one(manager, fixture, "Current draft", saved)
            original_goal = manager.projects[fixture["project_id"]]["definition"]["goal"]
            before = private_hashes(root)
            for draft in ["", " \t\r\n", "first invented draft", "second invented draft", original_goal, saved]:
                with self.subTest(draft=draft):
                    result = manager.task_preset_preview(preview_request(listed, draft))
                    assert_comparison(self, result, listed, draft, saved)
            self.assertEqual(manager.projects[fixture["project_id"]]["definition"]["goal"], original_goal)
            self.assertEqual(before, private_hashes(root))

    def test_unicode_codepoint_spans_exact_newlines_and_literal_markup_are_preserved(self):
        cases = [("prefix old suffix", "prefix new suffix", 7, 7), ("same", "same", 4, 0),
                 ("", "saved", 0, 0), ("abc", "abcXYZ", 3, 0), ("abcXYZ", "abc", 3, 0),
                 ("ababa", "acaba", 1, 3), ("🧪AΩ", "🧪BΩ", 1, 1),
                 ("cafe\u0301\r\n<script>draft</script>", "café\n<script>saved</script>", 3, 9)]
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            for number, (draft, goal, prefix, suffix) in enumerate(cases):
                with self.subTest(number=number):
                    listed, saved = save_one(manager, fixtures["python"], "Span " + str(number), goal)
                    row = next(row for row in listed["presets"] if row["id"] == saved["preset"]["id"])
                    before = private_hashes(root)
                    result = manager.task_preset_preview(preview_request(listed, draft, row))
                    assert_comparison(self, result, listed, draft, goal, prefix, suffix)
                    self.assertEqual(before, private_hashes(root))

    def test_maximum_escaped_goals_are_complete_and_bounded_without_clipping(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            for number, (draft, goal) in enumerate([("🧪" * 2000, "😀" * 2000), ("d" + "\x01" * 1999, "s" + "\x02" * 1999)]):
                listed, saved = save_one(manager, fixtures["python"], "Maximum " + str(number), goal)
                row = next(row for row in listed["presets"] if row["id"] == saved["preset"]["id"])
                request = preview_request(listed, draft, row)
                self.assertLessEqual(len(canonical(request)), 32768)
                before = private_hashes(root)
                result = manager.task_preset_preview(request)
                assert_comparison(self, result, listed, draft, goal, 0, 0)
                self.assertEqual(before, private_hashes(root))

    def test_exact_request_fields_and_draft_bounds_refuse_without_writes(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            listed, _ = save_one(manager, fixtures["python"])
            request = preview_request(listed, "Invented current draft.")
            for draft in [None, True, 1, [], {}, "x\x00y", "\ud800", "x" * 2001]:
                self.refusal(root, manager, {**request, "draft_goal": draft}, "TASK_PRESET_DRAFT_INVALID")
            for invalid in [{}, {**request, "unexpected": True}, {key: value for key, value in request.items() if key != "draft_goal"},
                            {**request, "project_id": "../outside"}, {**request, "preset_id": True}]:
                self.refusal(root, manager, invalid)

    def test_cross_project_ids_do_not_reveal_another_project_saved_goal(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            python, _ = save_one(manager, fixtures["python"], "Python only", "Invented Python private comparison sentinel")
            java = manager.task_preset_list(list_request(fixtures["java"]))
            request = preview_request(python, "Invented Java draft.")
            request.update({key: java[key] for key in ["project_id", "binding_sha256", "history_sha256"]})
            self.refusal(root, manager, request, "TASK_PRESET_NOT_FOUND")
            self.assertNotIn("sentinel", json.dumps(java))

    def test_stale_history_binding_and_raw_record_hash_pins_refuse(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            listed, _ = save_one(manager, fixture)
            request = preview_request(listed, "Current invented draft.")
            for key in ["history_sha256", "binding_sha256", "record_sha256"]:
                self.refusal(root, manager, {**request, key: "0" * 64})
            path = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
            path.write_bytes(path.read_bytes() + b" \n")
            self.refusal(root, manager, request)
            fresh = manager.task_preset_list(list_request(fixture))
            self.refusal(root, manager, {**preview_request(fresh, "Another draft."), "record_sha256": request["record_sha256"]})
            current = preview_request(fresh, "Another draft.")
            manager.task_preset_save(save_request(fresh, "Another saved task"))
            self.refusal(root, manager, current, "TASK_PRESET_HISTORY_CHANGED")

    def test_changed_loaded_config_or_task_bytes_refuse_preview(self):
        for kind in ["config", "task"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                target = manager.config_path if kind == "config" else fixture["task"]
                target.write_bytes(target.read_bytes() + b" \n")
                self.refusal(root, manager, preview_request(listed, "Invented draft."), "TASK_PRESET_PROJECT_CHANGED")

    def test_valid_changed_profile_lists_stale_and_refuses_preview_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manager, fixtures = build_presets_manager(root)
            fixture = fixtures["java"]
            try:
                with preset_guard(manager): listed, _ = save_one(manager, fixture)
                task = json.loads(fixture["task"].read_bytes())
                task["max_turns"] -= 1
                fixture["task"].write_bytes(canonical(task))
                manager = close_and_reload(manager)
                with preset_guard(manager):
                    fresh = manager.task_preset_list(list_request(fixture))
                    self.assertFalse(fresh["presets"][0]["compatible"])
                    self.refusal(root, manager, preview_request(fresh, "Current draft."), "TASK_PRESET_INCOMPATIBLE")
            finally:
                manager.close()

    def test_unsafe_partial_malformed_and_linked_stores_refuse_without_repair(self):
        for kind in ["partial", "extra", "stage", "mode", "symlink", "hardlink", "ancestor"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                path = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
                if kind == "partial": path.write_bytes(b'{"version":')
                elif kind == "extra":
                    record = json.loads(path.read_bytes()); record["unexpected"] = True; path.write_bytes(canonical(record))
                elif kind == "stage": write_new(path.with_suffix(".json.next"), b"Invented retained partial")
                elif kind == "mode": path.chmod(0o640)
                elif kind == "hardlink": os.link(path, root / "invented-record-link")
                elif kind == "symlink":
                    alternate = root / "invented-record-copy"; write_new(alternate, path.read_bytes())
                    path.unlink(); path.symlink_to(alternate)
                else:
                    original = path.parent; moved = original.with_name("invented-original")
                    original.rename(moved); original.symlink_to(moved, target_is_directory=True)
                self.refusal(root, manager, preview_request(listed, "Current draft."))

    def test_preview_does_not_read_source_or_reconcile_unrelated_hold_workers_jobs(self):
        with preset_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            hold = manager.data / "state/hold.json"
            hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented comparison planning hold", "turn": 1})
            write_new(hold, hold_raw)
            write_new(manager.data / "jobs" / ("a" * 16 + ".json"), canonical({"id": "a" * 16, "state": "RUNNING"}))
            child = Mock(); child.poll.side_effect = AssertionError("preview polled worker")
            manager.children["a" * 16] = (child, Mock())
            target = fixture["source"] / fixture["editable"]
            target.write_bytes(target.read_bytes() + b"# Invented changed source, not Run.\n")
            try:
                with preset_guard(manager):
                    listed, _ = save_one(manager, fixture)
                    before = private_hashes(root)
                    result = manager.task_preset_preview(preview_request(listed, "Held current draft."))
                    self.assertEqual(result["comparison"]["draft_goal"], "Held current draft.")
                    self.assertEqual(before, private_hashes(root))
                self.assertEqual(hold.read_bytes(), hold_raw)
                child.poll.assert_not_called()
            finally:
                manager.children.clear()

    def test_preview_repins_config_task_and_history_after_computation(self):
        import workbench
        for kind in ["config", "task", "history"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                request = preview_request(listed, "Invented changing-context draft.")
                original = workbench.compare_goals
                def drift(draft, saved):
                    result = original(draft, saved)
                    target = manager.config_path if kind == "config" else fixture["task"] if kind == "task" else preset_path(
                        manager, fixture["project_id"], listed["presets"][0]["id"])
                    target.write_bytes(target.read_bytes() + b" \n")
                    return result
                with patch("workbench.compare_goals", side_effect=drift):
                    with self.assertRaises(Refused) as caught:
                        manager.task_preset_preview(request)
                self.assertEqual(str(caught.exception), "TASK_PRESET_HISTORY_CHANGED" if kind == "history" else "TASK_PRESET_PROJECT_CHANGED")

    def test_restart_preview_is_deterministic_and_explicit_load_stays_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manager, fixtures = build_presets_manager(root)
            fixture = fixtures["python"]
            try:
                with preset_guard(manager):
                    listed, _ = save_one(manager, fixture, "Restart comparison", "Invented saved restart goal.")
                    request = preview_request(listed, "Distinct current draft.")
                    before_preview = manager.task_preset_preview(request)
                before = private_hashes(root)
                manager = close_and_reload(manager)
                with preset_guard(manager):
                    fresh = manager.task_preset_list(list_request(fixture))
                    after_preview = manager.task_preset_preview(preview_request(fresh, "Distinct current draft."))
                    self.assertEqual(before_preview, after_preview)
                    loaded = manager.task_preset_load(load_request(fresh))
                    self.assertEqual(loaded["goal"], after_preview["comparison"]["saved_goal"])
                    self.assertNotIn("comparison", loaded)
                self.assertEqual(before, private_hashes(root))
            finally:
                manager.close()


class PresetComparisonHTTPTests(unittest.TestCase):
    def test_python_java_http_preview_roundtrip_preserves_task_and_existing_load(self):
        with preset_http_fixture() as (root, manager, fixtures, request), preset_guard(manager):
            for language, fixture in fixtures.items():
                goal, draft = "Saved " + language + " goal café Ω.", "Current " + language + " draft 🧪."
                listed, _ = save_one(manager, fixture, "HTTP comparison", goal)
                before = private_hashes(root)
                status, value = request("/api/task-preset-preview", preview_request(listed, draft))
                self.assertEqual(status, 200)
                assert_comparison(self, value, listed, draft, goal)
                status, loaded = request("/api/task-preset-load", load_request(listed))
                self.assertEqual((status, loaded["goal"]), (200, goal))
                self.assertEqual(before, private_hashes(root))

    def test_preview_http_strict_framing_authentication_and_origin_precede_action(self):
        with preset_http_fixture() as (root, manager, fixtures, request):
            value = {"invented": "request"}
            with patch.object(manager, "task_preset_preview", side_effect=AssertionError("bad HTTP reached preview")) as invoke:
                for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                    {"Content-Length": "32769"}, {"Content-Length": "999"}, {"Content-Type": "application/zip"},
                    [("Content-Length", str(len(canonical(value))))], [("Content-Type", "application/json")]]:
                    before = private_hashes(root)
                    code, result = request("/api/task-preset-preview", value, headers)
                    self.assertEqual(code, 409)
                    self.assertRegex(result["error"], r"^TASK_PRESET_[A-Z_]+$")
                    self.assertEqual(before, private_hashes(root))
                for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"),
                    ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"), ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                    ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                    code, result = request("/api/task-preset-preview", value, headers)
                    self.assertEqual((code, result["error"]), (409, error))
                invoke.assert_not_called()

    def test_preview_http_duplicate_json_invalid_utf8_and_output_limit_refuse(self):
        with preset_http_fixture() as (root, manager, fixtures, request):
            for raw in [b'{"draft_goal":"x","draft_goal":"y"}', b"\xff", b"[]"]:
                before = private_hashes(root)
                code, result = request("/api/task-preset-preview", {}, raw=raw)
                self.assertEqual(code, 409)
                self.assertRegex(result["error"], r"^TASK_PRESET_[A-Z_]+$")
                self.assertEqual(before, private_hashes(root))
            with patch.object(manager, "task_preset_preview", return_value={"invented": "x" * 65536}):
                code, result = request("/api/task-preset-preview", {})
                self.assertEqual((code, result["error"]), (409, "TASK_PRESET_OUTPUT_LIMIT"))


if __name__ == "__main__":
    unittest.main()
