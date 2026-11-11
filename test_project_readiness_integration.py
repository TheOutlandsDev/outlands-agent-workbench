"""Static-readiness fixtures and controller/HTTP tests; no checks or providers."""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, sha, write_new
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-readiness-sentinel"
NOT_CHECKED = {
    "PROVIDER_AVAILABILITY", "CHECK_EXECUTION", "ISOLATION_CAPABILITY", "JAVA_VERSION",
    "MODEL_CONTEXT_FIT", "PROCESS_OWNERSHIP", "WORKSPACE_FRESHNESS", "SOURCE_CORRECTNESS",
}


def install_java_project(root, manager):
    """Configure invented Java files and unexecuted executable-presence stubs.

    Returns the source Path for project ID ``java``. The caller can obtain its
    task path from manager.projects and the fictional JDK from manager.jdk_home.
    """
    source, jdk = root / "invented-java", root / "invented-jdk"
    (source / "sample").mkdir(parents=True)
    (jdk / "bin").mkdir(parents=True)
    (source / "sample/Counter.java").write_bytes(b"package sample; class Counter { int next(int n) { return n + 1; } }\n")
    (source / "sample/CounterTest.java").write_bytes(b"package sample; class CounterTest { public static void main(String[] args) {} }\n")
    for name in ["java", "javac"]:
        path = jdk / "bin" / name
        path.write_bytes(b"invented presence fixture: must never be executed\n")
        path.chmod(0o700)
    manager.jdk_home = jdk
    request = {"id": "java", "name": "Invented Java readiness", "source": str(source),
               "language": "java", "files": ["sample/Counter.java", "sample/CounterTest.java"],
               "editable": ["sample/Counter.java"], "check": "sample.CounterTest",
               "goal": "Inspect this invented Java task statically."}
    candidate = manager.project_preview(request)
    manager.project_save({"draft": candidate["draft"]})
    return source


@contextmanager
def readiness_fixture(java=False):
    """Yield (temporary root, Manager, selected ID) without execution or holds."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", "invented-local-model")
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        if java:
            install_java_project(root, manager)
        project = "java" if java else "arithmetic"
        try:
            yield root, manager, project
        finally:
            manager.close()


def readiness_hashes(root):
    return {path.relative_to(root).as_posix(): sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


@contextmanager
def readiness_guard(manager):
    """Fail if advisory inspection reaches a live-state or execution path."""
    with ExitStack() as stack:
        for name in ["history", "refresh", "admission", "owns_active", "request_hold", "workspace_receipt",
                     "start", "stop", "create_workspace", "project_refresh_preview", "project_refresh_save"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("readiness reached " + name)))
        for name in ["workbench.process_stamp", "workbench.subprocess.Popen", "workbench.subprocess.run",
                     "agent.Session.checks", "agent.Ollama.request", "agent.Ollama.preflight",
                     "agent.ScriptedDemo.request", "isolation.check", "java_check.check",
                     "http.client.HTTPConnection", "socket.socket"]:
            stack.enter_context(patch(name, side_effect=AssertionError("readiness reached " + name)))
        yield


# Shared with the parent's offline acceptance and persistent preview helpers.
private_hashes = readiness_hashes
saved_only_guard = readiness_guard


def seed_readiness_job(manager, run_id="1111111111111111", state="FAILED", workspace=None, padding=0):
    """Write invented saved admission records directly, without running work."""
    project = manager.projects["arithmetic"]
    metadata = {"id": run_id, "project": "arithmetic", "project_name": "Invented saved task",
                "source": str(project["source"]), "goal": project["definition"]["goal"],
                "backend": "ollama", "model": "invented-local-model", "state": state,
                "created": 1, "pid": 99999999, "process_stamp": PRIVATE_SENTINEL,
                "private_extra": PRIVATE_SENTINEL + "x" * padding}
    write_new(manager.meta_path(run_id), canonical(metadata))
    if workspace is not None:
        run = manager.run_path(run_id)
        run.mkdir(mode=0o700)
        write_new(run / "git-workspace.json", canonical(workspace))
    return run_id


def completed_workspace():
    return {"status": "VERIFIED", "source_applied": False, "patch_applied_to_workspace": True,
            "result_sha256": "a" * 64, "patch_sha256": "b" * 64,
            "baseline_commit": "c" * 40, "branch": "review/invented",
            "path": "/fictional/private/workspace", "finished": 1,
            "checks": {"unit": {"exit_code": 0, "tests_ran": 4, "timed_out": False,
                                  "output_limited": False, "infrastructure_error": False,
                                  "output": PRIVATE_SENTINEL}}}


class ReadinessIntegrationTests(unittest.TestCase):
    def observe(self, root, manager, project="arithmetic", presence=None):
        """Default unit tests synthesize presence; parent acceptance probes real tools."""
        before = readiness_hashes(root)
        with readiness_guard(manager), patch("workbench.readiness_presence", side_effect=presence or (lambda _: True)):
            value = manager.project_readiness(project)
        self.assertEqual(before, readiness_hashes(root))
        self.assertLessEqual(len(canonical(value)), 131072)
        self.assertEqual(set(value["not_checked"]), NOT_CHECKED)
        self.assertNotIn(str(root), json.dumps(value))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))
        return value

    def test_python_static_pass_preserves_exact_fingerprints_scope_and_all_files(self):
        with readiness_fixture() as (root, manager, project):
            definition = manager.projects[project]["definition"]
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            self.assertEqual(value["reasons"], [])
            self.assertEqual(value["fingerprints"]["config"], {"expected_sha256": sha(manager.config_raw), "sha256": sha(manager.config_path.read_bytes()), "status": "MATCH"})
            task_raw = manager.projects[project]["task"].read_bytes()
            self.assertEqual(value["fingerprints"]["task"], {"expected_sha256": sha(task_raw), "sha256": sha(task_raw), "status": "MATCH"})
            self.assertEqual(value["goal"], definition["goal"])
            self.assertEqual({row["path"]: row["expected_sha256"] for row in value["files"]}, definition["files"])
            self.assertTrue(all(row["status"] == "MATCH" for row in value["files"]))
            self.assertEqual({row["path"] for row in value["files"] if row["editable"]}, set(definition["editable"]))
            self.assertEqual(value["total_bytes"], sum(row["bytes"] for row in value["files"]))
            self.assertEqual(value["limits"], {"max_files": 32, "max_file_bytes": 32768, "max_total_bytes": 131072,
                                                "max_turns": definition["max_turns"], "request_seconds": definition["request_seconds"]})
            self.assertEqual(value["checks"], [{"name": name, "spec": spec} for name, spec in sorted(definition["checks"].items())])
            self.assertEqual(value["admission"]["hold"], "ABSENT")
            self.assertEqual(list((manager.data / "jobs").glob("*.json")), [])
            self.assertEqual(list((manager.data / "runs").iterdir()), [])

    def test_java_presence_is_checked_without_running_version_or_compiler(self):
        with readiness_fixture(java=True) as (root, manager, project):
            observed = []
            value = self.observe(root, manager, project, lambda path: observed.append(Path(path)) or True)
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            jdk = next(row for row in value["prerequisites"] if row["id"] == "jdk")
            self.assertEqual(jdk, {"id": "jdk", "required": True, "status": "AVAILABLE"})
            self.assertIn(manager.jdk_home / "bin/java", observed)
            self.assertIn(manager.jdk_home / "bin/javac", observed)
            self.assertEqual(value["checks"][0]["spec"]["main_class"], "sample.CounterTest")

    def test_changed_source_alone_requires_refresh_with_current_whole_file_hash(self):
        with readiness_fixture() as (root, manager, project):
            source = manager.projects[project]["source"]
            path = source / "calculator.py"
            old = path.read_bytes()
            current = old + "# invented café owner edit\r\n".encode()
            path.write_bytes(current)
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "REFRESH_REQUIRED")
            self.assertEqual(set(value["reasons"]), {"SOURCE_CHANGED"})
            row = next(row for row in value["files"] if row["path"] == "calculator.py")
            self.assertEqual((row["status"], row["expected_sha256"], row["sha256"], row["bytes"]), ("CHANGED", sha(old), sha(current), len(current)))

    def test_unselected_source_is_not_read_or_reported(self):
        import workbench
        with readiness_fixture() as (root, manager, project):
            source = manager.projects[project]["source"]
            (source / "unselected.txt").write_bytes(PRIVATE_SENTINEL.encode() + b"\x00\xff")
            real_read, names = workbench.readiness_read_file, []

            def scoped_read(directory, name, *args, **kwargs):
                if Path(directory) == source:
                    names.append(name)
                    self.assertIn(name, manager.projects[project]["definition"]["files"])
                return real_read(directory, name, *args, **kwargs)

            with patch("workbench.readiness_read_file", side_effect=scoped_read):
                value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            self.assertEqual(set(names), set(manager.projects[project]["definition"]["files"]))
            self.assertNotIn("unselected.txt", json.dumps(value))

    def test_config_and_task_raw_drift_skip_every_source_read(self):
        import workbench
        for section in ["config", "task"]:
            with self.subTest(section=section), readiness_fixture() as (root, manager, project):
                target = manager.config_path if section == "config" else manager.projects[project]["task"]
                original = target.read_bytes()
                changed = original + b" \n"
                target.write_bytes(changed)
                source = manager.projects[project]["source"]
                real_read = workbench.readiness_read_file

                def no_source(directory, name, *args, **kwargs):
                    self.assertFalse(Path(directory) == source or source in Path(directory).parents)
                    return real_read(directory, name, *args, **kwargs)

                with patch("workbench.readiness_read_file", side_effect=no_source):
                    value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("CONFIG_CHANGED" if section == "config" else "TASK_CHANGED", value["reasons"])
                self.assertEqual(value["fingerprints"][section], {"expected_sha256": sha(original), "sha256": sha(changed), "status": "CHANGED"})
                self.assertTrue(all(row["status"] == "NOT_CHECKED" and row["sha256"] is None and row["bytes"] is None for row in value["files"]))
                self.assertIsNone(value["total_bytes"])

    def test_missing_limited_and_unreadable_fingerprints_skip_source_reads(self):
        import workbench
        for section in ["config", "task"]:
            for failure in ["MISSING", "LIMIT", "UNREADABLE"]:
                with self.subTest(section=section, failure=failure), readiness_fixture() as (root, manager, project):
                    target = manager.config_path if section == "config" else manager.projects[project]["task"]
                    if failure == "MISSING":
                        target.unlink()
                    elif failure == "LIMIT":
                        target.write_bytes(b" " * 262145)
                    source, real_read = manager.projects[project]["source"], workbench.readiness_read_file

                    def no_source(directory, name, *args, **kwargs):
                        self.assertFalse(Path(directory) == source or source in Path(directory).parents)
                        if failure == "UNREADABLE" and Path(directory) / name == target:
                            raise PermissionError(PRIVATE_SENTINEL)
                        return real_read(directory, name, *args, **kwargs)

                    with patch("workbench.readiness_read_file", side_effect=no_source):
                        value = self.observe(root, manager, project)
                    self.assertEqual(value["status"], "NEEDS_INSPECTION")
                    self.assertEqual(value["fingerprints"][section]["status"], failure)
                    self.assertIsNone(value["fingerprints"][section]["sha256"])
                    self.assertTrue(all(row["status"] == "NOT_CHECKED" for row in value["files"]))

    def test_missing_oversized_binary_and_invalid_utf8_source_block(self):
        cases = [(None, "MISSING", "SOURCE_MISSING"), (b"x" * 32769, "LIMIT", "FILE_LIMIT"),
                 (b"invented\x00binary", "BINARY", "BINARY_INPUT"), (b"invented\xfftext", "UTF8", "INVALID_UTF8")]
        for raw, status, reason in cases:
            with self.subTest(status=status), readiness_fixture() as (root, manager, project):
                path = manager.projects[project]["source"] / "calculator.py"
                if raw is None:
                    path.unlink()
                else:
                    path.write_bytes(raw)
                value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "BLOCKED")
                self.assertIn(reason, value["reasons"])
                self.assertEqual(next(row for row in value["files"] if row["path"] == "calculator.py")["status"], status)
                self.assertIsNone(value["total_bytes"])

    def test_linked_source_files_are_refused_without_reading_outside_text(self):
        for linked in ["symlink", "hardlink"]:
            with self.subTest(linked=linked), readiness_fixture() as (root, manager, project):
                outside = root / "outside-selected.py"
                outside.write_bytes(PRIVATE_SENTINEL.encode())
                path = manager.projects[project]["source"] / "calculator.py"
                path.unlink()
                if linked == "symlink":
                    path.symlink_to(outside)
                else:
                    path.hardlink_to(outside)
                value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "BLOCKED")
                self.assertIn("SOURCE_UNREADABLE", value["reasons"])
                self.assertEqual(next(row for row in value["files"] if row["path"] == "calculator.py")["status"], "UNREADABLE")

    def test_substituted_java_source_directory_is_not_followed(self):
        with readiness_fixture(java=True) as (root, manager, project):
            source = manager.projects[project]["source"]
            (source / "sample").rename(root / "retained-sample")
            outside = root / "outside-sample"
            outside.mkdir()
            for name in ["Counter.java", "CounterTest.java"]:
                (outside / name).write_bytes(PRIVATE_SENTINEL.encode())
            (source / "sample").symlink_to(outside, target_is_directory=True)
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "BLOCKED")
            self.assertTrue(all(row["status"] == "UNREADABLE" for row in value["files"]))

    def test_total_source_limit_blocks_even_when_every_file_size_is_known(self):
        with readiness_fixture() as (root, manager, _):
            source = root / "large-selected"
            source.mkdir()
            names = ["module.py", "test_module.py"] + ["part" + str(i) + ".py" for i in range(4)]
            for name in names:
                (source / name).write_bytes(b"# invented initial text\n")
            request = {"id": "large", "name": "Invented aggregate limit", "source": str(source), "language": "python",
                       "files": names, "editable": ["module.py"], "check": "test_module.py", "goal": "Inspect selected bytes."}
            candidate = manager.project_preview(request)
            manager.project_save({"draft": candidate["draft"]})
            for name in names:
                (source / name).write_bytes(b"#" + b"x" * 23998 + b"\n")
            value = self.observe(root, manager, "large")
            self.assertEqual(value["status"], "BLOCKED")
            self.assertIn("TOTAL_INPUT_LIMIT", value["reasons"])
            self.assertEqual(value["total_bytes"], 144000)
            self.assertTrue(all(row["bytes"] == 24000 for row in value["files"]))

    def test_optional_git_absence_does_not_block_static_checks(self):
        with readiness_fixture() as (root, manager, project):
            value = self.observe(root, manager, project, lambda path: Path(path).name != "git")
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            self.assertEqual(next(row for row in value["prerequisites"] if row["id"] == "git"), {"id": "git", "required": False, "status": "MISSING"})
            self.assertNotIn("PREREQUISITE_MISSING", value["reasons"])

    def test_required_tool_absence_blocks_without_attempting_a_probe_process(self):
        with readiness_fixture() as (root, manager, project):
            value = self.observe(root, manager, project, lambda path: Path(path).name != "bwrap")
            self.assertEqual(value["status"], "BLOCKED")
            self.assertIn("PREREQUISITE_MISSING", value["reasons"])
            self.assertEqual(next(row for row in value["prerequisites"] if row["id"] == "bwrap")["status"], "MISSING")

    def test_java_not_configured_and_missing_tools_are_distinct(self):
        with readiness_fixture(java=True) as (root, manager, project):
            jdk = manager.jdk_home
            manager.jdk_home = None
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "BLOCKED")
            self.assertIn("JDK_NOT_CONFIGURED", value["reasons"])
            self.assertEqual(next(row for row in value["prerequisites"] if row["id"] == "jdk")["status"], "NOT_CONFIGURED")
            manager.jdk_home = jdk
            value = self.observe(root, manager, project, lambda path: Path(path) != jdk / "bin/javac")
            self.assertEqual(value["status"], "BLOCKED")
            self.assertIn("PREREQUISITE_MISSING", value["reasons"])
            self.assertNotIn("JDK_NOT_CONFIGURED", value["reasons"])

    def test_present_valid_hold_overrides_changed_source_and_is_preserved(self):
        with readiness_fixture() as (root, manager, project):
            source = manager.projects[project]["source"] / "calculator.py"
            source.write_bytes(source.read_bytes() + b"# invented edit\n")
            hold = manager.data / "state/hold.json"
            write_new(hold, canonical({"state": "REQUEST_UNSETTLED", "run": "/fictional/private/run", "turn": 1}))
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "BLOCKED")
            self.assertEqual(value["admission"]["hold"], "PRESENT")
            self.assertTrue({"SOURCE_CHANGED", "HOLD_PRESENT"} <= set(value["reasons"]))
            self.assertNotIn("/fictional/private/run", json.dumps(value))

    def test_malformed_linked_and_unreadable_holds_require_inspection(self):
        import workbench
        for mode in ["invalid_json", "wrong_schema", "symlink", "hardlink", "unreadable"]:
            with self.subTest(mode=mode), readiness_fixture() as (root, manager, project):
                hold = manager.data / "state/hold.json"
                raw = canonical({"state": "REQUEST_UNSETTLED", "run": "/fictional/private/run", "turn": 1})
                if mode == "invalid_json":
                    hold.write_bytes(b"{invalid hold")
                elif mode == "wrong_schema":
                    hold.write_bytes(canonical([PRIVATE_SENTINEL]))
                elif mode in ["symlink", "hardlink"]:
                    outside = root / "outside-hold.json"
                    outside.write_bytes(raw)
                    if mode == "symlink":
                        hold.symlink_to(outside)
                    else:
                        hold.hardlink_to(outside)
                else:
                    hold.write_bytes(raw)
                real_read = workbench.readiness_read_file

                def read_hold(directory, name, *args, **kwargs):
                    if mode == "unreadable" and str(name).endswith("hold.json"):
                        raise PermissionError(PRIVATE_SENTINEL)
                    return real_read(directory, name, *args, **kwargs)

                with patch("workbench.readiness_read_file", side_effect=read_hold):
                    value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("HOLD_UNREADABLE", value["reasons"])
                self.assertIn(value["admission"]["hold"], ["PRESENT", "UNAVAILABLE"])

    def test_saved_active_recovery_and_uncertain_states_are_not_reconciled(self):
        for state, reason in [("RUNNING", "TASK_ACTIVE_OR_UNRESOLVED"), ("STOP_REQUESTED", "TASK_ACTIVE_OR_UNRESOLVED"),
                              ("RECOVERY_REQUIRED", "TASK_ACTIVE_OR_UNRESOLVED"), ("UNCERTAIN", "TASK_UNCERTAIN")]:
            with self.subTest(state=state), readiness_fixture() as (root, manager, project):
                run_id = seed_readiness_job(manager, state=state)
                value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "BLOCKED")
                self.assertIn(reason, value["reasons"])
                self.assertEqual(json.loads(manager.meta_path(run_id).read_bytes())["state"], state)
                self.assertEqual(value["admission"]["jobs_inspected"], 1)

    def test_known_terminal_failures_alone_do_not_block(self):
        with readiness_fixture() as (root, manager, project):
            for number, state in enumerate(["FAILED", "REFUSED", "INTERRUPTED", "REVIEW_READY"]):
                seed_readiness_job(manager, f"{number:016x}", state=state)
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            self.assertEqual(value["admission"]["jobs_inspected"], 4)

    def test_pending_failed_and_verified_workspaces_use_only_saved_receipts(self):
        for status in ["PREPARING", "FAILED", "VERIFIED"]:
            with self.subTest(status=status), readiness_fixture() as (root, manager, project):
                receipt = completed_workspace() if status == "VERIFIED" else {"status": status, "created": 1,
                    "source_applied": False, "result_sha256": "a" * 64, "patch_sha256": "b" * 64}
                seed_readiness_job(manager, workspace=receipt)
                value = self.observe(root, manager, project)
                self.assertEqual(value["admission"]["workspaces_inspected"], 1)
                self.assertEqual(value["status"], "STATIC_CHECKS_PASSED" if status == "VERIFIED" else "BLOCKED")
                if status != "VERIFIED":
                    self.assertIn("WORKSPACE_ACTIVE_OR_UNRESOLVED", value["reasons"])

    def test_damaged_job_and_workspace_records_require_inspection(self):
        for section, raw in [("job", canonical([])), ("job", canonical({"state": PRIVATE_SENTINEL})),
                             ("job", b"{broken metadata"), ("workspace", canonical({"status": "VERIFIED"})),
                             ("workspace", canonical(42))]:
            with self.subTest(section=section, raw=raw[:30]), readiness_fixture() as (root, manager, project):
                run_id = seed_readiness_job(manager, workspace=completed_workspace() if section == "workspace" else None)
                target = manager.meta_path(run_id) if section == "job" else manager.run_path(run_id) / "git-workspace.json"
                target.write_bytes(raw)
                value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("ADMISSION_RECORD_INVALID", value["reasons"])

    def test_malformed_pending_and_failed_receipts_retain_blocker_and_require_inspection(self):
        core = {"created": 1, "source_applied": False,
                "result_sha256": "a" * 64, "patch_sha256": "b" * 64}
        invalid = [
            ("minimal", {}),
            ("invalid_result_hash", {**core, "result_sha256": "g" * 64}),
            ("uppercase_patch_hash", {**core, "patch_sha256": "A" * 64}),
            ("boolean_created", {**core, "created": True}),
            ("negative_created", {**core, "created": -1}),
            ("unsafe_created", {**core, "created": 9007199254740992}),
            ("source_applied", {**core, "source_applied": True}),
            ("reason_type", {**core, "reason": 42}),
            ("reason_length", {**core, "reason": "x" * 129}),
            ("finished_type", {**core, "finished": True}),
            ("finished_range", {**core, "finished": 9007199254740992}),
            ("checks_type", {**core, "checks": []}),
            ("check_row_type", {**core, "checks": {"unit": []}}),
            ("check_fields", {**core, "checks": {"unit": {"exit_code": True}}}),
        ]
        for status in ["PREPARING", "FAILED"]:
            for name, fields in invalid:
                with self.subTest(status=status, case=name), readiness_fixture() as (root, manager, project):
                    seed_readiness_job(manager, workspace={"status": status, **fields})
                    value = self.observe(root, manager, project)
                    self.assertEqual(value["status"], "NEEDS_INSPECTION")
                    self.assertTrue({"WORKSPACE_ACTIVE_OR_UNRESOLVED", "ADMISSION_RECORD_INVALID"}
                                    <= set(value["admission"]["reasons"]))
                    self.assertTrue({"WORKSPACE_ACTIVE_OR_UNRESOLVED", "ADMISSION_RECORD_INVALID"}
                                    <= set(value["reasons"]))
            with self.subTest(status=status, case="valid_optional"), readiness_fixture() as (root, manager, project):
                check = {"exit_code": 1, "tests_ran": 4, "timed_out": False,
                         "output_limited": False, "infrastructure_error": False, "output": PRIVATE_SENTINEL}
                receipt = {"status": status, **core, "reason": "WORKSPACE_CHECKS_FAILED",
                           "finished": 2, "checks": {"unit": check}}
                seed_readiness_job(manager, workspace=receipt)
                value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "BLOCKED")
                self.assertIn("WORKSPACE_ACTIVE_OR_UNRESOLVED", value["reasons"])
                self.assertNotIn("ADMISSION_RECORD_INVALID", value["reasons"])

    def test_unfinished_metadata_next_file_remains_an_inspection_blocker(self):
        with readiness_fixture() as (root, manager, project):
            write_new(manager.data / "jobs/1111111111111111.json.next", canonical({"id": "1111111111111111", "state": "FAILED"}))
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "NEEDS_INSPECTION")
            self.assertIn("ADMISSION_RECORD_INVALID", value["reasons"])

    def test_job_inventory_limit_explicitly_blocks_partial_inspection(self):
        with readiness_fixture() as (root, manager, project):
            for number in range(205):
                seed_readiness_job(manager, f"{number:016x}")
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "NEEDS_INSPECTION")
            self.assertIn("ADMISSION_RECORD_LIMIT", value["reasons"])
            self.assertTrue(value["admission"]["truncated"])
            self.assertLessEqual(value["admission"]["jobs_inspected"], 200)

    def test_directory_enumeration_limit_does_not_claim_complete_admission(self):
        with readiness_fixture() as (root, manager, project):
            for number in range(1025):
                write_new(manager.data / "jobs" / ("invented-junk-" + str(number)), b"invented ignored entry\n")
            value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "NEEDS_INSPECTION")
            self.assertIn("ADMISSION_RECORD_LIMIT", value["reasons"])
            self.assertTrue(value["admission"]["truncated"])

    def test_aggregate_saved_record_budget_blocks_without_reading_every_job(self):
        import workbench
        with readiness_fixture() as (root, manager, project):
            for number in range(80):
                seed_readiness_job(manager, f"{number:016x}", padding=30000)
            real_read, total = workbench.readiness_read_file, 0

            def count_bytes(directory, name, *args, **kwargs):
                nonlocal total
                raw = real_read(directory, name, *args, **kwargs)
                if Path(directory) == manager.data and (str(name).startswith("jobs/") or str(name).startswith("runs/")):
                    total += len(raw)
                return raw

            with patch("workbench.readiness_read_file", side_effect=count_bytes):
                value = self.observe(root, manager, project)
            self.assertEqual(value["status"], "NEEDS_INSPECTION")
            self.assertIn("ADMISSION_RECORD_LIMIT", value["reasons"])
            self.assertTrue(value["admission"]["truncated"])
            self.assertLess(value["admission"]["jobs_inspected"], 80)
            self.assertLessEqual(total, 2097152)

    def test_substituted_jobs_and_runs_ancestors_never_expose_outside_records(self):
        for section in ["jobs", "runs"]:
            with self.subTest(section=section), readiness_fixture() as (root, manager, project):
                run_id = seed_readiness_job(manager, workspace=completed_workspace())
                store = manager.data / section
                store.rename(root / ("retained-" + section))
                outside = root / ("outside-" + section)
                outside.mkdir()
                if section == "jobs":
                    write_new(outside / (run_id + ".json"), canonical({"state": "FAILED", "private_extra": PRIVATE_SENTINEL}))
                else:
                    (outside / run_id).mkdir()
                    write_new(outside / run_id / "git-workspace.json", canonical({"status": "VERIFIED", "private_extra": PRIVATE_SENTINEL}))
                store.symlink_to(outside, target_is_directory=True)
                value = self.observe(root, manager, project)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertTrue(set(value["reasons"]) & {"ADMISSION_UNAVAILABLE", "ADMISSION_RECORD_INVALID"})

    def test_unknown_project_refuses_bounded_code_without_any_record_change(self):
        with readiness_fixture() as (root, manager, _):
            before = readiness_hashes(root)
            with readiness_guard(manager):
                for project in ["missing", "../outside", None]:
                    with self.subTest(project=project), self.assertRaisesRegex(Refused, "^READINESS_PROJECT_UNKNOWN$"):
                        manager.project_readiness(project)
            self.assertEqual(before, readiness_hashes(root))


@contextmanager
def readiness_http_fixture():
    """Exercise actual GET handlers in memory, without a socket or server."""
    with readiness_fixture() as (root, manager, project):
        handler_type = make_handler(manager, "invented-readiness-token", "http://127.0.0.1:8765")

        def request(path, headers=None):
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-readiness-token"}
            supplied.update(headers or {})
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = "GET", path
            handler.request_version, handler.requestline = "HTTP/1.1", "GET " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, value in supplied.items():
                handler.headers[key] = value
            handler.rfile, handler.wfile = io.BytesIO(), io.BytesIO()
            handler.do_GET()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(raw)

        yield root, manager, project, request


class ReadinessHTTPTests(unittest.TestCase):
    def test_get_readiness_is_static_and_preserves_all_private_bytes(self):
        with readiness_http_fixture() as (root, manager, project, request):
            before = readiness_hashes(root)
            with readiness_guard(manager), patch("workbench.readiness_presence", return_value=True):
                code, value = request("/api/project-readiness/" + project)
            self.assertEqual(code, 200)
            self.assertEqual(value["version"], 1)
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            self.assertEqual(set(value["not_checked"]), NOT_CHECKED)
            self.assertEqual(before, readiness_hashes(root))

    def test_get_readiness_session_host_cross_site_and_unknown_project_guards(self):
        with readiness_http_fixture() as (root, manager, project, request):
            before = readiness_hashes(root)
            with readiness_guard(manager):
                for headers, reason in [({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                                        ({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                                        ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                    with self.subTest(reason=reason):
                        code, value = request("/api/project-readiness/" + project, headers)
                        self.assertEqual((code, value["error"]), (403, reason))
                code, value = request("/api/project-readiness/missing")
                self.assertEqual((code, value["error"]), (409, "READINESS_PROJECT_UNKNOWN"))
            self.assertEqual(before, readiness_hashes(root))


if __name__ == "__main__":
    unittest.main()
