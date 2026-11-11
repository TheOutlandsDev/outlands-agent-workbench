# Version 0.8 validation

Observed on 10 November 2026 (America/New_York) on one Linux development host.
Final offline acceptance run 03 passed all **328 unit methods**:
the prior 270, 30 pure readiness methods and 28 readiness/controller/HTTP methods.
Version 0.8 qualification uses invented configured Python/Java projects and
saved admission records. It sent **zero real model requests**. Private source,
configs, histories, holds, revision records and review receipts remain excluded
from the public source package.

| Area | Observed result |
| --- | --- |
| Retained unit suites | All prior 270 methods passed |
| Pure readiness / readiness integration | 30 / 28 methods passed |
| Python/Java readiness fixtures | Static observations passed with required executables present; Java presence stubs were not executed |
| Source and prerequisite blockers | Java source drift required refresh; missing configured javac blocked; optional Git absence did not block |
| Fingerprints and saved admission | Exact raw config/task drift skipped source reads; saved active, recovery, uncertain, workspace and hold blockers remained observed |
| Read-only boundary | Source/private record hashes unchanged per inspection; guarded live-state, process, check and provider paths were not reached |
| Bounds and unsafe files | Source limits, missing/binary/UTF-8 input, symlinks/hardlinks, unsafe ancestors and partial admission inventories checked |
| Existing actual isolated integration | Python/Java checks and client parity, Git worker, namespace/time/output limits, prerequisite probes and reviewed refresh fixtures passed |
| Browser readiness | Python static pass, Java source-refresh status, config-drift inspection with source Not checked, and saved-hold blocks on both projects inspected |
| Browser controls | Project selector stayed usable under the synthetic hold; selection invalidated old results; keyboard selection/Enter worked; readiness and comparison remained mutually exclusive |
| Browser layout / immutability | At a 390-pixel viewport, client/scroll widths were both 375 pixels; file hashes remained unchanged within each read stage; owned preview stopped |

The first offline acceptance attempt failed at the new synthetic hold fixture.
That fixture used `reason` where the hold schema requires `state`; readiness
correctly reported **Needs inspection**, while the fixture expected **Blocked**.
The failed attempt was retained. Correcting the invented fixture produced the
passing run 02 with 324 methods; final post-review run 03 passed all 328 methods.
This was an offline fixture correction, with no provider request, replay,
recovery or change to the original uncertain Java run.

The readiness acceptance helper writes invented Python/Java files and
executable-presence stubs. It observes both static passes, source drift, a missing
Java compiler, a separate synthetic request hold and config drift. Each
inspection asserts unchanged private file hashes. Readiness executes zero
checks and sends zero model requests. The full runner separately repeats the
existing actual isolated Python/Java checks; presence observations do not
substitute for those execution results. One executed Java protected main is one
check result, regardless of its assertion count.

The browser preview used real readiness methods and HTTP handlers over isolated
invented projects. The hold and config-drift scenarios were deliberate fixture
changes between read stages; each read stage preserved its file hashes. The
project selector remained available while Run was blocked. These checks qualify
the observed readiness flows on this host, not deployment, all runtime behavior
or real-model acceptance. The preview was stopped after inspection.

## Static readiness evidence

`GET /api/project-readiness/PROJECT_ID` observes one already configured project.
It uses cached approved paths and definitions, without discovering repository
files or adopting external config/task changes. Expected and observed
fingerprints hash exact raw bytes, including JSON formatting. If either config
or task evidence changed or could not be read safely, source rows remain
`NOT_CHECKED`. Missing or unavailable sizes and hashes stay Unknown.

The report selects relative paths, editable/protected labels, hash/size rows,
fixed check specifications and request budgets from the approved task. It omits
absolute config/source/JDK/hold paths, source contents, check output, credentials,
prompts/responses, raw exceptions and unknown fields. Those selected paths,
goals and check specifications are still private project information. The UI
renders text without interpreting HTML.

Four advisory outcomes are available:

- **Static checks passed:** the required static observations passed at the
  displayed time. This does not authorize Run, qualify a provider or sandbox,
  or establish source correctness.
- **Source refresh required:** selected source hashes changed and no other issue
  was observed.
- **Blocked:** source safety/size, a required executable, saved task/workspace
  state or a valid present hold blocks new work.
- **Needs inspection:** config/task drift, invalid definitions, damaged or
  unavailable saved evidence, malformed holds or partial admission inventory
  prevents a static pass. New work remains blocked.

Inspection can become stale as files, executable presence or saved admission
evidence change. Starting a task still rechecks its authoritative guards.
Readiness adds no Run, source edit, refresh, retry, hold-clearing or recovery
action.

## Presence and saved admission observations

Prerequisite inspection checks regular/executable presence only. Python,
Bubblewrap and `prlimit` are required for checks. Git is optional for later Git
workspace creation. A JDK is required only for Java check profiles, with `java`
and `javac` present. No executable, version command or project check is run.
Trusted system executable symlinks may resolve for this presence observation;
it is not a binary identity or version attestation.

Every report explicitly leaves these eight areas **Not checked**:

- Provider availability.
- Check execution.
- Isolation capability.
- Java version.
- Model context fit.
- Process ownership.
- Workspace freshness.
- Source correctness.

Saved admission inspection does not call normal history, admission, worker
reconciliation, process-ownership lookup, check execution, provider preflight or
model-request paths. Saved `RUNNING`, `STOP_REQUESTED` and recovery states remain
as recorded. Saved uncertainty blocks even without an observed hold. Known
terminal failures alone do not block. Workspace receipts are inspected as saved
records without running Git, checks or freshness validation.

A valid present hold blocks new work. A malformed, unsafe or unreadable hold
requires inspection and remains blocked. Unknown/damaged metadata, unfinished
records or an incomplete admission inventory also require inspection. Neither
inspection nor viewing its result changes a hold, status, task, source file or
saved record.

## Read bounds and UI behavior

Inspection reads only the already selected scope: at most 32 files, each under a
32,768-byte file ceiling. Their combined source eligibility limit is 131,072
bytes. The inspector can read the bounded files to report all available sizes;
that total eligibility limit is not a 128-KiB physical I/O budget. When every
size is available, their sum remains visible even above the limit and blocks the
task. Otherwise the total remains Unknown. Config/task fingerprint reads have a
262,144-byte ceiling; they do not normalize or adopt observed contents.

Saved admission examines at most 200 matching job JSON/unfinished entries, with
directory enumeration bounded to 1,024 entries. Job/workspace records have a
32,768-byte ceiling, holds a 4,096-byte ceiling, and admission reads share a
2-MiB aggregate budget. Truncation, a read limit or unavailable evidence cannot
produce a static pass. The complete serialized readiness report is capped at
131,072 bytes and uses finite statuses/reasons.

Source/config/task and admission readers open path components without following
symlinks, retain regular-file/hardlink and UTF-8/binary guards, and expose no
unsafe target contents. Configured roots and the host filesystem still require
trust and stability. Sequential reads are not an atomic filesystem snapshot or
multiwriter transaction.

Normal polling pauses while readiness is opening or open, with a cancellable
ten-second wait for an earlier live update. Readiness and comparison are mutually
exclusive. Changing the selected project discards its previous report, and late
responses are ignored. Closing returns to normal polling/reconciliation. That
pause does not stop or resolve a provider request.

## Retained safeguards and historical limits

The acceptance runner retains selected-file search/read bounds, stale edit
hashes, protected tests, independent final checks, request-size refusals,
reviewed refreshes and saved-run comparison tests. Comparison remains saved
evidence rather than model ranking. Readiness does not predict model context fit
or replace the serialized chat-body guard. Refresh scope, edit permissions,
checks, budgets and Java JDK configuration remain fixed. Old task definitions,
run pins, failed records and interrupted preparation files remain preserved.

The original real uncertain Java run and its hold/result hashes remain
unchanged. Its cause and provider completion remain unknown. No retry, replay,
recovery, model eviction or new real-model qualification occurred. Prior
comparison, refresh, browser and model observations remain in
[version 0.7 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/d08ec0194fec7421e520cbab48827c4c72439ca2/VALIDATION.md).

Offline acceptance used Linux with Python 3.12.7, isolated system Python
3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting Java 17. Existing sandbox,
Git-workspace and platform limits remain as documented in the pinned validation.
Readiness does not qualify deployment or a real model. No GitHub CI run is
claimed for these local checks. Licensing remains **UNASSIGNED**; see
[origins and licensing](ORIGINS.md).
