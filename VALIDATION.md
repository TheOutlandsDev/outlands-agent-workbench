# Version 0.11 validation

Offline qualification on one Linux host passed **458 unit methods**: the prior
416, 24 distinct bundle/workspace engine methods and 18 controller/HTTP methods.
The full runner also passed actual isolated Python/Java worktree checks,
Java-client parity, original Git/source preservation, failed-check retention,
owned-worker interruption and all retained acceptance probes. No real-model
request was made. Real bundles and runtime records remain private.

| Area | Observed result |
| --- | --- |
| Retained suites | All prior 416 methods passed |
| Workspace engine | 24 distinct methods passed |
| Controller and HTTP | 18 methods passed |
| Canonical reconstruction | Exact UTF-8, LF/CRLF, missing final LF, multiple hunks/files, insertions and deletions checked |
| Rejected patch content | Extra metadata, binary/rename/mode syntax, escaped paths, wrong context/coordinates/markers and noncanonical context refused |
| Approved baseline | Fresh baseline, configured task pins, protected bytes and every candidate hash required |
| Stale and unsafe inputs | Config/task/source drift, archive/request changes, unsafe files and a repeated-read race refused with finite errors |
| Memory-only preview | No files, discovery, Git/check execution, process reconciliation, provider access or hold changes |
| Creation guards | One preview, five-minute expiry, exact pins, explicit Create, JDK preflight and admission enforced |
| Actual Python/Java reruns | Passing candidates checked in separate private Git review worktrees |
| Original Git state | Entire original source/Git file hashes, HEAD and status retained, including an outside-scope dirty edit and untracked private sentinel |
| Private Git state | Selected files only; protected hashes, baseline HEAD/branch and exact uncommitted candidate diff checked |
| Failure and stop | Wrong candidate failed actual checks and retained evidence; separate owned worker stopped with retained interruption; no retry |
| Receipts | Early failure retains staged pins; full private check evidence and bounded displays retained; invalid/nonpassing observations cannot verify |
| Restart and inventory | Unknown PREPARING jobs remain unowned/unresolved; malformed and over-limit histories fail closed |
| HTTP | Session/Host/Origin guards, exact ZIP and new JSON body lengths, media type, duplicate headers, transfer encoding and digest failures checked |
| Browser | Explicit Python/Java preview/Create/check results, input invalidation, keyboard Enter digest refusal, reset and private history observed |
| Final browser source | Under an invented hold, preview available and Create disabled; saved bytes and sources unchanged; owned preview stopped |

## Evidence classes

Fixtures contain invented Python/Java sources and synthetic v0.9-format bundles.
Their saved accepted/check rows are fixture evidence. Fresh isolated reruns are
separate execution evidence: a bundle with invented passing records but an
incorrect candidate fails the actual checks. Neither is a model-generated patch
or real-model qualification.

Actual acceptance starts with original Git repositories containing selected
baseline files, a tracked outside-scope file with an existing dirty edit and an
untracked private sentinel. Full original source/Git bytes, HEAD and status match
before and after. Only selected files enter the new worktrees. Candidate changes
remain uncommitted, with no staged candidate or new HEAD. Checks execute in the
existing networkless, read-only selected-file namespaces. Passing checks do not
establish general correctness or authorize adoption.

The browser used only invented private archives. Choosing inputs did not create
a job. Explicit Python creation reported four passing tests; Java reported one
passing main check. Receipts showed original-source application false and
uncommitted candidates. A wrong trusted digest entered with keyboard Enter
refused preview. Close/reopen cleared inputs. Under a deliberately added
synthetic hold, read-only preview worked while Create stayed disabled. A fresh
final server inspected that retained state without changing saved bytes. Source
closure hashes matched and the owned port was closed. No operational project or
real archive was used.

During focused development, one observer test refreshed its own invented Git
index with git status before comparing index bytes. Its assertion order was
corrected to observe bytes immediately after the worker, then inspect Git state.
An inherited class also duplicated preparation methods; final counts include
only distinct methods. The initial failed attempt is retained privately. Final
focused and full acceptance passed. Review also closed early-failure receipt pin
loss, interrupted-status consistency, repeated-read error mapping and exact new
JSON-length gaps before final qualification.

## Action and privacy boundaries

Preview verifies the existing archive format, configured profile, current
approved baseline and reconstructed candidate hashes. It retains one bounded
archive in memory and issues an expiring one-use preview. It performs no Git
command, check or provider request and does not read/reconcile normal task/hold
state. A new preview attempt invalidates the old draft. Its pin binds project,
archive, task, config and the prepared file/check summary. Unsigned hashes prove
integrity, not authenticity or rights.

Explicit Create rechecks current pins, source and admission before persisting a
private job. The worker repeats those checks, creates a selected-file baseline
repository and separate review worktree, installs verified candidate bytes and
runs configured fixed checks. Archive commands, hooks, filters, extraction paths
and patch metadata gain no authority. Git never runs in the original project.
Source/config/task pins and private inventory, hashes, HEAD, branch and staged
diff are checked again after execution.

Failed/interrupted jobs retain requests, archives, tasks, partial work, receipts
and available checks. They block further execution. Preview cannot clear a hold,
retry, resume, delete evidence, commit or apply to original source. Stop uses
only current owned child handles. Saved PIDs grant no ownership. Unknown
unfinished jobs remain unresolved after restart. History/status reconcile only
owned exited workspace workers, without establishing provider completion.

## Bounds and limits

| Input/output | Bound |
| --- | --- |
| Private ZIP | 1 byte to 2 MiB; existing strict six-member format |
| Config/task | 262,144 bytes each; exact cached SHA-256 |
| Selected source/candidate | 32 files, 32,768 bytes/file, 131,072 total |
| Changed text | UTF-8 LF/CRLF or unterminated last line; bare CR and ambiguous line separators refused |
| Prepared summary / preview response | 65,536 / 131,072 bytes |
| Preview | One memory draft, five-minute validity |
| Create/Stop JSON | 32,768 bytes, exact declared length |
| History | 200 records; damaged/over-limit evidence blocks execution |
| Private selected inventory | 512 file/directory entries |
| Receipt / list response | 262,144 bytes each |
| Receipt check display | 4,096 characters/check; clipping distinct from execution output limits |
| Full check evidence | Private checks.json, at most 2 MiB |

Host, config, selected projects and private store remain trusted and stable.
Sequential checks are not atomic snapshots or multiwriter transactions. Saved
VERIFIED means configured checks passed when created; later edits need new
checks/review. Linux namespace behavior was checked on one host, not every
platform or project. No new real-model qualification, deployment, inference,
source adoption or license assignment occurred.

The original uncertain Java result and hold retain their exact prior hashes.
Cause/provider completion remain unknown. No recovery, replay, retry or model
eviction occurred. Earlier limits remain documented in
[version 0.10 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/54e494b82d3905aaaa5f0dfded28d67884986c61/VALIDATION.md).
Acceptance used Python 3.12.7, isolated Python 3.10.12, Git 2.34.1 and Temurin JDK
21.0.13+9 targeting Java 17 on Linux. Local passes are not GitHub CI passes.
Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
