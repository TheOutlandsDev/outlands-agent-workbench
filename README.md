# OUTLANDS Agent Workbench

A local browser workspace for the OUTLANDS Coding Agent. Choose an explicitly
configured project and local model, follow the plan and checks, inspect the diff,
then review and download a patch. The agent edits a private copy; it never applies
the patch to your project.

Version 0.3 adds a checked foreground launcher and Git review workspaces to the
project wizard and isolated Python/Java task-to-reviewed-patch workflow. It remains a small Linux
prototype with a Python engine and a compatible Java launcher.
See [validation and limits](VALIDATION.md) and [origins](ORIGINS.md).

## Requirements

- Linux with Python 3.10 or newer; the application uses the standard library only.
- `/usr/bin/bwrap`, `/usr/bin/prlimit`, and `/usr/bin/python3` for isolated checks.
  The host must permit Bubblewrap user namespaces. Checks fail closed when these
  prerequisites are unavailable.
- Git 2.30 or newer at `/usr/bin/git` for Git review workspaces and acceptance.
- A JDK supporting Java 17 for the optional Java launcher and full acceptance run.
- For real inference: an already installed, tool-capable local model served by
  Ollama at `127.0.0.1:11434`. No model download, credential creation, installation,
  daemon setup, or provider reconfiguration is performed by this project.

## Daily launch

From the repository root, use one command with an absolute private workspace
outside the source checkout:

```sh
python3 -B launch.py --workspace /absolute/private-workbench \
  --model YOUR_LOCAL_MODEL --jdk-home /absolute/jdk
```

The launcher checks Linux/Python, the fixed Git/Bubblewrap/prlimit tools, an actual
isolated Python check, optional Java 17+ tools, and configured Ollama models using
read-only `/api/tags` and `/api/ps` requests. It performs zero inference, installs
nothing, downloads no model, and does not evict a loaded model. It refuses an
unavailable prerequisite or a differently loaded model instead of changing the
provider. Model execution location still depends on your trusted Ollama setup.

For a new workspace, a successful check creates the invented arithmetic demo and
private configuration. An existing workspace reuses `config.json` and `data`;
`--model`, when supplied, must already be in its approved model list. Omit
`--model` for a new scripted-only workspace, or `--jdk-home` for Python-only use.
Use the printed loopback URL. This stays in the foreground; Ctrl+C stops the
owned server and its task/workspace workers. No startup service or scheduled
process is installed.

To inspect prerequisites without creating a workspace or starting a server:

```sh
python3 -B launch.py --workspace /absolute/private-workbench \
  --model YOUR_LOCAL_MODEL --jdk-home /absolute/jdk --check-only
```

Private temporary fixtures are used for the isolation probe. The original
`workbench.py init-demo` and `serve` commands below remain available.

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
5. Optionally create a Git review workspace to apply and recheck the accepted
   patch in a separate snapshot. Adopt it in the intended project manually.

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

Start from the demo workspace, then click **Set up project**. Enter a local
absolute source directory, project name/ID, language, explicit relative file list,
editable subset, protected test entry point, and initial task. One path per line
is accepted; the wizard does not recursively scan your repository. Review every
selected path, size, SHA-256 and editable/protected label, then **Save project**.
Saving writes private configuration and a task definition; it does not start a
model. Files are rehashed before saving, starting a task, reviewing and exporting.
A changed source or externally changed config refuses the corresponding action.

The wizard adds a private project entry to the external config and stores its
task under `DATA/projects/PROJECT_ID.json`. Existing entries are not overwritten.
Drafts expire after five minutes or server restart. Configuration parents and
source directories must be trusted and stable while saving; this is not a
transactional multiuser configuration service. Keep all runtime configuration
outside the public source tree. There is no model picker that downloads models:
approved model names still come from the private config's `models` list.

Two fixed check profiles are supported:

- **Python:** choose a protected root-level `test_example.py` unittest module.
  Only selected project files are copied, so include any helpers it imports.
- **Java:** start the server with `--jdk-home /absolute/jdk`, list every required
  `.java` source, and enter the fully qualified protected test main class, such
  as `selection.SelectionOrderTest`. Its matching source path must be selected
  and protected. The runner compiles with `--release 17 -proc:none` into temporary
  classes, then runs that main program. A nonzero exit fails the check. No Maven,
  Gradle, JUnit dependency download, annotation processor, shell, or arbitrary
  command is provided. One reported Java test means one executed protected main
  program, not its number of assertions. Missing JDK configuration refuses a Java
  task before launching its engine child.

For example, enable Java when starting your existing private workspace:

```sh
python3 -B workbench.py serve \
  --config /absolute/private-workbench-demo/config.json \
  --data-dir /absolute/private-workbench-demo/data \
  --jdk-home /absolute/jdk
```

The new [Python manifest fixture](examples/python_manifest/manifest_guard.py) and
[Java selection fixture](examples/java_selection/selection/SelectionOrder.java)
are deliberately broken, invented projects for practicing setup. For Python,
select `manifest_guard.py` and protected `test_manifest_guard.py` from its fixture
root. For Java, select `selection/SelectionOrder.java` and protected
`selection/SelectionOrderTest.java` from its fixture root, with main class
`selection.SelectionOrderTest`. Copy a fixture to a private directory outside
this repository before setup; do not use the tool's own source root as a project.

Manual configs still use [config.example.json](config.example.json). Legacy tasks
in [task.example.json](task.example.json) use `outlands-coding-agent-v1` with named
Python test strings. The wizard creates `outlands-coding-agent-v2` tasks with the
same top-level fields and typed `checks`, for example:

```json
{"unit":{"kind":"python-unittest","pattern":"test_example.py"}}
```

```json
{"unit":{"kind":"java-main","sources":["Example.java","ExampleTest.java"],"main_class":"ExampleTest"}}
```

Current bounds are 32 UTF-8 files, 32 KiB per file, 128 KiB total source;
1–4 declared checks; 1–16 requests per task; 1–120 seconds per request and a
600-second model-loop ceiling. Wizard tasks use 12 requests. The UI displays the
request budget; it does not account for tokens or currency. No whole-repository
index or unattended task queue is included.

The model first receives only `set_plan`. After a valid plan is acknowledged,
requests offer `read_file`, `replace_text`, and `run_check`. The engine also
enforces the plan requirement. An edit requires the current file hash and one exact, unique text
span. Bytes outside that span are preserved, including surrounding whitespace
and line endings. Whole-file `write_file` is refused. Tests are protected, and
independent final checks run before a task becomes Ready for review.

## Apply an accepted patch in a Git review workspace

After inspecting Diff and Checks and accepting the exact patch, choose
**Create Git workspace**. A cancellable worker will:

1. Recheck the accepted artifact and original selected files.
2. Create a new private repository containing only the selected baseline files.
3. Commit that baseline with a generic local identity and create a separate
   `outlands/task-ID` worktree branch.
4. Apply the accepted patch there, verify every resulting file against the
   accepted hashes, and rerun the task's fixed checks without model inference.
5. Record the branch, baseline commit, local directory, and check results.

The workspace is independent of the project's existing Git repository. Original
files, branches, index and history are untouched; no existing Git history,
remotes, hooks or attributes are imported. Git uses a clean environment, disabled
hooks/external configuration and an empty template. `.git`, `.gitattributes`,
`.gitmodules` and `.gitconfig` selections are refused for this operation.
These choices build on Git's official [worktree](https://git-scm.com/docs/git-worktree)
and [initialization](https://git-scm.com/docs/git-init) interfaces.

The patch remains an **uncommitted diff** in the new worktree. Open the displayed
local directory in your editor, inspect the diff and decide whether to commit it
there. Exported patches remain available for manual adoption in the intended
original project. The app does not commit candidate changes, merge into the
original branch, push, or publish the private workspace. Its Git objects contain
selected source; keep the workspace and data directory private.

Checks passed is a recorded creation-time result. Later edits require fresh
checks and review. Repeating the creation request verifies the existing workspace
without reapplying the patch or launching another worker. **Stop workspace** acts
only on its owned active worker. Failed/interrupted attempts retain files and
logs and block new tasks for inspection; there is no automatic cleanup, replay,
hold-clearing or recreation of an uncertain attempt.

## Stops, failures, and trust

There is one active task or Git-workspace operation per data directory, with no unattended queue or automatic
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
empty environment, temporary `/tmp`, closed stdin, a 10-second timeout and bounded output. Python checks have a 1 GiB
address-space limit; Java checks have 2 GiB address space with a 128 MiB heap
limit per compiler/runtime JVM and constrained JVM worker counts. Original home/service roots are not
mounted. This is a prototype boundary, not a hardened hostile-code service: the
kernel and `/usr` are shared, and there are no cgroup CPU/process-count quotas.

## Python and Java entry points

The browser delegates to the same foreground Python engine. Legacy `outlands-coding-agent-v1` tasks remain supported, typed checks use
`outlands-coding-agent-v2`, and its CLI remains compatible with
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

This runs 100 unit methods, compiles the Java client with Java 17 compatibility and
warnings as errors, compares Python/Java scripted results, and exercises real
Bubblewrap checks, namespace boundaries, time/output limits, and patch handling. It also checks Java compilation diagnostics, protected-main
execution, namespace boundaries and Java timeout/output limits.
It also checks prerequisite reporting, an actual owned Git-workspace worker,
accepted-patch rechecks and preservation of the original project Git state.
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
