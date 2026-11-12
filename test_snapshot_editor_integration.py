"""Invented private edit fixtures, admission preservation and exact HTTP framing.

Recorded fixture checks are fake observations; actual isolated Python/Java
qualification is separate in qa_snapshot_editor.py. No provider is contacted.
"""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_snapshot_recheck_integration import (
    attempt_path, fake_recheck, passing_checks, populate_recheck_workspaces, recheck_fixture, recheck_request,
)
from test_snapshot_reexport_integration import (
    accept_request, download_request, snapshot_reexport_guard,
)
from workbench import Manager, init_demo, make_handler


@contextmanager
def editor_guard(manager):
    """Editor reads/writes never reconcile execution or run checks/providers/Git."""
    with no_provider_calls(), ExitStack() as stack:
        for name in ["history", "refresh", "admission", "view", "export", "verified_artifact",
                     "request_hold", "owns_active", "workspace_receipt", "bundle_workspace_view",
                     "bundle_workspaces", "snapshot_recheck_view", "snapshot_rechecks",
                     "snapshot_workspace_view", "snapshot_workspaces", "project_readiness"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("editor reached " + name)))
        for name in ["workbench.subprocess.Popen", "workbench.subprocess.run", "workbench.process_stamp",
                     "agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.git"]:
            stack.enter_context(patch(name, side_effect=AssertionError("editor reached " + name)))
        yield


def editor_preview(manager, fixture, old_text="a + b", new_text="(a + b)"):
    """Explicitly list, open and preview one selected editable fixture file."""
    files = manager.snapshot_editor_files({"workspace_id": fixture["workspace_id"]})
    name = files["files"][0]["path"]
    opened = manager.snapshot_editor_open({"workspace_id": fixture["workspace_id"], "path": name})
    preview = manager.snapshot_editor_preview({"workspace_id": fixture["workspace_id"], "path": name,
        "expected_sha256": opened["sha256"], "old_text": old_text, "new_text": new_text})
    return opened, preview


def save_request(preview):
    return {"preview_id": preview["preview_id"], "preview_sha256": preview["preview_sha256"]}


def fake_verified_recheck(manager, fixture):
    from snapshot_recheck import run
    preview = manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
    previous_jdk = manager.jdk_home
    try:
        if "java" in fixture["project_id"] and manager.jdk_home is None:
            manager.jdk_home = manager.data / "unexecuted-editor-fixture-jdk"
        with fake_recheck(manager) as (child, _):
            started = manager.snapshot_recheck_start(recheck_request(preview))
            receipt = run(attempt_path(manager, started["id"]), manager.jdk_home, passing_checks)
            assert receipt["status"] == "VERIFIED"
            child.poll.return_value = 0
            assert manager.snapshot_recheck_view(started["id"])["owned_active"] is False
    finally:
        manager.jdk_home = previous_jdk
    return receipt


class SnapshotEditorIntegrationTests(unittest.TestCase):
    def refusal(self, root, operation, request, code=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(request)
        self.assertRegex(str(caught.exception), r"^[A-Z][A-Z0-9_]{1,64}$")
        if code is not None:
            self.assertEqual(str(caught.exception), code)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_open_preview_and_save_preserve_all_other_bytes(self):
        with recheck_fixture(("python", "java")) as (root, manager, fixtures):
            for language, fixture in fixtures.items():
                before = private_hashes(root)
                with editor_guard(manager):
                    opened, preview = editor_preview(manager, fixture)
                self.assertEqual(before, private_hashes(root))
                self.assertFalse(opened["admission"]["blocked"])
                self.assertNotIn(str(root), json.dumps(preview))
                self.assertTrue(preview["edit"]["requires_recheck"])
                with editor_guard(manager):
                    saved = manager.snapshot_editor_save(save_request(preview))
                target = fixture["workspace"] / opened["path"]
                self.assertEqual(target.read_bytes(), opened["text"].encode().replace(b"a + b", b"(a + b)", 1))
                self.assertEqual(saved["after_sha256"], sha(target.read_bytes()))
                self.assertEqual(saved["status"], "SAVED")
                relative = str(target.relative_to(root))
                prefix = str((manager.data / "snapshot-workspace-edits" / saved["edit_id"]).relative_to(root)) + "/"
                after = private_hashes(root)
                self.assertEqual({p: v for p, v in before.items() if p != relative},
                    {p: v for p, v in after.items() if p != relative and not p.startswith(prefix)})
                self.assertEqual({p[len(prefix):] for p in after if p.startswith(prefix)},
                                 {"receipt.json", "original.bin", "candidate.bin"})
                self.assertIsNone(manager.admission())

    def test_unicode_crlf_keeps_untouched_bytes_and_exact_full_read(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            name = manager.projects[fixture["project_id"]]["definition"]["editable"][0]
            path = fixture["workspace"] / name
            original = path.read_bytes().replace(b"\n", b"\r\n") + "# untouched café Ω\r\n".encode()
            path.write_bytes(original)
            with editor_guard(manager):
                opened, preview = editor_preview(manager, fixture, new_text="(a + b)  # reviewed café")
                self.assertEqual(opened["text"].encode(), original)
                self.assertEqual(opened["line_endings"], "CRLF")
                manager.snapshot_editor_save(save_request(preview))
            self.assertEqual(path.read_bytes(), original.replace(b"a + b", "(a + b)  # reviewed café".encode(), 1))
            self.assertEqual(path.read_bytes().count(b"\r\n"), original.count(b"\r\n"))

    def test_protected_unselected_control_and_traversal_paths_refuse_without_writes(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            fixture = fixtures["python"]
            for name in ["test_arithmetic.py", "unselected.py", ".git", "../arithmetic.py", "/outside.py"]:
                self.refusal(root, manager.snapshot_editor_open, {"workspace_id": fixture["workspace_id"], "path": name})

    def test_invalid_fields_workspace_ids_and_stale_expected_hash_refuse(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            fixture = fixtures["python"]
            self.refusal(root, manager.snapshot_editor_files, {"workspace_id": fixture["workspace_id"], "extra": 1}, "SNAPSHOT_EDITOR_FIELDS")
            for identifier in ["", "../outside", "f" * 16, None]:
                self.refusal(root, manager.snapshot_editor_files, {"workspace_id": identifier})
            opened, _ = editor_preview(manager, fixture)
            self.refusal(root, manager.snapshot_editor_preview, {"workspace_id": fixture["workspace_id"], "path": opened["path"],
                "expected_sha256": "0" * 64, "old_text": "a + b", "new_text": "(a + b)"}, "SNAPSHOT_EDITOR_STALE")

    def test_config_task_original_source_and_git_drift_refuse_save(self):
        for mode in ["config", "task", "source", "git", "editable", "protected"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                with editor_guard(manager):
                    opened, preview = editor_preview(manager, fixture)
                path = {"config": manager.config_path, "task": fixture["task"],
                    "source": fixture["source"] / opened["path"], "git": fixture["workspace"] / ".git",
                    "editable": fixture["workspace"] / opened["path"],
                    "protected": fixture["workspace"] / "test_arithmetic.py"}[mode]
                path.write_bytes(path.read_bytes() + b" \n")
                with editor_guard(manager):
                    self.refusal(root, manager.snapshot_editor_save, save_request(preview))
                self.assertEqual(list((manager.data / "snapshot-workspace-edits").iterdir()), [])

    def test_readonly_preview_under_hold_save_blocks_and_retains_hold(self):
        with recheck_fixture() as (root, manager, fixtures):
            write_new(manager.data / "state/hold.json", canonical({"state": "REQUEST_UNSETTLED", "run": "Invented editor hold", "turn": 1}))
            with editor_guard(manager):
                _, preview = editor_preview(manager, fixtures["python"])
                self.assertTrue(preview["admission"]["blocked"])
                self.assertIn("HOLD_PRESENT", preview["admission"]["reasons"])
                self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_BLOCKED")

    def test_hold_added_after_preview_blocks_save_without_creating_journal(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            _, preview = editor_preview(manager, fixtures["python"])
            write_new(manager.data / "state/hold.json", b"invented corrupt hold stays held")
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_BLOCKED")
            self.assertEqual(list((manager.data / "snapshot-workspace-edits").iterdir()), [])

    def test_owned_worker_record_blocks_without_polling_or_reconciliation(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            _, preview = editor_preview(manager, fixtures["python"])
            child = Mock(); child.poll.side_effect = AssertionError("editor polled owned worker")
            manager.children["1" * 16] = (child, Mock())
            try:
                self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_BLOCKED")
                child.poll.assert_not_called()
            finally:
                manager.children.clear()

    def test_saved_active_and_uncertain_task_records_block_without_refresh(self):
        for state in ["RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED", "UNCERTAIN", "unknown"]:
            with self.subTest(state=state), recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
                _, preview = editor_preview(manager, fixtures["python"])
                write_new(manager.data / "jobs" / ("1" * 16 + ".json"), canonical({"id": "1" * 16, "state": state}))
                self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_BLOCKED")

    def test_expired_consumed_and_mismatched_previews_require_explicit_new_preview(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            with patch("workbench.time.monotonic", return_value=1000):
                _, preview = editor_preview(manager, fixtures["python"])
            with patch("workbench.time.monotonic", return_value=1301):
                self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_PREVIEW_EXPIRED")
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_PREVIEW_REQUIRED")
            _, preview = editor_preview(manager, fixtures["python"])
            self.refusal(root, manager.snapshot_editor_save, {"preview_id": "0" * 16, "preview_sha256": preview["preview_sha256"]},
                         "SNAPSHOT_EDITOR_PREVIEW_CHANGED")
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_PREVIEW_REQUIRED")

    def test_open_another_file_or_replacement_preview_invalidates_previous_save(self):
        with recheck_fixture(("python", "java")) as (root, manager, fixtures), editor_guard(manager):
            _, first = editor_preview(manager, fixtures["python"])
            _, second = editor_preview(manager, fixtures["java"])
            self.refusal(root, manager.snapshot_editor_save, save_request(first), "SNAPSHOT_EDITOR_PREVIEW_CHANGED")
            self.refusal(root, manager.snapshot_editor_save, save_request(second), "SNAPSHOT_EDITOR_PREVIEW_REQUIRED")
            opened, preview = editor_preview(manager, fixtures["python"])
            manager.snapshot_editor_open({"workspace_id": fixtures["python"]["workspace_id"], "path": opened["path"]})
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_PREVIEW_REQUIRED")

    def test_restart_discards_preview_and_preserves_saved_edit_evidence(self):
        # Own both Manager lifetimes explicitly: the shared recheck fixture
        # closes its one Manager on exit and must not double-close a restart.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = init_demo(root / "workspace", None)
            manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
            fixtures = populate_recheck_workspaces(manager, root, ("python",))
            with editor_guard(manager):
                _, preview = editor_preview(manager, fixtures["python"])
                saved = manager.snapshot_editor_save(save_request(preview))
                _, pending = editor_preview(manager, fixtures["python"], "(a + b)", "((a + b))")
            before = private_hashes(root)
            config, data = manager.config_path, manager.data
            manager.close()
            reopened = Manager(config, data)
            try:
                with editor_guard(reopened):
                    self.refusal(root, reopened.snapshot_editor_save, save_request(pending), "SNAPSHOT_EDITOR_PREVIEW_REQUIRED")
                    files = reopened.snapshot_editor_files({"workspace_id": fixtures["python"]["workspace_id"]})
                    self.assertEqual(files["files"][0]["sha256"], saved["after_sha256"])
                    self.assertFalse(files["admission"]["blocked"])
                self.assertEqual(before, private_hashes(root))
            finally:
                reopened.close()

    def test_save_consumes_cached_recheck_and_export_previews(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            receipt = fake_verified_recheck(manager, fixture)
            manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
            manager.snapshot_reexport_preview({"attempt_id": receipt["id"]})
            with editor_guard(manager):
                _, preview = editor_preview(manager, fixture)
                manager.snapshot_editor_save(save_request(preview))
            self.assertIsNone(manager.snapshot_recheck_draft)
            self.assertIsNone(manager.snapshot_reexport_draft)
            self.assertIsNone(manager.snapshot_editor_draft)

    def test_prior_attempt_refuses_after_edit_even_reverting_to_identical_checked_bytes(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            old = fake_verified_recheck(manager, fixture)
            old_before = private_hashes(attempt_path(manager, old["id"]))
            with editor_guard(manager):
                _, forward = editor_preview(manager, fixture)
                manager.snapshot_editor_save(save_request(forward))
                _, reverse = editor_preview(manager, fixture, "(a + b)", "a + b")
                manager.snapshot_editor_save(save_request(reverse))
            self.refusal(root, manager.snapshot_reexport_preview, {"attempt_id": old["id"]}, "SNAPSHOT_REEXPORT_RECHECK_REQUIRED")
            fresh = fake_verified_recheck(manager, fixture)
            with snapshot_reexport_guard(manager):
                preview = manager.snapshot_reexport_preview({"attempt_id": fresh["id"]})
                accepted = manager.snapshot_reexport_accept(accept_request(preview))
                raw = manager.snapshot_reexport_download(download_request(accepted, preview))
            from snapshot_export import verify_export
            self.assertEqual(verify_export(raw)["version"], 2)
            self.assertEqual(old_before, private_hashes(attempt_path(manager, old["id"])))

    def test_recheck_history_change_invalidates_editor_preview(self):
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            old = fake_verified_recheck(manager, fixture)
            with editor_guard(manager):
                _, preview = editor_preview(manager, fixture)
            path = attempt_path(manager, old["id"]) / "receipt.json"
            path.write_bytes(path.read_bytes() + b" \n")
            with editor_guard(manager):
                self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_STALE")

    def test_failed_save_retains_original_candidate_and_blocks_all_later_mutations(self):
        import snapshot_editor
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with editor_guard(manager):
                opened, preview = editor_preview(manager, fixture)
                before_target = (fixture["workspace"] / opened["path"]).read_bytes()
                replace = snapshot_editor.os.replace
                def fail_target(source, destination, *args, **kwargs):
                    if source == "replacement.next":
                        raise OSError("invented private write failure")
                    return replace(source, destination, *args, **kwargs)
                with patch("snapshot_editor.os.replace", side_effect=fail_target):
                    with self.assertRaisesRegex(Refused, "^SNAPSHOT_EDITOR_WRITE_FAILED$"):
                        manager.snapshot_editor_save(save_request(preview))
            self.assertEqual((fixture["workspace"] / opened["path"]).read_bytes(), before_target)
            directory, = (manager.data / "snapshot-workspace-edits").iterdir()
            receipt = json.loads((directory / "receipt.json").read_bytes())
            self.assertEqual((receipt["status"], receipt["workspace_write_state"]), ("FAILED", "MAY_HAVE_CHANGED"))
            self.assertEqual({p.name for p in directory.iterdir()}, {"receipt.json", "original.bin", "candidate.bin", "replacement.next"})
            before = private_hashes(root)
            self.assertEqual(manager.admission(), "SNAPSHOT_EDITOR_UNRESOLVED")
            self.assertIn("WORKSPACE_ACTIVE_OR_UNRESOLVED", manager.readiness_admission()["reasons"])
            self.refusal(root, manager.snapshot_recheck_preview, {"workspace_id": fixture["workspace_id"]}, "SNAPSHOT_EDITOR_UNRESOLVED")
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_PREVIEW_REQUIRED")
            self.assertEqual(before, private_hashes(root))

    def test_final_receipt_failure_retains_changed_target_and_uncertain_preparing_record(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            opened, preview = editor_preview(manager, fixtures["python"])
            with patch("workbench.replace_json", side_effect=OSError("invented final journal write failure")):
                with self.assertRaises(OSError):
                    manager.snapshot_editor_save(save_request(preview))
            path = fixtures["python"]["workspace"] / opened["path"]
            self.assertEqual(sha(path.read_bytes()), preview["edit"]["after_sha256"])
            directory, = (manager.data / "snapshot-workspace-edits").iterdir()
            receipt = json.loads((directory / "receipt.json").read_bytes())
            self.assertEqual((receipt["status"], receipt["workspace_write_state"]), ("PREPARING", "MAY_HAVE_CHANGED"))
            self.assertTrue(manager._snapshot_editor_admission()["blocked"])
            self.refusal(root, manager.snapshot_editor_files, {"workspace_id": fixtures["python"]["workspace_id"]}, "SNAPSHOT_EDITOR_UNRESOLVED")

    def test_post_replace_verification_failure_retains_uncertainty_without_rollback(self):
        import snapshot_editor
        with recheck_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            old = fake_verified_recheck(manager, fixture)
            with editor_guard(manager):
                opened, preview = editor_preview(manager, fixture)
                inspect = snapshot_editor.inspect_workspace
                calls = []
                def inspect_after_replace(*args, **kwargs):
                    calls.append(1)
                    if len(calls) == 3:
                        raise Refused("SNAPSHOT_EDITOR_STALE")
                    return inspect(*args, **kwargs)
                with patch("snapshot_editor.inspect_workspace", side_effect=inspect_after_replace):
                    with self.assertRaisesRegex(Refused, "^SNAPSHOT_EDITOR_WRITE_UNCERTAIN$"):
                        manager.snapshot_editor_save(save_request(preview))
            path = fixture["workspace"] / opened["path"]
            self.assertEqual(sha(path.read_bytes()), preview["edit"]["after_sha256"])
            directory, = (manager.data / "snapshot-workspace-edits").iterdir()
            receipt = json.loads((directory / "receipt.json").read_bytes())
            self.assertEqual((receipt["status"], receipt["reason"], receipt["workspace_write_state"]),
                ("FAILED", "SNAPSHOT_EDITOR_WRITE_UNCERTAIN", "MAY_HAVE_CHANGED"))
            self.assertEqual({p.name for p in directory.iterdir()}, {"receipt.json", "original.bin", "candidate.bin"})
            self.assertEqual(manager.admission(), "SNAPSHOT_EDITOR_UNRESOLVED")
            self.refusal(root, manager.snapshot_reexport_preview, {"attempt_id": old["id"]})

    def test_partial_malformed_and_pending_edit_records_refuse_without_repair(self):
        for mode in ["empty", "malformed", "next", "symlink"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures):
                directory = manager.data / "snapshot-workspace-edits" / ("0" * 16)
                if mode == "symlink":
                    directory.symlink_to(root, target_is_directory=True)
                else:
                    directory.mkdir(mode=0o700)
                    if mode == "malformed":
                        write_new(directory / "receipt.json", b"{\"status\":\"SAVED\"}")
                    elif mode == "next":
                        write_new(directory / "receipt.json.next", b"invented preserved partial receipt")
                before = private_hashes(manager.data)
                with patch.object(manager, "history", side_effect=AssertionError("unresolved edit reconciled jobs")):
                    self.assertEqual(manager.admission(), "SNAPSHOT_EDITOR_UNRESOLVED")
                self.assertIn("ADMISSION_RECORD_INVALID", manager.readiness_admission()["reasons"])
                self.refusal(manager.data, manager.snapshot_recheck_preview, {"workspace_id": fixtures["python"]["workspace_id"]})
                self.assertEqual(before, private_hashes(manager.data))

    def test_saved_retained_bytes_corruption_is_not_accepted_as_settled_evidence(self):
        for mode in ["candidate", "original", "link"]:
            with self.subTest(mode=mode), recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
                _, preview = editor_preview(manager, fixtures["python"])
                saved = manager.snapshot_editor_save(save_request(preview))
                directory = manager.data / "snapshot-workspace-edits" / saved["edit_id"]
                path = directory / ("original.bin" if mode == "original" else "candidate.bin")
                if mode == "link":
                    path.unlink(); path.symlink_to(directory / "original.bin")
                else:
                    path.write_bytes(path.read_bytes() + b"invented corruption")
                self.refusal(root, manager.snapshot_editor_files, {"workspace_id": fixtures["python"]["workspace_id"]}, "SNAPSHOT_EDITOR_UNRESOLVED")

    def test_journal_count_limit_refuses_before_source_write(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            _, preview = editor_preview(manager, fixtures["python"])
            saved = manager.snapshot_editor_save(save_request(preview))
            directory = manager.data / "snapshot-workspace-edits" / saved["edit_id"]
            original = json.loads((directory / "receipt.json").read_bytes())
            for number in range(199):
                identifier = f"{number:016x}"
                child = directory.parent / identifier
                child.mkdir(mode=0o700)
                write_new(child / "receipt.json", canonical({**original, "id": identifier}))
                for name in ["original.bin", "candidate.bin"]:
                    write_new(child / name, (directory / name).read_bytes())
            _, preview = editor_preview(manager, fixtures["python"], "(a + b)", "((a + b))")
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_STALE")
            self.assertEqual(len(list(directory.parent.iterdir())), 200)

    def test_receipt_budget_is_reserved_before_creating_a_new_edit(self):
        with recheck_fixture() as (root, manager, fixtures), editor_guard(manager):
            _, preview = editor_preview(manager, fixtures["python"])
            saved = manager.snapshot_editor_save(save_request(preview))
            directory = manager.data / "snapshot-workspace-edits" / saved["edit_id"]
            original = json.loads((directory / "receipt.json").read_bytes())
            for number in range(64):
                identifier = f"{number:016x}"
                child = directory.parent / identifier
                child.mkdir(mode=0o700)
                raw = canonical({**original, "id": identifier})
                write_new(child / "receipt.json", raw + b" " * (32500 - len(raw)))
                for name in ["original.bin", "candidate.bin"]:
                    write_new(child / name, (directory / name).read_bytes())
            _, preview = editor_preview(manager, fixtures["python"], "(a + b)", "((a + b))")
            self.refusal(root, manager.snapshot_editor_save, save_request(preview), "SNAPSHOT_EDITOR_UNRESOLVED")
            self.assertEqual(len(list(directory.parent.iterdir())), 65)


@contextmanager
def editor_http_fixture():
    with recheck_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-editor-token", "http://127.0.0.1:8765")
        def request(path, value, headers=None, raw=None):
            raw = canonical(value) if raw is None else raw
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-editor-token",
                "Origin": "http://127.0.0.1:8765", "Content-Type": "application/json", "Content-Length": str(len(raw))}
            duplicates = headers if isinstance(headers, list) else []
            if isinstance(headers, dict):
                supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "POST", path
            handler.request_version, handler.requestline = "HTTP/1.1", "POST " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in list(supplied.items()) + duplicates:
                handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
            handler.do_POST()
            head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(body)
        yield root, manager, fixtures, request


class SnapshotEditorHTTPTests(unittest.TestCase):
    def test_exact_files_open_preview_save_route_roundtrip(self):
        with editor_http_fixture() as (root, manager, fixtures, request), editor_guard(manager):
            workspace_id = fixtures["python"]["workspace_id"]
            code, files = request("/api/snapshot-editor-files", {"workspace_id": workspace_id})
            self.assertEqual(code, 200)
            name = files["files"][0]["path"]
            code, opened = request("/api/snapshot-editor-open", {"workspace_id": workspace_id, "path": name})
            self.assertEqual(code, 200)
            code, preview = request("/api/snapshot-editor-preview", {"workspace_id": workspace_id, "path": name,
                "expected_sha256": opened["sha256"], "old_text": "a + b", "new_text": "(a + b)"})
            self.assertEqual(code, 200)
            code, saved = request("/api/snapshot-editor-save", save_request(preview))
            self.assertEqual((code, saved["status"]), (200, "SAVED"))
            self.assertFalse(saved["source_applied"])
            self.assertNotIn(str(root), json.dumps(saved))

    def test_framing_authentication_and_origin_guards_precede_every_editor_route(self):
        with editor_http_fixture() as (root, manager, fixtures, request):
            for action in ["files", "open", "preview", "save"]:
                with patch.object(manager, "snapshot_editor_" + action, side_effect=AssertionError("malformed HTTP reached editor")) as invoke:
                    value = {"workspace_id": fixtures["python"]["workspace_id"]}
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"},
                        {"Content-Length": "-1"}, {"Content-Length": "262145"}, {"Content-Length": "999"},
                        {"Content-Type": "application/zip"}, [("Content-Length", str(len(canonical(value))))],
                        [("Content-Type", "application/json")]]:
                        before = private_hashes(root)
                        code, result = request("/api/snapshot-editor-" + action, value, headers)
                        self.assertEqual(code, 409)
                        self.assertRegex(result["error"], r"^[A-Z][A-Z0-9_]{1,64}$")
                        self.assertEqual(before, private_hashes(root))
                    for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"),
                        ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"),
                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                        ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        code, result = request("/api/snapshot-editor-" + action, value, headers)
                        self.assertEqual((code, result["error"]), (409, error))
                    invoke.assert_not_called()

    def test_duplicate_json_keys_unknown_routes_and_invalid_utf8_are_finite_refusals(self):
        with editor_http_fixture() as (root, manager, fixtures, request):
            for path, raw in [("files", b'{"workspace_id":"a","workspace_id":"b"}'),
                              ("files", b"\xff"), ("unknown", b"{}")]:
                before = private_hashes(root)
                code, result = request("/api/snapshot-editor-" + path, {}, raw=raw)
                self.assertEqual(code, 409)
                self.assertRegex(result["error"], r"^[A-Z][A-Z0-9_]{1,64}$")
                self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()
