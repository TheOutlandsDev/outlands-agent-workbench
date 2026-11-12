# Version 0.18 validation

Final offline qualification on one Linux host passed **792 unit methods across
34 suites**: the prior 744, 23 editor engine methods and 25 controller/HTTP
methods. Actual Python/Java edit → fresh isolated recheck → reviewed private v2
export passed, along with all prior acceptance probes. Editor operations made
zero checks, Git commands, worker or model requests; fresh checks ran separately
through existing fixed-check workers. Real bundles and evidence remain private.

| Area | Observed result |
| --- | --- |
| Exact editing | One nonempty unique byte span; Unicode, LF/CRLF/mixed bytes and missing final newline preserved outside the span |
| Scope | Existing approved editable snapshot-workspace files only; protected/control paths, links, escapes and unsafe modes refused |
| Mode compatibility | Existing 0600/0644/0664 preserved beneath verified owner-only private job directory; original/candidate evidence is 0600 |
| Pins | Source/task/config/creation/check/Git controls, all selected bytes, edit history and recheck history revalidated |
| Admission | Saved holds, active/uncertain records, owned-worker entries and unresolved edits refuse saves without reconciliation |
| One-use preview | Explicit list/open/preview/save; expiry, replacement and restart invalidate pins; no autosave or automatic rerun |
| Retained writes | Failed and post-replacement uncertain outcomes retain evidence and block later mutations without cleanup/retry/rollback |
| Journal | Strict finite receipts, original/candidate hashes, partial/link/count guards, aggregate bounds and new-record reservation |
| Fresh checks | Every saved edit records prior attempt IDs; controller re-export refuses them, including after reverting to identical bytes |
| HTTP | Session/origin and duplicate-header, transfer encoding, exact fields, body-size/short-read/JSON guards tested |
| Python/Java | Actual separate fixed checks pass, private packets verify as strict v2 and exact baseline-to-snapshot patches |
| Preservation | Original project/Git, historical creation/recheck/review evidence and unrelated synthetic holds remain unchanged |
| Browser | Python LF and captured Java CRLF selection, explicit saves/checks/review/download, parent/selection/reload invalidation observed |
| Download integrity | Both downloaded archives match acceptance digests and tested file hashes; notes and private paths absent |
| Teardown | Owned temporary browser server stopped, listener closed and original/historical bytes verified unchanged |

## Evidence classes and retained development outcomes

Unit fixtures use invented selected projects. Engine tests use supplied inspection
objects and guarded filesystem fixtures; they execute no project checks or Git.
Controller tests use actual private Git creation with clearly invented check
observations. These are separate from the full runner's actual Bubblewrap Python
unittest and Java compilation/protected-main checks, and from the browser's
actual Python four-test and Java one-main results. One Java test means one
executed protected main, not its number of assertions. No model was called.

The first 20-method engine run passed. The first 23-method integration run
exposed a real compatibility defect: the engine assumed mode 0600 while actual
Git checkout files used host-created 0664. The engine now supports and preserves
0600/0644/0664 inside the verified owner-only private job directory; 23 focused
engine methods passed. The second 25-method integration run passed behavior
checks but hit a test-cleanup double close after explicit restart. The corrected
fixture owns both manager lifetimes; a separate 25-method run passed. All earlier
logs remain retained. No failed runtime request, job or hold was retried, erased
or relabelled. The final full qualification passed on its new private root.

The browser version badge was corrected to 0.18 during qualification, with an
exact one-label HTML change; engine/controller/JavaScript bytes stayed unchanged.
Reload verified that label and discarded unsaved editor pins. Browser tests
reviewed and saved exactly two invented edits, performed fresh fixed checks,
explicitly accepted/downloaded two private v2 packets, then closed the temporary
server. Java selected text retained its original CRLF bytes despite browser
textarea normalization. A parent SHA input change and workspace switch discarded
old editor/export state. Browser locator and read-only download-collector helper
errors were corrected without repeating a save, check, acceptance or download.

## Bounds and trust limits

32 approved UTF-8 files, 32,768 bytes per file, 131,072 total selected bytes.
Requests/full-text responses: 262,144 bytes. Previews: 131,072 bytes. Diff: 240
lines/8,192 UTF-8 bytes with clipping. Journal: 200 entries, 2 MiB aggregate raw
receipts, 32,768 bytes per receipt and reserved before a new write; retained
original/candidate copies each have the per-file bound. Preview expiry is five
minutes or restart. Unsafe, partial, malformed or unfinished records refuse
without older-record fallback or repair.

A save writes one existing private worktree file and a new separate journal,
never original project files or historical results. A failure can leave the file
changed with uncertain finalization. Sequential guards and atomic replacement
assume a trusted stable single-owner filesystem; they are not multiwriter
compare-and-swap, authenticity or crash-recovery proof. The controller's new
attempt requirement uses the private journal; standalone archive verification
remains a hash/evidence check without human approval or access to that journal.
V1/v2 archive schemas remain unchanged. Passing fixed checks do not establish
source correctness, model competence, provider completion or adoption permission.

The original uncertain Java trial remains unqualified, with cause and provider
completion unknown. Its exact hold/result hashes are unchanged. No model request,
recovery, eviction, service change, original-project adoption or license assignment
occurred. Earlier evidence remains in [version 0.17 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/5c4f5901ad07c114b9a20c27403387dc9ff732e4/VALIDATION.md).
Qualification used Python 3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting
Java 17 on Linux. Local passes are not GitHub CI passes. Licensing remains
**UNASSIGNED**; see [origins](ORIGINS.md).
