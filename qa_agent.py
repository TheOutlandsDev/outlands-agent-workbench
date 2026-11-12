"""Offline acceptance: Python/Java launch, real Bubblewrap checks, no AI inference."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from agent import review_diff
from isolation import check
from qa_java import acceptance as java_acceptance
from qa_git import acceptance as git_acceptance
from qa_project_refresh import acceptance as refresh_acceptance
from qa_run_comparison import acceptance as comparison_acceptance
from qa_project_readiness import acceptance as readiness_acceptance
from qa_patch_bundle import acceptance as bundle_acceptance
from qa_bundle_project_check import acceptance as project_check_acceptance
from qa_bundle_workspace import acceptance as bundle_workspace_acceptance
from qa_workspace_recheck import acceptance as workspace_recheck_acceptance
from qa_snapshot_export import acceptance as snapshot_export_acceptance
from qa_snapshot_project_check import acceptance as snapshot_project_check_acceptance
from qa_snapshot_workspace import acceptance as snapshot_workspace_acceptance
from qa_snapshot_recheck import acceptance as snapshot_recheck_acceptance
from qa_snapshot_reexport import acceptance as snapshot_reexport_acceptance
from qa_snapshot_editor import acceptance as snapshot_editor_acceptance
from qa_workspace_search import acceptance as workspace_search_acceptance
from qa_task_presets import acceptance as task_presets_acceptance
from qa_preset_comparison import acceptance as preset_comparison_acceptance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jdk-home", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    work = args.work_dir.resolve()
    if work == here or here in work.parents:
        parser.error("choose a new work directory outside source")
    work.mkdir(mode=0o700, exist_ok=False)
    jdk = args.jdk_home.resolve()
    classes = work / "classes"
    classes.mkdir()
    commands = [
        [sys.executable, "-B", str(here / "agent.py")],
        [
            str(jdk / "bin/java"),
            "-cp",
            str(classes),
            "OutlandsAgentClient",
            sys.executable,
            str(here / "agent.py"),
        ],
    ]
    subprocess.run(
        [
            str(jdk / "bin/javac"),
            "--release",
            "17",
            "-Xlint:all",
            "-Werror",
            "-d",
            str(classes),
            str(here / "OutlandsAgentClient.java"),
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )
    for pattern in ["test_agent.py", "test_workbench.py", "test_project_setup.py", "test_git_workspace.py", "test_launch.py", "test_run_diagnostics.py", "test_project_context.py", "test_context_integration.py", "test_project_revisions.py", "test_project_refresh.py", "test_run_comparison.py", "test_run_comparison_integration.py", "test_project_readiness.py", "test_project_readiness_integration.py", "test_patch_bundle.py", "test_patch_bundle_integration.py", "test_bundle_project_check.py", "test_bundle_project_check_integration.py", "test_bundle_workspace.py", "test_bundle_workspace_integration.py", "test_workspace_recheck.py", "test_workspace_recheck_integration.py", "test_snapshot_export.py", "test_snapshot_export_integration.py", "test_snapshot_project_check.py", "test_snapshot_project_check_integration.py", "test_snapshot_workspace.py", "test_snapshot_workspace_integration.py", "test_snapshot_recheck.py", "test_snapshot_recheck_integration.py", "test_snapshot_reexport.py", "test_snapshot_reexport_integration.py", "test_snapshot_editor.py", "test_snapshot_editor_integration.py", "test_workspace_search.py", "test_workspace_search_integration.py", "test_task_presets.py", "test_task_presets_integration.py", "test_preset_comparison.py", "test_preset_comparison_integration.py"]:
        tests = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(here),
                "-p",
                pattern,
                "-v",
            ],
            capture_output=True,
            timeout=90 if pattern in {"test_snapshot_reexport_integration.py", "test_snapshot_editor_integration.py", "test_workspace_search_integration.py"} else 60 if pattern == "test_snapshot_recheck_integration.py" else 30,
            check=False,
        )
        (work / (pattern + ".log")).write_bytes(tests.stdout + tests.stderr)
        assert tests.returncode == 0, "offline unit tests failed"
    task = json.loads((here / "task.example.json").read_text())
    original = {
        n: hashlib.sha256((here / n).read_bytes()).hexdigest() for n in task["files"]
    }
    results = []
    for i, command in enumerate(commands):
        run = work / ("run-" + str(i))
        cmd = command + [
            "--task",
            str(here / "task.example.json"),
            "--source",
            str(here),
            "--run-dir",
            str(run),
            "--state-dir",
            str(work / "state"),
            "--backend",
            "scripted-demo",
        ]
        outcome = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        (work / ("client-" + str(i) + ".log")).write_bytes(
            outcome.stdout + outcome.stderr
        )
        assert outcome.returncode == 0 and not outcome.stderr, "scripted client failed"
        result = json.loads((run / "result.json").read_text())
        assert result["status"] == "REVIEW_READY" and not result["ai_inference"]
        assert not result["source_adopted"] and result["turns"] == 6
        assert (run / "work/calculator.py").read_text() == (
            here / "calculator.py"
        ).read_text().replace("return a - b", "return a + b")
        assert (run / "work/test_calculator.py").read_bytes() == (
            here / "test_calculator.py"
        ).read_bytes()
        events = [json.loads(p.read_text()) for p in sorted(run.glob("event-*.json"))]
        baseline = next(e["value"] for e in events if e["kind"] == "baseline_checks")[
            "unit"
        ]
        final = next(
            e["value"] for e in events if e["kind"] == "independent_final_checks"
        )["unit"]
        assert (
            baseline["exit_code"] == 1
            and final["exit_code"] == 0
            and baseline["tests_ran"] == final["tests_ran"] == 4
        )
        assert original == {
            n: hashlib.sha256((here / n).read_bytes()).hexdigest()
            for n in task["files"]
        }
        assert (
            json.loads(outcome.stdout)["result_sha256"]
            == hashlib.sha256((run / "result.json").read_bytes()).hexdigest()
        )
        results.append(result)
    assert results[0] == results[1], "Java and Python client result parity failed"
    patch_check = work / "patch-check"
    patch_check.mkdir()
    before = (here / "calculator.py").read_bytes()
    (patch_check / "calculator.py").write_bytes(before)
    unterminated = before.replace(b"return a - b", b"return a + b").rstrip(b"\n")
    patch_file = work / "unterminated.diff"
    patch_file.write_text(review_diff("calculator.py", before, unterminated))
    subprocess.run(
        ["/usr/bin/git", "-C", str(patch_check), "apply", "--check", str(patch_file)],
        capture_output=True,
        timeout=10,
        check=True,
    )
    probe = work / "probe"
    probe.mkdir()
    (probe / "test_boundary.py").write_text("""import pathlib, socket, unittest
class Boundary(unittest.TestCase):
    def test_original_roots_hidden(self):
        for name in ["/home", "/srv", "/run", "/etc"]:
            self.assertFalse(pathlib.Path(name).exists())
    def test_read_only_work(self):
        with self.assertRaises(OSError):
            pathlib.Path("/work/forbidden").write_text("x")
    def test_loopback_is_separate(self):
        with socket.socket() as s:
            s.settimeout(1)
            self.assertNotEqual(s.connect_ex(("127.0.0.1", 11434)), 0)
""")
    boundary = check(probe, "test_boundary.py", 10)
    assert boundary["exit_code"] == 0 and boundary["tests_ran"] == 3, (
        "sandbox boundary failed"
    )
    (probe / "test_slow.py").write_text(
        "import time, unittest\nclass Slow(unittest.TestCase):\n def test_wait(self): time.sleep(20)\n"
    )
    timeout = check(probe, "test_slow.py", 1)
    assert timeout["timed_out"], "timeout was not enforced"
    (probe / "test_loud.py").write_text(
        "import unittest\nclass Loud(unittest.TestCase):\n def test_output(self): print('x' * 100000)\n"
    )
    loud = check(probe, "test_loud.py", 10)
    assert loud["output_limited"], "output bound not enforced"
    report = {
        "status": "PASS",
        "ai_inference": False,
        "client_runs": 2,
        "client_result_parity": True,
        "baseline_tests_per_run": 4,
        "final_tests_per_run": 4,
        "boundary_tests": 3,
        "timeout_enforced": True,
        "output_limit_enforced": True,
        "source_unchanged": True,
        "unterminated_diff_git_check": True,
        "patch_sha256": results[0]["patch_sha256"],
        **java_acceptance(jdk, work),
        **git_acceptance(jdk, work),
        **refresh_acceptance(jdk, work),
        **comparison_acceptance(work),
        **readiness_acceptance(work),
        **bundle_acceptance(work),
        **project_check_acceptance(work),
        **bundle_workspace_acceptance(jdk, work),
        **workspace_recheck_acceptance(jdk, work),
        **snapshot_export_acceptance(jdk, work),
        **snapshot_project_check_acceptance(jdk, work),
        **snapshot_workspace_acceptance(jdk, work),
        **snapshot_recheck_acceptance(jdk, work),
        **snapshot_reexport_acceptance(jdk, work),
        **snapshot_editor_acceptance(jdk, work),
        **workspace_search_acceptance(jdk, work),
        **task_presets_acceptance(jdk, work),
        **preset_comparison_acceptance(jdk, work),
    }
    (work / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
