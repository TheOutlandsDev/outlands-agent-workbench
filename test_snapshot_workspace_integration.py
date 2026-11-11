"""Private snapshot-workspace lifecycle fixtures, guards and in-memory HTTP tests."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_bundle_workspace_integration import create_request, no_provider_calls, private_hashes
from test_snapshot_export_integration import populate_snapshot_exports, snapshot_export_guard
from test_workspace_recheck_integration import passing_checks
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-snapshot-workspace-sentinel"


def populate_snapshot_workspace_projects(manager, root, languages=("python", "java", "mixed")):
    """Seed saved packets with fake checks; never add or remove a target hold."""
    from snapshot_export import prepare
    fixtures = populate_snapshot_exports(manager, root, languages)
    for fixture in fixtures.values():
        raw = prepare(fixture["attempt_dir"])["archive"]
        fixture.update(archive_raw=raw, archive_sha256=sha(raw))
    assert not (manager.data / "state/hold.json").exists()
    return fixtures


@contextmanager
def workspace_fixture(languages=("python",)):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        manager._snapshot_fixture_closed = False
        fixtures = populate_snapshot_workspace_projects(manager, root, languages)
        try:
            yield root, manager, fixtures
        finally:
            for identifier, (_, log) in list(manager.snapshot_workspace_children.items()):
                log.close(); manager.snapshot_workspace_children.pop(identifier)
            if not manager._snapshot_fixture_closed: manager.close()


@contextmanager
def preview_guard(manager):
    with snapshot_export_guard(manager), ExitStack() as stack:
        for name in ["snapshot_workspace_view", "snapshot_workspaces", "snapshot_export_preview", "snapshot_export_download",
                     "snapshot_export_history", "readiness_admission", "comparison_history", "compare"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("snapshot preview reached " + name)))
        stack.enter_context(patch("workbench.readiness_presence", side_effect=AssertionError("prerequisite probe")))
        yield


@contextmanager
def fake_worker(manager, start_error=None):
    child = Mock(); child.pid = 99999999; child.poll.return_value = None
    with no_provider_calls(), patch("workbench.subprocess.run", side_effect=AssertionError("parent executed command")), \
            patch("workbench.subprocess.Popen", side_effect=start_error, return_value=child) as launch:
        try:
            yield child, launch
        finally:
            for identifier, (owned, log) in list(manager.snapshot_workspace_children.items()):
                if owned is child:
                    log.close(); manager.snapshot_workspace_children.pop(identifier)


def workspace_job(manager, identifier):
    return manager.data / "snapshot-workspaces" / identifier


class SnapshotWorkspaceIntegrationTests(unittest.TestCase):
    def preview(self, root, manager, fixture):
        before = private_hashes(root)
        with preview_guard(manager):
            value = manager.snapshot_workspace_preview(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
        self.assertEqual(before, private_hashes(root))
        self.assertIs(value["workspace_ready"], True)
        self.assertEqual(value["comparison"]["status"], "BASELINE_MATCH")
        self.assertEqual(value["comparison"]["reconstruction"]["status"], "VERIFIED")
        self.assertIs(value["comparison"]["task_pins_match"], True)
        self.assertEqual(value["archive_sha256"], fixture["archive_sha256"])
        self.assertEqual(value["config_sha256"], sha(manager.config_raw))
        self.assertEqual(value["task_sha256"], sha(manager.projects[fixture["project_id"]]["task_raw"]))
        self.assertNotIn(str(root), json.dumps(value)); self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))
        self.assertLessEqual(len(canonical(value)), 131072)
        return value

    def refused(self, root, operation, *args, codes=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught: operation(*args)
        reason = str(caught.exception)
        self.assertRegex(reason, r"^[A-Z][A-Z0-9_]{1,64}$")
        if codes: self.assertIn(reason, codes)
        self.assertNotIn(PRIVATE_SENTINEL, reason)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_previews_are_memory_only_without_jdk_or_target_hold(self):
        with workspace_fixture(("python", "java")) as (root, manager, fixtures):
            for language, fixture in fixtures.items():
                value = self.preview(root, manager, fixture)
                self.assertEqual(value["java_required"], language == "java")
                self.assertIs(value["java_available"], False)
                self.assertEqual({row["path"] for row in value["files"]}, set(manager.projects[fixture["project_id"]]["definition"]["files"]))
            self.assertEqual(list((manager.data / "snapshot-workspaces").iterdir()), [])

    def test_create_stages_distinct_pinned_job_and_owns_one_fixed_worker(self):
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
            before = private_hashes(root)
            with fake_worker(manager) as (_, launch):
                value = manager.snapshot_workspace_create(create_request(preview))
                self.assertEqual((value["status"], value["owned_active"]), ("PREPARING", True))
                self.assertEqual(value["format"], "outlands-snapshot-workspace-v1")
                job = workspace_job(manager, value["id"])
                self.assertEqual((job / "snapshot.zip").read_bytes(), fixture["archive_raw"])
                self.assertEqual((job / "task.json").read_bytes(), fixture["task"].read_bytes())
                request = json.loads((job / "request.json").read_bytes())
                self.assertEqual(set(request), {"version", "id", "project_id", "source", "config_path", "config_sha256", "task_path", "task_sha256", "archive_sha256", "preview_sha256"})
                self.assertEqual(request["source"], str(fixture["source"]))
                command = launch.call_args.args[0]
                self.assertTrue(command[2].endswith("/snapshot_workspace.py"))
                self.assertEqual(command[3:], ["--job-dir", str(job)])
                launch.assert_called_once()
                self.refused(root, manager.snapshot_workspace_create, create_request(preview), codes={"SNAPSHOT_WORKSPACE_PREVIEW_REQUIRED"})
                self.assertEqual(len(manager.snapshot_workspaces()["workspaces"]), 1)
            prefix = str(job.relative_to(root)) + "/"
            self.assertEqual(before, {name: value for name, value in private_hashes(root).items() if not name.startswith(prefix)})

    def test_fake_passing_worker_creates_selected_snapshot_worktree_without_old_record_writes(self):
        from snapshot_workspace import build
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
            before = private_hashes(root)
            with fake_worker(manager):
                created = manager.snapshot_workspace_create(create_request(preview))
            job = workspace_job(manager, created["id"])
            with no_provider_calls(): receipt = build(job, checker=passing_checks)
            self.assertEqual(receipt["status"], "VERIFIED")
            self.assertIs(receipt["source_applied"], False)
            self.assertIs(receipt["patch_applied_to_workspace"], True)
            self.assertEqual(receipt["branch"], "outlands/snapshot-" + created["id"])
            destination = Path(receipt["path"])
            task = manager.projects[fixture["project_id"]]["definition"]
            expected = {name: sha((fixture["attempt_dir"] / "snapshot" / name).read_bytes()) for name in task["files"]}
            self.assertEqual(receipt["snapshot"], expected)
            self.assertEqual({name: sha((destination / name).read_bytes()) for name in task["files"]}, expected)
            self.assertEqual(manager.snapshot_workspace_view(created["id"])["owned_active"], False)
            self.assertIsNone(manager.admission())
            prefix = str(job.relative_to(root)) + "/"
            self.assertEqual(before, {name: value for name, value in private_hashes(root).items() if not name.startswith(prefix)})

    def test_expiry_replacement_cross_project_and_invalid_preview_invalidate_drafts(self):
        with workspace_fixture(("python", "java")) as (root, manager, fixtures):
            with patch("workbench.time.monotonic", return_value=1000): old = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (_, launch), patch("workbench.time.monotonic", return_value=1301):
                self.refused(root, manager.snapshot_workspace_create, create_request(old), codes={"SNAPSHOT_WORKSPACE_PREVIEW_EXPIRED"})
                launch.assert_not_called()
            first = self.preview(root, manager, fixtures["python"]); second = self.preview(root, manager, fixtures["java"])
            with fake_worker(manager) as (_, launch):
                self.refused(root, manager.snapshot_workspace_create, create_request(first), codes={"SNAPSHOT_WORKSPACE_PREVIEW_CHANGED"})
                self.refused(root, manager.snapshot_workspace_create, {"preview_id": second["preview_id"], "preview_sha256": first["preview_sha256"]}, codes={"SNAPSHOT_WORKSPACE_PREVIEW_CHANGED"})
                with preview_guard(manager): self.refused(root, manager.snapshot_workspace_preview, fixtures["python"]["project_id"], b"invalid ZIP")
                self.refused(root, manager.snapshot_workspace_create, create_request(second), codes={"SNAPSHOT_WORKSPACE_PREVIEW_REQUIRED"})
                launch.assert_not_called()

    def test_stale_config_task_baseline_and_protected_bytes_refuse_before_job_creation(self):
        for mode in ["config", "task", "baseline", "protected"]:
            with self.subTest(mode=mode), workspace_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
                path = manager.config_path if mode == "config" else fixture["task"] if mode == "task" else fixture["source"] / ("test_arithmetic.py" if mode == "protected" else "arithmetic.py")
                path.write_bytes(path.read_bytes() + b" \n")
                with fake_worker(manager) as (_, launch), ExitStack() as stack:
                    if mode in ["config", "task"]:
                        stack.enter_context(patch("snapshot_workspace.read_selected", side_effect=AssertionError("changed profile read source")))
                    self.refused(root, manager.snapshot_workspace_create, create_request(preview))
                    launch.assert_not_called()
                self.assertEqual(list((manager.data / "snapshot-workspaces").iterdir()), [])

    def test_hold_allows_inspection_but_blocks_create_without_reprepare_or_write(self):
        with workspace_fixture() as (root, manager, fixtures):
            hold = manager.data / "state/hold.json"
            write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": PRIVATE_SENTINEL, "turn": 1}))
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (_, launch), patch("workbench.prepare_snapshot_workspace", side_effect=AssertionError("held execution prepared")):
                self.refused(root, manager.snapshot_workspace_create, create_request(preview), codes={"UNCERTAIN_REQUEST_HELD"})
                launch.assert_not_called()

    def test_java_requires_jdk_before_persisting_job(self):
        with workspace_fixture(("java",)) as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["java"])
            with fake_worker(manager) as (_, launch):
                self.refused(root, manager.snapshot_workspace_create, create_request(preview), codes={"JDK_REQUIRED"})
                launch.assert_not_called()

    def test_tested_mixed_and_mismatched_approved_task_pins_are_not_creation_baselines(self):
        for mode in ["tested", "mixed", "task_pins"]:
            with self.subTest(mode=mode), workspace_fixture(("mixed",)) as (root, manager, fixtures):
                fixture = fixtures["mixed"]; definition = manager.projects[fixture["project_id"]]["definition"]
                if mode in ["tested", "mixed"]:
                    names = definition["files"] if mode == "tested" else ["addition.py"]
                    for name in names: (fixture["source"] / name).write_bytes((fixture["attempt_dir"] / "snapshot" / name).read_bytes())
                else:
                    task = copy.deepcopy(definition); task["files"]["addition.py"] = "a" * 64
                    raw = canonical(task); fixture["task"].write_bytes(raw)
                    manager.projects[fixture["project_id"]].update(task_raw=raw, definition=task)
                with preview_guard(manager): self.refused(root, manager.snapshot_workspace_preview, fixture["project_id"], fixture["archive_raw"])

    def test_spawn_failure_retains_pinned_failure_and_blocks_legacy_execution(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager, OSError(PRIVATE_SENTINEL)) as (_, launch):
                with self.assertRaisesRegex(Refused, "^SNAPSHOT_WORKSPACE_START_FAILED$"):
                    manager.snapshot_workspace_create(create_request(preview))
                rows = manager.snapshot_workspaces()["workspaces"]
                self.assertEqual(len(rows), 1); self.assertEqual(rows[0]["status"], "FAILED")
                self.assertEqual(manager.admission(), "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED")
                self.refused(root, manager.start, {"project": "arithmetic", "model": "scripted-demo", "goal": manager.projects["arithmetic"]["definition"]["goal"]}, codes={"SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED"})
                self.refused(root, manager.snapshot_workspace_create, create_request(preview), codes={"SNAPSHOT_WORKSPACE_PREVIEW_REQUIRED"})
                launch.assert_called_once()

    def test_poll_completion_race_preserves_failed_receipt(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                created = manager.snapshot_workspace_create(create_request(preview))
                path = workspace_job(manager, created["id"]) / "receipt.json"
                def complete():
                    row = json.loads(path.read_bytes()); row.update(status="FAILED", reason="SNAPSHOT_WORKSPACE_CHECKS_FAILED", finished=row["created"] + 1)
                    path.write_bytes(canonical(row)); return 1
                child.poll.side_effect = complete
                value = manager.snapshot_workspace_view(created["id"])
                self.assertEqual((value["status"], value["reason"], value["owned_active"]), ("FAILED", "SNAPSHOT_WORKSPACE_CHECKS_FAILED", False))

    def test_owned_stop_retains_interruption_and_never_signals_unowned_history(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                created = manager.snapshot_workspace_create(create_request(preview))
                child.wait.side_effect = lambda **_: setattr(child.poll, "return_value", -15)
                with patch("workbench.os.killpg") as signal_group:
                    value = manager.snapshot_workspace_stop(created["id"]); signal_group.assert_called_once()
                self.assertEqual((value["status"], value["owned_active"]), ("INTERRUPTED", False))
                with patch("workbench.os.killpg", side_effect=AssertionError("unowned process signal")):
                    self.refused(root, manager.snapshot_workspace_stop, created["id"], codes={"NO_OWNED_ACTIVE_SNAPSHOT_WORKSPACE"})
                self.assertEqual(manager.admission(), "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED")

    def test_unknown_restart_pending_stays_unowned_and_unresolved_without_recovery(self):
        with workspace_fixture() as (root, first, fixtures):
            preview = self.preview(root, first, fixtures["python"])
            with fake_worker(first): created = first.snapshot_workspace_create(create_request(preview))
            first.close()
            first._snapshot_fixture_closed = True
            restarted = Manager(first.config_path, first.data)
            try:
                before = private_hashes(root)
                value = restarted.snapshot_workspace_view(created["id"])
                self.assertEqual((value["status"], value["owned_active"]), ("PREPARING", False))
                self.assertEqual(restarted.admission(), "SNAPSHOT_WORKSPACE_ACTIVE_OR_UNRESOLVED")
                with patch("workbench.os.killpg", side_effect=AssertionError("restart claimed ownership")):
                    self.refused(root, restarted.snapshot_workspace_stop, created["id"], codes={"NO_OWNED_ACTIVE_SNAPSHOT_WORKSPACE"})
                self.assertEqual(before, private_hashes(root))
            finally: restarted.close()

    def test_static_readiness_observes_pending_without_polling_or_rewriting_it(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                manager.snapshot_workspace_create(create_request(preview))
                before = private_hashes(root)
                child.poll.side_effect = AssertionError("readiness process reconciliation")
                with no_provider_calls():
                    value = manager.readiness_admission()
                self.assertIn("WORKSPACE_ACTIVE_OR_UNRESOLVED", value["reasons"])
                self.assertEqual(before, private_hashes(root))

    def test_static_readiness_blocks_verified_receipt_with_partial_next_without_mutation(self):
        from snapshot_workspace import build
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager): created = manager.snapshot_workspace_create(create_request(preview))
            job = workspace_job(manager, created["id"])
            with no_provider_calls(): receipt = build(job, checker=passing_checks)
            self.assertEqual(receipt["status"], "VERIFIED")
            write_new(job / "receipt.json.next", (job / "receipt.json").read_bytes())
            before = private_hashes(root)
            with no_provider_calls(), patch.object(manager, "snapshot_workspace_view", side_effect=AssertionError("readiness reconciled new workspace")):
                value = manager.readiness_admission()
            self.assertIn("ADMISSION_RECORD_INVALID", value["reasons"])
            self.assertEqual(before, private_hashes(root))
            self.refused(root, manager.snapshot_workspace_view, created["id"], codes={"SNAPSHOT_WORKSPACE_RECORD_INVALID"})

    def test_malformed_or_incomplete_verified_receipts_block_all_execution(self):
        for shape in [[], 42, {"status": []}, {"status": "VERIFIED"}]:
            with self.subTest(shape=shape), workspace_fixture() as (root, manager, fixtures):
                preview = self.preview(root, manager, fixtures["python"])
                with fake_worker(manager): created = manager.snapshot_workspace_create(create_request(preview))
                path = workspace_job(manager, created["id"]) / "receipt.json"
                if isinstance(shape, dict):
                    value = json.loads(path.read_bytes()); value.update(shape)
                else: value = shape
                path.write_bytes(canonical(value))
                self.refused(root, manager.snapshot_workspace_view, created["id"], codes={"SNAPSHOT_WORKSPACE_RECORD_INVALID"})
                self.assertEqual(manager.admission(), "SNAPSHOT_WORKSPACE_NEEDS_INSPECTION")
                before = private_hashes(root)
                with no_provider_calls(): self.assertIn("ADMISSION_RECORD_INVALID", manager.readiness_admission()["reasons"])
                self.assertEqual(before, private_hashes(root))

    def test_history_count_and_receipt_reserve_refuse_without_new_worker_or_record(self):
        for mode in ["count", "aggregate"]:
            with self.subTest(mode=mode), workspace_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]; first = self.preview(root, manager, fixture)
                with fake_worker(manager): created = manager.snapshot_workspace_create(create_request(first))
                template = json.loads((workspace_job(manager, created["id"]) / "receipt.json").read_bytes())
                count = 200 if mode == "count" else 9
                for number in range(count - 1):
                    identifier = f"{number:016x}"; directory = workspace_job(manager, identifier); directory.mkdir(mode=0o700)
                    raw = canonical({**template, "id": identifier})
                    if mode == "aggregate": raw += b" " * (235000 - len(raw))
                    write_new(directory / "receipt.json", raw)
                preview = self.preview(root, manager, fixture)
                with fake_worker(manager) as (_, launch), patch.object(manager, "admission", return_value=None):
                    self.refused(root, manager.snapshot_workspace_create, create_request(preview), codes={"SNAPSHOT_WORKSPACE_RECORD_LIMIT"})
                    launch.assert_not_called()
                self.assertEqual(len(list((manager.data / "snapshot-workspaces").iterdir())), count)

    def test_config_mutation_during_preparation_preserves_owner_bytes_and_refuses_preview(self):
        import snapshot_workspace
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; original = snapshot_workspace.read_selected
            owner_raw = manager.config_raw + b"\n"; calls = []
            def read_and_change(source, name, *args, **kwargs):
                raw = original(source, name, *args, **kwargs)
                if not calls: calls.append(name); manager.config_path.write_bytes(owner_raw)
                return raw
            before = private_hashes(root)
            with preview_guard(manager), patch("snapshot_workspace.read_selected", side_effect=read_and_change):
                with self.assertRaisesRegex(Refused, "^SNAPSHOT_WORKSPACE_PROJECT_CHANGED$"):
                    manager.snapshot_workspace_preview(fixture["project_id"], fixture["archive_raw"])
            self.assertTrue(calls)
            after = private_hashes(root); key = str(manager.config_path.relative_to(root))
            self.assertEqual({name: value for name, value in before.items() if name != key}, {name: value for name, value in after.items() if name != key})
            self.assertEqual(manager.config_path.read_bytes(), owner_raw)

    def test_fields_ids_and_unsafe_sources_are_bounded_without_persistent_writes(self):
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]; preview = self.preview(root, manager, fixture)
            with fake_worker(manager) as (_, launch):
                for request in [[], {"preview_id": preview["preview_id"]}, {**create_request(preview), "path": PRIVATE_SENTINEL}]:
                    self.refused(root, manager.snapshot_workspace_create, request, codes={"SNAPSHOT_WORKSPACE_FIELDS"})
                launch.assert_not_called()
            for identifier in [None, "../" + PRIVATE_SENTINEL, "g" * 16]:
                self.refused(root, manager.snapshot_workspace_view, identifier, codes={"SNAPSHOT_WORKSPACE_ID"})
            outside = root / "outside-source.py"; outside.write_bytes(PRIVATE_SENTINEL.encode())
            path = fixture["source"] / "arithmetic.py"; path.unlink(); path.symlink_to(outside)
            with preview_guard(manager): self.refused(root, manager.snapshot_workspace_preview, fixture["project_id"], fixture["archive_raw"])

    def test_invalid_archive_precedes_project_reads_and_old_recheck_preview_replaces_draft(self):
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with preview_guard(manager), patch("workbench.readiness_read_file", side_effect=AssertionError("invalid archive opened project file")):
                self.refused(root, manager.snapshot_workspace_preview, fixture["project_id"], b"invalid ZIP")
            preview = self.preview(root, manager, fixture)
            before = private_hashes(root)
            manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
            self.assertEqual(before, private_hashes(root))
            with fake_worker(manager) as (_, launch):
                self.refused(root, manager.snapshot_workspace_create, create_request(preview), codes={"SNAPSHOT_WORKSPACE_PREVIEW_REQUIRED"})
                launch.assert_not_called()

    def test_pending_receipt_next_file_is_retained_as_unresolved_evidence(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager): created = manager.snapshot_workspace_create(create_request(preview))
            job = workspace_job(manager, created["id"])
            write_new(job / "receipt.json.next", (job / "receipt.json").read_bytes())
            self.refused(root, manager.snapshot_workspace_view, created["id"], codes={"SNAPSHOT_WORKSPACE_RECORD_INVALID"})
            self.assertEqual(manager.admission(), "SNAPSHOT_WORKSPACE_NEEDS_INSPECTION")

    def test_close_stops_owned_child_and_preserves_foreign_saved_pending(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                created = manager.snapshot_workspace_create(create_request(preview))
                template = json.loads((workspace_job(manager, created["id"]) / "receipt.json").read_bytes())
                foreign = workspace_job(manager, "f" * 16); foreign.mkdir(mode=0o700)
                write_new(foreign / "receipt.json", canonical({**template, "id": "f" * 16}))
                foreign_before = private_hashes(foreign)
                child.wait.side_effect = lambda **_: setattr(child.poll, "return_value", -15)
                with patch("workbench.os.killpg") as signal_group:
                    manager.close(); signal_group.assert_called_once()
                    manager._snapshot_fixture_closed = True
                    self.assertEqual(signal_group.call_args.args[0], child.pid)
                self.assertEqual(private_hashes(foreign), foreign_before)
                self.assertEqual(manager.snapshot_workspace_view("f" * 16)["owned_active"], False)

    def test_new_type_is_not_adopted_by_legacy_recheck_or_export_routes(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager): created = manager.snapshot_workspace_create(create_request(preview))
            with no_provider_calls():
                self.refused(root, manager.recheck_preview, {"workspace_id": created["id"]})
                self.refused(root, manager.snapshot_export_preview, {"attempt_id": created["id"]})


@contextmanager
def workspace_http_fixture():
    with workspace_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-snapshot-workspace-token", "http://127.0.0.1:8765")
        def request(method, path, body=b"", headers=None):
            content_type = "application/json" if isinstance(body, dict) else "application/zip"
            if isinstance(body, dict): body = canonical(body)
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-snapshot-workspace-token"}
            if method == "POST": supplied.update({"Origin": "http://127.0.0.1:8765", "Content-Type": content_type, "Content-Length": str(len(body))})
            duplicate = headers if isinstance(headers, list) else []
            if isinstance(headers, dict): supplied.update(headers)
            handler = handler_type.__new__(handler_type); handler.command, handler.path = method, path
            handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, value in list(supplied.items()) + duplicate: handler.headers[key] = value
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            getattr(handler, "do_" + method)()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(raw)
        yield root, manager, fixtures, request


class SnapshotWorkspaceHTTPTests(unittest.TestCase):
    def test_binary_preview_json_create_and_saved_list_view(self):
        with workspace_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]; before = private_hashes(root)
            with preview_guard(manager):
                code, preview = request("POST", "/api/snapshot-workspace-preview/" + fixture["project_id"], fixture["archive_raw"], {"X-Snapshot-SHA256": fixture["archive_sha256"]})
            self.assertEqual(code, 200); self.assertEqual(before, private_hashes(root))
            with fake_worker(manager):
                code, created = request("POST", "/api/snapshot-workspace-create", create_request(preview))
                self.assertEqual((code, created["status"]), (200, "PREPARING"))
                code, rows = request("GET", "/api/snapshot-workspaces")
                self.assertEqual((code, rows["workspaces"][0]["id"]), (200, created["id"]))
                code, value = request("GET", "/api/snapshot-workspace/" + created["id"])
                self.assertEqual((code, value["owned_active"]), (200, True))

    def test_binary_and_json_framing_are_rejected_before_manager_invocation(self):
        with workspace_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]; before = private_hashes(root)
            with patch.object(manager, "snapshot_workspace_preview", side_effect=AssertionError("bad binary reached manager")) as invoke:
                for headers in [{"Content-Length": "2097153"}, {"Content-Length": "0"}, {"Content-Length": str(len(fixture["archive_raw"]) + 1)},
                    {"Transfer-Encoding": "chunked"}, [("Content-Length", str(len(fixture["archive_raw"])))], [("Content-Type", "application/zip")],
                    {"X-Snapshot-SHA256": "A" * 64}, [("X-Snapshot-SHA256", "a" * 64), ("X-Snapshot-SHA256", "a" * 64)]]:
                    code, value = request("POST", "/api/snapshot-workspace-preview/" + fixture["project_id"], fixture["archive_raw"], headers)
                    self.assertEqual(code, 409); self.assertRegex(value["error"], r"^[A-Z_]+$")
                invoke.assert_not_called()
            for action, method, body in [("create", "snapshot_workspace_create", {"preview_id": "1" * 16, "preview_sha256": "a" * 64}), ("stop", "snapshot_workspace_stop", {"id": "1" * 16})]:
                with patch.object(manager, method, side_effect=AssertionError("bad JSON reached manager")) as invoke:
                    for headers in [{"Content-Length": str(len(canonical(body)) + 1)}, {"Transfer-Encoding": "chunked"}, [("Content-Length", str(len(canonical(body))))]]:
                        code, value = request("POST", "/api/snapshot-workspace-" + action, body, headers)
                        self.assertEqual(code, 409); self.assertRegex(value["error"], r"^[A-Z_]+$")
                    invoke.assert_not_called()
            self.assertEqual(before, private_hashes(root))

    def test_host_session_origin_and_fetch_guards_apply_to_binary_preview(self):
        with workspace_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]; before = private_hashes(root)
            for headers, reason in [({"Host": "malicious.invalid"}, "HOST_REFUSED"), ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"), ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                code, value = request("POST", "/api/snapshot-workspace-preview/" + fixture["project_id"], fixture["archive_raw"], headers)
                self.assertEqual((code, value["error"]), (409, reason))
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__": unittest.main()
