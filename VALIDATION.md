# Version 0.19 validation

Final offline qualification on one Linux host passed **836 unit methods across
36 suites**: the prior 792, 20 pure workspace-search methods and 24 controller/HTTP
methods. Actual invented Python/Java search → protected/focused read → pinned
editor handoff → explicit edit → fresh isolated recheck → reviewed private v2
export passed, along with all prior acceptance probes. Navigation made zero
checks, Git commands, workers or model requests. Real workspace content and
bundles remain private.

| Area | Observed result |
| --- | --- |
| Approved scope | Only current selected files in verified private snapshot workspaces; no recursive discovery or scope expansion |
| Literal search | Case-sensitive matching, deterministic path/line order, Unicode columns and current file/workspace hashes |
| Focused reads | Inclusive numbered ranges, protected/editable labels, LF/CRLF/CR, empty files and explicit clipping/EOF |
| Pinned handoff | Explicit editable-only open rechecks whole snapshot and file hash; no automatic preview, save or run |
| Stale evidence | Changed file/other selected file, source/config/task/Git/creation or unresolved edit evidence refuses access |
| Race guards | Locked before/after inspections refuse drift observed during search, read or open |
| Read-only navigation | Guarded search/read skip admission and hold access; all three navigation routes preserve private file hashes |
| Held state | Search/read and admission-labelled handoff remain available under unrelated synthetic hold; later save refuses |
| HTTP | Exact fields, authentication/origin, duplicate headers, transfer encoding, short reads, JSON and route-specific caps tested |
| Python/Java | Actual separate fixed checks pass after explicit edits; strict v2 packets match exact tested snapshots |
| Preservation | Original project/Git and historical creation/check/review records remain unchanged; synthetic holds retained |
| Browser | Protected reads/editor refusal, Python LF, Java CRLF and café search, pinned handoff and full private export flows observed |
| Invalidation | Parent, workspace selection, range, save and page reload discard old source observations and dependent editor pins |
| Download integrity | Both browser ZIP hashes/strict v2 metadata/check counts/current selected hashes match private receipts |
| Teardown | Temporary owned server stopped, listener closed, exactly two private editable targets changed and historical bytes preserved |

## Evidence classes and preserved outcomes

All selected projects are invented. Pure engine tests use supplied inspection
objects and never access files, Git, checks or a provider. Controller fixtures use
actual private Git creation with clearly invented recorded check observations.
These are separate from the full runner's actual Bubblewrap Python unittest and
Java compilation/protected-main checks, and from the browser's actual Python
four-test and Java one-main results. One Java test means one executed protected
main, not an assertion count. No model was called.

The first focused pure run passed 20 methods; the first focused integration run
passed 24. The first full qualification passed 836 methods/36 suites and all
actual acceptance probes on its new private root. Final engine/controller/UI
bytes stayed unchanged through browser qualification and freeze. Earlier
milestone failures, partial records, holds and successful results remain separate
and preserved; no failed runtime request or held job was retried, erased or
relabelled. A read-only download collector needed a task-root path normalization
fix, then reread the same unchanged packets without repeating any application
operation.

Browser testing performed exactly two explicit saves, fresh rechecks, private
acceptances and downloads. Protected Python/Java test excerpts remained read-only;
editable handoff showed current exact hashes and Java CRLF bytes. Parent SHA-input
change discarded search/editor previews, range change discarded excerpt/handoff,
workspace switch disabled old export, and save cleared old search results. Reload
cleared cached observations and displayed 0.19. After the actual check/export
flows, an invented unrelated hold was added and retained; search/read/open and
preview remained available while Save stayed disabled. This was a separate
synthetic fixture, never a change to the original uncertain Java trial.

## Bounds and trust limits

32 approved UTF-8 files, 32,768 bytes/file and 131,072 total selected bytes. Query:
1–128 UTF-8 bytes, no NUL/newline; literal case-sensitive search returns one hit
per matching line, at most 20. Inner search results remain within 8,192 serialized
bytes including editable labels, trimming trailing hits when necessary while
retaining total counts and truncation. Search/read wrappers: 16,384 bytes. Search
line excerpts: 512 UTF-8 bytes. Focused reads: 1-based inclusive ranges of at most
80 lines, maximum line number 1,000,000 and 1,024 UTF-8 bytes per line, with actual
returned ranges/EOF/clipping. Empty files have no invented lines. HTTP input:
32,768 bytes for all three navigation routes; editor-open output retains the
existing 262,144-byte full-text bound.

The controller supplies and repeats verified filesystem inspections; pure helper
hashes are structural checks, not authorization or authenticity. Reads are
sequential on trusted stable single-owner storage, not an atomic multiwriter
snapshot or proof against transient changes. Search results are current byte
observations, not checks, model qualification or adoption permission. Opening a
result writes no files and does not bypass editor admission, review or fresh
recheck requirements. Existing v1/v2 archive and edit/recheck schemas remain
unchanged. Search queries, excerpts, relative paths and hashes contain private
source context and stay outside public uploads.

The original uncertain Java trial remains unqualified, with cause and provider
completion unknown. Its exact hold/result hashes are unchanged. No model request,
recovery, eviction, service change, original-project adoption or license assignment
occurred. Earlier evidence remains in [version 0.18 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/4d431fbc13454eb418818906ef410025c122e533/VALIDATION.md).
Qualification used Python 3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting
Java 17 on Linux. Local passes are not GitHub CI passes. Licensing remains
**UNASSIGNED**; see [origins](ORIGINS.md).
