# Version 0.29 validation

All **1,210 unit methods across 56 suites passed** on the final source.
The separate current-source targeted v0.29 native qualification and the actual
browser Run/Stop plus read-only restart passed. All **128 qualified code, static
and example hashes** stayed unchanged. These are local results, not GitHub CI.

The **complete native acceptance runner did not pass**: an unchanged inherited
snapshot-recheck stage returned RECHECK_RECORD_INVALID before the v0.29 stage
was reached. That failure is retained and is not repaired or requalified by the
targeted result. The source update is prepared as a **draft PR**, with this full
acceptance limitation explicit.

## Scope and evidence classes

Four new source modules provide a separate live Run/Stop QA wrapper, native
acceptance and two regression suites. The existing runner adds the suites and
calls the new acceptance stage last. The public snapshot has 132 files, including
128 qualified code/static/example inputs. The other 123 inherited files remain
byte-identical: production engine, Manager, admission, providers, Java client,
old QA/worker modules, saved readers, review writer, export gates and browser
JavaScript/CSS are unchanged. Only the HTML version badge changes outside docs,
the runner and the four new modules. No dependency or service is installed.

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

## Complete inherited acceptance limitation

The final full runner passed all 1,210 unit methods but exited in the unchanged
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

## Browser observations

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
