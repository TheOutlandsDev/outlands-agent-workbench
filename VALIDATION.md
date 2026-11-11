# Version 0.14 validation

Offline qualification on one Linux host passed **601 unit methods in 26 suites**:
the prior 550, 35 snapshot-project helper methods and 16 controller/HTTP methods.
The full runner also passed actual isolated Python/Java/mixed creation and
manual-edit snapshot rechecks before export, project comparison and the earlier
acceptance probes. Snapshot-project inspection performed zero checks or model
requests. Real exports, source/workspaces, snapshots and records remain private.

| Area | Observed result |
| --- | --- |
| Retained qualification | All prior 550 methods and acceptance probes passed |
| Snapshot-project helper | 35 methods passed |
| Controller and HTTP | 16 methods passed |
| Baseline reconstruction | Exact forward patch on selected original baseline reconstructed every tested hash and reproduced the canonical diff |
| Other byte states | Tested, mixed, different and missing observations gave no forward or reverse reconstruction proof |
| Actual checked fixtures | Separate isolated Python/Java/mixed initial and manual-edit snapshot checks passed before inspection |
| Profile guards | Format, selected path set, permissions, check specifications and budgets compared; mismatch skipped source reads |
| Project guards | Config/task pins checked before and after inspection; changed or unreadable evidence refused |
| Input ordering | Invalid archive or trusted hash refused before task/config/source reads |
| Patch evidence | Self-consistently rehashed wrong patch refused reconstruction; protected files and exact snapshot bounds enforced |
| Formatting | UTF-8, CRLF, missing final LF and empty-file changes checked without normalization |
| Source observations | Missing, changed, binary, invalid UTF-8, oversized, linked and special inputs reported/refused within bounds |
| Observed drift | Successful reconstruction reread its selected baseline; changed observations removed verification |
| Private output | Relative approved paths and bounded hashes only; no goals, source text, check output, host paths or run IDs |
| No runtime action | No inspector writes, extraction, Git/check/provider execution, executable probes, admission or hold inspection |
| HTTP | Session/Host/Origin/fetch guards and exact binary MIME/length/hash framing enforced |
| Browser | Baseline Python/Java, tested/mixed/different/missing, wrong trusted digest and result invalidation observed |
| Hold and restart | Inspection under a separate synthetic hold; execution still blocked; fresh final server changed no saved bytes |
| Teardown | Owned loopback port closed; original uncertain Java result/hold hashes unchanged |

## Evidence classes

Unit and browser fixtures use invented selected source, real private Git
worktrees and fake saved passing observations. They test reduction, controller
and interface behavior; they do not authenticate historical checks or establish
agent competence. Focused helper and integration suites passed their first runs.
No development test failure was hidden, rerun or relabelled.

Full acceptance separately created Python, Java and mixed review workspaces
using actual isolated checks, added invented manual comments, and ran actual
snapshot rechecks before preparing private v0.13 exports. Only then did it inspect
them under guards against execution, providers, extraction and old-record writes.
No JDK was configured for the inspector itself. Baselines reconstructed exactly;
tested/mixed/different/missing stages were separately labelled without that proof.
Intentional source changes between observations are retained as fixture stages;
the inspector did not make them. Each inspection preserved its input-stage bytes,
and earlier creation/recheck/workspace/Git evidence and synthetic holds remained
unchanged. Check execution belongs to fixture preparation, not inspection.

Browser checks independently observed Python and Java baseline reconstruction,
then intentional tested, mixed, changed and missing stages. Project/hash edits
invalidated old results, and a wrong supplied whole-archive digest refused before
comparison. The final server loaded retained state under a synthetic hold and
reported mixed bytes without reconstruction or writes; all saved bytes matched
afterward. Review corrected trusted-digest wording and replaced broad claims that
files stayed unchanged with precise statements that the check wrote no project
files, since other actors may change source during observation.

## Inspection contract

Only the strict four-member `outlands-reviewed-snapshot-export-v1` format is
accepted. Its stored framing, schemas, paths, fixed metadata, checksums and
optional trusted archive hash are verified before task/source access. Omitted
original records remain represented by unsigned hashes; a valid packet does
not authenticate those records, source ownership, provider completion or tests.
The older six-member reviewed bundle format stays separate and unchanged.

The explicitly selected approved task must match export format, scope, editable
permissions, configured check names/specifications and budgets before any source
read. Export paths never expand approved scope. Cached config/task fingerprints
are checked before and after the comparison, and CLI task bytes are reread before
returning. Current source hashes are compared with baseline and tested hashes;
configured task-pin matches remain a separate advisory observation.

Only a complete matching baseline supports strict forward reconstruction. The
diff is applied to a fresh in-memory copy, resulting paths/protected bytes and
all tested hashes must match, size bounds remain valid, and regenerated canonical
diff bytes must equal the archive patch. A final selected-byte reread removes
verification if observed drift occurs. Reconstruction failure becomes
NEEDS_INSPECTION with a finite reason. No reverse reconstruction is provided for
tested or mixed content, and no missing/different case establishes applicability.

The operation writes no source, workspace, acceptance or run record, performs no
archive extraction or filesystem apply, and runs no Git/check/model/provider
request, admission reconciliation or hold read/write. An unrelated hold remains
independent of this advisory inspection. The browser sends inputs only after an
explicit check action and discards stale results when inputs or panel state change.
No result authorizes execution, source adoption, a commit or clearing a hold.

## Bounds and remaining limits

| Input/output | Bound |
| --- | --- |
| Approved selected files | 32 named UTF-8 files, 32,768 bytes/file |
| Complete selected observation | At most 1 MiB to classify all bounded files |
| Reconstruction eligibility | 131,072 aggregate source/result bytes |
| Private archive / task | 2,097,152 / 262,144 bytes |
| Comparison / browser JSON | 65,536 / 131,072 bytes |
| Reconstruction output | Memory only, selected scope and recorded tested hashes |

The readers refuse unsafe links/special files and unsupported text. Observations
are sequential on a trusted, stable host/store, not an atomic multiwriter
snapshot or proof that no intermediate change occurred. TESTED_MATCH means only
observed bytes match recorded tested hashes; checks are not rerun and reverse
applicability remains unverified. Unsigned integrity and a trusted whole-archive
hash are separate from authentication and source correctness.

The original uncertain Java trial remains unqualified; its cause and provider
completion are unknown, and its result/hold retain their prior hashes. No model
request, recovery, retry, eviction, service/deployment change or license
assignment occurred. Earlier evidence remains in
[version 0.13 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/224fcfb8fcfff40186183101961a71b274865aad/VALIDATION.md).
Qualification used Python 3.12.7, isolated Python 3.10.12, Git 2.34.1 and Temurin
JDK 21.0.13+9 targeting Java 17 on Linux. Local passes are not GitHub CI passes.
Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
