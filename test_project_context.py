import hashlib
import json
import unittest
from unittest import mock

from project_context import ContextRefused, read_lines, search_text


def serialized_size(result):
    return len((json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
               .encode("ascii"))


class ContextTestCase(unittest.TestCase):
    def assert_refused(self, code, operation, *args):
        with self.assertRaises(ContextRefused) as caught:
            operation(*args)
        self.assertEqual(str(caught.exception), code)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.args, (code,))

    def assert_bounded(self, result):
        self.assertEqual(result["byte_limit"], 8192)
        self.assertLessEqual(serialized_size(result), 8192)


class SearchTests(ContextTestCase):
    def test_invented_python_and_java_hits_are_sorted_and_hashed(self):
        files = {
            "zeta/Counter.java": b"class Counter {\n  int count = 2;\n}\n",
            "alpha/count.py": b"count = 1\nprint(count)\n",
        }
        result = search_text(files, "count")
        self.assertEqual(result["query"], "count")
        self.assertEqual(result["files_searched"], 2)
        self.assertEqual(result["total_matches"], 3)
        self.assertEqual([(hit["path"], hit["line_number"], hit["column"])
                          for hit in result["matches"]],
                         [("alpha/count.py", 1, 1), ("alpha/count.py", 2, 7),
                          ("zeta/Counter.java", 2, 7)])
        for hit in result["matches"]:
            self.assertEqual(hit["sha256"], hashlib.sha256(files[hit["path"]]).hexdigest())
            self.assertFalse(hit["truncated"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["limit"], 20)
        self.assert_bounded(result)

    def test_one_match_per_line_case_sensitive_and_literal(self):
        files = {"sample.py": b"a.b a.b\naXb\nA.B\na.b\n"}
        result = search_text(files, "a.b")
        self.assertEqual(result["total_matches"], 2)
        self.assertEqual([(hit["line_number"], hit["column"]) for hit in result["matches"]],
                         [(1, 1), (4, 1)])
        self.assertEqual(search_text(files, "A.B")["total_matches"], 1)
        self.assertEqual(search_text(files, "absent")["matches"], [])

    def test_query_validation_has_fixed_codes(self):
        for query in ("", "x" * 129, "é" * 65, "a\nb", "a\rb", "a\x00b", "\ud800", 1, None):
            with self.subTest(query=repr(query)):
                self.assert_refused("CONTEXT_QUERY", search_text, {}, query)
        self.assertEqual(search_text({"x": b"\t"}, "\t")["total_matches"], 1)
        self.assertEqual(search_text({"x": b"x" * 128}, "x" * 128)["total_matches"], 1)

    def test_unicode_columns_count_code_points(self):
        result = search_text({"sample.py": "A😀é needle".encode("utf-8")}, "needle")
        self.assertEqual(result["matches"][0]["column"], 5)

    def test_unicode_excerpt_has_at_most_40_preceding_code_points(self):
        raw = ("界" * 60 + "needle" + "é" * 500).encode("utf-8")
        result = search_text({"sample.py": raw}, "needle")
        hit = result["matches"][0]
        self.assertEqual(hit["column"], 61)
        self.assertEqual(hit["text"].index("needle"), 40)
        self.assertLessEqual(len(hit["text"].encode("utf-8")), 512)
        self.assertTrue(hit["truncated"])
        self.assertTrue(result["truncated"])
        self.assert_bounded(result)

    def test_long_query_survives_excerpt_and_global_clipping(self):
        query = "\x7f" * 128
        raw = ("😀" * 40 + query + "é" * 200).encode("utf-8")
        result = search_text({"\x7f" * 1024: raw}, query)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(len(result["matches"]), 1)
        self.assertIn(query, result["matches"][0]["text"])
        self.assertTrue(result["truncated"])
        self.assert_bounded(result)

    def test_line_endings_and_no_final_newline(self):
        result = search_text({"x": b"hit\r\nhit\rhit\nhit"}, "hit")
        self.assertEqual([hit["line_number"] for hit in result["matches"]], [1, 2, 3, 4])
        self.assertEqual([hit["text"] for hit in result["matches"]], ["hit"] * 4)

    def test_only_cr_and_lf_separate_lines(self):
        result = search_text({"x": "left\v\f\u0085\u2028hit".encode("utf-8")}, "hit")
        self.assertEqual(result["matches"][0]["line_number"], 1)

    def test_empty_file_and_empty_snapshot(self):
        result = search_text({"empty.py": b""}, "hit")
        self.assertEqual(result["files_searched"], 1)
        self.assertEqual(result["total_matches"], 0)
        self.assertFalse(result["truncated"])
        self.assertEqual(search_text({}, "hit")["files_searched"], 0)

    def test_hit_cap_counts_all_matching_lines(self):
        result = search_text({"x": b"hit hit\n" * 80}, "hit")
        self.assertEqual(result["total_matches"], 80)
        self.assertEqual(len(result["matches"]), 20)
        self.assertEqual([hit["line_number"] for hit in result["matches"]], list(range(1, 21)))
        self.assertTrue(result["truncated"])
        self.assert_bounded(result)

    def test_exact_hit_and_text_limits_do_not_claim_truncation(self):
        result = search_text({"x": b"hit\n" * 20}, "hit")
        self.assertEqual(len(result["matches"]), 20)
        self.assertFalse(result["truncated"])
        exact_text = b"hit" + b"x" * 509
        result = search_text({"x": exact_text}, "hit")
        self.assertEqual(result["matches"][0]["text"].encode("utf-8"), exact_text)
        self.assertFalse(result["truncated"])

    def test_global_json_limit_includes_ascii_escape_expansion_and_metadata(self):
        raw = (("hit" + "\x7f" * 900 + "\n") * 20).encode("utf-8")
        result = search_text({"sample.py": raw}, "hit")
        self.assertEqual(result["total_matches"], 20)
        self.assertLess(len(result["matches"]), 20)
        self.assertTrue(result["truncated"])
        for hit in result["matches"]:
            self.assertIn("hit", hit["text"])
            self.assertLessEqual(len(hit["text"].encode("utf-8")), 512)
        self.assert_bounded(result)

    def test_search_rejects_invalid_utf8_even_without_a_hit(self):
        self.assert_refused("CONTEXT_UTF8", search_text, {"sample.py": b"\xff"}, "hit")

    def test_snapshot_limits_and_types(self):
        self.assert_refused("CONTEXT_FILES", search_text, [], "hit")
        self.assert_refused("CONTEXT_FILES", search_text, {"x": "hit"}, "hit")
        self.assert_refused("CONTEXT_FILES", search_text, {"x": bytearray(b"hit")}, "hit")
        self.assert_refused("CONTEXT_SNAPSHOT_LIMIT", search_text,
                            {str(i): b"" for i in range(33)}, "hit")
        self.assert_refused("CONTEXT_SNAPSHOT_LIMIT", search_text, {"x": b"x" * 32769}, "hit")
        self.assert_refused("CONTEXT_SNAPSHOT_LIMIT", search_text,
                            {str(i): b"x" * 32768 for i in range(5)}, "hit")
        self.assertEqual(search_text({str(i): b"" for i in range(32)}, "hit")["files_searched"], 32)
        self.assertEqual(search_text({str(i): b"x" * 32768 for i in range(4)}, "hit")["files_searched"], 4)

    def test_path_validation_is_bounded(self):
        for path in ("", "x\x00y", "x\ny", "x\ry", "x" * 1025, "é" * 513, "\ud800", 3):
            with self.subTest(path=repr(path)):
                self.assert_refused("CONTEXT_PATH", search_text, {path: b"hit"}, "hit")


class ReadLinesTests(ContextTestCase):
    def test_range_returns_exact_lines_and_whole_file_hash(self):
        raw = b"first\r\nsecond\rthird\nfourth"
        result = read_lines("sample.java", raw, 2, 3)
        self.assertEqual(result["path"], "sample.java")
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["requested_start"], 2)
        self.assertEqual(result["requested_end"], 3)
        self.assertEqual((result["start_line"], result["end_line"], result["total_lines"]), (2, 3, 4))
        self.assertEqual(result["lines"], [
            {"line_number": 2, "text": "second", "truncated": False},
            {"line_number": 3, "text": "third", "truncated": False},
        ])
        self.assertFalse(result["end_of_file"])
        self.assertFalse(result["truncated"])
        self.assert_bounded(result)

    def test_crlf_cr_and_lf_have_no_phantom_trailing_line(self):
        for raw in (b"one\r\ntwo\r\n", b"one\rtwo\r", b"one\ntwo\n", b"one\ntwo"):
            with self.subTest(raw=raw):
                result = read_lines("x", raw, 1, 3)
                self.assertEqual(result["total_lines"], 2)
                self.assertEqual([line["text"] for line in result["lines"]], ["one", "two"])
                self.assertEqual(result["end_line"], 2)
                self.assertTrue(result["end_of_file"])
                self.assertFalse(result["truncated"])

    def test_blank_lines_remain_real_lines(self):
        result = read_lines("x", b"\nalpha\n\n", 1, 3)
        self.assertEqual(result["total_lines"], 3)
        self.assertEqual([line["text"] for line in result["lines"]], ["", "alpha", ""])
        self.assertEqual(read_lines("x", b"\r\n", 1, 1)["total_lines"], 1)

    def test_empty_file_has_no_fabricated_lines(self):
        result = read_lines("empty.py", b"", 1, 1)
        self.assertEqual(result["sha256"], hashlib.sha256(b"").hexdigest())
        self.assertEqual(result["total_lines"], 0)
        self.assertEqual(result["lines"], [])
        self.assertIsNone(result["start_line"])
        self.assertIsNone(result["end_line"])
        self.assertTrue(result["end_of_file"])
        self.assertFalse(result["truncated"])
        self.assertEqual(read_lines("empty.py", b"", 50, 60)["lines"], [])

    def test_end_clamps_to_eof_without_claiming_omission(self):
        result = read_lines("x", b"one\ntwo\nthree", 2, 80)
        self.assertEqual(result["requested_end"], 80)
        self.assertEqual((result["start_line"], result["end_line"]), (2, 3))
        self.assertTrue(result["end_of_file"])
        self.assertFalse(result["truncated"])

    def test_ranges_require_exact_positive_bounded_integers(self):
        for start, end in ((True, 1), (1, True), (1.0, 1), (1, "1"),
                           (0, 1), (-1, 1), (2, 1), (1, 81),
                           (1_000_001, 1_000_001), (1_000_000, 1_000_001)):
            with self.subTest(start=start, end=end):
                self.assert_refused("CONTEXT_RANGE", read_lines, "x", b"one", start, end)
        self.assert_refused("CONTEXT_RANGE", read_lines, "x", b"one", 2, 2)
        self.assertEqual(read_lines("x", b"", 1_000_000, 1_000_000)["lines"], [])
        self.assertEqual(len(read_lines("x", b"x\n" * 80, 1, 80)["lines"]), 80)

    def test_long_line_clips_at_utf8_boundary(self):
        raw = ("😀" * 300).encode("utf-8")
        result = read_lines("x", raw, 1, 1)
        line = result["lines"][0]
        self.assertEqual(line["text"], "😀" * 256)
        self.assertEqual(len(line["text"].encode("utf-8")), 1024)
        self.assertTrue(line["truncated"])
        self.assertTrue(result["truncated"])
        self.assertTrue(result["end_of_file"])
        self.assert_bounded(result)

    def test_partial_three_byte_character_is_not_returned(self):
        result = read_lines("x", ("界" * 400).encode("utf-8"), 1, 1)
        self.assertEqual(result["lines"][0]["text"], "界" * 341)
        self.assertEqual(len(result["lines"][0]["text"].encode("utf-8")), 1023)
        self.assertTrue(result["truncated"])
        exact = read_lines("x", b"x" * 1024, 1, 1)
        self.assertFalse(exact["truncated"])

    def test_global_limit_reports_actual_contiguous_range_and_omissions(self):
        raw = (("😀" * 256 + "\n") * 30).encode("utf-8")
        result = read_lines("x", raw, 1, 30)
        self.assertLess(len(result["lines"]), 30)
        self.assertEqual(result["start_line"], 1)
        self.assertEqual(result["end_line"], len(result["lines"]))
        self.assertEqual([line["line_number"] for line in result["lines"]],
                         list(range(1, len(result["lines"]) + 1)))
        self.assertTrue(result["truncated"])
        self.assertFalse(result["end_of_file"])
        self.assertTrue(result["lines"][-1]["truncated"])
        for line in result["lines"]:
            self.assertLessEqual(len(line["text"].encode("utf-8")), 1024)
        self.assert_bounded(result)

    def test_worst_case_path_and_ascii_expansion_stay_within_global_limit(self):
        result = read_lines("\x7f" * 1024, b"\x7f" * 1024, 1, 1)
        self.assertEqual(len(result["lines"]), 1)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["lines"][0]["truncated"])
        self.assert_bounded(result)

    def test_whole_file_hash_changes_for_unselected_content_and_line_endings(self):
        first = read_lines("x", b"same\nfirst", 1, 1)
        second = read_lines("x", b"same\nother", 1, 1)
        third = read_lines("x", b"same\r\nfirst", 1, 1)
        self.assertEqual(first["lines"], second["lines"])
        self.assertEqual(first["lines"], third["lines"])
        self.assertEqual(len({first["sha256"], second["sha256"], third["sha256"]}), 3)
        self.assertNotEqual(search_text({"x": b"hit\nfirst"}, "hit")["matches"][0]["sha256"],
                            search_text({"x": b"hit\nother"}, "hit")["matches"][0]["sha256"])

    def test_read_input_validation(self):
        self.assert_refused("CONTEXT_FILES", read_lines, "x", "text", 1, 1)
        self.assert_refused("CONTEXT_UTF8", read_lines, "x", b"\xff", 1, 1)
        self.assert_refused("CONTEXT_SNAPSHOT_LIMIT", read_lines, "x", b"x" * 32769, 1, 1)
        self.assert_refused("CONTEXT_PATH", read_lines, "", b"x", 1, 1)


class PurityTests(ContextTestCase):
    def test_inputs_are_not_mutated_and_results_are_deterministic(self):
        files = {"b.java": b"hit\r\nlast", "a.py": b"hit hit\n"}
        original = files.copy()
        first = search_text(files, "hit")
        first["matches"][0]["text"] = "changed result"
        self.assertEqual(files, original)
        self.assertNotEqual(first, search_text(files, "hit"))
        self.assertEqual(search_text(files, "hit"), search_text(dict(reversed(list(files.items()))), "hit"))
        raw = files["a.py"]
        self.assertEqual(read_lines("a.py", raw, 1, 1), read_lines("a.py", raw, 1, 1))
        self.assertEqual(files, original)

    def test_operations_make_no_filesystem_calls(self):
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem open")), \
                mock.patch("os.open", side_effect=AssertionError("filesystem os.open")), \
                mock.patch("os.scandir", side_effect=AssertionError("filesystem scandir")), \
                mock.patch("os.listdir", side_effect=AssertionError("filesystem listdir")), \
                mock.patch("os.stat", side_effect=AssertionError("filesystem stat")), \
                mock.patch("pathlib.Path.open", side_effect=AssertionError("filesystem Path.open")):
            self.assertEqual(search_text({"not-a-real-path.py": b"hit"}, "hit")["total_matches"], 1)
            self.assertEqual(read_lines("not-a-real-path.py", b"hit", 1, 1)["lines"][0]["text"], "hit")

    def test_supplied_source_is_never_executed(self):
        raw = b"raise RuntimeError('this source must stay text')\n"
        with mock.patch("builtins.exec", side_effect=AssertionError("source exec")), \
                mock.patch("builtins.eval", side_effect=AssertionError("source eval")):
            self.assertEqual(search_text({"invented.py": raw}, "RuntimeError")["total_matches"], 1)
            self.assertEqual(read_lines("invented.py", raw, 1, 1)["lines"][0]["text"],
                             "raise RuntimeError('this source must stay text')")

    def test_unknown_exception_input_cannot_escape_fixed_codes(self):
        error = ContextRefused("private detail")
        self.assertEqual(str(error), "CONTEXT_FILES")


if __name__ == "__main__":
    unittest.main()
