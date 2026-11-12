# OUTLANDS Agent Workbench

A local browser workspace for the OUTLANDS Coding Agent. Choose an explicitly
configured project and local model, follow the plan and checks, inspect the diff,
then review and download a patch. The agent edits a private copy; it never applies
the patch to your project.

Version 0.26 adds **Saved Review History**: explicitly list bounded observed
review receipts for one selected run, then inspect an earlier verdict, private
note, recorded time and artifact hashes without replacing its current decision.
Damaged or partial history remains visible as uncertain; historical inspection
starts no task and grants no export authority. It retains **Saved Review Decisions** to the existing explicit saved-run
review. Inspect the observed human verdict, private note, recorded time and exact
artifact pins. Accepted, Rejected, Stale, Unreviewed and Unknown remain saved
observations; this panel grants no export or execution permission. Result
freshness follows the original review writer's canonical JSON hash, shown
separately from raw file evidence. It retains the **End-to-End Offline Acceptance**
harness: create a fresh
private fixture, run the existing exact scripted Python demo through normal live
history, review its actual checks and export a patch, then inspect the same
retained evidence after restart without another attempt. Java compilation and
checks use a separate invented fixture. This harness performs no real-model
inference and leaves the production engine, task admission and browser controls
unchanged. It retains **Saved Run Review**: explicitly inspect one search result's
saved task scope, check specifications and recorded results, historical request
diagnostics and bounded patch. Review reads private saved evidence with current
metadata/history pins and a second evidence check. It performs no live worker
reconciliation and leaves Task, model, project and comparison slots unchanged.
It retains **Run history search and filters**: explicitly search saved
job metadata by ID or task text, filter by project/outcome, review pinned saved
metadata and choose an existing comparison side. These actions never reconcile
workers or start a task. It retains **Preset preview and comparison**: explicitly view a saved goal
beside the current Task draft without changing Task. A highlight spans the first
through last difference; Load remains a separate explicit action. It retains
**Named task presets**: privately save the current Task under a
new name for an already configured project, then explicitly refresh, select and
load its goal into Task. Presets preserve the approved project profile and never
start Run or select a model. It retains **Workspace search and focused reads**:
explicitly search current approved files in a verified private snapshot review workspace, read small
numbered ranges from source or protected tests, then open a pinned editable
result in the existing editor. Search and read run no checks, Git commands,
providers or model requests. It retains **Scoped workspace editor**: explicitly select an approved
editable file in a verified private snapshot review worktree, load its exact
current text, preview one unique replacement and save the pinned change. A fresh
passing snapshot recheck is required before controller re-export. Editing runs
no checks or model requests. It retains **Reviewed snapshot re-export**: explicitly review the complete
original-baseline-to-tested-snapshot patch from a verified snapshot-workspace
recheck, save a separate private acceptance, then download a pinned version 2
bundle. Export executes no checks, Git command or model request. It retains
**Snapshot workspace recheck**: inspect manual editable-file
changes in a verified snapshot review workspace, then explicitly run the original
fixed Python/Java checks against a separate pinned private snapshot. Each attempt
has its own history; original creation evidence and previous results remain
unchanged. It makes no model request. It retains **Snapshot review workspace**: preview a private snapshot export
against an approved selected baseline, then explicitly create a separate private
Git worktree and run fresh configured Python/Java checks. It performs no model
inference and does not write original project files. It retains **Snapshot Export
Project Check**: compare a private snapshot export with an explicitly selected
project, then verify its forward patch in memory when current selected bytes
match the original baseline. Already-tested, mixed, different or missing bytes
are reported without reconstruction proof.
It retains **Reviewed Snapshot Export**: review a verified workspace
recheck’s exact tested snapshot, record a separate private acceptance, then
explicitly download a pinned four-member patch bundle. Export performs no new
checks or model requests. It retains **Workspace Recheck**: inspect manual
editable-file changes in a private bundle review worktree and explicitly rerun
its configured checks against a separate pinned snapshot. Each attempt preserves
earlier results.
It retains **Bundle Review Workspace**: preview a private bundle against
an approved baseline, then explicitly create a separate private Git worktree
and rerun its configured Python/Java checks. Candidate edits remain uncommitted.
It retains **Bundle Project Check**: compare a verified private bundle
with an explicitly selected project's approved scope, check profile and current
file hashes. Its browser panel and offline CLI make no source changes. It retains
private **Reviewed patch bundles**, a pinned download preview and a read-only
offline verifier, carrying accepted patches, selected file hashes and bounded
saved review/check evidence. Other features include
advisory **Project readiness** inspections of selected source,
exact task/config fingerprints, executable presence and saved admission evidence,
read-only run comparisons, reviewed project refreshes, task revisions,
scoped search, focused reads, request-size guards, Run Diagnostics, the foreground
launcher, Git review workspaces and the isolated Python/Java
task-to-reviewed-patch workflow. It remains a small Linux prototype with a Python
engine and a compatible Java launcher.
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
3. The baseline runs four tests with three failures; the corrected private copy has four
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
does not call a model. Earlier milestones recorded trials with
`qwen3-coder:30b`; version 0.7 adds no real-model qualification. See the historical
limits in [VALIDATION.md](VALIDATION.md).

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
requests offer `read_file`, `search_text`, `read_lines`, `replace_text`, and `run_check`. The engine also
enforces the plan requirement. An edit requires the current file hash and one exact, unique text
span. Bytes outside that span are preserved, including surrounding whitespace
and line endings. Whole-file `write_file` is refused. Tests are protected, and
independent final checks run before a task becomes Ready for review.

## Preview a private preset before loading

Choose a configured Python or Java project, explicitly **Refresh private presets**,
and select a compatible saved name. Choose **Preview and compare selected preset**
to view its saved instructions beside the current Task draft. The current draft
may be empty or whitespace. Preview does not fill Task or start a task.

The two read-only views preserve exact text. A highlight covers the span from
the first through last differing Unicode character, so unchanged middle text
may also be highlighted. Matching goals are labelled identical. Exact UTF-8
hashes identify both observations. The comparison performs no normalization,
newline folding, model request, Git command, check or source read.

Review the instructions, then explicitly **Load selected preset into Task** if
wanted. Loading still only fills Task; **Run task** remains separate. Existing
scripted Tasks stay read-only and cannot load a different goal, but can preview
and compare. An unrelated admission hold can remain while previewing; it does
not enable Task or Run. Close comparison to clear only that preview.

Draft/name, project/model, preset selection, refresh/save/load, configuration
context and task submission changes discard the old comparison. Reload does not
restore or request it. Stale config/task/profile/history/record pins and unsafe
or partial stores refuse preview; older incompatible profiles cannot be previewed
or loaded. No new record, job, cache file, import or export is created.

The current draft is limited to 0–2,000 Unicode codepoints and 8,000 UTF-8 bytes,
with no NUL or invalid Unicode. Saved goals retain the existing nonblank rule.
The preview request is at most 32,768 bytes and the complete response at most
65,536 bytes, including both unabridged goals; no text is silently clipped.
Comparisons, goal text and hashes are private project context and remain outside
public uploads. These sequential checks assume trusted stable single-owner
storage and do not qualify Run freshness or prove source correctness.

## Save and load private task presets

Use **Named task presets** in the task composer for an already configured Python
or Java project. Presets save reusable goal text, not a task run or a new project
configuration. The selected source identity, paths, editable scope, check
definitions, task format and request/time budgets form the approved task profile.
Loading cannot change those permissions or limits, select a project/model,
change the default goal, or start inference.

1. Choose the intended project and an already approved local model. Click
   **Refresh private presets** to observe its current profile and preset history.
2. Enter the desired **Task** and a **New preset name**, then click
   **Save current Task as preset**. Saving creates one immutable private record;
   it does not overwrite a preset or run the task.
3. Click **Refresh private presets** again. Saving discards the earlier view
   pins; no preset is selected or loaded automatically.
4. Choose a saved preset marked **Profile matches**, then click
   **Load selected preset into Task**. Only this explicit load returns the saved
   goal to Task; the list contains names and compatibility metadata, not goal text.
5. Review Task and use **Run task** separately when admission permits it. Restart
   with the same private config/data directory, refresh and load explicitly to
   reuse a saved preset later.

The scripted exercise keeps its original read-only Task, so loading is disabled
until an already approved local model is selected. Its displayed Task can still
be saved under a new name. Under an unrelated admission hold, metadata actions
may remain available and an explicit load can fill the disabled Task for review;
Task and Run remain disabled. Preset actions do not inspect or clear that hold.
Normal live updates pause while a preset request is in flight, after waiting up
to ten seconds for an earlier live update to finish. Later ordinary polling does
not replace a loaded goal. Project/model/configuration or new-task context
changes discard preset selections; late responses for older inputs are ignored.

A reviewed source-hash or default-goal refresh can reuse the same presets: those
values are excluded from the profile binding. Changing project/source identity,
selected paths, edit permissions, checks, format or budgets makes older bindings
stale. Those records remain visible as **Profile changed**, with loading disabled.
Current config/task bytes are checked before and after preset actions. Presets
do not read source bytes, establish source freshness or authorize Run; its normal
guards remain separate.

Names use NFC-normalized Unicode, with 1–80 code points and at most 240 UTF-8
bytes, no surrounding whitespace, control/format characters or line separators.
Names are unique case-insensitively across all bindings for that project. Goals
are nonblank, contain 1–2,000 code points and at most 8,000 UTF-8 bytes, and reject
NUL or invalid Unicode. Multiline goals are allowed; the browser keeps its normal
textarea newline presentation and existing 2,000-code-unit input limit. There
are at most 64 presets per project, 32 KiB per record and 2 MiB of raw records,
with room for a full record reserved before saving. Each HTTP request is bounded
to 32 KiB and its response to 64 KiB.

Presets live under `DATA/task-presets/PROJECT_ID/ID.json`, outside public source.
The private store uses mode 0700 directories and mode 0600 regular single-link
files. Keep real names, goals and generated records out of Git and public
uploads. This milestone provides no overwrite, rename, delete, import or export
action. A failed or uncertain save consumes the UI history pins and requires an
explicit refresh. Partial, malformed or uncertain store records are retained and
block that project's preset actions for inspection; no automatic cleanup,
fallback or retry is performed. Sequential pin checks and staged publication
require a trusted, stable filesystem and do not establish a multiwriter
transaction or crash-durability guarantee. See [validation and limits](VALIDATION.md)
for qualification status; presets add no real-model qualification or recovery of
the preserved uncertain Java trial.

## Inspect project readiness

Choose **Project readiness**, select an already configured project, then press
**Inspect selected project**. The project selector remains usable when a saved
admission block disables Run. The dated report shows exact saved/observed
config and task fingerprints, selected file hashes and sizes, editable/protected
scope, fixed checks and budgets, prerequisite presence and saved admission
observations. A report can become stale; starting a task still performs its own
authoritative checks.

| Result | Meaning |
| --- | --- |
| Static checks passed | The required static observations passed at the displayed time. This does not authorize Run or qualify a model, sandbox or source correction. |
| Source refresh required | Selected source hashes changed and no other issue was observed. Review a refresh separately. |
| Blocked | Selected source, a required executable, a saved task/workspace state or a present request hold blocks new work. |
| Needs inspection | Config/task drift, damaged or unavailable evidence, or a partial admission inventory needs inspection. New work remains blocked. |

Fingerprints hash exact raw bytes, including JSON formatting. If config or task
bytes differ from those loaded by the server, selected source rows remain
**Not checked**. Changed paths or definitions are not silently adopted. Source
inspection reads only already selected files, with 32 files and 32 KiB per file
as its bounds. The 128-KiB combined size is a task eligibility threshold; the
inspector can read the bounded files to report all available sizes and block an
excessive total. It does not discover repository files.

Prerequisites are checked for regular/executable presence only. Python,
Bubblewrap and `prlimit` are required for checks; Git is optional for later Git
workspace creation. Java tasks require a configured JDK with `java` and `javac`
present. Inspection runs no executable, `--version` command or project check.

Every report explicitly leaves these eight areas **Not checked**: provider
availability, check execution, isolation capability, Java version, model context
fit, process ownership, workspace freshness and source correctness. Saved
`RUNNING`, recovery and uncertain statuses are observed without reconciling
workers. A valid present hold blocks new work; an unreadable or malformed hold
requires inspection and remains blocked. Neither condition is cleared here.

Saved admission inspection considers at most 200 matching job/unfinished records,
with directory enumeration bounded to 1,024 entries and a 2-MiB aggregate record
budget. Partial or damaged evidence cannot produce a static pass. Internal paths,
source contents, check output and raw exceptions are excluded from the report;
the selected relative paths, goal and check specifications are still private
project information. Keep the browser and private data directory private.

Normal live polling pauses while readiness is opening or open. Opening waits up
to ten seconds for an earlier live update, with **Close readiness** available to
cancel. Readiness and comparison panels cannot open together. Changing the
selected project invalidates the old report, and late responses are ignored.
Closing returns to the normal live view and its polling/reconciliation. The
readiness panel contains no Run, source edit, refresh, check-execution, retry,
hold-clearing or recovery action.

## Refresh a configured project

After changing a selected source file outside the workbench, choose its project
and click **Refresh project**. The panel shows its current task fingerprint and
recent saved revisions. Edit the **Default goal for the next task**, then choose
**Review refresh**. Inspect each selected path, current size, configured/current
SHA-256 and editable/protected label, along with the parent/new task fingerprints,
fixed check definitions, model-turn limit and request timeout.

**Save task revision** saves exactly that reviewed candidate and reloads the
project configuration. Changed hashes are visible for both editable and protected
files; their edit permissions remain fixed. The refresh cannot add or remove
paths, change checks, expand editable scope, change budgets or reconfigure the
Java JDK. A goal-only revision is supported with zero changed file hashes. If
neither the goal nor any selected hash changed, the preview is refused as a no-op.

Task fingerprints hash the exact saved task-file bytes, including formatting.
The parent fingerprint identifies the task bytes referenced before saving; the
new fingerprint identifies the bytes prepared for the revision.
Externally changed config or task bytes, even a formatting-only task change,
require inspection rather than silent adoption. The source, config and current
task are re-read before saving, and a source change since preview refuses the
save. Drafts expire after five minutes or a server restart. Editing the reviewed
goal, changing projects or encountering an admission block invalidates the UI
preview. Review a fresh preview after resolving the cause; there is no automatic
retry.

Revision data stays under the external private data directory, in
`DATA/revisions/PROJECT_ID/REVISION_ID/`, with a parent task, new task and linked
receipt. Existing task files and run pins remain unchanged. The panel shows the
latest 20 committed revisions and marks omitted older entries; a project can
save at most 64 revisions. Older configured projects show **No saved revisions**
until their first refresh. Keep revision files out of Git and public uploads.

The save prepares new files first and atomically replaces the config pointer
last. Prepared files left by an interrupted save are retained; committed history
follows only links reachable from the current pointer. This requires a trusted,
stable filesystem. Sequential source/config/task rechecks are not a multiwriter
transaction, a snapshot service or a guarantee of atomicity across all files.

Saving starts no inference and writes no source files. It does not clear holds,
replay requests, roll back a project or overwrite previous runs. Admission blocks
preview/save while revision history remains readable. Refreshing does not
revalidate old reviews or exports: each remains tied to its original task and
recorded hashes and must still pass its own checks when used.

## Search and read focused project context

After planning, the agent can use `search_text` to find a case-sensitive literal
inside the task's selected snapshot files. Queries contain 1–128 UTF-8 bytes,
with no newline or NUL. Results give relative paths, 1-based line numbers,
Unicode code-point columns and whole-file SHA-256 hashes. One match is reported
per matching line, in path/line order. A result contains at most 20 hits and
8,192 serialized JSON bytes, including metadata and escaping. Matching lines
omitted by the limit are counted, and clipped excerpts are marked explicitly.

`read_lines` reads an inclusive range of at most 80 lines from one selected file.
Its numbered excerpts carry the current whole-file hash. A read result also has
an 8,192-byte ceiling, with returned ranges and truncation flags showing what
was omitted. Individual search/read line excerpts have 512/1,024 UTF-8 byte
limits. Empty files have no invented lines; LF, CRLF and CR are recognized.
Viewing excerpts does not normalize or modify the underlying file bytes.

The read-only **Context** tab shows up to eight recent search/read tool results.
It contains private project source, so keep it and the data directory private.
The helpers do not discover directories, execute source, search unselected files
or expand the selected scope. Existing `read_file` remains available. Editing
still requires the current whole-file hash and a unique exact text span;
protected tests remain protected.

Before each Ollama chat request, the full serialized JSON body, including tool
schemas and options, must fit **131,072 bytes**. An oversized candidate is
recorded as `REQUEST_SIZE_LIMIT` before that chat request is sent or a new hold
is created. Earlier recorded attempts retain their counts. Diagnostics show
measured bytes versus the ceiling. The CLI's existing read-only loaded-model
preflight can occur earlier; this guard makes no claim that all provider GETs
were skipped. It is a byte limit, not tokenizer-based context qualification.
Model context, prediction limits, timeouts and no-retry behavior are unchanged.

## Create a snapshot review workspace

Choose **Snapshot review workspace** to import a private four-member v0.13
snapshot-export archive into a new isolated review workspace. Embedded checksums
provide unsigned integrity, not authenticity or a prior human-approval assertion:

1. Select an already configured project and the private snapshot ZIP. Optionally
   enter a whole-archive SHA-256 obtained through a trusted separate channel.
2. Choose **Preview snapshot workspace** explicitly. Selected original baseline
   bytes, protected files, approved task file pins, selected scope, fixed check
   specifications and budgets must agree with the archive. Forward reconstruction
   must verify. Tested or mixed current bytes and a false configured-task pin
   match do not qualify for creation.
3. Review the exact archive, patch, task/config and preview hashes, selected
   baseline/snapshot file hashes and edit permissions. The Java-required and
   configured-JDK facts describe the prepared task and server configuration;
   preview performs no new executable probe.
4. Within five minutes, choose **Create snapshot workspace** explicitly. The
   server rechecks global admission, source/task/config/archive pins and required
   JDK configuration before creating the job. Its worker constructs the private
   worktree and runs the configured fixed checks there without model inference.
5. Inspect **Snapshot workspace history**, its selected receipt, private path,
   branch, baseline commit and fresh check results. Use **Refresh snapshot
   workspace history** for an explicit update. **Stop owned snapshot workspace**
   signals only the selected preparing worker owned by the current server.

Preview is memory-only, writes no project or workspace files, and executes no
Git command, check or provider request. It remains usable under an unrelated
hold. One cached preview is retained; expiry, server restart, changed inputs,
a new preview or changed selected workspace state requires another explicit
preview. Creation consumes the preview before persistent work and is never
repeated automatically. The UI's observed admission and JDK facts can become
stale; the server's creation guards remain authoritative. An unresolved hold,
active or unfinished work, failed workspace, damaged record or unknown creation
outcome blocks new execution. An ambiguous creation response requires explicit
history inspection before another decision.

The new store is `DATA/snapshot-workspaces/ID/`, with receipts in the distinct
`outlands-snapshot-workspace-v1` format. It holds the private archive, staged task
and request, initial/final receipt, worker log, check output and generated Git
files. The new repository contains only selected original baseline files; Git
commits that baseline and creates an `outlands/snapshot-ID` review worktree.
The worker installs only the hash-verified reconstructed snapshot there, leaving
its candidate edits uncommitted at creation. It does not use the original
project's Git repository or write original source, prior run, creation, recheck
or export records. No archive extraction or archive-supplied command is used.

Saved archive checks are earlier observations. The new worker runs fresh fixed
Python/Java checks from the approved local task, using the existing read-only,
networkless isolation. Java requires the server's configured `--jdk-home`;
Python does not. The worker rechecks source, task/config, staged bytes, Git
controls, selected scope and snapshot hashes before recording verification.
`VERIFIED` means those checks passed when this workspace was created; it is a
historical receipt, not a current-workspace inspection, model/provider proof,
authenticity assertion, source-correctness guarantee or adoption authorization.
Later manual changes need their own review and checks.

Failures, including early preparation failures, retain private partial files,
core pins and available evidence. Interrupted or unknown unfinished work is not
resumed, retried, deleted or relabelled successful. Closing the panel ends its
selected-worker polling without stopping the worker; stopping the server stops
workers it owns. After restart, saved unfinished work is unowned and unresolved.
No foreign or saved PID is signalled. Read-only preview/history does not clear a
hold or authorize recovery.

Use **Snapshot workspace recheck** below for later manual editable-file changes.
Use **Reviewed snapshot re-export** for an explicitly selected verified recheck.
Existing bundle review workspaces retain their separate tools; there is no
automatic conversion of old records. `snapshot_workspace.py` is the
controller's explicit staged-job worker, not a general archive-import CLI. Use
the reviewed browser flow for import and creation.

The store allows at most 200 jobs and 2,097,152 aggregate raw receipt bytes.
Creation reserves 262,144 bytes for its new receipt before writing. Each receipt
and task JSON is bounded to 262,144 bytes, the staged request to 32,768 bytes,
the preview response to 131,072 bytes and the history response to 262,144 bytes.
The archive limit is 2,097,152 bytes; selected baseline and reconstructed snapshot
limits remain 32 files, 32,768 bytes per file and 131,072 bytes total. Full check
evidence is bounded to 2,097,152 bytes; receipt output is clipped separately and
marked when truncated. Damaged, partial or over-limit records fail closed.
The host and private store must remain trusted and stable: sequential rechecks
are not a multiwriter transaction or an atomic filesystem snapshot. Keep these
archives, generated repositories, source copies, notes and logs out of public
source and uploads.

## Search a private snapshot review workspace

Select a verified creation in **Snapshot workspace history**, then use
**Workspace search and focused reads**. This panel searches the current selected
private worktree; the task Context tab continues to show saved agent tool results.

1. Enter a literal query and explicitly choose **Search approved workspace files**. Search
   considers only approved selected UTF-8 files. Results show relative paths,
   1-based line numbers, Unicode code-point columns, clipped excerpts, file hashes
   and editable/protected labels. It never discovers directories or expands scope.
2. Select a returned match, choose an inclusive range of up to 80 lines, then
   explicitly **Read selected range**. The numbered range carries the current
   whole-file and workspace hashes. Protected tests can be read in this panel.
3. For an editable match, explicitly **Open editable result in editor** to load the full
   bounded file in the existing editor after fresh file/workspace hash checks.
   It does not preview or save an edit. Protected results cannot enter the editor.
4. Review a unique exact replacement and explicitly save through the editor, then
   perform a fresh snapshot recheck and separate private export review.

Searches use the existing case-sensitive literal helper: queries contain 1–128
UTF-8 bytes, with no NUL or newline. One hit is reported per matching line, in
path/line order, with at most 20 returned hits. The inner serialized result stays
within 8,192 bytes including editable labels; trailing hits may be omitted to fit,
with total counts and clipping shown. Search/read wrappers are capped at 16,384
bytes. Focused reads use 1-based inclusive ranges of at most 80 lines and a maximum
line number of 1,000,000. Per-line search/read excerpts have 512/1,024-byte UTF-8
limits. Empty files have no invented lines; LF, CRLF and lone CR are recognized
without modifying underlying bytes. A clipped read may omit requested lines;
returned ranges and flags state what was actually included.

Each read and editor-open request pins the whole selected workspace snapshot and
file hash from the search. Changed selected bytes, protected tests, source,
task/config, creation/check or Git controls refuse stale access; search must be
explicitly refreshed. The controller reinspects before and after responding.
Parent workspace/input/history changes and explicit editor/recheck/export actions
discard cached browser pins; late responses for old selections are ignored.
Changing inputs never submits a search, read or editor-open request automatically.

Search/read make no source/record writes, Git/check/worker/model calls, runtime
reconciliation or hold access. An unrelated admission hold can remain while
searching and reading. Editor-open reads saved admission for the editor and still
writes no files; a hold blocks later saving. Malformed or unresolved edit evidence
continues to refuse inspection. New results are current byte observations, not
check results, model qualification, source-correctness proof or adoption approval.

The 32-file/32-KiB-per-file/128-KiB-total selected scope remains unchanged. HTTP
input is capped at 32,768 bytes for all three routes; editor-open retains the
existing 262,144-byte full-text response bound. Trusted stable single-owner
storage and sequential guards are not an atomic multiwriter snapshot. Search
queries, excerpts and worktree content stay private. Archive formats, prior
results and the original Java hold remain unchanged.

## Edit a private snapshot review workspace

Select a verified creation in **Snapshot workspace history**, then use **Scoped
workspace editor**. This first editor supports that snapshot workspace type only.

1. Choose **List editable workspace files**, select a file, then **Open selected
   workspace file**. The full bounded UTF-8 text is read-only until an explicit replacement
   is reviewed. The file hash, byte count and line-ending label are displayed.
2. Select text in the displayed file and choose **Use selected file text**, or
   enter a nonempty exact old span. A captured selection retains its original
   line endings even though browser textareas normalize their display. Editing
   that old-span input discards the captured span. For typed multiline spans,
   choose LF or CRLF explicitly; mixed files may require a captured selection.
3. Enter the replacement and its intended line endings, then **Preview workspace edit**.
   The old span must occur exactly once, including overlapping matches. Review
   the before/after hashes, byte counts and bounded diff. Bytes outside that span
   remain exact, including whitespace, line endings and missing final newlines.
4. Within five minutes, choose **Save reviewed workspace edit**. One save consumes the
   preview. Source/task/config/creation/check/Git controls, all selected bytes,
   edit/recheck history and read-only admission observations are rechecked.
5. Explicitly inspect and run a new snapshot recheck, then review and export its
   verified snapshot. A saved edit records earlier recheck IDs; controller
   re-export refuses them even when an edit restores identical old tested bytes.

Reads and previews perform no checks, Git commands, provider requests or worker
reconciliation. They display saved admission blocks. Saving refuses a hold,
active or unresolved saved execution, an owned-worker entry, stale source or
changed controls. A save writes only the selected existing private worktree file
and a new private edit record under `DATA/snapshot-workspace-edits/ID/`. The
original project and historical creation/recheck/acceptance records stay intact.
Protected files, new files, deletions, path escapes, links and Git controls cannot
be edited. A current file must be owner-owned, have one link and use mode 0600, 0644 or
0664 below its owner-only private job directory. Saves preserve that mode;
retained original/candidate copies use 0600.

The edit record retains original and candidate bytes. Its finite
`outlands-snapshot-workspace-edit-v1` receipt records SAVED or a retained
PREPARING/FAILED state. An unresolved, malformed or partial edit blocks subsequent
writes, execution and controller snapshot recheck/re-export. A failure can leave
the target changed with uncertain finalization; nothing is automatically rolled
back, cleaned up or retried. Inspect the retained private evidence before any
separate recovery decision. No recovery control is provided here.

Scope and size remain 32 UTF-8 files, 32,768 bytes per file and 131,072 total.
The JSON request/full-text response is capped at 262,144 bytes; previews at
131,072, with a 240-line/8,192-byte diff and explicit clipping. The journal permits
200 records and 2 MiB aggregate receipts with a 32,768-byte reservation for a new
record. Retained source copies are separately bounded to two 32,768-byte files per
saved edit. Previews expire after five minutes or restart; parent-input and
selection changes discard browser pins. A restarted server requires a new
explicit read/preview before saving.

These operations assume a trusted stable single-owner store. Sequential guards
and atomic replacement are not a multiwriter compare-and-swap transaction. The
standalone archive verifier checks packet hashes/evidence, without a private edit
journal or human approval claim. Archive formats and the original Java hold are
unchanged. Real editor records, worktrees and bundles remain private.

## Recheck a snapshot review workspace

Select a `VERIFIED` creation in **Snapshot workspace history**, then choose
**Inspect current snapshot workspace**. The read-only inspection compares
selected current bytes with the imported creation snapshot. Protected files,
approved original baseline, task/config/archive evidence and the simple private
Git baseline must still match. No Git command, project check, model request,
process reconciliation or project/worktree write occurs during inspection.
Inspection and history remain available under an unrelated hold.

Review changed editable files, hashes, fixed check profiles, preview expiry and
history pin. Within five minutes, explicitly choose **Run snapshot recheck**.
The server checks current admission and configured Java prerequisites, repeats
inspection, reserves receipt capacity and consumes the preview before writing a
new private attempt in `DATA/snapshot-workspace-rechecks/ID/`. Its worker copies
only the inspected selected bytes into a separate snapshot without Git metadata
and runs the original task's fixed isolated Python/Java checks there.

Each attempt has the distinct `outlands-snapshot-workspace-recheck-v1` format.
Creation receipts, earlier attempts, worktree/Git and original source stay
unchanged. Full check evidence stays private; displayed output is separately
bounded. `VERIFIED` records successful checks for the pinned snapshot at that
time. It does not refresh the creation receipt or guarantee correctness,
authenticity, provider completion or authorization to adopt changes.

Changed inputs, selected bytes, Git controls, history, expired/replaced previews
and restart require another explicit inspection. The worker rechecks both its
snapshot and live evidence around execution; drift retains available output but
refuses verification. Failures, interruptions, partial writes, malformed records
and unknown unfinished attempts stay retained and block further execution. No
automatic retry, evidence cleanup, hold clearing, source adoption, format conversion
is provided. Snapshot re-export requires the separate explicit review described
below. **Stop owned snapshot recheck** signals only
a worker owned by the current server; saved process identifiers grant no ownership.
Closing the panel ends selected polling without stopping the worker.

Git control/index validation reuses the existing direct readers for the generated
simple worktree subset. Current raw metadata hashes are new observations;
v0.15 did not record those raw historical hashes. The host/store must remain
trusted and stable; sequential guards are not an atomic filesystem snapshot.
Limits are 32 selected UTF-8 files, 32 KiB/file and 128 KiB total, 200 attempts,
2 MiB aggregate raw receipts, 256 KiB reserved per new receipt, 32 KiB requests,
64 KiB inspection summaries, 128 KiB previews and 256 KiB history responses.
Keep real workspaces, selected snapshots, check output and attempts private.

## Review and re-export a snapshot workspace

In **Snapshot review workspace**, select a verified creation and explicitly
refresh its recheck history. Select a `VERIFIED` recheck, then choose **Review
snapshot re-export**. The server reads its exact saved tested snapshot and full
check evidence, validates original creation/archive/task/config/source and current
Git/worktree pins, and prepares a version 2 packet in memory. It runs no Git
command, check, worker, provider request or process reconciliation and does not
read or change a hold. Preview remains available under an unrelated hold.

Review the complete original-approved-baseline-to-tested-snapshot patch and the
selected baseline/tested hashes, permissions, fixed check profiles and recorded
passing observations. This patch includes earlier imported changes and later
manual editable changes present in the tested snapshot. The browser clips the
preview at 240 lines/8,192 UTF-8 bytes and marks omissions; the bundle contains
the full patch. Recorded checks are historical, not a new execution or a model
result. Changed current evidence requires a new inspection and passing recheck;
export does not resample later untested edits.

Optionally add a private note, then explicitly choose **Accept reviewed snapshot
re-export** within five minutes. Acceptance stores only `receipt.json` and
`review.json` in the separate private `DATA/snapshot-reexports/ID/` history, using
`outlands-snapshot-reexport-acceptance-v1`. Notes allow at most 1,000 Unicode
code points and 2,000 UTF-8 bytes, with no NUL or invalid Unicode. Notes remain
private and are excluded from the archive. No human-approval assertion is
embedded in the packet. Existing creation, recheck and legacy export records
remain unchanged.

Choose **Download private re-export bundle** separately after acceptance. It
reconstructs and rechecks the exact accepted packet, attempt receipt, tested
bytes, original project/Git pins and history tips before returning the bytes.
A later acceptance or recheck invalidates older history-bound downloads. Damaged,
failed, PREPARING or partial acceptance evidence blocks new re-export acceptance
and download; there is no fallback to an older approval, repair, cleanup or
automatic retry. **Refresh re-export history** explicitly reloads saved approvals
after restart without inventing a new preview or accepting anything automatically.

The four members remain `changes.diff`, `verification.json`, `README.txt` and
`SHA256SUMS`. Version 2 explicitly identifies recorded snapshot-workspace recheck
evidence and uses `import_archive_sha256` for the earlier imported packet. The
new packet's own digest stays separate. No legacy `bundle_sha256` record is
fabricated. Original record hashes identify omitted evidence, not authenticity.
Prompts/responses, full check output, raw source copies, host paths, IDs, review
notes and times are excluded; the patch, relative names and check specifications
still contain private source information. Keep the unencrypted bundle private
and preserve a separately trusted whole-archive digest when available.

The current offline verifier, project checker and snapshot-workspace importer
explicitly support both v1 and v2 packets through strict separate schemas. V1
bytes and meaning remain unchanged. Older Workbench versions accept only v1;
use this version's tools for v2. Verify either format without project access:

```sh
python3 -B snapshot_export.py --archive /absolute/private-snapshot.zip \
  --expected-sha256 SHA256_FROM_TRUSTED_CHANNEL
```

Verification never extracts, applies or executes. Unsigned checksums and recorded
passing checks do not establish source correctness, authenticity, provider
completion or adoption permission. Re-export is bounded to 200 acceptances,
2 MiB aggregate raw receipts, 32 KiB reserved per new receipt, 128 KiB saved
reviews, 256 KiB history JSON, 2 MiB archive and 1 MiB patch. Selected-byte,
preview and private filesystem limits remain unchanged. These are sequential
trusted-store guards, not an atomic multiwriter transaction. Real bundles,
worktrees and acceptance history remain outside public GitHub source.

## Create a private bundle review workspace

Use **Bundle Review Workspace** when you have a private v0.9-format reviewed
bundle and want to check its candidate in a separate workspace:

1. Select an already configured project and a local ZIP. Optionally enter a
   SHA-256 obtained through a trusted separate route.
2. Explicitly preview it. The archive, configured task/check profile, selected
   baseline bytes, protected files and reconstructed candidate hashes must all
   agree. Only a fresh `BASELINE_MATCH` can produce a creation preview.
3. Review the file hashes and preview pin. Within five minutes, choose
   **Create private review workspace**. Creation checks the pins, source and
   normal admission guards again; a preview never authorizes a later changed
   bundle, configuration or baseline.
4. Inspect the resulting path, branch, baseline commit and rerun check results.
   A `VERIFIED` receipt means those configured checks passed in that selected-file
   workspace. Review its uncommitted diff yourself before any later adoption.

Preview is memory-only and runs no project check, Git command or provider request.
It works while execution is held. Only one preview is retained at a time; changing
inputs or using it requires a new preview. Creation stores the private archive,
task, request and receipt below `data/bundle-workspaces/ID/`. It creates a new
selected-file baseline repository and an independent review worktree there.
It never opens or changes the original project's Git repository.

Patch handling is deliberately narrow: canonical text diffs generated by the
bundle format are reconstructed in memory, verified against every candidate hash
and regenerated byte for byte. Git receives only the verified selected bytes.
No archive extraction, arbitrary patch command, hook, filter, rename, mode change,
binary patch or archive-supplied command is accepted. UTF-8 text, LF/CRLF and
missing final LF are supported; ambiguous line separators are refused.

The configured local task supplies the fixed isolated Python/Java checks. Saved
bundle checks do not substitute for this rerun. Java creation needs the server's
explicit `--jdk-home`; Python creation does not. Checks run with the existing
networkless, read-only selected-file isolation. These checks do not establish
source correctness, provider completion, provenance or approval to adopt code.

Failures and interruptions retain their private work and evidence. They block
new execution until manually inspected; the interface cannot retry, clear a hold,
delete evidence or commit/apply to the original project. Stop can signal only a
worker owned by the current server. After a restart, an unfinished saved job is
shown as unowned and unresolved, never resumed or signalled by a saved PID.
The history inspects at most 200 jobs and fails closed on damaged or over-limit
records. Receipt displays bound check output; full rerun evidence stays private.
Saved verification is a dated observation, not a freshness guarantee after manual
workspace edits. Real bundles and generated repositories remain private.

## Recheck a manually edited review workspace

In **Bundle review workspace**, select a creation receipt whose checks passed,
then choose **Inspect current workspace**. The inspection compares current
selected bytes with the creation candidate, shows editable-file changes and
requires protected files, approved original source, config and task pins to
remain valid. It inspects the known private Git relationships and baseline index
directly, without running Git, project checks or a model.

Review the selected hashes, snapshot pin and current history tip. Within five
minutes, explicitly choose **Run recheck**. The server rechecks the preview,
history and admission guards before creating a new private attempt below
`data/workspace-rechecks/ID/`. Its worker copies only the inspected selected
bytes into a separate snapshot and runs the original task's fixed isolated
Python/Java checks against that same snapshot. Java requires the configured JDK.
The app writes neither the original project nor the review worktree.

Recheck results have their own history. The original creation receipt stays a
historical result, and existing check evidence is never replaced. A fresh
`VERIFIED` receipt records passing configured checks for that snapshot at that
time. Later edits need a new inspection and recheck. Source correctness, provider
completion and permission to adopt changes remain separate decisions.

The preview binds selected bytes, creation/request records, task/config/bundle
pins, current Git guards and the current recheck-history digest. New previews,
expired previews, changed inputs and a changed history tip require another
explicit inspection. The worker rechecks those observations after execution;
drift retains the checks but refuses verification. No automatic retry occurs.
Failures, interruptions, malformed records and unknown unfinished attempts block
further execution. Stop signals only a recheck child owned by the current server.
Restart does not resume work or infer ownership from saved process identifiers.
Read-only inspection remains available under an unrelated hold.

This supports the simple private Git worktrees created by Bundle Review
Workspace, with their generated config, loose objects and version-2 index.
Commits, staged changes, changed branch/control pointers, protected edits,
unexpected files and unsupported Git metadata are refused for inspection.
Version 0.11 did not save historical raw control-file/index digests: the new
inspection validates their current structure and baseline semantics, then pins
their current bytes for this recheck. It does not invent earlier observations.
The reader follows Git's documented [index format](https://git-scm.com/docs/gitformat-index)
and [repository layout](https://git-scm.com/docs/gitrepository-layout), supporting
only the stated private-workspace subset.
The host/store must remain trusted; sequential checks are not atomic filesystem
snapshots. Keep all workspaces, selected snapshots and results private.

## Review and export a tested workspace snapshot

In **Bundle review workspace**, select an original creation whose status is
`VERIFIED`, refresh its recheck history explicitly, and select a `VERIFIED`
recheck attempt. Below that attempt, choose **Review snapshot export**. The
server prepares the archive in memory and shows its exact digest, original
baseline/tested-snapshot file hashes, editable/protected scope, fixed check
specifications and recorded passing observations. It does not execute Git,
checks or a provider request, reconcile old jobs, or write a new run.

The patch compares the approved original bundle baseline with that recheck's
saved tested snapshot. It therefore includes both the initial imported fix and
any selected editable manual changes captured by the recheck. Protected files
must remain unchanged. Use the original baseline hashes when reviewing the
combined patch. The original creation and recheck records remain historical and
unchanged.

Review the bounded diff carefully. The browser displays at most 240 lines and
8,192 UTF-8 bytes, with an explicit truncation notice when anything is omitted;
the archive contains the complete patch. Add an optional private note, then
choose **Accept reviewed snapshot** explicitly. Notes allow up to 1,000 Unicode
code points and 2,000 UTF-8 bytes, without NUL characters or invalid Unicode.
Editing a note does not change the artifact preview. Acceptance writes only
`receipt.json` and `review.json` below
`DATA/snapshot-exports/ACCEPTANCE_ID/`; the note stays in the private receipt.
Neither the note nor a human-acceptance assertion is included in the ZIP.

**Download private patch bundle** is a separate explicit action after acceptance.
The server reconstructs the artifact and rechecks the selected acceptance
receipt, archive digest, tested bytes, source/task/config/Git evidence and
history pins before returning it. Nothing is applied, extracted or committed.
The browser does not accept or download automatically. Keep the unencrypted ZIP
private and preserve its displayed whole-archive SHA-256 separately through a
trusted channel.

The four fixed members are:

| Member | Contents |
| --- | --- |
| `changes.diff` | The complete original-baseline-to-tested-snapshot patch |
| `verification.json` | Selected hashes, fixed task profile and recorded passing check observations |
| `README.txt` | Private handling, manual-use guidance and verification limits |
| `SHA256SUMS` | SHA-256 checksums of the other three members |

Raw source copies, full check output, prompts, model responses, host paths and
acceptance notes are excluded. The patch, relative filenames and check
specifications still contain private project information. Original record hashes
identify omitted bytes; they do not reconstruct or authenticate those records.
This packet provides unsigned byte integrity, not authenticity, a model result,
provider completion, source correctness or Git adoption. No checks are rerun by
preview, acceptance, download or the verifier.

Export previews are memory-only, expire after five minutes or server restart,
and are consumed by the explicit acceptance flow. Workspace/recheck selection,
new inspections or execution, changed inputs and changed history pins invalidate
cached review state. Changed source, task/config bytes, Git metadata, protected
files or tested snapshot bytes refuse the old evidence; inspect the cause and
obtain a fresh valid recheck before exporting changed content. A history-tip
change alone requires fresh explicit review and acceptance pins. A later
acceptance invalidates an earlier download's parent-history pin; the application
does not fall back to an older acceptance or overwrite old records.

Use **Refresh accepted exports history** to inspect saved acceptances and choose
one explicitly after a restart. Download needs no new preview when that saved
acceptance still passes every fresh server guard. `PREPARING`, `FAILED`, partial
or malformed acceptance evidence blocks new snapshot acceptance and download.
It remains available for inspection or produces a fixed inspection refusal;
there is no automatic retry, cleanup or repair. These export-only blockers do
not clear a model hold or change admission for other execution. Export inspection,
explicit acceptance and download remain available under an unrelated model hold
without reading or changing that hold. Normal live polling stays paused while
the existing workspace panel is open and resumes when it closes.

Bounds are 200 saved acceptances, 2,097,152 aggregate raw receipt bytes,
32,768 bytes per receipt, and 131,072 bytes per saved review. New acceptance
reserves room for its receipt before writing. The ZIP is limited to 2,097,152
bytes, the full patch to 1,048,576 bytes, and `verification.json` to 262,144 bytes.
The selected snapshot retains the 32-file, 32,768-byte-per-file and 131,072-byte
total bounds. Reads reject unsafe links and remain sequential; this requires a
trusted, stable private filesystem, not a multiwriter atomic snapshot service.

Use `snapshot_export.py` for this four-member format. The earlier six-member
reviewed-patch format and its verifier remain unchanged. Verify an explicitly
named downloaded snapshot archive without project access:

```sh
python3 -B snapshot_export.py --archive /absolute/private-snapshot-export.zip \
  --expected-sha256 SHA256_FROM_TRUSTED_CHANNEL
```

The digest option is optional for internal integrity inspection. A valid archive
prints a bounded JSON summary and exits 0; refused input prints a fixed code and
exits 1. This CLI is verify-only: it never creates an acceptance, extracts or
applies files, executes Git/checks/models, accesses a configured project, or
changes records or holds. Internal checksums alone cannot establish authenticity;
compare a whole-archive digest obtained independently when available.

## Check a snapshot export against a project

Choose **Check snapshot export**, select an already configured project and a
private v1 or v2 snapshot-export ZIP, and optionally supply a whole-archive SHA-256
from a trusted channel. Press **Check snapshot against project** explicitly.
Choosing a file alone sends nothing. The loopback server keeps the archive in
memory and writes no run, report, acceptance, source or workspace files.

The archive is verified before task/source access. Config and task bytes must
still match the approved loaded configuration. The export's task format,
selected paths, editable/protected permissions, fixed check specifications and
budgets must match that task before any selected source is read. Archive paths
never extend the approved project scope. A mismatch shows the difference and
skips source reads. Config/task guards are checked again after comparison.

| Observation | Meaning |
| --- | --- |
| Baseline match | Every selected file matches the original export baseline; strict forward reconstruction must also verify |
| Tested match | Every selected file matches the recorded tested snapshot; forward reconstruction is not checked |
| Mixed match | Selected files mix baseline and tested bytes; reconstruction is not checked |
| Different | At least one selected file differs from both applicable recorded hashes |
| Needs inspection | Missing, unreadable, unsupported, oversized, mismatched or changed evidence prevents a complete result |

Only complete baseline-matching bytes support reconstruction. The helper applies
the exact diff to a fresh in-memory copy, checks selected scope, protected files,
file/aggregate bounds and every tested snapshot hash, then regenerates the
canonical diff and requires identical patch bytes. It rereads the selected
baseline afterward to detect observed drift. A failed reconstruction or changed
observation removes verification and requires inspection. No reverse reconstruction
is attempted for tested or mixed selections, and nothing is applied to disk.

The report separates file observations, task-hash matches and reconstruction
status. A task pin mismatch remains visible even if current bytes match an
exported baseline. Check observations within the export are recorded evidence;
comparison runs no checks, Git commands or model requests, reads no holds, and
performs no process reconciliation or repair. It works under an unrelated model
hold and requires no JDK. The panel pauses normal polling while open, invalidates
results when inputs change and does not upload automatically.

The helper observes only the at-most 32 declared UTF-8 files, each at most
32,768 bytes. Complete per-file observations may read up to 1 MiB so an oversized
selection is reported accurately; reconstruction eligibility remains 131,072
aggregate bytes. The archive is limited to 2 MiB, the comparison JSON to 65,536
bytes and the browser response to 131,072 bytes. Links, special files and unsafe
paths are refused. Sequential observations require a trusted, stable store and
are not an atomic filesystem snapshot or an adoption authorization.

The same read-only comparison is available from the CLI:

```sh
python3 -B snapshot_project_check.py /absolute/private-snapshot-export.zip \
  --project /absolute/project --task /absolute/approved-task.json \
  --expect-sha256 SHA256_FROM_TRUSTED_CHANNEL
```

The digest option is optional. The CLI verifies the archive before opening the
task, checks the exact task bytes again before returning, and prints a bounded
JSON report. Exit 0 means baseline match with verified forward reconstruction or
tested-byte match; tested match explicitly leaves reconstruction unchecked. Exit
1 means another observation state; exit 2 means fixed input refusal. None means
safe adoption, authenticity, source correctness or fresh test execution. Keep
archives and reports private: relative filenames, checks and hashes are project
information. The earlier six-member bundle checker remains a separate format.

## Check a private bundle against a project

Choose **Check bundle against project**, select an already configured project,
choose a private ZIP, and optionally supply a whole-archive SHA-256 from a trusted
channel. Press **Check selected project** to send those archive bytes to this
local loopback server. Choosing a file alone does not submit it. The application
does not persist the uploaded archive or create a run record. Relative filenames,
check specifications and hashes in the report remain private project information.

The archive is verified first. Its format, selected path set, editable/protected
permissions, fixed check specifications and budgets must match the selected
task. A profile difference skips all source reads and shows the mismatch; archive
paths never expand the configured project scope. A change to the loaded config
or project-task bytes requires inspection and a reload of the intended config.

When the profile matches, the report compares only approved source bytes:

| Result | Meaning |
| --- | --- |
| Baseline match | Selected bytes match the bundle's baseline |
| Candidate match | Selected bytes match the bundle's candidate |
| Mixed match | Some edited files match the baseline and others the candidate |
| Different | At least one readable selected file matches neither version |
| Needs inspection | Profile differences, missing/unsafe files or incomplete/bounded evidence prevent a complete comparison |

An unchanged protected file can match both versions. A changed protected file
is reported as changed. Each row shows the archive's before/after hashes, the
selected task's configured digest, current digest/size and whether current bytes
match that configured pin. Configured pins stay separate from the selected-byte
comparison: a later task revision may pin candidate bytes. None of these results
authorizes Run or establishes patch applicability.

Use the same comparison offline with an explicitly named task and source root:

```sh
python3 -B bundle_project_check.py /absolute/private-bundle.zip \
  --project /absolute/project --task /absolute/task.json \
  --expect-sha256 SHA256_FROM_TRUSTED_CHANNEL
```

The digest option is optional for internal archive integrity checking. Embedded
checksums are unsigned; the expected digest must come through an independently
trusted channel to detect replacement. The CLI prints bounded JSON: exit 0 for a
complete baseline/candidate match, exit 1 for a nonmatch or inspection report, and
exit 2 for refused input. It reads named inputs and selected files without
extracting, applying, executing, writing, contacting a model or changing a hold.
Java source comparisons require no JDK or compiler invocation.

Reports explicitly leave task goals, check reruns, provider completion, source
correctness, patch applicability and Git adoption **Not checked**. Sequential
observations can become stale and are not an atomic filesystem snapshot. Review
the patch and run the intended checks separately before manual adoption.

The panel remains available under an unrelated request hold, pauses normal
polling while open, invalidates old results on project/file/digest changes, and
ignores late responses. Closing resumes the normal run view. The hold continues
to block new work. See [validation and bounds](VALIDATION.md) for read limits.

## Download a private reviewed bundle

After accepting a completed patch, open **Review & export**, then choose
**Preview private bundle**. Inspect the archive digest, its six members, selected
file hashes and saved check summary. **Download private bundle** rebuilds and
rechecks the artifact against that displayed digest; changed evidence requires
a new preview. The original plain-patch download remains available.

Keep the downloaded ZIP private: its patch, relative filenames and check
specifications can contain private source information. Choose a private download
location and review its filesystem permissions. Bundles are ordinary unencrypted
ZIP files; this application does not publish or upload them.
The source checkout ignores ZIP files to reduce accidental commits. This is an
upload safeguard, not filesystem access control or encryption.

The six fixed members are:

| Member | Contents |
| --- | --- |
| `changes.diff` | The exact accepted patch |
| `manifest.json` | Selected baseline/candidate hashes, editable scope, check profile, budgets and original-record digests |
| `review.json` | Accepted decision and hash bindings |
| `checks.json` | Selected recorded independent-final-check results |
| `README.txt` | Manual adoption instructions and verification limits |
| `SHA256SUMS` | SHA-256 checksums of the other five members |

Task goals, project/run/model identifiers, timestamps, review notes/identities,
prompts/responses, absolute paths, source copies and raw check output are omitted
from these summaries. The patch itself contains source changes. Original record
digests identify omitted private bytes; their contents cannot be reconstructed
or authenticated from the bundle.

Verify a downloaded archive from the repository root, using its displayed digest
from a trusted preview when available:

```sh
python3 -B patch_bundle.py /absolute/private-bundle.zip \
  --expect-sha256 SHA256_FROM_TRUSTED_PREVIEW
```

Omit `--expect-sha256` to inspect internal integrity alone. A valid archive prints
a bounded JSON summary and exits 0; a refusal prints a fixed error code and exits
2. The verifier reads without extracting files, applying patches, executing
checks, contacting a provider or changing run records. Embedded checksums are
unsigned integrity evidence. They do not establish authenticity; a person who
changes all the contents and checksums can create a different valid bundle.
An independently trusted whole-archive digest detects that replacement.

Every summary leaves check reruns, provider completion, source correctness and
Git adoption explicitly **Not checked**. Recorded passing checks remain saved
evidence. Before manual adoption, inspect the patch, compare the intended
project's baseline hashes, use a review workspace and run its fixed checks.

Bundle export requires a saved accepted `REVIEW_READY` artifact with complete
start-time task pins and the current project revision. Missing legacy pins,
changed config/task/source/candidate/protected files, partial records, or missing
passing final evidence are refused. The new bundle gate leaves existing plain
patch/workspace behavior intact. An unrelated request hold stays in place and
continues to block new work; bundle inspection does not clear or reconcile it.

The preview pauses normal run polling until closed, waits at most ten seconds
for an earlier update, and ignores late responses after selection changes.
Archives are built in memory and never cached in the private run directory.
Limits are a 2-MiB archive, six fixed stored members and a 1-MiB patch. The offline
verifier rejects compressed, encrypted, linked, duplicate, extra or unsafe members,
unsupported metadata, malformed schemas and hidden or trailing records. See
[validation and bounds](VALIDATION.md) for saved-record inspection limits.

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

## Inspect Run Diagnostics

Every run has a read-only **Diagnostics** tab and a summary beside its request
budget. New request records include the start time, monotonic elapsed time,
effective timeout, serialized request size when available, recorded transport
phase and a fixed error category. Optional provider counters are local
observations; request bytes and counts are not token-budget or currency accounting.
Phase is shown only when recorded. An active request may have no finish timing yet.

The panel distinguishes an owned active worker from an unresolved request after
it exits. A present hold that cannot be linked to the selected run stays visibly
present and continues blocking new work. A saved response proves that a response
was recorded; it does not establish task correctness or authorize clearing a hold.
Older runs display **Not recorded** for missing measurements. Missing or damaged
diagnostics are flagged for inspection without rewriting historical records.

New diagnostic fields are bounded and omit prompts, source, paths, model names
and exception text. Existing private run files still contain project content and
must remain private. The summary uses at most 16 request rows and the first 256
events, reporting when that event limit is reached. Viewing diagnostics performs
no provider request, retry, replay or recovery. The existing hold remains in place.

## Search and filter saved run history

Choose **Search run history** in the sidebar. It opens the existing read-only
Compare panel, waits for the earlier live update, and pauses normal polling.
Opening the panel does not submit a search. Enter literal, case-sensitive text
from a run ID or saved task goal, optionally choose a saved project ID/outcome,
then explicitly **Search saved runs**. Empty text includes all inspected records.

Project choices come from saved metadata, including historical projects that are
no longer configured. Missing or invalid recognized values appear as Unknown;
stored outcomes are observations, not live process or provider status. Search
examines complete valid saved goal fields before clipping result labels, so a
match beyond the beginning of a long goal can still be found. No regex, case
folding or Unicode normalization is applied. Counts distinguish inspected,
matched and returned rows. Catalog or result limits are explicit; a partial
inspection does not establish globally complete or newest history.

Select a result, then explicitly **Review selected saved metadata** to see its
complete cleaned goal, saved project/outcome/time and current record/history
hashes. It reads only saved job metadata, not source, task definitions, results,
events, holds or worker processes. It writes no record and never changes Task,
model, selected project or Run admission.

Explicitly **Use selected run as Left** or **Use selected run as Right** to
recheck the saved metadata and fill only that comparison slot. Choose the other
side deliberately, then use the existing **Compare saved runs** action to read saved
checks/results/diff evidence under its own unchanged guards. Handoff does not
submit Compare or choose another run to make a pair. Metadata review does not
replace full saved-evidence comparison.

Typing or changing filters sends no request and discards old results/details.
**Clear history filters** resets them without searching. New search, selection,
comparison context or panel navigation invalidates dependent observations; stale
responses cannot fill an old selection. Closing returns to the existing live
view and resumes its normal updates. Read-only search/review/handoff can remain
available under an unrelated admission hold while Task and Run stay blocked.

Each inspection admits at most 200 exact job names and 1,024 directory entries,
with one lookahead entry to detect truncation. Only guarded owner-private regular
single-link job JSON is read: 32,768 bytes/record and a 2-MiB logical read budget
per inspection, including refusal-byte reservation. Each operation performs two
inspections and checks the observed raw history pin again. Up to 100 result rows
are returned, reduced further when necessary to fit the 65,536-byte response;
the true inspected-set match count is retained. Query text is 0–128 UTF-8 bytes,
without NUL/newlines/invalid Unicode. HTTP input is at most 32,768 bytes. Labels
are at most 160 UTF-8 bytes with explicit clipping; selected metadata review can
return the full bounded goal. Malformed, unsafe or oversized records refuse
without repair, cleanup or fallback. These sequential observations assume trusted
stable single-owner storage and are not an atomic multiwriter snapshot.

Queries, goals, saved IDs, metadata, comparisons and hashes contain private
project context. Keep real histories and evidence out of public uploads.

## Review one saved run

Search saved history, explicitly select a result, then choose **Review selected
saved evidence**. The selected run's metadata/history pins must still match.
The read-only panel shows its saved goal, approved relative file scope and
fingerprints, editable-file choices, check specifications and budgets, recorded
check counts/outcomes, historical request diagnostics and bounded patch preview.
These are saved observations, not current project correctness or live worker
status. A recorded response is not proof that a task succeeded or that an
unsettled provider request finished. No private source file is opened.

The HTTP saved-review response is version 2, with the existing summary and
diagnostics plus a decision object. The explicit three-pin request is unchanged;
search, metadata-open, Compare and stored receipt formats are unchanged.

The saved review decision card uses the existing review receipts:

- **Unreviewed**: a safe present run has a complete empty receipt catalog.
- **Accepted** or **Rejected**: the saved verdict binds to the currently observed
  canonical result and complete patch hashes.
- **Stale**: a valid saved verdict names different current artifact pins.
- **Unknown**: receipts/catalog/artifacts are missing, invalid, inconsistent or
  limited; an earlier acceptance is not used as a fallback.

The card preserves a valid highest observed receipt's note, time and hashes when
available. Under a partial catalog it is an observed receipt, not a claim about
the globally latest decision. The result-content hash follows
sha(canonical(parsed result)), matching the existing writer; the existing raw
result-file fingerprint remains separate. Whitespace-only JSON formatting can
change that raw fingerprint without making the recorded decision stale. Valid
note text is rendered literally. A saved acceptance does not establish author
authenticity, live correctness, source adoption or export eligibility.

Missing or malformed optional records remain Unknown with finite notes. Failed,
uncertain, running and legacy observations remain as saved; review does not
repair records, retry a run or inspect or clear a hold. Historical diagnostics
omit live-state and hold fields. Missing task budgets are Unknown rather than
defaulted to an invented allowance. The complete bounded saved goal is retained;
patch clipping and incomplete evidence are explicit. Raw prompts, responses,
exception text, check output, private extra fields and absolute source paths are
excluded from this response.

This action is separate from **Review selected saved metadata**, the Left/Right
handoffs and **Compare saved runs**. It changes none of those selections and
never starts Run, checks, Git or a model. Changing search text, filters, selection
or navigation discards old evidence; stale responses cannot fill an old view.
An unrelated admission hold may leave saved review available while Task/Run stay
disabled. Review writes no index, token, cache, job or history record.

Each evidence inspection reads task/result files up to 32,768 bytes each and
patch bytes up to 65,536, with at most 8,192 UTF-8 bytes displayed. It admits at
most 256 event names while processing at most 1,024 directory entries, with one
lookahead for truncation. The same pass independently catalogs up to 100
canonical review receipts; an event limit cannot silently hide later receipts.
Each receipt is at most 32,768 bytes, with a separate 256-KiB aggregate logical
read budget. Invalid names, gaps and partial catalogs are explicit. Admitted
unread receipts still undergo safety/identity checks after budget exhaustion.
Events are limited to 262,144 bytes each and a 2-MiB
aggregate read budget including refusal-byte reservations. Oversized records
produce limit notes; only a bounded prefix and file identity are pinned, never
an unbounded full-file hash. Admitted events skipped after the byte budget is
spent still undergo safety and identity checks without reading contents.
Unsafe links, ownership, modes, multiple links or
changed evidence refuse review. Both saved evidence and bounded metadata history
are inspected twice. These bounds apply per inspection, not to the entire
request. The response is at most 65,536 bytes and refuses if its complete
sanitized content cannot fit. Sequential pins assume trusted stable single-owner
storage and are not an atomic multiwriter snapshot.

Real saved tasks, names, goals, hashes, diagnostics, results, review notes and patches contain
private project context and stay outside public source uploads.

## Inspect earlier saved reviews

After explicitly reviewing one saved run, choose **List saved review history**.
Select one observed receipt, then choose **Inspect selected historical review**.
The current decision card stays separate and unchanged. Reading an earlier
acceptance never replaces the highest observed decision or enables export.

Entries are ordered by canonical receipt filename ordinal, not wall-clock time.
The list contains at most 100 observed receipt descriptors; notes are returned
only for the explicitly selected entry. Missing, malformed and read-limited
entries retain fixed status labels without echoing corrupt contents. Missing,
partial or invalid catalogs are flagged; the list does not claim globally
complete or latest history. A valid observed note is displayed literally in full,
including Unicode and control characters, without treating markup as HTML.

Each usable entry separately reports whether its recorded artifact hashes match
the currently observed canonical result and patch, differ from them, or cannot
be compared. This relation is historical evidence, not a human verdict, current
source check, authenticity proof, adoption approval or export eligibility.
The canonical result hash follows the existing writer and ignores JSON
formatting; the raw result-file fingerprint remains separate evidence.

List and detail are explicit read-only requests bound to the saved run ID,
metadata, metadata-history and saved-evidence hashes. Detail additionally binds
the selected canonical receipt name. The server performs the existing bounded
safe inspection and rechecks evidence and metadata history before returning.
No source, current hold, provider or process is inspected; no new review,
index, cache, token, check, worker or export is created. An unrelated hold may
leave these reads available while Task and Run remain blocked.

Changing search/filter/selection or saved-review context, closing navigation,
a refusal or restart discards old history and detail. A new explicit saved review
and list are required after stale evidence; there is no automatic retry or
fallback. Requests are limited to 32,768 bytes and complete canonical responses
to 65,536 bytes. Existing per-inspection catalog, file, logical byte-budget,
owner-only no-follow and double-check limits remain as described above.
These sequential observations require a trusted stable single-owner store.
Keep real verdicts, notes, receipt names, times and artifact hashes private.

## Compare saved runs

Choose **Compare runs**, select two different saved-run IDs, then press
**Compare saved runs**. The panel reads only saved private metadata, task,
result, event and patch records. It does not read the current project source,
run checks, contact a model, reconcile workers, inspect or clear holds, repair
records, apply a patch or export one. An unknown run or unsafe data store is
refused with a fixed message.

The normal live-run polls pause while comparison is opening or open. Opening
waits up to ten seconds for an existing poll to finish, with Close available to
cancel the wait. **Close comparison** returns to the usual live view and resumes
its normal polling and state reconciliation. A comparison's saved `RUNNING` or
uncertain state is shown as recorded; it is not a current process observation.
Changing either selected ID discards the displayed comparison. Selections are
retained across reopen, and late responses for old selections are ignored.

The two sides show saved goals, outcomes, task/start/revision fingerprints,
selected baseline hashes, edit permissions, fixed check specifications and
recorded baseline/final check results. **Comparable recorded tasks** means the
available task evidence agrees on project, goal, file paths, baseline hashes,
editable scope, checks and budgets, without a fingerprint mismatch or incomplete
loader evidence. Differences are listed explicitly. A legacy start fingerprint
remains `NOT_RECORDED`; equality of saved task bytes does not reconstruct proof
of what an older run started with.

Measurements count recorded request starts, total serialized request-body bytes
when complete, and the sum of recorded request times. They are not token or
currency estimates, total task wall time, provider-completion evidence or a
model ranking. Deltas are right minus left. Legacy, corrupt or partial records
keep missing totals and deltas **Unknown**, rather than inventing zeros. An
explicitly evidenced refusal before sending any chat request can record zero
attempts. Different models or backends can be displayed without a quality score.

The saved-run inventory inspects at most 200 matching metadata files and returns
the latest 100 within that inspected set. A partial-history flag warns when more
records may be omitted; it does not promise the newest 100 across the entire
store. Directory enumeration also stops after 1,024 entries. Dropdown labels
are clipped safely to 160 UTF-8 bytes when needed, with a note; comparison shows
the full bounded saved goal.

Metadata, task and result sections each have a 32,768-byte read limit. At most
256 event files are considered, with 262,144 bytes per event and a 2 MiB aggregate
read budget. Unavailable, invalid or oversized sections become Unknown with
fixed notes. Only defined display fields are returned: raw check output,
provider payloads, prompts, response bodies and exception fields are excluded.
Saved goals, relative paths, model labels and patch text are still private
project evidence and must remain outside public uploads.

Each saved patch is read up to 65,536 bytes and displayed up to 8,192 UTF-8 bytes.
The literal saved patch-text difference is limited to 16,384 UTF-8 bytes and
240 lines; clipping is explicit and preserves Unicode boundaries. The serialized
comparison response is capped at 131,072 bytes. A patch difference compares saved
text only; it does not validate the patch against current source or authorize
adoption.

Reads are anchored at the private data root and reject symlinks in every path
component below it, including substituted `jobs`, `tasks` or `runs` directories.
The data root and its ancestors must remain trusted and stable. Reading saved
files sequentially is not an atomic snapshot or a multiwriter transaction;
concurrent changes can make the available evidence inconsistent.

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

## Run one offline browser workflow

The offline harness creates an entirely new private acceptance workspace. It
accepts only its own pinned fixture; it cannot adopt an existing project or
normal Workbench data directory. Initialize a new absolute path outside source:

```sh
python3 -B offline_workflow.py init --work-dir /absolute/new-private-workflow
python3 -B offline_workflow.py serve --work-dir /absolute/new-private-workflow --port 0
```

Open the printed loopback URL. Keep **Arithmetic demo**, **Scripted exercise · no
inference** and its original Task. Click **Run task** once. Follow the normal
history and plan, inspect baseline, agent and independent final checks, and
review the addition-only diff. Explicitly accept the current result/patch, then
download the reviewed patch. Nothing is applied to the original project.

The harness allows one scripted attempt per initialized root. It retains its
claim after a refused spawn, failure or interruption; it offers no reset or
automatic retry. Finish the child before stopping the server. Restart the same
serve command, reload the new session in the browser and select the same run to
verify retained history and review. Restart does not start another worker.
Keep the server in the foreground. Ctrl+C stops its owned child and listener;
interrupted evidence stays retained and does not establish successful acceptance.
This restricted QA server allows only the required Run, history, review, export
and saved-review routes. Other visible controls, including project setup,
refresh, workspaces, presets and Compare, refuse here.

Inspect the actual saved result and, optionally, the downloaded patch:

Keep the original browser download receipt. Stage its exact bytes as an
owner-0600 regular single-link file in an owner-0700 private folder outside the
fixture, with no symlink path components. The inspector checks these storage
requirements as well as the patch bytes and hashes.

```sh
python3 -B offline_workflow.py inspect --work-dir /absolute/new-private-workflow \
  --download /absolute/private-downloaded-patch.diff --require-accepted
```

Java checks are an independent explicit action on separate invented selected
files, using an already installed JDK:

```sh
python3 -B offline_workflow.py java-check --work-dir /absolute/new-private-workflow \
  --jdk-home /absolute/jdk
```

Java results are compile/protected-main evidence, not a Java agent or model run.
The Java check is also once-only per initialized root. A failed, partial or
JDK-refused attempt stays retained; there is no reset or automatic retry.
The Python worker uses the unchanged deterministic ScriptedDemo under additional
child-side provider/HTTP/socket guards. Those Python-level guards are not an
operating-system-wide network audit. Normal history and run updates stay active;
the harness does not substitute an empty feed. Session tokens are never printed.
Keep fixture configuration, runtime records, source copies, logs, claims,
diagnostics, check output, review/export receipts and downloaded patches private.
See [VALIDATION.md](VALIDATION.md) for the qualified scope and retained outcomes.

## Run acceptance checks

Use a shell with umask 022 for the complete suite: an existing negative
permission test deliberately creates a 0755 directory, which a more restrictive
mask changes. The subshell keeps this setting local to the command. Place the
new acceptance directory under an owner-only private parent.

```sh
(
  umask 022
  python3 -B qa_agent.py --jdk-home /absolute/jdk \
    --work-dir /absolute/new-private-acceptance
)
```

Final v0.26 offline qualification passed 1,117 unit methods across 50 suites, including
snapshot workspace, snapshot export and selected-project engine/controller/HTTP
regressions. The runner compiles the Java client with Java 17 compatibility and
warnings as errors, compares Python/Java scripted results,
and runs actual isolated checks. Acceptance covers namespace boundaries,
time/output limits, Java compilation diagnostics and protected-main execution,
prerequisite reporting, an owned Git-workspace worker, accepted-patch rechecks
and preservation of the original project Git state.

Invented Python and Java refresh fixtures run actual isolated baseline checks,
are corrected manually by the acceptance script, then pass final checks after a
reviewed hash revision. Goal-only revisions, restart persistence and refusal of a
stale refresh save are also checked. Comparison acceptance uses invented saved
Python/Java JSON histories, with guards against live-state, check, process and
provider paths and unchanged saved-file/hold hashes. These histories are not
model-generated results. Readiness acceptance uses invented configured Python
and Java projects, executable-presence stubs that are never run, source/config
drift, a missing Java compiler and a separate synthetic hold. Each inspection
preserves private file hashes and performs zero checks or model requests; the
runner's existing actual isolated checks remain separate. Bundle acceptance
uses invented accepted Python/Java artifacts and an unrelated synthetic hold,
verifies deterministic private archives, and refuses changed pins/source while
preserving private bytes. It performs no checks or provider requests. The
new bundle/project acceptance prepares baseline, candidate, mixed, different and
missing-source observations, checks configured-pin separation and config drift,
and retains the unrelated synthetic hold without inspector writes or execution.
Bundle-workspace acceptance reruns actual configured Python/Java checks in
separate private Git worktrees, preserves original source/Git bytes and unrelated
files, and retains a failed-check job and an owned-worker interruption without
retry. Saved bundle rows remain invented evidence, separate from these reruns.
Workspace-recheck acceptance edits only private worktree fixture files, runs
actual fixed Python/Java checks against separate pinned snapshots, preserves
creation evidence and earlier results, and retains failed/interrupted attempts
without retry or source adoption.
Snapshot-export acceptance uses invented Python/Java projects with actual initial
and snapshot checks performed separately. It reviews and accepts the tested
snapshots, verifies deterministic four-member archives and the combined initial
fix/manual-edit patch, and guards the export path against checks, Git execution,
provider requests and existing-record writes. It preserves source/Git, creation,
recheck and unrelated synthetic-hold bytes, refuses changed snapshots and stale
history pins, and keeps notes in private acceptance records outside the ZIP.
Snapshot-workspace acceptance imports tested Python/Java exports into new private
Git worktrees and runs their fixed isolated checks again. It verifies exact
selected snapshot bytes and uncommitted diffs, preserves original source/Git and
earlier records, and retains a deliberate failed-check workspace and an owned
worker stop without retry. These fresh checks remain distinct from the archive's
recorded observations. The final qualification retains all earlier client,
isolation, prerequisite, time/output, Git and preservation probes. See
[validation and limits](VALIDATION.md) for the preserved development failures,
final run and browser-review scope; these are local results, not a CI claim.
Editor acceptance loads and previews exact selected-file replacements under guards
against execution, explicitly saves only the target and new private journal,
refuses pre-edit attempts, runs separate actual Python/Java rechecks and exports
strict v2 packets. It verifies original source/Git and prior-evidence preservation,
then retains a separate synthetic hold and refuses another save without writes.
Editor integration tests cover exact Unicode/CRLF bytes, stale controls, saved
admission, one-use previews, restart, uncertain writes, partial records, bounds
and a new-attempt requirement even after a byte-identical revert.

Workspace-search acceptance navigates actual checked invented Python/Java
workspaces through protected excerpts and pinned editable handoff, performs an
explicit editor save, refuses old search pins, then runs fresh fixed checks and
reviews/downloads private v2 exports. Guards prove navigation performs no checks,
Git, providers, worker reconciliation or saved-record writes. A retained unrelated
synthetic hold allows navigation while refusing a save. Unit/controller/HTTP
checks separately exercise scope, source/config/Git/journal drift, Unicode and
line endings, result bounds, races, restarts, framing and route-specific caps.

Preset-comparison acceptance exercises invented Python/Java save/list/preview,
exact current-draft and saved-goal hashes, unchanged definitions/private bytes,
separate explicit Load, restart persistence and retained unrelated holds. It then
runs separate fixed checks against selected copies with unchanged scope/checks
and loaded goals. Preview itself starts no agent, check or model request. Browser
qualification also covers empty and identical drafts, Unicode highlights, literal
markup text, Close and input invalidation, scripted read-only Task and held Run.

Run-history acceptance uses invented Python/Java saved observations for literal
full-goal and ID search, project/state/unknown filters, pinned metadata review,
deliberate comparison handoffs, separate explicit Compare, restart and retained
holds. Saved outcomes are seeded observations, not executed agent results.
Separate actual fixed checks pass on selected Python/Java copies. The final
v0.22 frontend passed 183 isolated Node validator/handoff checks and browser checks
for explicit actions, Unicode, literal markup, local invalidation and held-state
review. The browser fixture stubs the normal live history feed empty to isolate
this panel; it does not qualify live worker reconciliation. See validation for
the frontend-only amendment and retained test-collector corrections.

Saved-run-review acceptance covers nine invented Python/Java ready, failed,
uncertain, running, legacy, corrupt and unknown saved histories, separate explicit
Compare consistency and exact review/hash persistence after restart. It preserves
all source/config/task/record bytes and modes plus an unrelated hold, then runs
independent fixed checks on selected copies. The final v0.23 frontend passed 189
isolated Node checks, including actual pure-helper Python/Java/legacy response
compatibility. Browser checks cover complete goals, scope, check specifications,
results, diagnostics, patch text, separate metadata review, missing budgets,
stale-history refusal, restart and held-state review. The live history feed is
stubbed empty in that browser fixture; qualification does not establish live
worker reconciliation or real-model completion. VALIDATION.md records all limits
and retained collector corrections.

Version 0.26 adds 21 pure history methods and 17 controller/HTTP methods.
Its final isolated frontend passes 624 checks: 255 inherited and 369 history
checks, including actual pure-helper and guarded controller DTOs. New acceptance
lists and inspects 16 invented Python/Java histories, preserves the current
decision and private bytes through restart, reads the earlier actual accepted
scripted receipt without another worker/check, and runs separate selected-copy
Python/Java checks. Browser checks use an intentionally empty normal feed;
VALIDATION.md records that limit, the retained socket-denied sandbox attempt,
corrected frontend collector, native completion and two blocked unclassified
browser routes. These local checks are not a GitHub CI or real-model claim.

The runner makes no AI inference requests. The
demo's `test_calculator.py` is intentionally failing before a task; use the acceptance runner rather than unrestricted test
discovery across the entire repository.

Real-model browser acceptance is a separate, explicit task; see
[VALIDATION.md](VALIDATION.md) for the observed result and its narrow coverage.
Snapshot-project acceptance separately creates actual checked Python/Java
snapshots, then compares their private exports under guards against runtime
execution and writes. It checks baseline reconstruction, tested/different/missing
observations, project drift and preservation; the inspector performs no checks
or model requests of its own.

Version 0.26 adds no real-model qualification. The offline harness, saved-run reviews, preset previews, named task presets, snapshot review workspaces,
snapshot exports, workspace rechecks, bundle review workspaces, project checks,
bundles, readiness,
comparisons, refreshes and context
tools do not determine the cause or provider completion of the preserved
uncertain Java trial from version 0.3.

## Publication and licensing

This repository contains reviewed reusable source, invented fixtures, and public
instructions. Private configs, host paths, run history, prompts, model responses,
logs, credentials, project data, real preset names/goals/records, model weights, runtimes, and private review
receipts are excluded. No open-source license has been assigned to this source;
public visibility does not grant a general reuse license. See
[ORIGINS.md](ORIGINS.md) for attribution and licensing status.
