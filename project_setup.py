"""Explicit file selection and hash-pinned task preparation; never scans a project."""

import re
from pathlib import Path

from agent import read_file, relative, require, sha, validate_task

FIELDS = {"id", "name", "source", "language", "files", "editable", "check", "goal"}
RESERVED = {".git", ".ssh", ".aws", ".codex", ".secrets", "secrets", "__pycache__"}


def prepare(request, jdk_available):
    require(isinstance(request, dict) and set(request) == FIELDS, "SETUP_FIELDS")
    require(isinstance(request["id"], str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", request["id"]), "PROJECT_ID")
    require(isinstance(request["name"], str) and 1 <= len(request["name"]) <= 80, "PROJECT_NAME")
    require(isinstance(request["source"], str), "PROJECT_PATH")
    source = Path(request["source"])
    require(source.is_absolute() and not source.is_symlink() and source.is_dir(), "PROJECT_PATH")
    source = source.resolve(strict=True)
    require(request["language"] in ["python", "java"], "PROJECT_LANGUAGE")
    names, editable = request["files"], request["editable"]
    require(isinstance(names, list) and 1 <= len(names) <= 32 and all(isinstance(n, str) for n in names), "FILES_LIMIT")
    require(len(set(names)) == len(names), "DUPLICATE_FILE")
    files, rows, total = {}, [], 0
    for name in names:
        relative(name)
        parts = name.split("/")
        require(not (set(p.lower() for p in parts) & RESERVED)
                and not any(p.lower().startswith(".env") for p in parts)
                and Path(name).suffix.lower() not in {".pem", ".key", ".db", ".sqlite", ".sqlite3", ".p12", ".pfx"}, "PRIVATE_FILE_REFUSED")
        raw = read_file(source, name)
        files[name] = sha(raw)
        total += len(raw)
        rows.append({"path": name, "bytes": len(raw), "sha256": files[name]})
    require(total <= 131072, "TOTAL_INPUT_LIMIT")
    require(isinstance(editable, list) and all(isinstance(n, str) for n in editable), "EDITABLE_SCOPE")
    if request["language"] == "python":
        spec = {"kind": "python-unittest", "pattern": request["check"]}
    else:
        require(jdk_available, "JDK_REQUIRED")
        spec = {"kind": "java-main", "sources": sorted(n for n in names if n.endswith(".java")), "main_class": request["check"]}
    task = validate_task({"format": "outlands-coding-agent-v2", "goal": request["goal"],
                          "files": files, "editable": editable, "checks": {"unit": spec},
                          "max_turns": 12, "request_seconds": 120})
    return source, task, [{**r, "editable": r["path"] in editable} for r in rows]
