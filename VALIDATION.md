# Version 0.9 validation

Observed on 10 November 2026 (America/New_York) on one Linux development host.
Offline acceptance passed all **377 unit methods**: the prior 328, 30 pure bundle
and CLI methods, and 19 bundle/controller/HTTP methods. The full runner also
passed existing actual isolated Python/Java, Java-client parity, Git worker,
namespace, timeout/output, prerequisite, refresh, comparison and readiness checks.
No real-model requests were made. Runtime records, downloaded bundles, private
source and review receipts remain excluded from the public source package.

| Area | Observed result |
| --- | --- |
| Retained unit suites | All prior 328 methods passed |
| Bundle builder/verifier/CLI | 30 methods passed |
| Bundle controller/HTTP | 19 methods passed |
| Invented Python/Java artifacts | Deterministic previews, pinned downloads and offline verification passed; Java bundle handling required no JDK |
| Evidence guards | Unaccepted, uncertain, stale, malformed, missing, partial and inconsistent scope/hash/final-check evidence refused |
| Filesystem/read bounds | Symlinks, hardlinks, substituted ancestors, record/scan/read limits and selected-snapshot total bound refused |
| Archive guards | Compression, encryption, ZIP64, duplicates, links, unsafe names, unsupported metadata, gaps/trailing data, CRC/schema/hash mismatches and external-pin changes refused |
| Read-only boundary | Private file-tree hashes and unrelated synthetic hold unchanged per inspection; guarded live-state, process, provider, check and socket paths were not reached |
| HTTP | In-memory handler tests verified Host/session/Origin/request guards, binary responses, attachment type and no-store headers |
| Browser Python/Java | Both six-member previews and downloaded ZIPs verified against their displayed whole-archive digests |
| Browser stale evidence | A later synthetic accepted review invalidated the old pin; source drift refused export; both cleared the preview and disabled download |
| Browser controls | Run selection invalidated preview; keyboard Enter downloaded; bundle/readiness/comparison panels stayed mutually exclusive |
| Browser layout | At a 390-pixel viewport, client and scroll widths were both 375 pixels; desktop and final privacy wording inspected |
| Existing actual isolated acceptance | Python/Java checks, Java client, Git workspace, namespace, timeout/output and prerequisite checks passed separately |

Bundle fixtures are meaningful invented Python/Java before/after sources with
protected checks and directly saved accepted records. Their passing check rows
are invented evidence for archive logic; they were not produced by a new model
run or by executing those fixture checks. Bundle operations themselves executed
zero checks and made zero provider requests. The full runner's actual isolated
Python/Java execution checks are separate from these saved fixtures.

Browser testing used real handlers and bundle methods over invented private
workspaces. Deliberate changes occurred between read stages: an additional Java
acceptance record retained the original review, and a Python source comment
exercised source-drift refusal. Each inspection stage preserved file hashes; no
assertion of unchanged bytes spans those intentional changes. Owned previews
were stopped after inspection.

The browser initially saved the two invented ZIPs with broader local file
permissions than intended. Those exact hash-verified test files were restricted
to owner-only permissions without changing their bytes. The UI and README tell
users to choose a private download folder: the browser controls downloaded file
location and permissions. The ZIP is unencrypted; the application does not
guarantee privacy of a user's chosen download folder. No real bundle or private
operational history was used for browser testing or included in the public
source export.

## Saved acceptance and artifact checks

The loader reads saved evidence directly. It does not call normal
view/history/refresh/export, worker reconciliation, admission, hold association,
process-ownership lookup, checks, model preflight or provider-request paths.
An unrelated saved request hold remains unchanged and still blocks new work.
Saved uncertainty cannot be bundled. Active selected task/workspace child IDs
are refused using the in-memory registry without polling a process.

Current config and project-task raw fingerprints must match cached approved
definitions. Run task and project-task start pins must match exact raw task bytes
and the current project revision. Missing legacy pins are refused and never
reconstructed. Scope, edit permissions, checks, budgets and format must agree
with the current project; a goal override can differ. This stricter bundle gate
leaves old plain-patch export behavior intact.

The latest contiguous review must be accepted and bind exact canonical result
bytes and the saved patch. A single independent-final-check event must cover
exactly the declared checks with positive integer test counts, zero exit codes
and no timeout, output-limit or infrastructure failure. Booleans cannot stand in
for integer observations. Unsafe, malformed or incomplete evidence refuses the
operation rather than producing a partially qualified bundle.

Baseline and candidate hashes must agree with the task/result. Current selected
source must match the baseline; protected files must be unchanged. The loader
reconstructs the diff and compares its bytes/hashes with the saved accepted
patch. Export repeats the reads, rebuilds the deterministic archive and requires
the preview's whole-archive SHA-256. Nothing is cached or written to the run
directory. Sequential reads are not an atomic filesystem snapshot; the private
store and host filesystem still require trust and stability.

## Contents and verification limits

The six members are `manifest.json`, `changes.diff`, `review.json`, `checks.json`,
`README.txt` and `SHA256SUMS`. Summaries select file hashes and permissions, check
specifications/budgets, accepted status and recorded passing check observations.
They omit task goals, run/project/model identifiers, timestamps, review notes or
identity, prompts/responses, absolute paths, source copies and raw check output.
The patch, relative filenames and check specifications remain private source
information. Text is rendered without interpreting HTML.

Original task/result/review/final-event digests identify omitted bytes. They
cannot reconstruct or authenticate those records. Embedded checksums are
unsigned integrity evidence. A person who replaces all contents and checksums
can produce another internally consistent archive. A whole-archive digest from
an independently trusted preview detects that replacement; the verifier does
not establish who authored or approved an archive.

Every summary explicitly leaves these four areas **Not checked**:

- Check rerun.
- Provider completion.
- Source correctness.
- Git adoption.

The offline CLI reads only its named input, validates a bounded canonical ZIP and
prints a selected JSON summary. It follows no input-path symlinks, refuses
hardlinks/nonregular files, and checks bounded input size/stability. It never
extracts, applies a patch, runs a check, contacts a provider or changes
run/source/hold records. The expected SHA-256 option is optional for internal
integrity inspection and required for an externally pinned comparison.

## Bounds and retained limits

| Input or output | Bound |
| --- | --- |
| Complete archive | 2 MiB, exactly six stored members |
| Patch | 1 MiB, nonempty UTF-8 without NUL |
| JSON records/member payloads | 262,144 bytes each; metadata/latest review 32,768 bytes |
| Selected baseline/candidate/current-source snapshots | At most 32 files, 32,768 bytes/file and 131,072 bytes total for each snapshot |
| Reviews | At most 100 contiguous entries; latest record read |
| Events | At most 256 contiguous entries, 262,144 bytes/event and 8 MiB aggregate |
| Directory enumeration | At most 1,024 entries per bounded scan |
| Serialized preview | 65,536 bytes |
| Wait for earlier live UI update | Cancellable, ten seconds |

The verifier bounds and parses the six fixed local/central records before
reading payloads. It requires exact layout, names, sizes, CRC, permissions, dates,
method, schema and checksum bindings, then compares canonical archive bytes.
There is no input archive extraction or unbounded ZIP metadata inventory. Stored
members avoid decompression; this is a narrow application format rather than a
general archive recovery or extraction utility.

The original uncertain real-model Java outcome and hold/result hashes remain
unchanged. Cause and provider completion remain unknown. No retry, replay,
recovery, model eviction, deployment or new real-model qualification occurred.
Earlier observations and platform limits remain in
[version 0.8 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/0fcdc4f0b1980cc4ed13118cb381f5bc29f35e26/VALIDATION.md).
Acceptance used Python 3.12.7, isolated system Python 3.10.12, Git 2.34.1
and Temurin JDK 21.0.13+9 targeting Java 17 on Linux. No GitHub CI pass is claimed
for these local results. Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
