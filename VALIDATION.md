# Version 0.3 validation

Observed on 10 November 2026 on one Linux development host. Private project
sources, inputs, prompts, responses, patches, run histories and receipts remain
outside this public source package. The fresh Java model trial described below
ended uncertain.

| Area | Observed result |
| --- | --- |
| Engine unit suite | 42 methods passed |
| Workbench/controller/HTTP suite | 25 methods passed |
| Project setup and typed-check suite | 14 methods passed |
| Git workspace suite | 10 methods passed |
| Launcher suite | 9 methods passed |
| Java client compatibility | Compiled with `--release 17 -Xlint:all -Werror`; Python and compiled Java legacy scripted results matched |
| Python sandbox acceptance | Actual four-test baseline/final exercise, namespace probes, timeout/output limits and patch handling passed |
| Java sandbox acceptance | Failing baseline main became a passing main with six assertions; compilation diagnostics, namespace probes, timeout and output limits checked |
| Launcher acceptance | Actual prerequisite/isolation probe passed without inference; foreground launch and restart inspected |
| Git worker acceptance | Actual owned asynchronous worker applied an accepted patch, passed its four-test check, preserved original files/Git state, reaped the worker and refused to reapply on repeated request |
| Existing Python utility trial | Six local-model requests; six final tests passed; accepted patch download matched; separate Git workspace passed all six rechecks |
| Original Java utility trial | Stopped after one request with `PLAN_REQUIRED`; no model-directed read or edit occurred |
| Fresh Java utility trial | Plan and two file reads completed; fourth request ended without a durable response; `UNCERTAIN` hold retained, no edits |
| Browser persistence | Saved projects, accepted Python review/workspace and failed Java history survived restart |
| Responsive layout | Desktop and 390-pixel viewport inspected; document width matched viewport width |
| Static syntax | Python AST/JSON parsing and JavaScript syntax checks passed |

The current offline acceptance run passed all 100 unit methods and made no model
requests. Its coverage includes previous scope, review, uncertainty and Java
setup checks, plus prerequisite refusal, plan-tool advertisement, selected-file
Git snapshot creation, exact accepted-byte checks, original Git-state preservation,
failed-check retention, stop handling, idempotent workspace inspection and typed
send/header/body timeout outcomes with unchanged holds and no retries.
Java check counts describe protected main-program executions, not assertion counts.

## Existing-tool trials and preserved failure

The trials used private, byte-identical copies of existing offline resource
planning utilities, with new protected tests and fictional inputs. No defect was
injected. Each proposed feature adds projected remaining CPU and memory to an
existing admission report while preserving its original fields, decision and
exit status, including negative shortfalls. Six scenarios cover admission, CPU
shortfall, memory shortfall, a free-memory floor, stale observations and unhealthy
observations. These inputs do not qualify any live host or service.

**Python:** the six baseline tests failed because the new fields were absent.
The installed local `qwen3-coder:30b` model completed the task in six requests.
All six independent final tests passed. Review bound the exact result and patch
hashes, and the downloaded patch matched. The Git workspace applied that accepted
patch to a separate selected-file snapshot and passed all six checks again.
Original source, protected tests and the original project Git state remained
unchanged. Candidate changes remain uncommitted in the private worktree.

**Java:** its baseline compiled and failed the first assertion for the missing
fields. The model then requested `read_file` before `set_plan`. The existing guard
refused this with `PLAN_REQUIRED` after one response, before executing that
model-directed tool call. The run failed, no edits occurred, and no uncertainty
hold remains. Its result and response are retained unchanged. No automatic retry
was performed.

After that failure, provider requests were changed to advertise only `set_plan`
until its valid tool result is acknowledged, then offer the other three tools.
The existing guards and budgets remain enforced. That change passed the full
99-method offline acceptance run. The successful Python model trial predates this
tool-advertisement change; it does not qualify the final provider behavior.
The owner then approved one fresh Java trial, capped at 12 requests. Its first
three responses completed the plan and read both selected files. The fourth
request ended without a saved response. The engine recorded `EXECUTION_ERROR`
and retained a `REQUEST_UNSETTLED` hold, marking the run `UNCERTAIN` and blocking
new tasks. The elapsed time is consistent with the configured 120-second request
timeout, but the exception type was not retained, so that cause is not confirmed.
The provider's completion is unknown. No edit, final check, accepted patch or Git
workspace resulted from this trial. Both Java outcomes and the hold remain
unchanged; no further request, retry, hold clearing or model eviction followed.
There is no successful final-engine Java model result for this candidate.

The final offline-only diagnostic change records future `TimeoutError` failures
as `PROVIDER_SEND_TIMEOUT`, `PROVIDER_HEADER_TIMEOUT` or `PROVIDER_BODY_TIMEOUT`.
It retains the uncertainty hold and existing request limits. Three mocked timeout
phases verified the recorded reason, single request, closed client and blocked
subsequent admission. The full 100-method acceptance run passed. This change
does not establish the cause of the preserved Java outcome and has not received
a fresh real-model trial.

Both existing-tool sources, protected trial harnesses, proposed patches and
histories stay private. Public examples remain invented exercises. These small
trials are not a held-out benchmark, arbitrary-project competence result or
production qualification. Earlier v0.2 invented-fixture results remain historical
evidence in repository history; they are not fresh v0.3 model results.

## Practical limits

Only Linux and the named local model were exercised. Java remains a compatible
launch client for the Python engine, with a fixed Java compile/main check profile.
Maven/Gradle/JUnit dependency resolution, annotation processors, arbitrary shell
commands, package installation, remote hosting, automatic recovery and unattended
queues are not implemented. A selected check passing is evidence for that check,
not proof of universal correctness or resistance to adversarial code.

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
Temurin JDK 21.0.13+9 targeting Java 17. No GitHub CI run is claimed for these
local checks. See [origins and licensing](ORIGINS.md).
