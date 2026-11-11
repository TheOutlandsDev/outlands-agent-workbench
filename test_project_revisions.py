"""Offline refresh tests on invented temporary Python and Java source only."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Refused, read_file, sha, validate_task
from project_revisions import refresh_task


def task_for(source, files, *, java=False):
    for path, raw in files.items():
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    if java:
        editable = ["sample/Value.java"]
        checks = {"unit": {"kind": "java-main", "sources": list(files),
                           "main_class": "sample.ValueTest"}}
    else:
        editable = ["module.py"]
        checks = {"unit": "test_module.py"}
    return validate_task({
        "format": "outlands-coding-agent-v2" if java else "outlands-coding-agent-v1",
        "goal": "Inspect the invented value.",
        "files": {name: sha(raw) for name, raw in files.items()},
        "editable": editable,
        "checks": checks,
        "max_turns": 3,
        "request_seconds": 17,
    })


def python_task(source):
    return task_for(source, {
        "test_module.py": b"import unittest\n# Invented protected entrypoint.\n",
        "module.py": b"def value():\n    return 1\n",
    })


class RefreshTests(unittest.TestCase):
    def assert_refused(self, code, source, task, goal):
        with self.assertRaises(Refused) as caught:
            refresh_task(source, task, goal)
        self.assertEqual(caught.exception.args, (code,))

    def assert_preserved_scope(self, before, candidate):
        self.assertEqual(set(candidate), set(before))
        self.assertEqual(list(candidate["files"]), list(before["files"]))
        for field in ("format", "editable", "checks", "max_turns", "request_seconds"):
            self.assertEqual(candidate[field], before[field])

    def test_python_v1_changed_editable_file_has_exact_sorted_review_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            before = copy.deepcopy(task)
            changed = b"def value():\n    return 2\n"
            (source / "module.py").write_bytes(changed)
            candidate, rows = refresh_task(source, task, task["goal"])
            self.assertEqual([row["path"] for row in rows], ["module.py", "test_module.py"])
            self.assertEqual(rows[0], {
                "path": "module.py", "bytes": len(changed),
                "old_sha256": task["files"]["module.py"], "sha256": sha(changed),
                "editable": True, "changed": True,
            })
            protected = (source / "test_module.py").read_bytes()
            self.assertEqual(rows[1], {
                "path": "test_module.py", "bytes": len(protected),
                "old_sha256": sha(protected), "sha256": sha(protected),
                "editable": False, "changed": False,
            })
            self.assertEqual(candidate["files"]["module.py"], sha(changed))
            self.assertEqual(candidate["goal"], task["goal"])
            self.assertEqual(task, before)
            self.assert_preserved_scope(before, candidate)

    def test_java_v2_refresh_preserves_nested_check_spec_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = task_for(source, {
                "sample/ValueTest.java": b"package sample;\nclass ValueTest { public static void main(String[] args) {} }\n",
                "sample/Value.java": b"package sample;\nclass Value { static int value() { return 1; } }\n",
            }, java=True)
            before = copy.deepcopy(task)
            changed = b"package sample;\nclass Value { static int value() { return 2; } }\n"
            (source / "sample/Value.java").write_bytes(changed)
            candidate, rows = refresh_task(source, task, "Review the revised Java value.")
            self.assertEqual(candidate["format"], "outlands-coding-agent-v2")
            self.assertEqual([row["path"] for row in rows], ["sample/Value.java", "sample/ValueTest.java"])
            self.assertEqual([row["changed"] for row in rows], [True, False])
            self.assertEqual(candidate["files"]["sample/Value.java"], sha(changed))
            self.assert_preserved_scope(before, candidate)
            self.assertEqual(task, before)
            self.assertIsNot(candidate["checks"], task["checks"])
            self.assertIsNot(candidate["checks"]["unit"]["sources"], task["checks"]["unit"]["sources"])

    def test_protected_file_change_is_visible_and_remains_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            raw = b"import unittest\n# Owner revised the protected entrypoint.\n"
            (source / "test_module.py").write_bytes(raw)
            candidate, rows = refresh_task(source, task, task["goal"])
            row = next(row for row in rows if row["path"] == "test_module.py")
            self.assertTrue(row["changed"])
            self.assertFalse(row["editable"])
            self.assertEqual(row["sha256"], sha(raw))
            self.assertEqual(candidate["files"]["test_module.py"], sha(raw))
            self.assertEqual(candidate["editable"], ["module.py"])
            self.assertEqual(candidate["checks"], task["checks"])

    def test_no_changes_refused_but_goal_only_revision_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            before = copy.deepcopy(task)
            self.assert_refused("REFRESH_NO_CHANGES", source, task, task["goal"])
            candidate, rows = refresh_task(source, task, "A new goal only.")
            self.assertEqual(candidate["goal"], "A new goal only.")
            self.assertEqual(candidate["files"], task["files"])
            self.assertTrue(all(not row["changed"] for row in rows))
            self.assertEqual(task, before)
            self.assert_preserved_scope(before, candidate)

    def test_goal_validation_happens_before_reads_and_preserves_exact_text(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            for goal in ("", "x" * 2001, None, True, 3, []):
                with self.subTest(goal=repr(goal)), \
                        patch("project_revisions.read_file", side_effect=AssertionError("unexpected read")):
                    self.assert_refused("GOAL_LIMIT", source, task, goal)
            for goal in ("x", "😀" * 2000, "  preserve this spacing  "):
                with self.subTest(length=len(goal)):
                    candidate, _ = refresh_task(source, task, goal)
                    self.assertEqual(candidate["goal"], goal)

    def test_old_task_is_validated_before_new_goal_or_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            valid = python_task(source)
            for field, value, code in (("goal", "", "GOAL_LIMIT"),
                                       ("editable", ["test_module.py"], "CHECK_PROTECTED"),
                                       ("max_turns", True, "TURN_LIMIT"),
                                       ("request_seconds", 121, "TIME_LIMIT")):
                task = copy.deepcopy(valid)
                task[field] = value
                with self.subTest(field=field), \
                        patch("project_revisions.read_file", side_effect=AssertionError("unexpected read")):
                    self.assert_refused(code, source, task, "New valid goal.")

    def test_bad_paths_hashes_and_scope_are_refused_without_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            valid = python_task(source)
            for task, code in (
                ({**valid, "files": {"../outside.py": "a" * 64}}, "INVALID_PATH"),
                ({**valid, "files": {"module.py": "private invalid hash"}}, "INVALID_HASH"),
                ({**valid, "editable": ["undeclared.py"]}, "EDITABLE_SCOPE"),
                ({**valid, "files": {str(i) + ".py": "a" * 64 for i in range(33)}}, "FILES_LIMIT"),
                ({**valid, "extra": "unrecognized"}, "TASK_FIELDS"),
            ):
                with self.subTest(code=code), \
                        patch("project_revisions.read_file", side_effect=AssertionError("unexpected read")):
                    self.assert_refused(code, source, task, "New valid goal.")

    def test_reads_only_declared_files_in_sorted_order_without_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            (source / "unselected.py").write_bytes(b"\xff\x00")
            (source / "unselected-link.py").symlink_to(source / "unselected.py")
            with patch("project_revisions.read_file", wraps=read_file) as reader, \
                    patch("os.scandir", side_effect=AssertionError("directory scan")), \
                    patch("os.listdir", side_effect=AssertionError("directory listing")), \
                    patch("os.walk", side_effect=AssertionError("directory walk")), \
                    patch("pathlib.Path.iterdir", side_effect=AssertionError("directory iteration")), \
                    patch("pathlib.Path.glob", side_effect=AssertionError("directory glob")), \
                    patch("pathlib.Path.rglob", side_effect=AssertionError("recursive glob")):
                candidate, rows = refresh_task(source, task, "Updated goal.")
            self.assertEqual([call.args for call in reader.call_args_list],
                             [(source, "module.py"), (source, "test_module.py")])
            self.assertEqual(set(candidate["files"]), set(task["files"]))
            self.assertEqual(len(rows), 2)

    def test_candidate_and_rows_cannot_mutate_original_task_or_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            before = copy.deepcopy(task)
            raw_before = {name: (source / name).read_bytes() for name in task["files"]}
            candidate, rows = refresh_task(source, task, "Updated goal.")
            candidate["files"]["module.py"] = "0" * 64
            candidate["editable"].append("invented.py")
            candidate["checks"]["other"] = "test_module.py"
            rows[0]["path"] = "changed result"
            self.assertEqual(task, before)
            self.assertEqual({name: (source / name).read_bytes() for name in task["files"]}, raw_before)

    def test_invalid_utf8_is_a_fixed_refusal_and_does_not_mutate_task(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            before = copy.deepcopy(task)
            (source / "module.py").write_bytes(b"private-prefix\xff")
            self.assert_refused("REFRESH_UTF8", source, task, "Updated goal.")
            self.assertEqual(task, before)

    def test_nul_and_oversized_file_use_existing_guard_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            for raw, code in ((b"binary\x00input", "BINARY_INPUT"),
                              (b"x" * 32769, "FILE_LIMIT")):
                with self.subTest(code=code):
                    (source / "module.py").write_bytes(raw)
                    self.assert_refused(code, source, task, "Updated goal.")

    def test_aggregate_limit_and_exact_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            files = {"module.py": b"x" * 32768, "test_module.py": b"y" * 32768,
                     "extra_a.py": b"z" * 32768, "extra_b.py": b"w" * 32768}
            task = task_for(source, files)
            candidate, rows = refresh_task(source, task, "Updated goal.")
            self.assertEqual(sum(row["bytes"] for row in rows), 131072)
            self.assertEqual(candidate["files"], task["files"])
            (source / "extra_c.py").write_bytes(b"x")
            task["files"]["extra_c.py"] = sha(b"x")
            before = copy.deepcopy(task)
            self.assert_refused("REFRESH_SNAPSHOT_LIMIT", source, task, "Updated goal.")
            self.assertEqual(task, before)

    def test_declared_symlink_and_missing_file_preserve_existing_os_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            (source / "module.py").unlink()
            with self.assertRaises(FileNotFoundError):
                refresh_task(source, task, "Updated goal.")
            (source / "other.py").write_bytes(b"invented")
            (source / "module.py").symlink_to(source / "other.py")
            with self.assertRaises(OSError):
                refresh_task(source, task, "Updated goal.")

    def test_hardlinked_and_nonregular_declared_files_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            (source / "hard.py").hardlink_to(source / "module.py")
            self.assert_refused("INPUT_TYPE", source, task, "Updated goal.")
            (source / "module.py").unlink()
            os.mkfifo(source / "module.py")
            self.assert_refused("INPUT_TYPE", source, task, "Updated goal.")

    def test_symlinked_root_and_parent_directory_are_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "real"
            source.mkdir()
            task = python_task(source)
            alias = root / "alias"
            alias.symlink_to(source, target_is_directory=True)
            with self.assertRaises(OSError):
                refresh_task(alias, task, "Updated goal.")
            (source / "nested").symlink_to(source, target_is_directory=True)
            task["files"]["nested/module.py"] = task["files"]["module.py"]
            with self.assertRaises(OSError):
                refresh_task(source, task, "Updated goal.")

    def test_hashes_cover_original_complete_bytes_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            raw = b"def value():\r\n    return 1\r\n"
            (source / "module.py").write_bytes(raw)
            candidate, rows = refresh_task(source, task, task["goal"])
            self.assertEqual(candidate["files"]["module.py"], sha(raw))
            self.assertTrue(rows[0]["changed"])
            self.assertEqual(rows[0]["bytes"], len(raw))
            self.assertEqual((source / "module.py").read_bytes(), raw)

    def test_refresh_does_not_execute_source_or_start_checks_or_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            task = python_task(source)
            (source / "module.py").write_bytes(b"raise RuntimeError('source stays text')\n")
            with patch("builtins.exec", side_effect=AssertionError("source execution")), \
                    patch("builtins.eval", side_effect=AssertionError("source evaluation")), \
                    patch("subprocess.Popen", side_effect=AssertionError("process start")), \
                    patch("subprocess.run", side_effect=AssertionError("process run")), \
                    patch("agent.isolated_check", side_effect=AssertionError("Python check")), \
                    patch("agent.isolated_java_check", side_effect=AssertionError("Java check")):
                candidate, rows = refresh_task(source, task, "Updated goal.")
            self.assertTrue(rows[0]["changed"])
            self.assertEqual(candidate["goal"], "Updated goal.")


if __name__ == "__main__":
    unittest.main()
