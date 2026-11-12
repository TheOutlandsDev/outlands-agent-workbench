"""Invented pure preset profiles; no storage, project code or model execution."""

import copy
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha
import task_presets as presets


def project(language="python", *, legacy=False):
    if language == "python":
        files = {"module.py": sha(b"invented implementation"), "test_module.py": sha(b"invented protected tests")}
        check = "test_module.py" if legacy else {"kind": "python-unittest", "pattern": "test_module.py"}
        editable = ["module.py"]
    else:
        files = {"sample/Module.java": sha(b"invented Java"), "sample/ModuleTest.java": sha(b"invented protected main")}
        check = {"kind": "java-main", "sources": sorted(files), "main_class": "sample.ModuleTest"}
        editable = ["sample/Module.java"]
    task = {"format": "outlands-coding-agent-v1" if legacy else "outlands-coding-agent-v2",
            "goal": "Invented default goal", "files": files, "editable": editable,
            "checks": {"unit": check}, "max_turns": 12, "request_seconds": 120}
    return {"id": "invented_" + language, "name": "Invented " + language,
            "source": Path("/absolute/invented-private-" + language), "definition": task,
            "task_raw": canonical(task), "task": Path("/absolute/private-config/task.json")}


def record(value=None, *, name="Fix checks", goal="Fix the selected implementation while preserving protected checks."):
    value = project() if value is None else value
    return {"version": 1, "format": presets.FORMAT, "id": "1" * 16, "created": 1,
            **presets.prepare(value, name, goal)}


@contextmanager
def pure_guard():
    with ExitStack() as stack:
        for name in ("builtins.open", "os.open", "pathlib.Path.resolve", "pathlib.Path.stat",
                     "subprocess.Popen", "subprocess.run", "agent.read_file"):
            stack.enter_context(patch(name, side_effect=AssertionError("pure preset helper reached " + name)))
        yield


class TaskPresetTests(unittest.TestCase):
    def refused(self, code, operation, *args):
        with self.assertRaises(Refused) as caught:
            operation(*args)
        self.assertEqual(str(caught.exception), "TASK_PRESET_" + code)
        self.assertIn(str(caught.exception), presets.CODES)

    def test_python_java_and_legacy_profiles_are_pure_and_structurally_valid(self):
        for value in (project(), project("java"), project(legacy=True)):
            before = copy.deepcopy(value)
            with pure_guard():
                prepared = presets.prepare(value, "Small refactor", "Refactor the selected code without changing behavior.")
                saved = {"version": 1, "format": presets.FORMAT, "id": "2" * 16, "created": 123, **prepared}
                self.assertTrue(presets.validate_record(saved))
                self.assertTrue(presets.matches(saved, value))
            self.assertEqual(before, value)
            self.assertEqual(prepared["binding_sha256"], presets.profile(value))

    def test_profile_binds_project_identity_and_source_identity(self):
        value = project()
        expected = presets.profile(value)
        for key, replacement in (("id", "another_project"), ("source", Path("/absolute/another-source"))):
            changed = copy.deepcopy(value); changed[key] = replacement
            self.assertNotEqual(expected, presets.profile(changed))
            self.assertFalse(presets.matches(record(value), changed))

    def test_profile_ignores_source_hash_and_default_goal_refresh(self):
        value = project(); saved = record(value)
        refreshed = copy.deepcopy(value)
        refreshed["definition"]["goal"] = "Another approved default goal"
        refreshed["definition"]["files"] = {name: sha(("new bytes " + name).encode())
                                              for name in refreshed["definition"]["files"]}
        refreshed["task_raw"] = canonical(refreshed["definition"])
        self.assertEqual(presets.profile(value), presets.profile(refreshed))
        self.assertTrue(presets.matches(saved, refreshed))

    def test_profile_ignores_project_label_model_and_configuration_metadata(self):
        value = project(); changed = copy.deepcopy(value)
        changed.update(name="Renamed display only", models=["invented-model"], selected_model="invented-model",
                       config_sha256="f" * 64, task_raw=b"different formatting", task=Path("/absolute/new-task.json"))
        self.assertEqual(presets.profile(value), presets.profile(changed))

    def test_engine_valid_default_goal_values_are_excluded_without_weakening_new_preset_goals(self):
        value = project(); expected = presets.profile(value)
        for goal in (" ", "\x00", "\ud800"):
            changed = copy.deepcopy(value); changed["definition"]["goal"] = goal
            self.assertEqual(expected, presets.profile(changed))
            self.assertEqual(expected, presets.prepare(changed, "Valid preset", "A safe explicit new goal")["binding_sha256"])
            self.refused("GOAL_INVALID", presets.prepare, changed, "Invalid new preset", goal)

    def test_profile_canonicalizes_selected_and_editable_order_and_check_key_order(self):
        value = project(); task = value["definition"]
        task["files"]["helper.py"] = sha(b"invented helper")
        task["editable"].append("helper.py")
        task["checks"]["second"] = copy.deepcopy(task["checks"]["unit"])
        changed = copy.deepcopy(value)
        for key in ("files", "checks"):
            changed["definition"][key] = dict(reversed(list(task[key].items())))
        changed["definition"]["editable"].reverse()
        self.assertEqual(presets.profile(value), presets.profile(changed))

    def test_profile_changes_for_selected_scope_edit_permissions_and_budgets(self):
        value = project(); expected = presets.profile(value)
        variants = []
        changed = copy.deepcopy(value); changed["definition"]["files"]["helper.py"] = sha(b"new helper"); variants.append(changed)
        changed = copy.deepcopy(variants[0]); changed["definition"]["editable"].append("helper.py"); variants.append(changed)
        for key, replacement in (("max_turns", 11), ("request_seconds", 60)):
            changed = copy.deepcopy(value); changed["definition"][key] = replacement; variants.append(changed)
        for changed in variants:
            self.assertNotEqual(expected, presets.profile(changed))
            self.assertFalse(presets.matches(record(value), changed))

    def test_profile_changes_for_check_specification_and_task_format(self):
        value = project(); expected = presets.profile(value)
        changed = copy.deepcopy(value)
        changed["definition"]["checks"]["another"] = copy.deepcopy(changed["definition"]["checks"]["unit"])
        self.assertNotEqual(expected, presets.profile(changed))
        self.assertNotEqual(expected, presets.profile(project(legacy=True)))
        java = project("java"); changed = copy.deepcopy(java)
        changed["definition"]["checks"]["unit"]["sources"].reverse()
        self.assertNotEqual(presets.profile(java), presets.profile(changed))

    def test_name_nfc_casefold_duplicates_and_display_case_are_consistent(self):
        value = project()
        a = presets.prepare(value, "Café checks", "Goal")
        b = presets.prepare(value, "Cafe\u0301 CHECKS", "Goal")
        self.assertEqual(a["name"], "Café checks")
        self.assertEqual(b["name"], "Café CHECKS")
        self.assertEqual(a["name_key"], b["name_key"])
        self.assertEqual(presets.prepare(value, "Straße", "Goal")["name_key"],
                         presets.prepare(value, "STRASSE", "Goal")["name_key"])

    def test_name_limits_before_and_after_normalization(self):
        value = project()
        self.assertEqual(presets.prepare(value, "界" * 80, "Goal")["name"], "界" * 80)
        for bad in ("", "x" * 81, "😀" * 61, "e\u0301" * 41, None, 12, True):
            self.refused("NAME_INVALID", presets.prepare, value, bad, "Goal")

    def test_name_refuses_surrounding_whitespace_controls_and_invisible_formatting(self):
        value = project()
        for bad in (" leading", "trailing ", "\tname", "line\nname", "line\rname", "a\x00b", "a\x1bb",
                    "a\u2028b", "a\u2029b", "a\u200bb", "a\u202eb", "\ud800"):
            self.refused("NAME_INVALID", presets.prepare, value, bad, "Goal")

    def test_goal_text_is_exact_including_multiline_whitespace_and_unicode(self):
        value = project(); goal = "  Fix café checks.\r\nKeep the API.\n\tObserve actual results.  "
        before = copy.deepcopy(value)
        prepared = presets.prepare(value, "Goal text", goal)
        self.assertEqual(prepared["goal"], goal)
        self.assertEqual(before, value)

    def test_goal_bounds_blank_nul_and_invalid_unicode_refuse_without_leaks(self):
        value = project()
        self.assertEqual(presets.prepare(value, "Maximum", "😀" * 2000)["goal"], "😀" * 2000)
        for bad in ("", " \t\r\n", "x" * 2001, "a\x00b", "\udfff", None, 1, True):
            self.refused("GOAL_INVALID", presets.prepare, value, "Valid name", bad)

    def test_prepared_fields_do_not_forward_private_paths_or_model_metadata(self):
        value = project(); value["private_extra"] = "invented-private-sentinel"
        value["selected_model"] = "invented-model-label"
        prepared = presets.prepare(value, "Reviewed goal", "Fix the selected code")
        self.assertEqual(set(prepared), {"project_id", "name", "name_key", "goal", "binding_sha256"})
        raw = canonical(prepared)
        for omitted in (str(value["source"]).encode(), b"invented-private-sentinel", b"invented-model-label", b"test_module.py"):
            self.assertNotIn(omitted, raw)

    def test_valid_record_has_exact_finite_keys_and_no_automatic_task_fields(self):
        saved = record()
        self.assertTrue(presets.validate_record(saved))
        self.assertEqual(set(saved), presets.FIELDS)
        for extra in ("files", "editable", "checks", "models", "source", "status", "run", "task_sha256"):
            changed = {**saved, extra: "invented"}
            self.assertFalse(presets.validate_record(changed))
        for key in saved:
            changed = dict(saved); del changed[key]
            self.assertFalse(presets.validate_record(changed))

    def test_record_identity_version_time_and_binding_types_are_strict(self):
        saved = record()
        changes = {"version": [True, 0, 2, "1"], "format": [None, "other", 1],
                   "id": ["A" * 16, "a" * 15, "a" * 17, None],
                   "project_id": ["Another", "../bad", "", "a" * 33, None],
                   "created": [True, -1, presets.MAX_SAFE + 1, 1.0],
                   "binding_sha256": ["A" * 64, "a" * 63, "g" * 64, None]}
        for key, invalid in changes.items():
            for bad in invalid:
                self.assertFalse(presets.validate_record({**saved, key: bad}), (key, bad))
        self.assertTrue(presets.validate_record({**saved, "created": presets.MAX_SAFE}))

    def test_record_names_keys_and_goals_are_revalidated_without_normalizing_saved_evidence(self):
        saved = record(name="Café")
        for key, bad in (("name", "Cafe\u0301"), ("name", " Café"), ("name_key", "CAFE"),
                         ("name_key", 1), ("goal", "\x00"), ("goal", " "), ("goal", "\ud800")):
            self.assertFalse(presets.validate_record({**saved, key: bad}))

    def test_stale_records_remain_valid_but_cannot_match_changed_project(self):
        value = project(); saved = record(value)
        changed = copy.deepcopy(value); changed["definition"]["max_turns"] = 10
        self.assertTrue(presets.validate_record(saved))
        self.assertFalse(presets.matches(saved, changed))
        self.assertFalse(presets.matches({**saved, "goal": "\x00"}, value))
        self.assertFalse(presets.matches(None, value))

    def test_invalid_current_project_is_a_finite_profile_refusal(self):
        value = project()
        variants = [None, [], {}, {**value, "id": "../bad"}, {**value, "source": Path("relative")},
                    {**value, "source": "/absolute/../ambiguous"}, {**value, "source": "/absolute/\x00bad"},
                    {**value, "source": "/absolute/\ud800bad"}]
        for key, bad in (("files", {}), ("editable", ["test_module.py"]), ("checks", {}),
                         ("max_turns", True), ("request_seconds", 121), ("goal", "")):
            changed = copy.deepcopy(value); changed["definition"][key] = bad; variants.append(changed)
        for bad in variants:
            self.refused("PROFILE_INVALID", presets.profile, bad)
        self.refused("PROFILE_INVALID", presets.matches, record(value), {})

    def test_canonical_source_identity_is_lexical_without_filesystem_access(self):
        value = project()
        string_path = {**value, "source": str(value["source"])}
        with pure_guard():
            self.assertEqual(presets.profile(value), presets.profile(string_path))
            self.assertEqual(presets.prepare(value, "Lexical source", "Goal")["binding_sha256"], presets.profile(value))

    def test_maximum_unicode_record_stays_below_record_limit(self):
        saved = record(name="界" * 80, goal="😀" * 2000)
        self.assertLessEqual(len(canonical(saved)), presets.MAX_RECORD)
        self.assertTrue(presets.validate_record(saved))
        self.assertNotIn(b"/absolute/", canonical(saved))


if __name__ == "__main__":
    unittest.main()
