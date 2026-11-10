"""Offline engine tests. No inference and no execution of supplied source."""

import io
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
    gate,
    main,
    parse,
    read_file,
    relative,
    review_diff,
    sha,
    validate_task,
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

    def request(self, messages, seconds):
        del messages, seconds
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        return item


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
            for raw in [b"x" * 16385, b"\x00"]:
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
        self.assertEqual(len(payload["tools"]), 4)
        self.assertEqual(result["content"], "hello")


if __name__ == "__main__":
    unittest.main()
