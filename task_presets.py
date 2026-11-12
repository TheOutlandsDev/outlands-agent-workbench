"""Pure goal-only preset validation and approved-project profile bindings.

The controller owns authorization and guarded private storage. These helpers do
not open paths, inspect source bytes, execute checks/Git/providers, or read or
change runtime state. Profile hashes are unsigned structural bindings, not proof
of authenticity, source freshness, admission or permission to run a task.
"""

import copy
import re
import unicodedata
from pathlib import Path, PurePosixPath

from agent import Refused, canonical, sha, validate_task


FORMAT = "outlands-task-preset-v1"
MAX_RECORD = 32768
MAX_SAFE = 9007199254740991
ID = re.compile(r"[0-9a-f]{16}\Z")
ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = {"version", "format", "id", "project_id", "name", "name_key", "goal", "binding_sha256", "created"}
CODES = frozenset("TASK_PRESET_" + suffix for suffix in (
    "NAME_INVALID", "GOAL_INVALID", "PROFILE_INVALID", "OUTPUT_LIMIT"))


def _require(condition, suffix):
    if not condition:
        raise Refused("TASK_PRESET_" + suffix)


def _name(value):
    """Canonicalize a bounded display label and derive its duplicate key.

    Limits apply before and after NFC normalization. Surrounding whitespace is
    refused rather than silently removed. Casefolding is only a duplicate key;
    the displayed name retains its original case.
    """
    try:
        _require(type(value) is str and 1 <= len(value) <= 80, "NAME_INVALID")
        _require(len(value.encode("utf-8")) <= 240, "NAME_INVALID")
        name = unicodedata.normalize("NFC", value)
        _require(1 <= len(name) <= 80 and len(name.encode("utf-8")) <= 240
                 and name == name.strip(), "NAME_INVALID")
        _require(not any(unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                         for character in name), "NAME_INVALID")
        return name, unicodedata.normalize("NFC", name.casefold())
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise Refused("TASK_PRESET_NAME_INVALID") from None


def _goal(value):
    """Preserve exact prompt text; reject empty/blank, NUL and invalid Unicode."""
    try:
        _require(type(value) is str and 1 <= len(value) <= 2000 and bool(value.strip())
                 and "\x00" not in value, "GOAL_INVALID")
        _require(len(value.encode("utf-8")) <= 8000, "GOAL_INVALID")
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise Refused("TASK_PRESET_GOAL_INVALID") from None


def _profile(project, goal=None):
    """Build a private lexical binding without filesystem canonicalization."""
    try:
        _require(type(project) is dict and type(project["id"]) is str
                 and ALIAS.fullmatch(project["id"]) is not None, "PROFILE_INVALID")
        source = project["source"]
        _require(isinstance(source, (str, Path, PurePosixPath)), "PROFILE_INVALID")
        source = PurePosixPath(source)
        _require(source.is_absolute() and ".." not in source.parts
                 and "\x00" not in str(source), "PROFILE_INVALID")
        str(source).encode("utf-8")
        task = copy.deepcopy(project["definition"])
        _require(type(task) is dict and type(task.get("files")) is dict
                 and type(task.get("editable")) is list and type(task.get("checks")) is dict,
                 "PROFILE_INVALID")
        # Goal values are deliberately outside the profile. A supplied preset
        # goal still passes the existing task validator, including its bound.
        if goal is not None:
            task["goal"] = goal
        validate_task(task)
        binding = {"version": 1, "project_id": project["id"], "source": str(source),
                   "task_format": task["format"], "files": sorted(task["files"]),
                   "editable": sorted(task["editable"]), "checks": copy.deepcopy(task["checks"]),
                   "max_turns": task["max_turns"], "request_seconds": task["request_seconds"]}
        return project["id"], sha(canonical(binding))
    except (Refused, KeyError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
        raise Refused("TASK_PRESET_PROFILE_INVALID") from None


def profile(project):
    """Hash project identity, source identity and fixed scope/checks/budgets only."""
    return _profile(project)[1]


def prepare(project, name, goal):
    """Return only bounded private preset fields, without a path or model setting."""
    name, name_key = _name(name)
    goal = _goal(goal)
    project_id, binding = _profile(project, goal)
    result = {"project_id": project_id, "name": name, "name_key": name_key,
              "goal": goal, "binding_sha256": binding}
    _require(len(canonical(result)) <= MAX_RECORD, "OUTPUT_LIMIT")
    return result


def validate_record(value):
    """Recognize immutable finite records, including structurally valid stale ones."""
    try:
        if (type(value) is not dict or set(value) != FIELDS
                or type(value["version"]) is not int or value["version"] != 1
                or type(value["format"]) is not str or value["format"] != FORMAT
                or type(value["id"]) is not str or ID.fullmatch(value["id"]) is None
                or type(value["project_id"]) is not str or ALIAS.fullmatch(value["project_id"]) is None
                or type(value["created"]) is not int or not 0 <= value["created"] <= MAX_SAFE
                or type(value["binding_sha256"]) is not str or HASH.fullmatch(value["binding_sha256"]) is None):
            return False
        name, name_key = _name(value["name"])
        return (name == value["name"] and type(value["name_key"]) is str and value["name_key"] == name_key
                and _goal(value["goal"]) == value["goal"] and len(canonical(value)) <= MAX_RECORD)
    except (Refused, KeyError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
        return False


def matches(value, project):
    """Report compatibility only; this never loads a goal into an executing task."""
    if not validate_record(value):
        return False
    project_id, binding = _profile(project)
    return value["project_id"] == project_id and value["binding_sha256"] == binding
