"""Private-bundle/project inspection over invented sources; no runtime work."""

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
from test_patch_bundle_integration import (
    _seed_accepted_run, populate_bundle_runs, private_hashes,
    saved_only_guard as bundle_build_guard,
)
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-project-check-sentinel"
NOT_CHECKED = ["TASK_GOAL", "CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "PATCH_APPLICABILITY", "GIT_ADOPTION"]


@contextmanager
def saved_only_guard(manager):
    with bundle_build_guard(manager), ExitStack() as stack:
        for name in ["bundle_preview", "bundle_export", "_bundle_bytes", "_guarded_bundle",
                     "project_readiness", "readiness_admission", "comparison_history", "compare"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("project check reached " + name)))
        stack.enter_context(patch("workbench.readiness_presence", side_effect=AssertionError("executable presence probe")))
        stack.enter_context(patch("zipfile.ZipFile.extract", side_effect=AssertionError("extract")))
        stack.enter_context(patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extractall")))
        yield


def _install_mixed(manager, root):
    source = root / "mixed-project-source"
    source.mkdir(mode=0o700)
    before = {"addition.py": b"def add(a, b):\n    return a - b\n",
              "increment.py": b"def increment(n):\n    return n - 1\n",
              "test_mixed.py": b"import unittest\nfrom addition import add\nfrom increment import increment\nclass MixedTests(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2, 3), 5)\n    def test_negative(self): self.assertEqual(add(-2, -3), -5)\n    def test_increment(self): self.assertEqual(increment(4), 5)\n    def test_zero(self): self.assertEqual(increment(-1), 0)\n"}
    after = {**before, "addition.py": before["addition.py"].replace(b"a - b", b"a + b"),
             "increment.py": before["increment.py"].replace(b"n - 1", b"n + 1")}
    for name, raw in before.items():
        write_new(source / name, raw)
    draft = manager.project_preview({"id": "bundle_mixed", "name": "Invented mixed project check", "source": str(source),
        "language": "python", "files": list(before), "editable": ["addition.py", "increment.py"],
        "check": "test_mixed.py", "goal": PRIVATE_SENTINEL + " approved goal"})
    manager.project_save({"draft": draft["draft"]})
    return manager.projects["bundle_mixed"], before, after


def populate_project_check(manager, root):
    """Build private fixture bundles before inspector guards; save no archives.

    Returns python/java/mixed entries containing project_id, run_id, bundle_raw,
    bundle_sha256, source and task. All source/check histories are invented.
    """
    mixed = _install_mixed(manager, root)
    ids = populate_bundle_runs(manager, root)
    ids["mixed"] = "3333333333333333"
    _seed_accepted_run(manager, ids["mixed"], *mixed)
    fixtures = {}
    for language, run_id in ids.items():
        project_id = "bundle_" + language
        preview = manager.bundle_preview(run_id)
        raw = manager.bundle_export(run_id, preview["bundle_sha256"])
        fixtures[language] = {"project_id": project_id, "run_id": run_id,
            "bundle_raw": raw, "bundle_sha256": preview["bundle_sha256"],
            "source": manager.projects[project_id]["source"], "task": manager.projects[project_id]["task"]}
    return fixtures


@contextmanager
def project_check_fixture():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        fixtures = populate_project_check(manager, root)
        try:
            yield root, manager, fixtures
        finally:
            manager.close()


def stage_candidate(manager, fixture, names=None):
    """Intentional fixture edit between observations; never applies/extracts ZIPs."""
    names = names if names is not None else manager.projects[fixture["project_id"]]["definition"]["files"]
    for name in names:
        (fixture["source"] / name).write_bytes((manager.run_path(fixture["run_id"]) / "work" / name).read_bytes())


def stage_approved_task(manager, fixture, task):
    """Model a separately loaded approved task revision in an isolated fixture."""
    raw = canonical(task)
    fixture["task"].write_bytes(raw)
    manager.projects[fixture["project_id"]]["task_raw"] = raw
    manager.projects[fixture["project_id"]]["definition"] = copy.deepcopy(task)


class ProjectCheckIntegrationTests(unittest.TestCase):
    def inspect(self, root, manager, fixture, expected=None):
        before = private_hashes(root)
        hold_raw = (manager.data / "state/hold.json").read_bytes()
        with saved_only_guard(manager):
            value = manager.bundle_project_check(fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"])
        self.assertEqual(before, private_hashes(root))
        self.assertEqual((manager.data / "state/hold.json").read_bytes(), hold_raw)
        self.assertEqual(set(value), {"version", "project", "checked_at_ms", "config_sha256", "task_sha256", "comparison"})
        self.assertEqual(value["project"]["id"], fixture["project_id"])
        self.assertEqual(value["config_sha256"], sha(manager.config_raw))
        self.assertEqual(value["task_sha256"], sha(manager.projects[fixture["project_id"]]["task_raw"]))
        report = value["comparison"]
        self.assertEqual(report["not_checked"], NOT_CHECKED)
        self.assertNotIn(str(root), json.dumps(value))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))
        self.assertLessEqual(len(canonical(value)), 131072)
        self.assertLessEqual(len(canonical(report)), 65536)
        if expected is not None:
            self.assertEqual(report["status"], expected)
        return value

    def assert_refused(self, root, manager, project, raw, pin=None, codes=None):
        before = private_hashes(root)
        with saved_only_guard(manager), self.assertRaises(Refused) as caught:
            manager.bundle_project_check(project, raw, pin)
        code = str(caught.exception)
        self.assertRegex(code, r"^(PROJECT_CHECK|BUNDLE)_[A-Z_]{1,48}$")
        if codes:
            self.assertIn(code, codes)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_baseline_checks_are_read_only_under_unrelated_hold(self):
        import workbench
        with project_check_fixture() as (root, manager, fixtures):
            self.assertIsNone(manager.jdk_home)
            reader = workbench.readiness_read_file
            for language in ["python", "java"]:
                fixture = fixtures[language]
                allowed = {manager.config_path, fixture["task"]}

                def only_config_and_task(directory, name, *args, **kwargs):
                    self.assertIn(Path(directory) / name, allowed)
                    return reader(directory, name, *args, **kwargs)

                with self.subTest(language=language), patch("workbench.readiness_read_file", side_effect=only_config_and_task):
                    value = self.inspect(root, manager, fixture, "BASELINE_MATCH")
                report = value["comparison"]
                self.assertTrue(all(report["profile"].values()))
                self.assertTrue(report["task_pins_match"])
                self.assertTrue(all(row["status"] in ["BASELINE", "UNCHANGED"] for row in report["files"]))
                self.assertEqual(report["total_bytes"], sum(row["bytes"] for row in report["files"]))
                self.assertEqual(set(report["notes"]), {"PRIVATE_PROJECT_INFORMATION", "STATIC_OBSERVATIONS_ONLY", "UNSIGNED_BUNDLE"})

    def test_candidate_source_matches_even_when_configured_pins_still_name_baseline(self):
        with project_check_fixture() as (root, manager, fixtures):
            for language in ["python", "java"]:
                with self.subTest(language=language):
                    fixture = fixtures[language]
                    stage_candidate(manager, fixture)
                    report = self.inspect(root, manager, fixture, "CANDIDATE_MATCH")["comparison"]
                    self.assertFalse(report["task_pins_match"])
                    self.assertTrue(any(row["status"] == "CANDIDATE" and row["task_pin_match"] is False for row in report["files"]))

    def test_genuine_mixed_baseline_candidate_observation_is_explicit(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["mixed"]
            stage_candidate(manager, fixture, ["addition.py"])
            report = self.inspect(root, manager, fixture, "MIXED_MATCH")["comparison"]
            self.assertEqual({row["status"] for row in report["files"]}, {"BASELINE", "CANDIDATE", "UNCHANGED"})
            self.assertIn("MIXED_BASELINE_CANDIDATE", report["reasons"])

    def test_later_configured_candidate_or_other_pins_do_not_change_profile_comparison(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            stage_candidate(manager, fixture)
            task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
            task["files"] = {name: sha((fixture["source"] / name).read_bytes()) for name in task["files"]}
            task["goal"] = "A separately approved goal absent from the archive."
            stage_approved_task(manager, fixture, task)
            report = self.inspect(root, manager, fixture, "CANDIDATE_MATCH")["comparison"]
            self.assertTrue(report["task_pins_match"])
            self.assertTrue(all(report["profile"].values()))
            task["files"] = {name: "0" * 64 for name in task["files"]}
            stage_approved_task(manager, fixture, task)
            report = self.inspect(root, manager, fixture, "CANDIDATE_MATCH")["comparison"]
            self.assertFalse(report["task_pins_match"])
            self.assertTrue(all(report["profile"].values()))

    def test_arbitrary_and_protected_source_drift_are_different(self):
        for protected in [False, True]:
            with self.subTest(protected=protected), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                name = "test_arithmetic.py" if protected else "arithmetic.py"
                path = fixture["source"] / name
                path.write_bytes(path.read_bytes() + b"# intentional unrelated fixture change\n")
                report = self.inspect(root, manager, fixture, "DIFFERENT")["comparison"]
                row = next(row for row in report["files"] if row["path"] == name)
                self.assertEqual(row["status"], "CHANGED")
                self.assertEqual(row["editable"], not protected)
                self.assertIn("SOURCE_CHANGED", report["reasons"])

    def test_missing_unsafe_binary_utf8_and_limited_source_never_match(self):
        for mode, status, reason in [("missing", "MISSING", "SOURCE_MISSING"), ("symlink", "UNREADABLE", "SOURCE_UNREADABLE"),
                                     ("hardlink", "UNREADABLE", "SOURCE_UNREADABLE"), ("binary", "BINARY", "BINARY_INPUT"),
                                     ("utf8", "UTF8", "INVALID_UTF8"), ("limit", "LIMIT", "FILE_LIMIT")]:
            with self.subTest(mode=mode), project_check_fixture() as (root, manager, fixtures):
                fixture, name = fixtures["python"], "arithmetic.py"
                path = fixture["source"] / name
                if mode == "missing":
                    path.unlink()
                elif mode in ["symlink", "hardlink"]:
                    outside = root / "outside-selected.py"; outside.write_bytes(PRIVATE_SENTINEL.encode())
                    path.unlink()
                    if mode == "symlink":
                        path.symlink_to(outside)
                    else:
                        path.hardlink_to(outside)
                else:
                    path.write_bytes({"binary": b"invented\x00bytes", "utf8": b"invented\xffbytes", "limit": b"x" * 32769}[mode])
                report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")["comparison"]
                row = next(row for row in report["files"] if row["path"] == name)
                self.assertEqual(row["status"], status)
                self.assertIsNone(row["current_sha256"])
                self.assertIsNone(row["bytes"])
                self.assertIsNone(row["task_pin_match"])
                self.assertIsNone(report["total_bytes"])
                self.assertIn(reason, report["reasons"])

    def test_selected_source_ancestors_and_unselected_files_are_guarded(self):
        import bundle_project_check
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["java"]
            (fixture["source"] / "unselected.txt").write_text(PRIVATE_SENTINEL)
            read, selected = bundle_project_check.read_selected, []

            def declared_only(directory, name, *args, **kwargs):
                self.assertIn(name, manager.projects[fixture["project_id"]]["definition"]["files"])
                selected.append(name)
                return read(directory, name, *args, **kwargs)

            with patch("bundle_project_check.read_selected", side_effect=declared_only):
                self.inspect(root, manager, fixture, "BASELINE_MATCH")
            self.assertEqual(set(selected), set(manager.projects[fixture["project_id"]]["definition"]["files"]))
            directory = fixture["source"] / "sample"
            directory.rename(root / "retained-java-source")
            outside = root / "outside-java-source"; outside.mkdir()
            for name in ["Sum.java", "SumTest.java"]:
                (outside / name).write_text(PRIVATE_SENTINEL)
            directory.symlink_to(outside, target_is_directory=True)
            report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")["comparison"]
            self.assertTrue(all(row["status"] == "UNREADABLE" for row in report["files"]))

    def test_every_profile_difference_skips_all_source_reads(self):
        for mode, flag, reason in [("format", "format", "FORMAT_MISMATCH"), ("extra", "scope", "SCOPE_MISMATCH"),
                                   ("replacement", "scope", "SCOPE_MISMATCH"), ("permissions", "permissions", "PERMISSIONS_MISMATCH"),
                                   ("checks", "checks", "CHECKS_MISMATCH"), ("budgets", "budgets", "BUDGETS_MISMATCH")]:
            with self.subTest(mode=mode), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["mixed" if mode == "permissions" else "python"]
                task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
                if mode == "format":
                    task["format"] = "outlands-coding-agent-v1"
                    task["checks"] = {"unit": "test_arithmetic.py"}
                elif mode == "extra":
                    task["files"]["unselected_missing.py"] = "0" * 64
                elif mode == "replacement":
                    del task["files"]["arithmetic.py"]
                    task["files"]["replacement_missing.py"] = "0" * 64
                    task["editable"] = ["replacement_missing.py"]
                elif mode == "permissions":
                    task["editable"] = ["addition.py"]
                elif mode == "checks":
                    task["checks"] = {"different": task["checks"]["unit"]}
                else:
                    task["max_turns"] -= 1
                stage_approved_task(manager, fixture, task)
                with patch("bundle_project_check.read_selected", side_effect=AssertionError("profile mismatch read source")):
                    report = self.inspect(root, manager, fixture, "NEEDS_INSPECTION")["comparison"]
                self.assertIs(report["profile"][flag], False)
                self.assertIn(reason, report["reasons"])
                self.assertTrue(all(row["status"] in ["NOT_CHECKED", "OUT_OF_SCOPE"] and row["current_sha256"] is None for row in report["files"]))
                if mode == "extra":
                    self.assertEqual(report["project_only"], ["unselected_missing.py"])
                elif mode == "replacement":
                    self.assertEqual(report["bundle_only"], ["arithmetic.py"])
                    self.assertEqual(report["project_only"], ["replacement_missing.py"])
                    self.assertEqual(next(row for row in report["files"] if row["path"] == "arithmetic.py")["status"], "OUT_OF_SCOPE")
                elif mode == "permissions":
                    self.assertIn({"path": "increment.py", "bundle_editable": True, "project_editable": False}, report["permission_differences"])

    def test_raw_config_or_task_drift_and_invalid_task_skip_source(self):
        for mode in ["config", "task", "invalid_task"]:
            with self.subTest(mode=mode), project_check_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                if mode == "invalid_task":
                    task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
                    task["editable"] = ["test_arithmetic.py"]
                    stage_approved_task(manager, fixture, task)
                else:
                    path = manager.config_path if mode == "config" else fixture["task"]
                    path.write_bytes(path.read_bytes() + b" \n")
                with patch("bundle_project_check.read_selected", side_effect=AssertionError("task/config drift read source")):
                    self.assert_refused(root, manager, fixture["project_id"], fixture["bundle_raw"], fixture["bundle_sha256"],
                        codes={"PROJECT_CHECK_TASK_INVALID"} if mode == "invalid_task" else {"PROJECT_CHECK_PROJECT_CHANGED"})

    def test_archive_and_input_refusals_happen_before_selected_source_reads(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            with patch("bundle_project_check.read_selected", side_effect=AssertionError("invalid input read source")):
                for raw in [None, b"", bytearray(fixture["bundle_raw"]), b"invalid private archive", fixture["bundle_raw"] + b"trailing", b"x" * 2097153]:
                    with self.subTest(kind=type(raw).__name__, length=len(raw) if raw is not None else None):
                        self.assert_refused(root, manager, fixture["project_id"], raw)
                self.assert_refused(root, manager, fixture["project_id"], fixture["bundle_raw"], "0" * 64, codes={"BUNDLE_CHANGED"})
                for pin in ["bad", "A" * 64, True]:
                    with self.subTest(pin=pin):
                        self.assert_refused(root, manager, fixture["project_id"], fixture["bundle_raw"], pin, codes={"BUNDLE_HASH_REQUIRED"})

    def test_optional_pin_and_unknown_projects_do_not_create_records(self):
        with project_check_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            before = private_hashes(root)
            with saved_only_guard(manager):
                report = manager.bundle_project_check(fixture["project_id"], fixture["bundle_raw"])["comparison"]
            self.assertEqual(report["bundle_sha256"], fixture["bundle_sha256"])
            self.assertEqual(before, private_hashes(root))
            with patch("bundle_project_check.read_selected", side_effect=AssertionError("unknown project read source")):
                for project in [None, "missing", "../outside"]:
                    with self.subTest(project=project):
                        self.assert_refused(root, manager, project, fixture["bundle_raw"], codes={"PROJECT_CHECK_PROJECT_UNKNOWN"})

    def test_true_known_total_above_eligibility_limit_is_shown_and_blocks_match(self):
        from patch_bundle import build_bundle
        with project_check_fixture() as (root, _, _):
            source = root / "large-project-source"; source.mkdir()
            names = ["arithmetic.py", "extra_a.py", "extra_b.py", "extra_c.py", "test_arithmetic.py"]
            before = {name: b"# old" + b"x" * 32762 + b"\n" for name in names}
            after = {**before, "arithmetic.py": before["arithmetic.py"].replace(b"# old", b"# new", 1)}
            for name, raw in before.items():
                write_new(source / name, raw)
            task = {"format": "outlands-coding-agent-v2", "goal": "Inspect invented oversized selected files.",
                    "files": {name: sha(raw) for name, raw in before.items()}, "editable": ["arithmetic.py"],
                    "checks": {"unit": {"kind": "python-unittest", "pattern": "test_arithmetic.py"}},
                    "max_turns": 12, "request_seconds": 120}
            task_path, config = root / "large-task.json", root / "large-config.json"
            write_new(task_path, canonical(task))
            write_new(config, canonical({"format": "outlands-workbench-config-v1", "models": [], "projects": [
                {"id": "large", "name": "Invented source total", "source": str(source), "task": str(task_path)}]}))
            other = Manager(config, root / "large-data")
            try:
                run_id = "aaaaaaaaaaaaaaaa"
                _seed_accepted_run(other, run_id, other.projects["large"], before, after)
                run = other.run_path(run_id)
                raw = build_bundle((other.data / "tasks" / (run_id + ".json")).read_bytes(), (run / "result.json").read_bytes(),
                    (run / "review-000.json").read_bytes(), (run / "event-001.json").read_bytes(), (run / "changes.diff").read_bytes())
                write_new(other.data / "state/hold.json", canonical({"state": "REQUEST_UNSETTLED", "run": "invented unrelated", "turn": 1}))
                fixture = {"project_id": "large", "bundle_raw": raw, "bundle_sha256": sha(raw), "source": source, "task": task_path}
                report = self.inspect(root, other, fixture, "NEEDS_INSPECTION")["comparison"]
                self.assertEqual(report["total_bytes"], 163840)
                self.assertTrue(all(row["bytes"] == 32768 for row in report["files"]))
                self.assertIn("TOTAL_INPUT_LIMIT", report["reasons"])
            finally:
                other.close()


@contextmanager
def project_check_http_fixture():
    with project_check_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-project-check-token", "http://127.0.0.1:8765")

        def request(project, body, headers=None):
            body = body if body is not None else b""
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-project-check-token",
                        "Origin": "http://127.0.0.1:8765", "Content-Type": "application/zip", "Content-Length": str(len(body))}
            duplicate = headers if isinstance(headers, list) else []
            if isinstance(headers, dict):
                supplied.update(headers)
            path = "/api/bundle-project-check/" + project
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "POST", path
            handler.request_version, handler.requestline = "HTTP/1.1", "POST " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, value in list(supplied.items()) + duplicate:
                handler.headers[key] = value
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            handler.do_POST()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            lines = head.decode().split("\r\n")
            returned = {key.lower(): value.strip() for key, value in (line.split(":", 1) for line in lines[1:])}
            return int(lines[0].split(" ")[1]), returned, json.loads(raw)

        yield root, manager, fixtures, request


class ProjectCheckHTTPTests(unittest.TestCase):
    def test_raw_binary_post_is_read_only_json_no_store(self):
        with project_check_http_fixture() as (root, manager, fixtures, request):
            fixture, before = fixtures["python"], private_hashes(root)
            with saved_only_guard(manager):
                code, headers, value = request(fixture["project_id"], fixture["bundle_raw"],
                    {"X-Bundle-SHA256": fixture["bundle_sha256"], "X-File-Name": PRIVATE_SENTINEL})
            self.assertEqual(code, 200)
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertTrue(headers["content-type"].startswith("application/json"))
            self.assertEqual(value["comparison"]["status"], "BASELINE_MATCH")
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))
            self.assertEqual(before, private_hashes(root))

    def test_http_host_session_origin_and_cross_site_guards_preserve_tree(self):
        with project_check_http_fixture() as (root, manager, fixtures, request):
            fixture, before = fixtures["python"], private_hashes(root)
            with saved_only_guard(manager):
                for headers, reason in [({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                                        ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"),
                                        ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                    with self.subTest(reason=reason):
                        code, _, value = request(fixture["project_id"], fixture["bundle_raw"], headers)
                        self.assertEqual((code, value["error"]), (409, reason))
            self.assertEqual(before, private_hashes(root))

    def test_binary_mime_length_transfer_and_pin_guards_precede_source_reads(self):
        with project_check_http_fixture() as (root, manager, fixtures, request):
            fixture, before = fixtures["python"], private_hashes(root)
            cases = [({"Content-Type": "application/json"}, "PROJECT_CHECK_INPUT"),
                     ({"Content-Length": "0"}, "PROJECT_CHECK_INPUT"),
                     ({"Content-Length": "-1"}, "PROJECT_CHECK_INPUT"),
                     ({"Content-Length": "abc"}, "PROJECT_CHECK_INPUT"),
                     ({"Content-Length": "2097153"}, "PROJECT_CHECK_LIMIT"),
                     ({"Content-Length": str(len(fixture["bundle_raw"]) + 1)}, "PROJECT_CHECK_INPUT"),
                     ({"Transfer-Encoding": "chunked"}, "PROJECT_CHECK_INPUT"),
                     ({"X-Bundle-SHA256": "bad"}, "PROJECT_CHECK_INPUT"),
                     ({"X-Bundle-SHA256": "0" * 64}, "BUNDLE_CHANGED"),
                     ([("Content-Length", str(len(fixture["bundle_raw"])))], "PROJECT_CHECK_INPUT"),
                     ([("X-Bundle-SHA256", fixture["bundle_sha256"]), ("X-Bundle-SHA256", fixture["bundle_sha256"])] , "PROJECT_CHECK_INPUT")]
            with saved_only_guard(manager), patch("bundle_project_check.read_selected", side_effect=AssertionError("bad HTTP input read source")):
                for headers, reason in cases:
                    with self.subTest(reason=reason, headers=headers):
                        code, _, value = request(fixture["project_id"], fixture["bundle_raw"], headers)
                        self.assertEqual((code, value["error"]), (409, reason))
                code, _, value = request("missing", fixture["bundle_raw"])
                self.assertEqual((code, value["error"]), (409, "PROJECT_CHECK_PROJECT_UNKNOWN"))
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()

