"""Read-only snapshot-packet/project inspection over invented saved workspaces."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from test_bundle_workspace_integration import private_hashes
from test_snapshot_export_integration import populate_snapshot_exports, snapshot_export_guard
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-snapshot-project-check-sentinel"


def populate_snapshot_project_checks(manager, root, languages=("python", "java", "mixed")):
    """Prepare invented packets before guards, without real checks or inference."""
    from snapshot_export import prepare
    fixtures = populate_snapshot_exports(manager, root, languages)
    for fixture in fixtures.values():
        raw = prepare(fixture["attempt_dir"])["archive"]
        fixture.update(archive_raw=raw, archive_sha256=sha(raw))
    hold = manager.data / "state/hold.json"
    write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": PRIVATE_SENTINEL, "turn": 1}))
    return fixtures


@contextmanager
def project_check_fixture(languages=("python",)):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        fixtures = populate_snapshot_project_checks(manager, root, languages)
        try:
            yield root, manager, fixtures
        finally:
            manager.close()


@contextmanager
def saved_only_guard(manager):
    with snapshot_export_guard(manager), ExitStack() as stack:
        for name in ["snapshot_export_preview", "snapshot_export_accept", "snapshot_export_download", "snapshot_export_history",
                     "bundle_project_check", "bundle_workspace_preview", "recheck_preview", "readiness_admission",
                     "comparison_history", "compare"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("snapshot project check reached " + name)))
        stack.enter_context(patch("workbench.readiness_presence", side_effect=AssertionError("executable probe")))
        stack.enter_context(patch("zipfile.ZipFile.extract", side_effect=AssertionError("archive extraction")))
        stack.enter_context(patch("zipfile.ZipFile.extractall", side_effect=AssertionError("archive extraction")))
        yield


def stage_tested(fixture, names=None):
    """Intentionally change only invented project bytes between inspections."""
    task = json.loads(fixture["task"].read_bytes())
    for name in names if names is not None else task["files"]:
        (fixture["source"] / name).write_bytes((fixture["attempt_dir"] / "snapshot" / name).read_bytes())


def stage_task(manager, fixture, task):
    raw = canonical(task)
    fixture["task"].write_bytes(raw)
    manager.projects[fixture["project_id"]].update(task_raw=raw, definition=copy.deepcopy(task))


class SnapshotProjectCheckIntegrationTests(unittest.TestCase):
    def inspect(self, root, manager, fixture, status):
        before = private_hashes(root)
        with saved_only_guard(manager):
            result = manager.snapshot_project_check(fixture["project_id"], fixture["archive_raw"], fixture["archive_sha256"])
        self.assertEqual(before, private_hashes(root))
        self.assertEqual(set(result), {"version", "project", "checked_at_ms", "config_sha256", "task_sha256", "comparison"})
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["project"]["id"], fixture["project_id"])
        self.assertEqual(result["config_sha256"], sha(manager.config_raw))
        self.assertEqual(result["task_sha256"], sha(manager.projects[fixture["project_id"]]["task_raw"]))
        self.assertEqual(result["comparison"]["status"], status)
        self.assertLessEqual(len(canonical(result)), 131072)
        self.assertNotIn(str(root), json.dumps(result))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result))
        return result["comparison"]

    def refused(self, root, operation, *args, codes=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(*args)
        reason = str(caught.exception)
        self.assertRegex(reason, r"^[A-Z][A-Z_]+$")
        if codes: self.assertIn(reason, codes)
        self.assertNotIn(PRIVATE_SENTINEL, reason)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_baseline_has_forward_reconstruction_and_tested_has_no_reverse_claim(self):
        with project_check_fixture(("python", "java")) as (root, manager, fixtures):
            self.assertIsNone(manager.jdk_home)
            hold = (manager.data / "state/hold.json").read_bytes()
            for language, fixture in fixtures.items():
                with self.subTest(language=language):
                    report = self.inspect(root, manager, fixture, "BASELINE_MATCH")
                    self.assertEqual(report["reconstruction"]["status"], "VERIFIED")
                    stage_tested(fixture)
                    report = self.inspect(root, manager, fixture, "TESTED_MATCH")
                    self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")
            self.assertEqual(hold, (manager.data / "state/hold.json").read_bytes())

    def test_mixed_different_and_missing_are_observations_without_reconstruction(self):
        with project_check_fixture(("mixed",)) as (root, manager, fixtures):
            fixture = fixtures["mixed"]
            stage_tested(fixture, ["addition.py"])
            report = self.inspect(root, manager, fixture, "MIXED_MATCH")
            self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")
            path = fixture["source"] / "addition.py"
            path.write_bytes(path.read_bytes() + b"# intentional different source\n")
            self.inspect(root, manager, fixture, "DIFFERENT")
            (fixture["source"] / "test_mixed.py").unlink()
            self.inspect(root, manager, fixture, "NEEDS_INSPECTION")

    def test_unknown_projects_and_invalid_input_are_bounded_refusals(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with saved_only_guard(manager):
                for project in [None, "../" + PRIVATE_SENTINEL, "missing_project"]:
                    self.refused(root, manager.snapshot_project_check, project, fixture["archive_raw"])
                for raw in [None, "private text", bytearray(b"zip"), b"", b"x" * (2097152 + 1)]:
                    self.refused(root, manager.snapshot_project_check, fixture["project_id"], raw)
                for expected in [False, "", "A" * 64, "0" * 64]:
                    self.refused(root, manager.snapshot_project_check, fixture["project_id"], fixture["archive_raw"], expected)

    def test_invalid_archive_is_rejected_before_task_or_source_reads(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with saved_only_guard(manager), patch("workbench.readiness_read_file", side_effect=AssertionError("invalid archive read local task/config")), \
                    patch("snapshot_project_check.read_selected", side_effect=AssertionError("invalid archive read source")):
                self.refused(root, manager.snapshot_project_check, fixture["project_id"], b"invalid-private-zip")

    def test_config_or_task_drift_skips_selected_source_reads(self):
        for mode in ["config", "task"]:
            with self.subTest(mode=mode), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                path = manager.config_path if mode == "config" else fixture["task"]
                path.write_bytes(path.read_bytes() + b" \n")
                with saved_only_guard(manager), patch("snapshot_project_check.read_selected", side_effect=AssertionError("drifted project read source")):
                    self.refused(root, manager.snapshot_project_check, fixture["project_id"], fixture["archive_raw"])

    def test_approved_profile_differences_skip_all_source_and_never_claim_reconstruction(self):
        for mode, flag in [("scope", "scope"), ("permissions", "permissions"), ("checks", "checks"), ("budgets", "budgets")]:
            with self.subTest(mode=mode), project_check_fixture(("mixed",)) as (root, manager, fixtures):
                fixture = fixtures["mixed"]
                task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
                if mode == "scope":
                    task["files"]["invented_extra.py"] = sha(PRIVATE_SENTINEL.encode())
                    write_new(fixture["source"] / "invented_extra.py", PRIVATE_SENTINEL.encode())
                elif mode == "permissions": task["editable"].remove("increment.py")
                elif mode == "checks": task["checks"] = {"other_checks": next(iter(task["checks"].values()))}
                else: task["max_turns"] += 1
                stage_task(manager, fixture, task)
                with patch("snapshot_project_check.read_selected", side_effect=AssertionError("profile mismatch read source")):
                    report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")
                self.assertIs(report["profile"][flag], False)
                self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")
                if mode == "permissions":
                    self.assertEqual(report["permission_differences"], [{"path": "increment.py", "archive_editable": True, "project_editable": False}])

    def test_goal_text_is_explicitly_unassessed_without_blocking_exact_profile(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
            task["goal"] = PRIVATE_SENTINEL + " different approved goal"
            stage_task(manager, fixture, task)
            report = self.inspect(root, manager, fixture, "BASELINE_MATCH")
            self.assertEqual(report["reconstruction"]["status"], "VERIFIED")
            self.assertIn("TASK_GOAL", report["not_checked"])

    def test_unsafe_selected_files_and_ancestors_are_unknown_observations(self):
        for mode in ["symlink", "hardlink", "root"]:
            with self.subTest(mode=mode), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                outside = root / "outside-source"; outside.mkdir()
                write_new(outside / "sentinel", PRIVATE_SENTINEL.encode())
                if mode == "root":
                    fixture["source"].rename(root / "retained-source")
                    fixture["source"].symlink_to(outside, target_is_directory=True)
                else:
                    path = fixture["source"] / "arithmetic.py"
                    other = outside / "arithmetic.py"; other.write_bytes(path.read_bytes()); path.unlink()
                    path.symlink_to(other) if mode == "symlink" else path.hardlink_to(other)
                report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")
                self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")

    def test_binary_invalid_utf8_and_oversized_source_are_bounded_and_read_only(self):
        for raw, reason in [(b"\x00" + PRIVATE_SENTINEL.encode(), "BINARY_INPUT"), (b"\xff", "INVALID_UTF8"), (b"x" * 32769, "FILE_LIMIT")]:
            with self.subTest(reason=reason), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                (fixture["source"] / "arithmetic.py").write_bytes(raw)
                report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")
                self.assertIn(reason, report["reasons"])
                self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")

    def test_source_drift_between_forward_reconstruction_reads_is_detected(self):
        import snapshot_project_check
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            original = snapshot_project_check.read_selected
            counts = {}
            def read_changed(source, name, limit=32768):
                counts[name] = counts.get(name, 0) + 1
                raw = original(source, name, limit)
                return raw + b"# simulated second observation\n" if name == "arithmetic.py" and counts[name] > 1 else raw
            with patch("snapshot_project_check.read_selected", side_effect=read_changed):
                report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")
            self.assertIn("OBSERVATION_CHANGED", report["reasons"])
            self.assertEqual(report["reconstruction"]["status"], "REFUSED")
            self.assertEqual(report["reconstruction"]["files_checked"], 0)

    def test_config_or_task_change_during_helper_read_refuses_wrapper_without_overwriting_it(self):
        import snapshot_project_check
        for mode in ["config", "task"]:
            with self.subTest(mode=mode), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                original = snapshot_project_check.read_selected
                owner_path = manager.config_path if mode == "config" else fixture["task"]
                owner_raw = owner_path.read_bytes() + b"\n"
                called = []
                def read_and_edit(source, name, limit=32768):
                    raw = original(source, name, limit)
                    if not called:
                        called.append(name); owner_path.write_bytes(owner_raw)
                    return raw
                original_hashes = private_hashes(root)
                with saved_only_guard(manager), patch("snapshot_project_check.read_selected", side_effect=read_and_edit):
                    with self.assertRaisesRegex(Refused, "^SNAPSHOT_PROJECT_PROJECT_CHANGED$"):
                        manager.snapshot_project_check(fixture["project_id"], fixture["archive_raw"])
                self.assertTrue(called)
                changed = private_hashes(root)
                owner_key = str(owner_path.relative_to(root))
                self.assertEqual({name: value for name, value in original_hashes.items() if name != owner_key},
                    {name: value for name, value in changed.items() if name != owner_key})
                self.assertEqual(owner_path.read_bytes(), owner_raw)

    def test_hash_consistent_but_wrong_patch_has_no_forward_proof(self):
        import snapshot_export
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            members = snapshot_export._members(fixture["archive_raw"])
            patch_raw = members["changes.diff"].replace(b"-    return a - b", b"-    return a / b", 1)
            self.assertNotEqual(patch_raw, members["changes.diff"])
            verification = json.loads(members["verification.json"])
            verification["hashes"]["patch_sha256"] = sha(patch_raw)
            parts = {"changes.diff": patch_raw, "verification.json": canonical(verification), "README.txt": members["README.txt"]}
            parts["SHA256SUMS"] = snapshot_export._checksums(parts)
            raw = snapshot_export._archive(parts)
            snapshot_export.verify_export(raw)  # Structural checks alone lack baseline bytes.
            changed = {**fixture, "archive_raw": raw, "archive_sha256": sha(raw)}
            report = self.inspect(root, manager, changed, "NEEDS_INSPECTION")
            self.assertEqual(report["reconstruction"]["status"], "REFUSED")
            self.assertEqual(report["reconstruction"]["reason"], "PATCH_INVALID")
            self.assertEqual(report["reconstruction"]["files_checked"], 0)

    def test_protected_drift_is_different_without_patch_applicability_claim(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            path = fixture["source"] / "test_arithmetic.py"
            path.write_bytes(path.read_bytes() + b"# intentional protected test drift\n")
            report = self.inspect(root, manager, fixture, "DIFFERENT")
            self.assertEqual(report["reconstruction"]["status"], "NOT_CHECKED")
            row = next(row for row in report["files"] if row["path"] == "test_arithmetic.py")
            self.assertIs(row["editable"], False)
            self.assertEqual(row["status"], "CHANGED")


@contextmanager
def snapshot_check_http_fixture():
    with project_check_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-snapshot-project-token", "http://127.0.0.1:8765")

        def request(raw, project_id, headers=None):
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-snapshot-project-token",
                "Origin": "http://127.0.0.1:8765", "Content-Type": "application/zip", "Content-Length": str(len(raw))}
            duplicate = headers if isinstance(headers, list) else []
            if isinstance(headers, dict): supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "POST", "/api/snapshot-project-check/" + project_id
            handler.request_version, handler.requestline = "HTTP/1.1", "POST " + handler.path + " HTTP/1.1"
            handler.headers = Message()
            for key, value in list(supplied.items()) + duplicate: handler.headers[key] = value
            handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
            handler.do_POST()
            head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            response = dict(line.decode().split(": ", 1) for line in head.split(b"\r\n")[1:])
            return int(head.split(b" ", 2)[1]), response, json.loads(body)

        yield root, manager, fixtures, request


class SnapshotProjectCheckHTTPTests(unittest.TestCase):
    def test_binary_upload_observes_saved_packet_without_writes(self):
        with snapshot_check_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]; before = private_hashes(root)
            with saved_only_guard(manager):
                for headers in [{}, {"X-Snapshot-SHA256": fixture["archive_sha256"]}]:
                    code, response, value = request(fixture["archive_raw"], fixture["project_id"], headers)
                    self.assertEqual(code, 200)
                    self.assertEqual(response["Content-Type"].split(";", 1)[0], "application/json")
                    self.assertEqual(value["comparison"]["status"], "BASELINE_MATCH")
                    self.assertEqual(value["comparison"]["reconstruction"]["status"], "VERIFIED")
                    self.assertNotIn(str(root), json.dumps(value))
            self.assertEqual(before, private_hashes(root))

    def test_binary_framing_and_hash_header_guards_precede_manager(self):
        with snapshot_check_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]; raw = fixture["archive_raw"]; before = private_hashes(root)
            with patch.object(manager, "snapshot_project_check", side_effect=AssertionError("bad HTTP reached manager")) as invoke:
                bad = [{"Content-Type": "application/json"}, [("Content-Type", "application/zip")],
                    {"Transfer-Encoding": "chunked"}, [("Content-Length", str(len(raw)))],
                    {"Content-Length": str(len(raw) + 1)}, {"Content-Length": "2097153"},
                    {"Content-Length": "0"}, {"Content-Length": "-1"}, {"X-Snapshot-SHA256": "A" * 64},
                    {"X-Snapshot-SHA256": "bad"}, [("X-Snapshot-SHA256", "a" * 64), ("X-Snapshot-SHA256", "a" * 64)]]
                for headers in bad:
                    with self.subTest(headers=headers):
                        code, _, value = request(raw, fixture["project_id"], headers)
                        self.assertEqual(code, 409)
                        self.assertIn(value["error"], {"SNAPSHOT_PROJECT_INPUT", "SNAPSHOT_PROJECT_LIMIT"})
                invoke.assert_not_called()
            self.assertEqual(before, private_hashes(root))

    def test_host_session_origin_fetch_and_wrong_digest_have_finite_errors(self):
        with snapshot_check_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]; before = private_hashes(root)
            with saved_only_guard(manager):
                for headers, reason in [({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                    ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"), ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"),
                    ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED"), ({"X-Snapshot-SHA256": "0" * 64}, "SNAPSHOT_EXPORT_ARCHIVE_CHANGED")]:
                    code, _, value = request(fixture["archive_raw"], fixture["project_id"], headers)
                    self.assertEqual((code, value["error"]), (409, reason))
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()
