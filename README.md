# OUTLANDS Agent Workbench

A local browser workspace for the OUTLANDS Coding Agent. Choose an explicitly
configured project and local model, follow the plan and checks, inspect the diff,
then review and download a patch. The agent edits a private copy; it never applies
the patch to your project.

Version 0.10 adds **Bundle Project Check**: compare a verified private bundle
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

## Run acceptance checks

```sh
python3 -B qa_agent.py --jdk-home /absolute/jdk \
  --work-dir /absolute/new-private-acceptance
```

This runs 416 unit methods: the prior 377, 24 bundle/project engine/CLI methods
and 15 controller/HTTP methods. It compiles the Java client with Java 17
compatibility and warnings as errors, compares Python/Java scripted results,
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
The runner makes no AI inference requests. The
demo's `test_calculator.py` is intentionally failing before a task; use the acceptance runner rather than unrestricted test
discovery across the entire repository.

Real-model browser acceptance is a separate, explicit task; see
[VALIDATION.md](VALIDATION.md) for the observed result and its narrow coverage.
Version 0.10 was tested offline only. Bundle/project checks, bundles, readiness,
comparisons, refreshes and context
tools do not determine the cause or provider completion of the preserved
uncertain Java trial from version 0.3.

## Publication and licensing

This repository contains reviewed reusable source, invented fixtures, and public
instructions. Private configs, host paths, run history, prompts, model responses,
logs, credentials, project data, model weights, runtimes, and private review
receipts are excluded. No open-source license has been assigned to this source;
public visibility does not grant a general reuse license. See
[ORIGINS.md](ORIGINS.md) for attribution and licensing status.
