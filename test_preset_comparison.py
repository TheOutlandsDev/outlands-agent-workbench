"""Invented text-only comparisons; no project source, storage or inference."""

import hashlib
import itertools
import json
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from agent import Refused, canonical
from preset_comparison import CODES, FORMAT, compare_goals


FIELDS = {"version", "format", "draft_goal", "saved_goal", "draft_sha256", "saved_sha256",
          "identical", "prefix_chars", "suffix_chars"}


@contextmanager
def pure_guard():
    with ExitStack() as stack:
        for target in ("builtins.open", "os.open", "pathlib.Path.resolve", "pathlib.Path.stat",
                       "subprocess.Popen", "subprocess.run", "agent.read_file", "agent.Ollama.request",
                       "agent.Ollama.preflight", "agent.ScriptedDemo.request", "agent.Session.checks"):
            stack.enter_context(patch(target, side_effect=AssertionError("comparison reached " + target)))
        yield


class PresetComparisonTests(unittest.TestCase):
    def refused(self, code, draft, saved):
        with self.assertRaises(Refused) as caught:
            compare_goals(draft, saved)
        self.assertEqual(str(caught.exception), code)
        self.assertIn(code, CODES)

    def test_exact_finite_dto_and_known_utf8_hash(self):
        result = compare_goals("abc", "abc")
        self.assertEqual(result, {"version": 1, "format": "outlands-task-preset-comparison-v1",
            "draft_goal": "abc", "saved_goal": "abc",
            "draft_sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "saved_sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "identical": True, "prefix_chars": 3, "suffix_chars": 0})
        self.assertEqual(set(result), FIELDS)
        self.assertIs(type(result["version"]), int)
        self.assertIs(type(result["identical"]), bool)
        self.assertIs(type(result["prefix_chars"]), int)
        self.assertIs(type(result["suffix_chars"]), int)
        self.assertEqual(FORMAT, result["format"])

    def test_empty_draft_preserves_the_entire_saved_goal(self):
        result = compare_goals("", "Review invented Python arithmetic.")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (0, 0))
        self.assertEqual(result["draft_sha256"], "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertFalse(result["identical"])
        self.assertEqual(result["saved_goal"], "Review invented Python arithmetic.")

    def test_whitespace_only_draft_is_allowed_without_stripping(self):
        draft = " \t\r\n\u2003"
        result = compare_goals(draft, "Keep the invented checks fixed.")
        self.assertEqual(result["draft_goal"], draft)
        self.assertEqual(result["draft_sha256"], hashlib.sha256(draft.encode("utf-8")).hexdigest())
        self.assertFalse(result["identical"])

    def test_equal_multiline_unicode_uses_full_prefix_and_no_suffix(self):
        goal = "Review caf\u00e9 \U0001f680.\r\nPreserve \u03a9 checks.\n"
        result = compare_goals(goal, goal)
        self.assertTrue(result["identical"])
        self.assertEqual(result["prefix_chars"], len(goal))
        self.assertEqual(result["suffix_chars"], 0)
        self.assertEqual(result["draft_goal"], goal)

    def test_one_replacement_marks_only_the_different_span(self):
        result = compare_goals("Review Python arithmetic now.", "Review Java arithmetic now.")
        prefix, suffix = result["prefix_chars"], result["suffix_chars"]
        self.assertEqual("Review Python arithmetic now."[prefix:-suffix], "Python")
        self.assertEqual("Review Java arithmetic now."[prefix:-suffix], "Java")
        self.assertEqual(prefix, len("Review "))
        self.assertEqual(suffix, len(" arithmetic now."))

    def test_multiple_edits_use_one_span_including_unchanged_middle(self):
        result = compare_goals("aBcDeFz", "aXcYeFz")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (1, 3))
        self.assertEqual(result["draft_goal"][1:-3], "BcD")
        self.assertEqual(result["saved_goal"][1:-3], "XcY")

    def test_insertion_retains_shared_unicode_prefix_and_suffix(self):
        result = compare_goals("\U0001f680 Keep checks.", "\U0001f680 Keep protected checks.")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (7, 7))
        self.assertEqual(result["draft_goal"][7:-7], "")
        self.assertEqual(result["saved_goal"][7:-7], "protected ")

    def test_deletion_produces_an_empty_saved_change_span(self):
        result = compare_goals("Keep protected checks.", "Keep checks.")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (5, 7))
        self.assertEqual(result["draft_goal"][5:-7], "protected ")
        self.assertEqual(result["saved_goal"][5:-7], "")

    def test_repeated_characters_do_not_overlap_prefix_and_suffix(self):
        for draft, saved in (("aaa", "aaaa"), ("aaaa", "aaa")):
            result = compare_goals(draft, saved)
            self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (3, 0))
            self.assertFalse(result["identical"])

    def test_difference_at_start_preserves_the_complete_shared_suffix(self):
        result = compare_goals("\u03a9 arithmetic", "\U0001f680 arithmetic")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (0, len(" arithmetic")))
        self.assertNotEqual(result["draft_sha256"], result["saved_sha256"])

    def test_difference_at_end_preserves_the_complete_shared_prefix(self):
        result = compare_goals("Review checksA", "Review checksB")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (13, 0))
        self.assertEqual(result["draft_goal"], "Review checksA")
        self.assertEqual(result["saved_goal"], "Review checksB")

    def test_disjoint_goals_have_no_shared_edges(self):
        result = compare_goals("Python", "Java")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (0, 0))
        self.assertFalse(result["identical"])

    def test_combining_sequences_are_not_normalized_or_grapheme_collapsed(self):
        draft, saved = "caf\u00e9 check", "cafe\u0301 check"
        result = compare_goals(draft, saved)
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (3, 6))
        self.assertEqual(result["draft_goal"], draft)
        self.assertEqual(result["saved_goal"], saved)
        self.assertNotEqual(result["draft_sha256"], result["saved_sha256"])

    def test_astral_characters_are_counted_as_codepoints_not_bytes_or_utf16(self):
        result = compare_goals("\U0001f680a\U0001f600", "\U0001f680b\U0001f600")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (1, 1))
        self.assertEqual(result["draft_sha256"], hashlib.sha256("\U0001f680a\U0001f600".encode("utf-8")).hexdigest())

    def test_crlf_and_lf_are_exactly_distinct(self):
        result = compare_goals("first\r\nlast", "first\nlast")
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (5, 5))
        self.assertNotEqual(result["draft_sha256"], result["saved_sha256"])
        self.assertEqual(json.loads(canonical(result))["draft_goal"], "first\r\nlast")

    def test_control_quotes_and_private_looking_text_stay_plain_exact_data(self):
        draft = '<script>alert("invented")</script>\t\b\u0001 /invented/private/path'
        saved = 'Review <script> as literal text.\nKeep \u0001 and quotes " unchanged.'
        result = compare_goals(draft, saved)
        self.assertEqual(result["draft_goal"], draft)
        self.assertEqual(result["saved_goal"], saved)
        self.assertEqual(json.loads(canonical(result)), result)
        self.assertEqual(set(result), FIELDS)

    def test_maximum_astral_goals_fit_the_escaped_output_without_clipping(self):
        draft, saved = "\U0001f680" * 2000, "\U0001f600" * 2000
        result = compare_goals(draft, saved)
        raw = canonical(result)
        self.assertEqual((len(draft.encode("utf-8")), len(saved.encode("utf-8"))), (8000, 8000))
        self.assertGreater(len(raw), 48000)
        self.assertLessEqual(len(raw), 65536)
        self.assertEqual(json.loads(raw)["draft_goal"], draft)
        self.assertEqual(json.loads(raw)["saved_goal"], saved)
        self.assertEqual((result["prefix_chars"], result["suffix_chars"]), (0, 0))

    def test_maximum_escaped_controls_and_whitespace_are_not_omitted(self):
        draft, saved = "\u0001" * 2000, "\u0002" * 1999 + "x"
        result = compare_goals(draft, saved)
        self.assertLessEqual(len(canonical(result)), 65536)
        self.assertEqual(json.loads(canonical(result)), result)
        self.assertEqual(compare_goals(" " * 2000, "x")["draft_goal"], " " * 2000)

    def test_invalid_draft_types_bounds_nul_and_unicode_have_one_finite_error(self):
        class StringSubclass(str):
            pass
        for value in (None, False, 1, b"bytes", [], {}, StringSubclass("draft"), "a" * 2001,
                      "\U0001f680" * 2001, "a\x00b", "\ud800", "\udfff", "\ud83d\ude80"):
            with self.subTest(value_type=type(value).__name__):
                self.refused("TASK_PRESET_DRAFT_INVALID", value, "A valid invented saved goal")

    def test_saved_goals_retain_existing_nonblank_preset_validation(self):
        for value in (None, True, 1, b"bytes", [], {}, "", " ", "\t\r\n\u2003", "a" * 2001,
                      "\U0001f680" * 2001, "a\x00b", "\ud800", "\udfff", "\ud83d\ude80"):
            with self.subTest(value_type=type(value).__name__):
                self.refused("TASK_PRESET_GOAL_INVALID", "", value)

    def test_shared_edges_are_maximal_nonoverlapping_and_symmetric_on_small_alphabet(self):
        alphabet = ("a", "\U0001f680", "\n")
        goals = ["".join(characters) for length in range(4)
                 for characters in itertools.product(alphabet, repeat=length)]
        for draft in goals:
            for saved in goals:
                if not saved.strip():
                    continue
                result = compare_goals(draft, saved)
                prefix, suffix = result["prefix_chars"], result["suffix_chars"]
                self.assertLessEqual(prefix + suffix, min(len(draft), len(saved)))
                self.assertEqual(draft[:prefix], saved[:prefix])
                if suffix:
                    self.assertEqual(draft[-suffix:], saved[-suffix:])
                if not result["identical"]:
                    if prefix < min(len(draft), len(saved)):
                        self.assertNotEqual(draft[prefix], saved[prefix])
                    if prefix + suffix < min(len(draft), len(saved)):
                        self.assertNotEqual(draft[-suffix - 1], saved[-suffix - 1])
                    draft_middle = draft[prefix:len(draft) - suffix if suffix else len(draft)]
                    saved_middle = saved[prefix:len(saved) - suffix if suffix else len(saved)]
                    self.assertNotEqual(draft_middle, saved_middle)
                else:
                    self.assertEqual((prefix, suffix), (len(draft), 0))
                if draft.strip():
                    reverse = compare_goals(saved, draft)
                    self.assertEqual((prefix, suffix), (reverse["prefix_chars"], reverse["suffix_chars"]))

    def test_comparison_is_pure_deterministic_and_does_not_call_runtime(self):
        with pure_guard():
            first = compare_goals("Review invented Python behavior.\n", "Review invented Java behavior.\n")
            second = compare_goals("Review invented Python behavior.\n", "Review invented Java behavior.\n")
        self.assertEqual(first, second)
        self.assertEqual(set(first), FIELDS)


if __name__ == "__main__":
    unittest.main()
