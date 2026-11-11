"""Invented accepted artifacts and read-only private-bundle integration tests."""

import copy
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, review_diff, sha, write_new
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-bundle-metadata-sentinel"
BUNDLE_IDS = {"python": "1111111111111111", "java": "2222222222222222"}
MEMBERS = {"manifest.json", "changes.diff", "review.json", "checks.json", "README.txt", "SHA256SUMS"}
NOT_CHECKED = ["CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "GIT_ADOPTION"]


def private_hashes(root):
    return {path.relative_to(root).as_posix(): sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


@contextmanager
def saved_only_guard(manager):
    """Bundle operations may read pinned files, but no live/execution APIs."""
    with ExitStack() as stack:
        for name in ["view", "history", "refresh", "export", "verified_artifact", "admission", "owns_active",
                     "request_hold", "workspace_receipt", "start", "stop", "create_workspace"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("bundle reached " + name)))
        for name in ["workbench.process_stamp", "workbench.subprocess.Popen", "workbench.subprocess.run",
                     "agent.Session.checks", "agent.Ollama.request", "agent.Ollama.preflight",
                     "agent.ScriptedDemo.request", "isolation.check", "java_check.check",
                     "http.client.HTTPConnection", "socket.socket"]:
            stack.enter_context(patch(name, side_effect=AssertionError("bundle reached " + name)))
        yield


def _install_project(manager, root, language):
    """Configure meaningful source text, without invoking a compiler or test."""
    source = root / ("bundle-source-" + language)
    source.mkdir(mode=0o700)
    if language == "python":
        before = {"arithmetic.py": b"def add(a, b):\n    return a - b\n",
                  "test_arithmetic.py": b"import unittest\nfrom arithmetic import add\n\nclass SumTests(unittest.TestCase):\n    def test_positive(self): self.assertEqual(add(2, 3), 5)\n    def test_negative(self): self.assertEqual(add(-2, -3), -5)\n    def test_zero(self): self.assertEqual(add(0, 0), 0)\n    def test_mixed(self): self.assertEqual(add(-2, 3), 1)\n"}
        editable, check = "arithmetic.py", "test_arithmetic.py"
        after = {**before, editable: before[editable].replace(b"a - b", b"a + b")}
    else:
        before = {"sample/Sum.java": b"package sample;\npublic class Sum {\n    public static int add(int a, int b) { return a - b; }\n}\n",
                  "sample/SumTest.java": b"package sample;\npublic class SumTest {\n    public static void main(String[] args) {\n        if (Sum.add(2, 3) != 5 || Sum.add(-2, -3) != -5 || Sum.add(-2, 3) != 1)\n            throw new AssertionError(\"invented sum mismatch\");\n    }\n}\n"}
        editable, check = "sample/Sum.java", "sample.SumTest"
        after = {**before, editable: before[editable].replace(b"a - b", b"a + b")}
    for name, raw in before.items():
        path = source / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_new(path, raw)
    project_id = "bundle_" + language
    request = {"id": project_id, "name": "Invented " + language + " bundle project", "source": str(source),
               "language": language, "files": list(before), "editable": [editable], "check": check,
               "goal": PRIVATE_SENTINEL + " approved default goal"}
    original_jdk = manager.jdk_home
    try:
        if language == "java":
            manager.jdk_home = root / "fictional-jdk-not-needed-for-bundles"
        draft = manager.project_preview(request)
        manager.project_save({"draft": draft["draft"]})
    finally:
        manager.jdk_home = original_jdk
    return manager.projects[project_id], before, after


def _seed_accepted_run(manager, run_id, project, before, after):
    task = copy.deepcopy(project["definition"])
    task["goal"] = PRIVATE_SENTINEL + " run goal override"
    task_raw = canonical(task)
    run = manager.run_path(run_id)
    run.mkdir(mode=0o700)
    for label, files in [("baseline", before), ("work", after)]:
        directory = run / label
        directory.mkdir(mode=0o700)
        for name, raw in files.items():
            path = directory / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(path, raw)
    patch_raw = "".join(review_diff(name, before[name], after[name]) for name in sorted(before)).encode()
    result = {"format": task["format"], "status": "REVIEW_READY", "reason": "CHECKS_PASSED", "backend": "ollama",
              "ai_inference": True, "turns": 1, "source_adopted": False, "patch_sha256": sha(patch_raw),
              "files": {name: {"before": sha(before[name]), "after": sha(after[name])} for name in sorted(before)},
              "private_extra": PRIVATE_SENTINEL}
    result_raw = canonical(result)
    review = {"id": run_id, "result_sha256": sha(result_raw), "patch_sha256": sha(patch_raw), "verdict": "accepted",
              "note": PRIVATE_SENTINEL + " private review note", "recorded": 100,
              "source_applied": False, "private_extra": PRIVATE_SENTINEL}
    java = any(isinstance(spec, dict) and spec.get("kind") == "java-main" for spec in task["checks"].values())
    passing = {"exit_code": 0, "tests_ran": 1 if java else 4, "timed_out": False,
               "output_limited": False, "infrastructure_error": False, "output": PRIVATE_SENTINEL}
    if java:
        passing.update(kind="java-main", phase="run")
    final = {"index": 1, "kind": "independent_final_checks", "value": {name: copy.deepcopy(passing) for name in task["checks"]},
             "private_extra": PRIVATE_SENTINEL}
    baseline = {"index": 0, "kind": "baseline_checks", "value": {name: {**passing, "exit_code": 1} for name in task["checks"]}}
    metadata = {"id": run_id, "project": project["id"], "project_name": project["name"], "source": str(project["source"]),
                "goal": task["goal"], "model": PRIVATE_SENTINEL + "-model", "backend": "ollama", "state": "REVIEW_READY",
                "created": 100, "finished": 101, "task_sha256": sha(task_raw),
                "project_task_sha256": sha(project["task_raw"]), "private_extra": PRIVATE_SENTINEL}
    write_new(manager.meta_path(run_id), canonical(metadata))
    write_new(manager.data / "tasks" / (run_id + ".json"), task_raw)
    for name, raw in [("result.json", result_raw), ("changes.diff", patch_raw), ("review-000.json", canonical(review)),
                      ("event-000.json", canonical(baseline)), ("event-001.json", canonical(final))]:
        write_new(run / name, raw)


def populate_bundle_runs(manager, root):
    """Populate a fresh private Manager with invented accepted Python/Java runs.

    Recorded checks are deliberately saved fixture evidence; nothing executes.
    The separate synthetic hold is unrelated to either accepted artifact.
    """
    prepared = {language: _install_project(manager, root, language) for language in ["python", "java"]}
    for language, (project, before, after) in prepared.items():
        _seed_accepted_run(manager, BUNDLE_IDS[language], project, before, after)
    write_new(manager.data / "state/hold.json", canonical({"state": "REQUEST_UNSETTLED",
        "run": str(manager.data / "runs/eeeeeeeeeeeeeeee"), "turn": 1}))
    return dict(BUNDLE_IDS)


@contextmanager
def bundle_fixture():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        ids = populate_bundle_runs(manager, root)
        try:
            yield root, manager, ids
        finally:
            manager.close()


def rewrite_json(path, mutate):
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_bytes(canonical(value))


class BundleIntegrationTests(unittest.TestCase):
    def assert_refused(self, root, operation, *args, codes=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(*args)
        code = str(caught.exception)
        self.assertRegex(code, r"^BUNDLE_[A-Z_]{1,48}$")
        self.assertNotIn(PRIVATE_SENTINEL, code)
        if codes:
            self.assertIn(code, codes)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_roundtrip_is_deterministic_read_only_and_needs_no_jdk(self):
        from patch_bundle import verify_bundle
        with bundle_fixture() as (root, manager, ids):
            self.assertIsNone(manager.jdk_home)
            before = private_hashes(root)
            hold_raw = (manager.data / "state/hold.json").read_bytes()
            with saved_only_guard(manager), patch("zipfile.ZipFile.extract", side_effect=AssertionError("extract")), patch("zipfile.ZipFile.extractall", side_effect=AssertionError("extractall")):
                for language, run_id in ids.items():
                    with self.subTest(language=language):
                        preview = manager.bundle_preview(run_id)
                        self.assertEqual(preview, manager.bundle_preview(run_id))
                        raw = manager.bundle_export(run_id, preview["bundle_sha256"])
                        self.assertEqual(raw, manager.bundle_export(run_id, preview["bundle_sha256"]))
                        self.assertEqual(preview, verify_bundle(raw, preview["bundle_sha256"]))
                        self.assertEqual(preview["member_count"], 6)
                        self.assertEqual({row["path"] for row in preview["members"]}, MEMBERS)
                        self.assertEqual(preview["not_checked"], NOT_CHECKED)
                        self.assertEqual(preview["review"], {"verdict": "accepted", "source_applied": False})
                        self.assertEqual(preview["checks"][0]["tests_ran"], 1 if language == "java" else 4)
                        self.assertEqual(set(preview["notes"]), {"PRIVATE_SOURCE_CONTENT", "RECORDED_CHECKS_ONLY", "UNSIGNED_BUNDLE"})
            self.assertEqual(before, private_hashes(root))
            self.assertEqual(hold_raw, (manager.data / "state/hold.json").read_bytes())

    def test_bundle_members_strip_private_records_but_keep_reviewed_patch(self):
        with bundle_fixture() as (root, manager, ids):
            with saved_only_guard(manager):
                preview = manager.bundle_preview(ids["python"])
                raw = manager.bundle_export(ids["python"], preview["bundle_sha256"])
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                content = {name: archive.read(name) for name in archive.namelist()}
            self.assertEqual(set(content), MEMBERS)
            encoded = b"\n".join(content.values())
            for private in [PRIVATE_SENTINEL, str(root), ids["python"], "bundle_python"]:
                self.assertNotIn(private.encode(), encoded)
                self.assertNotIn(private, json.dumps(preview))
            self.assertEqual(content["changes.diff"], (manager.run_path(ids["python"]) / "changes.diff").read_bytes())
            self.assertIn(b"return a + b", content["changes.diff"])
            self.assertNotIn(b"test_positive", encoded)
            manifest = json.loads(content["manifest.json"])
            self.assertEqual(set(manifest), {"format", "hashes", "task_profile", "files"})
            self.assertNotIn("goal", manifest["task_profile"])
            self.assertEqual(manifest["hashes"]["task_sha256"], sha((manager.data / "tasks" / (ids["python"] + ".json")).read_bytes()))

    def test_preview_pin_refuses_later_valid_review_record_change(self):
        with bundle_fixture() as (root, manager, ids), saved_only_guard(manager):
            run_id = ids["python"]
            first = manager.bundle_preview(run_id)
            rewrite_json(manager.run_path(run_id) / "review-000.json", lambda row: row.update(note=PRIVATE_SENTINEL + " intentional later fixture note"))
            self.assert_refused(root, manager.bundle_export, run_id, first["bundle_sha256"], codes={"BUNDLE_CHANGED"})
            second = manager.bundle_preview(run_id)
            self.assertNotEqual(first["bundle_sha256"], second["bundle_sha256"])
            self.assertTrue(manager.bundle_export(run_id, second["bundle_sha256"]).startswith(b"PK"))

    def test_download_requires_a_valid_external_archive_pin(self):
        with bundle_fixture() as (root, manager, ids), saved_only_guard(manager):
            for pin in [None, "bad", "A" * 64, True]:
                with self.subTest(pin=pin):
                    self.assert_refused(root, manager.bundle_export, ids["python"], pin, codes={"BUNDLE_HASH_REQUIRED"})
            self.assert_refused(root, manager.bundle_export, ids["python"], "0" * 64, codes={"BUNDLE_CHANGED"})

    def test_config_task_pin_and_scope_drift_refuse_before_source_reads(self):
        import workbench
        for mode in ["config", "project_task", "legacy_run_pin", "legacy_project_pin", "wrong_project_pin", "run_pin", "source_root", "scope", "checks", "budgets"]:
            with self.subTest(mode=mode), bundle_fixture() as (root, manager, ids):
                run_id = ids["python"]
                project = manager.projects["bundle_python"]
                metadata_path = manager.meta_path(run_id)
                task_path = manager.data / "tasks" / (run_id + ".json")
                if mode == "config":
                    manager.config_path.write_bytes(manager.config_raw + b" \n")
                elif mode == "project_task":
                    project["task"].write_bytes(project["task_raw"] + b" \n")
                elif mode in ["legacy_run_pin", "legacy_project_pin"]:
                    key = "task_sha256" if mode == "legacy_run_pin" else "project_task_sha256"
                    rewrite_json(metadata_path, lambda row: row.pop(key))
                elif mode == "wrong_project_pin":
                    rewrite_json(metadata_path, lambda row: row.update(project_task_sha256="0" * 64))
                elif mode == "source_root":
                    rewrite_json(metadata_path, lambda row: row.update(source="/fictional/unapproved/source"))
                else:
                    task = json.loads(task_path.read_bytes())
                    if mode == "scope":
                        task["files"]["unselected.py"] = "0" * 64
                    elif mode == "checks":
                        task["checks"] = {"different": task["checks"]["unit"]}
                    elif mode == "budgets":
                        task["max_turns"] -= 1
                    else:
                        task["goal"] += " changed without updating run pin"
                    task_path.write_bytes(canonical(task))
                    if mode != "run_pin":
                        rewrite_json(metadata_path, lambda row: row.update(task_sha256=sha(task_path.read_bytes())))
                reader = workbench.readiness_read_file

                def no_source(directory, name, *args, **kwargs):
                    self.assertFalse(Path(directory) == project["source"] or project["source"] in Path(directory).parents)
                    self.assertFalse(str(name).endswith("hold.json"))
                    return reader(directory, name, *args, **kwargs)

                with saved_only_guard(manager), patch("workbench.readiness_read_file", side_effect=no_source):
                    self.assert_refused(root, manager.bundle_preview, run_id, codes={"BUNDLE_PROJECT_CHANGED", "BUNDLE_PIN_REQUIRED"})

    def test_baseline_work_original_protected_and_saved_patch_drift_refuse(self):
        for mode in ["baseline", "work", "source", "protected", "patch"]:
            with self.subTest(mode=mode), bundle_fixture() as (root, manager, ids):
                run_id, run = ids["python"], manager.run_path(ids["python"])
                target = {"baseline": run / "baseline/arithmetic.py", "work": run / "work/arithmetic.py",
                          "source": manager.projects["bundle_python"]["source"] / "arithmetic.py",
                          "protected": run / "work/test_arithmetic.py", "patch": run / "changes.diff"}[mode]
                target.write_bytes(target.read_bytes() + b"# invented later fixture change\n")
                with saved_only_guard(manager):
                    self.assert_refused(root, manager.bundle_preview, run_id,
                        codes={"BUNDLE_SOURCE_CHANGED"} if mode == "source" else {"BUNDLE_ARTIFACT_CHANGED"})

    def test_coordinated_protected_candidate_result_and_patch_tamper_still_refuses(self):
        with bundle_fixture() as (root, manager, ids):
            run_id, run = ids["python"], manager.run_path(ids["python"])
            protected = run / "work/test_arithmetic.py"
            protected.write_bytes(protected.read_bytes() + b"# invented protected edit\n")
            task = json.loads((manager.data / "tasks" / (run_id + ".json")).read_bytes())
            patch_raw = "".join(review_diff(name, (run / "baseline" / name).read_bytes(), (run / "work" / name).read_bytes()) for name in sorted(task["files"])).encode()
            (run / "changes.diff").write_bytes(patch_raw)
            result = json.loads((run / "result.json").read_bytes())
            result["files"]["test_arithmetic.py"]["after"] = sha(protected.read_bytes())
            result["patch_sha256"] = sha(patch_raw)
            (run / "result.json").write_bytes(canonical(result))
            rewrite_json(run / "review-000.json", lambda row: row.update(result_sha256=sha(canonical(result)), patch_sha256=sha(patch_raw)))
            with saved_only_guard(manager):
                self.assert_refused(root, manager.bundle_preview, run_id, codes={"BUNDLE_ARTIFACT_CHANGED"})

    def test_uncertain_unaccepted_and_missing_acceptance_never_export(self):
        for mode in ["uncertain", "result_failed", "review_rejected", "review_missing", "latest_rejected"]:
            with self.subTest(mode=mode), bundle_fixture() as (root, manager, ids):
                run_id, run = ids["python"], manager.run_path(ids["python"])
                if mode == "uncertain":
                    rewrite_json(manager.meta_path(run_id), lambda row: row.update(state="UNCERTAIN"))
                elif mode == "result_failed":
                    rewrite_json(run / "result.json", lambda row: row.update(status="FAILED"))
                elif mode == "review_missing":
                    (run / "review-000.json").unlink()
                elif mode == "review_rejected":
                    rewrite_json(run / "review-000.json", lambda row: row.update(verdict="rejected"))
                else:
                    latest = json.loads((run / "review-000.json").read_bytes()); latest["verdict"] = "rejected"
                    write_new(run / "review-001.json", canonical(latest))
                with saved_only_guard(manager):
                    self.assert_refused(root, manager.bundle_preview, run_id,
                        codes={"BUNDLE_NOT_REVIEW_READY"} if mode in ["uncertain", "result_failed"] else {"BUNDLE_REVIEW_REQUIRED"})

    def test_result_review_and_final_evidence_changes_refuse_bounded_errors(self):
        for mode in ["result_raw", "review_bad_json", "review_wrong_id", "review_applied", "result_adopted",
                     "final_zero", "final_boolean", "final_timeout", "final_scope", "final_missing", "final_duplicate"]:
            with self.subTest(mode=mode), bundle_fixture() as (root, manager, ids):
                run_id, run = ids["python"], manager.run_path(ids["python"])
                final_path = run / "event-001.json"
                if mode == "result_raw":
                    rewrite_json(run / "result.json", lambda row: row.update(private_extra=PRIVATE_SENTINEL + " edited"))
                elif mode == "review_bad_json":
                    (run / "review-000.json").write_bytes(b"{invalid " + PRIVATE_SENTINEL.encode())
                elif mode == "review_wrong_id":
                    rewrite_json(run / "review-000.json", lambda row: row.update(id="f" * 16))
                elif mode == "review_applied":
                    rewrite_json(run / "review-000.json", lambda row: row.update(source_applied=True))
                elif mode == "result_adopted":
                    rewrite_json(run / "result.json", lambda row: row.update(source_adopted=True))
                    rewrite_json(run / "review-000.json", lambda row: row.update(result_sha256=sha((run / "result.json").read_bytes())))
                elif mode == "final_missing":
                    final_path.unlink()
                elif mode == "final_duplicate":
                    duplicate = json.loads(final_path.read_bytes()); duplicate["index"] = 2
                    write_new(run / "event-002.json", canonical(duplicate))
                elif mode == "final_scope":
                    rewrite_json(final_path, lambda row: row.update(value={"other": row["value"]["unit"]}))
                else:
                    key, value = {"final_zero": ("tests_ran", 0), "final_boolean": ("tests_ran", True), "final_timeout": ("timed_out", True)}[mode]
                    rewrite_json(final_path, lambda row: row["value"]["unit"].update({key: value}))
                with saved_only_guard(manager):
                    self.assert_refused(root, manager.bundle_preview, run_id)

    def test_partial_and_gapped_review_event_records_are_never_adopted(self):
        for mode in ["review_next", "review_gap", "event_next", "event_gap", "event_index"]:
            with self.subTest(mode=mode), bundle_fixture() as (root, manager, ids):
                run_id, run = ids["python"], manager.run_path(ids["python"])
                if mode.endswith("next"):
                    write_new(run / ("review-001.json.next" if mode == "review_next" else "event-002.json.next"), b"{}\n")
                elif mode == "review_gap":
                    (run / "review-000.json").rename(run / "review-001.json")
                elif mode == "event_gap":
                    (run / "event-001.json").rename(run / "event-002.json")
                else:
                    rewrite_json(run / "event-001.json", lambda row: row.update(index=7))
                with saved_only_guard(manager):
                    self.assert_refused(root, manager.bundle_preview, run_id, codes={"BUNDLE_RECORD_INVALID"})

    def test_active_child_ids_refuse_using_memory_only(self):
        for collection in ["children", "workspace_children"]:
            with self.subTest(collection=collection), bundle_fixture() as (root, manager, ids):
                child = Mock(); child.poll.side_effect = AssertionError("process lookup")
                entries = getattr(manager, collection); entries[ids["python"]] = (child, Mock())
                try:
                    with saved_only_guard(manager):
                        self.assert_refused(root, manager.bundle_preview, ids["python"], codes={"BUNDLE_NOT_REVIEW_READY"})
                    child.poll.assert_not_called()
                finally:
                    entries.pop(ids["python"])

    def test_unknown_and_traversal_ids_refuse_without_touching_records(self):
        with bundle_fixture() as (root, manager, _), saved_only_guard(manager):
            for run_id in [None, "../outside", "/fictional/private/run", "g" * 16, "f" * 16]:
                with self.subTest(run_id=run_id):
                    self.assert_refused(root, manager.bundle_preview, run_id, codes={"BUNDLE_RUN_UNKNOWN"})

    def test_missing_and_oversized_record_sections_refuse(self):
        for section in ["metadata", "task", "result", "review", "event", "patch", "baseline"]:
            for mode in ["missing", "oversized"]:
                with self.subTest(section=section, mode=mode), bundle_fixture() as (root, manager, ids):
                    run_id, run = ids["python"], manager.run_path(ids["python"])
                    target, limit = {"metadata": (manager.meta_path(run_id), 32768),
                        "task": (manager.data / "tasks" / (run_id + ".json"), 262144),
                        "result": (run / "result.json", 262144), "review": (run / "review-000.json", 32768),
                        "event": (run / "event-001.json", 262144), "patch": (run / "changes.diff", 1048576),
                        "baseline": (run / "baseline/arithmetic.py", 32768)}[section]
                    if mode == "missing":
                        target.unlink()
                    else:
                        target.write_bytes(b"x" * (limit + 1))
                    with saved_only_guard(manager):
                        self.assert_refused(root, manager.bundle_preview, run_id,
                            codes={"BUNDLE_RECORD_LIMIT"} if mode == "oversized" else None)

    def test_combined_snapshot_limit_refuses_even_with_matching_record_pins(self):
        with bundle_fixture() as (root, _, _):
            source = root / "oversized-selected-source"
            source.mkdir()
            names = ["arithmetic.py", "extra_a.py", "extra_b.py", "extra_c.py", "test_arithmetic.py"]
            before = {name: b"# old" + b"x" * 32762 + b"\n" for name in names}
            after = {**before, "arithmetic.py": before["arithmetic.py"].replace(b"# old", b"# new", 1)}
            for name, raw in before.items():
                write_new(source / name, raw)
            task = {"format": "outlands-coding-agent-v2", "goal": "Inspect an invented over-limit historical snapshot.",
                    "files": {name: sha(raw) for name, raw in before.items()}, "editable": ["arithmetic.py"],
                    "checks": {"unit": {"kind": "python-unittest", "pattern": "test_arithmetic.py"}},
                    "max_turns": 12, "request_seconds": 120}
            task_path, config_path = root / "oversized-task.json", root / "oversized-config.json"
            write_new(task_path, canonical(task))
            write_new(config_path, canonical({"format": "outlands-workbench-config-v1", "models": [], "projects": [
                {"id": "oversized", "name": "Invented over-limit history", "source": str(source), "task": str(task_path)}]}))
            other = Manager(config_path, root / "oversized-data")
            try:
                run_id = "aaaaaaaaaaaaaaaa"
                _seed_accepted_run(other, run_id, other.projects["oversized"], before, after)
                self.assertTrue(all(len(raw) == 32768 for raw in before.values()))
                self.assertGreater(sum(map(len, before.values())), 131072)
                with saved_only_guard(other):
                    self.assert_refused(root, other.bundle_preview, run_id, codes={"BUNDLE_RECORD_LIMIT"})
            finally:
                other.close()

    def test_review_and_event_inventory_limits_refuse_partial_scans(self):
        for section in ["review", "event"]:
            with self.subTest(section=section), bundle_fixture() as (root, manager, ids):
                run_id, run = ids["python"], manager.run_path(ids["python"])
                maximum = 100 if section == "review" else 256
                start = 1 if section == "review" else 2
                for number in range(start, maximum + 1):
                    value = json.loads((run / "review-000.json").read_bytes()) if section == "review" else {"index": number, "kind": "tool_result", "value": {}}
                    write_new(run / (section + "-%03d.json" % number), canonical(value))
                with saved_only_guard(manager):
                    self.assert_refused(root, manager.bundle_preview, run_id, codes={"BUNDLE_RECORD_LIMIT"})

    def test_event_aggregate_budget_is_bounded(self):
        import workbench
        with bundle_fixture() as (root, manager, ids):
            run_id, run = ids["python"], manager.run_path(ids["python"])
            for number in range(2, 36):
                write_new(run / ("event-%03d.json" % number), canonical({"index": number, "kind": "response", "value": {"content": "x" * 260000}}))
            reader, total = workbench.readiness_read_file, 0

            def count_events(directory, name, *args, **kwargs):
                nonlocal total
                raw = reader(directory, name, *args, **kwargs)
                if Path(directory) == run and str(name).startswith("event-"):
                    total += len(raw)
                return raw

            with saved_only_guard(manager), patch("workbench.readiness_read_file", side_effect=count_events):
                self.assert_refused(root, manager.bundle_preview, run_id, codes={"BUNDLE_RECORD_LIMIT"})
            self.assertLessEqual(total, 8 * 1048576)

    def test_linked_records_and_substituted_store_source_ancestors_are_refused(self):
        for section in ["jobs", "tasks", "runs", "source", "baseline", "work", "review_symlink", "result_hardlink"]:
            with self.subTest(section=section), bundle_fixture() as (root, manager, ids):
                run_id, run = ids["python"], manager.run_path(ids["python"])
                if section in ["review_symlink", "result_hardlink"]:
                    path = run / ("review-000.json" if section == "review_symlink" else "result.json")
                    outside = root / "outside-record.json"; outside.write_bytes(path.read_bytes())
                    path.unlink()
                    if section == "review_symlink":
                        path.symlink_to(outside)
                    else:
                        path.hardlink_to(outside)
                else:
                    path = (manager.data / section if section in ["jobs", "tasks", "runs"] else
                            manager.projects["bundle_python"]["source"] if section == "source" else run / section)
                    retained = root / ("retained-" + section)
                    path.rename(retained)
                    outside = root / ("outside-" + section); outside.mkdir()
                    (outside / "private.txt").write_text(PRIVATE_SENTINEL)
                    path.symlink_to(outside, target_is_directory=True)
                with saved_only_guard(manager):
                    self.assert_refused(root, manager.bundle_preview, run_id)


@contextmanager
def bundle_http_fixture():
    with bundle_fixture() as (root, manager, ids):
        handler_type = make_handler(manager, "invented-bundle-token", "http://127.0.0.1:8765")

        def request(method, path, value=None, headers=None):
            body = canonical(value) if value is not None else b""
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-bundle-token"}
            if method == "POST":
                supplied.update({"Origin": "http://127.0.0.1:8765", "Content-Type": "application/json", "Content-Length": str(len(body))})
            supplied.update(headers or {})
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = method, path
            handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in supplied.items():
                handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            getattr(handler, "do_" + method)()
            head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            lines = head.decode().split("\r\n")
            returned = {key.lower(): value.strip() for key, value in (line.split(":", 1) for line in lines[1:])}
            return int(lines[0].split(" ")[1]), returned, raw

        yield root, manager, ids, request


class BundleHTTPTests(unittest.TestCase):
    def test_preview_then_pinned_binary_download_has_private_no_store_headers(self):
        from patch_bundle import verify_bundle
        with bundle_http_fixture() as (root, manager, ids, request):
            before = private_hashes(root)
            with saved_only_guard(manager):
                code, headers, raw = request("GET", "/api/bundle-preview/" + ids["python"])
                self.assertEqual(code, 200)
                preview = json.loads(raw)
                code, headers, raw = request("POST", "/api/bundle-export", {"id": ids["python"], "bundle_sha256": preview["bundle_sha256"]})
                self.assertEqual(code, 200)
                self.assertEqual(headers["content-type"], "application/zip")
                self.assertEqual(headers["cache-control"], "no-store")
                self.assertIn("outlands-reviewed-bundle-" + ids["python"] + ".zip", headers["content-disposition"])
                self.assertEqual(preview, verify_bundle(raw, preview["bundle_sha256"]))
            self.assertEqual(before, private_hashes(root))

    def test_http_guards_pin_and_request_shape_are_finite_and_read_only(self):
        with bundle_http_fixture() as (root, manager, ids, request):
            before = private_hashes(root)
            with saved_only_guard(manager):
                code, _, raw = request("GET", "/api/bundle-preview/" + ids["python"], headers={"X-Workbench-Token": ""})
                self.assertEqual((code, json.loads(raw)["error"]), (403, "SESSION_REQUIRED"))
                body = {"id": ids["python"], "bundle_sha256": "0" * 64}
                for headers, reason in [({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                                        ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                                        ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"),
                                        ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED"),
                                        ({"Content-Type": "text/plain"}, "JSON_REQUIRED")]:
                    with self.subTest(reason=reason):
                        code, _, raw = request("POST", "/api/bundle-export", body, headers)
                        self.assertIn(code, [403, 409])
                        self.assertEqual(json.loads(raw)["error"], reason)
                for value, reason in [({**body, "private_extra": PRIVATE_SENTINEL}, "BUNDLE_RECORD_INVALID"),
                                      ({"id": ids["python"]}, "BUNDLE_RECORD_INVALID"),
                                      ({**body, "bundle_sha256": "bad"}, "BUNDLE_HASH_REQUIRED"),
                                      (body, "BUNDLE_CHANGED")]:
                    with self.subTest(reason=reason):
                        code, _, raw = request("POST", "/api/bundle-export", value)
                        self.assertEqual(code, 409)
                        self.assertEqual(json.loads(raw)["error"], reason)
                        self.assertNotIn(PRIVATE_SENTINEL, raw.decode())
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()

