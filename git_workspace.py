"""Apply an accepted patch to a private, selected-file Git worktree and recheck it."""

import argparse
import os
import re
import subprocess
import time
from pathlib import Path

from agent import Refused, atomic_json, canonical, parse, read_file, require, sha, validate_task, write_new
from isolation import check as python_check
from java_check import check as java_check

FORBIDDEN = {".git", ".gitattributes", ".gitmodules", ".gitconfig"}


def validate_files(task):
    require(not any(set(p.lower() for p in n.split("/")) & FORBIDDEN for n in task["files"]), "GIT_CONTROL_FILE_REFUSED")


def git(root, *arguments):
    command = ["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
               "-c", "core.autocrlf=false", "-c", "core.attributesFile=/dev/null",
               "-c", "commit.gpgSign=false", "-c", "core.fsmonitor=false",
               "-c", "user.name=OUTLANDS Workbench", "-c", "user.email=workbench@example.invalid",
               "-C", str(root), *arguments]
    outcome = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                             timeout=15, check=False,
                             env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                                  "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                                  "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    require(len(outcome.stdout) + len(outcome.stderr) <= 262144, "GIT_OUTPUT_LIMIT")
    require(outcome.returncode == 0, "GIT_COMMAND_FAILED")
    return outcome.stdout


def snapshot_files(root, expected, git_control=False):
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_dir()}
    if git_control:
        actual.discard(".git")
    require(actual == set(expected), "WORKSPACE_SCOPE_CHANGED")
    for name, digest in expected.items():
        require(sha(read_file(root, name)) == digest, "WORKSPACE_BYTES_CHANGED")


def fixed_checks(work, task, jdk_home):
    results = {}
    for name, spec in task["checks"].items():
        if isinstance(spec, dict) and spec["kind"] == "java-main":
            require(jdk_home is not None, "JDK_REQUIRED")
            result = java_check(work, spec, 10, jdk_home)
        else:
            pattern = spec["pattern"] if isinstance(spec, dict) else spec
            result = python_check(work, pattern, 10)
        results[name] = result
    return results


def completed_checks(results):
    return bool(results) and all(r["exit_code"] == 0 and r["tests_ran"] > 0
                                and not any(r[k] for k in ["timed_out", "output_limited", "infrastructure_error"])
                                for r in results.values())


def inspect(root, task, result, receipt):
    require(receipt["status"] == "VERIFIED", "WORKSPACE_NEEDS_INSPECTION")
    work = root / "review"
    snapshot_files(work, {n: row["after"] for n, row in result["files"].items()}, True)
    require(git(work, "rev-parse", "HEAD").decode().strip() == receipt["baseline_commit"], "WORKSPACE_HEAD_CHANGED")
    require(git(work, "symbolic-ref", "--short", "HEAD").decode().strip() == receipt["branch"], "WORKSPACE_BRANCH_CHANGED")
    changed = {n.decode() for n in git(work, "diff", "--name-only", "-z", "HEAD", "--").split(b"\0") if n}
    expected = {n for n in task["editable"] if result["files"][n]["before"] != result["files"][n]["after"]}
    require(changed == expected, "WORKSPACE_DIFF_CHANGED")


def build(run, destination, source, result_hash, patch_hash, jdk_home=None, checker=fixed_checks):
    receipt_path = run / "git-workspace.json"
    receipt = parse(read_file(run, receipt_path.name, 262144))
    require(receipt["status"] == "PREPARING" and receipt["result_sha256"] == result_hash
            and receipt["patch_sha256"] == patch_hash, "WORKSPACE_REQUEST_CHANGED")
    try:
        task = validate_task(parse(read_file(run, "task.json", 262144)))
        result = parse(read_file(run, "result.json", 262144))
        patch = read_file(run, "changes.diff", 1048576)
        require(sha(canonical(result)) == result_hash and result["status"] == "REVIEW_READY"
                and sha(patch) == patch_hash == result["patch_sha256"], "WORKSPACE_ARTIFACT_CHANGED")
        reviews = sorted(run.glob("review-*.json"))
        require(bool(reviews), "REVIEW_REQUIRED")
        review = parse(read_file(run, reviews[-1].name, 262144))
        require(review["verdict"] == "accepted" and review["result_sha256"] == result_hash
                and review["patch_sha256"] == patch_hash, "REVIEW_CHANGED")
        validate_files(task)
        require(set(result["files"]) == set(task["files"]), "WORKSPACE_SCOPE_CHANGED")
        for name, digest in task["files"].items():
            require(sha(read_file(source, name)) == digest == result["files"][name]["before"], "ORIGINAL_SOURCE_CHANGED")
            require(sha(read_file(run / "baseline", name)) == digest, "BASELINE_CHANGED")
            require(sha(read_file(run / "work", name)) == result["files"][name]["after"], "CANDIDATE_CHANGED")
            if name not in task["editable"]:
                require(result["files"][name]["after"] == digest, "PROTECTED_FILE_CHANGED")
        destination.mkdir(mode=0o700, exist_ok=False)
        repository = destination / "baseline-repo"
        repository.mkdir(mode=0o700)
        template = destination / "empty-template"
        template.mkdir(mode=0o700)
        for name in task["files"]:
            target = repository / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_new(target, read_file(run / "baseline", name))
        git(repository, "init", "--object-format=sha1", "--initial-branch=baseline", "--template=" + str(template))
        git(repository, "add", "--force", "--", *sorted(task["files"]))
        git(repository, "commit", "--no-verify", "-m", "Selected task baseline")
        commit = git(repository, "rev-parse", "HEAD").decode().strip()
        require(re.fullmatch(r"[0-9a-f]{40}", commit), "GIT_HEAD_FORMAT")
        branch = "outlands/task-" + run.name
        work = destination / "review"
        git(repository, "worktree", "add", "-b", branch, str(work), "baseline")
        patch_file = destination / "accepted.diff"
        write_new(patch_file, patch)
        git(work, "apply", "--check", "--whitespace=nowarn", str(patch_file))
        git(work, "apply", "--whitespace=nowarn", str(patch_file))
        verified = {**receipt, "status": "VERIFIED", "branch": branch,
                    "baseline_commit": commit, "path": str(work), "source_applied": False,
                    "patch_applied_to_workspace": True, "finished": int(time.time())}
        inspect(destination, task, result, verified)
        checks = checker(work, task, jdk_home)
        # Preserve failing evidence before refusing the operation.
        receipt.update(checks=checks)
        require(completed_checks(checks), "WORKSPACE_CHECKS_FAILED")
        for name, digest in task["files"].items():
            require(sha(read_file(source, name)) == digest, "ORIGINAL_SOURCE_CHANGED")
        current = sorted(run.glob("review-*.json"))[-1]
        current_review = parse(read_file(run, current.name, 262144))
        require(current_review["verdict"] == "accepted" and current_review["result_sha256"] == result_hash
                and current_review["patch_sha256"] == patch_hash, "REVIEW_CHANGED")
        inspect(destination, task, result, verified)
        verified["checks"] = checks
        atomic_json(receipt_path, verified)
        return verified
    except BaseException as error:
        receipt.update(status="FAILED", reason=str(error) if isinstance(error, Refused) else "WORKSPACE_EXECUTION_FAILED",
                       finished=int(time.time()), source_applied=False)
        atomic_json(receipt_path, receipt)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["run-dir", "destination", "source"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--result-sha256", required=True)
    parser.add_argument("--patch-sha256", required=True)
    parser.add_argument("--jdk-home", type=Path)
    args = parser.parse_args()
    require(all(p.is_absolute() and not p.is_symlink() for p in [args.run_dir, args.destination, args.source]), "WORKSPACE_PATH")
    source, destination = args.source.resolve(), args.destination.resolve()
    require(source != destination and source not in destination.parents and destination not in source.parents, "WORKSPACE_OUTSIDE_SOURCE")
    build(args.run_dir, args.destination, args.source, args.result_sha256, args.patch_sha256, args.jdk_home)


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit(1) from None
