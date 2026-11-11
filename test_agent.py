"""Offline engine tests. No inference and no execution of supplied source."""

import io
import http.client
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import (
    Ollama,
    Refused,
    ScriptedDemo,
    Session,
    canonical,
    DIAGNOSTIC_FORMAT,
    DIAGNOSTIC_METRICS,
    gate,
    main,
    parse,
    read_file,
    relative,
    review_diff,
    sha,
    validate_task,
    tools_for_messages,
)

HERE = Path(__file__).resolve().parent


def fake_check(work, pattern, seconds):
    del pattern, seconds
    ok = "return a + b" in (work / "calculator.py").read_text()
    return {
        "exit_code": 0 if ok else 1,
        "timed_out": False,
        "output_limited": False,
        "infrastructure_error": False,
        "output": "fictional checker",
        "tests_ran": 4,
    }


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir()
        task = json.loads((HERE / "task.example.json").read_text())
        for name in task["files"]:
            (source / name).write_bytes((HERE / name).read_bytes())
        session = Session(task, source, root / "run", fake_check)
        yield root, session


def call(name, arguments):
    return {
        "role": "assistant",
        "old_text": "x",
        "new_text": "y",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


class Sequence:
    def __init__(self, items):
        self.items = iter(items)
        self.calls = 0

    def request(self, messages, seconds):
        del messages, seconds
        self.calls += 1
        item = next(self.items)
        if isinstance(item, BaseException):
            raise item
        return item


def diagnostics(session, kind):
    return [event["value"]["diagnostics"] for event in session.events if event["kind"] == kind]


class ContractTests(unittest.TestCase):
    def test_demo_contract(self):
        validate_task(json.loads((HERE / "task.example.json").read_text()))

    def test_strict_json(self):
        for raw in [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"{", b" " * 262145]:
            with self.subTest(raw=raw[:20]), self.assertRaises(Refused):
                parse(raw)

    def test_bad_paths(self):
        for value in [
            "../x",
            "/tmp/x",
            "a/../x",
            "a//b",
            "a/./b",
            "a/",
            "a\\b",
            "a b",
            "",
            "x" * 129,
            "a/" * 8 + "b",
        ]:
            with self.subTest(value=value), self.assertRaises(Refused):
                relative(value)

    def test_task_fields(self):
        task = json.loads((HERE / "task.example.json").read_text())
        task["shell"] = "ignored"
        with self.assertRaises(Refused):
            validate_task(task)

    def test_limits(self):
        for field, value in [
            ("max_turns", True),
            ("max_turns", 0),
            ("max_turns", 17),
            ("request_seconds", 121),
            ("request_seconds", 0),
            ("goal", ""),
            ("files", {}),
            ("checks", {}),
            ("editable", []),
        ]:
            task = json.loads((HERE / "task.example.json").read_text())
            task[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(Refused):
                validate_task(task)

    def test_protected_test(self):
        task = json.loads((HERE / "task.example.json").read_text())
        task["editable"].append("test_calculator.py")
        with self.assertRaisesRegex(Refused, "CHECK_PROTECTED"):
            validate_task(task)

    def test_bad_hash(self):
        task = json.loads((HERE / "task.example.json").read_text())
        task["files"]["calculator.py"] = "BAD"
        with self.assertRaises(Refused):
            validate_task(task)

    def test_case_collision(self):
        task = json.loads((HERE / "task.example.json").read_text())
        task["files"]["Calculator.py"] = "0" * 64
        with self.assertRaises(Refused):
            validate_task(task)


class FilesTests(unittest.TestCase):
    def test_lexical_alias_run_inside_source_refused(self):
        with fixture() as (_, s), self.assertRaisesRegex(Refused, "RUN_OUTSIDE_SOURCE"):
            Session(s.task, s.source / ".." / "source", s.source / "nested", fake_check)

    def test_lexical_alias_state_inside_source_refused(self):
        with fixture() as (root, s), redirect_stdout(io.StringIO()) as output:
            code = main(
                [
                    "--task",
                    str(HERE / "task.example.json"),
                    "--source",
                    str(s.source),
                    "--run-dir",
                    str(root / "another"),
                    "--state-dir",
                    str(s.source / ".." / "source" / "state"),
                    "--backend",
                    "scripted-demo",
                ]
            )
            self.assertEqual(code, 2)
            self.assertEqual(
                json.loads(output.getvalue())["reason"], "STATE_OUTSIDE_SOURCE"
            )
            self.assertFalse((s.source / "state").exists())

    def test_unterminated_diff_marker(self):
        value = review_diff("sample.py", b"old\n", b"new")
        self.assertEqual(
            value,
            "--- a/sample.py\n+++ b/sample.py\n@@ -1 +1 @@\n-old\n+new\n\\ No newline at end of file\n",
        )

    def test_link_and_special_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_text("fixture")
            (root / "link").symlink_to(root / "file")
            os.link(root / "file", root / "hard")
            os.mkfifo(root / "fifo")
            for name in ["link", "hard", "fifo"]:
                with self.subTest(name=name), self.assertRaises((Refused, OSError)):
                    read_file(root, name)

    def test_parent_link_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            (root / "real/f").write_text("fictional")
            (root / "alias").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaises(OSError):
                read_file(root, "alias/f")

    def test_size_and_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_bytes(b"x" * 32768)
            self.assertEqual(len(read_file(root, "file")), 32768)
            for raw in [b"x" * 32769, b"\x00"]:
                (root / "file").write_bytes(raw)
                with self.assertRaises(Refused):
                    read_file(root, "file")

    def test_source_hash_changed(self):
        with fixture() as (root, session):
            (session.source / "calculator.py").write_text("changed")
            with self.assertRaisesRegex(Refused, "SOURCE_HASH_CHANGED"):
                Session(session.task, session.source, root / "second", fake_check)
            self.assertFalse((root / "second").exists())

    def test_existing_run_refused(self):
        with fixture() as (_, session), self.assertRaises(FileExistsError):
            Session(session.task, session.source, session.root, fake_check)


class ToolTests(unittest.TestCase):
    def test_plan_required(self):
        with fixture() as (_, s), self.assertRaisesRegex(Refused, "PLAN_REQUIRED"):
            s.tool("read_file", {"path": "calculator.py"})

    def test_plan_once(self):
        with fixture() as (_, s):
            s.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaises(Refused):
                s.tool("set_plan", {"steps": ["Again"]})

    def test_read_scope(self):
        with fixture() as (_, s):
            s.tool("set_plan", {"steps": ["Inspect"]})
            for path in ["../secret", "/etc/passwd", "unlisted.py"]:
                with (
                    self.subTest(path=path),
                    self.assertRaisesRegex(Refused, "READ_SCOPE"),
                ):
                    s.tool("read_file", {"path": path})

    def test_write_and_stale_hash(self):
        with fixture() as (_, s):
            s.tool("set_plan", {"steps": ["Inspect"]})
            value = s.tool("read_file", {"path": "calculator.py"})
            args = {
                "path": "calculator.py",
                "expected_sha256": value["sha256"],
                "old_text": "return a - b",
                "new_text": "return a + b",
            }
            result = s.tool("replace_text", args)
            self.assertEqual(
                result["sha256"],
                sha(
                    value["content"]
                    .replace(args["old_text"], args["new_text"])
                    .encode()
                ),
            )
            with self.assertRaisesRegex(Refused, "STALE_EDIT_HASH"):
                s.tool("replace_text", args)
            self.assertIn("a - b", (s.source / "calculator.py").read_text())

    def test_protected_write_and_unknown_check(self):
        with fixture() as (_, s):
            s.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaisesRegex(Refused, "WRITE_SCOPE"):
                s.tool(
                    "replace_text",
                    {
                        "path": "test_calculator.py",
                        "expected_sha256": "0" * 64,
                        "old_text": "x",
                        "new_text": "y",
                    },
                )
            with self.assertRaisesRegex(Refused, "CHECK_SCOPE"):
                s.tool("run_check", {"check_id": "shell"})

    def test_unknown_tool(self):
        with fixture() as (_, s):
            s.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaisesRegex(Refused, "UNKNOWN_TOOL"):
                s.tool("exec", {"command": "anything"})

    def test_extra_arguments(self):
        with fixture() as (_, s):
            s.tool("set_plan", {"steps": ["Inspect"]})
            with self.assertRaises(Refused):
                s.tool("read_file", {"path": "calculator.py", "extra": True})

    def test_protected_tamper(self):
        with fixture() as (_, s):
            (s.work / "test_calculator.py").write_text("changed")
            with self.assertRaisesRegex(Refused, "PROTECTED_FILE_CHANGED"):
                s.verify_copy()

    def test_extra_file(self):
        with fixture() as (_, s):
            (s.work / "unexpected").write_text("x")
            with self.assertRaisesRegex(Refused, "WORK_TREE_CHANGED"):
                s.verify_copy()


class LoopTests(unittest.TestCase):
    def test_scripted_flow(self):
        with fixture() as (root, s):
            result = s.run(ScriptedDemo(), root / "hold", "scripted-demo")
            self.assertEqual(result["status"], "REVIEW_READY")
            self.assertFalse(result["ai_inference"])
            self.assertEqual(result["turns"], 6)
            self.assertIn("+    return a + b", (s.root / "changes.diff").read_text())

    def test_early_final(self):
        with fixture() as (root, s):
            result = s.run(
                Sequence([{"role": "assistant", "content": "Done"}]),
                root / "hold",
                "scripted-demo",
            )
            self.assertEqual(result["reason"], "FINAL_REQUIRED")

    def test_false_completion(self):
        with fixture() as (root, s):
            result = s.run(
                Sequence(
                    [
                        call("set_plan", {"steps": ["Done"]}),
                        {"role": "assistant", "content": "Tests passed"},
                    ]
                ),
                root / "hold",
                "scripted-demo",
            )
            self.assertEqual(result["reason"], "FINAL_CHECKS_FAILED")

    def test_budget_exhaustion(self):
        with fixture() as (root, s):
            s.task["max_turns"] = 1
            result = s.run(
                Sequence([call("set_plan", {"steps": ["Read"]})]),
                root / "hold",
                "scripted-demo",
            )
            self.assertEqual(result["reason"], "TURN_BUDGET_EXHAUSTED")

    def test_uncertain_transport(self):
        with fixture() as (root, s):
            state = root / "state"
            with gate(state) as hold:
                result = s.run(
                    Sequence([OSError("uncertain transport")]), hold, "ollama"
                )
            self.assertEqual(result["status"], "UNCERTAIN")
            with self.assertRaisesRegex(Refused, "UNCERTAIN_REQUEST_HELD"), gate(state):
                pass

    def test_malformed_response_holds(self):
        with fixture() as (root, s):
            result = s.run(Sequence([{"role": "user"}]), root / "hold", "ollama")
            self.assertEqual(result["status"], "UNCERTAIN")

    def test_model_violation_stops_without_retry(self):
        with fixture() as (root, s):
            provider = Sequence(
                [call("set_plan", {"steps": ["Read"]}), call("exec", {})]
            )
            result = s.run(provider, root / "hold", "scripted-demo")
            self.assertEqual(result["reason"], "UNKNOWN_TOOL")
            self.assertEqual(result["turns"], 2)

    def test_multiple_tools_refused(self):
        with fixture() as (root, s):
            item = call("set_plan", {"steps": ["Read"]})
            item["tool_calls"] *= 2
            result = s.run(Sequence([item]), root / "hold", "scripted-demo")
            self.assertEqual(result["reason"], "ONE_TOOL_PER_TURN")

    def test_check_infrastructure_stops_before_request(self):
        with fixture() as (root, s):

            def bad_check(*_):
                return {
                    "exit_code": 1,
                    "timed_out": False,
                    "output_limited": False,
                    "infrastructure_error": True,
                }

            s.checker = bad_check
            result = s.run(Sequence([]), root / "hold", "scripted-demo")
            self.assertEqual(result["reason"], "CHECK_EXECUTION_FAILED")
            self.assertEqual(result["turns"], 0)

    def test_lock_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            with (
                gate(state),
                self.assertRaisesRegex(Refused, "WORKER_BUSY"),
                gate(state),
            ):
                pass

    def test_private_state_required(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o755)
            with self.assertRaisesRegex(Refused, "STATE_PRIVATE"), gate(state):
                pass


class TransportTests(unittest.TestCase):
    def test_provider_timeout_phase_preserves_hold_without_retry(self):
        for phase in ["SEND", "HEADER", "BODY"]:
            with self.subTest(phase=phase), fixture() as (root, session):
                with patch("agent.http.client.HTTPConnection") as factory:
                    connection = factory.return_value
                    if phase == "SEND":
                        connection.request.side_effect = TimeoutError("private transport detail")
                    elif phase == "HEADER":
                        connection.getresponse.side_effect = TimeoutError("private transport detail")
                    else:
                        connection.getresponse.return_value.read.side_effect = TimeoutError("private transport detail")
                    with gate(root / "state") as hold:
                        result = session.run(Ollama("fictional-model"), hold, "ollama")
                    self.assertEqual(result["status"], "UNCERTAIN")
                    self.assertEqual(result["reason"], "PROVIDER_" + phase + "_TIMEOUT")
                    self.assertEqual(result["turns"], 1)
                    self.assertTrue(all(row["before"] == row["after"] for row in result["files"].values()))
                    connection.request.assert_called_once()
                    connection.close.assert_called_once()
                    factory.assert_called_once_with("127.0.0.1", 11434, timeout=session.task["request_seconds"])
                    start = diagnostics(session, "request_started")[0]
                    finish = diagnostics(session, "request_finished")[0]
                    self.assertEqual(start["request_bytes"], len(connection.request.call_args.args[2]))
                    self.assertEqual(start["timeout_seconds"], session.task["request_seconds"])
                    self.assertEqual(finish["phase"], phase)
                    self.assertEqual(finish["outcome"], "ERROR")
                    self.assertEqual(finish["reason"], result["reason"])
                    self.assertEqual(finish["error_category"], "TIMEOUT")
                    self.assertEqual(finish["metrics"], {})
                    self.assertNotIn("private transport detail", json.dumps([start, finish]))
                    with self.assertRaisesRegex(Refused, "UNCERTAIN_REQUEST_HELD"), gate(root / "state"):
                        pass

    def test_tool_offers_follow_acknowledged_plan(self):
        for messages in [[], [{"role": "assistant", "tool_calls": [{"function": {"name": "set_plan"}}]}], [{"role": "tool", "tool_name": "read_file"}]]:
            self.assertEqual([t["function"]["name"] for t in tools_for_messages(messages)], ["set_plan"])
        offered = tools_for_messages([{"role": "tool", "tool_name": "set_plan", "content": "recorded"}])
        self.assertEqual([t["function"]["name"] for t in offered], ["read_file", "replace_text", "run_check"])

    def test_preflight_other_model_refused(self):
        with patch("agent.http.client.HTTPConnection") as connection:
            reply = connection.return_value.getresponse.return_value
            reply.status = 200
            reply.read.return_value = canonical({"models": [{"name": "another-model"}]})
            with self.assertRaisesRegex(Refused, "OTHER_MODEL_LOADED"):
                Ollama("chosen-model").preflight()
            connection.return_value.request.assert_called_once_with("GET", "/api/ps")

    def test_preflight_idle(self):
        with patch("agent.http.client.HTTPConnection") as connection:
            reply = connection.return_value.getresponse.return_value
            reply.status = 200
            reply.read.return_value = canonical({"models": []})
            Ollama("chosen-model").preflight()

    def test_incomplete_generation_refused(self):
        with patch("agent.http.client.HTTPConnection") as connection:
            reply = connection.return_value.getresponse.return_value
            reply.status = 200
            reply.read.return_value = canonical(
                {"done": False, "message": {"role": "assistant"}}
            )
            with self.assertRaisesRegex(Refused, "PROVIDER_INCOMPLETE"):
                Ollama("chosen-model").request([], 5)

    def test_ollama_wire(self):
        class Connection:
            sent = None

            def __init__(self, host, port, timeout):
                self.args = (host, port, timeout)

            def request(self, method, path, payload, headers):
                Connection.sent = (
                    self.args,
                    method,
                    path,
                    json.loads(payload),
                    headers,
                )

            def getresponse(self):
                return self

            status = 200

            def read(self, _):
                return canonical(
                    {"done": True, "message": {"role": "assistant", "content": "hello"}}
                )

            def close(self):
                pass

        with patch("agent.http.client.HTTPConnection", Connection):
            result = Ollama("fictional-model").request([], 5)
        args, method, path, payload, _ = Connection.sent
        self.assertEqual(args, ("127.0.0.1", 11434, 5))
        self.assertEqual((method, path), ("POST", "/api/chat"))
        self.assertFalse(payload["stream"])
        self.assertEqual([t["function"]["name"] for t in payload["tools"]], ["set_plan"])
        self.assertEqual(result["content"], "hello")


class DiagnosticsTests(unittest.TestCase):
    def test_custom_provider_contract_and_monotonic_elapsed(self):
        with fixture() as (root, session):
            provider = Sequence([{"role": "assistant", "content": "private response"}])
            with patch("agent.time.time_ns", side_effect=[2000000000, 1000000000]), patch(
                "agent.time.monotonic_ns", side_effect=[10000000000, 10047000000]
            ):
                result = session.run(provider, root / "hold", "scripted-demo")
            self.assertEqual(result["reason"], "FINAL_REQUIRED")
            self.assertEqual(provider.calls, 1)
            self.assertEqual(diagnostics(session, "request_started"), [{
                "format": DIAGNOSTIC_FORMAT, "started_at_ms": 2000,
                "timeout_seconds": session.task["request_seconds"], "request_bytes": None,
            }])
            self.assertEqual(diagnostics(session, "request_finished"), [{
                "format": DIAGNOSTIC_FORMAT, "finished_at_ms": 1000, "elapsed_ms": 47,
                "phase": "COMPLETE", "outcome": "RESPONSE_RECORDED", "reason": None,
                "error_category": None, "metrics": {},
            }])
            kinds = [event["kind"] for event in session.events]
            self.assertLess(kinds.index("response"), kinds.index("request_finished"))
            self.assertNotIn("private response", json.dumps(diagnostics(session, "request_finished")))

    def test_elapsed_is_nonnegative_when_mock_clock_goes_backwards(self):
        with fixture() as (root, session), patch(
            "agent.time.monotonic_ns", side_effect=[100000000, 99000000]
        ):
            session.run(Sequence([OSError("private")]), root / "hold", "ollama")
            self.assertEqual(diagnostics(session, "request_finished")[0]["elapsed_ms"], 0)

    def test_ollama_metrics_and_durable_order_before_release(self):
        with fixture() as (root, session), patch("agent.http.client.HTTPConnection") as factory:
            connection = factory.return_value
            metrics = dict(zip(DIAGNOSTIC_METRICS, [0, 9007199254740991, 2, 3, 4, 5]))
            reply = connection.getresponse.return_value
            reply.status = 200
            reply.read.return_value = canonical({
                "done": True, "message": {"role": "assistant", "content": "private prompt code"},
                "model": "private-model", "private_path": "/private/code.py", **metrics,
            })
            with gate(root / "state") as hold:
                original_emit = session.emit

                def observe(kind, value):
                    if kind in {"response", "request_finished"}:
                        self.assertTrue(hold.exists())
                    original_emit(kind, value)
                    if kind == "request_finished":
                        responses = [e for e in session.events if e["kind"] == "response"]
                        self.assertEqual(len(responses), 1)
                        path = session.root / f"event-{responses[0]['index']:03d}.json"
                        self.assertEqual(json.loads(path.read_bytes()), responses[0])

                with patch.object(session, "emit", side_effect=observe):
                    session.run(Ollama("private-model"), hold, "ollama")
                self.assertFalse(hold.exists())
            finish = diagnostics(session, "request_finished")[0]
            self.assertEqual(finish["metrics"], metrics)
            self.assertEqual(finish["phase"], "COMPLETE")
            self.assertEqual(finish["outcome"], "RESPONSE_RECORDED")
            evidence = canonical([diagnostics(session, kind) for kind in ("request_started", "request_finished")])
            for private in [b"private prompt code", b"private-model", b"/private/code.py"]:
                self.assertNotIn(private, evidence)
            connection.request.assert_called_once()
            connection.close.assert_called_once()
            for event in session.events:
                if event["kind"].startswith("request_"):
                    path = session.root / f"event-{event['index']:03d}.json"
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_metrics_are_omitted_without_coercion(self):
        for invalid in [True, False, "1", 1.0, -1, 9007199254740992, None, {}, []]:
            with self.subTest(invalid=invalid), fixture() as (root, session), patch(
                "agent.http.client.HTTPConnection"
            ) as factory:
                reply = factory.return_value.getresponse.return_value
                reply.status = 200
                reply.read.return_value = canonical({
                    "done": True, "message": {"role": "assistant", "content": "done"},
                    **{key: invalid for key in DIAGNOSTIC_METRICS}, "other_count": 12,
                })
                session.run(Ollama("fictional-model"), root / "hold", "ollama")
                self.assertEqual(diagnostics(session, "request_finished")[0]["metrics"], {})
                factory.return_value.request.assert_called_once()

    def test_transport_failures_are_classified_without_private_text(self):
        for operation, phase, exc, category in [
            ("request", "SEND", ConnectionRefusedError("private host path"), "CONNECTION"),
            ("getresponse", "HEADER", http.client.BadStatusLine("private protocol"), "HTTP_PROTOCOL"),
            ("read", "BODY", http.client.IncompleteRead(b"private response"), "HTTP_PROTOCOL"),
            ("request", "SEND", OSError("private OS path"), "OS_ERROR"),
        ]:
            with self.subTest(phase=phase, category=category), fixture() as (root, session), patch(
                "agent.http.client.HTTPConnection"
            ) as factory:
                connection = factory.return_value
                target = connection.getresponse.return_value if operation == "read" else connection
                getattr(target, operation).side_effect = exc
                result = session.run(Ollama("private-model"), root / "hold", "ollama")
                finish = diagnostics(session, "request_finished")[0]
                self.assertEqual(result["reason"], "EXECUTION_ERROR")
                self.assertEqual(result["status"], "UNCERTAIN")
                self.assertEqual((finish["phase"], finish["error_category"]), (phase, category))
                self.assertEqual(finish["reason"], "EXECUTION_ERROR")
                self.assertNotIn("private", json.dumps(finish))
                self.assertTrue((root / "hold").exists())
                connection.request.assert_called_once()
                connection.close.assert_called_once()

    def test_malformed_responses_stop_at_validation_and_keep_hold(self):
        cases = [
            (b'{"private":', "INVALID_JSON"),
            (canonical({"done": False}), "PROVIDER_INCOMPLETE"),
            (canonical({"done": True}), "EXECUTION_ERROR"),
            (canonical({"done": True, "message": {"role": "user"}}), "MODEL_MESSAGE"),
            (canonical({"done": True, "message": {"role": "assistant", "content": 3}}), "MODEL_CONTENT"),
        ]
        for body, reason in cases:
            with self.subTest(reason=reason), fixture() as (root, session), patch(
                "agent.http.client.HTTPConnection"
            ) as factory:
                connection = factory.return_value
                reply = connection.getresponse.return_value
                reply.status, reply.read.return_value = 200, body
                result = session.run(Ollama("fictional-model"), root / "hold", "ollama")
                finish = diagnostics(session, "request_finished")[0]
                self.assertEqual(result["reason"], reason)
                self.assertEqual(finish["reason"], reason)
                self.assertEqual(finish["phase"], "VALIDATE")
                self.assertEqual(finish["outcome"], "ERROR")
                self.assertFalse(any(e["kind"] == "response" for e in session.events))
                self.assertTrue((root / "hold").exists())
                connection.request.assert_called_once()
                connection.close.assert_called_once()

    def test_unknown_refusal_remains_in_result_but_not_diagnostics(self):
        private = "private code /path/model prompt"
        with fixture() as (root, session):
            provider = Sequence([Refused(private)])
            result = session.run(provider, root / "hold", "ollama")
            finish = diagnostics(session, "request_finished")[0]
            self.assertEqual(result["reason"], private)
            self.assertIsNone(finish["reason"])
            self.assertEqual(finish["error_category"], "REFUSED")
            self.assertEqual(finish["phase"], "UNKNOWN")
            self.assertNotIn(private, json.dumps(finish))
            self.assertEqual(provider.calls, 1)

    def test_interrupt_closes_client_and_retains_admission_hold(self):
        for operation, phase in [("request", "SEND"), ("getresponse", "HEADER"), ("read", "BODY")]:
            with self.subTest(phase=phase), fixture() as (root, session), patch(
                "agent.http.client.HTTPConnection"
            ) as factory:
                connection = factory.return_value
                target = connection.getresponse.return_value if operation == "read" else connection
                getattr(target, operation).side_effect = KeyboardInterrupt("private interruption")
                with gate(root / "state") as hold:
                    result = session.run(Ollama("fictional-model"), hold, "ollama")
                finish = diagnostics(session, "request_finished")[0]
                self.assertEqual(result["reason"], "OWNER_INTERRUPT")
                self.assertEqual(result["status"], "UNCERTAIN")
                self.assertEqual(finish["phase"], phase)
                self.assertEqual(finish["outcome"], "INTERRUPTED")
                self.assertEqual(finish["error_category"], "INTERRUPTED")
                self.assertEqual(finish["reason"], "OWNER_INTERRUPT")
                self.assertNotIn("private interruption", json.dumps(finish))
                connection.request.assert_called_once()
                connection.close.assert_called_once()
                with self.assertRaisesRegex(Refused, "UNCERTAIN_REQUEST_HELD"), gate(root / "state"):
                    pass

    def test_finish_storage_failure_retains_response_and_hold_without_retry(self):
        with fixture() as (root, session):
            provider = Sequence([{"role": "assistant", "content": "private response"}])
            original_emit, writes = session.emit, []

            def fail_finish(kind, value):
                writes.append(kind)
                if kind == "request_finished":
                    raise OSError("private diagnostic storage")
                original_emit(kind, value)

            with patch.object(session, "emit", side_effect=fail_finish):
                result = session.run(provider, root / "hold", "ollama")
            self.assertEqual((result["status"], result["reason"]), ("UNCERTAIN", "EXECUTION_ERROR"))
            self.assertTrue((root / "hold").exists())
            self.assertEqual(provider.calls, 1)
            self.assertEqual(writes.count("request_finished"), 1)
            responses = [event for event in session.events if event["kind"] == "response"]
            self.assertEqual(len(responses), 1)
            path = session.root / f"event-{responses[0]['index']:03d}.json"
            self.assertEqual(json.loads(path.read_bytes()), responses[0])

    def test_error_diagnostic_failure_preserves_original_reason_and_hold(self):
        with fixture() as (root, session):
            provider = Sequence([Refused("PROVIDER_HTTP")])
            original_emit, attempts = session.emit, []

            def fail_finish(kind, value):
                if kind == "request_finished":
                    attempts.append(value)
                    raise OSError("private diagnostic storage")
                original_emit(kind, value)

            with patch.object(session, "emit", side_effect=fail_finish):
                result = session.run(provider, root / "hold", "ollama")
            self.assertEqual((result["status"], result["reason"]), ("UNCERTAIN", "PROVIDER_HTTP"))
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["diagnostics"]["reason"], "PROVIDER_HTTP")
            self.assertEqual(provider.calls, 1)
            self.assertTrue((root / "hold").exists())

    def test_response_storage_error_records_finite_error_without_releasing_hold(self):
        with fixture() as (root, session):
            provider = Sequence([{"role": "assistant", "content": "done"}])
            original_emit = session.emit

            def fail_response(kind, value):
                if kind == "response":
                    raise OSError("private response storage")
                original_emit(kind, value)

            with patch.object(session, "emit", side_effect=fail_response):
                result = session.run(provider, root / "hold", "ollama")
            finish = diagnostics(session, "request_finished")[0]
            self.assertEqual(result["status"], "UNCERTAIN")
            self.assertEqual((finish["phase"], finish["outcome"]), ("VALIDATE", "ERROR"))
            self.assertEqual(finish["error_category"], "OS_ERROR")
            self.assertFalse(any(event["kind"] == "response" for event in session.events))
            self.assertEqual(provider.calls, 1)
            self.assertTrue((root / "hold").exists())

    def test_started_attempt_guard_error_does_not_call_provider_or_clear_hold(self):
        import agent

        with fixture() as (root, session):
            provider, hold = Sequence([]), root / "hold"
            original_write = agent.write_new

            def interrupted_hold_write(path, raw):
                original_write(path, raw)
                if path == hold:
                    raise Refused("SESSION_TIME_LIMIT")

            with patch("agent.write_new", side_effect=interrupted_hold_write):
                result = session.run(provider, hold, "ollama")
            finish = diagnostics(session, "request_finished")[0]
            self.assertEqual(result["reason"], "SESSION_TIME_LIMIT")
            self.assertEqual((finish["phase"], finish["outcome"]), ("PREPARE", "ERROR"))
            self.assertEqual(finish["reason"], "SESSION_TIME_LIMIT")
            self.assertEqual(provider.calls, 0)
            self.assertTrue(hold.exists())

    def test_uncaught_provider_error_still_has_finite_private_diagnostics(self):
        with fixture() as (root, session):
            provider = Sequence([RuntimeError("private provider failure")])
            with self.assertRaisesRegex(RuntimeError, "private provider failure"):
                session.run(provider, root / "hold", "ollama")
            finish = diagnostics(session, "request_finished")[0]
            self.assertEqual(finish["error_category"], "EXECUTION")
            self.assertEqual(finish["reason"], "EXECUTION_ERROR")
            self.assertEqual(finish["phase"], "UNKNOWN")
            self.assertEqual(provider.calls, 1)
            self.assertTrue((root / "hold").exists())
            self.assertNotIn("private", json.dumps(finish))


if __name__ == "__main__":
    unittest.main()
