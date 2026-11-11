# Version 0.6 validation

Observed on 10 November 2026 (America/New_York) on one Linux development host.
The final offline acceptance run passed all **218 unit methods**: the prior 173,
17 revision-helper methods and 28 refresh/controller methods. Qualification used
invented fixtures, actual isolated checks, deterministic exercises and mocked
transports. Version 0.6 sent **zero real model requests**. Private source,
revision records, runtime histories and review receipts remain excluded.

| Area | Observed result |
| --- | --- |
| Engine unit suite | 55 methods passed |
| Workbench/controller/HTTP suite | 25 methods passed |
| Setup / Git workspace / launcher suites | 14 / 10 / 9 methods passed |
| Run Diagnostics suite | 15 methods passed |
| Pure project context suite | 31 methods passed |
| Context/request-size integration suite | 14 methods passed |
| Pure project revision helpers | 17 methods passed |
| Refresh/controller/HTTP integration | 28 methods passed |
| Invented Python refresh fixture | Actual isolated baseline: 6 tests, 2 failures; after a manual fixture correction and reviewed hash revision: 6 passed |
| Invented Java refresh fixture | Actual isolated baseline: protected main failed; after a manual fixture correction and reviewed hash revision: protected main passed, reporting 6 assertions |
| Revision persistence | Both fixtures saved a goal-only second revision; their two-revision chains survived manager restart |
| Stale refresh save | Later source change refused the save and preserved the existing config; no inference or hold was created |
| Existing offline integration | Python/Java client parity, actual isolated checks, namespace/time/output limits, Git worker, accepted-artifact rechecks and prerequisites passed |
| Python browser refresh | Legacy empty history, exact hash preview, stale-source refusal, fresh preview/save, no-op refusal and goal-only revision passed |
| Java browser refresh | Exact review and save passed; Java JDK configuration remained unchanged |
| Browser persistence / invalidation | Reload retained the new default goal and saved history: two Python revisions and one Java revision; goal edits invalidated the draft and the old run remained available |
| Browser admission | A separate synthetic hold blocked refresh controls while revision history remained readable |
| Mobile layout | At a 390-pixel viewport, client and scroll widths were both 375 pixels; no horizontal page overflow |

The Java fixture result counts one executed protected main, not six separate
test methods. The acceptance script made the small source corrections itself;
these observations do not demonstrate model competence. Selected scope, edit
permissions, fixed checks, budgets, protected fixture bytes and earlier task
definitions remained unchanged through those refreshes. The owned browser-preview
process was stopped after inspection. No model calls were used for browser QA.

## Reviewed refresh behavior

Refresh previews expose configured/current hashes, byte sizes and the
editable/protected status of every selected file. Changes to protected-file
hashes are visible without making those files editable. Only the default goal
and hash values of already selected paths can change. A goal-only revision is
supported; an unchanged goal and unchanged hashes are refused as a no-op.
The Java JDK configuration remains unchanged.

The parent task fingerprint hashes its exact raw file bytes, including JSON
formatting. The candidate fingerprint hashes the exact bytes prepared for save.
Tests cover independent candidate construction, fixed scope/checks/budgets,
guarded file reads, UTF-8 and snapshot bounds, goal-only/no-op behavior, expiring
five-minute drafts, exact task/config drift, stale source and altered linked
revision records. Active or unresolved task/workspace state blocks preview/save;
malformed workspace admission records also refuse new work. Viewing revision
history does not clear those blocks.

Saving re-reads the source, current task and config before committing the new
pointer. New parent/task/receipt files are prepared outside the public source
tree, and the atomic config-pointer replacement happens last. Tests exercise
refusals and interruption before that commit boundary. Prepared files are
retained and do not appear in committed history unless reachable through the
current pointer. The linked history returns the latest 20 revisions, reports
truncation and caps a project's saved chain at 64 revisions.

These are sequential file rechecks on a trusted, stable filesystem. They are
not a multiwriter transaction, snapshot service or universal atomicity guarantee
across source, task, receipt and config files. There is no rollback, request
replay, hold clearing or scope expansion. Old task definitions and run pins are
preserved. A refresh does not revalidate an old export or renew an old review;
their original evidence and later use checks still apply.

## Retained context and request-size safeguards

The offline acceptance retains the bounded literal search and focused-read
checks: declared-file scope, stable order, Unicode columns and clipping,
LF/CRLF/CR, empty files, no-final-newline inputs, exact serialized sizes,
whole-file hashes and input immutability. Context helpers treat selected source
as text and do not execute it. Search returns at most 20 matching lines; a
focused read requests at most 80 lines. Each result stays within 8,192 serialized
JSON bytes, and the read-only Context view retains eight recent results with
explicit omissions and text-only rendering.

The full Ollama chat body remains capped at 131,072 serialized bytes. Mocked
boundary tests accept an exactly sized candidate and refuse one byte over before
that chat request is sent or a new hold is created. Later refusals preserve prior
attempt counts and response evidence. The separate CLI loaded-model GET
preflight can occur earlier. This makes no claim of zero provider GETs,
tokenizer-based context qualification or universal model context fitness.

The original uncertain Java run and its hold/result bytes remain unchanged.
Its cause and provider completion remain unknown. No replay, recovery, hold
clearing, model eviction or new real-model qualification occurred. Historical
browser/model observations and earlier limits remain in
[version 0.5 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/d5906bd03e6d5f99cc35c04232bf5aec339c03ae/VALIDATION.md).

## Practical limits

Offline acceptance used Linux. Historical model observations apply only to the
named model in the earlier records. Java remains a compatible launch client for
the Python engine, with a fixed Java compile/main check profile. Maven/Gradle/JUnit
dependency resolution, annotation processors, arbitrary shell commands, package
installation, remote hosting, automatic recovery and unattended queues are not
implemented. Passing a selected check is evidence for that check, not universal
correctness or resistance to adversarial code.

The Git workspace is an independent selected-file repository. It does not import
the original project's history, remotes, hooks or attributes. A verified receipt
records creation-time checks; later workspace edits require new checks and review.
The app leaves candidate changes uncommitted and does not merge or push them.
Failed or interrupted workspace operations retain files/logs and block new tasks
for inspection.

The namespace boundary shares the kernel and read-only system/JDK files. It has
no cgroup CPU/process-count quotas. Python checks use a 1 GiB address-space limit;
Java checks use 2 GiB address space and 128 MiB heap per compiler/runtime JVM.
Each check has a ten-second wall-clock timeout and bounded output. Input/config
parents must be trusted and stable; this is not a hardened multiuser service.
The launcher checks prerequisites without installing software or changing models.
A loopback model endpoint alone does not attest where inference executes.

Acceptance used Python 3.12.7, isolated system Python 3.10.12, Git 2.34.1 and
Temurin JDK 21.0.13+9 targeting Java 17. No GitHub CI run is claimed for these local
checks. Licensing remains **UNASSIGNED**; see [origins and licensing](ORIGINS.md).
