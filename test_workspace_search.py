"""Invented inspection envelopes for pure scoped search/read/handoff guards.

No filesystem inspection, Git, project checks, provider or model is executed by
these fixtures. Controller and actual fixed-check qualification remain separate.
"""

import copy
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, canonical, sha
import workspace_search as workspace


def inspection(files=None, editable=None, *, created=None):
    files = dict(files if files is not None else {
        "main.py": b"def add(a, b):\n    return a + b\n",
        "sample/Sum.java": b"class Sum {\n    int add(int a, int b) { return a + b; }\n}\n",
        "test_main.py": b"def test_add():\n    assert add(1, 2) == 3\n",
    })
    editable = list(editable if editable is not None else [name for name in files if not name.startswith("test_")])
    created = files if created is None else created
    rows = [{"path": name, "editable": name in editable, "created_sha256": sha(created[name]),
             "current_sha256": sha(raw), "bytes": len(raw), "changed": raw != created[name]}
            for name, raw in sorted(files.items())]
    pins = {key: sha(("invented-" + key).encode()) for key in workspace.PINS}
    guards = [{"path": "workspace/review/.git", "sha256": sha(b"invented guard"), "bytes": 14}]
    summary = {"version": 1, "workspace_id": "1" * 16, "source_applied": False,
               **pins, "guards": guards, "files": rows, "total_bytes": sum(map(len, files.values())),
               "changed_files": sum(row["changed"] for row in rows)}
    summary["snapshot_sha256"] = sha(canonical({"files": {row["path"]: row["current_sha256"] for row in rows},
                                                "guards": guards, **pins}))
    return {"summary": summary, "selected_bytes": files,
            "task": {"files": {name: sha(raw) for name, raw in created.items()}, "editable": editable}}


def pin(value, path):
    return sha(value["selected_bytes"][path]), value["summary"]["snapshot_sha256"]


@contextmanager
def no_execution():
    with ExitStack() as stack:
        for name in ("builtins.open", "os.open", "subprocess.run", "subprocess.Popen", "agent.read_file"):
            stack.enter_context(patch(name, side_effect=AssertionError("pure workspace helper reached " + name)))
        yield


class WorkspaceSearchTests(unittest.TestCase):
    def refused(self, suffix, operation, *args):
        with self.assertRaises(Refused) as caught:
            operation(*args)
        self.assertEqual(str(caught.exception), "WORKSPACE_SEARCH_" + suffix)
        self.assertIn(str(caught.exception), workspace.CODES)

    def test_python_java_and_protected_hits_have_current_scope_and_pins(self):
        value, before = inspection(), inspection()
        with no_execution():
            result = workspace.search(value, "add")
        self.assertEqual(value, before)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["workspace_id"], value["summary"]["workspace_id"])
        self.assertEqual(result["snapshot_sha256"], value["summary"]["snapshot_sha256"])
        hits = result["result"]["matches"]
        self.assertEqual([(hit["path"], hit["line_number"], hit["editable"]) for hit in hits],
                         [("main.py", 1, True), ("sample/Sum.java", 2, True),
                          ("test_main.py", 1, False), ("test_main.py", 2, False)])
        for hit in hits:
            self.assertEqual(hit["sha256"], sha(value["selected_bytes"][hit["path"]]))

    def test_literal_case_sensitive_matches_remain_one_per_line(self):
        value = inspection({"value.py": b"a.b a.b\naXb\nA.B\na.b\n"})
        result = workspace.search(value, "a.b")["result"]
        self.assertEqual(result["total_matches"], 2)
        self.assertEqual([hit["line_number"] for hit in result["matches"]], [1, 4])
        self.assertEqual(workspace.search(value, "A.B")["result"]["total_matches"], 1)
        self.assertEqual(workspace.search(value, "absent")["result"]["matches"], [])

    def test_unicode_codepoint_columns_and_all_line_endings_preserve_bytes(self):
        raw = "é😀 needle\r\nneedle\rneedle\nneedle".encode()
        value = inspection({"main.py": raw})
        before = copy.deepcopy(value)
        with no_execution():
            result = workspace.search(value, "needle")["result"]
            read = workspace.read(value, "main.py", *pin(value, "main.py"), 1, 4)
        self.assertEqual([(hit["line_number"], hit["column"]) for hit in result["matches"]],
                         [(1, 4), (2, 1), (3, 1), (4, 1)])
        self.assertEqual([line["text"] for line in read["result"]["lines"]],
                         ["é😀 needle", "needle", "needle", "needle"])
        self.assertEqual(value, before)

    def test_hit_and_serialized_limits_count_permission_labels_and_escaped_unicode(self):
        raw = ("😀" * 70 + "needle" + "\x7f" * 300 + "\n").encode() * 30
        value = inspection({"main.py": raw})
        result = workspace.search(value, "needle")
        inner = result["result"]
        self.assertEqual(inner["total_matches"], 30)
        self.assertLessEqual(len(inner["matches"]), 20)
        self.assertTrue(inner["truncated"])
        self.assertLessEqual(len(canonical(inner)), inner["byte_limit"])
        self.assertLessEqual(len(canonical(result)), 16384)
        for hit in inner["matches"]:
            self.assertIn("needle", hit["text"])
            self.assertLessEqual(len(hit["text"].encode()), 512)
            self.assertTrue(hit["editable"])

    def test_focused_protected_read_is_allowed_and_labeled_without_full_text(self):
        value = inspection()
        with no_execution():
            result = workspace.read(value, "test_main.py", *pin(value, "test_main.py"), 2, 2)
        self.assertFalse(result["editable"])
        self.assertEqual(result["result"]["lines"], [{"line_number": 2, "text": "    assert add(1, 2) == 3", "truncated": False}])
        self.assertEqual(result["result"]["sha256"], pin(value, "test_main.py")[0])
        self.assertNotIn("text", result)
        self.assertNotIn("task", result)
        self.assertNotIn("guards", result)

    def test_explicit_editable_handoff_authorizes_metadata_without_opening(self):
        value = inspection()
        for name in ["main.py", "sample/Sum.java"]:
            with no_execution():
                result = workspace.validate_open(value, name, *pin(value, name))
            self.assertEqual(result, {"path": name, "sha256": pin(value, name)[0],
                                     "bytes": len(value["selected_bytes"][name]), "editable": True})
        self.refused("PROTECTED", workspace.validate_open, value, "test_main.py", *pin(value, "test_main.py"))

    def test_scope_paths_cannot_select_unapproved_or_control_files(self):
        value = inspection()
        for name in ["../main.py", "/main.py", "main.py/..", "./main.py", "a//b", ".git", "a/.git/config",
                     "private.py", "a\\b", None, [], "a" * 129]:
            for operation, tail in [(workspace.read, (1, 2)), (workspace.validate_open, ())]:
                with self.subTest(name=name, operation=operation.__name__):
                    self.refused("SCOPE", operation, value, name, *pin(value, "main.py"), *tail)

    def test_query_errors_are_fixed_and_do_not_expose_requested_text(self):
        value = inspection()
        for query in ["", "x" * 129, "é" * 65, "a\nb", "a\rb", "a\x00b", "\ud800", True, None, []]:
            self.refused("QUERY", workspace.search, value, query)
        self.assertEqual(workspace.search(inspection({"main.py": b"x" * 128}), "x" * 128)["result"]["total_matches"], 1)

    def test_expected_hashes_are_strict_lowercase_and_snapshot_pin_is_required(self):
        value = inspection()
        digest, snapshot = pin(value, "main.py")
        for bad in [None, True, [], "", digest.upper(), "x" * 64, digest + "\n"]:
            self.refused("INPUT", workspace.read, value, "main.py", bad, snapshot, 1, 1)
            self.refused("INPUT", workspace.validate_open, value, "main.py", digest, bad)

    def test_changed_file_hash_or_entire_snapshot_refuses_old_result(self):
        value = inspection()
        digest, snapshot = pin(value, "main.py")
        self.refused("STALE", workspace.read, value, "main.py", "f" * 64, snapshot, 1, 2)
        self.refused("STALE", workspace.validate_open, value, "main.py", digest, "f" * 64)
        changed = dict(value["selected_bytes"])
        changed["sample/Sum.java"] += b"// changed sibling\n"
        fresh = inspection(changed, created=value["selected_bytes"])
        self.assertEqual(pin(fresh, "main.py")[0], digest)
        self.refused("STALE", workspace.read, fresh, "main.py", digest, snapshot, 1, 2)

    def test_empty_selected_file_has_no_invented_lines(self):
        value = inspection({"empty.py": b""})
        result = workspace.read(value, "empty.py", *pin(value, "empty.py"), 1, 80)
        self.assertEqual(result["result"]["lines"], [])
        self.assertIsNone(result["result"]["start_line"])
        self.assertEqual(workspace.search(value, "hit")["result"]["files_searched"], 1)
        self.refused("LIMIT", workspace.search, inspection({}, []), "hit")

    def test_read_ranges_are_strict_and_eof_clamping_remains_visible(self):
        value = inspection()
        for start, end in [(0, 1), (2, 1), (1, 81), (True, 2), (1, False), (1, "2"), (1, 1000001), (99, 100)]:
            self.refused("RANGE", workspace.read, value, "main.py", *pin(value, "main.py"), start, end)
        result = workspace.read(value, "main.py", *pin(value, "main.py"), 1, 80)["result"]
        self.assertEqual(result["requested_end"], 80)
        self.assertEqual(result["end_line"], 2)
        self.assertTrue(result["end_of_file"])

    def test_focused_read_clipping_is_bounded_and_numbered(self):
        value = inspection({"main.py": (("😀" * 1200 + "\n") * 6).encode()})
        result = workspace.read(value, "main.py", *pin(value, "main.py"), 1, 6)
        inner = result["result"]
        self.assertTrue(inner["truncated"])
        self.assertLessEqual(len(canonical(inner)), 8192)
        self.assertLessEqual(len(canonical(result)), 16384)
        self.assertEqual([row["line_number"] for row in inner["lines"]], list(range(1, len(inner["lines"]) + 1)))
        self.assertTrue(all(len(row["text"].encode()) <= 1024 for row in inner["lines"]))

    def test_selected_count_per_file_and_aggregate_bounds(self):
        for files in [{"f%d.py" % i: b"x" for i in range(33)}, {"main.py": b"x" * 32769},
                      {"f%d.py" % i: b"x" * 32768 for i in range(5)}]:
            self.refused("LIMIT", workspace.search, inspection(files), "x")
        value = inspection({"f%d.py" % i: b"x" * 32768 for i in range(4)})
        self.assertEqual(workspace.search(value, "x")["result"]["files_searched"], 4)

    def test_malformed_selected_bytes_and_scope_are_not_trusted(self):
        value = inspection()
        for corrupt in ["not bytes", None, bytearray(b"x"), b"bad\x00data", b"bad\xffdata"]:
            altered = copy.deepcopy(value)
            altered["selected_bytes"]["main.py"] = corrupt
            self.refused("RECORD_INVALID", workspace.search, altered, "add")
        for task in [{"files": [], "editable": []}, {"files": {}, "editable": []},
                     {"files": value["task"]["files"], "editable": ["private.py"]},
                     {"files": value["task"]["files"], "editable": ["main.py", "main.py"]}]:
            altered = copy.deepcopy(value); altered["task"] = task
            self.refused("RECORD_INVALID", workspace.search, altered, "add")

    def test_rows_must_match_bytes_scope_flags_counts_and_unique_order(self):
        value = inspection()
        changes = [("bytes", True), ("bytes", 1), ("editable", False), ("editable", 1),
                   ("changed", True), ("current_sha256", "f" * 64), ("created_sha256", "bad")]
        for key, item in changes:
            altered = copy.deepcopy(value); altered["summary"]["files"][0][key] = item
            self.refused("RECORD_INVALID", workspace.search, altered, "add")
        for kind in ["duplicate", "order", "missing", "extra"]:
            altered = copy.deepcopy(value); rows = altered["summary"]["files"]
            if kind == "duplicate": rows[-1] = copy.deepcopy(rows[0])
            elif kind == "order": rows.reverse()
            elif kind == "missing": rows.pop()
            else: rows[0]["private"] = "invented hidden metadata"
            self.refused("RECORD_INVALID", workspace.search, altered, "add")

    def test_protected_bytes_cannot_be_relabelled_as_a_valid_current_snapshot(self):
        base = inspection()
        files = dict(base["selected_bytes"]); files["test_main.py"] += b"# changed\n"
        altered = inspection(files, created=base["selected_bytes"])
        self.refused("RECORD_INVALID", workspace.search, altered, "changed")

    def test_snapshot_digest_binds_guard_and_creation_pins(self):
        value = inspection()
        for kind in ["snapshot", "guard", "creation", "total", "changed_count"]:
            altered = copy.deepcopy(value); summary = altered["summary"]
            if kind == "snapshot": summary["snapshot_sha256"] = "f" * 64
            elif kind == "guard": summary["guards"][0]["sha256"] = "f" * 64
            elif kind == "creation": summary["creation_sha256"] = "f" * 64
            elif kind == "total": summary["total_bytes"] += 1
            else: summary["changed_files"] = True
            self.refused("RECORD_INVALID", workspace.search, altered, "add")

    def test_incorrect_identity_and_guard_shapes_refuse_finitely(self):
        value = inspection()
        for key, item in [("version", True), ("workspace_id", "F" * 16), ("source_applied", True),
                          ("guards", {}), ("guards", []), ("snapshot_sha256", "A" * 64),
                          ("task_sha256", "bad")]:
            altered = copy.deepcopy(value); altered["summary"][key] = item
            self.refused("RECORD_INVALID", workspace.search, altered, "add")
        for malformed in [None, [], {}, {"summary": []}]:
            self.refused("RECORD_INVALID", workspace.search, malformed, "add")

    def test_private_inspection_metadata_is_not_forwarded_or_modified(self):
        value = inspection()
        value["task"]["private_sentinel"] = "invented internal metadata sentinel"
        value["summary"]["private_sentinel"] = "invented internal metadata sentinel"
        before = copy.deepcopy(value)
        with no_execution():
            searched = workspace.search(value, "add")
            read = workspace.read(value, "main.py", *pin(value, "main.py"), 1, 2)
            opened = workspace.validate_open(value, "main.py", *pin(value, "main.py"))
        for result in [searched, read, opened]:
            self.assertNotIn(b"invented internal metadata sentinel", canonical(result))
        self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()
