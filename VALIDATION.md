# Version 0.5 validation

Observed on 10 November 2026 (America/New_York) on one Linux development host.
Qualification was offline only: invented Python/Java text fixtures, deterministic
navigation exercises and mocked HTTP transports. No real model request was sent.
Private project data, runtime histories and review receipts remain excluded.

| Area | Observed result |
| --- | --- |
| Engine unit suite | 55 methods passed |
| Workbench/controller/HTTP suite | 25 methods passed |
| Setup / Git workspace / launcher suites | 14 / 10 / 9 methods passed |
| Run Diagnostics suite | 15 methods passed |
| Pure project context suite | 31 methods passed |
| Context/request-size integration suite | 14 methods passed |
| Existing offline integration | Actual isolated Python/Java checks, Java-client parity, namespace/time/output limits, Git worker and prerequisites passed |
| Browser Context | Scoped search hits, Unicode text, grouped file hashes, numbered focused reads and explicit truncation inspected |
| Browser size refusal | Initial refusal showed zero attempted requests and no new hold; a later refusal retained its prior attempted request and recorded response |
| Legacy and keyboard behavior | Empty historical context remained empty; keyboard tab navigation worked |
| Persistence / layout | Saved context survived reload; desktop and 390-pixel viewport inspected with no horizontal page overflow |

All **173 unit methods** passed in the final offline acceptance run. Python AST,
JSON parsing and JavaScript syntax checks also passed. The tests cover exact
literal matching and stable order, case sensitivity, Unicode columns and clipping,
LF/CRLF/CR, empty files, no-final-newline inputs, per-line/result limits, exact
serialized JSON sizes, whole-file hashes and input immutability. Supplied source
is treated as text and is not executed by the context helpers.

Integration checks enforce planning, declared-file scope, symlink refusal,
protected-test immutability and stale edit hashes. A deterministic task searched
for the relevant expression, derived a focused read from the actual hit, made a
small hash-bound edit and passed the existing final checks without altering its
original source. This is an offline exercise, not a model competence benchmark.

## Request-size and privacy evidence

The full Ollama JSON request body is capped at 131,072 bytes. Boundary tests
verified that an exactly sized body can be sent through a mocked transport, and
one byte over is refused before opening the chat connection or creating a new
request hold. A growing valid snapshot history reached the same guard after five
prior mocked attempts; the refused sixth candidate was not counted as a sent
attempt. Earlier response evidence and any pre-existing hold remained unchanged.
The existing CLI loaded-model GET preflight remains separate and can run earlier.
No claim of zero provider GETs, tokenizer-based limits or universal model context
fitness is made.

`request_refused` stores bounded size/ceiling fields and a fixed reason, without
the candidate payload or model name. The Context view intentionally shows private
selected source; unknown extra tool-result fields and unselected paths are
excluded from that view. Excerpts use text rendering, with no HTML interpretation
or source execution. Search/read results stay within 8,192 serialized JSON bytes;
search returns at most 20 matching lines and each focused read requests at most
80 lines. The view retains only eight recent context results. Limits and omitted
content are explicit.

The original uncertain Java run and its hold were preserved byte-for-byte. Its
cause and provider completion remain unknown. No replay, recovery, hold clearing,
model eviction or new real-model qualification occurred. The final v0.5 engine
has offline acceptance only. Prior limitations and model observations remain in
[version 0.4 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/ccf3184d2a74eb2c6a9f7c193c08125831e05248/VALIDATION.md).

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
