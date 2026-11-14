"""Check local prerequisites, then replace this foreground process with the Workbench."""

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from agent import Refused, parse, require
from isolation import check as isolated_check
from java_check import validate_jdk
from preflight_worker import CORE_REASONS, supervise
from workbench import HERE, init_demo, load_config


# These are application limits, not claims about provider naming or capacity.
PROVIDER_MAX_BYTES = 262144
PROVIDER_MAX_MODELS = 256
_PROVIDER_IO_ERRORS = (OSError, http.client.HTTPException, ValueError)


def version(command):
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=5, check=False)
    require(result.returncode == 0 and len(result.stdout) + len(result.stderr) < 16384, "TOOL_VERSION_FAILED")
    lines = (result.stdout + result.stderr).decode("utf-8", "replace").splitlines()
    require(bool(lines), "TOOL_VERSION_FAILED")
    return lines[0]


def _provider_names(raw):
    require(type(raw) is bytes, "PROVIDER_PREFLIGHT_SHAPE")
    require(len(raw) <= PROVIDER_MAX_BYTES, "PROVIDER_PREFLIGHT_LIMIT")
    try:
        value = parse(raw)
    except (Refused, ValueError, UnicodeError, RecursionError):
        raise Refused("PROVIDER_PREFLIGHT_SHAPE") from None
    require(type(value) is dict and type(value.get("models")) is list, "PROVIDER_PREFLIGHT_SHAPE")
    rows = value["models"]
    require(len(rows) <= PROVIDER_MAX_MODELS, "PROVIDER_PREFLIGHT_LIMIT")
    names = set()
    for row in rows:
        require(type(row) is dict and type(row.get("name")) is str
                and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", row["name"]) is not None,
                "PROVIDER_PREFLIGHT_SHAPE")
        require(row["name"] not in names, "PROVIDER_PREFLIGHT_SHAPE")
        names.add(row["name"])
    return names


def _provider_reason(error):
    if isinstance(error, Refused):
        return str(error) if str(error) in CORE_REASONS else "PROVIDER_PREFLIGHT_PROTOCOL"
    if isinstance(error, TimeoutError):
        return "PROVIDER_PREFLIGHT_TIMEOUT"
    if isinstance(error, (http.client.HTTPException, ValueError)):
        return "PROVIDER_PREFLIGHT_PROTOCOL"
    return "PROVIDER_PREFLIGHT_CONNECTION"


def _provider_models(connection, path, configured, notify):
    require(path in {"/api/tags", "/api/ps"}, "PROVIDER_PREFLIGHT_SHAPE")
    response, failed = None, True
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        require(type(response.status) is int and response.status == 200, "PROVIDER_PREFLIGHT_HTTP")
        names = _provider_names(response.read(PROVIDER_MAX_BYTES + 1))
        if path == "/api/tags":
            require(configured <= names, "MODEL_NOT_INSTALLED")
        else:
            require(names <= configured, "OTHER_MODEL_LOADED")
        failed = False
        return len(names)
    except (Refused, *_PROVIDER_IO_ERRORS) as error:
        reason = _provider_reason(error)
        notify(reason)
        raise Refused(reason) from None
    finally:
        if response is not None:
            try:
                response.close()
            except _PROVIDER_IO_ERRORS:
                if not failed:
                    notify("PROVIDER_PREFLIGHT_CLEANUP")
                    raise Refused("PROVIDER_PREFLIGHT_CLEANUP") from None


def _provider_configured(models):
    require(type(models) is list and 1 <= len(models) <= 8, "PROVIDER_PREFLIGHT_SHAPE")
    require(all(type(name) is str and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", name) is not None
                for name in models), "PROVIDER_PREFLIGHT_SHAPE")
    configured = frozenset(models)
    require(len(configured) == len(models), "PROVIDER_PREFLIGHT_SHAPE")
    return configured


def _provider_query(models, notify_primary=None):
    """Pure query seam; the public provider() supplies the owned-process bound."""
    configured = _provider_configured(models)
    notified = False
    def notify(reason):
        nonlocal notified
        if notified or notify_primary is None:
            return
        notified = True
        try:
            notify_primary(reason)
        except (OSError, ValueError):
            # A broken parent channel must not replace the original failure.
            pass
    connection, failed = None, True
    try:
        try:
            # Socket operations retain their own timeout inside the worker.
            connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=5)
            _provider_models(connection, "/api/tags", configured, notify)
            loaded = _provider_models(connection, "/api/ps", configured, notify)
        except (Refused, *_PROVIDER_IO_ERRORS) as error:
            reason = _provider_reason(error)
            notify(reason)
            raise Refused(reason) from None
        failed = False
        return {"installed_models": len(configured), "loaded_approved_models": loaded, "inference_requests": 0}
    finally:
        if connection is not None:
            try:
                connection.close()
            except _PROVIDER_IO_ERRORS:
                if not failed:
                    notify("PROVIDER_PREFLIGHT_CLEANUP")
                    raise Refused("PROVIDER_PREFLIGHT_CLEANUP") from None


def provider(models):
    configured = _provider_configured(models)
    return supervise(sorted(configured))


def doctor(models, jdk_home=None):
    require(sys.platform.startswith("linux") and sys.version_info >= (3, 10), "LINUX_PYTHON_REQUIRED")
    for executable in ["/usr/bin/python3", "/usr/bin/git", "/usr/bin/bwrap", "/usr/bin/prlimit"]:
        require(Path(executable).is_file() and os.access(executable, os.X_OK), "TOOL_MISSING")
    git_version = version(["/usr/bin/git", "--version"])
    matched = re.search(r"git version ([0-9]+)[.]([0-9]+)", git_version)
    require(matched is not None and tuple(map(int, matched.groups())) >= (2, 30), "GIT_VERSION_REQUIRED")
    checks = {"python": sys.version.split()[0], "git": git_version}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "test_prerequisite.py").write_text("import unittest\nclass Ready(unittest.TestCase):\n def test_ready(self): self.assertTrue(True)\n")
        outcome = isolated_check(root, "test_prerequisite.py", 10)
    require(outcome["exit_code"] == 0 and outcome["tests_ran"] == 1
            and not any(outcome[k] for k in ["timed_out", "output_limited", "infrastructure_error"]), "ISOLATION_UNAVAILABLE")
    checks["isolated_python_check"] = "PASS"
    if jdk_home is not None:
        home = validate_jdk(jdk_home)
        checks["java"] = version([str(home / "bin/java"), "--version"])
        checks["javac"] = version([str(home / "bin/javac"), "-version"])
        compiler = re.search(r"javac ([0-9]+)", checks["javac"])
        require(compiler is not None and int(compiler.group(1)) >= 17, "JAVA_17_REQUIRED")
    else:
        checks["java"] = "NOT_CONFIGURED"
    checks["ollama"] = provider(models) if models else "NOT_CONFIGURED_SCRIPTED_ONLY"
    return {"format": "outlands-workbench-launch-v1", "status": "PASS", "checks": checks,
            "inference_requests": 0, "software_installed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--jdk-home", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace
    require(workspace.is_absolute() and not workspace.is_symlink(), "ABSOLUTE_WORKSPACE_REQUIRED")
    workspace = workspace.resolve()
    require(workspace != HERE and HERE not in workspace.parents and workspace not in HERE.parents, "WORKSPACE_OUTSIDE_SOURCE")
    require(0 <= args.port <= 65535, "PORT_RANGE")
    if args.model:
        require(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", args.model), "MODEL_NAME")
    if workspace.exists():
        require(workspace.is_dir(), "WORKSPACE_REQUIRED")
        _, models = load_config(workspace / "config.json")
        require(args.model is None or args.model in models, "MODEL_NOT_CONFIGURED")
    else:
        models = [args.model] if args.model else []
    report = doctor(models, args.jdk_home)
    print(json.dumps(report, sort_keys=True), flush=True)
    if args.check_only:
        return
    if not workspace.exists():
        init_demo(workspace, args.model)
    command = [sys.executable, "-B", str(HERE / "workbench.py"), "serve",
               "--config", str(workspace / "config.json"), "--data-dir", str(workspace / "data"),
               "--port", str(args.port)]
    if args.jdk_home is not None:
        command += ["--jdk-home", str(args.jdk_home)]
    os.execve(sys.executable, command, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError, subprocess.SubprocessError, http.client.HTTPException) as error:
        report = {"status": "REFUSED", "reason": str(error) if isinstance(error, Refused) else "PREREQUISITE_OR_STARTUP_FAILED"}
        diagnostics = getattr(error, "preflight_diagnostics", None)
        if (type(diagnostics) is dict and set(diagnostics) == {"deadline_expired", "forced_stop", "worker_reaped"}
                and all(type(value) is bool for value in diagnostics.values())):
            report["preflight_diagnostics"] = diagnostics
        print(json.dumps(report))
        raise SystemExit(2) from None
