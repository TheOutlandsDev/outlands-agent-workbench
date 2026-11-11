"""Offline context tools, edit bindings, before-send refusal and browser DTOs."""

import json
import unittest
from unittest.mock import patch

from agent import MAX_REQUEST_BYTES, Ollama, Refused, Session, canonical, sha
from run_diagnostics import summarize
from test_agent import call, fixture
from test_workbench import manager_fixture
from workbench import context_evidence


class NavigationExercise:
    """Deterministic fixture, with no transport or model."""
    def __init__(self):
        self.turn = 0

    def request(self, messages, seconds):
        del seconds
        self.turn += 1
        if self.turn == 1:
            return call("set_plan", {"steps": ["Search the selected files", "Read the relevant lines", "Correct addition and check"]})
        if self.turn == 2:
            return call("search_text", {"query": "return"})
        if self.turn == 3:
            hit = json.loads(messages[-1]["content"])["matches"][0]
            return call("read_lines", {"path": hit["path"], "start_line": max(1, hit["line_number"] - 2), "end_line": hit["line_number"] + 1})
        if self.turn == 4:
            read = json.loads(messages[-1]["content"])
            return call("replace_text", {"path": "calculator.py", "expected_sha256": read["sha256"],
                                         "old_text": "return a - b", "new_text": "return a + b"})
        if self.turn == 5:
            return call("run_check", {"check_id": "unit"})
        return {"role": "assistant", "content": "Offline navigation exercise passed its recorded check."}


def messages_at_size(provider, size):
    value = [{"role": "user", "content": ""}]
    overhead = len(provider.request_payload(value))
    value[0]["content"] = "x" * (size - overhead)
    assert len(provider.request_payload(value)) == size
    return value


class ContextIntegrationTests(unittest.TestCase):
    def test_plan_still_required_for_both_tools(self):
        with fixture() as (_, session):
            for tool, args in [("search_text", {"query": "return"}), ("read_lines", {"path": "calculator.py", "start_line": 1, "end_line": 4})]:
                with self.assertRaisesRegex(Refused, "PLAN_REQUIRED"):
                    session.tool(tool, args)

    def test_declared_paths_and_tool_arguments_cannot_expand_scope(self):
        with fixture() as (_, session):
            session.tool("set_plan", {"steps": ["Inspect"]})
            for path in ["../outside.py", "/fictional/outside.py", "unselected.py"]:
                with self.assertRaisesRegex(Refused, "READ_SCOPE"):
                    session.tool("read_lines", {"path": path, "start_line": 1, "end_line": 1})
            with self.assertRaisesRegex(Refused, "TOOL_ARGUMENTS"):
                session.tool("search_text", {"query": "return", "files": ["outside.py"]})

    def test_linked_work_file_is_refused_before_context_access(self):
        with fixture() as (root, session):
            session.tool("set_plan", {"steps": ["Inspect"]})
            target = root / "outside.py"; target.write_text("private fictional text\n")
            selected = session.work / "calculator.py"; selected.unlink(); selected.symlink_to(target)
            for name, args in [("read_lines", {"path": "calculator.py", "start_line": 1, "end_line": 1}), ("search_text", {"query": "private"})]:
                with self.assertRaises((Refused, OSError)):
                    session.tool(name, args)

    def test_focused_hash_cannot_authorize_a_stale_edit(self):
        with fixture() as (_, session):
            session.tool("set_plan", {"steps": ["Inspect and edit"]})
            read = session.tool("read_lines", {"path": "calculator.py", "start_line": 1, "end_line": 4})
            args = {"path": "calculator.py", "expected_sha256": read["sha256"], "old_text": "return a - b", "new_text": "return a + b"}
            session.tool("replace_text", args)
            with self.assertRaisesRegex(Refused, "STALE_EDIT_HASH"):
                session.tool("replace_text", {**args, "old_text": "return a + b", "new_text": "return a - b"})

    def test_protected_files_are_readable_but_stay_protected(self):
        with fixture() as (_, session):
            session.tool("set_plan", {"steps": ["Inspect protected checks"]})
            read = session.tool("read_lines", {"path": "test_calculator.py", "start_line": 1, "end_line": 5})
            self.assertTrue(read["lines"])
            with self.assertRaisesRegex(Refused, "WRITE_SCOPE"):
                session.tool("replace_text", {"path": "test_calculator.py", "expected_sha256": read["sha256"], "old_text": "unittest", "new_text": "changed"})

    def test_navigation_fixture_finishes_with_originals_unchanged(self):
        with fixture() as (root, session):
            before = {name: (session.source / name).read_bytes() for name in session.task["files"]}
            result = session.run(NavigationExercise(), root / "hold", "scripted-demo")
            self.assertEqual(result["status"], "REVIEW_READY")
            self.assertEqual(result["turns"], 6)
            tools = [e["value"]["name"] for e in session.events if e["kind"] == "tool_result"]
            self.assertEqual(tools, ["set_plan", "search_text", "read_lines", "replace_text", "run_check"])
            focused = [e["value"]["result"] for e in session.events if e["kind"] == "tool_result" and e["value"]["name"] == "read_lines"][0]
            self.assertTrue(any("return a - b" in row["text"] for row in focused["lines"]))
            self.assertEqual(before, {name: (session.source / name).read_bytes() for name in before})


class RequestLimitTests(unittest.TestCase):
    def test_growing_real_wire_payload_is_refused_after_prior_tool_reads(self):
        class OfflineOllama(Ollama):
            calls = 0
            def request(self, messages, seconds):
                del messages, seconds
                self.calls += 1
                if self.calls == 1:
                    return call("set_plan", {"steps": ["Inspect selected text"]})
                return call("read_file", {"path": ["a.py", "b.py", "c.py", "a.py"][self.calls - 2]})
        with fixture() as (root, original):
            task = dict(original.task); task["files"] = dict(task["files"])
            for name in ["a.py", "b.py", "c.py"]:
                raw = b"#" + b"x" * 32766 + b"\n"
                (original.source / name).write_bytes(raw); task["files"][name] = sha(raw)
            session = Session(task, original.source, root / "large-run", original.checker)
            provider = OfflineOllama("fictional-model"); hold = root / "hold"
            with patch("agent.http.client.HTTPConnection") as factory:
                result = session.run(provider, hold, "ollama")
            factory.assert_not_called()
            self.assertEqual((result["reason"], result["turns"], provider.calls), ("REQUEST_SIZE_LIMIT", 5, 5))
            self.assertFalse(hold.exists())
            refused = [e for e in session.events if e["kind"] == "request_refused"]
            self.assertEqual(len(refused), 1)
            self.assertGreater(refused[0]["value"]["diagnostics"]["request_bytes"], MAX_REQUEST_BYTES)

    def test_actual_wire_boundary_and_oversize_before_connection(self):
        provider = Ollama("fictional-model")
        with patch("agent.http.client.HTTPConnection") as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 200; response.read.return_value = canonical({"done": True, "message": {"role": "assistant", "content": "ok"}})
            provider.request(messages_at_size(provider, MAX_REQUEST_BYTES), 5)
            self.assertEqual(len(factory.return_value.request.call_args.args[2]), MAX_REQUEST_BYTES)
            factory.assert_called_once()
        with patch("agent.http.client.HTTPConnection") as factory, self.assertRaisesRegex(Refused, "REQUEST_SIZE_LIMIT"):
            provider.request(messages_at_size(provider, MAX_REQUEST_BYTES + 1), 5)
        factory.assert_not_called()

    def test_initial_refusal_has_zero_attempts_no_chat_no_new_hold(self):
        with fixture() as (root, session), patch("agent.http.client.HTTPConnection") as factory:
            provider = Ollama("fictional-model"); hold = root / "hold"
            with self.assertRaisesRegex(Refused, "REQUEST_SIZE_LIMIT"):
                session.request(provider, messages_at_size(provider, MAX_REQUEST_BYTES + 1), 120, 1, hold, "ollama")
            factory.assert_not_called(); self.assertFalse(hold.exists())
            self.assertEqual(session.requests_started, 0)
            self.assertEqual([e["kind"] for e in session.events], ["request_refused"])
            result = session.artifacts("FAILED", "REQUEST_SIZE_LIMIT", "ollama", session.requests_started)
            view = summarize(session.task, result, session.events, "FAILED", "ollama")
            self.assertEqual(view["budget"]["used"], 0)
            self.assertIs(view["preflight"]["chat_request_sent"], False)
            self.assertIn("REQUEST_SIZE_REFUSED", view["notes"])

    def test_later_refusal_preserves_previous_request_count(self):
        with fixture() as (root, session), patch("agent.http.client.HTTPConnection") as factory:
            provider = Ollama("fictional-model"); hold = root / "hold"
            response = factory.return_value.getresponse.return_value
            response.status = 200; response.read.return_value = canonical({"done": True, "message": {"role": "assistant", "content": "ok"}})
            session.request(provider, [], 120, 1, hold, "ollama")
            with self.assertRaisesRegex(Refused, "REQUEST_SIZE_LIMIT"):
                session.request(provider, messages_at_size(provider, MAX_REQUEST_BYTES + 1), 120, 2, hold, "ollama")
            factory.assert_called_once(); self.assertFalse(hold.exists())
            result = session.artifacts("FAILED", "REQUEST_SIZE_LIMIT", "ollama", session.requests_started)
            view = summarize(session.task, result, session.events, "FAILED", "ollama")
            self.assertEqual(view["budget"]["used"], 1)
            self.assertEqual(len(view["requests"]), 1)

    def test_refusal_does_not_modify_an_existing_hold_or_record_payload(self):
        with fixture() as (root, session), patch("agent.http.client.HTTPConnection") as factory:
            hold = root / "hold"; original = b'fictional preserved hold\n'; hold.write_bytes(original)
            provider = Ollama("fictional-private-model")
            messages = messages_at_size(provider, MAX_REQUEST_BYTES + 1)
            messages[0]["content"] = "private-content-sentinel" + messages[0]["content"]
            with self.assertRaisesRegex(Refused, "REQUEST_SIZE_LIMIT"):
                session.request(provider, messages, 120, 1, hold, "ollama")
            self.assertEqual(hold.read_bytes(), original); factory.assert_not_called()
            encoded = json.dumps(session.events)
            self.assertNotIn("private-content-sentinel", encoded)
            self.assertNotIn("fictional-private-model", encoded)


class ContextViewTests(unittest.TestCase):
    def test_malformed_preflight_cannot_claim_no_chat_or_expose_text(self):
        with fixture() as (_, session):
            secret = "fictional private detail"
            event = {"kind": "request_refused", "value": {"turn": 1, "diagnostics": {
                "format": "outlands-request-preflight-v1", "reason": secret, "request_bytes": True,
                "limit_bytes": MAX_REQUEST_BYTES, "chat_request_sent": False, "new_hold_created": False}}}
            view = summarize(session.task, None, [event], "FAILED", "ollama")
            self.assertIsNone(view["preflight"])
            self.assertNotIn(secret, json.dumps(view))
            self.assertIn("INVALID_DIAGNOSTICS", view["notes"])

    def test_context_view_only_retains_known_selected_fields(self):
        with manager_fixture() as (_, manager, _):
            source = manager.projects["arithmetic"]["source"]
            raw = (source / "calculator.py").read_bytes()
            from project_context import search_text
            result = search_text({"calculator.py": raw}, "return")
            result["private_extra"] = "private sentinel"
            result["matches"][0]["private_extra"] = "private sentinel"
            clean = context_evidence("search_text", result, {"calculator.py"})
            self.assertNotIn("private sentinel", json.dumps(clean))
            result["matches"][0]["path"] = "unselected.py"
            self.assertIsNone(context_evidence("search_text", result, {"calculator.py"}))

    def test_new_and_legacy_run_views_have_bounded_context(self):
        with manager_fixture(seed=True) as (_, manager, run_id):
            self.assertEqual(manager.view(run_id)["context"], [])
            from project_context import read_lines
            run = manager.run_path(run_id)
            raw = (run / "work/calculator.py").read_bytes()
            start_index = len(list(run.glob("event-*.json")))
            from agent import write_new
            for offset in range(10):
                index = start_index + offset
                write_new(run / ("event-%03d.json" % index), canonical({"index": index, "kind": "tool_result", "value": {"name": "read_lines", "result": read_lines("calculator.py", raw, 1, 4)}}))
            view = manager.view(run_id)
            self.assertEqual(len(view["context"]), 8)
            self.assertEqual(view["context"][0]["index"], start_index + 2)


if __name__ == "__main__":
    unittest.main()
