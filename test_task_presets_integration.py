"""Invented private preset fixtures: metadata only, never inference or execution.

Profiles use Python/Java task definitions; project code is not read by preset
actions. Separate fixed-check qualification is in qa_task_presets.py.
"""

import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from workbench import Manager, init_demo, make_handler


def build_presets_manager(root, jdk=None):
    """Fresh invented correct source profiles; no code/Git/provider is executed."""
    root.mkdir(mode=0o700)
    paths = init_demo(root / "workspace", None)
    config = Path(paths["config"])
    value = json.loads(config.read_bytes())
    fixtures = {}
    sources = {
        "python": {
            "arithmetic.py": b"def add(a, b):\n    return a + b\n",
            "constants.py": b"ZERO = 0\n",
            "test_arithmetic.py": b"import unittest\nfrom arithmetic import add\nclass SumTests(unittest.TestCase):\n    def test_positive(self): self.assertEqual(add(2, 3), 5)\n    def test_negative(self): self.assertEqual(add(-2, -3), -5)\n    def test_zero(self): self.assertEqual(add(0, 0), 0)\n    def test_mixed(self): self.assertEqual(add(-2, 3), 1)\n",
        },
        "java": {
            "sample/Sum.java": b"package sample;\npublic class Sum {\n    public static int add(int a, int b) { return a + b; }\n}\n",
            "sample/SumTest.java": b"package sample;\npublic class SumTest {\n    public static void main(String[] args) {\n        if (Sum.add(2, 3) != 5 || Sum.add(-2, -3) != -5 || Sum.add(0, 0) != 0 || Sum.add(-2, 3) != 1) throw new AssertionError(\"invented arithmetic mismatch\");\n    }\n}\n",
        },
    }
    for language, files in sources.items():
        source = root / ("source-" + language)
        source.mkdir(mode=0o700)
        for name, raw in files.items():
            target = source / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(target, raw)
        editable = "arithmetic.py" if language == "python" else "sample/Sum.java"
        check = ({"kind": "python-unittest", "pattern": "test_arithmetic.py"} if language == "python" else
                 {"kind": "java-main", "sources": sorted(files), "main_class": "sample.SumTest"})
        task = {"format": "outlands-coding-agent-v2", "goal": "Review this invented arithmetic module without changing its behavior.",
                "files": {name: sha(raw) for name, raw in sorted(files.items())}, "editable": [editable],
                "checks": {"unit": check}, "max_turns": 12, "request_seconds": 30}
        task_path = root / (language + "-task.json")
        write_new(task_path, canonical(task))
        identifier = "preset_" + language
        value["projects"].append({"id": identifier, "name": "Invented " + language + " preset project",
                                  "source": str(source), "task": str(task_path)})
        fixtures[language] = {"project_id": identifier, "source": source, "task": task_path,
                              "editable": editable, "files": files}
    config.write_bytes(canonical(value))
    manager = Manager(config, Path(paths["data_dir"]), jdk)
    return manager, fixtures


@contextmanager
def preset_fixture(jdk=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "fixture"
        manager, fixtures = build_presets_manager(root, jdk)
        try:
            yield root, manager, fixtures
        finally:
            manager.close()


@contextmanager
def preset_guard(manager):
    """Preset planning never starts work, reconciles jobs or reads project code."""
    with no_provider_calls(), ExitStack() as stack:
        for name in ["history", "refresh", "admission", "view", "export", "verified_artifact", "request_hold",
                     "owns_active", "workspace_receipt", "bundle_workspace_view", "bundle_workspaces",
                     "snapshot_recheck_view", "snapshot_rechecks", "snapshot_workspace_view", "snapshot_workspaces",
                     "project_readiness", "readiness_admission", "_snapshot_editor_admission", "current_project", "start"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("preset reached " + name)))
        for name in ["workbench.subprocess.Popen", "workbench.subprocess.run", "workbench.process_stamp",
                     "agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.git",
                     "workbench.readiness_presence"]:
            stack.enter_context(patch(name, side_effect=AssertionError("preset executed or probed " + name)))
        import workbench
        sources = [project["source"] for project in manager.projects.values()]
        for name in ["read_file", "readiness_read_file"]:
            original = getattr(workbench, name)
            def checked(root, relative, *args, _original=original, **kwargs):
                candidate = Path(root)
                if any(candidate == source or source in candidate.parents for source in sources):
                    raise AssertionError("preset read project source")
                return _original(root, relative, *args, **kwargs)
            stack.enter_context(patch.object(workbench, name, side_effect=checked))
        yield


def list_request(fixture):
    return {"project_id": fixture["project_id"]}


def save_request(listed, name="Small refactor", goal="Refactor the selected code while preserving behavior."):
    return {"project_id": listed["project_id"], "name": name, "goal": goal,
            "binding_sha256": listed["binding_sha256"], "history_sha256": listed["history_sha256"]}


def load_request(listed, row=None):
    row = listed["presets"][0] if row is None else row
    return {"project_id": listed["project_id"], "preset_id": row["id"], "record_sha256": row["record_sha256"],
            "binding_sha256": listed["binding_sha256"], "history_sha256": listed["history_sha256"]}


def preset_path(manager, project_id, preset_id):
    return manager.data / "task-presets" / project_id / (preset_id + ".json")


def save_one(manager, fixture, name="Small refactor", goal="Refactor the selected code while preserving behavior."):
    listed = manager.task_preset_list(list_request(fixture))
    saved = manager.task_preset_save(save_request(listed, name, goal))
    return manager.task_preset_list(list_request(fixture)), saved


def close_and_reload(manager, jdk=None):
    config, data = manager.config_path, manager.data
    manager.close()
    return Manager(config, data, jdk)


class TaskPresetIntegrationTests(unittest.TestCase):
    def refusal(self, root, operation, request, code=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(request)
        self.assertRegex(str(caught.exception), r"^TASK_PRESET_[A-Z_]{1,48}$")
        if code is not None:
            self.assertEqual(str(caught.exception), code)
        self.assertNotIn(str(root), str(caught.exception))
        self.assertEqual(before, private_hashes(root))

    def test_python_java_save_list_load_are_goal_only_and_preserve_all_other_bytes(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            for language, fixture in fixtures.items():
                before = private_hashes(root)
                directory = manager.data / "task-presets" / fixture["project_id"]
                self.assertFalse(directory.exists())
                listed = manager.task_preset_list(list_request(fixture))
                self.assertEqual(listed["presets"], [])
                self.assertFalse(directory.exists())
                self.assertEqual(before, private_hashes(root))
                goal = "Improve the selected " + language + " error handling without expanding scope."
                saved = manager.task_preset_save(save_request(listed, "Error handling", goal))
                row = saved["preset"]
                path = preset_path(manager, fixture["project_id"], row["id"])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                after = private_hashes(root)
                relative = str(path.relative_to(root))
                self.assertEqual(before, {name: value for name, value in after.items() if name != relative})
                record = json.loads(path.read_bytes())
                self.assertEqual(record["goal"], goal)
                listed = manager.task_preset_list(list_request(fixture))
                self.assertEqual(len(listed["presets"]), 1)
                self.assertNotIn("goal", listed["presets"][0])
                self.assertIs(listed["presets"][0]["compatible"], True)
                loaded = manager.task_preset_load(load_request(listed))
                self.assertEqual(loaded["goal"], goal)
                self.assertEqual(loaded["record_sha256"], sha(path.read_bytes()))
                self.assertEqual(loaded["history_sha256"], listed["history_sha256"])
                self.assertNotIn(str(root), json.dumps(loaded))
                self.assertEqual(after, private_hashes(root))

    def test_unicode_name_normalization_goal_bytes_and_private_text_remain_exact(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            goal = "Keep literal text café Ω 終.\r\nNo automatic run.\n$(invented-text-only)"
            listed, saved = save_one(manager, fixtures["python"], "Cafe\u0301 Ω", goal)
            loaded = manager.task_preset_load(load_request(listed))
            self.assertEqual(loaded["name"], "Café Ω")
            self.assertEqual(loaded["goal"], goal)
            self.assertNotIn("goal", json.dumps(listed["presets"]))
            self.assertEqual(saved["preset"]["id"], loaded["preset_id"])

    def test_duplicate_names_are_casefold_nfc_and_isolated_by_project(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            listed, _ = save_one(manager, fixtures["python"], "Café STRASSE")
            self.refusal(root, manager.task_preset_save, save_request(listed, "Cafe\u0301 Straße"))
            java = manager.task_preset_list(list_request(fixtures["java"]))
            saved = manager.task_preset_save(save_request(java, "Café STRASSE"))
            self.assertEqual(saved["project_id"], fixtures["java"]["project_id"])

    def test_cross_project_records_and_identifiers_do_not_disclose_goals(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            listed, _ = save_one(manager, fixtures["python"], "Private task", "Invented private Python preset sentinel")
            row = listed["presets"][0]
            java = manager.task_preset_list(list_request(fixtures["java"]))
            self.assertEqual(java["presets"], [])
            self.assertNotIn("sentinel", json.dumps(java))
            request = {**load_request(listed), "project_id": fixtures["java"]["project_id"],
                       "binding_sha256": java["binding_sha256"], "history_sha256": java["history_sha256"]}
            self.refusal(root, manager.task_preset_load, request)
            directory = manager.data / "task-presets" / fixtures["java"]["project_id"]
            directory.mkdir(mode=0o700, exist_ok=True)
            write_new(directory / (row["id"] + ".json"), preset_path(manager, fixtures["python"]["project_id"], row["id"]).read_bytes())
            self.refusal(root, manager.task_preset_list, list_request(fixtures["java"]))

    def test_source_content_is_not_read_or_changed_by_any_preset_action(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            # The task intentionally still pins earlier bytes. Presets are not Run.
            target = fixture["source"] / fixture["editable"]
            target.write_bytes(target.read_bytes() + b"# invented unapproved source change\n")
            listed, _ = save_one(manager, fixture)
            before = private_hashes(root)
            loaded = manager.task_preset_load(load_request(listed))
            self.assertEqual(loaded["project_id"], fixture["project_id"])
            self.assertEqual(before, private_hashes(root))

    def test_stale_history_and_record_hashes_refuse_save_or_load_without_writes(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            old = manager.task_preset_list(list_request(fixture))
            listed, _ = save_one(manager, fixture)
            self.refusal(root, manager.task_preset_save, save_request(old, "Another task"))
            for key in ["record_sha256", "binding_sha256", "history_sha256"]:
                self.refusal(root, manager.task_preset_load, {**load_request(listed), key: "0" * 64})
            manager.task_preset_save(save_request(listed, "Another task"))
            self.refusal(root, manager.task_preset_load, load_request(listed))

    def test_exact_fields_ids_names_goals_and_pins_are_bounded(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            listed, _ = save_one(manager, fixture)
            for request in [{}, {**list_request(fixture), "extra": 1}, {"project_id": "../outside"},
                            {"project_id": None}, {"project_id": "unknown_project"}]:
                self.refusal(root, manager.task_preset_list, request)
            for name in ["", " ", " padded", "padded ", "x\ny", "x\x00y", "x\u2028y", "x\u200by", "Ω" * 81, True]:
                self.refusal(root, manager.task_preset_save, save_request(listed, name))
            for goal in ["", " \n", "x\x00y", "\ud800", "x" * 2001, None, True]:
                self.refusal(root, manager.task_preset_save, save_request(listed, "Other task", goal))
            for request in [{**save_request(listed), "extra": 1}, {**load_request(listed), "extra": 1},
                            {**load_request(listed), "preset_id": "../outside"}, {**load_request(listed), "preset_id": True}]:
                self.refusal(root, manager.task_preset_save if "goal" in request else manager.task_preset_load, request)

    def test_changed_loaded_config_or_task_bytes_refuse_all_actions(self):
        for kind in ["config", "task"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                target = manager.config_path if kind == "config" else fixture["task"]
                target.write_bytes(target.read_bytes() + b" \n")
                self.refusal(root, manager.task_preset_list, list_request(fixture))
                self.refusal(root, manager.task_preset_save, save_request(listed, "Other task"))
                self.refusal(root, manager.task_preset_load, load_request(listed))

    def test_restart_preserves_records_and_requires_explicit_list_and_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manager, fixtures = build_presets_manager(root)
            try:
                with preset_guard(manager):
                    listed, _ = save_one(manager, fixtures["python"], "Restart task", "Keep this exact invented goal after restart.")
                before = private_hashes(root)
                manager = close_and_reload(manager)
                with preset_guard(manager):
                    refreshed = manager.task_preset_list(list_request(fixtures["python"]))
                    self.assertEqual(refreshed, listed)
                    loaded = manager.task_preset_load(load_request(refreshed))
                    self.assertEqual(loaded["goal"], "Keep this exact invented goal after restart.")
                self.assertEqual(before, private_hashes(root))
            finally:
                manager.close()

    def test_approved_hash_and_default_goal_refresh_keeps_profile_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manager, fixtures = build_presets_manager(root)
            fixture = fixtures["python"]
            try:
                with preset_guard(manager):
                    listed, _ = save_one(manager, fixture)
                task = json.loads(fixture["task"].read_bytes())
                target = fixture["source"] / fixture["editable"]
                target.write_bytes(target.read_bytes() + b"# invented approved refresh\n")
                task["files"][fixture["editable"]] = sha(target.read_bytes())
                task["goal"] = "A changed default goal in an independently approved task."
                fixture["task"].write_bytes(canonical(task))
                manager = close_and_reload(manager)
                before = private_hashes(root)
                with preset_guard(manager):
                    current = manager.task_preset_list(list_request(fixture))
                    self.assertEqual(current["binding_sha256"], listed["binding_sha256"])
                    self.assertTrue(current["presets"][0]["compatible"])
                    loaded = manager.task_preset_load(load_request(current))
                    self.assertEqual(loaded["goal"], "Refactor the selected code while preserving behavior.")
                self.assertEqual(before, private_hashes(root))
            finally:
                manager.close()

    def test_scope_checks_permissions_budgets_and_source_identity_make_presets_stale(self):
        for kind in ["scope", "checks", "editable", "turns", "timeout", "source"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "fixture"
                manager, fixtures = build_presets_manager(root)
                fixture = fixtures["python"]
                try:
                    with preset_guard(manager):
                        listed, _ = save_one(manager, fixture)
                    task = json.loads(fixture["task"].read_bytes())
                    if kind == "scope":
                        task["files"]["helper.py"] = sha(b"# invented helper\n")
                        write_new(fixture["source"] / "helper.py", b"# invented helper\n")
                    elif kind == "checks": task["checks"]["renamed_unit"] = task["checks"].pop("unit")
                    elif kind == "editable": task["editable"].append("constants.py")
                    elif kind == "turns": task["max_turns"] -= 1
                    elif kind == "timeout": task["request_seconds"] += 1
                    else:
                        source = root / "other-approved-source"
                        source.mkdir(mode=0o700)
                        for name, raw in fixture["files"].items(): write_new(source / name, raw)
                        config = json.loads(manager.config_path.read_bytes())
                        next(row for row in config["projects"] if row["id"] == fixture["project_id"])["source"] = str(source)
                        manager.config_path.write_bytes(canonical(config))
                    fixture["task"].write_bytes(canonical(task))
                    manager = close_and_reload(manager)
                    with preset_guard(manager):
                        current = manager.task_preset_list(list_request(fixture))
                        self.assertNotEqual(current["binding_sha256"], listed["binding_sha256"])
                        self.assertFalse(current["presets"][0]["compatible"])
                        self.refusal(root, manager.task_preset_load, load_request(current))
                        self.refusal(root, manager.task_preset_save, save_request(current))
                finally:
                    manager.close()

    def test_unrelated_hold_owned_workers_and_saved_jobs_are_not_read_or_reconciled(self):
        with preset_fixture() as (root, manager, fixtures):
            hold = manager.data / "state/hold.json"
            raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented unrelated preset planning hold", "turn": 1})
            write_new(hold, raw)
            write_new(manager.data / "jobs" / ("a" * 16 + ".json"), canonical({"id": "a" * 16, "state": "RUNNING"}))
            child = Mock(); child.poll.side_effect = AssertionError("preset polled worker")
            manager.children["a" * 16] = (child, Mock())
            try:
                with preset_guard(manager):
                    listed, saved = save_one(manager, fixtures["python"], "Held planning", "Invented private planning without execution.")
                    before = private_hashes(root)
                    loaded = manager.task_preset_load(load_request(listed))
                    self.assertEqual(loaded["preset_id"], saved["preset"]["id"])
                    self.assertEqual(before, private_hashes(root))
                self.assertEqual(hold.read_bytes(), raw)
                child.poll.assert_not_called()
            finally:
                manager.children.clear()

    def test_partial_malformed_extra_and_wrong_project_records_refuse_without_repair(self):
        for kind in ["partial", "extra", "foreign", "pending"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                path = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
                record = json.loads(path.read_bytes())
                if kind == "partial": path.write_bytes(b'{"version":')
                elif kind == "extra": record["unexpected"] = "invented"; path.write_bytes(canonical(record))
                elif kind == "foreign": record["project_id"] = fixtures["java"]["project_id"]; path.write_bytes(canonical(record))
                else: write_new(path.with_suffix(".next"), b"invented unfinished write")
                self.refusal(root, manager.task_preset_list, list_request(fixture))
                self.refusal(root, manager.task_preset_save, save_request(listed, "Other task"))
                self.refusal(root, manager.task_preset_load, load_request(listed))

    def test_record_symlink_hardlink_and_ancestor_symlink_refuse(self):
        for kind in ["symlink", "hardlink", "ancestor"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                path = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
                raw = path.read_bytes()
                if kind == "hardlink": os.link(path, root / "invented-record-link")
                elif kind == "symlink":
                    external = root / "invented-record-copy"; write_new(external, raw); path.unlink(); path.symlink_to(external)
                else:
                    directory = path.parent; moved = directory.with_name("invented-original-directory")
                    directory.rename(moved); directory.symlink_to(moved, target_is_directory=True)
                self.refusal(root, manager.task_preset_list, list_request(fixture))
                self.refusal(root, manager.task_preset_load, load_request(listed))

    def test_count_limit_and_maximum_goal_preserve_existing_records(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            listed, _ = save_one(manager, fixture, "Task zero")
            first = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
            template = json.loads(first.read_bytes())
            first.write_bytes(first.read_bytes() + b" " * (32768 - first.stat().st_size))
            for number in range(1, 63):
                record = {**template, "id": format(number, "016x"), "name": "Task " + str(number), "name_key": "task " + str(number)}
                raw = canonical(record)
                write_new(first.parent / (record["id"] + ".json"), raw + b" " * (32768 - len(raw)))
            current = manager.task_preset_list(list_request(fixture))
            self.assertEqual(len(current["presets"]), 63)
            saved = manager.task_preset_save(save_request(current, "Ω" * 80, "🧪" * 2000))
            self.assertEqual(saved["project_id"], fixture["project_id"])
            full = manager.task_preset_list(list_request(fixture))
            self.assertEqual((full["limit"], len(full["presets"])), (64, 64))
            self.assertLessEqual(len(canonical(full)), 65536)
            self.refusal(root, manager.task_preset_save, save_request(full, "One too many"))

    def test_oversized_record_and_directory_entry_bound_refuse_without_repairs(self):
        for kind in ["record", "entries"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                path = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
                if kind == "record": path.write_bytes(path.read_bytes() + b" " * 32768)
                else:
                    for number in range(65): write_new(path.parent / (format(number, "016x") + ".json"), b"{}")
                self.refusal(root, manager.task_preset_list, list_request(fixture))

    def test_record_collision_does_not_overwrite_existing_preset(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            listed, saved = save_one(manager, fixtures["python"])
            identifier = saved["preset"]["id"]
            before = private_hashes(root)
            with patch("workbench.secrets.token_hex", return_value=identifier):
                with self.assertRaises(Refused): manager.task_preset_save(save_request(listed, "Collision task"))
            after = private_hashes(root)
            self.assertEqual({name: value for name, value in after.items() if name in before}, before)

    def test_partial_save_failure_is_retained_and_blocks_later_actions(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            listed, _ = save_one(manager, fixture)
            original = manager._task_preset_write
            def fail(fd, name, raw):
                original(fd, name, b'{"version":')
                raise OSError("invented interrupted metadata write")
            before = private_hashes(root)
            with patch.object(manager, "_task_preset_write", side_effect=fail):
                with self.assertRaises(Refused): manager.task_preset_save(save_request(listed, "Retained partial task"))
            after = private_hashes(root)
            self.assertEqual({name: value for name, value in after.items() if name in before}, before)
            self.assertEqual(len(set(after) - set(before)), 1)
            self.refusal(root, manager.task_preset_list, list_request(fixture))
            self.refusal(root, manager.task_preset_load, load_request(listed))

    def test_unsafe_record_project_and_store_modes_refuse_without_repair(self):
        for kind in ["record", "project", "store"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                path = preset_path(manager, fixture["project_id"], listed["presets"][0]["id"])
                target = path if kind == "record" else path.parent if kind == "project" else path.parent.parent
                unsafe_mode = 0o640 if kind == "record" else 0o750
                target.chmod(unsafe_mode)
                self.refusal(root, manager.task_preset_list, list_request(fixture))
                self.refusal(root, manager.task_preset_save, save_request(listed, "Other task"))
                self.refusal(root, manager.task_preset_load, load_request(listed))
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), unsafe_mode)

    def test_config_and_task_changes_after_staging_leave_retained_unpublished_record(self):
        for kind in ["config", "task"]:
            with self.subTest(kind=kind), preset_fixture() as (root, manager, fixtures), preset_guard(manager):
                fixture = fixtures["python"]
                listed, _ = save_one(manager, fixture)
                target = manager.config_path if kind == "config" else fixture["task"]
                original = manager._task_preset_write
                def drift(fd, name, raw):
                    original(fd, name, raw)
                    target.write_bytes(target.read_bytes() + b" \n")
                before = private_hashes(root)
                with patch.object(manager, "_task_preset_write", side_effect=drift):
                    with self.assertRaisesRegex(Refused, "^TASK_PRESET_SAVE_FAILED$"):
                        manager.task_preset_save(save_request(listed, "Retained drift task"))
                after = private_hashes(root)
                changed = {name for name in before if before[name] != after.get(name)}
                self.assertEqual(changed, {target.relative_to(root).as_posix()})
                added = set(after) - set(before)
                self.assertEqual(len(added), 1)
                self.assertTrue(next(iter(added)).endswith(".json.next"))
                self.refusal(root, manager.task_preset_list, list_request(fixture))
                self.refusal(root, manager.task_preset_load, load_request(listed))

    def test_post_publication_failure_preserves_record_and_uncertain_marker(self):
        with preset_fixture() as (root, manager, fixtures), preset_guard(manager):
            fixture = fixtures["python"]
            listed, _ = save_one(manager, fixture)
            original = os.fsync
            def fail_directory_sync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("invented directory-sync failure after publication")
                original(fd)
            before = private_hashes(root)
            with patch("workbench.os.fsync", side_effect=fail_directory_sync):
                with self.assertRaisesRegex(Refused, "^TASK_PRESET_SAVE_UNCERTAIN$"):
                    manager.task_preset_save(save_request(listed, "Retained uncertain task"))
            after = private_hashes(root)
            self.assertEqual({name: value for name, value in after.items() if name in before}, before)
            added = set(after) - set(before)
            self.assertEqual(len(added), 2)
            self.assertEqual({Path(name).suffix for name in added}, {".json", ".uncertain"})
            self.refusal(root, manager.task_preset_list, list_request(fixture))
            self.refusal(root, manager.task_preset_save, save_request(listed, "Other task"))
            self.refusal(root, manager.task_preset_load, load_request(listed))


@contextmanager
def preset_http_fixture():
    with preset_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-preset-token", "http://127.0.0.1:8765")
        def request(path, value, headers=None, raw=None):
            raw = canonical(value) if raw is None else raw
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-preset-token",
                "Origin": "http://127.0.0.1:8765", "Content-Type": "application/json", "Content-Length": str(len(raw))}
            duplicates = headers if isinstance(headers, list) else []
            if isinstance(headers, dict): supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "POST", path
            handler.request_version, handler.requestline = "HTTP/1.1", "POST " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in list(supplied.items()) + duplicates: handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
            handler.do_POST()
            head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(body)
        yield root, manager, fixtures, request


class TaskPresetHTTPTests(unittest.TestCase):
    def test_explicit_list_save_load_roundtrip_and_private_goal_omission(self):
        with preset_http_fixture() as (root, manager, fixtures, request), preset_guard(manager):
            fixture = fixtures["python"]
            before = private_hashes(root)
            code, listed = request("/api/task-preset-list", list_request(fixture))
            self.assertEqual(code, 200)
            self.assertEqual(before, private_hashes(root))
            code, saved = request("/api/task-preset-save", save_request(listed, "HTTP task", "Invented HTTP private goal."))
            self.assertEqual(code, 200)
            code, listed = request("/api/task-preset-list", list_request(fixture))
            self.assertEqual(code, 200)
            self.assertNotIn("Invented HTTP private goal", json.dumps(listed))
            before = private_hashes(root)
            code, loaded = request("/api/task-preset-load", load_request(listed))
            self.assertEqual((code, loaded["goal"]), (200, "Invented HTTP private goal."))
            self.assertEqual(loaded["preset_id"], saved["preset"]["id"])
            self.assertEqual(before, private_hashes(root))

    def test_exact_framing_authentication_and_origin_precede_each_action(self):
        with preset_http_fixture() as (root, manager, fixtures, request):
            for path, method in [("/api/task-preset-list", "task_preset_list"),
                                 ("/api/task-preset-save", "task_preset_save"),
                                 ("/api/task-preset-load", "task_preset_load")]:
                with patch.object(manager, method, side_effect=AssertionError("malformed request reached preset action")) as invoke:
                    value = list_request(fixtures["python"])
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                        {"Content-Length": "32769"}, {"Content-Length": "999"}, {"Content-Type": "application/zip"},
                        [("Content-Length", str(len(canonical(value))))], [("Content-Type", "application/json")]]:
                        before = private_hashes(root)
                        code, result = request(path, value, headers)
                        self.assertEqual(code, 409)
                        self.assertRegex(result["error"], r"^TASK_PRESET_[A-Z_]+$")
                        self.assertEqual(before, private_hashes(root))
                    for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"),
                        ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"),
                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"), ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        code, result = request(path, value, headers)
                        self.assertEqual((code, result["error"]), (409, error))
                    invoke.assert_not_called()

    def test_duplicate_keys_invalid_unicode_unknown_routes_and_output_caps_refuse(self):
        with preset_http_fixture() as (root, manager, fixtures, request):
            for path, raw in [("/api/task-preset-list", b'{"project_id":"x","project_id":"y"}'),
                              ("/api/task-preset-save", b"\xff"), ("/api/task-preset-unknown", b"{}")]:
                before = private_hashes(root)
                code, result = request(path, {}, raw=raw)
                self.assertEqual(code, 409)
                self.assertRegex(result["error"], r"^TASK_PRESET_[A-Z_]+$")
                self.assertEqual(before, private_hashes(root))
            for path, method in [("/api/task-preset-list", "task_preset_list"),
                                 ("/api/task-preset-save", "task_preset_save"),
                                 ("/api/task-preset-load", "task_preset_load")]:
                with patch.object(manager, method, return_value={"invented": "x" * 65536}):
                    code, result = request(path, {})
                    self.assertEqual((code, result["error"]), (409, "TASK_PRESET_OUTPUT_LIMIT"))


if __name__ == "__main__":
    unittest.main()
