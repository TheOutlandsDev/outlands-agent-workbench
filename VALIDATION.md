# Version 0.13 validation

Offline qualification on one Linux host passed **550 unit methods in 24 suites**:
the prior 500, 31 snapshot-export engine methods and 19 controller/HTTP methods.
The full runner also passed actual isolated Python/Java creation and manual-edit
rechecks before export, exact patch reconstruction and the earlier acceptance
probes. No model request was made. Real bundles, workspaces, snapshots, exports,
acceptance notes and runtime records remain private.

| Area | Observed result |
| --- | --- |
| Retained suites | All prior 500 methods and acceptance probes passed |
| Snapshot-export engine | 31 methods passed |
| Controller and HTTP | 19 methods passed |
| Exact patch scope | Approved original baseline to the selected VERIFIED tested snapshot; initial imported fix and later tested manual comments both present |
| Python and Java | Actual isolated creation/recheck checks passed; exported patch reconstructed the exact selected tested bytes |
| Formatting | UTF-8, CRLF, missing final LF, empty-file changes and multiple hunks round-tripped; ambiguous separators refused |
| Recorded checks | Full bounded check evidence, exact configured names/specifications, types, passing observations, hashes and clipped receipt display validated |
| Archive | Four deterministic stored ZIP members; fixed metadata, sizes, checksums, paths and finite schemas checked without extraction |
| Privacy | No raw records, goals, host paths, timestamps, private Git refs, prompts, check output or acceptance notes in verification data |
| Acceptance | Five-minute one-use preview, explicit private note, exact receipt/review pins and separate download |
| History | Current recheck and acceptance tips bound; a later acceptance invalidates an earlier download; no older fallback |
| Stale evidence | Changed source/config/task/Git, protected files, snapshot, saved checks and receipts refused |
| Failure | Partial, malformed, PREPARING and FAILED acceptance evidence blocks exports; own-review mutation retains FAILED evidence |
| Bounds | Receipt count/aggregate/reserve, record sizes, snapshot, patch, preview and archive limits enforced |
| No execution | Export preview/accept/download/history and verifier guarded against Git/check/provider/process/admission/reconciliation calls |
| Unrelated hold | Export operations worked without reading or changing the synthetic hold; execution admission remained blocked |
| HTTP | Session/Host/Origin/fetch guards, exact declared JSON framing, duplicate lengths, transfer encoding and ZIP response checked |
| Browser | Explicit Python/Java review, acceptance and download; Unicode note boundary, selection invalidation and stale-history refusal observed |
| Restart and teardown | Final server downloaded identical retained Java bytes without changing saved records; owned loopback port closed |

## Evidence classes

Unit fixtures contain invented Python/Java source and saved passing observations,
using real private Git worktrees with fake check runners. They prove controller
and reducer behavior, not historical agent execution. Browser trials likewise
used invented creation/recheck observations; downloaded ZIPs independently
verified and reconstructed the exact fixture snapshots from their baselines.

Full acceptance separately ran the actual fixed isolated Python/Java checks to
create review workspaces, added invented manual UTF-8 comments, and ran actual
snapshot rechecks before exporting. Preview, acceptance, download and the
verifier ran under no-runtime guards after those checks. They performed zero new
check executions or model requests. Original source/worktree/Git bytes, earlier
creation/recheck records and synthetic holds stayed unchanged; explicit export
acceptance added only its own private receipt and displayed-review record.
A deliberately altered snapshot was refused and its private negative stage
retained. Newer acceptance history invalidated the earlier download.

Initial focused HTTP testing had one test-only MIME expectation mismatch:
the valid response included `charset=utf-8`. The assertion was corrected to
compare its media type; that first failure was retained privately. Later focused
suites and the full qualification passed. Independent review also found and
fixed prior-review integrity and own-review mutation gaps before final testing.
UI review corrected inspection invalidation and lone-surrogate note handling.
No failed operational run or uncertain model request was retried or relabelled.

## Review and integrity boundaries

Export preparation requires the exact selected VERIFIED recheck receipt and
request, original initial receipt/task, complete full check evidence and matching
original creation/project/config/bundle/Git pins. It re-inspects current selected
workspace bytes and requires the tested snapshot/hash to remain current. The
saved recheck preview is reconstructed using its original saved history pin;
current global histories separately bind the new export review.

The patch compares approved original baseline bytes with that tested snapshot,
including the initial bundle changes and later tested editable refinements.
Only selected editable files may differ; protected files must match. The
canonical unified diff is parsed and applied in memory against the baseline,
then required to reconstruct the exact snapshot. No filesystem patch is applied.
Unsupported or ambiguous line syntax is refused rather than normalized.

The deterministic `outlands-reviewed-snapshot-export-v1` archive contains exactly
`changes.diff`, `verification.json`, `README.txt` and `SHA256SUMS`. Verification
carries relative scope, selected hashes, fixed task profile/check specifications
and finite passing observations. Original records are omitted and represented
by hashes. The patch and filenames still contain private project information.
The archive is unencrypted, unsigned and private. Embedded checksums establish
integrity, not authenticity, ownership, source correctness, provider completion
or permission to adopt changes. The verifier neither extracts nor executes it.

Human acceptance remains outside the archive to avoid a circular acceptance/hash
claim. Explicit acceptance binds the displayed summary, preview, whole archive
and current histories in two private files. It consumes the draft before writing
and revalidates after staging. Late failure retains FAILED or unresolved partial
evidence, blocks further exports and does not change normal execution admission.
Every accepted review is validated when traversing history. No cleanup, repair,
retry, hold clearing, Git adoption or model recovery is provided.

Download revalidates the exact accepted receipt, saved review, reconstructed
artifact and histories without writes. Parent acceptance history excludes only
the selected acceptance itself; any later acceptance invalidates the old pin.
Restart discards previews but permits explicitly selected saved acceptance to
download when every fresh guard still matches. Histories never select an older
approval as a substitute. Changed content needs a valid fresh recheck; a history
pin change alone needs fresh explicit review and acceptance.

## Bounds and remaining limits

| Input/output | Bound |
| --- | --- |
| Selected files | 32 UTF-8 files, 32,768 bytes/file, 131,072 total |
| Full check evidence | 2,097,152 bytes |
| Patch / verification / archive | 1,048,576 / 262,144 / 2,097,152 bytes |
| Summary / review preview | 65,536 / 131,072 bytes |
| Diff display | 8,192 UTF-8 bytes and 240 lines; truncation labelled |
| Preview | One memory draft, five-minute validity, one-use acceptance |
| Private acceptance | 200 records, 2 MiB aggregate raw receipts, 32,768-byte receipt reserve |
| Saved review | 131,072 bytes each; at most 200 traversed |
| Note | 1,000 Unicode code points, 2,000 UTF-8 bytes, no NUL or invalid Unicode |
| JSON request / history response | 32,768 / 262,144 bytes |

This retains the documented simple private Git/index-v2/loose-object subset.
The host/config/private store must remain trusted and stable. Sequential
observations are not atomic multiwriter snapshots or proof that no intermediate
change occurred. Saved checks and unsigned hashes cannot authenticate an agent
run. Real-model Java qualification remains uncertain and untested by this work;
the original held result and hold retain their prior hashes.

No inference, recovery, retry, eviction, service/deployment change or license
assignment occurred. Earlier evidence remains in
[version 0.12 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/5a939ed98a6b741ec8942ecb6ee486b33396dad1/VALIDATION.md).
Qualification used Python 3.12.7, isolated Python 3.10.12, Git 2.34.1 and Temurin
JDK 21.0.13+9 targeting Java 17 on Linux. Local passes are not GitHub CI passes.
Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
