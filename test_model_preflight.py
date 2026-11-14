"""Fake-only model preflight contracts; no provider, check or process is run.

The CLI cases call main() in process with fixed-tool/isolated-check fakes. They
do not exercise a native CLI process, a real model, a server or a global timeout.
Cleanup counters describe application calls, not HTTP library internal closes.
"""

import hashlib
import http.client
import io
import json
import os
import socket
import stat
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import launch
from agent import Refused


MODEL = "invented-model:unit"
OTHER = "invented-other:unit"
LIMIT = 262144
PREFIX = "PROVIDER_PREFLIGHT_"
ISOLATION_PASS = {
    "exit_code": 0, "tests_ran": 1, "timed_out": False,
    "output_limited": False, "infrastructure_error": False,
}


def payload(names, **extra):
    return json.dumps({"models": [{"name": name} for name in names], **extra}).encode()


class FakeResponse:
    def __init__(self, endpoint, raw, status, faults, events):
        self.endpoint = endpoint
        self.raw = raw
        self.status = status
        self.faults = faults
        self.events = events
        self.read_sizes = []
        self.close_calls = 0

    def read(self, amount):
        self.read_sizes.append(amount)
        self.events.append(("read", self.endpoint))
        error = self.faults.get(("read", self.endpoint))
        if error is not None:
            raise error
        return self.raw[:amount]

    def close(self):
        self.close_calls += 1
        self.events.append(("response_close", self.endpoint))
        error = self.faults.get(("response_close", self.endpoint))
        if error is not None:
            raise error


class FakeConnection:
    """Only the two contracted GET operations exist; no socket is available."""

    def __init__(self, tags, ps, statuses=None, faults=None):
        self.faults = faults or {}
        self.events = []
        statuses = statuses or {}
        self.responses = {
            "/api/tags": FakeResponse("/api/tags", tags, statuses.get("/api/tags", 200), self.faults, self.events),
            "/api/ps": FakeResponse("/api/ps", ps, statuses.get("/api/ps", 200), self.faults, self.events),
        }
        self.requests = []
        self.returned = []
        self.current = None
        self.close_calls = 0

    def request(self, method, endpoint, *args, **kwargs):
        if args or kwargs or method != "GET" or endpoint not in self.responses:
            raise AssertionError("unexpected provider operation")
        if self.requests != [("GET", path) for path in ("/api/tags", "/api/ps")[:len(self.requests)]]:
            raise AssertionError("provider request ordering")
        if len(self.requests) >= 2 or endpoint != ("/api/tags", "/api/ps")[len(self.requests)]:
            raise AssertionError("provider retry or extra request")
        self.requests.append((method, endpoint))
        self.current = endpoint
        self.events.append(("request", endpoint))
        error = self.faults.get(("request", endpoint))
        if error is not None:
            raise error

    def getresponse(self):
        if self.current is None or self.current in self.returned:
            raise AssertionError("unexpected response operation")
        self.events.append(("getresponse", self.current))
        error = self.faults.get(("getresponse", self.current))
        if error is not None:
            raise error
        self.returned.append(self.current)
        return self.responses[self.current]

    def close(self):
        self.close_calls += 1
        self.events.append(("connection_close", None))
        error = self.faults.get(("connection_close", None))
        if error is not None:
            raise error


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.denied = []
        for target in ("socket.socket", "socket.create_connection", "subprocess.Popen", "subprocess.run",
                       "os.execve", "os.system", "os.posix_spawn", "os.posix_spawnp", "os.fork"):
            mock = self.stack.enter_context(patch(target, side_effect=AssertionError("real I/O forbidden in offline tests")))
            self.denied.append(mock)

    def tearDown(self):
        for forbidden in self.denied:
            forbidden.assert_not_called()

    @contextmanager
    def transport(self, tags=None, ps=None, statuses=None, faults=None, constructor_error=None):
        connection = FakeConnection(payload([MODEL]) if tags is None else tags,
                                    payload([]) if ps is None else ps, statuses, faults)
        factory = Mock(return_value=connection, side_effect=constructor_error)
        with patch("launch.http.client.HTTPConnection", factory):
            try:
                yield connection, factory
            finally:
                if factory.called:
                    factory.assert_called_once_with("127.0.0.1", 11434, timeout=5)
                    self.assertEqual(connection.close_calls, 0 if constructor_error is not None else 1)
                else:
                    self.assertEqual(connection.close_calls, 0)
                self.assertLessEqual(len(connection.requests), 2)
                for endpoint, response in connection.responses.items():
                    self.assertEqual(response.close_calls, int(endpoint in connection.returned))
                    self.assertTrue(all(amount == LIMIT + 1 for amount in response.read_sizes))
                if connection.close_calls:
                    self.assertEqual(connection.events[-1], ("connection_close", None))

    def refuses(self, code, models=None):
        with self.assertRaises(Refused) as caught:
            launch.provider([MODEL] if models is None else models)
        self.assertEqual(str(caught.exception), code)


class ModelPreflightTests(OfflineCase):
    def test_success_counts_empty_and_approved_loaded_models(self):
        for approved, loaded in (([MODEL], []), ([MODEL], [MODEL]), ([MODEL, OTHER], [OTHER, MODEL])):
            with self.subTest(loaded=loaded), self.transport(tags=payload(approved + ["invented-installed-extra"]), ps=payload(loaded)) as (connection, _):
                self.assertEqual(launch.provider(approved), {
                    "installed_models": len(approved), "loaded_approved_models": len(loaded), "inference_requests": 0,
                })
                self.assertEqual(connection.requests, [("GET", "/api/tags"), ("GET", "/api/ps")])
                self.assertLess(connection.events.index(("response_close", "/api/tags")),
                                connection.events.index(("request", "/api/ps")))

    def test_extra_api_fields_are_accepted(self):
        raw = json.dumps({"models": [{"name": MODEL, "size": 7, "details": {"family": "invented"}}], "next": None}).encode()
        with self.transport(tags=raw, ps=raw):
            self.assertEqual(launch.provider([MODEL])["loaded_approved_models"], 1)

    def test_missing_installed_model_stops_before_loaded_query(self):
        with self.transport(tags=payload([OTHER])) as (connection, _):
            self.refuses("MODEL_NOT_INSTALLED")
            self.assertEqual(connection.requests, [("GET", "/api/tags")])

    def test_valid_unapproved_loaded_model_has_distinct_reason(self):
        with self.transport(ps=payload([OTHER])):
            self.refuses("OTHER_MODEL_LOADED")

    def test_non_200_responses_are_refused_at_either_endpoint(self):
        for endpoint in ("/api/tags", "/api/ps"):
            for status in (201, 302, 401, 500):
                with self.subTest(endpoint=endpoint, status=status), self.transport(statuses={endpoint: status}) as (connection, _):
                    self.refuses(PREFIX + "HTTP")
                    self.assertEqual(connection.responses[endpoint].read_sizes, [])
                    self.assertEqual(len(connection.requests), 1 if endpoint == "/api/tags" else 2)

    def test_invalid_json_utf8_duplicate_keys_and_constants_are_shape_errors(self):
        invalid = [b"{", b"\xff", b'{} trailing', b'{"models":[],"models":[]}',
                   b'{"models":[{"name":"a","name":"b"}]}',
                   b'{"models":[],"other":{"same":1,"same":2}}',
                   b'{"models":[],"other":NaN}', b'{"models":[],"other":Infinity}',
                   b'{"models":[],"other":-Infinity}',
                   b'{"models":[],"other":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}"]
        for endpoint in ("/api/tags", "/api/ps"):
            for index, raw in enumerate(invalid):
                with self.subTest(endpoint=endpoint, case=index), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                    self.refuses(PREFIX + "SHAPE")

    def test_invalid_root_and_models_containers_are_shape_errors(self):
        for endpoint in ("/api/tags", "/api/ps"):
            for value in (None, True, 42, [], "invented", {}, {"models": None}, {"models": {}}, {"models": "invented"}):
                raw = json.dumps(value).encode()
                with self.subTest(endpoint=endpoint, value=value), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                    self.refuses(PREFIX + "SHAPE")

    def test_malformed_extra_rows_are_not_silently_ignored(self):
        for endpoint in ("/api/tags", "/api/ps"):
            for row in (None, False, 17, "invented", []):
                raw = json.dumps({"models": [{"name": MODEL}, row]}).encode()
                with self.subTest(endpoint=endpoint, row=row), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                    self.refuses(PREFIX + "SHAPE")

    def test_missing_or_invalid_model_names_are_shape_errors(self):
        rows = [{}, *({"name": name} for name in (None, False, 17, [], {}, "", "x" * 97, "with space", "line\nname", "nul\0name", "\u03bb"))]
        for endpoint in ("/api/tags", "/api/ps"):
            for index, row in enumerate(rows):
                raw = json.dumps({"models": [{"name": MODEL}, row]}).encode()
                with self.subTest(endpoint=endpoint, case=index), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                    self.refuses(PREFIX + "SHAPE")

    def test_duplicate_api_model_names_are_refused(self):
        for endpoint in ("/api/tags", "/api/ps"):
            raw = payload([MODEL, MODEL])
            with self.subTest(endpoint=endpoint), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                self.refuses(PREFIX + "SHAPE")

    def test_api_row_limit_is_bounded_before_membership(self):
        maximum = [MODEL] + ["invented-%03d" % n for n in range(255)]
        with self.transport(tags=payload(maximum)):
            self.assertEqual(launch.provider([MODEL])["installed_models"], 1)
        for endpoint in ("/api/tags", "/api/ps"):
            raw = payload(maximum + ["invented-over-limit"])
            with self.subTest(endpoint=endpoint), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                self.refuses(PREFIX + "LIMIT")

    def test_exact_body_bound_and_one_byte_over_at_both_endpoints(self):
        for endpoint in ("/api/tags", "/api/ps"):
            base = payload([MODEL])
            for extra in (0, 1):
                raw = base + b" " * (LIMIT + extra - len(base))
                with self.subTest(endpoint=endpoint, extra=extra), self.transport(**({"tags": raw} if endpoint == "/api/tags" else {"ps": raw})):
                    if extra:
                        self.refuses(PREFIX + "LIMIT")
                    else:
                        self.assertEqual(launch.provider([MODEL])["inference_requests"], 0)

    def test_configured_models_are_validated_before_connection(self):
        invalid = (None, MODEL, (MODEL,), [], [MODEL, MODEL], [None], [True], [17],
                   [""], ["with space"], ["\u03bb"], ["x" * 97], ["invented-%d" % n for n in range(9)])
        for index, models in enumerate(invalid):
            with self.subTest(case=index), self.transport() as (_, factory):
                with self.assertRaises(Refused) as caught:
                    launch.provider(models)
                self.assertEqual(str(caught.exception), PREFIX + "SHAPE")
                factory.assert_not_called()

    def test_configured_count_and_name_length_boundaries(self):
        names = ["x" * 96] + ["invented-%d" % n for n in range(7)]
        with self.transport(tags=payload(names), ps=payload(names)):
            self.assertEqual(launch.provider(names), {"installed_models": 8, "loaded_approved_models": 8, "inference_requests": 0})

    def _fault_at_stages(self, make_error, code):
        stages = [("constructor", None)] + [(stage, endpoint) for endpoint in ("/api/tags", "/api/ps") for stage in ("request", "getresponse", "read")]
        for stage, endpoint in stages:
            error = make_error()
            options = {"constructor_error": error} if stage == "constructor" else {"faults": {(stage, endpoint): error}}
            with self.subTest(stage=stage, endpoint=endpoint), self.transport(**options) as (connection, _):
                self.refuses(PREFIX + code)
                self.assertEqual(len(connection.requests), 0 if stage == "constructor" else (1 if endpoint == "/api/tags" else 2))

    def test_timeouts_at_constructor_request_response_or_read_are_finite(self):
        self._fault_at_stages(lambda: socket.timeout("invented timeout detail"), "TIMEOUT")

    def test_os_errors_at_constructor_request_response_or_read_are_finite(self):
        self._fault_at_stages(lambda: OSError("invented private transport detail"), "CONNECTION")

    def test_disconnects_are_protocol_errors_without_retry(self):
        self._fault_at_stages(lambda: http.client.RemoteDisconnected("invented disconnect detail"), "PROTOCOL")

    def test_http_protocol_errors_and_value_errors_are_finite(self):
        for make_error in (lambda: http.client.BadStatusLine("invented status detail"), lambda: ValueError("invented protocol detail")):
            self._fault_at_stages(make_error, "PROTOCOL")

    def test_incomplete_response_read_is_protocol_error(self):
        for endpoint in ("/api/tags", "/api/ps"):
            with self.subTest(endpoint=endpoint), self.transport(faults={("read", endpoint): http.client.IncompleteRead(b"invented partial") }):
                self.refuses(PREFIX + "PROTOCOL")

    def test_response_cleanup_failure_refuses_before_any_next_get(self):
        for endpoint in ("/api/tags", "/api/ps"):
            for make_error in (lambda: OSError("invented cleanup"), lambda: TimeoutError("invented cleanup"), lambda: http.client.HTTPException("invented cleanup"), lambda: ValueError("invented cleanup")):
                with self.subTest(endpoint=endpoint, kind=make_error().__class__.__name__), self.transport(faults={("response_close", endpoint): make_error()}) as (connection, _):
                    self.refuses(PREFIX + "CLEANUP")
                    self.assertEqual(len(connection.requests), 1 if endpoint == "/api/tags" else 2)

    def test_connection_cleanup_failure_after_success_is_finite(self):
        for error in (OSError("invented cleanup"), TimeoutError("invented cleanup"), http.client.HTTPException("invented cleanup"), ValueError("invented cleanup")):
            with self.subTest(kind=type(error).__name__), self.transport(faults={("connection_close", None): error}):
                self.refuses(PREFIX + "CLEANUP")

    def test_primary_refusal_survives_response_and_connection_cleanup_failures(self):
        cases = [
            ({"statuses": {"/api/tags": 503}}, "/api/tags", PREFIX + "HTTP"),
            ({"tags": b"{"}, "/api/tags", PREFIX + "SHAPE"),
            ({"tags": b" " * (LIMIT + 1)}, "/api/tags", PREFIX + "LIMIT"),
            ({"tags": payload([])}, "/api/tags", "MODEL_NOT_INSTALLED"),
            ({"ps": payload([OTHER])}, "/api/ps", "OTHER_MODEL_LOADED"),
            ({"faults": {("read", "/api/ps"): TimeoutError("invented primary")}}, "/api/ps", PREFIX + "TIMEOUT"),
            ({"faults": {("read", "/api/ps"): OSError("invented primary")}}, "/api/ps", PREFIX + "CONNECTION"),
            ({"faults": {("read", "/api/ps"): http.client.RemoteDisconnected("invented primary")}}, "/api/ps", PREFIX + "PROTOCOL"),
        ]
        for options, endpoint, expected in cases:
            options = dict(options)
            faults = dict(options.pop("faults", {}))
            faults.update({("response_close", endpoint): OSError("invented secondary response cleanup"),
                           ("connection_close", None): OSError("invented secondary connection cleanup")})
            with self.subTest(expected=expected), self.transport(**options, faults=faults):
                self.refuses(expected)

    def test_unexpected_programmer_errors_escape_but_still_clean_up(self):
        for make_error in (lambda: RuntimeError("invented programmer error"), lambda: TypeError("invented programmer error"), lambda: AssertionError("invented programmer error")):
            for stage in ("constructor", "request", "getresponse", "read", "response_close", "connection_close"):
                error = make_error()
                faults = {("connection_close", None): OSError("invented secondary cleanup")}
                if stage != "constructor":
                    faults[(stage, None if stage == "connection_close" else "/api/tags")] = error
                if stage == "read":
                    faults[("response_close", "/api/tags")] = OSError("invented secondary cleanup")
                options = {"constructor_error": error} if stage == "constructor" else {"faults": faults}
                with self.subTest(stage=stage, kind=type(error).__name__), self.transport(**options):
                    with self.assertRaises(type(error)) as caught:
                        launch.provider([MODEL])
                    self.assertIs(caught.exception, error)


def tree_rows(root):
    """Snapshot only a fresh test-owned tree, including directory link counts."""
    result = {}
    if not root.exists():
        return result
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        row = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_nlink)
        if path.is_file():
            raw = path.read_bytes()
            row += (len(raw), hashlib.sha256(raw).hexdigest())
        result[str(path.relative_to(root))] = row
    return result


def existing_workspace(parent, models):
    root = parent / "existing"
    project = root / "project"
    root.mkdir(mode=0o700)
    project.mkdir(mode=0o700)
    raw_files = {"answer.py": b"def answer():\n    return 7\n", "test_answer.py": b"# Invented protected fixture; never executed.\n"}
    for name, raw in raw_files.items():
        (project / name).write_bytes(raw)
        (project / name).chmod(0o600)
    task = {"format": "outlands-coding-agent-v1", "goal": "Invented preflight-only fixture; do not execute.",
            "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in raw_files.items()},
            "editable": ["answer.py"], "checks": {"unit": "test_answer.py"}, "max_turns": 2, "request_seconds": 5}
    (root / "task.json").write_text(json.dumps(task))
    config = {"format": "outlands-workbench-config-v1", "models": models,
              "projects": [{"id": "invented", "name": "Invented preflight", "source": str(project), "task": str(root / "task.json")}]}
    (root / "config.json").write_text(json.dumps(config))
    (root / "task.json").chmod(0o600)
    (root / "config.json").chmod(0o600)
    (root / "data").mkdir(mode=0o700)
    (root / "data" / "owner-sentinel.txt").write_bytes(b"Invented configured state: preserve exactly.\n")
    (root / "data" / "owner-sentinel.txt").chmod(0o600)
    return root


class ModelPreflightCliTests(OfflineCase):
    @contextmanager
    def doctor_fakes(self):
        with patch("launch.version", return_value="git version 2.34.1") as version, \
                patch("launch.isolated_check", return_value=ISOLATION_PASS) as isolated, \
                patch("launch.validate_jdk", side_effect=AssertionError("no JDK in this fixture")) as jdk, \
                patch("launch.init_demo", side_effect=AssertionError("check-only must not initialize")) as initialize, \
                patch("launch.os.access", return_value=True), patch("launch.Path.is_file", return_value=True):
            yield version, isolated
            jdk.assert_not_called()
            initialize.assert_not_called()

    def invoke(self, workspace, model=MODEL):
        args = ["launch.py", "--workspace", str(workspace), "--model", model, "--check-only"]
        output = io.StringIO()
        with patch("sys.argv", args), redirect_stdout(output):
            launch.main()
        return json.loads(output.getvalue())

    def test_fresh_model_check_only_uses_real_doctor_control_flow_without_init(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            workspace = parent / "never-created"
            before = tree_rows(parent)
            with self.doctor_fakes() as (version, isolated), self.transport() as (connection, _):
                report = self.invoke(workspace)
                version.assert_called_once_with(["/usr/bin/git", "--version"])
                isolated.assert_called_once()
                self.assertEqual(connection.requests, [("GET", "/api/tags"), ("GET", "/api/ps")])
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["checks"]["ollama"], {"installed_models": 1, "loaded_approved_models": 0, "inference_requests": 0})
            self.assertEqual(report["checks"]["java"], "NOT_CONFIGURED")
            self.assertFalse(workspace.exists())
            self.assertEqual(tree_rows(parent), before)

    def test_existing_check_only_keeps_all_configured_models_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            workspace = existing_workspace(parent, [MODEL, OTHER])
            before = tree_rows(parent)
            with self.doctor_fakes(), self.transport(tags=payload([MODEL, OTHER]), ps=payload([OTHER])):
                report = self.invoke(workspace)
            self.assertEqual(report["checks"]["ollama"], {"installed_models": 2, "loaded_approved_models": 1, "inference_requests": 0})
            self.assertEqual(tree_rows(parent), before)

    def test_refused_fresh_preflight_never_creates_workspace_or_handoff(self):
        cases = [({"tags": payload([])}, "MODEL_NOT_INSTALLED"),
                 ({"tags": b"{"}, PREFIX + "SHAPE"),
                 ({"statuses": {"/api/ps": 503}}, PREFIX + "HTTP"),
                 ({"faults": {("read", "/api/ps"): OSError("invented unavailable")}}, PREFIX + "CONNECTION"),
                 ({"faults": {("response_close", "/api/tags"): OSError("invented cleanup")}}, PREFIX + "CLEANUP")]
        for options, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                workspace = parent / "never-created"
                before = tree_rows(parent)
                with self.doctor_fakes(), self.transport(**options), self.assertRaises(Refused) as caught:
                    self.invoke(workspace)
                self.assertEqual(str(caught.exception), code)
                self.assertFalse(workspace.exists())
                self.assertEqual(tree_rows(parent), before)

    def test_refused_existing_preflight_preserves_config_task_source_and_state(self):
        cases = [({"ps": payload([OTHER])}, "OTHER_MODEL_LOADED"),
                 ({"tags": payload([MODEL, MODEL])}, PREFIX + "SHAPE"),
                 ({"constructor_error": TimeoutError("invented timeout")}, PREFIX + "TIMEOUT"),
                 ({"faults": {("connection_close", None): OSError("invented cleanup")}}, PREFIX + "CLEANUP")]
        for options, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                workspace = existing_workspace(parent, [MODEL])
                before = tree_rows(parent)
                with self.doctor_fakes(), self.transport(**options), self.assertRaises(Refused) as caught:
                    self.invoke(workspace)
                self.assertEqual(str(caught.exception), code)
                self.assertEqual(tree_rows(parent), before)

    def test_unconfigured_cli_model_refuses_before_doctor_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            workspace = existing_workspace(parent, [MODEL])
            before = tree_rows(parent)
            with self.doctor_fakes() as (version, isolated), self.transport() as (_, factory), self.assertRaises(Refused) as caught:
                self.invoke(workspace, OTHER)
            self.assertEqual(str(caught.exception), "MODEL_NOT_CONFIGURED")
            version.assert_not_called()
            isolated.assert_not_called()
            factory.assert_not_called()
            self.assertEqual(tree_rows(parent), before)


if __name__ == "__main__":
    unittest.main()
