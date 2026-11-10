# OUTLANDS Agent Workbench

A local browser workspace for the OUTLANDS Coding Agent. Choose an explicitly
configured project and local model, follow the plan and checks, inspect the diff,
then review and download a patch. The agent edits a private copy; it never applies
the patch to your project.

This first milestone completes the path from submission to reviewed patch. It is
a small Linux prototype with a Python engine and a compatible Java launcher.
See [validation and limits](VALIDATION.md) and [origins](ORIGINS.md).

## Requirements

- Linux with Python 3.10 or newer; the application uses the standard library only.
- `/usr/bin/bwrap`, `/usr/bin/prlimit`, and `/usr/bin/python3` for isolated checks.
  The host must permit Bubblewrap user namespaces. Checks fail closed when these
  prerequisites are unavailable.
- Git for the acceptance runner's patch check.
- A JDK supporting Java 17 for the optional Java launcher and full acceptance run.
- For real inference: an already installed, tool-capable local model served by
  Ollama at `127.0.0.1:11434`. No model download, credential creation, installation,
  daemon setup, or provider reconfiguration is performed by this project.

## Start with the invented demo

Clone or download this repository and run from its root. Use a new, absolute
workspace path **outside** the repository. The following creates fictional input
files, a task definition, and configuration in that private workspace:

```sh
python3 -B workbench.py init-demo --workspace /absolute/private-workbench-demo
python3 -B workbench.py serve \
  --config /absolute/private-workbench-demo/config.json \
  --data-dir /absolute/private-workbench-demo/data
```

Open the `http://127.0.0.1:PORT` address printed in the terminal. The default port
is chosen by the OS; `--port 8765` requests a fixed port. Keep the terminal open.
Stop the foreground server with Ctrl+C.

1. Choose **Arithmetic demo** and **Scripted exercise · no inference**.
2. Submit the unchanged task. Follow Activity, then inspect Diff and Checks.
3. The baseline has four failing tests; the corrected private copy has four
   passing tests. The original deliberately broken `calculator.py` stays intact.
4. In Review & export, record a note and accept or reject the exact patch.
   An accepted review unlocks **Download reviewed patch**.
5. Inspect and apply the downloaded patch yourself in the intended project.
   The workbench provides no automatic apply, commit, push, or deployment tool.

History, prompts, model responses, copies, checks, review notes, and patches are
stored under the private data directory. Restart with the same config and data
directory to inspect them. Keep this directory out of Git and public uploads.

## Use an installed local model

To include a local model when creating a **new** demo workspace:

```sh
python3 -B workbench.py init-demo \
  --workspace /absolute/private-model-demo --model YOUR_LOCAL_MODEL
```

Start that workspace with `serve`, select the model, and press Run task to
authorize one bounded inference task. The scripted option remains available and
does not call a model. The tested real model was `qwen3-coder:30b`; other models
have not been qualified by this milestone.

The engine checks Ollama's loaded-model list and refuses a different loaded
model. It does not evict models or retry a failed request. Verify the selected
model is genuinely local: a loopback endpoint alone does not attest where the
model server executes inference. Do not use a cloud-backed model for private
project content. The provider protocol follows Ollama's official
[chat API](https://docs.ollama.com/api/chat) and
[tool calling](https://docs.ollama.com/capabilities/tool-calling) documentation.

## Configure another small project

Copy [config.example.json](config.example.json) to a private location outside this
repository and replace its generic absolute paths. Configuration is loaded at
server startup. Each project points to a source directory and a separate task
JSON using the schema in [task.example.json](task.example.json).

The task declares exact relative file paths and SHA-256 hashes, editable files,
protected test modules, named checks, and budgets. For each selected file, obtain
the current digest with `sha256sum path/to/file.py`; put the 64 lowercase hex
characters in the task's `files` map. Review the selected content before allowing
inference. Files omitted from the task are neither copied nor visible to tools.
After deliberately changing source, update the task hashes and restart the
server. A stale hash refuses a new task or patch export.

Current bounds: 32 UTF-8 files, 16 KiB per file, 128 KiB total source; 1–4 named
Python unittest modules; 1–16 model requests; 1–120 seconds per request and a
600-second model-loop ceiling. The UI displays the request budget. This is not a
token or currency accounting system, a whole-repository index, or a Maven/Gradle
test runner. Selected Java text can be edited, but executable check support in
this milestone is limited to the declared Python unittest modules.

The model receives only four tools: `set_plan`, `read_file`, `replace_text`, and
`run_check`. An edit requires the current file hash and one exact, unique text
span. Bytes outside that span are preserved, including surrounding whitespace
and line endings. Whole-file `write_file` is refused. Tests are protected, and
independent final checks run before a task becomes Ready for review.

## Stops, failures, and trust

There is one active task per data directory, with no unattended queue or automatic
resubmission. Stop task signals only the child owned by this workbench. Stopping
an HTTP request cannot prove the provider stopped its inference. An unsettled
request produces an uncertainty hold and blocks another task. A process whose
ownership cannot be established after restart requires inspection. There is no
UI button to clear holds, replay requests, erase failures, or resume unknown work.
Inspect the private records and provider state before making a recovery decision.

Review/export rechecks source, protected files, candidate bytes, result/patch
hashes, and recorded passing final checks. A download is a proposal for manual
review, not a proof that the change is correct for every use.

Use this on a trusted local machine with trusted, stable config and project
directories. The server binds only loopback, validates Host and same-origin
requests, and uses an in-memory session token. It is not multiuser authentication
and is not configured for a reverse proxy, LAN exposure, or Internet hosting.
Local users with account access can inspect the private records.

Checks run with a read-only working copy, separate network/PID/user namespaces,
empty environment, temporary `/tmp`, closed stdin, a 10-second timeout, 1 GiB
address-space limit, and bounded output. Original home/service roots are not
mounted. This is a prototype boundary, not a hardened hostile-code service: the
kernel and `/usr` are shared, and there are no cgroup CPU/process-count quotas.

## Python and Java entry points

The browser delegates to the same foreground Python engine. Its task format
remains `outlands-coding-agent-v1` and its CLI remains compatible with
[OutlandsAgentClient.java](OutlandsAgentClient.java):

```sh
java OutlandsAgentClient.java /absolute/python3 /absolute/repo/agent.py \
  --task /absolute/private-workbench-demo/task.json \
  --source /absolute/private-workbench-demo/project \
  --run-dir /absolute/new-private-run \
  --state-dir /absolute/private-engine-state \
  --backend scripted-demo
```

For a real engine invocation use `--backend ollama --model YOUR_LOCAL_MODEL
--allow-local-inference` in place of the scripted backend. Use a new run directory
each time, and preserve the state directory and failed or uncertain results.
The Java client passes an argument list without a shell and forwards the Python
engine's exit status. It does not implement a second agent engine or browser UI.

## Run acceptance checks

```sh
python3 -B qa_agent.py --jdk-home /absolute/jdk \
  --work-dir /absolute/new-private-acceptance
```

This runs 65 unit methods, compiles the Java client with Java 17 compatibility and
warnings as errors, compares Python/Java scripted results, and exercises real
Bubblewrap checks, namespace boundaries, time/output limits, and patch handling.
It makes no AI inference requests. The demo's `test_calculator.py` is intentionally
failing before a task; use the acceptance runner rather than unrestricted test
discovery across the entire repository.

Real-model browser acceptance is a separate, explicit task; see
[VALIDATION.md](VALIDATION.md) for the observed result and its narrow coverage.

## Publication and licensing

This repository contains reviewed reusable source, invented fixtures, and public
instructions. Private configs, host paths, run history, prompts, model responses,
logs, credentials, project data, model weights, runtimes, and private review
receipts are excluded. No open-source license has been assigned to this source;
public visibility does not grant a general reuse license. See
[ORIGINS.md](ORIGINS.md) for attribution and licensing status.
