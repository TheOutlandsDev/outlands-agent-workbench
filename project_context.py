"""Pure context helpers over an explicitly supplied, bounded file snapshot.

These helpers never discover, open, or execute files. Paths are display labels;
the caller is responsible for authorizing the selected snapshot and its scope.
Response limits count compact ``ensure_ascii=True`` JSON plus one newline.
"""

import hashlib
import json


MAX_FILES = 32
MAX_FILE_BYTES = 32_768
MAX_SNAPSHOT_BYTES = 131_072
MAX_PATH_BYTES = 1_024
BYTE_LIMIT = 8_192
SEARCH_LIMIT = 20
SEARCH_TEXT_BYTES = 512
READ_TEXT_BYTES = 1_024
MAX_READ_LINES = 80
MAX_LINE_NUMBER = 1_000_000


class ContextRefused(Exception):
    """A refusal containing only a fixed, non-sensitive error code."""

    CODES = frozenset({
        "CONTEXT_QUERY", "CONTEXT_FILES", "CONTEXT_PATH",
        "CONTEXT_SNAPSHOT_LIMIT", "CONTEXT_UTF8", "CONTEXT_RANGE",
    })

    def __init__(self, code):
        self.code = code if type(code) is str and code in self.CODES else "CONTEXT_FILES"
        super().__init__(self.code)


def _validate_path(path):
    if (type(path) is not str or not path or len(path) > MAX_PATH_BYTES
            or any(char in path for char in ("\x00", "\r", "\n"))):
        raise ContextRefused("CONTEXT_PATH")
    try:
        encoded = path.encode("utf-8")
    except UnicodeEncodeError:
        raise ContextRefused("CONTEXT_PATH") from None
    if len(encoded) > MAX_PATH_BYTES:
        raise ContextRefused("CONTEXT_PATH")


def _validate_raw(raw):
    if type(raw) is not bytes:
        raise ContextRefused("CONTEXT_FILES")
    if len(raw) > MAX_FILE_BYTES:
        raise ContextRefused("CONTEXT_SNAPSHOT_LIMIT")


def _lines(raw):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ContextRefused("CONTEXT_UTF8") from None
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if normalized.endswith("\n"):
        lines.pop()
    return lines


def _json_bytes(result):
    return len((json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
               .encode("ascii"))


def _utf8_prefix(text, byte_limit):
    """Take complete Unicode code points, without retaining a partial UTF-8 unit."""
    return text.encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def _search_result(query, files_searched, total_matches, matches):
    return {
        "query": query,
        "files_searched": files_searched,
        "total_matches": total_matches,
        "matches": matches,
        "truncated": total_matches > len(matches) or any(hit["truncated"] for hit in matches),
        "limit": SEARCH_LIMIT,
        "byte_limit": BYTE_LIMIT,
    }


def search_text(files: dict[str, bytes], query: str) -> dict:
    """Search case-sensitive literal text, returning the first hit on each line.

    Matching lines are counted across the entire snapshot, including lines that
    cannot be returned within the hit or serialized-response byte limit.
    """
    if (type(query) is not str or not query or len(query) > 128
            or any(char in query for char in ("\x00", "\r", "\n"))):
        raise ContextRefused("CONTEXT_QUERY")
    try:
        query_bytes = len(query.encode("utf-8"))
    except UnicodeEncodeError:
        raise ContextRefused("CONTEXT_QUERY") from None
    if query_bytes > 128:
        raise ContextRefused("CONTEXT_QUERY")
    if type(files) is not dict:
        raise ContextRefused("CONTEXT_FILES")
    if len(files) > MAX_FILES:
        raise ContextRefused("CONTEXT_SNAPSHOT_LIMIT")
    total_bytes = 0
    for path, raw in files.items():
        _validate_path(path)
        _validate_raw(raw)
        total_bytes += len(raw)
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise ContextRefused("CONTEXT_SNAPSHOT_LIMIT")

    total_matches = 0
    candidates = []
    for path in sorted(files):
        raw = files[path]
        lines = _lines(raw)
        digest = None
        for line_number, line in enumerate(lines, 1):
            column = line.find(query)
            if column < 0:
                continue
            total_matches += 1
            if len(candidates) == SEARCH_LIMIT:
                continue
            if digest is None:
                digest = hashlib.sha256(raw).hexdigest()
            prefix = line[max(0, column - 40):column]
            suffix = _utf8_prefix(
                line[column + len(query):],
                SEARCH_TEXT_BYTES - len(prefix.encode("utf-8")) - query_bytes,
            )
            candidates.append((path, line_number, column + 1, line, prefix, suffix, digest))

    matches = []
    for path, number, column, line, prefix, suffix, digest in candidates:
        def candidate(context_count):
            before_count = min(context_count, len(prefix))
            before = prefix[len(prefix) - before_count:]
            after = suffix[:max(0, context_count - len(prefix))]
            text = before + query + after
            return {"path": path, "line_number": number, "column": column,
                    "text": text, "sha256": digest,
                    "truncated": len(text) != len(line)}

        def fits(hit):
            return _json_bytes(_search_result(
                query, len(files), total_matches, matches + [hit])) <= BYTE_LIMIT

        full_count = len(prefix) + len(suffix)
        hit = candidate(full_count)
        if not fits(hit):
            if not fits(candidate(0)):
                break
            low, high = 0, full_count
            while low < high:
                middle = (low + high + 1) // 2
                if fits(candidate(middle)):
                    low = middle
                else:
                    high = middle - 1
            hit = candidate(low)
        matches.append(hit)
    return _search_result(query, len(files), total_matches, matches)


def _read_result(path, digest, start, end, total, expected_count, lines):
    return {
        "path": path,
        "sha256": digest,
        "requested_start": start,
        "requested_end": end,
        "start_line": lines[0]["line_number"] if lines else None,
        "end_line": lines[-1]["line_number"] if lines else None,
        "total_lines": total,
        "lines": lines,
        "truncated": len(lines) < expected_count or any(line["truncated"] for line in lines),
        "end_of_file": total == 0 or bool(lines and lines[-1]["line_number"] == total),
        "byte_limit": BYTE_LIMIT,
    }


def read_lines(path: str, raw: bytes, start_line: int, end_line: int) -> dict:
    """Read an inclusive line range from supplied bytes, with explicit omissions.

    A valid range on an empty file returns no lines. For a nonempty file, the
    start must exist; the end can clamp to EOF. Output byte clipping preserves
    a contiguous actual line range and marks every shortened line.
    """
    _validate_path(path)
    _validate_raw(raw)
    if (type(start_line) is not int or type(end_line) is not int
            or not 1 <= start_line <= MAX_LINE_NUMBER
            or not start_line <= end_line <= MAX_LINE_NUMBER
            or end_line - start_line + 1 > MAX_READ_LINES):
        raise ContextRefused("CONTEXT_RANGE")
    source_lines = _lines(raw)
    total = len(source_lines)
    if total and start_line > total:
        raise ContextRefused("CONTEXT_RANGE")
    digest = hashlib.sha256(raw).hexdigest()
    selected = source_lines[start_line - 1:min(end_line, total)]
    returned = []

    def result(lines):
        return _read_result(path, digest, start_line, end_line, total, len(selected), lines)

    for number, line in enumerate(selected, start_line):
        text = _utf8_prefix(line, READ_TEXT_BYTES)

        def candidate(count):
            prefix = text[:count]
            return {"line_number": number, "text": prefix,
                    "truncated": len(prefix) != len(line)}

        def fits(item):
            return _json_bytes(result(returned + [item])) <= BYTE_LIMIT

        item = candidate(len(text))
        shortened_for_output = not fits(item)
        if shortened_for_output:
            # Do not report a nonempty source line as empty merely to fit it.
            minimum = 1 if text else 0
            if not fits(candidate(minimum)):
                break
            low, high = minimum, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if fits(candidate(middle)):
                    low = middle
                else:
                    high = middle - 1
            item = candidate(low)
        returned.append(item)
        if shortened_for_output:
            break
    return result(returned)
