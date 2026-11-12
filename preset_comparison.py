"""Pure bounded comparison of an unsaved draft and one private preset goal.

The highlighted span runs from the first through the last difference and can
include unchanged text between edits. It is not a minimal edit script. Exact
Unicode text and UTF-8 hashes are retained; this helper never loads or runs a
goal, inspects a project, opens paths, or invokes providers, Git or checks.
"""

from agent import Refused, canonical, sha


FORMAT = "outlands-task-preset-comparison-v1"
MAX_OUTPUT = 65536
CODES = frozenset({"TASK_PRESET_DRAFT_INVALID", "TASK_PRESET_GOAL_INVALID", "TASK_PRESET_OUTPUT_LIMIT"})


def _goal_bytes(value, *, draft):
    code = "TASK_PRESET_DRAFT_INVALID" if draft else "TASK_PRESET_GOAL_INVALID"
    try:
        if (type(value) is not str or not 0 <= len(value) <= 2000 or "\x00" in value
                or (not draft and not value.strip())):
            raise Refused(code)
        raw = value.encode("utf-8")
        if len(raw) > 8000:
            raise Refused(code)
        return raw
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise Refused(code) from None


def compare_goals(draft_goal, saved_goal):
    """Return exact text/hashes and nonoverlapping Unicode-codepoint bounds.

    A draft may be empty or whitespace-only. A saved goal follows the existing
    nonblank preset rules. Neither value is normalized or newline-folded. Equal
    goals use their complete length as prefix and zero suffix.
    """
    draft_raw = _goal_bytes(draft_goal, draft=True)
    saved_raw = _goal_bytes(saved_goal, draft=False)
    prefix = 0
    while prefix < min(len(draft_goal), len(saved_goal)) and draft_goal[prefix] == saved_goal[prefix]:
        prefix += 1
    suffix = 0
    remaining = min(len(draft_goal) - prefix, len(saved_goal) - prefix)
    while suffix < remaining and draft_goal[-suffix - 1] == saved_goal[-suffix - 1]:
        suffix += 1
    result = {"version": 1, "format": FORMAT, "draft_goal": draft_goal, "saved_goal": saved_goal,
              "draft_sha256": sha(draft_raw), "saved_sha256": sha(saved_raw),
              "identical": draft_goal == saved_goal, "prefix_chars": prefix, "suffix_chars": suffix}
    if len(canonical(result)) > MAX_OUTPUT:
        raise Refused("TASK_PRESET_OUTPUT_LIMIT")
    return result
