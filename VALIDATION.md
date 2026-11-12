# Version 0.22 validation

Final offline qualification on one Linux host passed **961 unit methods across
42 suites**: the prior 919, 26 pure history methods and 16 controller/HTTP methods.
Actual invented Python/Java history search → pinned metadata review → deliberate
ID handoff → separate explicit comparison → restart passed. Separate actual
fixed checks passed on selected copies: four Python unit tests and one Java
protected main. All prior acceptance probes also passed. No agent Run or model
inference was started by the new acceptance.

| Area | Observed result |
| --- | --- |
| Search | Literal case-sensitive query matches a valid full saved goal or ID before display clipping; no text normalization or query trimming |
| Filters | Exact historical project alias and saved state, including explicit unknown values; choices include inspected historical projects |
| Ordering | Known creation times newest first, then unknown; descending ID breaks ties |
| Metadata | Explicit review rechecks collection and raw-record hashes and returns only cleaned saved metadata; private extra fields excluded |
| Evidence drift | Changed records/history, stale pins, unsafe stores, malformed wrappers and duplicate IDs refuse without repair |
| Boundaries | Search/open read jobs metadata only; no config/task/source/result/event/hold reader, process probe, provider, worker or live-history reconciliation |
| HTTP | Explicit POST routes inherit session/Host/Origin, strict JSON/framing and request/response bounds; negative cases covered |
| Handoff | Fresh explicit metadata open fills only the requested Left or Right slot; no automatic pair, Task assignment or Compare request |
| Comparison | Existing saved-evidence comparison is a separate explicit action and may read its existing task/result/event/diff inputs |
| Python/Java | Seeded saved observations searched/reviewed; independent fixed checks pass on copies without changing original source/config/tasks |
| Browser | Explicit search/review/handoff/Compare, Unicode, literal markup, no matches, unknown metadata, input invalidation and restart observed |
| Held state | Read-only history review works with an unrelated invented hold while Task/Run remain disabled and composer values unchanged |
| Preservation | All initial 56 browser fixture files retain exact bytes/modes; only a new invented hold was added and retained |
| Teardown | Both temporary owned servers stopped and the loopback listener was verified closed |

## Evidence classes and retained corrections

All selected projects, names, histories and instructions are invented. Saved
REVIEW_READY, FAILED and UNCERTAIN rows are seeded observations, not actual agent
outcomes. Pure helper tests perform no I/O or runtime work. Controller fixtures
guard excluded readers and operations and exercise actual private metadata files
and bounded HTTP. Separate Bubblewrap Python unittest and Java compilation/
protected-main checks on selected copies are independent of search/open. One Java
test denotes one protected main, not an assertion count. Prior scripted-client
acceptance remains separate and does not qualify a real model.

The first pure run passed 26 methods. The initial integration run passed 15 of
16: a test expected query/filter errors for non-string inputs, whereas the
contract requires an input error. Correcting only that expectation yielded
16/16; both logs are retained. The first complete backend qualification passed
961/42 and actual acceptance. Independent frontend review found malformed
match-field and note types plus terminal-line-separator identifier acceptance.
Only the new history validators in app.js were tightened. The other 99 qualified
executable/static/input hashes stayed unchanged; no Python/controller/Java input
changed. The amended frontend passed **183 isolated Node validator and mocked
handoff checks** and independent review. An initial negative Node fixture had
misclassified a valid alias as invalid; its correction required no source edit.
All 100 final qualified inputs match the reviewed snapshot.

One preliminary browser opening of the existing comparison-history reader
preceded the frontend amendment; it made no new search, metadata-open or Compare
request. The corrected UI was reloaded before all 17 final browser observations.
The browser fixture deliberately stubs the normal live history feed empty and
counts it, preventing unrelated saved-worker reconciliation during this panel's
qualification. New search/open and the existing read-only comparison routes are
real. This is not acceptance of the normal live history feed or worker recovery.

Across two browser sessions there were nine explicit search requests, seven
metadata-open requests (including handoffs), and one explicit Compare request.
Search controls did not issue requests on typing, filter changes or local Clear.
Search matched a query beyond the normal goal prefix, and the clipped excerpt
retained the complete query. Metadata review showed the complete Unicode goal
and literal markup as text. Left-only handoff kept Right empty; later Right
handoff left comparison unrequested until the separate Compare click. A read-only
collector initially checked only the first part of the comparison panel; the
full DOM confirmed both IDs/cards. Compare was not repeated to correct that
collector. Java combining/astral text, case-sensitive no-match, unknown legacy
metadata and retained uncertain observations were also reviewed. Reload cleared
cached results/details and comparison slots. A subsequent review after restart
worked under an invented hold with Task/Run disabled. No captured browser console
warnings/errors occurred; the observed badge was 0.22.

Guarded Run/start, refresh, process-probe, provider, outbound HTTP and worker-launch
counts were all zero. Existing comparison-history reads are separate from search
and may occur when opening the panel; the empty normal-feed stub is a fixture
limit. Initial source/config/task/job/run bytes and modes remained unchanged.
No historical failure, partial record or hold was retried, cleaned up, erased or
relabelled. Private fixture observations and logs are excluded from publication.

## Bounds and trust limits

Each inspection processes at most 1,024 directory entries, admits at most 200
metadata filenames, reads at most 32,768 bytes per file and stays within a 2-MiB
logical read budget including overflow-byte reservations. One lookahead entry
can be consumed to detect truncation. Search and open each perform two bounded
inspections to detect intervening drift; 2 MiB is not a total per-request bound.
Metadata files must be owner-only regular single-link files in owner-only
anchored data/jobs directories. No-follow opens and descriptor/path identity
checks reject unsafe or changed storage. This is a sequential observation on
trusted stable single-owner storage, not an atomic multiwriter snapshot or a
crash-durability guarantee.

A query is at most 128 UTF-8 bytes and excludes NUL, CR, LF and invalid Unicode.
Empty query means all inspected rows. Saved valid goals allow 0–2,000 codepoints
and at most 8,000 UTF-8 bytes; legacy missing/invalid fields become unknown,
with invalid-present fields explicitly noted. Known labels display at most
160 UTF-8 bytes. Query matches are computed before clipping; metadata review
returns the complete cleaned goal. Results are capped at 100 rows and reduced
further to fit the 65,536-byte canonical response. Matched/returned/inspected
counts and independent catalog/result truncation flags disclose omissions.
The new HTTP requests are at most 32,768 bytes. A truncated catalog is a bounded
subset, not a claim that all saved runs were searched.

The frontend validates response shapes, exact enum/type membership, ID/hash
lengths and complete alias matches, with text-node rendering and current-input
checks before handoff. Hash pins are integrity observations, not ownership,
authenticity or authorization proofs. Saved states are observations, not live
status or current source correctness. Search reads no source and performs no
checks. It creates no persistent search cache, token, history index or record.

Real histories, goals, names, configuration, source, comparisons, bundles and
runtime records remain excluded from public uploads. The original uncertain
Java trial remains unqualified; cause and provider completion are unknown. Its
exact hold/result preservation hashes remain unchanged. No inference, recovery,
eviction, service change, original-project adoption or license assignment
occurred. Earlier evidence remains in [version 0.21 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/a94ce24f01eee07aeaafb6dce6ca9484e0865fad/VALIDATION.md).
Qualification used Python 3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting
Java 17 on Linux. Local passes are not GitHub CI passes. Licensing remains
**UNASSIGNED**; see [origins](ORIGINS.md).
