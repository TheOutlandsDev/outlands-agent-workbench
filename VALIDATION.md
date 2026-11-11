# Version 0.4 validation

Observed on 10 November 2026 (America/New_York) on one Linux development host.
This milestone was tested offline with invented inputs, scripted exercises,
mocked transports and an owned simulated waiting provider. It made no real
model requests. Private configs, histories, prompts, responses and review
receipts remain outside this public package.

| Area | Observed result |
| --- | --- |
| Engine unit suite | 55 methods passed |
| Workbench/controller/HTTP suite | 25 methods passed |
| Project setup and typed-check suite | 14 methods passed |
| Git workspace suite | 10 methods passed |
| Launcher suite | 9 methods passed |
| Run Diagnostics suite | 15 methods passed |
| Java client compatibility | Compiled with `--release 17 -Xlint:all -Werror`; Python and compiled Java scripted results matched |
| Python/Java isolated checks | Baseline/final exercises, namespace probes, diagnostics, timeout and output limits passed |
| Git/launcher integration | Actual owned Git worker, accepted-patch recheck, original-state preservation and prerequisite probe passed |
| Browser diagnostics | Owned simulated request shown as active; stopping its worker preserved an uncertain result/hold and blocked new tasks |
| Legacy and completed runs | Missing measurements stayed Not recorded; completed scripted turns retained recorded timing and no-inference labeling |
| Present unassociated hold | Shown as present and blocking, rather than absent |
| Keyboard and layout | Diagnostics/Diff arrow navigation passed; desktop and 390-pixel viewport inspected, document width matched client width |
| Persistence | Recorded interruption and blocked admission survived browser reload |

All **128 unit methods** passed. The offline integration runner made zero model
requests. New transport tests cover send/header/body timeouts, connection,
protocol and operating-system errors, malformed responses, interruption,
unknown refusal text, invalid metrics and failures while writing evidence.
They check a single attempt, closed clients, finite sanitized metadata, durable
response ordering and retained uncertainty holds. An error while recording a
finish does not cause a retry or release an unsettled hold.

Controller tests distinguish an owned live worker from an unknown process after
restart. They also cover corrupt request events, missing finish records,
response claims without durable response evidence, legacy history, malformed
holds, finite summary bounds and exclusion of raw private text. Inspecting a
run does not rewrite its result or clear its hold.

## Evidence and qualification boundaries

New diagnostics record UTC start time, monotonic elapsed milliseconds, the
configured request timeout, actual serialized Ollama payload bytes when known,
recorded phase and fixed error category. Only six optional provider integer
counters are retained; booleans, strings, floats, negative values and values
outside the safe integer range are excluded. No raw exception text, source,
prompt, path or model name is copied into these new diagnostic fields. Existing
private run evidence remains private.

The request/response wire settings, file scope, checks, budgets, plan requirement,
review bindings and no-retry behavior remain unchanged. Viewing diagnostics does
not contact a provider. A saved response is distinct from a successful task.
An active request may have no recorded finish yet; older missing measurements
are not reconstructed. Summaries are limited to 16 turns and 256 events, with
an explicit inspection note if that event limit is exceeded.

The browser exercise used an invented waiting provider in an owned local child,
with no HTTP/model call. Stop task interrupted that child; the engine retained
its result, finish evidence and request hold. This exercises the local lifecycle,
not proof that stopping a real HTTP client stops provider inference.

The earlier real-model Java trial from version 0.3 remains **UNCERTAIN**. Its
fourth request had no durable response; its generic error and 120-second timing
do not establish the precise cause or provider completion. Both earlier Java
outcomes and the original hold were preserved unchanged during this milestone.
No new Java or Python real-model qualification is claimed. The final version 0.4
engine has offline acceptance only. Historical model results are recorded in
[version 0.3 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/d6d115bee1e94a1bede0288e418e2cc243badf38/VALIDATION.md).

## Practical limits

Offline acceptance used Linux; historical model observations apply only to the
named model in the earlier records. Java remains a compatible
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
