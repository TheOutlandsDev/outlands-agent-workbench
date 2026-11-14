"""Prerequisite outcomes and foreground launch contract; no model requests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Refused
from launch import doctor, main, provider
import launch


PASS = {"exit_code": 0, "tests_ran": 1, "timed_out": False, "output_limited": False, "infrastructure_error": False}
QUERY = getattr(launch, "_provider_query", provider)


class LaunchTests(unittest.TestCase):
    @patch("launch.isolated_check", return_value=PASS)
    @patch("launch.version", return_value="git version 2.34.1")
    def test_scripted_checks_do_not_contact_model(self, _version, _isolated):
        with patch("launch.provider") as model:
            result = doctor([])
            model.assert_not_called()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["inference_requests"], 0)

    @patch("launch.version", return_value="git version 2.20.0")
    def test_old_git_refused(self, _version):
        with self.assertRaisesRegex(Refused, "GIT_VERSION_REQUIRED"): doctor([])

    @patch("launch.Path.is_file", return_value=False)
    def test_missing_tool_refused(self, _exists):
        with self.assertRaisesRegex(Refused, "TOOL_MISSING"): doctor([])

    @patch("launch.isolated_check", return_value={**PASS, "exit_code": 1})
    @patch("launch.version", return_value="git version 2.34.1")
    def test_unavailable_namespace_refused(self, _version, _isolated):
        with self.assertRaisesRegex(Refused, "ISOLATION_UNAVAILABLE"): doctor([])

    @patch("launch.validate_jdk", return_value=Path("/fictional/jdk"))
    @patch("launch.isolated_check", return_value=PASS)
    @patch("launch.version", side_effect=["git version 2.34.1", "openjdk 15", "javac 15"])
    def test_old_java_refused(self, _version, _isolated, _jdk):
        with self.assertRaisesRegex(Refused, "JAVA_17_REQUIRED"): doctor([], Path("/fictional/jdk"))

    def test_provider_uses_only_read_only_requests(self):
        connection = Mock()
        tag, ps = Mock(status=200), Mock(status=200)
        tag.read.return_value = b'{"models":[{"name":"fictional-model"}]}'
        ps.read.return_value = b'{"models":[]}'
        connection.getresponse.side_effect = [tag, ps]
        with patch("launch.http.client.HTTPConnection", return_value=connection):
            self.assertEqual(QUERY(["fictional-model"])["inference_requests"], 0)
        self.assertEqual([c.args for c in connection.request.call_args_list], [("GET", "/api/tags"), ("GET", "/api/ps")])

    def test_missing_model_refused_without_download(self):
        connection = Mock(); response = Mock(status=200)
        response.read.return_value = b'{"models":[]}'
        connection.getresponse.return_value = response
        with patch("launch.http.client.HTTPConnection", return_value=connection), self.assertRaisesRegex(Refused, "MODEL_NOT_INSTALLED"):
            QUERY(["fictional-model"])
        self.assertEqual(connection.request.call_count, 1)

    @patch("launch.doctor", return_value={"status": "PASS"})
    def test_check_only_does_not_create_workspace_or_launch(self, _doctor):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "new"
            with patch("sys.argv", ["launch.py", "--workspace", str(workspace), "--check-only"]), patch("launch.os.execve") as execute:
                main()
                execute.assert_not_called()
            self.assertFalse(workspace.exists())

    @patch("launch.doctor", return_value={"status": "PASS"})
    def test_new_foreground_launch_preserves_explicit_arguments(self, _doctor):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "new"
            with patch("sys.argv", ["launch.py", "--workspace", str(workspace), "--port", "8765"]), patch("launch.os.execve") as execute:
                main()
            args = execute.call_args.args
            self.assertIn(str(workspace / "config.json"), args[1])
            self.assertIn("8765", args[1])
            self.assertNotIn("PYTHONPATH", args[2])
            self.assertTrue((workspace / "config.json").is_file())


if __name__ == "__main__":
    unittest.main()
