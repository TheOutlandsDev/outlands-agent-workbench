# Milestone validation

Observed on 10 November 2026 on one Linux development host. Private acceptance
records are kept outside the public source package.

| Area | Observed result |
| --- | --- |
| Engine unit suite | 40 methods passed |
| Workbench/controller/HTTP suite | 25 methods passed |
| Java compatibility | Compiled with `--release 17 -Xlint:all -Werror`; Python and compiled Java scripted results matched |
| Actual isolated checks | Four failing baseline tests became four passing final tests in both client exercises |
| Namespace boundary | Three probes passed: original roots hidden, working copy read-only, separate loopback network |
| Execution bounds | Real timeout and output-limit exercises passed |
| Patch handling | Git accepted the exact candidate and the missing-final-newline regression patch with `apply --check` |
| Browser scripted workflow | Submitted task, inspected diff/checks, accepted review, downloaded matching patch |
| History | Completed run and review persisted across server restart |
| Stop | A private waiting fixture was interrupted during baseline checks with zero model requests |
| Responsive interface | Desktop and 390-pixel viewport inspected; no document-width overflow at the narrow viewport |
| Static checks | Ruff check/format and JavaScript syntax check passed |

The 65 unit methods include unique-span replacement, stale hashes, duplicate
matches, scope restrictions, protected files, CRLF/Unicode/newline preservation,
refusal of whole-file writes, admission across stored history, artifact tampering,
review/export gating, origin/Host/token checks, and private configuration handling.

## Final-engine real-model acceptance

The final executable source completed one explicitly submitted browser task using
the already installed local `qwen3-coder:30b` model through Ollama:

- Six model requests, no automatic retries.
- A plan, two file reads, one exact text replacement, a named check, and completion.
- The only edit was `return a - b` to `return a + b` in the invented calculator.
  Blank lines, surrounding text, and the final newline were preserved.
- All four baseline tests failed; all four independent final tests passed.
- Original project source and protected tests remained byte-for-byte unchanged.
- Browser acceptance recorded the exact result and patch hashes. The downloaded
  patch matched the recorded artifact and passed `git apply --check`.
- No patch was automatically applied and no model weights were changed.

The final executable source hashes stayed unchanged throughout this real-model
browser exercise. The check demonstrates the complete task-to-reviewed-patch
workflow for **one already-known invented arithmetic fixture**. It is not a
held-out benchmark, broad-project competence result, or production qualification.

## Practical limits

Only Linux and the named local model were qualified. Java is a compatible launch
client; Maven/Gradle checks and a Java-native agent engine were not implemented.
The check runner executes fixed Python unittest modules, with no dependency
installation or arbitrary shell tool. Larger projects, long sessions, model
switching under concurrent host workloads, hostile multitenant execution, remote
hosting, automatic recovery, deployment, and long-running operation remain
unqualified. There is no token-price budget or automatic task queue.

The application was checked with Python 3.12.7, isolated system Python 3.10.12,
and Temurin JDK 21.0.13+9 targeting Java 17. Validation does not grant publication
or licensing permission; see [origins and licensing](ORIGINS.md).
