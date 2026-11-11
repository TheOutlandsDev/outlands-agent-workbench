"""Pure readiness tests over invented static observations only."""

import copy
import json
import unittest
from unittest.mock import patch

from project_readiness import NOT_CHECKED, REASONS, summarize


def snapshot(*, java=False):
    files = ({"sample/ValueTest.java": "b" * 64, "sample/Value.java": "a" * 64} if java
             else {"test_module.py": "b" * 64, "module.py": "a" * 64})
    editable = ["sample/Value.java"] if java else ["module.py"]
    checks = ({"unit": {"kind": "java-main", "sources": list(files), "main_class": "sample.ValueTest"}}
              if java else {"unit": "test_module.py"})
    task = {"format": "outlands-coding-agent-v2" if java else "outlands-coding-agent-v1",
        "goal": "Inspect the invented value.", "files": files, "editable": editable,
        "checks": checks, "max_turns": 3, "request_seconds": 17}
    return {"project": "invented", "name": "Invented project", "checked_at_ms": 1_800_000_000_000,
        "definition": task,
        "config": {"expected_sha256": "c" * 64, "sha256": "c" * 64, "status": "MATCH"},
        "task": {"expected_sha256": "d" * 64, "sha256": "d" * 64, "status": "MATCH"},
        "files": [{"path": name, "editable": name in editable, "expected_sha256": digest,
                   "sha256": digest, "bytes": 40 + index, "status": "MATCH"}
                  for index, (name, digest) in enumerate(files.items())],
        "prerequisites": [{"id": name, "required": name not in {"git", "jdk"} or java and name == "jdk",
                           "status": "NOT_REQUIRED" if name == "jdk" and not java else "AVAILABLE"}
                          for name in ("python", "git", "bwrap", "prlimit", "jdk")],
        "admission": {"hold": "ABSENT", "jobs_inspected": 0, "workspaces_inspected": 0,
                      "truncated": False, "reasons": []}, "notes": []}


def source_row(value, path="module.py"):
    return next(row for row in value["files"] if row["path"] == path)


def prerequisite(value, identifier):
    return next(row for row in value["prerequisites"] if row["id"] == identifier)


class ReadinessTests(unittest.TestCase):
    def test_python_success_is_only_static_and_has_exact_dto(self):
        supplied = snapshot()
        value = summarize(supplied)
        self.assertEqual(set(value), {"version", "project", "name", "checked_at_ms", "status", "goal",
            "fingerprints", "files", "total_bytes", "limits", "checks", "prerequisites", "admission", "reasons", "not_checked"})
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertEqual(value["reasons"], [])
        self.assertEqual(value["not_checked"], list(NOT_CHECKED))
        self.assertEqual(len(value["not_checked"]), 8)
        self.assertEqual(value["goal"], supplied["definition"]["goal"])
        self.assertEqual(value["total_bytes"], 81)
        self.assertEqual(value["limits"], {"max_files": 32, "max_file_bytes": 32768,
            "max_total_bytes": 131072, "max_turns": 3, "request_seconds": 17})
        self.assertEqual([row["path"] for row in value["files"]], ["module.py", "test_module.py"])
        self.assertFalse(source_row(value, "test_module.py")["editable"])
        self.assertEqual(value["checks"], [{"name": "unit", "spec": "test_module.py"}])
        self.assertNotIn("provider_ready", value)
        self.assertIn("ISOLATION_CAPABILITY", value["not_checked"])

    def test_java_profile_preserves_check_spec_and_requires_jdk_without_qualification(self):
        supplied = snapshot(java=True)
        value = summarize(supplied)
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertEqual(value["checks"][0]["spec"], supplied["definition"]["checks"]["unit"])
        self.assertTrue(prerequisite(value, "jdk")["required"])
        self.assertIn("JAVA_VERSION", value["not_checked"])
        self.assertIn("CHECK_EXECUTION", value["not_checked"])

    def test_source_change_alone_requires_refresh(self):
        supplied = snapshot()
        source_row(supplied).update(sha256="e" * 64, status="CHANGED")
        value = summarize(supplied)
        self.assertEqual(value["status"], "REFRESH_REQUIRED")
        self.assertEqual(value["reasons"], ["SOURCE_CHANGED"])
        self.assertEqual(source_row(value)["expected_sha256"], "a" * 64)
        self.assertEqual(source_row(value)["sha256"], "e" * 64)

    def test_raw_fingerprints_are_not_reconstructed_from_json_definition(self):
        supplied = snapshot()
        # These are supplied hashes of exact original raw bytes, including JSON whitespace.
        supplied["task"].update(expected_sha256="f" * 64, sha256="f" * 64)
        value = summarize(supplied)
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertEqual(value["fingerprints"]["task"]["sha256"], "f" * 64)

    def test_config_or_task_drift_keeps_all_source_rows_not_checked(self):
        for section, code in (("config", "CONFIG_CHANGED"), ("task", "TASK_CHANGED")):
            with self.subTest(section=section):
                supplied = snapshot()
                supplied[section].update(sha256="e" * 64, status="CHANGED")
                source_row(supplied).update(sha256="f" * 64, status="CHANGED", bytes=32769)
                value = summarize(supplied)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn(code, value["reasons"])
                self.assertNotIn("SOURCE_CHANGED", value["reasons"])
                self.assertNotIn("FILE_LIMIT", value["reasons"])
                self.assertIsNone(value["total_bytes"])
                for row in value["files"]:
                    self.assertEqual(row["status"], "NOT_CHECKED")
                    self.assertIsNone(row["sha256"])
                    self.assertIsNone(row["bytes"])

    def test_unreadable_missing_limited_and_unknown_fingerprints_require_inspection(self):
        for section in ("config", "task"):
            for status in ("MISSING", "UNREADABLE", "LIMIT", "unknown", None):
                with self.subTest(section=section, status=status):
                    supplied = snapshot()
                    supplied[section]["status"] = status
                    value = summarize(supplied)
                    self.assertEqual(value["status"], "NEEDS_INSPECTION")
                    self.assertIn(section.upper() + "_UNREADABLE", value["reasons"])
                    self.assertIsNone(value["fingerprints"][section]["sha256"])

    def test_fingerprint_hashes_and_status_must_be_consistent(self):
        supplied = snapshot()
        supplied["config"]["sha256"] = "e" * 64
        value = summarize(supplied)
        self.assertEqual(value["fingerprints"]["config"]["status"], "CHANGED")
        supplied = snapshot()
        supplied["task"]["status"] = "CHANGED"
        value = summarize(supplied)
        self.assertEqual(value["fingerprints"]["task"]["status"], "UNREADABLE")
        supplied["task"]["expected_sha256"] = "private invalid hash"
        self.assertIsNone(summarize(supplied)["fingerprints"]["task"]["expected_sha256"])

    def test_invalid_cached_tasks_do_not_expose_unapproved_scope_or_goal(self):
        changes = [lambda task: task.update(extra="private raw content"),
            lambda task: task.update(max_turns=True), lambda task: task.update(request_seconds=121),
            lambda task: task.update(goal=""), lambda task: task.update(goal="\ud800"),
            lambda task: task.update(files={"../outside.py": "a" * 64}),
            lambda task: task.update(files={str(i) + ".py": "a" * 64 for i in range(33)}),
            lambda task: task.update(editable=["test_module.py"])]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                supplied = snapshot()
                change(supplied["definition"])
                value = summarize(supplied)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("DEFINITION_INVALID", value["reasons"])
                self.assertEqual(value["files"], [])
                self.assertEqual(value["checks"], [])
                self.assertIsNone(value["goal"])
                self.assertIsNone(value["limits"]["max_turns"])

    def test_unknown_missing_duplicate_and_mismatched_source_scope_fail_closed(self):
        supplied = snapshot()
        supplied["files"].append({"path": "/private/unapproved.py", "content": "private raw source"})
        value = summarize(supplied)
        self.assertEqual(value["status"], "NEEDS_INSPECTION")
        self.assertNotIn("/private/unapproved.py", json.dumps(value))
        for kind in ("missing", "duplicate", "editable", "expected"):
            with self.subTest(kind=kind):
                supplied = snapshot()
                if kind == "missing":
                    supplied["files"] = []
                elif kind == "duplicate":
                    supplied["files"].append(copy.deepcopy(source_row(supplied)))
                elif kind == "editable":
                    source_row(supplied)["editable"] = False
                else:
                    source_row(supplied)["expected_sha256"] = "e" * 64
                value = summarize(supplied)
                self.assertIn(value["status"], {"BLOCKED", "NEEDS_INSPECTION"})
                self.assertIn("SOURCE_UNREADABLE", value["reasons"])

    def test_missing_unsafe_and_unchecked_source_blocks(self):
        for status, code in (("MISSING", "SOURCE_MISSING"), ("UNREADABLE", "SOURCE_UNREADABLE"),
                             ("LIMIT", "FILE_LIMIT"), ("BINARY", "BINARY_INPUT"),
                             ("UTF8", "INVALID_UTF8"), ("NOT_CHECKED", "SOURCE_UNREADABLE"),
                             ("unknown", "SOURCE_UNREADABLE")):
            with self.subTest(status=status):
                supplied = snapshot()
                source_row(supplied).update(status=status, sha256=None, bytes=None)
                value = summarize(supplied)
                self.assertEqual(value["status"], "BLOCKED")
                self.assertIn(code, value["reasons"])
                self.assertIsNone(value["total_bytes"])
                self.assertIsNone(source_row(value)["sha256"])

    def test_file_limit_preserves_known_size_and_total(self):
        supplied = snapshot()
        source_row(supplied)["bytes"] = 32769
        value = summarize(supplied)
        self.assertEqual(value["status"], "BLOCKED")
        self.assertEqual(source_row(value)["status"], "LIMIT")
        self.assertEqual(source_row(value)["bytes"], 32769)
        self.assertEqual(value["total_bytes"], 32809)

    def test_aggregate_limit_exact_boundary_and_excess_are_disclosed(self):
        for count, expected in ((4, "STATIC_CHECKS_PASSED"), (5, "BLOCKED")):
            supplied = snapshot()
            paths = ["module.py", "test_module.py", *["extra%s.py" % i for i in range(count - 2)]]
            supplied["definition"]["files"] = {path: "a" * 64 for path in paths}
            supplied["files"] = [{"path": path, "editable": path == "module.py", "expected_sha256": "a" * 64,
                "sha256": "a" * 64, "bytes": 32768, "status": "MATCH"} for path in paths]
            value = summarize(supplied)
            self.assertEqual(value["status"], expected)
            self.assertEqual(value["total_bytes"], count * 32768)
            if count == 5:
                self.assertIn("TOTAL_INPUT_LIMIT", value["reasons"])

    def test_unknown_or_boolean_size_never_counts_as_zero(self):
        for size in (None, True, -1, "40"):
            supplied = snapshot()
            source_row(supplied)["bytes"] = size
            value = summarize(supplied)
            self.assertIsNone(value["total_bytes"])
            self.assertIsNone(source_row(value)["bytes"])
            self.assertEqual(value["status"], "BLOCKED")

    def test_git_is_optional_even_when_missing_or_not_checked(self):
        for status in ("MISSING", "NOT_CHECKED", "NOT_CONFIGURED"):
            supplied = snapshot()
            prerequisite(supplied, "git").update(status=status, required=False)
            value = summarize(supplied)
            self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
            self.assertFalse(prerequisite(value, "git")["required"])
            self.assertEqual(prerequisite(value, "git")["status"], status)

    def test_required_check_tools_must_be_available(self):
        for identifier in ("python", "bwrap", "prlimit"):
            for status in ("MISSING", "NOT_CHECKED", "NOT_REQUIRED", "NOT_CONFIGURED"):
                with self.subTest(identifier=identifier, status=status):
                    supplied = snapshot()
                    prerequisite(supplied, identifier).update(status=status, required=True)
                    value = summarize(supplied)
                    self.assertEqual(value["status"], "BLOCKED")
                    self.assertTrue(prerequisite(value, identifier)["required"])
                    self.assertIn("PREREQUISITE_MISSING", value["reasons"])

    def test_java_jdk_missing_and_not_configured_are_distinct(self):
        for status, reason in (("NOT_CONFIGURED", "JDK_NOT_CONFIGURED"), ("MISSING", "PREREQUISITE_MISSING"),
                               ("NOT_CHECKED", "PREREQUISITE_MISSING")):
            supplied = snapshot(java=True)
            prerequisite(supplied, "jdk").update(status=status, required=True)
            value = summarize(supplied)
            self.assertTrue(prerequisite(value, "jdk")["required"])
            self.assertEqual(value["status"], "BLOCKED")
            self.assertIn(reason, value["reasons"])
        supplied = snapshot()
        prerequisite(supplied, "jdk").update(status="MISSING", required=False)
        self.assertEqual(summarize(supplied)["status"], "STATIC_CHECKS_PASSED")

    def test_requiredness_is_derived_and_contradictory_observations_need_inspection(self):
        for java, identifier, supplied_required, derived_required in (
                (False, "git", True, False), (False, "jdk", True, False),
                (False, "python", False, True), (True, "jdk", False, True)):
            with self.subTest(java=java, identifier=identifier):
                supplied = snapshot(java=java)
                prerequisite(supplied, identifier)["required"] = supplied_required
                value = summarize(supplied)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("DEFINITION_INVALID", value["reasons"])
                self.assertEqual(prerequisite(value, identifier)["required"], derived_required)

    def test_saved_active_uncertain_and_workspace_blockers_override_source_refresh(self):
        for reason in ("TASK_ACTIVE_OR_UNRESOLVED", "TASK_UNCERTAIN", "WORKSPACE_ACTIVE_OR_UNRESOLVED"):
            supplied = snapshot()
            source_row(supplied).update(status="CHANGED", sha256="e" * 64)
            supplied["admission"].update(jobs_inspected=1, reasons=[reason])
            value = summarize(supplied)
            self.assertEqual(value["status"], "BLOCKED")
            self.assertIn(reason, value["admission"]["reasons"])
            self.assertEqual(value["admission"]["jobs_inspected"], 1)
            self.assertIn("PROCESS_OWNERSHIP", value["not_checked"])

    def test_present_and_damaged_holds_preserve_blocking_evidence(self):
        supplied = snapshot()
        supplied["admission"]["hold"] = "PRESENT"
        value = summarize(supplied)
        self.assertEqual(value["status"], "BLOCKED")
        self.assertIn("HOLD_PRESENT", value["reasons"])
        supplied["admission"]["reasons"] = ["HOLD_UNREADABLE", "ADMISSION_RECORD_INVALID"]
        value = summarize(supplied)
        self.assertEqual(value["status"], "NEEDS_INSPECTION")
        self.assertEqual(value["admission"]["hold"], "PRESENT")
        self.assertIn("HOLD_PRESENT", value["reasons"])
        supplied["admission"]["hold"] = "UNAVAILABLE"
        self.assertEqual(summarize(supplied)["status"], "NEEDS_INSPECTION")

    def test_terminal_saved_failures_alone_do_not_block(self):
        supplied = snapshot()
        supplied["admission"].update(jobs_inspected=2, terminal_states=["FAILED", "REFUSED"])
        value = summarize(supplied)
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertNotIn("terminal_states", value["admission"])

    def test_unknown_damaged_or_limited_admission_requires_inspection(self):
        for update in ({"hold": "unknown"}, {"jobs_inspected": True}, {"jobs_inspected": 201},
                       {"jobs_inspected": -1}, {"workspaces_inspected": 1},
                       {"truncated": True}, {"truncated": None}, {"reasons": ["private raw exception"]}):
            with self.subTest(update=update):
                supplied = snapshot()
                supplied["admission"].update(update)
                value = summarize(supplied)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertNotIn("private raw exception", json.dumps(value))
        supplied = snapshot()
        supplied["admission"] = None
        self.assertIn("ADMISSION_UNAVAILABLE", summarize(supplied)["reasons"])

    def test_unknown_fields_private_paths_source_and_exceptions_are_stripped(self):
        supplied = snapshot()
        secret = "private-hidden /invented/account/source"
        supplied.update(source=secret, credentials=secret, exception=secret)
        supplied["config"]["path"] = secret
        supplied["task"]["raw"] = secret
        source_row(supplied).update(content=secret, error=secret)
        prerequisite(supplied, "jdk")["path"] = secret
        supplied["admission"].update(run=secret, response=secret, prompt=secret)
        value = summarize(supplied)
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertNotIn(secret, json.dumps(value))
        supplied["notes"] = [secret]
        value = summarize(supplied)
        self.assertNotIn(secret, json.dumps(value))
        self.assertTrue(set(value["reasons"]) <= REASONS)
        self.assertEqual(value["status"], "NEEDS_INSPECTION")

    def test_unicode_display_and_complete_json_stay_bounded(self):
        supplied = snapshot(java=True)
        supplied["definition"]["goal"] = "😀" * 2000
        supplied["name"] = "界" * 80
        value = summarize(supplied)
        self.assertEqual(value["goal"], "😀" * 2000)
        self.assertEqual(value["name"], "界" * 80)
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertLessEqual(len((json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")), 131072)
        supplied["name"] = "\ud800"
        self.assertIsNone(summarize(supplied)["name"])

    def test_maximum_selected_files_and_checks_remain_bounded(self):
        supplied = snapshot(java=True)
        paths = ["sample/ValueTest.java", *["sample/Value%s.java" % index for index in range(31)]]
        supplied["definition"].update(files={path: "a" * 64 for path in paths}, editable=[paths[1]], goal="😀" * 2000)
        supplied["definition"]["checks"] = {"unit%s" % index: {"kind": "java-main", "sources": list(paths),
            "main_class": "sample.ValueTest"} for index in range(4)}
        supplied["files"] = [{"path": path, "editable": path == paths[1], "expected_sha256": "a" * 64,
            "sha256": "a" * 64, "bytes": 0, "status": "MATCH"} for path in paths]
        value = summarize(supplied)
        self.assertEqual(value["status"], "STATIC_CHECKS_PASSED")
        self.assertEqual(len(value["files"]), 32)
        self.assertEqual(len(value["checks"]), 4)
        self.assertEqual(value["total_bytes"], 0)
        self.assertLessEqual(len((json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")), 131072)

    def test_unknown_required_prerequisite_observations_are_not_static_success(self):
        supplied = snapshot()
        supplied["prerequisites"] = [{"id": "unapproved-tool", "required": True, "status": "AVAILABLE", "path": "/private/tool"}]
        value = summarize(supplied)
        self.assertEqual(value["status"], "NEEDS_INSPECTION")
        self.assertIn("PREREQUISITE_MISSING", value["reasons"])
        self.assertEqual([row["id"] for row in value["prerequisites"]], ["python", "git", "bwrap", "prlimit", "jdk"])
        self.assertNotIn("/private/tool", json.dumps(value))

    def test_damaged_prerequisite_envelopes_cannot_statically_pass(self):
        cases = []
        valid = snapshot()["prerequisites"]
        cases.extend((None, {}, valid[:-1], valid + [copy.deepcopy(valid[1])],
                      valid + [{"id": "unknown", "required": False, "status": "AVAILABLE"}],
                      valid + [copy.deepcopy(valid[1])] * 100))
        duplicate = copy.deepcopy(valid)
        duplicate[1] = copy.deepcopy(duplicate[0])
        cases.append(duplicate)
        unknown = copy.deepcopy(valid)
        unknown[1]["id"] = "unapproved-tool"
        cases.append(unknown)
        malformed = copy.deepcopy(valid)
        malformed[1] = "private malformed Git observation"
        cases.append(malformed)
        for index, observations in enumerate(cases):
            with self.subTest(index=index):
                supplied = snapshot()
                supplied["prerequisites"] = observations
                value = summarize(supplied)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("DEFINITION_INVALID", value["reasons"])
                self.assertEqual([row["id"] for row in value["prerequisites"]], ["python", "git", "bwrap", "prlimit", "jdk"])
                self.assertNotIn("private malformed Git observation", json.dumps(value))

    def test_corrupted_optional_git_observation_requires_inspection(self):
        for update in ({"status": "unknown"}, {"status": None}, {"required": "false"}, {"required": None}):
            with self.subTest(update=update):
                supplied = snapshot()
                prerequisite(supplied, "git").update(update)
                value = summarize(supplied)
                self.assertEqual(value["status"], "NEEDS_INSPECTION")
                self.assertIn("DEFINITION_INVALID", value["reasons"])
                self.assertFalse(prerequisite(value, "git")["required"])

    def test_damaged_top_level_and_overlong_labels_never_raise_or_leak(self):
        for supplied in (None, [], {}, {"definition": {"files": {3: "a" * 64}}}):
            value = summarize(supplied)
            self.assertEqual(value["status"], "NEEDS_INSPECTION")
            self.assertIsNone(value["goal"])
        supplied = snapshot()
        supplied["name"] = "é" * 1000
        supplied["checked_at_ms"] = True
        value = summarize(supplied)
        self.assertEqual(len(value["name"]), 80)
        self.assertIsNone(value["checked_at_ms"])
        self.assertEqual(value["status"], "NEEDS_INSPECTION")

    def test_nested_specs_and_all_inputs_are_independent_of_results(self):
        supplied = snapshot(java=True)
        before = copy.deepcopy(supplied)
        value = summarize(supplied)
        self.assertEqual(supplied, before)
        value["checks"][0]["spec"]["sources"].append("not-original.java")
        value["files"][0]["path"] = "changed-result"
        value["not_checked"].clear()
        self.assertEqual(supplied, before)
        self.assertEqual(summarize(supplied)["not_checked"], list(NOT_CHECKED))

    def test_no_filesystem_process_network_execution_or_evaluation(self):
        supplied = snapshot()
        with patch("builtins.open", side_effect=AssertionError("filesystem")), \
                patch("os.open", side_effect=AssertionError("filesystem")), \
                patch("pathlib.Path.open", side_effect=AssertionError("filesystem")), \
                patch("subprocess.Popen", side_effect=AssertionError("process")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("builtins.exec", side_effect=AssertionError("execution")), \
                patch("builtins.eval", side_effect=AssertionError("evaluation")):
            self.assertEqual(summarize(supplied)["status"], "STATIC_CHECKS_PASSED")


if __name__ == "__main__":
    unittest.main()
