"""Local OUTLANDS Agent Workbench; configured projects, one task, reviewed exports."""

import argparse
import copy
import fcntl
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from java_check import validate_jdk
from project_setup import prepare
from git_workspace import inspect as inspect_workspace
from git_workspace import validate_files as validate_workspace_files

from agent import (
    Refused,
    canonical,
    parse,
    read_file,
    require,
    review_diff,
    sha,
    validate_task,
    write_new,
)

HERE = Path(__file__).resolve().parent
ID = re.compile(r"[0-9a-f]{16}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


def private_dir(path):
    require(path.is_absolute() and not path.is_symlink(), "PRIVATE_DIRECTORY_REQUIRED")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    require(
        info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
        "PRIVATE_DIRECTORY_REQUIRED",
    )


def json_file(path):
    return parse(read_file(path.parent, path.name, 262144))


def replace_json(path, value):
    temporary = path.with_name(path.name + ".next")
    write_new(temporary, canonical(value))
    os.replace(temporary, path)


def process_stamp(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return raw[raw.rfind(")") + 2 :].split()[19]
    except (OSError, IndexError):
        return None


def load_config(path):
    require(
        path.is_absolute() and HERE not in path.resolve().parents,
        "CONFIG_OUTSIDE_SOURCE",
    )
    value = json_file(path)
    require(
        isinstance(value, dict) and set(value) == {"format", "projects", "models"},
        "CONFIG_FIELDS",
    )
    require(value["format"] == "outlands-workbench-config-v1", "CONFIG_FORMAT")
    require(
        isinstance(value["projects"], list) and 1 <= len(value["projects"]) <= 16,
        "PROJECT_LIMIT",
    )
    projects = {}
    for row in value["projects"]:
        require(
            isinstance(row, dict) and set(row) == {"id", "name", "source", "task"},
            "PROJECT_FIELDS",
        )
        require(
            isinstance(row["id"], str)
            and ALIAS.fullmatch(row["id"])
            and row["id"] not in projects,
            "PROJECT_ID",
        )
        require(
            isinstance(row["name"], str) and 1 <= len(row["name"]) <= 80, "PROJECT_NAME"
        )
        require(
            isinstance(row["source"], str) and isinstance(row["task"], str),
            "PROJECT_PATH",
        )
        source, task = Path(row["source"]), Path(row["task"])
        require(
            source.is_absolute()
            and task.is_absolute()
            and not source.is_symlink()
            and not task.is_symlink(),
            "PROJECT_PATH",
        )
        require(source.is_dir(), "PROJECT_SOURCE")
        definition = validate_task(json_file(task))
        projects[row["id"]] = {
            **row,
            "source": source.resolve(),
            "task": task.resolve(),
            "definition": definition,
        }
    require(
        isinstance(value["models"], list) and len(value["models"]) <= 8, "MODEL_LIMIT"
    )
    models = []
    for model in value["models"]:
        require(
            isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", model),
            "MODEL_NAME",
        )
        require(model not in models, "MODEL_DUPLICATE")
        models.append(model)
    return projects, models


class Manager:
    def __init__(self, config, data, jdk_home=None):
        self.projects, self.models = load_config(config)
        self.config_path = config
        self.config_raw = read_file(config.parent, config.name, 262144)
        self.jdk_home = validate_jdk(jdk_home) if jdk_home is not None else None
        self.drafts = {}
        require(data.is_absolute() and not data.is_symlink(), "DATA_DIRECTORY")
        self.data = data.resolve()
        for source in [HERE] + [p["source"] for p in self.projects.values()]:
            require(
                self.data != source
                and source not in self.data.parents
                and self.data not in source.parents,
                "DATA_OUTSIDE_SOURCE",
            )
        private_dir(self.data)
        for name in ["jobs", "tasks", "runs", "state", "projects", "workspaces"]:
            private_dir(self.data / name)
        self.server_lock = os.open(
            self.data / "server.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        require(os.fstat(self.server_lock).st_nlink == 1, "SERVER_LOCK_TYPE")
        try:
            fcntl.flock(self.server_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.server_lock)
            raise Refused("SERVER_ALREADY_RUNNING") from None
        self.lock = threading.RLock()
        self.children = {}
        self.workspace_children = {}

    def workspace_receipt(self, run_id):
        path = self.run_path(run_id) / "git-workspace.json"
        entry = self.workspace_children.get(run_id)
        receipt = json_file(path) if path.exists() else None
        if entry is not None and entry[0].poll() is not None:
            child, log = self.workspace_children.pop(run_id)
            log.close()
            if receipt is not None and receipt["status"] == "PREPARING":
                receipt.update(status="FAILED", reason="WORKSPACE_INTERRUPTED", finished=int(time.time()))
                replace_json(path, receipt)
        return receipt

    def create_workspace(self, request):
        with self.lock:
            require(isinstance(request, dict) and set(request) == {"id", "result_sha256", "patch_sha256"}, "WORKSPACE_FIELDS")
            run_id = request["id"]
            self.export(run_id)
            self.verified_artifact(run_id, request["result_sha256"], request["patch_sha256"])
            run = self.run_path(run_id)
            task = json_file(self.data / "tasks" / (run_id + ".json"))
            validate_workspace_files(task)
            existing = self.workspace_receipt(run_id)
            destination = self.data / "workspaces" / run_id
            if existing is not None:
                require(existing["result_sha256"] == request["result_sha256"] and existing["patch_sha256"] == request["patch_sha256"], "WORKSPACE_ARTIFACT_CHANGED")
                require(existing["status"] in ["PREPARING", "VERIFIED"], "WORKSPACE_NEEDS_INSPECTION")
                if existing["status"] == "VERIFIED":
                    inspect_workspace(destination, task, self.result(run_id), existing)
                return existing
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            receipt = {"status": "PREPARING", "created": int(time.time()), "source_applied": False,
                       "result_sha256": request["result_sha256"], "patch_sha256": request["patch_sha256"]}
            write_new(run / "git-workspace.json", canonical(receipt))
            meta = self.metadata(run_id)
            command = [sys.executable, "-B", str(HERE / "git_workspace.py"), "--run-dir", str(run),
                       "--source", meta["source"], "--destination", str(destination),
                       "--result-sha256", request["result_sha256"], "--patch-sha256", request["patch_sha256"]]
            if self.jdk_home is not None:
                command += ["--jdk-home", str(self.jdk_home)]
            fd = os.open(run / "workspace-worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            log = os.fdopen(fd, "wb")
            try:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"})
            except OSError:
                log.close()
                receipt.update(status="FAILED", reason="WORKSPACE_START_FAILED")
                replace_json(run / "git-workspace.json", receipt)
                raise Refused("WORKSPACE_START_FAILED") from None
            self.workspace_children[run_id] = (child, log)
            return receipt

    def stop_workspace(self, run_id):
        with self.lock:
            self.meta_path(run_id)
            entry = self.workspace_children.get(run_id)
            require(entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_WORKSPACE")
            child = entry[0]
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            self.workspace_receipt(run_id)
            return {"status": "STOP_REQUESTED"}

    def project_preview(self, request):
        with self.lock:
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            source, task, rows = prepare(request, self.jdk_home is not None)
            require(request["id"] not in self.projects and len(self.projects) < 16, "PROJECT_EXISTS_OR_LIMIT")
            for root in [HERE, self.data]:
                require(source != root and source not in root.parents and root not in source.parents, "PROJECT_OVERLAP")
            self.drafts = {key: value for key, value in self.drafts.items() if value["expires"] > time.monotonic()}
            require(len(self.drafts) < 16, "DRAFT_LIMIT")
            draft_id = secrets.token_hex(8)
            self.drafts[draft_id] = {"request": copy.deepcopy(request), "task": task,
                                     "source": source, "expires": time.monotonic() + 300}
            return {"draft": draft_id, "name": request["name"], "files": rows,
                    "checks": task["checks"], "max_turns": task["max_turns"], "total_bytes": sum(r["bytes"] for r in rows)}

    def project_save(self, request):
        with self.lock:
            require(isinstance(request, dict) and set(request) == {"draft"}
                    and isinstance(request["draft"], str), "DRAFT_REQUIRED")
            draft = self.drafts.get(request["draft"])
            require(draft is not None and draft["expires"] > time.monotonic(), "DRAFT_EXPIRED")
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            source, task, _ = prepare(draft["request"], self.jdk_home is not None)
            require(source == draft["source"] and task == draft["task"], "SETUP_SOURCE_CHANGED")
            require(read_file(self.config_path.parent, self.config_path.name, 262144) == self.config_raw, "CONFIG_CHANGED")
            name = draft["request"]["id"]
            require(name not in self.projects and len(self.projects) < 16, "PROJECT_EXISTS_OR_LIMIT")
            task_path = self.data / "projects" / (name + ".json")
            row = {"id": name, "name": draft["request"]["name"], "source": str(source), "task": str(task_path)}
            config = parse(self.config_raw)
            config["projects"].append(row)
            write_new(task_path, canonical(task))
            replace_json(self.config_path, config)
            self.config_raw = canonical(config)
            self.projects[name] = {**row, "source": source, "task": task_path, "definition": task}
            del self.drafts[request["draft"]]
            return {"id": name, "name": row["name"]}

    def meta_path(self, run_id):
        require(isinstance(run_id, str) and ID.fullmatch(run_id), "RUN_ID")
        return self.data / "jobs" / (run_id + ".json")

    def metadata(self, run_id):
        return json_file(self.meta_path(run_id))

    def run_path(self, run_id):
        self.meta_path(run_id)
        return self.data / "runs" / run_id

    def result(self, run_id):
        path = self.run_path(run_id) / "result.json"
        if not path.exists():
            return None
        try:
            return json_file(path)
        except (Refused, OSError, ValueError):
            return None

    def refresh(self, meta):
        run_id = meta["id"]
        entry = self.children.get(run_id)
        if entry is not None:
            child, log = entry
            code = child.poll()
            if code is None:
                return meta
            log.close()
            del self.children[run_id]
            meta["exit_code"] = code
        elif meta["state"] in ["RUNNING", "STOP_REQUESTED"]:
            stamp = process_stamp(meta.get("pid", -1))
            if stamp is not None and stamp == meta.get("process_stamp"):
                return {**meta, "state": "RECOVERY_REQUIRED"}
        else:
            return meta
        result = self.result(run_id)
        meta["state"] = (
            result.get("status", "FAILED")
            if isinstance(result, dict)
            else "FAILED"
            if "exit_code" in meta
            else "RECOVERY_REQUIRED"
        )
        meta["finished"] = int(time.time())
        replace_json(self.meta_path(run_id), meta)
        return meta

    def history(self, limit=100):
        with self.lock:
            rows = []
            for path in sorted((self.data / "jobs").glob("*.json")):
                require(ID.fullmatch(path.stem), "HISTORY_ID")
                meta = self.refresh(json_file(path))
                rows.append(
                    {
                        k: meta.get(k)
                        for k in [
                            "id",
                            "project_name",
                            "backend",
                            "model",
                            "goal",
                            "created",
                            "finished",
                            "state",
                        ]
                    }
                )
            rows = sorted(rows, key=lambda x: (x["created"], x["id"]), reverse=True)
            return rows if limit is None else rows[:limit]

    def admission(self):
        rows = self.history(limit=None)
        hold = self.data / "state/hold.json"
        if hold.exists() or hold.is_symlink():
            return "UNCERTAIN_REQUEST_HELD"
        for row in rows:
            receipt = self.workspace_receipt(row["id"])
            if receipt is not None and receipt["status"] in ["PREPARING", "FAILED"]:
                return "WORKSPACE_ACTIVE_OR_UNRESOLVED"
        if any(
            r["state"] in ["RUNNING", "STOP_REQUESTED", "RECOVERY_REQUIRED"]
            for r in rows
        ):
            return "TASK_ACTIVE_OR_UNRESOLVED"
        return None

    def start(self, request):
        with self.lock:
            require(
                isinstance(request, dict)
                and set(request) == {"project", "model", "goal"},
                "START_FIELDS",
            )
            require(
                isinstance(request["project"], str)
                and request["project"] in self.projects,
                "PROJECT_UNKNOWN",
            )
            require(
                isinstance(request["model"], str)
                and request["model"] in ["scripted-demo"] + self.models,
                "MODEL_NOT_CONFIGURED",
            )
            blocked = self.admission()
            require(blocked is None, blocked or "ADMISSION")
            project = self.projects[request["project"]]
            task = copy.deepcopy(project["definition"])
            require(self.jdk_home is not None or not any(
                isinstance(spec, dict) and spec.get("kind") == "java-main"
                for spec in task["checks"].values()), "JDK_REQUIRED")
            require(
                isinstance(request["goal"], str) and 1 <= len(request["goal"]) <= 2000,
                "GOAL_LIMIT",
            )
            if request["model"] == "scripted-demo":
                require(
                    task == json_file(HERE / "task.example.json")
                    and request["goal"] == task["goal"],
                    "SCRIPTED_DEMO_ONLY",
                )
            task["goal"] = request["goal"]
            validate_task(task)
            for name, digest in task["files"].items():
                require(
                    sha(read_file(project["source"], name)) == digest,
                    "SOURCE_HASH_CHANGED",
                )
            run_id = secrets.token_hex(8)
            task_path = self.data / "tasks" / (run_id + ".json")
            write_new(task_path, canonical(task))
            backend = (
                "scripted-demo" if request["model"] == "scripted-demo" else "ollama"
            )
            meta = {
                "id": run_id,
                "project": project["id"],
                "project_name": project["name"],
                "source": str(project["source"]),
                "goal": task["goal"],
                "model": request["model"],
                "backend": backend,
                "created": int(time.time()),
                "state": "RECOVERY_REQUIRED",
            }
            write_new(self.meta_path(run_id), canonical(meta))
            command = [
                sys.executable,
                "-B",
                str(HERE / "agent.py"),
                "--task",
                str(task_path),
                "--source",
                str(project["source"]),
                "--run-dir",
                str(self.run_path(run_id)),
                "--state-dir",
                str(self.data / "state"),
                "--backend",
                backend,
            ]
            if backend == "ollama":
                command += ["--model", request["model"], "--allow-local-inference"]
            if self.jdk_home is not None:
                command += ["--jdk-home", str(self.jdk_home)]
            log_path = self.data / "jobs" / (run_id + ".log")
            fd = os.open(
                log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            log = os.fdopen(fd, "wb")
            try:
                child = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C.UTF-8",
                        "PYTHONNOUSERSITE": "1",
                    },
                )
            except OSError:
                log.close()
                meta.update(state="FAILED", finished=int(time.time()))
                replace_json(self.meta_path(run_id), meta)
                raise Refused("ENGINE_START_FAILED") from None
            self.children[run_id] = (child, log)
            meta.update(
                state="RUNNING", pid=child.pid, process_stamp=process_stamp(child.pid)
            )
            replace_json(self.meta_path(run_id), meta)
            return {"id": run_id}

    def view(self, run_id):
        with self.lock:
            meta = self.refresh(self.metadata(run_id))
            run = self.run_path(run_id)
            events, plans, checks = [], [], []
            turns, pending = 0, 0
            for path in sorted(run.glob("event-*.json")):
                try:
                    event = json_file(path)
                except (Refused, OSError, ValueError):
                    pending += 1
                    continue
                kind, value = event["kind"], event["value"]
                if kind == "request_started":
                    turns = max(turns, value["turn"])
                    text = "Model turn " + str(value["turn"])
                elif kind == "tool_result":
                    text = value["name"].replace("_", " ")
                    if value["name"] == "set_plan":
                        plans = value["result"]["steps"]
                    if value["name"] == "run_check":
                        checks.append({"label": "Agent check", **value["result"]})
                elif kind in ["baseline_checks", "independent_final_checks"]:
                    text = (
                        "Baseline checks"
                        if kind == "baseline_checks"
                        else "Independent final checks"
                    )
                    checks.extend(
                        {"label": text + " · " + name, **result}
                        for name, result in value.items()
                    )
                elif kind == "completion":
                    text = value["summary"][:2000]
                else:
                    continue
                events.append({"kind": kind, "text": text, "index": event["index"]})
            task = json_file(self.data / "tasks" / (run_id + ".json"))
            result = self.result(run_id)
            patch_path = run / "changes.diff"
            patch_text = (
                read_file(run, "changes.diff", 1048576).decode()
                if patch_path.is_file()
                else ""
            )
            result_hash = sha(canonical(result)) if result else None
            reviews = sorted(run.glob("review-*.json"))
            last_review = json_file(reviews[-1]) if reviews else None
            for entry in checks:
                entry["output"] = entry.get("output", "")[:8192]
            workspace = self.workspace_receipt(run_id)
            return {
                "id": run_id,
                "project_name": meta["project_name"],
                "goal": meta["goal"],
                "model": meta["model"],
                "backend": meta["backend"],
                "state": meta["state"],
                "turns": turns,
                "max_turns": task["max_turns"],
                "plan": plans,
                "events": events[-100:],
                "checks": checks,
                "result": result,
                "result_sha256": result_hash,
                "patch_sha256": sha(patch_text.encode())
                if patch_path.is_file()
                else None,
                "patch": patch_text,
                "review": last_review,
                "pending_events": pending,
                "workspace": {**workspace, "owned_active": run_id in self.workspace_children}
                if workspace is not None else None,
                "admission_block": self.admission(),
            }

    def verified_artifact(self, run_id, result_hash, patch_hash):
        meta = self.refresh(self.metadata(run_id))
        require(meta["state"] == "REVIEW_READY", "TASK_NOT_REVIEW_READY")
        run = self.run_path(run_id)
        result = self.result(run_id)
        require(
            isinstance(result, dict)
            and result["status"] == "REVIEW_READY"
            and sha(canonical(result)) == result_hash,
            "RESULT_CHANGED",
        )
        evidence = [json_file(path) for path in sorted(run.glob("event-*.json"))]
        final = [
            e["value"] for e in evidence if e["kind"] == "independent_final_checks"
        ]
        require(
            len(final) == 1
            and final[0]
            and all(
                r["exit_code"] == 0
                and r["tests_ran"] > 0
                and not any(
                    r[key]
                    for key in ["timed_out", "output_limited", "infrastructure_error"]
                )
                for r in final[0].values()
            ),
            "FINAL_EVIDENCE_REQUIRED",
        )
        task = json_file(self.data / "tasks" / (run_id + ".json"))
        project = self.projects.get(meta["project"])
        require(
            project is not None and str(project["source"]) == meta["source"],
            "PROJECT_SCOPE_CHANGED",
        )
        require(set(result["files"]) == set(task["files"]), "RESULT_SCOPE_CHANGED")
        patch_text = ""
        for name, digest in sorted(task["files"].items()):
            before = read_file(run / "baseline", name)
            after = read_file(run / "work", name)
            require(
                sha(before) == digest == result["files"][name]["before"],
                "BASELINE_CHANGED",
            )
            require(sha(after) == result["files"][name]["after"], "CANDIDATE_CHANGED")
            require(
                sha(read_file(project["source"], name)) == digest,
                "ORIGINAL_SOURCE_CHANGED",
            )
            if name not in task["editable"]:
                require(sha(after) == digest, "PROTECTED_FILE_CHANGED")
            patch_text += review_diff(name, before, after)
        raw = patch_text.encode()
        require(sha(raw) == patch_hash == result["patch_sha256"], "PATCH_CHANGED")
        require(read_file(run, "changes.diff", 1048576) == raw, "PATCH_CHANGED")
        return raw

    def review(self, request):
        with self.lock:
            require(
                isinstance(request, dict)
                and set(request)
                == {"id", "result_sha256", "patch_sha256", "verdict", "note"},
                "REVIEW_FIELDS",
            )
            require(request["verdict"] in ["accepted", "rejected"], "REVIEW_VERDICT")
            workspace = self.workspace_receipt(request["id"])
            require(workspace is None or workspace["status"] != "PREPARING", "WORKSPACE_ACTIVE_OR_UNRESOLVED")
            require(
                isinstance(request["note"], str) and len(request["note"]) <= 2000,
                "REVIEW_NOTE",
            )
            self.verified_artifact(
                request["id"], request["result_sha256"], request["patch_sha256"]
            )
            run = self.run_path(request["id"])
            reviews = list(run.glob("review-*.json"))
            require(len(reviews) < 100, "REVIEW_LIMIT")
            record = {**request, "recorded": int(time.time()), "source_applied": False}
            write_new(run / f"review-{len(reviews):03d}.json", canonical(record))
            return record

    def export(self, run_id):
        with self.lock:
            view = self.view(run_id)
            review = view["review"]
            require(
                review is not None and review["verdict"] == "accepted",
                "REVIEW_REQUIRED",
            )
            return self.verified_artifact(
                run_id, review["result_sha256"], review["patch_sha256"]
            )

    def stop(self, run_id):
        with self.lock:
            self.meta_path(run_id)
            entry = self.children.get(run_id)
            require(
                entry is not None and entry[0].poll() is None, "NO_OWNED_ACTIVE_TASK"
            )
            child = entry[0]
            meta = self.metadata(run_id)
            meta["state"] = "STOP_REQUESTED"
            replace_json(self.meta_path(run_id), meta)
            child.terminate()

            def finish_stop():
                try:
                    child.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                with self.lock:
                    self.refresh(self.metadata(run_id))

            threading.Thread(target=finish_stop, daemon=True).start()
            return {"state": "STOP_REQUESTED"}

    def config_view(self):
        return {
            "projects": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "goal": p["definition"]["goal"],
                    "files": sorted(p["definition"]["files"]),
                    "editable": p["definition"]["editable"],
                    "checks": sorted(p["definition"]["checks"]),
                    "scripted_available": p["definition"] == json_file(HERE / "task.example.json"),
                }
                for p in self.projects.values()
            ],
            "models": self.models,
            "java_available": self.jdk_home is not None,
            "admission_block": self.admission(),
        }

    def close(self):
        for run_id in list(self.workspace_children):
            try:
                self.stop_workspace(run_id)
            except Refused:
                pass
        for run_id in list(self.workspace_children):
            self.workspace_receipt(run_id)
        for run_id in list(self.children):
            try:
                self.stop(run_id)
            except Refused:
                pass
        for child, log in list(self.children.values()):
            try:
                child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            log.close()
        os.close(self.server_lock)


def make_handler(manager, token, origin):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

        def send(
            self, code, raw, kind="application/json; charset=utf-8", attachment=None
        ):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'",
            )
            if attachment:
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{attachment}"'
                )
            self.end_headers()
            self.wfile.write(raw)

        def guard(self, api=False):
            require(
                self.headers.get("Host") == origin.split("://", 1)[1], "HOST_REFUSED"
            )
            require(
                self.headers.get("Sec-Fetch-Site", "none") in ["none", "same-origin"],
                "CROSS_SITE_REFUSED",
            )
            if api:
                supplied = self.headers.get("X-Workbench-Token", "")
                require(hmac.compare_digest(supplied, token), "SESSION_REQUIRED")

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                self.guard(path.startswith("/api/"))
                if path == "/":
                    raw = (
                        (HERE / "static/index.html")
                        .read_bytes()
                        .replace(b"__SESSION_TOKEN__", token.encode())
                    )
                    self.send(200, raw, "text/html; charset=utf-8")
                elif path in ["/app.js", "/style.css"]:
                    self.send(
                        200,
                        (HERE / "static" / path[1:]).read_bytes(),
                        "text/javascript; charset=utf-8"
                        if path.endswith(".js")
                        else "text/css; charset=utf-8",
                    )
                elif path == "/api/config":
                    self.send(200, canonical(manager.config_view()))
                elif path == "/api/history":
                    self.send(200, canonical(manager.history()))
                elif path.startswith("/api/run/"):
                    self.send(
                        200, canonical(manager.view(path.removeprefix("/api/run/")))
                    )
                elif path.startswith("/api/export/"):
                    run_id = path.removeprefix("/api/export/")
                    raw = manager.export(run_id)
                    self.send(
                        200,
                        raw,
                        "text/plain; charset=utf-8",
                        f"outlands-patch-{run_id}.diff",
                    )
                else:
                    self.send(404, canonical({"error": "NOT_FOUND"}))
            except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
                self.send(
                    403
                    if isinstance(exc, Refused)
                    and str(exc)
                    in ["HOST_REFUSED", "CROSS_SITE_REFUSED", "SESSION_REQUIRED"]
                    else 409,
                    canonical(
                        {
                            "error": str(exc)
                            if isinstance(exc, Refused)
                            else "REQUEST_REFUSED"
                        }
                    ),
                )

        def do_POST(self):
            try:
                self.guard(True)
                require(self.headers.get("Origin") == origin, "ORIGIN_REFUSED")
                require(
                    self.headers.get("Content-Type", "").split(";", 1)[0]
                    == "application/json",
                    "JSON_REQUIRED",
                )
                length = int(self.headers.get("Content-Length", "0"))
                require(0 < length <= 32768, "REQUEST_LIMIT")
                request = parse(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == "/api/start":
                    result = manager.start(request)
                elif path == "/api/project-preview":
                    result = manager.project_preview(request)
                elif path == "/api/project-save":
                    result = manager.project_save(request)
                elif path == "/api/workspace":
                    result = manager.create_workspace(request)
                elif path == "/api/workspace-stop":
                    require(isinstance(request, dict) and set(request) == {"id"}, "STOP_FIELDS")
                    result = manager.stop_workspace(request["id"])
                elif path == "/api/stop":
                    require(
                        isinstance(request, dict) and set(request) == {"id"},
                        "STOP_FIELDS",
                    )
                    result = manager.stop(request["id"])
                elif path == "/api/review":
                    result = manager.review(request)
                else:
                    raise Refused("NOT_FOUND")
                self.send(200, canonical(result))
            except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
                self.send(
                    409,
                    canonical(
                        {
                            "error": str(exc)
                            if isinstance(exc, Refused)
                            else "REQUEST_REFUSED"
                        }
                    ),
                )

    return Handler


def init_demo(workspace, model):
    require(
        workspace.is_absolute() and not workspace.is_symlink(),
        "ABSOLUTE_WORKSPACE_REQUIRED",
    )
    workspace = workspace.resolve()
    require(workspace != HERE and HERE not in workspace.parents, "DEMO_OUTSIDE_SOURCE")
    workspace.mkdir(mode=0o700, exist_ok=False)
    project = workspace / "project"
    project.mkdir(mode=0o700)
    for name in ["calculator.py", "test_calculator.py"]:
        write_new(project / name, (HERE / name).read_bytes())
    write_new(workspace / "task.json", (HERE / "task.example.json").read_bytes())
    config = {
        "format": "outlands-workbench-config-v1",
        "projects": [
            {
                "id": "arithmetic",
                "name": "Arithmetic demo",
                "source": str(project),
                "task": str(workspace / "task.json"),
            }
        ],
        "models": [model] if model else [],
    }
    write_new(workspace / "config.json", canonical(config))
    return {
        "config": str(workspace / "config.json"),
        "data_dir": str(workspace / "data"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("init-demo")
    demo.add_argument("--workspace", type=Path, required=True)
    demo.add_argument("--model")
    serve = sub.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--data-dir", type=Path, required=True)
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--jdk-home", type=Path)
    args = parser.parse_args()
    if args.command == "init-demo":
        print(json.dumps(init_demo(args.workspace, args.model)))
        return
    require(0 <= args.port <= 65535, "PORT_RANGE")
    manager = Manager(args.config, args.data_dir, args.jdk_home)
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler)
    server.daemon_threads = True
    origin = "http://127.0.0.1:" + str(server.server_address[1])
    server.RequestHandlerClass = make_handler(manager, token, origin)
    replace_json(manager.data / "server-info.json", {"url": origin, "pid": os.getpid()})
    print("OUTLANDS Agent Workbench: " + origin, flush=True)

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "REFUSED",
                    "reason": str(error)
                    if isinstance(error, Refused)
                    else "STARTUP_FAILED",
                }
            )
        )
        raise SystemExit(2) from None
