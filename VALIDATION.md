# Version 0.2 validation

Observed on 10 November 2026 on one Linux development host. Private inputs,
provider responses, run histories and acceptance receipts remain outside this
public source package.

| Area | Observed result |
| --- | --- |
| Engine unit suite | 40 methods passed |
| Existing Workbench/controller/HTTP suite | 25 methods passed |
| Project setup and typed-check suite | 14 methods passed |
| Java client compatibility | Compiled with `--release 17 -Xlint:all -Werror`; Python and compiled Java legacy scripted results matched |
| Python sandbox acceptance | Actual four-test baseline/final exercise, three namespace probes, timeout/output limits, and Git patch handling passed |
| Java sandbox acceptance | Failing baseline main became a passing main with six assertions; compilation diagnostics, namespace probes, timeout and output limits checked |
| Browser project setup | Previewed explicit files/hashes, protected tests, and saved separate Python and Java projects without inference |
| Browser task workflow | Both new model tasks reached independent final checks, accepted review, and matching patch download |
| Persistence | Both wizard-added projects, completed runs and accepted reviews survived server restart |
| Responsive layout | Desktop and 390-pixel viewport inspected; document width matched viewport width |
| Static syntax | Python AST/JSON parse and JavaScript syntax checks passed |

The 79 unit methods include legacy behavior and setup checks for scope, source
changes between preview/save, stale or replayed drafts, duplicate projects,
external config changes, private files, symlinks/hardlinks, editable test refusal,
uncertainty admission, Java source/main validation, and missing-JDK refusal before
child launch. The offline acceptance runner makes no model requests. Java check
counts describe protected main-program executions, not assertion counts.

## Two fresh final-engine local-model tasks

Both projects were configured through the browser wizard from private copies of
the invented examples. The installed local `qwen3-coder:30b` model completed each
in six requests, twelve total, with no automatic retries. The executable source
and fixture hashes stayed unchanged throughout qualification.

**Python manifest guard:** six baseline tests ran, with two failures (empty and
prefix digests were incorrectly accepted). The patch changed prefix matching to
exact equality and updated the docstring. All six independent final tests passed.
Surrounding whitespace, blank lines and the final newline were preserved.

**Java selection order:** the baseline compiled, then its protected test main
failed on first-occurrence ordering. The patch replaced `TreeSet` with
`LinkedHashSet` and removed the unused import. Independent final compilation and
the protected main passed all six assertions, covering order, deduplication, empty
input, case distinctions, unchanged input and null values. Other formatting and
the interface were preserved.

For both tasks, original source and protected tests remained byte-for-byte
unchanged. Accepted browser reviews bound the exact result/patch hashes. Each
download matched its recorded patch and passed `git apply --check`. Neither patch
was automatically applied. No model weights were changed or models evicted.

These are two fresh, small invented fixtures, not a held-out benchmark,
arbitrary-project competence result, or production qualification. The earlier
arithmetic scripted exercise remains available to check the legacy task format
without inference.

## Practical limits

Only Linux and the named local model were qualified. Java remains a compatible
launch client for the Python agent, with a new fixed Java compile/main check
profile. Maven/Gradle/JUnit dependency resolution, annotation processors, arbitrary
shell commands, package installation, remote hosting, automatic recovery and
unattended queues are not implemented. A selected check passing is evidence for
that check, not proof of universal correctness or resistance to adversarial code.

The namespace boundary shares the kernel and read-only system/JDK files. It has
no cgroup CPU/process-count quotas. Python checks use a 1 GiB address-space limit;
Java checks use 2 GiB address space and 128 MiB heap per compiler/runtime JVM.
Each check has a ten-second wall-clock timeout and bounded output. Input/config
parents must be trusted and stable; this is not a hardened multiuser service.

Acceptance used Python 3.12.7, isolated system Python 3.10.12, and Temurin JDK
21.0.13+9 targeting Java 17. Version 0.1 stop checks are retained in its earlier acceptance records; this
version also rechecked saved projects, run/review persistence and responsive layout. See
[origins and licensing](ORIGINS.md).
