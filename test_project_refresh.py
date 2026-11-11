"""Offline refresh transactions over invented, explicitly selected projects."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_workbench import decision, manager_fixture
from workbench import Manager, init_demo, make_handler


def disk_snapshot(root):
    """Observe fixture bytes, including old runs; never follow selected symlinks."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def change_python(manager):
    source = manager.projects["arithmetic"]["source"]
    path = source / "calculator.py"
    raw = path.read_bytes().replace(b"return a - b", b"return a + b")
    path.write_bytes(raw)
    return raw


def preview(manager, goal=None, project="arithmetic"):
    if goal is None:
        goal = manager.projects[project]["definition"]["goal"]
    return manager.project_refresh_preview({"project": project, "goal": goal})


def install_java(root, manager):
    """Declare Java text without validating or executing any Java installation."""
    source = root / "invented-java"
    (source / "selection").mkdir(parents=True)
    (source / "selection/Counter.java").write_bytes(
        b"package selection; class Counter { static int next(int n) { return n - 1; } }\n"
    )
    (source / "selection/CounterTest.java").write_bytes(
        b"package selection; class CounterTest { public static void main(String[] args) {} }\n"
    )
    manager.jdk_home = root / "fictional-unexecuted-jdk"
    request = {
        "id": "counter", "name": "Invented Java counter", "source": str(source),
        "language": "java", "files": ["selection/Counter.java", "selection/CounterTest.java"],
        "editable": ["selection/Counter.java"], "check": "selection.CounterTest",
        "goal": "Correct the selected counter expression.",
    }
    draft = manager.project_preview(request)
    manager.project_save({"draft": draft["draft"]})
    return source


class RefreshTests(unittest.TestCase):
    def assert_refused_without_disk_changes(self, root, code, operation, request):
        before = disk_snapshot(root)
        with self.assertRaisesRegex(Refused, "^" + code + "$"):
            operation(request)
        self.assertEqual(before, disk_snapshot(root))

    def test_python_preview_is_read_only_and_reports_only_declared_files(self):
        with manager_fixture() as (root, manager, _):
            project = manager.projects["arithmetic"]
            original = copy.deepcopy(project["definition"])
            changed = change_python(manager)
            (project["source"] / "unselected.txt").write_text("invented unselected sentinel")
            before = disk_snapshot(root)
            candidate = preview(manager)
            self.assertEqual(before, disk_snapshot(root))
            self.assertEqual(candidate["project"], "arithmetic")
            self.assertEqual(candidate["name"], "Arithmetic demo")
            self.assertEqual(candidate["parent_task_sha256"], sha(project["task"].read_bytes()))
            rows = {row["path"]: row for row in candidate["files"]}
            self.assertEqual(set(rows), set(original["files"]))
            self.assertEqual(rows["calculator.py"]["old_sha256"], original["files"]["calculator.py"])
            self.assertEqual(rows["calculator.py"]["sha256"], sha(changed))
            self.assertEqual(rows["calculator.py"]["bytes"], len(changed))
            self.assertTrue(rows["calculator.py"]["changed"])
            self.assertTrue(rows["calculator.py"]["editable"])
            self.assertFalse(rows["test_calculator.py"]["changed"])
            self.assertFalse(rows["test_calculator.py"]["editable"])
            self.assertEqual(candidate["files_changed"], 1)
            self.assertFalse(candidate["goal_changed"])
            self.assertEqual(candidate["total_bytes"], sum(row["bytes"] for row in rows.values()))
            self.assertEqual(candidate["checks"], original["checks"])
            self.assertEqual(candidate["max_turns"], original["max_turns"])
            self.assertEqual(candidate["request_seconds"], original["request_seconds"])
            self.assertNotIn(str(project["source"]), json.dumps(candidate))
            self.assertNotIn("invented unselected sentinel", json.dumps(candidate))
            self.assertEqual(project["definition"], original)

    def test_goal_only_save_preserves_original_task_and_protected_scope(self):
        with manager_fixture() as (_, manager, _):
            project = manager.projects["arithmetic"]
            old_path = project["task"]
            old_raw = old_path.read_bytes()
            original = copy.deepcopy(project["definition"])
            goal = "Inspect the invented arithmetic boundary cases."
            candidate = preview(manager, goal)
            self.assertEqual(candidate["files_changed"], 0)
            self.assertTrue(candidate["goal_changed"])
            saved = manager.project_refresh_save({"draft": candidate["draft"]})
            updated = manager.projects["arithmetic"]
            expected = {**original, "goal": goal}
            self.assertEqual(updated["definition"], expected)
            self.assertEqual(saved["id"], "arithmetic")
            self.assertEqual(saved["name"], project["name"])
            self.assertRegex(saved["revision"], r"^[0-9a-f]{16}$")
            self.assertEqual(saved["task_sha256"], candidate["task_sha256"])
            self.assertEqual(saved["task_sha256"], sha(canonical(expected)))
            self.assertNotEqual(updated["task"], old_path)
            self.assertEqual(old_path.read_bytes(), old_raw)
            self.assertEqual(updated["task"].read_bytes(), canonical(expected))
            config = json.loads(manager.config_path.read_bytes())
            row = next(row for row in config["projects"] if row["id"] == "arithmetic")
            self.assertEqual(Path(row["task"]), updated["task"])
            self.assertEqual(manager.history(), [])
            history = manager.project_revisions("arithmetic")
            self.assertEqual(history["task_sha256"], saved["task_sha256"])
            self.assertEqual(history["limit"], 20)
            self.assertFalse(history["truncated"])
            self.assertEqual(len(history["revisions"]), 1)
            revision = history["revisions"][0]
            self.assertEqual(revision["id"], saved["revision"])
            self.assertEqual(revision["parent_task_sha256"], sha(old_raw))
            self.assertEqual(revision["task_sha256"], saved["task_sha256"])
            self.assertEqual(revision["files_changed"], 0)
            self.assertTrue(revision["goal_changed"])
            self.assertIs(revision["current"], True)
            self.assertIs(type(revision["created"]), int)
            self.assertNotIn(str(updated["task"]), json.dumps(history))

    def test_java_refresh_keeps_sources_main_class_and_protection(self):
        with manager_fixture() as (root, manager, _):
            source = install_java(root, manager)
            old = copy.deepcopy(manager.projects["counter"]["definition"])
            for name in old["files"]:
                path = source / name
                path.write_bytes(path.read_bytes() + b"// invented owner edit\n")
            candidate = preview(manager, project="counter")
            self.assertEqual(candidate["files_changed"], 2)
            rows = {row["path"]: row for row in candidate["files"]}
            self.assertTrue(rows["selection/Counter.java"]["editable"])
            self.assertFalse(rows["selection/CounterTest.java"]["editable"])
            manager.project_refresh_save({"draft": candidate["draft"]})
            saved = manager.projects["counter"]["definition"]
            for key in ["format", "goal", "editable", "checks", "max_turns", "request_seconds"]:
                self.assertEqual(saved[key], old[key])
            self.assertEqual(set(saved["files"]), set(old["files"]))
            self.assertEqual(saved["checks"]["unit"]["main_class"], "selection.CounterTest")
            self.assertEqual(saved["files"], {name: sha((source / name).read_bytes()) for name in old["files"]})

    def test_manager_restart_loads_new_revision_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = init_demo(root / "workspace", "fictional-model")
            config, data = Path(paths["config"]), Path(paths["data_dir"])
            first = Manager(config, data)
            try:
                change_python(first)
                candidate = preview(first)
                saved = first.project_refresh_save({"draft": candidate["draft"]})
                task_path = first.projects["arithmetic"]["task"]
                definition = copy.deepcopy(first.projects["arithmetic"]["definition"])
            finally:
                first.close()
            restarted = Manager(config, data)
            try:
                self.assertEqual(restarted.projects["arithmetic"]["task"], task_path)
                self.assertEqual(restarted.projects["arithmetic"]["definition"], definition)
                self.assertEqual(restarted.project_revisions("arithmetic")["revisions"][0]["id"], saved["revision"])
            finally:
                restarted.close()

    def test_new_run_uses_refreshed_snapshot_without_starting_a_worker(self):
        with manager_fixture() as (_, manager, _):
            changed = change_python(manager)
            candidate = preview(manager, "Inspect the refreshed invented source.")
            manager.project_refresh_save({"draft": candidate["draft"]})
            child = Mock(); child.pid = 99999999; child.poll.return_value = None
            with patch("workbench.subprocess.Popen", return_value=child) as spawn, patch("workbench.process_stamp", return_value="fictional"):
                started = manager.start({"project": "arithmetic", "model": "fictional-model", "goal": candidate["goal"]})
            try:
                run_task = json.loads((manager.data / "tasks" / (started["id"] + ".json")).read_bytes())
                self.assertEqual(run_task, manager.projects["arithmetic"]["definition"])
                self.assertEqual(run_task["files"]["calculator.py"], sha(changed))
                command = spawn.call_args.args[0]
                self.assertEqual(Path(command[command.index("--task") + 1]), manager.data / "tasks" / (started["id"] + ".json"))
            finally:
                _, log = manager.children.pop(started["id"])
                log.close()

    def test_second_revision_retains_previous_tasks_and_parent_link(self):
        with manager_fixture() as (_, manager, _):
            first = preview(manager, "First invented revised goal.")
            saved_first = manager.project_refresh_save({"draft": first["draft"]})
            first_path = manager.projects["arithmetic"]["task"]
            first_raw = first_path.read_bytes()
            second = preview(manager, "Second invented revised goal.")
            saved_second = manager.project_refresh_save({"draft": second["draft"]})
            self.assertNotEqual(saved_first["revision"], saved_second["revision"])
            self.assertEqual(first_path.read_bytes(), first_raw)
            rows = manager.project_revisions("arithmetic")["revisions"]
            self.assertEqual(len(rows), 2)
            current = next(row for row in rows if row["current"])
            self.assertEqual(current["id"], saved_second["revision"])
            self.assertEqual(current["parent_task_sha256"], saved_first["task_sha256"])
            self.assertFalse(next(row for row in rows if row["id"] == saved_first["revision"])["current"])

    def test_history_limits_display_without_dropping_current_revision(self):
        with manager_fixture() as (_, manager, _):
            first_path, first_raw = None, None
            for number in range(22):
                candidate = preview(manager, "Invented goal revision " + str(number))
                saved = manager.project_refresh_save({"draft": candidate["draft"]})
                if number == 0:
                    first_path = manager.projects["arithmetic"]["task"]
                    first_raw = first_path.read_bytes()
            history = manager.project_revisions("arithmetic")
            self.assertEqual(len(history["revisions"]), 20)
            self.assertEqual(history["limit"], 20)
            self.assertTrue(history["truncated"])
            self.assertEqual([row["id"] for row in history["revisions"] if row["current"]], [saved["revision"]])
            self.assertEqual(first_path.read_bytes(), first_raw)

    def test_source_change_between_preview_and_save_refused(self):
        with manager_fixture() as (root, manager, _):
            change_python(manager)
            candidate = preview(manager)
            path = manager.projects["arithmetic"]["source"] / "calculator.py"
            path.write_bytes(path.read_bytes() + b"# later invented change\n")
            self.assert_refused_without_disk_changes(root, "REFRESH_SOURCE_CHANGED", manager.project_refresh_save, {"draft": candidate["draft"]})
            self.assertEqual(manager.project_revisions("arithmetic")["revisions"], [])

    def test_source_reverting_to_original_after_preview_is_still_stale(self):
        with manager_fixture() as (root, manager, _):
            path = manager.projects["arithmetic"]["source"] / "calculator.py"
            original = path.read_bytes()
            change_python(manager)
            candidate = preview(manager)
            path.write_bytes(original)
            self.assert_refused_without_disk_changes(root, "REFRESH_SOURCE_CHANGED", manager.project_refresh_save, {"draft": candidate["draft"]})

    def test_saved_revision_invalidates_a_competing_preview(self):
        with manager_fixture() as (root, manager, _):
            first = preview(manager, "First reviewed invented goal.")
            competing = preview(manager, "Competing reviewed invented goal.")
            saved = manager.project_refresh_save({"draft": first["draft"]})
            self.assert_refused_without_disk_changes(root, "CONFIG_CHANGED", manager.project_refresh_save, {"draft": competing["draft"]})
            self.assertEqual(manager.project_revisions("arithmetic")["revisions"][0]["id"], saved["revision"])

    def test_setup_and_refresh_drafts_cannot_cross_save_endpoints(self):
        from test_project_setup import request as setup_request
        with manager_fixture() as (root, manager, _):
            setup = manager.project_preview(setup_request(root))
            refresh = preview(manager, "Invented refreshed goal.")
            self.assert_refused_without_disk_changes(root, "DRAFT_EXPIRED", manager.project_refresh_save, {"draft": setup["draft"]})
            self.assert_refused_without_disk_changes(root, "DRAFT_EXPIRED", manager.project_save, {"draft": refresh["draft"]})

    def test_failed_pointer_write_retains_preparation_without_saved_history(self):
        with manager_fixture() as (_, manager, _):
            candidate = preview(manager, "Invented goal before interrupted commit.")
            old_pointer = manager.projects["arithmetic"]["task"]
            old_config = manager.config_path.read_bytes()
            with patch("workbench.replace_json", side_effect=OSError("invented commit failure")) as commit:
                with self.assertRaisesRegex(OSError, "invented commit failure"):
                    manager.project_refresh_save({"draft": candidate["draft"]})
            commit.assert_called_once()
            self.assertEqual(manager.config_path.read_bytes(), old_config)
            self.assertEqual(manager.projects["arithmetic"]["task"], old_pointer)
            self.assertEqual(manager.project_revisions("arithmetic")["revisions"], [])
            prepared = list((manager.data / "revisions/arithmetic").glob("*/receipt.json"))
            self.assertEqual(len(prepared), 1)
            self.assertEqual(json.loads(prepared[0].read_bytes())["task_sha256"], candidate["task_sha256"])
            self.assertEqual((prepared[0].parent / "task.json").read_bytes(), canonical(manager.drafts[candidate["draft"]]["task"]))

    def test_final_recheck_catches_source_change_after_files_are_prepared(self):
        with manager_fixture() as (_, manager, _):
            candidate = preview(manager, "Invented goal before final recheck.")
            old_config = manager.config_path.read_bytes()
            path = manager.projects["arithmetic"]["source"] / "calculator.py"
            changed = path.read_bytes() + b"# invented change during preparation\n"

            def write_then_change(destination, raw):
                write_new(destination, raw)
                if destination.name == "receipt.json":
                    path.write_bytes(changed)

            with patch("workbench.write_new", side_effect=write_then_change):
                with self.assertRaisesRegex(Refused, "^REFRESH_SOURCE_CHANGED$"):
                    manager.project_refresh_save({"draft": candidate["draft"]})
            self.assertEqual(path.read_bytes(), changed)
            self.assertEqual(manager.config_path.read_bytes(), old_config)
            self.assertEqual(manager.project_revisions("arithmetic")["revisions"], [])
            self.assertEqual(len(list((manager.data / "revisions/arithmetic").glob("*/receipt.json"))), 1)

    def test_no_op_revision_tamper_is_refused_even_with_consistent_hashes(self):
        with manager_fixture() as (root, manager, _):
            first = preview(manager, "First invented revised goal.")
            manager.project_refresh_save({"draft": first["draft"]})
            pending = preview(manager, "Next invented revised goal.")
            folder = manager.projects["arithmetic"]["task"].parent
            task_raw = (folder / "task.json").read_bytes()
            (folder / "parent-task.json").write_bytes(task_raw)
            receipt = json.loads((folder / "receipt.json").read_bytes())
            receipt.update(parent_task_sha256=sha(task_raw), files_changed=0, goal_changed=False)
            (folder / "receipt.json").write_bytes(canonical(receipt))
            before = disk_snapshot(root)
            with self.assertRaisesRegex(Refused, "^REVISION_RECORD_CHANGED$"):
                manager.project_revisions("arithmetic")
            self.assertEqual(before, disk_snapshot(root))
            self.assert_refused_without_disk_changes(root, "REVISION_RECORD_CHANGED", manager.project_refresh_preview, {"project": "arithmetic", "goal": "Another invented goal."})
            self.assert_refused_without_disk_changes(root, "REVISION_RECORD_CHANGED", manager.project_refresh_save, {"draft": pending["draft"]})

    def test_external_config_change_during_final_snapshot_check_is_preserved(self):
        from workbench import refresh_task as actual_refresh
        with manager_fixture() as (_, manager, _):
            candidate = preview(manager, "Invented goal before late configuration edit.")
            old_pointer = manager.projects["arithmetic"]["task"]
            owner_raw = manager.config_raw + b" \n"
            calls = 0

            def refresh_then_change(*args):
                nonlocal calls
                value = actual_refresh(*args)
                calls += 1
                if calls == 2:
                    manager.config_path.write_bytes(owner_raw)
                return value

            with patch("workbench.refresh_task", side_effect=refresh_then_change):
                with self.assertRaisesRegex(Refused, "^CONFIG_CHANGED$"):
                    manager.project_refresh_save({"draft": candidate["draft"]})
            self.assertEqual(calls, 2)
            self.assertEqual(manager.config_path.read_bytes(), owner_raw)
            self.assertEqual(manager.projects["arithmetic"]["task"], old_pointer)

    def test_external_config_change_after_next_file_is_written_is_preserved(self):
        with manager_fixture() as (_, manager, _):
            candidate = preview(manager, "Invented goal before pointer swap.")
            old_pointer = manager.projects["arithmetic"]["task"]
            owner_raw = manager.config_raw + b"\n "
            temporary = manager.config_path.with_name(manager.config_path.name + ".next")

            def write_then_change(destination, raw):
                write_new(destination, raw)
                if destination == temporary:
                    manager.config_path.write_bytes(owner_raw)

            with patch("workbench.write_new", side_effect=write_then_change):
                with self.assertRaisesRegex(Refused, "^CONFIG_CHANGED$"):
                    manager.project_refresh_save({"draft": candidate["draft"]})
            self.assertEqual(manager.config_path.read_bytes(), owner_raw)
            self.assertEqual(manager.projects["arithmetic"]["task"], old_pointer)
            self.assertTrue(temporary.is_file())

    def test_external_task_change_blocks_preview_and_save(self):
        with manager_fixture() as (root, manager, _):
            candidate = preview(manager, "Proposed invented goal.")
            task_path = manager.projects["arithmetic"]["task"]
            changed = json.loads(task_path.read_bytes())
            changed["goal"] = "External invented task edit."
            task_path.write_bytes(canonical(changed))
            self.assert_refused_without_disk_changes(root, "PROJECT_TASK_CHANGED", manager.project_refresh_save, {"draft": candidate["draft"]})
            self.assert_refused_without_disk_changes(root, "PROJECT_TASK_CHANGED", manager.project_refresh_preview, {"project": "arithmetic", "goal": "Another invented goal."})

    def test_external_config_change_is_preserved(self):
        with manager_fixture() as (root, manager, _):
            candidate = preview(manager, "Proposed invented goal.")
            manager.config_path.write_bytes(manager.config_raw + b" \n")
            self.assert_refused_without_disk_changes(root, "CONFIG_CHANGED", manager.project_refresh_save, {"draft": candidate["draft"]})
            self.assert_refused_without_disk_changes(root, "CONFIG_CHANGED", manager.project_refresh_preview, {"project": "arithmetic", "goal": "Another invented goal."})

    def test_request_cannot_expand_scope_or_change_checks_and_limits(self):
        with manager_fixture() as (root, manager, _):
            base = {"project": "arithmetic", "goal": "An invented next goal."}
            for key, value in {"files": ["outside.py"], "editable": ["test_calculator.py"], "source": "/fictional/other", "checks": {}, "max_turns": 16, "request_seconds": 1}.items():
                with self.subTest(field=key):
                    self.assert_refused_without_disk_changes(root, "REFRESH_FIELDS", manager.project_refresh_preview, {**base, key: value})
            candidate = preview(manager, base["goal"])
            self.assert_refused_without_disk_changes(root, "DRAFT_REQUIRED", manager.project_refresh_save, {"draft": candidate["draft"], "goal": "Unreviewed replacement."})

    def test_invalid_goals_and_unknown_projects_refused_without_writes(self):
        with manager_fixture() as (root, manager, _):
            for goal in ["", "x" * 2001, None, True]:
                with self.subTest(goal=type(goal).__name__):
                    self.assert_refused_without_disk_changes(root, "GOAL_LIMIT", manager.project_refresh_preview, {"project": "arithmetic", "goal": goal})
            self.assert_refused_without_disk_changes(root, "PROJECT_UNKNOWN", manager.project_refresh_preview, {"project": "missing", "goal": "Invented goal."})

    def test_no_op_refused_without_any_persistent_change(self):
        with manager_fixture() as (root, manager, _):
            self.assert_refused_without_disk_changes(root, "REFRESH_NO_CHANGES", manager.project_refresh_preview, {"project": "arithmetic", "goal": manager.projects["arithmetic"]["definition"]["goal"]})

    def test_expired_and_reused_drafts_cannot_save_twice(self):
        with manager_fixture() as (root, manager, _):
            with patch("workbench.time.monotonic", return_value=1000):
                expired = preview(manager, "An expiring invented goal.")
            with patch("workbench.time.monotonic", return_value=2000):
                self.assert_refused_without_disk_changes(root, "DRAFT_EXPIRED", manager.project_refresh_save, {"draft": expired["draft"]})
            candidate = preview(manager, "A saved invented goal.")
            manager.project_refresh_save({"draft": candidate["draft"]})
            self.assert_refused_without_disk_changes(root, "DRAFT_EXPIRED", manager.project_refresh_save, {"draft": candidate["draft"]})

    def test_held_admission_blocks_preview_and_save_without_mutation(self):
        with manager_fixture() as (root, manager, _):
            candidate = preview(manager, "An invented next goal.")
            hold = manager.data / "state/hold.json"
            hold.write_bytes(canonical({"state": "fictional unsettled hold"}))
            self.assert_refused_without_disk_changes(root, "UNCERTAIN_REQUEST_HELD", manager.project_refresh_preview, {"project": "arithmetic", "goal": "Another invented goal."})
            self.assert_refused_without_disk_changes(root, "UNCERTAIN_REQUEST_HELD", manager.project_refresh_save, {"draft": candidate["draft"]})

    def test_owned_active_run_blocks_preview_and_save_without_mutation(self):
        with manager_fixture() as (root, manager, run_id):
            candidate = preview(manager, "An invented next goal.")
            write_new(manager.meta_path(run_id), canonical({"id": run_id, "state": "RUNNING", "created": 1}))
            child = Mock(); child.poll.return_value = None
            manager.children[run_id] = (child, Mock())
            try:
                self.assert_refused_without_disk_changes(root, "TASK_ACTIVE_OR_UNRESOLVED", manager.project_refresh_preview, {"project": "arithmetic", "goal": "Another invented goal."})
                self.assert_refused_without_disk_changes(root, "TASK_ACTIVE_OR_UNRESOLVED", manager.project_refresh_save, {"draft": candidate["draft"]})
            finally:
                manager.children.pop(run_id)

    def test_unknown_or_malformed_workspace_receipt_blocks_refresh_without_mutation(self):
        with manager_fixture(seed=True) as (root, manager, run_id):
            candidate = preview(manager, "Invented next goal before workspace inspection.")
            receipt = manager.run_path(run_id) / "git-workspace.json"
            for value in [{"status": "FUTURE_UNKNOWN_STATE"}, [], 42, "bad", {"status": "VERIFIED"}]:
                with self.subTest(receipt=value):
                    receipt.write_bytes(canonical(value))
                    self.assert_refused_without_disk_changes(root, "WORKSPACE_ACTIVE_OR_UNRESOLVED", manager.project_refresh_preview, {"project": "arithmetic", "goal": "Another invented goal."})
                    self.assert_refused_without_disk_changes(root, "WORKSPACE_ACTIVE_OR_UNRESOLVED", manager.project_refresh_save, {"draft": candidate["draft"]})

    def test_refresh_preserves_old_run_and_does_not_revalidate_old_export(self):
        with manager_fixture(seed=True) as (root, manager, run_id):
            manager.review(decision(manager, run_id))
            self.assertTrue(manager.export(run_id))
            old_run = disk_snapshot(manager.run_path(run_id))
            old_task_path = manager.projects["arithmetic"]["task"]
            old_task = old_task_path.read_bytes()
            change_python(manager)
            candidate = preview(manager)
            manager.project_refresh_save({"draft": candidate["draft"]})
            self.assertEqual(old_task_path.read_bytes(), old_task)
            self.assertEqual(disk_snapshot(manager.run_path(run_id)), old_run)
            self.assertEqual(manager.history()[0]["id"], run_id)
            with self.assertRaisesRegex(Refused, "ORIGINAL_SOURCE_CHANGED"):
                manager.export(run_id)
            self.assertEqual(disk_snapshot(manager.run_path(run_id)), old_run)


@contextmanager
def http_fixture():
    """Run the actual request handlers in memory, without binding a socket."""
    with manager_fixture() as (root, manager, _):
        origin = "http://127.0.0.1:8765"
        handler_type = make_handler(manager, "fictional-refresh-token", origin)

        def request(method, path, value=None, headers=None):
            body = canonical(value) if value is not None else b""
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "fictional-refresh-token"}
            if value is not None:
                supplied.update({"Origin": origin, "Content-Type": "application/json", "Content-Length": str(len(body))})
            if headers is not None:
                supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = method, path
            handler.request_version = "HTTP/1.1"
            handler.requestline = method + " " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in supplied.items():
                handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            getattr(handler, "do_" + method)()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(raw)

        yield root, manager, request


class RefreshHTTPTests(unittest.TestCase):
    def test_preview_save_and_history_http_contract(self):
        with http_fixture() as (_, manager, request):
            code, candidate = request("POST", "/api/project-refresh-preview", {"project": "arithmetic", "goal": "Inspect the HTTP fixture."})
            self.assertEqual(code, 200)
            self.assertEqual(candidate["files_changed"], 0)
            code, saved = request("POST", "/api/project-refresh-save", {"draft": candidate["draft"]})
            self.assertEqual(code, 200)
            code, history = request("GET", "/api/project-revisions/arithmetic")
            self.assertEqual(code, 200)
            self.assertEqual(history["task_sha256"], saved["task_sha256"])
            self.assertEqual(history["revisions"][0]["id"], saved["revision"])
            self.assertNotIn(str(manager.data), json.dumps(history))

    def test_refresh_http_requires_session_origin_and_scope_guard(self):
        with http_fixture() as (root, _, request):
            before = disk_snapshot(root)
            code, value = request("GET", "/api/project-revisions/arithmetic", headers={"X-Workbench-Token": ""})
            self.assertEqual((code, value["error"]), (403, "SESSION_REQUIRED"))
            code, value = request("POST", "/api/project-refresh-preview", {"project": "arithmetic", "goal": "Invented goal."}, {"Origin": "https://malicious.invalid"})
            self.assertEqual((code, value["error"]), (409, "ORIGIN_REFUSED"))
            code, value = request("POST", "/api/project-refresh-preview", {"project": "arithmetic", "goal": "Invented goal.", "files": ["outside.py"]})
            self.assertEqual((code, value["error"]), (409, "REFRESH_FIELDS"))
            self.assertEqual(before, disk_snapshot(root))


if __name__ == "__main__":
    unittest.main()
