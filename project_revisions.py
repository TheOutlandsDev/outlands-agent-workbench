"""Prepare a task refresh from declared files without saving or executing it."""

from copy import deepcopy
from pathlib import Path

from agent import Refused, read_file, require, sha, validate_task


MAX_REFRESH_BYTES = 131_072


def refresh_task(source: Path, task: dict, goal: str) -> tuple[dict, list[dict]]:
    """Return an independent candidate and sorted review rows for existing scope.

    Only the goal and values of existing file hashes can change. Every declared
    file, including protected files, is read with the engine's guarded reader.
    The caller decides whether to save the returned candidate.
    """
    validate_task(task)
    candidate = deepcopy(task)
    candidate["goal"] = goal
    validate_task(candidate)
    rows, total = [], 0
    for path in sorted(task["files"]):
        try:
            raw = read_file(source, path)
        except UnicodeDecodeError:
            raise Refused("REFRESH_UTF8") from None
        total += len(raw)
        require(total <= MAX_REFRESH_BYTES, "REFRESH_SNAPSHOT_LIMIT")
        digest = sha(raw)
        old_digest = task["files"][path]
        candidate["files"][path] = digest
        rows.append({"path": path, "bytes": len(raw), "old_sha256": old_digest,
                     "sha256": digest, "editable": path in task["editable"],
                     "changed": old_digest != digest})
    require(candidate != task, "REFRESH_NO_CHANGES")
    return candidate, rows
