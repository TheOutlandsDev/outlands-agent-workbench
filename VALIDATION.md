# Version 0.12 validation

Offline qualification on one Linux host passed **500 unit methods**: the prior
458, 21 workspace-recheck engine methods and 21 controller/HTTP methods. The
full runner also passed actual isolated Python/Java snapshot rechecks, preserved
creation/worktree/original Git state, retained failed attempts and owned-worker
interruption, plus all earlier acceptance probes. No model request was made.
Real workspaces, bundles, snapshots and runtime records remain private.

| Area | Observed result |
| --- | --- |
| Retained suites | All prior 458 methods passed |
| Recheck engine | 21 distinct methods passed |
| Controller and HTTP | 21 methods passed |
| Manual editable bytes | Invented Python/Java worktrees with UTF-8 comment additions inspected and rechecked |
| Original evidence | Creation receipts/checks, prior rechecks, manually edited worktrees and original source/Git bytes preserved |
| Fixed snapshots | Only selected pinned bytes copied; every configured check uses that same separate snapshot; no .git copied |
| Private Git identity | Pointers/backlink/commondir, config, refs, baseline index entries and loose object identities checked without Git execution |
| Index/cache handling | Version-2 index checksum, paths, modes, flags, stage and baseline blob IDs checked; known TREE/FSMN cache structures bounded; unknown formats refused |
| Protected and unsafe scope | Protected edits, executable bits, symlinks, hardlinks, extra files, bad encoding and size limits refused |
| Staged or committed state | Changed index entries, commits, branch/control pointers and unsupported Git state refused |
| Preview and history | Five-minute one-use preview, exact pins, replacement/expiry/cross-workspace guards and history-tip invalidation checked |
| Stale execution | Live-worktree, original source/config/task, snapshot and history changes during checks retain results without verification |
| Failure and interruption | Actual wrong manual edit fails fresh tests; separate owned stop retains interruption; no retry or cleanup |
| Admission | Hold allows read-only inspection but prevents execution; Java prerequisite and record/count/aggregate limits checked before persistent start |
| Restart and receipts | Unknown PREPARING attempts stay unowned/unresolved; malformed receipts block; early failures retain pinned identity |
| HTTP | Session/Host/Origin guards, exact JSON framing, short complete JSON, duplicate lengths and transfer encoding checked |
| Browser | Explicit Python/Java inspection and Run recheck, separate results, selection invalidation and hold-blocked execution observed |
| Final source and teardown | Fresh final server inspected retained fixture state without saved-byte changes; owned loopback port closed |

## Evidence classes and observed runs

Fixtures use invented sources, private bundles and configurations. Unit fixture
creation uses real private Git worktrees with fake passing check rows, clearly
labelled as invented evidence. Full acceptance instead creates the initial
Python/Java workspaces with actual isolated checks before making manual UTF-8
comment additions and running fresh snapshot checks. Those results remain
separate from the creation records; none is a model-generated refinement.

Actual acceptance confirms selected snapshot hashes equal the reviewed current
bytes, full check-evidence hashes match, earlier result files remain unchanged,
and no Git directory or unrelated file enters the snapshot. A later intentionally
wrong editable expression fails actual Python tests. Its failed result and
snapshot are retained, block execution and cannot reuse the consumed preview.
A separate hold-free fixture verifies owned stop and retained interruption.
Original Git HEAD/status/file hashes, existing unrelated dirty state and private
sentinels remain unchanged per operation. The synthetic builder holds remain.

The browser used invented creation records and real snapshot reruns: four Python
tests and one Java main check passed. Each inspection showed one changed editable
file and unchanged protected tests. Old creation results stayed historical, with
separate recheck IDs and snapshot pins. An invented hold allowed inspection while
Run recheck was disabled. Final fresh-server inspection preserved all saved bytes,
creation records and worktree files, and the owned server was stopped.

Initial browser inspection and the first focused engine run refused valid Git
FSMN cache metadata. The reader was corrected to validate the known bounded
cache structure while retaining exact baseline-entry checks; the existing index
was never rewritten to hide the issue. One corruption test also needed write
permission on its own synthetic read-only Git object before deliberately changing
it. Initial failures remain recorded privately. Explicit cache regression cases,
final focused suites and full qualification passed. No failed operational or
uncertain model request was replayed or relabelled.

## Inspection and execution boundaries

Inspection reads a valid VERIFIED imported-bundle creation, verifies its original
request/task/config/bundle/check pins, and compares selected current worktree
bytes with its recorded candidate. Only editable bytes may differ. Original
project pins, protected bytes and private Git baseline semantics must remain
valid. There is no Git subprocess, project check, provider call, hold read/write,
process reconciliation or persistent write in this inspection.

Version 0.11 did not record historical raw Git control/index hashes. The new
reader validates the expected private relationship and current baseline index,
then pins current metadata bytes for this recheck. It does not invent historical
observations. Loose commit/tree/blob objects are bounded, decompressed and checked
against their identities and the regenerated selected baseline. Known cache data
has no execution authority and cannot replace baseline-entry validation.

An explicit Start binds the inspection and current global recheck-history digest,
rechecks admission and Java prerequisites, consumes the preview and creates a new
private attempt. The worker inspects again, copies selected bytes into one new
snapshot, runs only the original configured fixed checks, and rechecks the
snapshot, owner worktree, creation/project pins and prior history afterward.
Drift or nonpassing checks retain evidence and refuse VERIFIED status.

Each attempt has a new ID, request, initial receipt, snapshot and result. Only its
own preparing receipt transitions to a final state. Earlier creation/attempt
records and worktree bytes are never overwritten. Failures, interruptions and
unknown unfinished or damaged evidence remain blockers. No UI action retries,
clears holds, deletes evidence, adopts source or commits a candidate. Stop uses
only a child owned by the current server. Restart never grants PID-based ownership.

## Bounds and limitations

| Input/output | Bound |
| --- | --- |
| Selected snapshot | 32 UTF-8 files, 32,768 bytes/file, 131,072 total |
| Snapshot inventory | 512 file/directory entries |
| Task/config/creation and attempt receipt | 262,144 bytes each |
| Private bundle | Existing strict format, at most 2 MiB |
| Git index | Version 2, at most 262,144 bytes; known TREE/FSMN caches only |
| Loose Git object | 262,144 compressed/decompressed bytes each |
| Inspection / preview JSON | 65,536 / 131,072 bytes |
| Preview | One memory draft, five-minute validity, one-use start |
| History | 200 attempts and 2 MiB aggregate raw receipt bytes |
| New-attempt admission | Reserves 262,144 receipt bytes before any persistent start |
| History response | 262,144 bytes; selected-workspace rows with global history pin |
| Receipt check display | 4,096 characters/check; display clipping distinct from execution output limits |
| Full private check evidence | At most 2 MiB |
| JSON request | 32,768 bytes, exact declared length |

This supports the original simple private Git layout, version-2 index and loose
objects created by the workbench. Packed/rewritten or other unsupported Git state
is refused. The host, config and private store remain trusted and stable.
Sequential observations are not atomic snapshots, locks or proof that no
intermediate change occurred. A passing receipt describes its checked snapshot
at that time; later edits need new checks. Hashes establish integrity, not
provenance, authenticity, general source correctness or adoption permission.

The original uncertain Java result and hold retain their prior hashes. Its cause
and provider completion remain unknown. No inference, recovery, retry, model
eviction, deployment or license assignment occurred. Earlier evidence remains in
[version 0.11 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/5c215da44e285924a101f9d4e097783ec5da293e/VALIDATION.md).
Qualification used Python 3.12.7, isolated Python 3.10.12, Git 2.34.1 and Temurin
JDK 21.0.13+9 targeting Java 17 on Linux. Local passes are not GitHub CI passes.
Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
