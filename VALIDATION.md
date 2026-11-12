# Version 0.27 validation

Native offline qualification passed **1,145 unit methods across 52 suites**:
1,117 inherited methods plus 14 restricted-harness and 14 dependent-verification
methods. All earlier and new acceptance stages passed on the first complete
native run. All **120 qualified code, static and example hashes** stayed unchanged.
The **624 inherited isolated frontend checks** passed (255 inherited checks and
369 history checks). These are local results, not GitHub CI.

## Scope and evidence classes

The restricted offline harness adds exactly two saved-history POST routes and
separate request counters. It delegates the existing four-pin list and five-pin
selected-detail handlers. Existing request authentication, framing and size
bounds remain intact. Production engine, saved-review readers, review writer,
export gates, admission, worker implementation and earlier offline-workflow QA
are unchanged. Browser JavaScript/CSS are identical to version 0.26; HTML changes
only the version badge.

The 14 new engine tests and 14 integration tests use deliberately invented
fixtures, fake check results and fabricated worker/Java/prior-report receipts.
They test strict routing, authentication, framing, exact pins, malformed and
missing dependencies, source mismatch, stale evidence and read-only restart.
These unit fixtures are not actual worker or Java execution evidence.

The first focused integration attempt passed 11 of 12 methods and retained one
incorrect spy assertion: normal run view also calls admission, which legitimately
reads history again. The expectation was corrected without changing production
behavior. Two additional cases tightened dependency-counter and receipt checks;
the final 14-method focused suite passed. The failed log remains private. No
consumed actual worker/model attempt was retried or cleaned up.

## Actual native workflow verification

The existing earlier acceptance stage creates a fresh same-source private
fixture and runs one actual scripted Python worker with real isolated baseline,
agent and final checks (four tests at each phase). Its separate invented Java
fixture passes one actual protected-main check; that is one main program, not
an assertion count. This is scripted execution, with no real-model inference.
The existing full runner also retains its Python/Java launcher, isolation,
Git/workspace, refresh, comparison, readiness, bundle and snapshot acceptances.

The new last stage requires that earlier completed accepted workflow and its
exact report, export, worker-exit and Java receipt hashes. It verifies source-bound
launch arguments before opening the fixture. Missing, malformed, partial or
foreign-source dependencies refuse without recreation, adoption, cleanup or retry.
It reads the earlier Java evidence without running another Java check or agent.

Using the restricted HTTP handler, the stage keeps normal history and run view
real, explicitly searches and opens saved metadata, reads the v2 saved review,
lists receipts and inspects the selected receipt. It repeats with a fresh manager,
token and counters after restart. The same note, recorded time, current decision
and artifact pins return exactly. Every original fixture byte and mode remains
unchanged. Guard attempts and new worker launches, checks, model requests, review
writes and export requests are all zero. Saved-only guards are scoped to the
explicit saved routes; terminal history/view refresh is not replaced or hidden.

## Browser observations

Two owned native browser sessions use that same completed current-source actual
fixture through the public offline CLI and unchanged normal history/view feed.
A private observational wrapper delegates those routes and records finite request
paths/statuses outside the fixture. It refuses task, review-write and export
actions and guards worker, check, provider, process, Git and outbound paths.

The initial page shows one completed ready-for-review scripted run, its original
plan. Task remains read-only for the scripted model. Explicit search,
saved-evidence review, history list, selection and detail show the existing
acceptance, private note, time and exact result/patch hashes. No Run, Accept,
Reject or download action is requested. Model/project values, Task and export
controls remain unchanged. Restart clears cached review cards; repeating those
explicit reads returns identical decision, note, time, hashes and form state.
The browser does not observe the earlier RUNNING-to-completed transition.

Across both sessions, normal history and run view each receive six requests;
search, saved review, history list and selected detail each receive two. The
wrapper records two denied GET `/favicon.ico` requests, each returning 403
`SESSION_REQUIRED`; no cause is inferred beyond these recorded request paths and
responses. Browser warning/error captures are empty. All execution/write guards
and worker/start/check/review-write/export/provider/outbound counters remain zero.

Each public CLI session adds only its exact new session/shutdown receipt pair.
Every preexisting fixture file and directory retains bytes and modes. These four
normal CLI receipts across two sessions do not alter runtime, worker, review,
acceptance or export evidence. Both servers exit successfully; a direct native
ECONNREFUSED probe confirms the loopback listener closed.

## Limits, privacy and licensing

This qualifies one complete offline scripted review workflow and completed-feed
browser persistence. It does not qualify a real model, a Java agent, browser
observation of execution, arbitrary tasks, deployment or current source adoption.
The new stage performs no second actual task or check. Python-level interception
is not operating-system-wide packet auditing.

Stable trusted single-owner storage remains required. Bounded sequential reads
are not atomic multiwriter snapshots or crash-durability guarantees. Saved human
verdicts and artifact relations do not establish author authenticity, source
correctness, adoption or execution/export permission. Earlier history damage,
Unicode, formatting and stale-response coverage remains inherited; it is distinct
from this milestone's single completed actual browser fixture.

Real records, histories, notes, configs, run roots, worker evidence, patches,
exports, logs, browser screenshots and private helper tools remain outside public
source. The original uncertain Java trial remains held and unqualified; cause
and provider completion remain unknown. Root compared only its two authorized
preservation hashes, with no held Manager/runtime/provider/recovery/retry access.
Licensing remains **UNASSIGNED**. Naming-only provenance checks do not establish
ownership or redistribution rights. Earlier evidence and retained attempts are
in [version 0.26 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/96214eea8333de7bca1efc5e01aa7e2e4ed87893/VALIDATION.md).
See [origins](ORIGINS.md) for attribution and licensing limits.
