"""Deterministic private patch bundles and a read-only, non-extracting verifier."""

import hashlib
import io
import os
import re
import stat
import struct
import sys
import zipfile
import zlib

from agent import Refused, canonical, parse, validate_task


MAX_ARCHIVE = 2_097_152
MAX_PATCH = 1_048_576
MAX_JSON = 262_144
MAX_SAFE = 9_007_199_254_740_991
MEMBERS = ("manifest.json", "changes.diff", "review.json", "checks.json", "README.txt", "SHA256SUMS")
HASH_KEYS = {"task_sha256", "result_sha256", "review_record_sha256", "final_event_sha256", "patch_sha256"}
NOT_CHECKED = ["CHECK_RERUN", "PROVIDER_COMPLETION", "SOURCE_CORRECTNESS", "GIT_ADOPTION"]
NOTES = ["PRIVATE_SOURCE_CONTENT", "RECORDED_CHECKS_ONLY", "UNSIGNED_BUNDLE"]
HASH = re.compile(r"[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"[0-9a-f]{16}\Z")
CODE_SET = frozenset({"BUNDLE_RECORD_INVALID", "BUNDLE_LIMIT", "BUNDLE_FINAL_REQUIRED", "BUNDLE_REVIEW_REQUIRED",
    "BUNDLE_NOT_REVIEW_READY", "BUNDLE_PIN_REQUIRED", "BUNDLE_ARTIFACT_CHANGED", "BUNDLE_INVALID",
    "BUNDLE_CHANGED", "BUNDLE_HASH_REQUIRED"})
README = (
    "OUTLANDS reviewed patch bundle\n"
    "\n"
    "PRIVATE SOURCE CONTENT: the patch, relative file names and check specifications\n"
    "can contain private project information. Keep this bundle private.\n"
    "\n"
    "This bundle records an accepted review and passing independent final checks.\n"
    "Verification checks stored bytes and consistency; it does not rerun checks,\n"
    "establish provider completion or source correctness, or adopt changes in Git.\n"
    "The original task/result/review/event records are represented by hashes only.\n"
    "Those records are absent and cannot be reconstructed or authenticated here.\n"
    "Embedded checksums are unsigned integrity evidence, not authenticity. Verify\n"
    "an independently trusted whole-archive SHA256 pin when one is available.\n"
    "\n"
    "Manual adoption: inspect the patch and scope, compare the intended project's\n"
    "baseline hashes, apply changes manually in your chosen review workspace, and\n"
    "run the fixed checks there before deciding to adopt them. This verifier never\n"
    "extracts files, applies a patch, executes checks, or changes source or holds.\n"
).encode("ascii")
PERMISSIONS = (stat.S_IFREG | 0o600) << 16


def _require(condition, code="BUNDLE_INVALID"):
    if not condition:
        raise Refused(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return type(value) is str and len(value) == 64 and HASH.fullmatch(value) is not None


def _integer(value, low=0, high=MAX_SAFE):
    return type(value) is int and low <= value <= high


def _record(raw):
    _require(type(raw) is bytes, "BUNDLE_RECORD_INVALID")
    _require(len(raw) <= MAX_JSON, "BUNDLE_LIMIT")
    value = parse(raw)
    _require(type(value) is dict, "BUNDLE_RECORD_INVALID")
    return value


def _task(value):
    # Shared validation remains authoritative; these checks bound its structural work.
    _require(type(value) is dict and len(value) == 7, "BUNDLE_RECORD_INVALID")
    _require(type(value.get("files")) is dict and 1 <= len(value["files"]) <= 32,
             "BUNDLE_RECORD_INVALID")
    _require(all(type(path) is str and len(path) <= 128 and _hash(digest)
                 for path, digest in value["files"].items()), "BUNDLE_RECORD_INVALID")
    _require(type(value.get("editable")) is list and len(value["editable"]) <= 32
             and all(type(path) is str and len(path) <= 128 for path in value["editable"]), "BUNDLE_RECORD_INVALID")
    _require(type(value.get("checks")) is dict and len(value["checks"]) <= 4, "BUNDLE_RECORD_INVALID")
    validate_task(value)
    value["goal"].encode("utf-8")
    return value


def _spec(value):
    if isinstance(value, str):
        return value
    if value["kind"] == "python-unittest":
        return {"kind": value["kind"], "pattern": value["pattern"]}
    return {"kind": value["kind"], "sources": list(value["sources"]), "main_class": value["main_class"]}


def _passing(raw, code="BUNDLE_FINAL_REQUIRED"):
    _require(type(raw) is dict and type(raw.get("exit_code")) is int and raw["exit_code"] == 0
             and _integer(raw.get("tests_ran"), 1)
             and all(raw.get(key) is False for key in ("timed_out", "output_limited", "infrastructure_error")), code)
    return {"exit_code": 0, "tests_ran": raw["tests_ran"], "timed_out": False,
            "output_limited": False, "infrastructure_error": False}


def _patch(raw):
    _require(type(raw) is bytes and bool(raw), "BUNDLE_INVALID")
    _require(len(raw) <= MAX_PATCH, "BUNDLE_LIMIT")
    _require(b"\x00" not in raw, "BUNDLE_INVALID")
    raw.decode("utf-8")


def _checksums(payloads):
    return "".join(_sha(payloads[name]) + "  " + name + "\n"
                   for name in sorted(name for name in MEMBERS if name != "SHA256SUMS")).encode("ascii")


def _archive(payloads):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.create_version = info.extract_version = 20
            info.external_attr = PERMISSIONS
            info.internal_attr = 0
            info.compress_type = zipfile.ZIP_STORED
            info.extra = info.comment = b""
            archive.writestr(info, payloads[name])
    raw = stream.getvalue()
    _require(len(raw) <= MAX_ARCHIVE, "BUNDLE_LIMIT")
    return raw


def _build(task_raw, result_raw, review_raw, final_event_raw, patch):
    task = _task(_record(task_raw))
    result, review, final = _record(result_raw), _record(review_raw), _record(final_event_raw)
    _patch(patch)
    _require(result_raw == canonical(result), "BUNDLE_RECORD_INVALID")
    _require(result.get("status") == "REVIEW_READY", "BUNDLE_NOT_REVIEW_READY")
    _require(result.get("format") == task["format"] and result.get("source_adopted") is False,
             "BUNDLE_RECORD_INVALID")
    _require(type(result.get("files")) is dict and set(result["files"]) == set(task["files"]), "BUNDLE_RECORD_INVALID")
    files = []
    for path in sorted(task["files"]):
        row = result["files"][path]
        _require(type(row) is dict and _hash(row.get("before")) and _hash(row.get("after")), "BUNDLE_RECORD_INVALID")
        _require(row["before"] == task["files"][path], "BUNDLE_ARTIFACT_CHANGED")
        editable = path in task["editable"]
        _require(editable or row["before"] == row["after"], "BUNDLE_ARTIFACT_CHANGED")
        files.append({"path": path, "editable": editable, "before_sha256": row["before"], "after_sha256": row["after"]})
    _require(any(row["before_sha256"] != row["after_sha256"] for row in files), "BUNDLE_ARTIFACT_CHANGED")
    _require(review.get("verdict") == "accepted", "BUNDLE_REVIEW_REQUIRED")
    _require(review.get("source_applied") is False and _integer(review.get("recorded"))
             and type(review.get("id")) is str and len(review["id"]) == 16 and RUN_ID.fullmatch(review["id"]),
             "BUNDLE_RECORD_INVALID")
    _require(_hash(review.get("result_sha256")) and _hash(review.get("patch_sha256")), "BUNDLE_PIN_REQUIRED")
    _require(review["result_sha256"] == _sha(result_raw) and review["patch_sha256"] == _sha(patch)
             and result.get("patch_sha256") == _sha(patch), "BUNDLE_ARTIFACT_CHANGED")
    _require(final.get("kind") == "independent_final_checks" and _integer(final.get("index"), 0, 255)
             and type(final.get("value")) is dict and set(final["value"]) == set(task["checks"]), "BUNDLE_FINAL_REQUIRED")
    checks = [{"name": name, "spec": _spec(task["checks"][name]), **_passing(final["value"][name])}
              for name in sorted(task["checks"])]
    hashes = {"task_sha256": _sha(task_raw), "result_sha256": _sha(result_raw),
              "review_record_sha256": _sha(review_raw), "final_event_sha256": _sha(final_event_raw), "patch_sha256": _sha(patch)}
    manifest = {"format": "outlands-reviewed-patch-bundle-v1", "hashes": hashes,
                "task_profile": {"format": task["format"], "max_turns": task["max_turns"],
                    "request_seconds": task["request_seconds"], "checks": {name: _spec(spec) for name, spec in task["checks"].items()}},
                "files": files}
    review_summary = {"format": "outlands-reviewed-patch-review-v1", "verdict": "accepted", "source_applied": False, "hashes": hashes}
    check_summary = {"format": "outlands-reviewed-patch-checks-v1", "evidence": "RECORDED_INDEPENDENT_FINAL_CHECKS",
                     "hashes": hashes, "checks": checks, "not_checked": list(NOT_CHECKED)}
    payloads = {"manifest.json": canonical(manifest), "changes.diff": patch,
                "review.json": canonical(review_summary), "checks.json": canonical(check_summary), "README.txt": README}
    _require(all(len(payloads[name]) <= MAX_JSON for name in ("manifest.json", "review.json", "checks.json")), "BUNDLE_LIMIT")
    payloads["SHA256SUMS"] = _checksums(payloads)
    return _archive(payloads)


def _safe_error(exc, default):
    code = str(exc) if isinstance(exc, Refused) else None
    return code if code in CODE_SET else default


def build_bundle(task_raw: bytes, result_raw: bytes, review_raw: bytes, final_event_raw: bytes, patch: bytes) -> bytes:
    """Build a private, deterministic archive from accepted saved record bytes."""
    try:
        return _build(task_raw, result_raw, review_raw, final_event_raw, patch)
    except (Refused, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise Refused(_safe_error(exc, "BUNDLE_RECORD_INVALID")) from None


def _members(raw):
    """Parse prebounded stored ZIP records directly; never allocate ZIP metadata lists."""
    _require(type(raw) is bytes)
    _require(len(raw) <= MAX_ARCHIVE, "BUNDLE_LIMIT")
    _require(len(raw) >= 22)
    end = struct.unpack_from("<4s4H2IH", raw, len(raw) - 22)
    _require(end[0] == b"PK\x05\x06" and end[1:5] == (0, 0, 6, 6) and end[7] == 0)
    directory_size, directory_start = end[5], end[6]
    _require(directory_size == sum(46 + len(name) for name in MEMBERS)
             and directory_start + directory_size == len(raw) - 22)
    cursor, next_local, payloads = directory_start, 0, {}
    for name in MEMBERS:
        _require(cursor + 46 <= len(raw) - 22)
        central = struct.unpack_from("<4s6H3I5H2I", raw, cursor)
        encoded_name = name.encode("ascii")
        _require(central[0] == b"PK\x01\x02" and central[1:7] == (788, 20, 0, 0, 0, 33)
                 and central[8] == central[9] and central[10:15] == (len(encoded_name), 0, 0, 0, 0)
                 and central[15] == PERMISSIONS and central[16] == next_local)
        size, checksum = central[9], central[7]
        ceiling = MAX_PATCH if name == "changes.diff" else MAX_JSON if name.endswith(".json") else len(README) if name == "README.txt" else 1024
        _require(size <= ceiling, "BUNDLE_LIMIT")
        _require(raw[cursor + 46:cursor + 46 + len(encoded_name)] == encoded_name)
        _require(next_local + 30 + len(encoded_name) + size <= directory_start)
        local = struct.unpack_from("<4s5H3I2H", raw, next_local)
        _require(local == (b"PK\x03\x04", 20, 0, 0, 0, 33, checksum, size, size, len(encoded_name), 0))
        start = next_local + 30 + len(encoded_name)
        _require(raw[next_local + 30:start] == encoded_name)
        payload = raw[start:start + size]
        _require(zlib.crc32(payload) & 0xffffffff == checksum)
        payloads[name] = payload
        next_local = start + size
        cursor += 46 + len(encoded_name)
    _require(next_local == directory_start and cursor == len(raw) - 22)
    return payloads


def _schema(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _verify(raw, expected_sha256):
    if expected_sha256 is not None:
        _require(_hash(expected_sha256), "BUNDLE_HASH_REQUIRED")
    payloads = _members(raw)
    bundle_hash = _sha(raw)
    _require(expected_sha256 is None or bundle_hash == expected_sha256, "BUNDLE_CHANGED")
    _require(payloads["README.txt"] == README and payloads["SHA256SUMS"] == _checksums(payloads))
    _patch(payloads["changes.diff"])
    manifest, review, checks = (_record(payloads[name]) for name in ("manifest.json", "review.json", "checks.json"))
    _schema(manifest, {"format", "hashes", "task_profile", "files"})
    _require(manifest["format"] == "outlands-reviewed-patch-bundle-v1")
    hashes = manifest["hashes"]
    _schema(hashes, HASH_KEYS)
    _require(all(_hash(value) for value in hashes.values()) and hashes["patch_sha256"] == _sha(payloads["changes.diff"]))
    profile, files = manifest["task_profile"], manifest["files"]
    _schema(profile, {"format", "max_turns", "request_seconds", "checks"})
    _require(type(files) is list and 1 <= len(files) <= 32)
    before, editable, names = {}, [], []
    for row in files:
        _schema(row, {"path", "editable", "before_sha256", "after_sha256"})
        _require(type(row["path"]) is str and len(row["path"]) <= 128 and type(row["editable"]) is bool
                 and _hash(row["before_sha256"]) and _hash(row["after_sha256"]))
        _require(row["path"] not in before and (row["editable"] or row["before_sha256"] == row["after_sha256"]))
        before[row["path"]] = row["before_sha256"]
        names.append(row["path"])
        if row["editable"]:
            editable.append(row["path"])
    _require(names == sorted(names) and any(row["before_sha256"] != row["after_sha256"] for row in files))
    task = _task({**profile, "goal": "Inspect this invented bundle profile.", "files": before, "editable": editable})
    _schema(review, {"format", "verdict", "source_applied", "hashes"})
    _require(review["format"] == "outlands-reviewed-patch-review-v1" and review["verdict"] == "accepted"
             and review["source_applied"] is False and review["hashes"] == hashes)
    _schema(checks, {"format", "evidence", "hashes", "checks", "not_checked"})
    _require(checks["format"] == "outlands-reviewed-patch-checks-v1"
             and checks["evidence"] == "RECORDED_INDEPENDENT_FINAL_CHECKS"
             and checks["hashes"] == hashes and checks["not_checked"] == NOT_CHECKED
             and type(checks["checks"]) is list and len(checks["checks"]) == len(task["checks"]))
    for row, name in zip(checks["checks"], sorted(task["checks"])):
        _schema(row, {"name", "spec", "exit_code", "tests_ran", "timed_out", "output_limited", "infrastructure_error"})
        _require(row["name"] == name and row["spec"] == _spec(task["checks"][name]))
        _passing(row)
    for name, value in (("manifest.json", manifest), ("review.json", review), ("checks.json", checks)):
        _require(payloads[name] == canonical(value))
    _require(raw == _archive(payloads))
    summary = {"version": 1, "bundle_sha256": bundle_hash, "archive_bytes": len(raw), "member_count": 6,
        "members": [{"path": name, "bytes": len(payloads[name]), "sha256": _sha(payloads[name])} for name in MEMBERS],
        "hashes": hashes, "files": files, "checks": checks["checks"],
        "review": {"verdict": "accepted", "source_applied": False}, "not_checked": list(NOT_CHECKED), "notes": list(NOTES)}
    _require(len(canonical(summary)) <= 65536, "BUNDLE_LIMIT")
    return summary


def verify_bundle(raw: bytes, expected_sha256: str | None = None) -> dict:
    """Verify stored archive integrity and selected claims, without extraction or execution."""
    try:
        return _verify(raw, expected_sha256)
    except (Refused, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, struct.error) as exc:
        raise Refused(_safe_error(exc, "BUNDLE_INVALID")) from None


def _read_input(name):
    _require(type(name) is str and name.startswith("/") and len(name) <= 4096 and "\x00" not in name)
    _require(len(name.encode("utf-8")) <= 4096)
    parts = name.split("/")[1:]
    _require(parts and all(part and part not in {".", ".."} for part in parts))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1)
            _require(before.st_size <= MAX_ARCHIVE, "BUNDLE_LIMIT")
            raw = stream.read(MAX_ARCHIVE + 1)
            after = os.fstat(stream.fileno())
            _require(len(raw) <= MAX_ARCHIVE, "BUNDLE_LIMIT")
            _require(after.st_nlink == 1 and before.st_size == after.st_size == len(raw)
                     and before.st_mtime_ns == after.st_mtime_ns)
            return raw
    finally:
        os.close(fd)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        _require(type(argv) is list and len(argv) in {1, 3})
        if argv == ["--help"] or argv == ["-h"]:
            sys.stdout.write("Usage: patch_bundle.py /absolute/private.zip [--expect-sha256 HASH]\n")
            return 0
        expected = None
        if len(argv) == 3:
            _require(argv[1] == "--expect-sha256")
            expected = argv[2]
            _require(_hash(expected), "BUNDLE_HASH_REQUIRED")
        summary = verify_bundle(_read_input(argv[0]), expected)
        sys.stdout.write(canonical(summary).decode("ascii"))
        return 0
    except (Refused, OSError, ValueError, TypeError, AttributeError) as exc:
        sys.stdout.write(canonical({"error": _safe_error(exc, "BUNDLE_INVALID")}).decode("ascii"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
