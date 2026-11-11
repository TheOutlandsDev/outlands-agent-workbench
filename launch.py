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
from workbench import HERE, init_demo, load_config


def version(command):
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=5, check=False)
    require(result.returncode == 0 and len(result.stdout) + len(result.stderr) < 16384, "TOOL_VERSION_FAILED")
    lines = (result.stdout + result.stderr).decode("utf-8", "replace").splitlines()
    require(bool(lines), "TOOL_VERSION_FAILED")
    return lines[0]


def provider(models):
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=5)
    try:
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        require(response.status == 200, "PROVIDER_PREFLIGHT_HTTP")
        installed = parse(response.read(262145))
        require(isinstance(installed, dict) and isinstance(installed.get("models"), list), "PROVIDER_PREFLIGHT_SHAPE")
        names = {row.get("name") for row in installed["models"] if isinstance(row, dict) and isinstance(row.get("name"), str)}
        require(set(models) <= names, "MODEL_NOT_INSTALLED")
        connection.request("GET", "/api/ps")
        response = connection.getresponse()
        require(response.status == 200, "PROVIDER_PREFLIGHT_HTTP")
        loaded = parse(response.read(262145))
        require(isinstance(loaded, dict) and isinstance(loaded.get("models"), list), "PROVIDER_PREFLIGHT_SHAPE")
        require(all(isinstance(row, dict) and row.get("name") in models for row in loaded["models"]), "OTHER_MODEL_LOADED")
        return {"installed_models": len(models), "loaded_approved_models": len(loaded["models"]), "inference_requests": 0}
    finally:
        connection.close()


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
        print(json.dumps({"status": "REFUSED", "reason": str(error) if isinstance(error, Refused) else "PREREQUISITE_OR_STARTUP_FAILED"}))
        raise SystemExit(2) from None
