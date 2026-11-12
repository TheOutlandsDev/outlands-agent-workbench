"""Invented exact edits and real filesystem guards, without executing any checks."""

import copy
import os
import stat
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, sha
from snapshot_recheck import inspect
from test_snapshot_recheck import fixture, tree
import snapshot_editor as editor


@contextmanager
def edit_fixture(*, java=False, content=None):
    with fixture(java=java) as (root, data, job, source, task, before, after):
        name = "sample/Main.java" if java else "main.py"
        path = job / "workspace/review" / name
        path.chmod(0o600)
        if content is not None:
            path.write_bytes(content)
        edit = data / "snapshot-workspace-edits" / ("b" * 16)
        edit.mkdir(mode=0o700, parents=True)
        yield root, job, source, task, name, path, edit


@contextmanager
def no_execution():
    with ExitStack() as stack:
        for name in ("subprocess.Popen", "subprocess.run", "git_workspace.git", "agent.Session.checks",
                     "isolation.check", "java_check.check"):
            stack.enter_context(patch(name, side_effect=AssertionError("editor executed " + name)))
        yield


class SnapshotEditorTests(unittest.TestCase):
    def refused(self, fn, *args, suffix=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            fn(*args, **kwargs)
        self.assertIn(str(caught.exception), editor.CODES)
        if suffix is not None:
            self.assertEqual(str(caught.exception), "SNAPSHOT_EDITOR_" + suffix)
        return str(caught.exception)

    def test_read_exact_python_java_and_readonly(self):
        for java in (False, True):
            with self.subTest(java=java), edit_fixture(java=java) as (root, job, _, _, name, path, _):
                inspected, before = inspect(job), tree(root)
                with no_execution():
                    result = editor.read(inspected, name)
                self.assertEqual(result["text"].encode(), path.read_bytes())
                self.assertEqual(result["sha256"], sha(path.read_bytes()))
                self.assertEqual(result["bytes"], len(path.read_bytes()))
                self.assertEqual(result["snapshot_sha256"], inspected["summary"]["snapshot_sha256"])
                self.assertTrue(result["editable"])
                self.assertFalse(result["source_applied"])
                self.assertEqual(before, tree(root))

    def test_line_endings_are_observed_without_normalization(self):
        for raw, kind in ((b"a\nb\n", "LF"), (b"a\r\nb\r\n", "CRLF"), (b"a\r\nb\n", "MIXED"),
                          (b"a\rb", "MIXED"), (b"a", "NONE"), (b"", "NONE")):
            with self.subTest(kind=kind), edit_fixture(content=raw) as (_, job, _, _, name, _, _):
                value = editor.read(inspect(job), name)
                self.assertEqual(value["text"].encode(), raw)
                self.assertEqual(value["line_endings"], kind)

    def test_preview_preserves_unicode_crlf_whitespace_and_missing_final_newline(self):
        raw = "# café\r\ndef value():\r\n\treturn 2  # 雪".encode()
        with edit_fixture(content=raw) as (root, job, _, _, name, _, _):
            inspected, before = inspect(job), tree(root)
            with no_execution():
                result = editor.prepare(inspected, name, sha(raw), "return 2", "return 3")
            self.assertEqual(result["original"], raw)
            self.assertEqual(result["candidate"], raw.replace(b"return 2", b"return 3"))
            self.assertIn("café", result["summary"]["diff"]["text"])
            self.assertEqual(result["summary"]["before_sha256"], sha(raw))
            self.assertEqual(result["summary"]["after_sha256"], sha(result["candidate"]))
            self.assertEqual(before, tree(root))

    def test_scope_and_protected_refusals(self):
        with edit_fixture() as (_, job, _, _, name, _, _):
            inspected = inspect(job)
            for path in ("../main.py", "/main.py", "main.py/..", "./main.py", "a//b", ".git", "other-private.py", "a/.git/config", "a\\b", None):
                self.refused(editor.read, inspected, path, suffix="SCOPE")
            self.refused(editor.read, inspected, "test_main.py", suffix="PROTECTED")
            self.refused(editor.prepare, inspected, "test_main.py", "a" * 64, "x", "y", suffix="PROTECTED")
            self.assertEqual(editor.read(inspected, name)["path"], name)

    def test_stale_and_invalid_expected_hash(self):
        with edit_fixture() as (_, job, _, _, name, path, _):
            inspected = inspect(job)
            self.refused(editor.prepare, inspected, name, "0" * 64, "return 2", "return 3", suffix="STALE")
            for bad in (None, "A" * 64, "a" * 63, 7):
                self.refused(editor.prepare, inspected, name, bad, "return 2", "return 3", suffix="INPUT")
            self.assertEqual(editor.read(inspected, name)["sha256"], sha(path.read_bytes()))

    def test_text_search_noop_and_overlap_refusals(self):
        with edit_fixture(content=b"aaa unique aaa\n") as (_, job, _, _, name, path, _):
            inspected, pin = inspect(job), sha(path.read_bytes())
            self.refused(editor.prepare, inspected, name, pin, "", "new", suffix="SEARCH_REQUIRED")
            for old in ("not present", "aaa", "aa"):
                self.refused(editor.prepare, inspected, name, pin, old, "new", suffix="SEARCH_NOT_UNIQUE")
            self.refused(editor.prepare, inspected, name, pin, "unique", "unique", suffix="NO_CHANGE")
            for old, new in (("unique", "x\x00"), ("unique", "\ud800"), ("unique", None), (None, "x"), ("\ud800", "x")):
                self.refused(editor.prepare, inspected, name, pin, old, new, suffix="TEXT_INVALID")
        with edit_fixture(content=b"aaa") as (_, job, _, _, name, path, _):
            self.refused(editor.prepare, inspect(job), name, sha(path.read_bytes()), "aa", "x", suffix="SEARCH_NOT_UNIQUE")

    def test_replacement_may_delete_one_span_without_reformatting(self):
        with edit_fixture(content=b"before\r\nREMOVE\r\nafter") as (_, job, _, _, name, path, _):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "REMOVE\r\n", "")
            self.assertEqual(prepared["candidate"], b"before\r\nafter")

    def test_file_and_aggregate_size_limits(self):
        with edit_fixture(content=b"x") as (_, job, _, _, name, path, _):
            inspected = inspect(job)
            self.refused(editor.prepare, inspected, name, sha(path.read_bytes()), "x", "a" * 32769, suffix="LIMIT")
            large = copy.deepcopy(inspected)
            large["selected_bytes"] = {"main.py": b"X" + b"a" * 32759, "one.py": b"a" * 32768,
                                       "two.py": b"a" * 32768, "three.py": b"a" * 32768, "test_main.py": b"a" * 8}
            large["task"]["files"] = {name: sha(raw) for name, raw in large["selected_bytes"].items()}
            large["summary"]["files"] = [{"path": name, "bytes": len(raw), "current_sha256": sha(raw),
                                             "editable": name == "main.py"} for name, raw in large["selected_bytes"].items()]
            self.refused(editor.prepare, large, "main.py", sha(large["selected_bytes"]["main.py"]), "X", "XX", suffix="LIMIT")

    def test_diff_clipping_has_unicode_and_line_bounds(self):
        raw = ("#" + "雪" * 6000 + "\nreturn 2\n").encode()
        with edit_fixture(content=raw) as (_, job, _, _, name, path, _):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            value = prepared["summary"]["diff"]
            self.assertTrue(value["clipped"])
            self.assertLessEqual(len(value["text"].encode()), 8192)
            self.assertNotIn("\ufffd", value["text"])
        raw = b"".join((str(i) + " old\n").encode() for i in range(500))
        with edit_fixture(content=raw) as (_, job, _, _, name, path, _):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), raw.decode(), raw.replace(b"old", b"new").decode())
            self.assertTrue(prepared["summary"]["diff"]["clipped"])
            self.assertLessEqual(len(prepared["summary"]["diff"]["text"].splitlines()), 240)

    def test_exact_save_python_java_preserves_all_other_files(self):
        for java in (False, True):
            with self.subTest(java=java), edit_fixture(java=java) as (root, job, source, _, name, path, edit):
                inspected, before, source_before = inspect(job), tree(root), tree(source)
                prepared = editor.prepare(inspected, name, sha(path.read_bytes()), "return 2", "return 3")
                called = []
                with no_execution():
                    result = editor.save(job, prepared, edit, lambda: called.append(True))
                self.assertEqual(called, [True])
                self.assertEqual(path.read_bytes(), prepared["candidate"])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual((edit / "original.bin").read_bytes(), prepared["original"])
                self.assertEqual((edit / "candidate.bin").read_bytes(), prepared["candidate"])
                self.assertFalse((edit / "replacement.next").exists())
                self.assertTrue(result["requires_recheck"])
                self.assertFalse(result["source_applied"])
                self.assertEqual(result["snapshot_sha256"], inspect(job)["summary"]["snapshot_sha256"])
                after = tree(root)
                changed = str(path.relative_to(root))
                self.assertEqual({k: v for k, v in before.items() if k != changed},
                                 {k: v for k, v in after.items() if k != changed and not k.startswith(str(edit.relative_to(root)) + "/")})
                self.assertEqual(tree(source), source_before)

    def test_stale_snapshot_refuses_before_stage(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            path.write_bytes(path.read_bytes() + b"# owner edit\n")
            self.refused(editor.save, job, prepared, edit, lambda: None, suffix="STALE")
            self.assertFalse((edit / "original.bin").exists())
            self.assertIn(b"owner edit", path.read_bytes())

    def test_scope_edit_directory_and_tampered_preparation(self):
        with edit_fixture() as (root, job, _, _, name, path, edit):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            foreign = root / "foreign"; foreign.mkdir(mode=0o700)
            self.refused(editor.save, job, prepared, foreign, lambda: None, suffix="SCOPE")
            damaged = copy.deepcopy(prepared); damaged["candidate"] += b"# unreviewed\n"
            self.refused(editor.save, job, damaged, edit, lambda: None, suffix="RECORD_INVALID")
            self.assertEqual(path.read_bytes(), prepared["original"])

    def test_save_refuses_wide_mode_and_hardlink(self):
        for hard in (False, True):
            with self.subTest(hard=hard), edit_fixture() as (root, job, _, _, name, path, edit):
                prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
                if hard:
                    os.link(path, root / "alias.py")
                else:
                    path.chmod(0o666)
                self.refused(editor.save, job, prepared, edit, lambda: None)
                self.assertEqual(path.read_bytes(), prepared["original"])

    def test_save_preserves_normal_git_0644_mode_and_private_sidecars(self):
        for mode in (0o644, 0o664):
            with self.subTest(mode=oct(mode)), edit_fixture() as (_, job, _, _, name, path, edit):
                path.chmod(mode)
                prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
                editor.save(job, prepared, edit, lambda: None)
                self.assertEqual(path.read_bytes(), prepared["candidate"])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
                self.assertEqual(stat.S_IMODE((edit / "original.bin").stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE((edit / "candidate.bin").stat().st_mode), 0o600)

    def test_save_refuses_other_write_execute_and_special_modes(self):
        for mode in (0o666, 0o755, 0o4600, 0o1600):
            with self.subTest(mode=oct(mode)), edit_fixture() as (_, job, _, _, name, path, edit):
                prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
                path.chmod(mode)
                self.refused(editor.save, job, prepared, edit, lambda: None)
                self.assertEqual(path.read_bytes(), prepared["original"])

    def test_save_requires_private_job_ancestor_for_git_file_modes(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            path.chmod(0o664)
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            job.chmod(0o755)
            self.refused(editor.save, job, prepared, edit, lambda: None)
            self.assertEqual(path.read_bytes(), prepared["original"])

    def test_save_refuses_target_and_parent_symlinks(self):
        for parent in (False, True):
            with self.subTest(parent=parent), edit_fixture(java=True) as (root, job, _, _, name, path, edit):
                prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
                if parent:
                    moved = root / "moved"; path.parent.rename(moved); path.parent.symlink_to(moved, target_is_directory=True)
                else:
                    moved = root / "moved.java"; path.rename(moved); path.symlink_to(moved)
                self.refused(editor.save, job, prepared, edit, lambda: None)
                self.assertEqual((moved / path.name).read_bytes() if parent else moved.read_bytes(), prepared["original"])

    def test_guard_refusal_retains_all_staged_bytes(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            def guard():
                raise Refused("SNAPSHOT_EDITOR_STALE")
            self.refused(editor.save, job, prepared, edit, guard, suffix="STALE")
            self.assertEqual(path.read_bytes(), prepared["original"])
            self.assertEqual((edit / "original.bin").read_bytes(), prepared["original"])
            self.assertEqual((edit / "candidate.bin").read_bytes(), prepared["candidate"])
            self.assertEqual((edit / "replacement.next").read_bytes(), prepared["candidate"])

    def test_guard_target_inode_substitution_refuses_equal_bytes(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            def guard():
                substitute = path.with_name("substitute")
                substitute.write_bytes(path.read_bytes()); substitute.chmod(0o600)
                os.replace(substitute, path)
            self.refused(editor.save, job, prepared, edit, guard, suffix="STALE")
            self.assertEqual(path.read_bytes(), prepared["original"])
            self.assertTrue((edit / "replacement.next").exists())

    def test_guard_staged_bytes_substitution_refused(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            def guard():
                (edit / "replacement.next").write_bytes(b"unreviewed\n")
            self.refused(editor.save, job, prepared, edit, guard, suffix="STALE")
            self.assertEqual(path.read_bytes(), prepared["original"])
            self.assertEqual((edit / "replacement.next").read_bytes(), b"unreviewed\n")

    def test_failing_replace_retains_partials_and_refuses_retry(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
            with patch("snapshot_editor.os.replace", side_effect=OSError("invented private failure")):
                self.refused(editor.save, job, prepared, edit, lambda: None, suffix="WRITE_FAILED")
            self.assertEqual(path.read_bytes(), prepared["original"])
            retained = tree(edit)
            self.refused(editor.save, job, prepared, edit, lambda: None, suffix="WRITE_FAILED")
            self.assertEqual(retained, tree(edit))

    def test_failed_postinspection_keeps_replaced_bytes_and_uncertainty(self):
        with edit_fixture() as (_, job, _, _, name, path, edit):
            inspected = inspect(job)
            prepared = editor.prepare(inspected, name, sha(path.read_bytes()), "return 2", "return 3")
            with patch("snapshot_editor.inspect_workspace", side_effect=[inspected, inspected, Refused("SNAPSHOT_RECHECK_STALE")]):
                self.refused(editor.save, job, prepared, edit, lambda: None, suffix="WRITE_UNCERTAIN")
            self.assertEqual(path.read_bytes(), prepared["candidate"])
            self.assertEqual((edit / "original.bin").read_bytes(), prepared["original"])
            self.assertEqual((edit / "candidate.bin").read_bytes(), prepared["candidate"])
            self.assertFalse((edit / "replacement.next").exists())

    def test_guard_changes_protected_or_git_control_refuses_without_replace(self):
        for control in (False, True):
            with self.subTest(control=control), edit_fixture() as (_, job, _, _, name, path, edit):
                prepared = editor.prepare(inspect(job), name, sha(path.read_bytes()), "return 2", "return 3")
                target = job / "workspace/review" / (".git" if control else "test_main.py")
                # A change before the final inspection must refuse before guard.
                original_inspect = editor.inspect_workspace
                calls = []
                def changed(*args):
                    calls.append(True)
                    if len(calls) == 2:
                        target.write_bytes(target.read_bytes() + b"# changed\n")
                    return original_inspect(*args)
                with patch("snapshot_editor.inspect_workspace", side_effect=changed):
                    self.refused(editor.save, job, prepared, edit, lambda: None)
                self.assertEqual(path.read_bytes(), prepared["original"])
                self.assertTrue((edit / "replacement.next").exists())


if __name__ == "__main__":
    unittest.main()
