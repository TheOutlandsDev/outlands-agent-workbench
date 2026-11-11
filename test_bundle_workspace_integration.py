"""Hold-free workspace fixtures and bounded preview/create/receipt integration."""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_bundle_project_check_integration import populate_project_check
from test_patch_bundle_integration import private_hashes
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-bundle-workspace-sentinel"


def populate_workspace_projects(manager, root):
    """Copy only invented source/task profiles into a clean, hold-free Manager.

    A separate builder retains its synthetic hold. That hold is never removed,
    copied into the target Manager, or used to authorize workspace creation.
    """
    builder_root = root / "bundle-builder"
    builder_root.mkdir(mode=0o700)
    paths = init_demo(builder_root / "workspace", None)
    builder = Manager(Path(paths["config"]), Path(paths["data_dir"]))
    fixtures = {}
    try:
        built = populate_project_check(builder, builder_root)
        builder_hold = builder.data / "state/hold.json"
        hold_raw = builder_hold.read_bytes()
        for language, item in built.items():
            definition = builder.projects[item["project_id"]]["definition"]
            source = root / ("workspace-source-" + language)
            source.mkdir(mode=0o700)
            for name in definition["files"]:
                target = source / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                write_new(target, (item["source"] / name).read_bytes())
            project_id = "workspace_" + language
            spec = next(iter(definition["checks"].values()))
            java = isinstance(spec, dict) and spec.get("kind") == "java-main"
            request = {"id": project_id, "name": "Invented " + language + " bundle workspace", "source": str(source),
                "language": "java" if java else "python", "files": list(definition["files"]),
                "editable": list(definition["editable"]), "check": spec["main_class"] if java else spec["pattern"],
                "goal": "Review this invented private bundle in a separate workspace."}
            previous_jdk = manager.jdk_home
            try:
                if java and manager.jdk_home is None:
                    manager.jdk_home = root / "unexecuted-jdk-presence-marker"
                draft = manager.project_preview(request)
                manager.project_save({"draft": draft["draft"]})
            finally:
                manager.jdk_home = previous_jdk
            fixtures[language] = {"project_id": project_id, "bundle_raw": item["bundle_raw"],
                "bundle_sha256": item["bundle_sha256"], "source": source,
                "task": manager.projects[project_id]["task"]}
        assert builder_hold.read_bytes() == hold_raw
        assert not (manager.data / "state/hold.json").exists()
        return fixtures
    finally:
        builder.close()


@contextmanager
def workspace_fixture(jdk=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]), jdk)
        fixtures = populate_workspace_projects(manager, root)
        try:
            yield root, manager, fixtures
        finally:
            # Mocked test workers never represent an external process.
            for workspace_id, (_, log) in list(manager.bundle_workspace_children.items()):
                log.close()
                manager.bundle_workspace_children.pop(workspace_id)
            manager.close()


@contextmanager
def no_provider_calls():
    with ExitStack() as stack:
        for name in ["agent.Ollama.request", "agent.Ollama.preflight", "agent.ScriptedDemo.request",
                     "http.client.HTTPConnection", "socket.socket"]:
            stack.enter_context(patch(name, side_effect=AssertionError("workspace reached " + name)))
        yield


@contextmanager
def preview_guard(manager):
    with no_provider_calls(), ExitStack() as stack:
        for name in ["history", "refresh", "admission", "view", "export", "verified_artifact", "request_hold",
                     "owns_active", "workspace_receipt", "bundle_preview", "bundle_export"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("preview reached " + name)))
        for name in ["workbench.subprocess.Popen", "workbench.subprocess.run", "workbench.process_stamp",
                     "agent.Session.checks", "isolation.check", "java_check.check"]:
            stack.enter_context(patch(name, side_effect=AssertionError("preview reached " + name)))
        yield


def create_request(preview):
    return {"preview_id": preview["preview_id"], "preview_sha256": preview["preview_sha256"]}


@contextmanager
def fake_worker(manager, *, start_error=None):
    child = Mock()
    child.pid = 99999999
    child.poll.return_value = None
    with no_provider_calls(), patch("workbench.subprocess.run", side_effect=AssertionError("parent ran command")), \
            patch("workbench.subprocess.Popen", side_effect=start_error, return_value=child) as launch:
        try:
            yield child, launch
        finally:
            for workspace_id, (owned, log) in list(manager.bundle_workspace_children.items()):
                if owned is child:
                    log.close()
                    manager.bundle_workspace_children.pop(workspace_id)


def workspace_job(manager, workspace_id):
    return manager.data / "bundle-workspaces" / workspace_id


class BundleWorkspaceIntegrationTests(unittest.TestCase):
    def preview(self, root, manager, fixture):
        before = private_hashes(root)
        with preview_guard(manager):
            result = manager.bundle_workspace_preview(fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"])
        self.assertEqual(before, private_hashes(root))
        self.assertEqual(result["comparison"]["status"], "BASELINE_MATCH")
        self.assertIs(result["workspace_ready"], True)
        self.assertEqual(result["bundle_sha256"], fixture["bundle_sha256"])
        self.assertEqual(result["config_sha256"], sha(manager.config_raw))
        self.assertEqual(result["task_sha256"], sha(manager.projects[fixture["project_id"]]["task_raw"]))
        self.assertRegex(result["preview_id"], r"^[0-9a-f]{16}$")
        self.assertRegex(result["preview_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn(str(root), json.dumps(result))
        return result

    def assert_no_write_refusal(self, root, operation, *args, codes=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(*args)
        code = str(caught.exception)
        self.assertRegex(code, r"^[A-Z][A-Z0-9_]{1,64}$")
        self.assertNotIn(PRIVATE_SENTINEL, code)
        if codes:
            self.assertIn(code, codes)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_previews_are_memory_only_with_builder_hold_retained(self):
        with workspace_fixture() as (root, manager, fixtures):
            self.assertFalse((manager.data / "state/hold.json").exists())
            self.assertIsNone(manager.jdk_home)
            for language in ["python", "java"]:
                with self.subTest(language=language):
                    result = self.preview(root, manager, fixtures[language])
                    self.assertGreater(result["expires_at_ms"], 0)
                    self.assertEqual({row["path"] for row in result["files"]}, set(manager.projects[fixtures[language]["project_id"]]["definition"]["files"]))
            self.assertEqual(list((manager.data / "bundle-workspaces").iterdir()), [])

    def test_create_persists_only_owned_job_and_launches_fixed_worker_once(self):
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            original = private_hashes(fixture["source"])
            preview = self.preview(root, manager, fixture)
            with fake_worker(manager) as (_, launch):
                result = manager.bundle_workspace_create(create_request(preview))
                self.assertEqual(result["status"], "PREPARING")
                self.assertIs(result["owned_active"], True)
                self.assertIs(result["source_applied"], False)
                job = workspace_job(manager, result["id"])
                self.assertTrue({"receipt.json", "request.json", "task.json", "bundle.zip", "worker.log"} <= {p.name for p in job.iterdir()})
                self.assertEqual((job / "bundle.zip").read_bytes(), fixture["bundle_raw"])
                self.assertEqual((job / "task.json").read_bytes(), manager.projects[fixture["project_id"]]["task_raw"])
                request = json.loads((job / "request.json").read_bytes())
                self.assertEqual(request["source"], str(fixture["source"]))
                self.assertEqual(request["preview_sha256"], preview["preview_sha256"])
                command = launch.call_args.args[0]
                self.assertTrue(command[2].endswith("/bundle_workspace.py"))
                self.assertEqual(command[3:], ["--job-dir", str(job)])
                launch.assert_called_once()
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(preview), codes={"BUNDLE_WORKSPACE_PREVIEW_REQUIRED"})
                self.assertEqual(len(manager.bundle_workspaces()["workspaces"]), 1)
            self.assertEqual(original, private_hashes(fixture["source"]))
            self.assertEqual(list((manager.data / "jobs").iterdir()), [])
            self.assertEqual(list((manager.data / "runs").iterdir()), [])

    def test_expired_preview_never_creates_or_launches(self):
        with workspace_fixture() as (root, manager, fixtures):
            with patch("workbench.time.monotonic", return_value=1000):
                preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (_, launch), patch("workbench.time.monotonic", return_value=1301):
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(preview), codes={"BUNDLE_WORKSPACE_PREVIEW_EXPIRED"})
                launch.assert_not_called()

    def test_preview_attempts_replace_old_cross_project_and_bundle_pins(self):
        with workspace_fixture() as (root, manager, fixtures):
            first = self.preview(root, manager, fixtures["python"])
            second = self.preview(root, manager, fixtures["java"])
            with fake_worker(manager) as (_, launch):
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(first), codes={"BUNDLE_WORKSPACE_PREVIEW_CHANGED"})
                self.assert_no_write_refusal(root, manager.bundle_workspace_create,
                    {"preview_id": second["preview_id"], "preview_sha256": first["preview_sha256"]}, codes={"BUNDLE_WORKSPACE_PREVIEW_CHANGED"})
                with preview_guard(manager):
                    self.assert_no_write_refusal(root, manager.bundle_workspace_preview, fixtures["python"]["project_id"], b"invalid ZIP")
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(second), codes={"BUNDLE_WORKSPACE_PREVIEW_REQUIRED"})
                launch.assert_not_called()

    def test_current_config_task_and_baseline_drift_refuse_before_jobs(self):
        for mode in ["config", "task", "baseline", "protected"]:
            with self.subTest(mode=mode), workspace_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                target = manager.config_path if mode == "config" else fixture["task"] if mode == "task" else fixture["source"] / ("test_arithmetic.py" if mode == "protected" else "arithmetic.py")
                target.write_bytes(target.read_bytes() + b"\n# intentional fixture drift\n")
                with fake_worker(manager) as (_, launch), ExitStack() as stack:
                    if mode in ["config", "task"]:
                        stack.enter_context(patch("workbench.prepare_bundle_workspace", side_effect=AssertionError("project pin drift read source")))
                    self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(preview),
                        codes={"BUNDLE_WORKSPACE_PROJECT_CHANGED"} if mode in ["config", "task"] else None)
                    launch.assert_not_called()
                self.assertEqual(list((manager.data / "bundle-workspaces").iterdir()), [])

    def test_selected_unsafe_source_and_nonbaseline_candidate_never_prepare(self):
        for mode in ["symlink", "hardlink", "candidate"]:
            with self.subTest(mode=mode), workspace_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                target = fixture["source"] / "arithmetic.py"
                if mode == "candidate":
                    target.write_bytes(target.read_bytes().replace(b"a - b", b"a + b"))
                else:
                    outside = root / "outside-selected.py"; outside.write_bytes(PRIVATE_SENTINEL.encode())
                    target.unlink()
                    if mode == "symlink":
                        target.symlink_to(outside)
                    else:
                        target.hardlink_to(outside)
                with preview_guard(manager):
                    self.assert_no_write_refusal(root, manager.bundle_workspace_preview, fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"])
                self.assertEqual(list((manager.data / "bundle-workspaces").iterdir()), [])

    def test_target_hold_allows_advisory_preview_but_create_has_no_mutation(self):
        with workspace_fixture() as (root, manager, fixtures):
            hold = manager.data / "state/hold.json"
            write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": "/fictional/unrelated-held-run", "turn": 1}))
            preview = self.preview(root, manager, fixtures["python"])
            original_hold = hold.read_bytes()
            with fake_worker(manager) as (_, launch), patch("workbench.prepare_bundle_workspace", side_effect=AssertionError("held create prepared files")):
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(preview), codes={"UNCERTAIN_REQUEST_HELD"})
                launch.assert_not_called()
            self.assertEqual(hold.read_bytes(), original_hold)

    def test_java_jdk_prerequisite_refuses_before_persistent_work(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["java"])
            with fake_worker(manager) as (_, launch):
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(preview), codes={"JDK_REQUIRED"})
                launch.assert_not_called()
            self.assertEqual(list((manager.data / "bundle-workspaces").iterdir()), [])

    def test_start_failure_is_retained_consumes_preview_and_blocks_existing_start(self):
        with workspace_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            source_before = private_hashes(fixture["source"])
            preview = self.preview(root, manager, fixture)
            with fake_worker(manager, start_error=OSError(PRIVATE_SENTINEL)) as (_, launch):
                with self.assertRaisesRegex(Refused, "^BUNDLE_WORKSPACE_START_FAILED$"):
                    manager.bundle_workspace_create(create_request(preview))
                rows = manager.bundle_workspaces()["workspaces"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "FAILED")
                job = workspace_job(manager, rows[0]["id"])
                self.assertTrue((job / "bundle.zip").is_file())
                self.assertEqual(manager.admission(), "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED")
                self.assert_no_write_refusal(root, manager.bundle_workspace_create, create_request(preview), codes={"BUNDLE_WORKSPACE_PREVIEW_REQUIRED"})
                self.assert_no_write_refusal(root, manager.start, {"project": "arithmetic", "model": "scripted-demo", "goal": manager.projects["arithmetic"]["definition"]["goal"]}, codes={"BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED"})
                launch.assert_called_once()
            self.assertEqual(source_before, private_hashes(fixture["source"]))

    def test_owned_exit_keeps_worker_failure_receipt_written_during_poll(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                result = manager.bundle_workspace_create(create_request(preview))
                receipt_path = workspace_job(manager, result["id"]) / "receipt.json"

                def finish_worker():
                    receipt = json.loads(receipt_path.read_bytes())
                    receipt.update(status="FAILED", reason="BUNDLE_WORKSPACE_CHECKS_FAILED", finished=100)
                    receipt_path.write_bytes(canonical(receipt))
                    return 1

                child.poll.side_effect = finish_worker
                value = manager.bundle_workspace_view(result["id"])
                self.assertEqual(value["status"], "FAILED")
                self.assertEqual(value["reason"], "BUNDLE_WORKSPACE_CHECKS_FAILED")
                self.assertIs(value["owned_active"], False)
                before = private_hashes(root)
                self.assertEqual(manager.bundle_workspace_view(result["id"])["status"], "FAILED")
                self.assertEqual(before, private_hashes(root))
                self.assertEqual(manager.admission(), "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED")

    def test_owned_exit_without_terminal_evidence_is_interrupted_not_verified(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                result = manager.bundle_workspace_create(create_request(preview))
                child.poll.return_value = 0
                value = manager.bundle_workspace_view(result["id"])
                self.assertEqual(value["status"], "INTERRUPTED")
                self.assertEqual(value["reason"], "BUNDLE_WORKSPACE_INTERRUPTED")
                self.assertIs(value["owned_active"], False)
                self.assertEqual(manager.admission(), "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED")

    def test_owned_stop_retains_job_and_cannot_stop_unowned_again(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with fake_worker(manager) as (child, _):
                result = manager.bundle_workspace_create(create_request(preview))
                child.wait.side_effect = lambda **_: setattr(child.poll, "return_value", -15)
                with patch("workbench.os.killpg") as signal_group:
                    value = manager.bundle_workspace_stop(result["id"])
                    signal_group.assert_called_once()
                self.assertEqual(value["status"], "INTERRUPTED")
                self.assertTrue((workspace_job(manager, result["id"]) / "bundle.zip").is_file())
                with patch("workbench.os.killpg", side_effect=AssertionError("unowned signal")):
                    self.assert_no_write_refusal(root, manager.bundle_workspace_stop, result["id"], codes={"NO_OWNED_ACTIVE_BUNDLE_WORKSPACE"})

    def test_malformed_and_incomplete_verified_receipts_are_bounded_and_blocked(self):
        for mutation in [[], 42, {"status": []}, {"status": "VERIFIED"}]:
            with self.subTest(mutation=mutation), workspace_fixture() as (root, manager, fixtures):
                preview = self.preview(root, manager, fixtures["python"])
                with fake_worker(manager):
                    result = manager.bundle_workspace_create(create_request(preview))
                    path = workspace_job(manager, result["id"]) / "receipt.json"
                    if isinstance(mutation, dict):
                        value = json.loads(path.read_bytes()); value.update(mutation)
                    else:
                        value = mutation
                    path.write_bytes(canonical(value))
                    self.assert_no_write_refusal(root, manager.bundle_workspace_view, result["id"], codes={"BUNDLE_WORKSPACE_RECORD_INVALID"})
                    self.assertEqual(manager.admission(), "BUNDLE_WORKSPACE_NEEDS_INSPECTION")

    def test_request_shape_cannot_choose_paths_or_expand_execution_scope(self):
        with workspace_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            for key, value in {"path": "/fictional/outside", "project_id": "workspace_java", "bundle_raw": "unreviewed", "checks": {}, "command": "invented"}.items():
                with self.subTest(key=key), fake_worker(manager) as (_, launch):
                    self.assert_no_write_refusal(root, manager.bundle_workspace_create, {**create_request(preview), key: value}, codes={"BUNDLE_WORKSPACE_FIELDS"})
                    launch.assert_not_called()

    def test_restart_preserves_unknown_preparing_without_ownership_or_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = init_demo(root / "workspace", None)
            config, data = Path(paths["config"]), Path(paths["data_dir"])
            first = Manager(config, data)
            try:
                fixtures = populate_workspace_projects(first, root)
                preview = self.preview(root, first, fixtures["python"])
                with fake_worker(first):
                    result = first.bundle_workspace_create(create_request(preview))
            finally:
                first.close()
            restarted = Manager(config, data)
            try:
                before = private_hashes(root)
                value = restarted.bundle_workspace_view(result["id"])
                self.assertEqual(value["status"], "PREPARING")
                self.assertIs(value["owned_active"], False)
                self.assertEqual(restarted.admission(), "BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED")
                with patch("workbench.os.killpg", side_effect=AssertionError("restart claimed process")):
                    self.assert_no_write_refusal(root, restarted.bundle_workspace_stop, result["id"], codes={"NO_OWNED_ACTIVE_BUNDLE_WORKSPACE"})
                self.assertEqual(before, private_hashes(root))
            finally:
                restarted.close()

    def test_saved_workspace_inventory_is_bounded_before_reading_partial_history(self):
        with workspace_fixture() as (root, manager, _):
            for number in range(201):
                (manager.data / "bundle-workspaces" / f"{number:016x}").mkdir()
            self.assert_no_write_refusal(root, manager.bundle_workspaces, codes={"BUNDLE_WORKSPACE_RECORD_LIMIT"})
            self.assertEqual(manager.admission(), "BUNDLE_WORKSPACE_NEEDS_INSPECTION")


@contextmanager
def workspace_http_fixture():
    with workspace_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-workspace-token", "http://127.0.0.1:8765")

        def request(method, path, body=b"", headers=None):
            if isinstance(body, dict):
                body, content_type = canonical(body), "application/json"
            else:
                content_type = "application/zip"
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-workspace-token"}
            if method == "POST":
                supplied.update({"Origin": "http://127.0.0.1:8765", "Content-Type": content_type, "Content-Length": str(len(body))})
            duplicate = headers if isinstance(headers, list) else []
            if isinstance(headers, dict):
                supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = method, path
            handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, value in list(supplied.items()) + duplicate:
                handler.headers[key] = value
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            getattr(handler, "do_" + method)()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(raw)

        yield root, manager, fixtures, request


class BundleWorkspaceHTTPTests(unittest.TestCase):
    def test_binary_preview_json_create_and_saved_list_view_contracts(self):
        with workspace_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]
            before = private_hashes(root)
            with preview_guard(manager):
                code, preview = request("POST", "/api/bundle-workspace-preview/" + fixture["project_id"], fixture["bundle_raw"], {"X-Bundle-SHA256": fixture["bundle_sha256"]})
            self.assertEqual(code, 200)
            self.assertEqual(before, private_hashes(root))
            with fake_worker(manager):
                code, created = request("POST", "/api/bundle-workspace-create", create_request(preview))
                self.assertEqual((code, created["status"]), (200, "PREPARING"))
                code, listing = request("GET", "/api/bundle-workspaces")
                self.assertEqual(code, 200)
                self.assertEqual(listing["workspaces"][0]["id"], created["id"])
                code, value = request("GET", "/api/bundle-workspace/" + created["id"])
                self.assertEqual((code, value["owned_active"]), (200, True))

    def test_http_guard_binary_bounds_and_json_create_shapes(self):
        with workspace_http_fixture() as (root, manager, fixtures, request):
            fixture, before = fixtures["python"], private_hashes(root)
            path = "/api/bundle-workspace-preview/" + fixture["project_id"]
            cases = [({"Host": "malicious.invalid"}, "HOST_REFUSED"), ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                     ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"), ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED"),
                     ({"Content-Type": "application/json"}, "PROJECT_CHECK_INPUT"), ({"Content-Length": "2097153"}, "PROJECT_CHECK_LIMIT"),
                     ({"Content-Length": "0"}, "PROJECT_CHECK_INPUT"), ({"Content-Length": str(len(fixture["bundle_raw"]) + 1)}, "PROJECT_CHECK_INPUT"),
                     ({"Transfer-Encoding": "chunked"}, "PROJECT_CHECK_INPUT"), ([("Content-Length", str(len(fixture["bundle_raw"])))], "PROJECT_CHECK_INPUT")]
            with preview_guard(manager):
                for headers, reason in cases:
                    with self.subTest(reason=reason):
                        code, value = request("POST", path, fixture["bundle_raw"], headers)
                        self.assertEqual((code, value["error"]), (409, reason))
            self.assertEqual(before, private_hashes(root))
            with preview_guard(manager):
                preview = manager.bundle_workspace_preview(fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"])
            with fake_worker(manager) as (_, launch):
                code, value = request("POST", "/api/bundle-workspace-create", {**create_request(preview), "path": "/fictional/outside"})
                self.assertEqual((code, value["error"]), (409, "BUNDLE_WORKSPACE_FIELDS"))
                for headers in [{"Transfer-Encoding": "chunked"}, [("Content-Length", str(len(canonical(create_request(preview)))) )]]:
                    code, value = request("POST", "/api/bundle-workspace-create", create_request(preview), headers)
                    self.assertEqual(code, 409)
                launch.assert_not_called()
            for endpoint, method, body in [("create", "bundle_workspace_create", create_request(preview)),
                                            ("stop", "bundle_workspace_stop", {"id": "1111111111111111"})]:
                with self.subTest(short_complete_json=endpoint), patch.object(manager, method, side_effect=AssertionError("short body invoked manager")) as invoke:
                    code, value = request("POST", "/api/bundle-workspace-" + endpoint, body,
                                          {"Content-Length": str(len(canonical(body)) + 1)})
                    self.assertEqual((code, value["error"]), (409, "BUNDLE_WORKSPACE_INPUT"))
                    invoke.assert_not_called()
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()

