# Version 0.29 validation

## Recheck reliability amendment

All **1,214 unit methods across 56 suites passed** on the amended source. A
separate fresh targeted Python/Java workspace and snapshot recheck qualification
passed, followed by a **fresh complete native acceptance PASS**, including the
previously blocked dependency path and the v0.29 Run/Stop case. All **128 code,
static and example pins** remained unchanged during qualification. These are
local offline results, not GitHub CI or real-model qualification.

The initial v0.29 full acceptance run remains FAILED and retained. Its traceback
identifies a guarded-read/parse refusal before schema/ID validation, but does not
retain the underlying exception. Later saved receipts are complete JSON with
VERIFIED status. Those later bytes do not establish what the failed read saw.
The original runtime cause remains **unconfirmed**; a new PASS does not relabel
that earlier run. Its complete worker-exit audit remains unverified.

A fresh deterministic synthetic case proves a concrete source defect class:
os.replace can unlink an opened regular receipt between open and fstat. The old
reader rejects that descriptor with INPUT_TYPE. Only recheck_view now opts into
one reopen after the first descriptor is both regular and has zero links. It
never reads the unlinked descriptor. The newly named file must pass the existing
no-follow/nonblocking, regular/single-link, bounded-size, NUL/UTF-8 and later
schema/ID guards. A second unlink, malformed or unsafe replacement still refuses.
There is no cached result, sleep, task retry, execution or record rewrite added
by this bounded reread. Other callers retain a single-open default.

Four new regression methods use invented Python/Java receipt shapes and fake
live/exited children without a worker, Git, project check, compiler or provider.
They cover valid replacement, malformed JSON/schema/IDs, binary/UTF-8/size bounds,
multiple links, symlinks, directories, missing files, a second unlink, descriptor
closure and unchanged defaults. The unchanged source failed these new cases as
expected. The first corrected integration run exposed a real directory-descriptor
leak: fdopen could raise before the old context closed its successful open. That
failed result and source are retained. Explicit descriptor ownership now closes
on every path, and the unchanged regression suite passes **25/25 methods**.

The first focused native attempt was refused by the tool sandbox's Bubblewrap
network-namespace restriction: infrastructure_error was true and zero project
tests ran. It remains FAILED. A distinct fresh fixture with required namespace
support passed actual Python/Java checks, intentional failed-check and owned-stop
cases, source/Git preservation and earlier-evidence preservation. The complete
runner then passed on another new fixture. Its collector observed no residual
command lines naming that fresh root after exit; this bounded observation is
not an operating-system-wide worker-exit or packet audit. No earlier failed
workspace was reopened through Manager, repaired, reset, adopted or cleaned up.

Earlier actual Live Run/Stop browser observations below apply to the **initial
v0.29 source**. The merged recheck backend has separately passed the dated browser
verification below. Browser HTML/JavaScript/CSS remain unchanged. Real records and
generated fixtures stay private. The original uncertain Java trial remains
held/unqualified, no Java agent or real model is qualified, and licensing remains
UNASSIGNED. These validation observations include no release or deployment.

## Post-merge Python/Java browser recheck verification

On **2026-11-13**, fresh browser verification used the unchanged 132-file source
at merged commit `a510c235e8b963d67d526f122f09f107f5652dd7`. A private allowlisted
loopback wrapper served the normal `Manager`, `make_handler` and unchanged UI.
The production CLI was not used; the wrapper avoided its server-info write.
Private helpers, fixtures and actual records remain outside public source.

The target history was genuinely empty, with no feed stub. Invented recorded
bundles supplied separate actual creation checks. One manual Unicode comment was
added to each editable private worktree. Through the browser, exactly two recheck
previews and starts launched two workers, Java first and Python second. The
browser observed PREPARING and then VERIFIED with owned_active false for both.
The Java check ran one test and the Python check ran four; both exited zero with
no infrastructure error, timeout or output truncation. These are fixed-check
results on invented source, with no model or coding-agent execution.

After settlement, a fresh-token server session and browser reload performed only
GET history/detail inspection. It made zero POST, preview, start, spawn, provider,
agent, check, review or export operations. Two final global-history response bodies
and two selected-detail response bodies had exactly the same hashes across
restart. All 204 file rows and 149 directory rows, including their modes, were
unchanged during read-only restart. All 188 initial file bytes/modes were
preserved; the live rechecks added only 16 files within the workspace-rechecks
store. All 132 source hashes remained unchanged throughout acceptance, before
this documentation update.

Both temporary owned listeners were closed, with ECONNREFUSED observations. Root
compared only the original uncertain Java trial's two authorized preservation
hashes; both remained unchanged. The browser phases requested no adoption, commit
or export; private setup bundle preparation remains separate. No new Live Run/Stop
case, real-model request or Java-agent trial was performed. The prior 1,214-method,
56-suite complete native qualification remains separate evidence; this browser
verification adds no new unit-test or GitHub CI claim. The original failed runs,
unconfirmed historical cause and earlier worker-exit audit limits remain intact.

## Normal server-CLI observations and retained observer limits

On **2026-11-13**, two normal `workbench.py serve` sessions used the unchanged
132-file merged source at `6ef01d96e60e9e35e7a254b5c9cedc6471997217`. The product
CLI, Manager, handler and browser feed were not patched or replaced. External
process/connect tracing observed the CLI and its descendants. The `launch.py`
prerequisite doctor was not run; it performs a separate isolated check and
therefore is outside this zero-task/check startup observation.

A fresh private fixture contained only explicitly invented terminal metadata and
tasks for Python and Java profiles. The browser freshly loaded each session and
selected Java, then Python. Both rows displayed FAILED, 0/12 turns and Scripted /
no inference. Result and patch pins stayed Pending; Accept, Reject, Download and
Git workspace creation stayed disabled. These are seeded saved observations,
not executed failed agent runs or failed tests. Browser actions were read-only;
no task Run or Stop action was requested.

An independent API client made four GET requests per session: the normal index,
history and the two selected run views. The three API response bodies matched
exactly in hash and byte length across restart. Fresh session-token hashes
differed, so the token-bearing index bodies were expected to differ. The client
saved hashes and finite labels without raw tokens or response bodies; its HTTP
observations remain separate from visible browser evidence.

The initial case had 16 files and 22 directories. After both sessions it had 17
files and the same 22 directories. The only allowed product-file change was
normal creation, then replacement, of the configured data directory's
`server-info.json`, containing exactly the current loopback URL and owned CLI
PID. Every other file byte, mode and link
count remained unchanged. All 132 source hashes stayed unchanged during the
observations, before this documentation update. Private session/audit artifacts
were outside the product fixture and remain excluded from public source.

Both owned CLI processes shut down through normal SIGTERM handling and exited
zero; all 40 first-session and 50 restart process/thread traces ended with
zero-exit records. No
containment or adopted-child cleanup was used. Both owned listeners subsequently
refused connections with ECONNREFUSED. Each session trace recorded one initial
CLI execution, no additional execution or non-thread child creation, and no IP
or other connect calls beyond four failed AF_UNIX attempts to the local nscd
socket, each returning ENOENT. This is scoped process/connect evidence, not an
operating-system-wide network or worker-exit audit.

The first external supervisor required zero connect calls of any kind and
therefore refused those four failed local probes. Its original summary remains
FAILED/unqualified. Later independent saved-trace classification and bounded
closure review cleared the one planned restart; the first session was not rerun
or relabelled. The revised external classifier accepts only the exact failed
local nscd calls, bounded to four, and the restart summary qualified. Product
source and handler behavior were unchanged by that observer correction.

A later static review found two limits in the private restart gate: an
alternative qualified=true branch would skip the separate review requirement,
and the gate did not explicitly compare its mirrored first summary. That review
arrived after restart had launched. Root then independently confirmed the actual
mirror was byte-identical to the original first summary, both remained
unqualified, and all recorded pins matched. The private helper was retired
unchanged and is not public source. Those checks address the actual observed
path; they do not qualify adversarial gate inputs, the alternative branch or
concurrent mutation. No blanket gate PASS is claimed.

Private observer setup refusals before a runtime claim remain retained. No task
worker, project check, provider/model request, JDK or Git command, new Live
Run/Stop case, adoption or export was performed by these sessions. Root's final
closure record preserves the two original authorized Java hashes and existing
tool pins. The original uncertain Java trial remains held/unqualified. Earlier
1,214-method/56-suite complete native qualification, all historical failures and
unconfirmed causes remain separate. No new unit-test, GitHub CI, real-model or
Java-agent qualification, code feature, deployment or license change follows.

## Separate launcher check-only prerequisite observation

On **2026-11-13**, one unchanged `launch.py --check-only` invocation used the
132-file source at merged commit `e45a27ce1dc8a007c0366ebc64c04346f8953341`, a
fresh private workspace path and no model or JDK configuration. It returned PASS
and exit zero, with no launcher stderr, outer timeout or containment. All 132
source hashes matched before and after, before this documentation update, and
the requested workspace remained absent. The earlier server-CLI observations
did not run this separate doctor.

The launcher inspected Git's version and its unchanged PASS condition requires
exactly one isolated Python prerequisite unittest, exit zero and no timeout,
output-limit or infrastructure-error flags. That source gate establishes the
count of one; the normal CLI does not expose the raw isolated unittest output.
No raw host versions, private paths or runtime identifiers are published here.

The product normally removes its fresh disposable self-test directory and
temporary check-output file. The trial's temporary area was empty at closure.
This expected cleanup is distinct from the private launcher stdout, stderr,
process result and source-pin evidence, which remain retained. It does not
remove or relabel any earlier failed fixture. Failure detail from this CLI is
sparse; the PASS does not reconstruct historical failure causes.

This qualifies only that prerequisite configuration. No workspace initialization,
full launcher handoff, server, provider, JDK, project check, model or coding agent
was exercised. It adds no Git project-operation, unit-suite rerun or GitHub CI
qualification. The earlier 1,214-method/56-suite native result, observer/gate
failures and limits remain separate; the original Java hold and UNASSIGNED
licensing remain unchanged.

## Separate full launcher handoff observation

On **2026-11-13**, one unchanged full `launch.py` invocation used the 132-file
source at merged commit `951e46b4c2d427429ad417341169dc0447f0d1fe`, a fresh absent
private workspace and no model or JDK. It produced the doctor PASS line followed
by the normal server URL. The same owned PID and process start stamp survived
execve, with the exact expected `workbench.py serve` command after handoff.

The doctor inspected Git's version and its unchanged PASS gate establishes one
isolated Python prerequisite unittest with the required passing flags. Raw
isolated unittest output is unavailable from the normal launcher. The product
removed its disposable self-test/output files; the temporary area was empty at
closure. Private launcher logs, ready/result records and the new workspace remain
retained. The earlier check-only observation remains a separate trial.

Genuine demo initialization created six files and 18 directories, including the
workspace root. Configuration had no models and one Arithmetic demo project;
the two project files and task matched the source fixtures exactly. All 15 data
stores remained empty. The browser loaded Arithmetic demo, Scripted / no
inference and history zero, with no feed patch. No task Run or Stop was requested,
and the tab was closed before server shutdown. The copied calculator fixture is
intentionally initially failing; no project tests were run or fixes inferred.

Normal SIGTERM server shutdown exited zero, the owned listener refused a later
connection with ECONNREFUSED, and launcher stderr was empty. No recorder
containment was used. Ready and closed workspace snapshots had identical bytes,
modes and link counts. All 132 source hashes matched before and after, before
this documentation update. Root's two authorized original Java preservation
hashes also remained unchanged.

This observes only demo setup without a configured model, process handoff,
browser loading and shutdown. It adds no task, model, JDK, real-project, Git
project-operation or GitHub CI qualification, and no syscall or broad descendant
audit was performed. Raw host versions, paths, process/port/token values and
runtime records remain private. Earlier failures, observer/gate limits, unknown
causes and the 1,214-method/56-suite native qualification remain separate. The
original uncertain Java hold and UNASSIGNED licensing remain unchanged; no code
feature, deployment or license change is introduced.

## Scope and evidence classes

Four new source modules provide a separate live Run/Stop QA wrapper, native
acceptance and two regression suites. The existing runner adds the suites and
calls the new acceptance stage last. The public snapshot has 132 files, including
128 qualified code/static/example inputs. Relative to the initial v0.29 draft,
the amendment changes only workbench.py, its existing recheck integration suite
and three documentation files. The shared guarded reader closes every opened
leaf descriptor, and only recheck_view opts into one reopen after a regular
opened descriptor is found unlinked. Other reader defaults and strict receipt
validation remain. Agent execution, admission logic, providers, Java client,
workers, other readers, review writers, export gates and browser JavaScript/CSS
are unchanged. No dependency or service is installed.

The wrapper creates its own new private root around a new unchanged v0.28 Stop
fixture. It reuses the original logical-command validation, source fingerprints,
argument/environment/log checks, PID custody, parent handshake and fixed
controlled child. The inherited worker's finite armed lifetime remains 30
seconds. The new manager has a separate 25-second window from its start intent.

The controlled process executes no agent, model or project check and creates no
agent result, run directory, event, patch or human review. Unit/integration tests
use explicitly labelled fake children and fabricated receipts. Those tests do
not establish native signal delivery or a real browser workflow.

## Running-response and owned-Stop gate

The original authenticated normal handler first sends the actual successful
Running run-view body. Only after its write returns can the wrapper publish a
source/control/ID/PID-bound response receipt. History-only or direct Manager
inspection, missing/wrong session, failed response writes and unrelated paths
cannot arm Stop. A server-write return does not prove client delivery, rendering
or a human observation.

A separate append-only armed-stop receipt links that response to the unchanged
worker's armed checkpoint. One explicit Stop checks ownership, source/control,
linked receipts and the finite deadline. A bounded wait of at most one second
within that same Stop accommodates the short worker handshake; it sends no
additional Stop signal and retries no publication. Torn, missing, unsafe or
stale evidence cannot qualify.

The 25-second monitor and ordinary server close use containment, recorded
separately from the explicit owned Stop. Expiry, gate failure, containment or
missing exit evidence remains Unknown/unqualified. The unchanged worker retains
its independent finite lifetime if monitor custody is incomplete.

The corrected wrapper observes original receipt publication before invoking the
unchanged strict validator: missing/staged final records and an exact same-inode
two-link commit window remain pending. Foreign links, unsafe modes/ownership or
other custody errors refuse. Full original validation is still mandatory before
arming. Running-response capture validates source/control and inner workflow
inputs without walking the concurrently publishing worker-receipt catalog.

Unexpected readiness errors publish one fixed stage/type failure receipt and
disable qualification and explicit Stop; they do not silently end the deadline
watchdog. A child-poll error instead records unknown ownership and ends further
probing/signalling, because current liveness cannot be established. The original
worker's finite lifetime remains the backstop. No error text or private path is
copied into the failure receipt, and failed publication is not retried.

## Focused qualification and retained development evidence

The first focused fake-only run passed 21 methods. The second passed 24 methods,
adding a same-Stop readiness race, a finite missing-arm refusal and uncertain
armed-stop publication. The race test observes one signal after readiness; the
missing-arm case sends none. The uncertain publication leaves its staged receipt
and consumes its claim without overwrite, signal or favourable relabelling.

After the first native failure below, deterministic monitor tests retained three
expected assertion failures across 27 methods. The earlier fixtures used inert
threads and did not exercise the monitor. The new tests use bounded fake events,
real strict receipt readers and synthetic publications to reproduce the two-link
and disappearing-stage windows, and to require a durable failure/watchdog path.
They establish a defect class, not the actual native exception that was lost.

A later focused run retained one obsolete aggregate publication-count assertion:
the correction adds a distinct failure receipt. The test now requires exactly
one armed-stop publication attempt and one typed failure publication, with staged
bytes preserved and no signal or qualification. Final focused qualification
passed 32 methods, including setup pinning, unsafe ownership, initial poll errors, foreign
hardlinks and driver-read serialization. No native child ran in these focuses.

Before native qualification, independent review corrected a QA evidence label:
the history-state list now contains only actual history responses. The explicit
Stop response is recorded separately and is not invented as a polled history
state. The driver explicitly identifies its normal HTTP handler as in-memory
BytesIO execution, not a socket/client-delivery or browser observation.

The first qualification setup preflight refused two new staging intermediate
directories with inherited group-write mode 0775. Only those two source staging
directories were tightened to 0755; every source byte and validation guard
remained unchanged. That refusal occurred before a qualified-input receipt,
acceptance work directory, test or worker existed. Its evidence was retained,
and no actual task was retried, reset, adopted or cleaned up.

## Retained first native candidate

The first complete native runner passed all 1,202 methods across 56 suites and
reached the new final acceptance stage. That stage committed one Running response
but did not produce an outer armed-stop gate within its 20-second acceptance
deadline. It sent zero explicit Stop requests; the finally-close contained the
owned child. The original receipts show SIGTERM/exit 130 and the saved state is
Failed. That is containment evidence, not successful explicit Stop acceptance.

The original worker's armed receipt was valid when inspected afterward. The
monitor had no durable error receipt, so its exact exception remains unknown.
Static review identified silent monitor termination; strict-reader/publication
races are a supported explanation, not retrospectively proven native events.
The old code bytes, all 56 suite logs and the entire failed fixture were sealed.
Read-only diagnosis changed no fixture byte or mode, and no Manager, process
probe, provider, recovery, retry, reset or adoption was used on that fixture.

Corrected-source qualification uses a distinct new private workspace and fresh
fixture. It does not replay or relabel the consumed failed attempt. The native
driver now serializes readiness reads with the same manager lock used by the
monitor, releases it before waiting and propagates strict refusals without retry.

## Retained second candidate collector refusal

The corrected monitor completed the actual native Running-response/armed/explicit
Stop chain, with SIGTERM/exit 130, no containment and a Verified typed report.
All 1,208 methods in 56 suites passed. The overall runner still exited at a later
collector assertion comparing initialization rows across Manager construction;
it did not create its final acceptance report and remains a retained failed
qualification, with its verified process evidence recorded separately.

A fresh setup-only experiment established the assertion error without running a
child: Manager legitimately adds its data directory and setup files, changing
the existing workspace directory's link count from three to four. All seven
initialized regular files retain identical bytes, modes and links. The snapshot
helper includes directory link counts, so taking that baseline before Manager
setup imposed an invalid invariant. The correction preserves the initial file
pins across setup, then takes the complete runtime baseline before Run. The
subsequent settled and read-only restart comparisons remain strict.

Both consumed candidates, their code bytes, logs and fixture snapshots remain
private and unchanged. Final qualification uses another fresh corrected-source
workspace; it neither adopts nor re-executes either retained fixture.

## Initial complete acceptance failure (retained)

The initial v0.29 full runner passed all 1,210 unit methods but exited in the unchanged
inherited snapshot-recheck acceptance path with RECHECK_RECORD_INVALID. That
stage precedes the new v0.29 stage, so no v0.29 fixture or Run was consumed there.
The inherited failure, source bytes and logs remain retained. Its finally block
invokes Manager close; a separate audit confirming every inherited worker exit
was not performed. No reset, recovery, retry or favourable relabelling follows.

The targeted v0.29 qualification below is a separate first execution of that
unreached stage on the same final code. Its PASS does not establish a passing
complete acceptance run or repair the inherited failure. The public PR remains
a draft pending that broader qualification.

## Actual native controlled case

The independent first direct call to the final v0.29 acceptance stage passed
on a fresh private root. It was not called by the earlier failed full runner and
did not adopt or replay any retained fixture. The native child and normal HTTP
handler in memory observed Running, Stop requested and Failed history states;
the explicit Stop response is also recorded separately.

The complete genuine chain verifies one launch, one successful Running-view
receipt, one linked armed-stop receipt and one explicit owned Stop. It records
SIGTERM 15/exit 130, zero containment stops, no agent execution and no agent
result/run directory. Initial regular-file pins remain exact across Manager
setup; the complete post-setup baseline is preserved during the controlled run.

One real in-memory review request returned TASK_NOT_REVIEW_READY and one export
request returned REVIEW_REQUIRED. Both requests are counted; review writes and
export outputs remain zero and the entire settled fixture stays unchanged.
Normal/saved reads repeat identically with fresh managers/tokens after read-only
restart. All original fixture bytes/modes stay identical, with zero new worker,
check, model, Stop, publication, review-write or export operation on restart.

Parent guard-attempt counts remained zero; child receipts record zero provider,
check and network attempts. The fixed controlled child runs no agent or Git
path. These observations remain bounded Python-level evidence. Earlier scripted-agent and
fixed Python/Java check stages are separate evidence, not new model inference.

Normal terminal metadata remains Failed because no agent result exists. A
verified owned Stop depends on the original actual SIGTERM/exit-130 receipt
chain and the new Running-response/armed-stop links, not a favourable UI label.
The native driver's handler-in-memory observations and the browser's actual
loopback HTTP observations are separate evidence.

Missing artifacts retain Unknown current decision and an empty incomplete
saved-review history. Existing review/export guards refuse insufficient evidence.
Read-only restart uses fresh managers and session tokens with the same source
and fixture; it starts no worker, model, check, Stop, review writer or export.
Prior Python/Java scripted-client and fixed-check acceptance remains separate.

## Initial v0.29 Live Run/Stop browser observations (historical)

One fresh, source-bound browser fixture runs through the real normal handler
and real loopback HTTP. The browser clicked Run once, visibly showed Running
for that same selected run, clicked Stop once and visibly showed Stop requested,
then Failed. Native receipts agree with one owned SIGTERM/exit-130 Stop and no
containment. Browser rendering is independent evidence; the server-write receipt
does not claim to prove it.

The browser shows zero model turns and Scripted / no inference. Stop becomes
disabled after settlement. Accept, Reject and Download remain disabled; no review
or export action is requested. Saved evidence shows Unknown decision, unavailable
artifact pins and an empty incomplete receipt history; historical inspection is
disabled. No result, patch, receipt selection or Interrupted state is fabricated.

The owned server exits successfully and a native loopback probe confirms its
listener closed. A fresh read-only server session reloads the same Failed run
and clears cached saved cards. Explicit saved review/history requests return
identical completed response hashes and identical metadata, history and evidence
pins. No second Run, Stop, worker, model, check, writer or export is requested.
Every preexisting fixture byte/mode stays unchanged; only the exact normal outer
CLI session/shutdown pair is added during read-only restart.

Both observer sessions passed with the normal feed unmodified and all forbidden
operation counters zero. Both public CLI processes exit successfully; native
ECONNREFUSED probes verify the fixed listener closed after each session. Each
session records one denied favicon GET with SESSION_REQUIRED; browser console
warning/error captures are empty. Python guards remain separate from OS-wide
packet auditing. All browser receipts, images and records remain private.

## Limits, privacy and licensing

This qualifies only the stated controlled local process workflow. It does not
qualify a real model, coding-agent success or failed checks, Java-agent execution,
remote inference cancellation, arbitrary tasks, source adoption, recovery or
deployment. Signal receipt custody assumes stable trusted single-owner storage.
Sequential inspections are not atomic multiwriter snapshots, authenticity
attestations or crash-durability guarantees. Python guards are not an
operating-system-wide packet audit.

Real records, histories, configuration, run roots, logs, notes, receipts,
patches, exports, screenshots and private helpers stay outside public source.
The original uncertain Java trial stays held/unqualified; only its two authorized
preservation hashes are compared, without held Manager/runtime/provider,
recovery or retry access. Existing notices and unresolved rights remain;
licensing stays **UNASSIGNED**. Naming-only provenance checks do not establish
originality, ownership or redistribution rights.

Earlier evidence remains in [version 0.28 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/33db63cb02c4b75b4b865c8bdd406bd07778d0c6/VALIDATION.md).
See [origins](ORIGINS.md) for attribution and licensing limits.
