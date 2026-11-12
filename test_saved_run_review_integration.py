"""Invented historical evidence review; no live state or execution paths."""

import copy
import json
import os
import stat
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused, canonical, sha, write_new
from test_run_comparison_integration import PRIVATE_SENTINEL, seed_saved_run
from test_run_history_integration import history_guard, history_http_fixture, history_request, open_request
from test_task_presets_integration import build_presets_manager
from workbench import Manager


REVIEW_IDS = {"python_ok": "1" * 16, "python_failed": "2" * 16, "uncertain": "3" * 16,
              "legacy": "4" * 16, "java_ok": "5" * 16, "java_failed": "6" * 16,
              "corrupt": "7" * 16, "running": "8" * 16, "unknown": "9" * 16}


def private_inventory(root):
    rows = {}
    for path in root.rglob("*"):
        info = path.lstat()
        row = {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "links": info.st_nlink}
        if stat.S_ISREG(info.st_mode): row["sha256"] = sha(path.read_bytes())
        elif stat.S_ISLNK(info.st_mode): row["link"] = os.readlink(path)
        rows[path.relative_to(root).as_posix()] = row
    return rows


def populate_review_histories(manager, fixtures):
    """Add nine invented records; no checks, providers or agent are executed."""
    tasks = {}
    for language, fixture in fixtures.items():
        task = copy.deepcopy(manager.projects[fixture["project_id"]]["definition"])
        task["goal"] = "Invented " + language + " historical task " + "x" * 240 + " SAVED-" + language + " café e\u0301 🧪 <b>literal</b>"
        tasks[language] = task
    cases = [("python_ok", "python", "REVIEW_READY", False), ("python_failed", "python", "FAILED", False),
             ("uncertain", "python", "UNCERTAIN", False), ("legacy", "python", "FAILED", True),
             ("java_ok", "java", "REVIEW_READY", False), ("java_failed", "java", "FAILED", False),
             ("corrupt", "python", "FAILED", False), ("running", "python", "RUNNING", False)]
    for number, (name, language, state, legacy) in enumerate(cases):
        fixture = fixtures[language]
        seed_saved_run(manager, REVIEW_IDS[name], tasks[language], project=fixture["project_id"],
                       project_name="Invented " + language + " saved review", state=state,
                       legacy=legacy, created=100 + number)
    corrupt = manager.run_path(REVIEW_IDS["corrupt"])
    (manager.data / "tasks" / (REVIEW_IDS["corrupt"] + ".json")).write_bytes(b"{invented malformed task")
    (corrupt / "result.json").write_bytes(b"{invented malformed result")
    (corrupt / "event-000.json").write_bytes(b"{invented malformed event")
    (corrupt / "changes.diff").write_bytes(b"\xff")
    running = manager.run_path(REVIEW_IDS["running"])
    for name in ["result.json", "changes.diff", "event-002.json", "event-003.json", "event-004.json"]:
        path = running / name
        if path.exists(): path.unlink()
    write_new(manager.meta_path(REVIEW_IDS["unknown"]), canonical({"id": REVIEW_IDS["unknown"],
              "goal": "Invented unknown historical review 🧪", "state": "FUTURE_UNKNOWN"}))
    return dict(REVIEW_IDS)


@contextmanager
def review_fixture(jdk=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "fixture"
        manager, fixtures = build_presets_manager(root, jdk)
        ids = populate_review_histories(manager, fixtures)
        try:
            yield root, manager, fixtures, ids
        finally:
            manager.close()


@contextmanager
def review_guard(manager):
    with history_guard(manager), ExitStack() as stack:
        for name in ["metadata", "result", "comparison_bundle", "comparison_record", "run_history_open"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("saved review reached " + name)))
        yield


def selected_request(manager, run_id):
    searched = manager.run_history_search(history_request(run_id))
    row = next(row for row in searched["runs"] if row["id"] == run_id)
    return open_request(searched, row)


class SavedRunReviewIntegrationTests(unittest.TestCase):
    def refusal(self, root, manager, request, code=None):
        before = private_inventory(root)
        with self.assertRaises(Refused) as caught: manager.run_history_review(request)
        self.assertRegex(str(caught.exception), r"^SAVED_REVIEW_[A-Z_]{1,48}$")
        if code is not None: self.assertEqual(str(caught.exception), code)
        self.assertNotIn(str(root), str(caught.exception))
        self.assertEqual(before, private_inventory(root))

    def test_python_java_review_exact_envelope_preserves_bytes_modes_and_task(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            definitions = copy.deepcopy({key: value["definition"] for key, value in manager.projects.items()})
            before = private_inventory(root)
            for name in ["python_ok", "python_failed", "java_ok", "java_failed"]:
                request = selected_request(manager, ids[name])
                value = manager.run_history_review(request)
                self.assertEqual(set(value), {"version", "id", "record_sha256", "history_sha256", "evidence_sha256", "summary", "diagnostics", "decision"})
                self.assertEqual(value["version"], 2)
                self.assertEqual(value["decision"]["state"], "UNREVIEWED")
                self.assertEqual({key: value[key] for key in request}, request)
                self.assertRegex(value["evidence_sha256"], r"^[0-9a-f]{64}$")
                side = value["summary"]
                self.assertEqual(side["task_integrity"], "MATCH")
                self.assertEqual(side["state"], "FAILED" if "failed" in name else "REVIEW_READY")
                self.assertTrue(side["files"] and side["checks"] and side["baseline_checks"] and side["final_checks"])
                self.assertIn("<b>literal</b>", side["goal"])
                self.assertIn("--- a/", side["patch"]["text"])
                diagnostics = value["diagnostics"]
                self.assertEqual(set(diagnostics), {"version", "reason", "provider_completion", "budget", "requests", "legacy", "notes", "preflight"})
                self.assertNotIn("hold", diagnostics); self.assertNotIn("state", diagnostics)
                self.assertTrue(diagnostics["requests"])
                self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))
                self.assertNotIn(str(root), json.dumps(value))
                self.assertLessEqual(len(canonical(value)), 65536)
            self.assertEqual(definitions, {key: value["definition"] for key, value in manager.projects.items()})
            self.assertEqual(before, private_inventory(root))

    def test_failed_uncertain_running_legacy_corrupt_and_unknown_are_retained_observations(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            before = private_inventory(root)
            values = {name: manager.run_history_review(selected_request(manager, ids[name])) for name in
                      ["python_failed", "uncertain", "running", "legacy", "corrupt", "unknown"]}
            self.assertEqual(values["python_failed"]["summary"]["result_status"], "FAILED")
            self.assertEqual(values["uncertain"]["summary"]["state"], "UNCERTAIN")
            self.assertEqual(values["uncertain"]["diagnostics"]["provider_completion"], "UNKNOWN")
            self.assertEqual(values["running"]["summary"]["state"], "RUNNING")
            self.assertEqual(values["running"]["diagnostics"]["provider_completion"], "UNKNOWN")
            self.assertEqual(values["legacy"]["summary"]["task_integrity"], "NOT_RECORDED")
            self.assertTrue(values["legacy"]["diagnostics"]["legacy"])
            self.assertEqual(values["corrupt"]["summary"]["task_integrity"], "UNAVAILABLE")
            self.assertIn("RECORD_INVALID", values["corrupt"]["summary"]["notes"])
            self.assertIsNone(values["corrupt"]["diagnostics"]["budget"]["limit"])
            unknown = values["unknown"]
            self.assertIsNone(unknown["summary"]["state"])
            self.assertEqual(unknown["diagnostics"]["budget"], {"used": None, "limit": None, "per_request_seconds": None})
            self.assertEqual(before, private_inventory(root))

    def test_current_source_config_task_and_unrelated_hold_are_not_read(self):
        with review_fixture() as (root, manager, fixtures, ids):
            request = selected_request(manager, ids["python_failed"])
            hold = manager.data / "state/hold.json"
            hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented saved-review planning hold", "turn": 1})
            write_new(hold, hold_raw)
            manager.config_path.write_bytes(b"{invented invalid current config")
            fixtures["python"]["task"].write_bytes(b"{invented invalid current task")
            for path in fixtures["python"]["source"].iterdir(): path.unlink()
            fixtures["python"]["source"].rmdir()
            child = Mock(); child.poll.side_effect = AssertionError("saved review polled owned process")
            manager.children[ids["running"]] = (child, Mock())
            try:
                with review_guard(manager):
                    before = private_inventory(root)
                    value = manager.run_history_review(request)
                    self.assertEqual(value["summary"]["result_status"], "FAILED")
                    self.assertEqual(before, private_inventory(root))
                self.assertEqual(hold.read_bytes(), hold_raw)
                child.poll.assert_not_called()
            finally:
                manager.children.clear()

    def test_exact_request_pins_stale_metadata_history_and_missing_id_refuse(self):
        with review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
            request = selected_request(manager, ids["python_ok"])
            for invalid in [{}, [], None, {**request, "extra": True}, {**request, "id": "../outside"},
                            {**request, "id": True}, {**request, "record_sha256": "bad"}, {**request, "history_sha256": None}]:
                self.refusal(root, manager, invalid, "SAVED_REVIEW_INPUT")
            self.refusal(root, manager, {**request, "id": "f" * 16}, "SAVED_REVIEW_NOT_FOUND")
            self.refusal(root, manager, {**request, "record_sha256": "0" * 64}, "SAVED_REVIEW_RECORD_CHANGED")
            self.refusal(root, manager, {**request, "history_sha256": "0" * 64}, "SAVED_REVIEW_HISTORY_CHANGED")
            path = manager.meta_path(ids["python_ok"])
            path.write_bytes(path.read_bytes() + b" \n")
            self.refusal(root, manager, request, "SAVED_REVIEW_HISTORY_CHANGED")

    def test_present_metadata_id_must_match_selected_filename_even_with_current_pins(self):
        for identity in ["f" * 16, True, None]:
            with self.subTest(identity=identity), review_fixture() as (root, manager, fixtures, ids), review_guard(manager):
                run_id = ids["python_ok"]
                path = manager.meta_path(run_id)
                metadata = json.loads(path.read_bytes()); metadata["id"] = identity
                path.write_bytes(canonical(metadata))
                _, history, _ = manager._run_history_inspection()
                request = {"id": run_id, "record_sha256": sha(path.read_bytes()), "history_sha256": history}
                self.refusal(root, manager, request, "SAVED_REVIEW_RECORD_INVALID")

    def test_missing_optional_files_and_selected_run_directory_stay_unknown(self):
        for kind in ["task", "result", "patch", "events", "run"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids):
                run_id = ids["python_ok"]
                run = manager.run_path(run_id)
                if kind == "task": (manager.data / "tasks" / (run_id + ".json")).unlink()
                elif kind == "result": (run / "result.json").unlink()
                elif kind == "patch": (run / "changes.diff").unlink()
                elif kind == "events":
                    for path in run.glob("event-*.json"): path.unlink()
                else:
                    for path in run.iterdir(): path.unlink()
                    run.rmdir()
                with review_guard(manager):
                    before = private_inventory(root)
                    value = manager.run_history_review(selected_request(manager, run_id))
                    self.assertIn("RECORD_MISSING", value["summary"]["notes"])
                    if kind == "task":
                        self.assertEqual(value["summary"]["task_integrity"], "UNAVAILABLE")
                        self.assertIsNone(value["diagnostics"]["budget"]["limit"])
                    self.assertEqual(before, private_inventory(root))

    def test_malformed_optional_json_utf8_and_fingerprints_are_not_repaired(self):
        for kind in ["task", "result", "event", "patch", "task-hash", "patch-hash"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids):
                run_id = ids["python_ok"]; run = manager.run_path(run_id)
                if kind == "task": (manager.data / "tasks" / (run_id + ".json")).write_bytes(b"{malformed")
                elif kind == "result": (run / "result.json").write_bytes(b"[]")
                elif kind == "event": (run / "event-000.json").write_bytes(b"\xff")
                elif kind == "patch": (run / "changes.diff").write_bytes(b"\xff")
                elif kind == "task-hash":
                    path = manager.data / "tasks" / (run_id + ".json")
                    task = json.loads(path.read_bytes()); task["goal"] += " changed saved bytes"; path.write_bytes(canonical(task))
                else: (run / "changes.diff").write_bytes(b"--- invented changed patch\n")
                with review_guard(manager):
                    before = private_inventory(root)
                    value = manager.run_history_review(selected_request(manager, run_id))
                    if kind == "task-hash": self.assertEqual(value["summary"]["task_integrity"], "MISMATCH")
                    elif kind == "patch-hash": self.assertIs(value["summary"]["patch"]["matches_recorded"], False)
                    else: self.assertIn("RECORD_INVALID", value["summary"]["notes"])
                    self.assertEqual(before, private_inventory(root))

    def test_unsafe_task_result_event_patch_files_refuse_without_fallback(self):
        for field in ["task", "result", "event", "patch"]:
            for kind in ["mode", "symlink", "hardlink", "directory"]:
                with self.subTest(field=field, kind=kind), review_fixture() as (root, manager, fixtures, ids):
                    run_id = ids["python_ok"]; run = manager.run_path(run_id)
                    path = manager.data / "tasks" / (run_id + ".json") if field == "task" else run / {
                        "result": "result.json", "event": "event-000.json", "patch": "changes.diff"}[field]
                    if kind == "mode": path.chmod(0o640)
                    elif kind == "hardlink": os.link(path, root / "invented-evidence-link")
                    elif kind == "symlink":
                        other = root / "invented-evidence-copy"; write_new(other, path.read_bytes()); path.unlink(); path.symlink_to(other)
                    else: path.unlink(); path.mkdir(mode=0o700)
                    with review_guard(manager):
                        self.refusal(root, manager, selected_request(manager, run_id), "SAVED_REVIEW_STORE_UNSAFE")

    def test_unsafe_missing_and_substituted_store_directories_refuse(self):
        for field in ["tasks", "runs", "selected"]:
            for kind in ["mode", "symlink", "missing"]:
                if field == "selected" and kind == "missing": continue
                with self.subTest(field=field, kind=kind), review_fixture() as (root, manager, fixtures, ids):
                    path = manager.run_path(ids["python_ok"]) if field == "selected" else manager.data / field
                    if kind == "mode": path.chmod(0o750)
                    else:
                        moved = root / "invented-original-directory"
                        path.rename(moved)
                        if kind == "symlink": path.symlink_to(moved, target_is_directory=True)
                    with review_guard(manager):
                        self.refusal(root, manager, selected_request(manager, ids["python_ok"]), "SAVED_REVIEW_STORE_UNSAFE")

    def test_optional_record_size_limits_return_notes_with_bounded_prefix_pins(self):
        for field in ["task", "result", "event", "patch"]:
            with self.subTest(field=field), review_fixture() as (root, manager, fixtures, ids):
                run_id = ids["python_ok"]; run = manager.run_path(run_id)
                path = manager.data / "tasks" / (run_id + ".json") if field == "task" else run / {
                    "result": "result.json", "event": "event-000.json", "patch": "changes.diff"}[field]
                limit = 262144 if field == "event" else 65536 if field == "patch" else 32768
                raw = path.read_bytes(); path.write_bytes(raw + b" " * (limit + 1 - len(raw)))
                with review_guard(manager):
                    before = private_inventory(root)
                    value = manager.run_history_review(selected_request(manager, run_id))
                    self.assertIn("RECORD_LIMIT", value["summary"]["notes"])
                    self.assertRegex(value["evidence_sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(before, private_inventory(root))

    def test_event_count_and_malformed_names_are_bounded_and_disclosed(self):
        with review_fixture() as (root, manager, fixtures, ids):
            run_id = ids["python_ok"]; run = manager.run_path(run_id)
            for number in range(300, 557):
                write_new(run / ("event-%03d.json" % number), canonical({"index": number, "kind": "invented", "value": {}}))
            write_new(run / "event-malformed.json", b"not parsed or read")
            with review_guard(manager):
                before = private_inventory(root)
                value = manager.run_history_review(selected_request(manager, run_id))
                self.assertIn("EVENT_LIMIT", value["summary"]["notes"])
                self.assertEqual(before, private_inventory(root))
        with review_fixture() as (root, manager, fixtures, ids):
            run = manager.run_path(ids["python_ok"])
            write_new(run / "event-malformed.json", b"\xff")
            with review_guard(manager):
                value = manager.run_history_review(selected_request(manager, ids["python_ok"]))
                self.assertIn("RECORD_INVALID", value["summary"]["notes"])

    def test_event_aggregate_actual_read_bytes_stay_within_each_inspection_budget(self):
        with review_fixture() as (root, manager, fixtures, ids):
            run_id = ids["python_ok"]; run = manager.run_path(run_id)
            for number in range(100, 109):
                raw = canonical({"index": number, "kind": "invented", "value": {}})
                write_new(run / ("event-%03d.json" % number), raw + b" " * (262144 - len(raw)))
            original_read = manager._saved_run_review_file
            original_inspect = manager._saved_run_review_inspection
            reads, per_inspection = [], []
            def observed(fd, name, limit):
                value = original_read(fd, name, limit)
                raw = value[0]
                if name.startswith("event-"):
                    reads.append((limit, 0 if raw is None else len(raw)))
                return value
            def inspected(*args, **kwargs):
                start = len(reads)
                value = original_inspect(*args, **kwargs)
                per_inspection.append(reads[start:])
                return value
            with review_guard(manager), patch.object(manager, "_saved_run_review_file", side_effect=observed), patch.object(
                    manager, "_saved_run_review_inspection", side_effect=inspected):
                before = private_inventory(root)
                value = manager.run_history_review(selected_request(manager, run_id))
                self.assertIn("EVENT_LIMIT", value["summary"]["notes"])
                self.assertEqual(len(per_inspection), 2)
                for rows in per_inspection:
                    self.assertLessEqual(len(rows), 256)
                    self.assertLessEqual(sum(actual for _, actual in rows), 2097152)
                    self.assertTrue(all(0 <= limit <= 262144 and actual <= limit + 1 for limit, actual in rows))
                self.assertEqual(before, private_inventory(root))

    def test_admitted_unread_events_are_safe_and_pinned_after_byte_budget_exhaustion(self):
        import workbench
        for kind in ["mode", "symlink", "hardlink", "directory", "inplace-drift"]:
            with self.subTest(kind=kind), review_fixture() as (root, manager, fixtures, ids):
                run_id = ids["python_ok"]; run = manager.run_path(run_id)
                for number in range(100, 109):
                    raw = canonical({"index": number, "kind": "invented", "value": {}})
                    write_new(run / ("event-%03d.json" % number), raw + b" " * (262144 - len(raw)))
                unread = run / "event-999.json"
                write_new(unread, canonical({"index": 999, "kind": "invented", "value": {}}))
                if kind == "mode": unread.chmod(0o640)
                elif kind == "hardlink": os.link(unread, root / "invented-unread-link")
                elif kind == "symlink":
                    other = root / "invented-unread-copy"; write_new(other, unread.read_bytes())
                    unread.unlink(); unread.symlink_to(other)
                elif kind == "directory": unread.unlink(); unread.mkdir(mode=0o700)
                request = selected_request(manager, run_id)
                original_read, original_review = manager._saved_run_review_file, workbench.review_saved_run
                calls = []
                inode = unread.lstat().st_ino
                def observe(fd, name, limit):
                    calls.append((name, limit))
                    result = original_read(fd, name, limit)
                    if name == unread.name:
                        self.assertEqual(limit, 0)
                        self.assertEqual(result[0], b"")
                        self.assertIsNotNone(result[1])
                    return result
                def drift(*args, **kwargs):
                    result = original_review(*args, **kwargs)
                    if kind == "inplace-drift": unread.write_bytes(unread.read_bytes() + b" \n")
                    return result
                with review_guard(manager), patch.object(manager, "_saved_run_review_file", side_effect=observe), patch(
                        "workbench.review_saved_run", side_effect=drift) as pure:
                    if kind == "inplace-drift":
                        with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_EVIDENCE_CHANGED$"):
                            manager.run_history_review(request)
                        self.assertEqual(unread.stat().st_ino, inode)
                        self.assertEqual(calls.count((unread.name, 0)), 2)
                        pure.assert_called_once()
                    else:
                        self.refusal(root, manager, request, "SAVED_REVIEW_STORE_UNSAFE")
                        pure.assert_not_called()
                    self.assertIn((unread.name, 0), calls)

    def test_malformed_event_prefix_with_bad_extension_is_not_read_but_name_is_pinned(self):
        import workbench
        with review_fixture() as (root, manager, fixtures, ids):
            run_id = ids["python_ok"]; run = manager.run_path(run_id)
            malformed = run / "event-001.txt"
            write_new(malformed, b"\xff invented malformed event filename")
            original_read, original_review = manager._saved_run_review_file, workbench.review_saved_run
            names = []
            def observe(fd, name, limit):
                names.append(name)
                return original_read(fd, name, limit)
            with review_guard(manager), patch.object(manager, "_saved_run_review_file", side_effect=observe):
                request = selected_request(manager, run_id)
                before = private_inventory(root)
                value = manager.run_history_review(request)
                self.assertIn("RECORD_INVALID", value["summary"]["notes"])
                self.assertNotIn(malformed.name, names)
                self.assertEqual(before, private_inventory(root))
                def rename(*args, **kwargs):
                    result = original_review(*args, **kwargs)
                    malformed.rename(run / "event-001.backup")
                    return result
                with patch("workbench.review_saved_run", side_effect=rename):
                    with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_EVIDENCE_CHANGED$"):
                        manager.run_history_review(request)
                self.assertNotIn("event-001.txt", names)
                self.assertNotIn("event-001.backup", names)

    def test_run_directory_enumeration_bound_discloses_partial_event_catalog(self):
        with review_fixture() as (root, manager, fixtures, ids):
            run_id = ids["python_ok"]; run = manager.run_path(run_id)
            for number in range(1025): write_new(run / ("invented-ignored-" + str(number)), b"Not event evidence")
            with review_guard(manager):
                before = private_inventory(root)
                value = manager.run_history_review(selected_request(manager, run_id))
                self.assertIn("EVENT_LIMIT", value["summary"]["notes"])
                self.assertEqual(before, private_inventory(root))

    def test_metadata_history_and_each_saved_evidence_change_after_pure_review_refuse(self):
        import workbench
        for field in ["metadata", "other-metadata", "task", "result", "event", "patch", "new-event"]:
            with self.subTest(field=field), review_fixture() as (root, manager, fixtures, ids):
                run_id = ids["python_ok"]; run = manager.run_path(run_id)
                request = selected_request(manager, run_id)
                original = workbench.review_saved_run
                def drift(*args, **kwargs):
                    value = original(*args, **kwargs)
                    if field == "metadata": path = manager.meta_path(run_id)
                    elif field == "other-metadata": path = manager.meta_path(ids["java_failed"])
                    elif field == "task": path = manager.data / "tasks" / (run_id + ".json")
                    elif field == "new-event":
                        write_new(run / "event-009.json", canonical({"index": 9, "kind": "invented", "value": {}}))
                        return value
                    else: path = run / {"result": "result.json", "event": "event-000.json", "patch": "changes.diff"}[field]
                    path.write_bytes(path.read_bytes() + b" \n")
                    return value
                with review_guard(manager), patch("workbench.review_saved_run", side_effect=drift):
                    with self.assertRaises(Refused) as caught: manager.run_history_review(request)
                self.assertEqual(str(caught.exception), "SAVED_REVIEW_HISTORY_CHANGED" if "metadata" in field else "SAVED_REVIEW_EVIDENCE_CHANGED")

    def test_equal_byte_directory_swap_during_review_is_not_a_stable_snapshot(self):
        import workbench
        for field in ["selected", "tasks"]:
            with self.subTest(field=field), review_fixture() as (root, manager, fixtures, ids):
                request = selected_request(manager, ids["python_ok"])
                directory = manager.run_path(ids["python_ok"]) if field == "selected" else manager.data / "tasks"
                original = workbench.review_saved_run
                def swap(*args, **kwargs):
                    value = original(*args, **kwargs)
                    moved = root / "invented-retained-directory"
                    directory.rename(moved); directory.mkdir(mode=0o700)
                    for path in moved.iterdir(): write_new(directory / path.name, path.read_bytes())
                    return value
                with review_guard(manager), patch("workbench.review_saved_run", side_effect=swap):
                    with self.assertRaisesRegex(Refused, "^SAVED_REVIEW_EVIDENCE_CHANGED$"):
                        manager.run_history_review(request)

    def test_restart_review_reproduces_exact_pins_without_private_record_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manager, fixtures = build_presets_manager(root)
            ids = populate_review_histories(manager, fixtures)
            try:
                with review_guard(manager):
                    request = selected_request(manager, ids["java_failed"])
                    value = manager.run_history_review(request)
                before = private_inventory(root)
                config, data = manager.config_path, manager.data
                manager.close(); manager = None
                manager = Manager(config, data)
                with review_guard(manager):
                    self.assertEqual(manager.run_history_review(selected_request(manager, ids["java_failed"])), value)
                self.assertEqual(before, private_inventory(root))
            finally:
                if manager is not None: manager.close()


class SavedRunReviewHTTPTests(unittest.TestCase):
    def test_http_explicit_single_review_preserves_search_open_and_all_evidence(self):
        with history_http_fixture() as (root, manager, ids, request), review_guard(manager):
            selected = selected_request(manager, ids["java_failed"])
            before = private_inventory(root)
            code, value = request("/api/run-history-review", selected)
            self.assertEqual((code, value["summary"]["result_status"]), (200, "FAILED"))
            self.assertEqual({key: value[key] for key in selected}, selected)
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(value))
            self.assertEqual(before, private_inventory(root))

    def test_http_session_origin_strict_framing_and_short_body_precede_review(self):
        with history_http_fixture() as (root, manager, ids, request):
            value = {"invented": "request"}
            with patch.object(manager, "run_history_review", side_effect=AssertionError("bad request reached saved review")) as action:
                for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": "0"}, {"Content-Length": "-1"},
                    {"Content-Length": "32769"}, {"Content-Length": "999"}, {"Content-Type": "application/zip"},
                    [("Content-Length", str(len(canonical(value))))], [("Content-Type", "application/json")]]:
                    code, result = request("/api/run-history-review", value, headers)
                    self.assertEqual(code, 409); self.assertRegex(result["error"], r"^SAVED_REVIEW_[A-Z_]+$")
                for headers, error in [({"Host": "untrusted.invalid"}, "HOST_REFUSED"),
                    ({"Origin": "https://untrusted.invalid"}, "ORIGIN_REFUSED"), ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                    ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                    code, result = request("/api/run-history-review", value, headers)
                    self.assertEqual((code, result["error"]), (409, error))
                action.assert_not_called()

    def test_http_duplicate_json_invalid_utf8_schema_and_output_caps_refuse(self):
        with history_http_fixture() as (root, manager, ids, request):
            for raw in [b'{"id":"x","id":"y"}', b"\xff", b"[]"]:
                before = private_inventory(root)
                code, result = request("/api/run-history-review", {}, raw=raw)
                self.assertEqual(code, 409); self.assertRegex(result["error"], r"^SAVED_REVIEW_[A-Z_]+$")
                self.assertEqual(before, private_inventory(root))
            with patch.object(manager, "run_history_review", return_value={"invented": "x" * 65536}):
                code, result = request("/api/run-history-review", {})
                self.assertEqual((code, result["error"]), (409, "SAVED_REVIEW_OUTPUT_LIMIT"))


if __name__ == "__main__":
    unittest.main()
