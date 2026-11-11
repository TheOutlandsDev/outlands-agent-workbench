# Version 0.15 validation

Offline qualification on one Linux host passed **652 unit methods in 28 suites**:
the prior 601, 26 snapshot-workspace engine methods and 25 controller/HTTP
methods. The full runner also passed actual isolated Python/Java imports into
new private Git worktrees, retained failed-check and owned-stop cases, and all
earlier acceptance probes. No model request was made. Real archives, workspaces,
snapshots, configured projects, output and runtime records remain private.

| Area | Observed result |
| --- | --- |
| Retained qualification | Prior 601 methods and acceptance probes passed |
| Snapshot-workspace engine | 26 methods passed |
| Controller and HTTP | 25 methods passed |
| Execution eligibility | Strict v0.13 archive plus baseline match, verified forward reconstruction and approved task hashes all required |
| Exact import | Baseline and reconstructed selected bytes, protected files, canonical patch and exported snapshot hashes matched |
| Independent Git | Only selected baseline files committed in a fresh private repository; imported edits remained uncommitted in its separate review worktree |
| Actual fresh checks | Fixed Python and Java checks passed in the new worktree; results stored separately from archive observations |
| Original evidence | Source/Git, unrelated dirty/untracked source, prior creation/recheck snapshots and builder holds preserved |
| Retained failure | An unsigned packet with plausible invented passing observations but wrong code failed actual new checks; failure and partial workspace retained |
| Owned stop | Separate slow invented fixture interrupted through its owned child; receipt and inputs retained without retry |
| Preview | One memory draft, five-minute expiry, exact pins and one-use consumption; replacement/expiry/cross-project/drift tested |
| Project guards | Cached config/task bytes, approved source, archive, request and worktree/Git rechecked before verification |
| Git controls | Generated control/config/index pins checked before post-check Git execution; changed controls or executable selected files refused |
| Lifecycle | Unknown PREPARING on restart stays unowned/unresolved; Stop never uses a saved PID; shutdown handles owned children |
| Admission | New active/failed/interrupted/invalid records block all execution paths; static readiness recognizes the new type and partial next-receipt marker |
| History bounds | 200 jobs, 2 MiB aggregate raw receipts and 262,144-byte reserved receipt capacity checked before creation |
| HTTP | Session/Host/Origin/fetch guards, unique MIME/length/hash framing, short body and transfer encoding tested |
| Browser | Explicit Python/Java preview/Create, fresh results, input invalidation, wrong digest and hold-blocked creation observed |
| Restart and teardown | Final server inspected retained history and preview without saved-byte changes; owned port closed |

## Evidence classes and observed outcomes

Unit setup uses invented Python/Java/mixed source, real private Git and saved
passing observations produced by fake fixture checkers. Unit worker tests use
explicit fake check functions. These distinguish schema/behavior coverage from
actual execution and establish no model competence or provider completion.

Full acceptance first creates actual checked Python/Java source snapshots through
older fixture workflows, then imports their v0.13 packets using the new worker.
Actual fixed isolated checks run again inside each new review worktree. Selected
bytes and hashes match the imported snapshot; baseline Git commits remain at
their recorded identities, and candidate diffs remain uncommitted. Original
source/Git, unrelated files and earlier saved evidence remain unchanged.

A deliberately wrong unsigned packet carries invented passing archive rows.
Its strict structural/hash eligibility is not evidence of correctness: actual
new checks fail. The FAILED job, archive, full checks and partial private
worktree are retained, further execution is blocked, and the consumed preview
cannot retry it. A separate slow fixture demonstrates owned Stop and retained
INTERRUPTED status. No old job is cleared, relabelled or automatically replayed.

The browser separately created two new workspaces from invented archive records.
Four actual Python tests and one actual Java main test passed. The interface
separated those fresh checks from recorded archive observations and exposed
historical results without source adoption. A separate synthetic hold added
after completion allowed preview while blocking Create. After restart neither
old child was owned or stoppable; preview still worked under that hold. Final
saved-byte hashes matched, prior records/source were preserved, and the owned
loopback server stopped. Actual Stop coverage comes from full acceptance, not
an unperformed browser action.

The initial focused integration run had two fixture-cleanup errors because tests
that explicitly closed a Manager were closed again by shared cleanup. Closure
tracking was corrected in the tests; the original log remains private. A
subsequent readiness regression also checks a VERIFIED receipt with a leftover
next-receipt marker. Final focused suites and the full qualification passed.
No failed operational or uncertain model request was rerun or relabelled.

## Preview, creation and retention boundaries

Preview accepts only the strict four-member snapshot-export format and verifies
it before task/source access. Exact task format/scope/permissions/check/budget
profiles must match. It requires both complete current baseline bytes and true
approved task-pin matches, then reconstructs the exact exported snapshot in
memory with protected-file, bounds, hash and canonical-diff checks. Cached
config/task guards are checked around preparation. Preview starts no Git,
checks, worker, admission reconciliation, hold read or persistent write. The
JDK availability display is a cached configuration fact, not a new probe.

Explicit Create rechecks current admission, configured Java prerequisites and
all project/archive/preview evidence. It reserves receipt capacity and consumes
the draft before persistent staging. Only a new private job is written. The
worker validates its distinct request/initial receipt, current config/project
mapping, original task/source, staged archive and preview binding before creating
any private Git workspace. Source data never becomes a Git control directory.

Only selected baseline files enter its fresh baseline repository. The imported
snapshot is written solely in a separate private review worktree, checked for
exact scope/permissions/Git state, then passed to the original fixed isolated
check runner. Full check evidence and clipped display rows remain distinct.
After checking, input/source/config/task/archive and worktree/Git guards are
revalidated. Unsafe generated Git-control drift is refused before post-check
Git commands can acquire altered configuration authority.

The worker transitions only its own initial receipt and checks its expected
raw bytes before final replacement. Early failure retains available identity
pins. Changed/partial next-receipt evidence is not overwritten or cleaned up.
Unknown, malformed, failed, interrupted and unfinished jobs remain blockers.
Runtime admission and static readiness both recognize these records; readiness
never reconciles a process or repairs evidence. Stop and shutdown use only
children owned by the current Manager, never persisted process identifiers.

## Type, bounds and remaining limits

This milestone uses `outlands-snapshot-workspace-v1` in a separate private history.
It does not fabricate v0.9 model/run metadata or convert this into an older bundle
workspace. Existing v0.12 manual recheck and v0.13 snapshot re-export interfaces
do not support this new type. Creation and fresh fixed checks are supported;
later edits need separate review and future versioned tooling.

| Input/output | Bound |
| --- | --- |
| Selected baseline/snapshot | 32 UTF-8 files, 32,768 bytes/file, 131,072 aggregate each |
| Private snapshot archive | 2,097,152 bytes |
| Task/config/receipt | 262,144 bytes each |
| Worker request / JSON action | 32,768 bytes each |
| Prepared summary / browser preview | 65,536 / 131,072 bytes |
| Full checks / clipped display | 2 MiB / 4,096 characters per check |
| Private history | 200 jobs and 2 MiB aggregate raw receipts |
| New creation reserve / history JSON | 262,144 / 262,144 bytes |
| Preview | One cached archive, five minutes, one-use Create |

The host/private store and configured projects must remain trusted and stable.
Sequential checks are not atomic multiwriter snapshots or proof that no
intermediate mutation occurred. An unsigned archive or a passing fixed check
is not authenticity, source correctness, adoption permission, model competence
or provider-completion proof. No commit of candidate changes or deployment is
performed. Original project and old result/hold bytes are not changed.

The original uncertain Java trial remains unqualified; its cause and provider
completion remain unknown and its two protected files retain their prior hashes.
No model request, recovery, retry, eviction, service/deployment change or license
assignment occurred. Earlier evidence remains in
[version 0.14 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/0d8d5f7147cf8c0dfeed6e4368a786e2e50b05b7/VALIDATION.md).
Qualification used Python 3.12.7, isolated Python 3.10.12, Git 2.34.1 and Temurin
JDK 21.0.13+9 targeting Java 17 on Linux. Local passes are not GitHub CI passes.
Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
