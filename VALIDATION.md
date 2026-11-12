# Version 0.20 validation

Final offline qualification on one Linux host passed **881 unit methods across
38 suites**: the prior 836, 21 pure task-preset methods and 24 controller/HTTP
methods. Actual invented Python/Java private save → list → explicit load →
restart persistence passed. Separate explicit fixed checks passed against task
copies carrying the loaded goals and unchanged scope, checks and budgets. All
prior acceptance probes also passed. Preset operations made zero checks, Git
commands, workers or model requests and started no agent run.

| Area | Observed result |
| --- | --- |
| Goal-only scope | Explicit list/save/load never changes source, config, task definition, default goal, model selection, checks, permissions or budgets |
| Project identity | Binding covers project/source identity, task format, selected paths, editable paths, exact checks and budgets |
| Routine refresh | Approved file-hash/default-goal refresh preserves the profile; changed scope/check/budget/source identity makes older records incompatible |
| Names and goals | NFC names, Unicode/casefold duplicates, project isolation, exact API goal text and bounded serialized records tested |
| Current evidence | Loaded config/task bytes, profile, full preset history and selected record hashes are pinned before/after operations |
| Private storage | Owned 0700 directories, 0600 regular single-link files, no-follow descriptor paths and no-overwrite publication |
| Retained failures | Partial stage, config/task drift after staging, unsafe modes and post-publication uncertainty refuse without cleanup or repair |
| Bounds | 64-record capacity, full 63-record reserved-write budget, record/history/request/output limits tested |
| HTTP | Three explicit POST routes enforce exact fields, session/Host/Origin, header/body framing and route caps |
| Read-only planning | Empty list creates no project directory; list omits goals; load returns only the explicitly selected goal |
| Python/Java | Actual separate fixed checks pass with loaded goals and all other definition fields unchanged |
| Restart | New Manager and browser server reuse retained private records; reload never automatically lists or loads presets |
| Browser | Explicit save/refresh/select/load works for Python and Java, with placeholder selection and duplicate refusal |
| Scripted restriction | The scripted Task remains read-only and Load disabled even with a compatible selected preset |
| Held state | An invented unrelated hold allows goal loading into disabled Task while Task/Run stay disabled and the hold remains retained |
| Preservation | Browser fixture source/config/task hashes and empty jobs/runs/tasks remain unchanged; original Java hold/result hashes still match |
| Teardown | Both temporary owned server sessions stopped and the loopback listener was verified closed |

## Evidence classes and preserved outcomes

All selected projects, names and goals are invented. Pure helpers perform no
filesystem, Git, check, provider or runtime access. Controller tests guard those
boundaries and test private filesystem records and HTTP framing. Actual
Python/Java fixed checks are separate explicit acceptance steps, never a side
effect of listing, saving or loading a preset. The new acceptance starts no
agent run; the existing full runner independently retains its scripted-client
workflow. One Java test means one protected main, not an assertion count.
No model inference was requested.

Focused qualification retained earlier passing logs as coverage grew: the final
pure run passed 21 methods and the final integration run passed 24. The first
full qualification passed all 881 methods/38 suites and the actual acceptance
probes. Final engine/controller/UI/input hashes stayed unchanged through browser
qualification and freeze. All earlier milestone failures, partial records,
holds and successes remain separately preserved; no failed runtime request or
held job was retried, erased or relabelled.

The browser used only fresh invented private fixtures, with agent Run, provider,
outbound HTTP and worker execution blocked and counted. Across two server
sessions it made exactly eight explicit lists, four save attempts (three new
records and one duplicate refusal), and four explicit loads. There were zero
Run attempts, provider calls, outbound HTTP calls or worker launches. The same
name was stored independently for Python and Java. Refresh retained the draft
and placeholder; Save required a new explicit Refresh. Project switching and
reload discarded previous selections. Both language goals survived restart.
The browser showed version 0.20 with no captured warnings/errors.

After the restart checks, an invented unrelated hold was added and retained.
Python Load filled only the disabled Task; existing Run admission stayed blocked.
This fixture never opens or changes the original uncertain Java workspace.
The three preset records and the invented hold remain private. A sandbox-limited
process/listener verification was completed in the permitted host context;
no application operation or runtime task was repeated for that verification.

## Bounds and trust limits

Each project stores at most 64 immutable records, each at most 32,768 bytes, with
at most 2 MiB of raw record history. Save reserves a full record before staging.
Names are NFC-normalized, 1–80 Unicode codepoints and at most 240 UTF-8 bytes,
without surrounding whitespace or control/format/surrogate/line-separator
characters. Names are unique per project using NFC casefold, including old
incompatible bindings. Goals are nonblank, 1–2,000 codepoints and at most 8,000
UTF-8 bytes, with no NUL or invalid Unicode. API goal text is retained exactly;
browser textareas use their normal newline presentation.
All three preset HTTP requests are capped at 32,768 bytes and responses at
65,536 bytes. List returns bounded names, compatibility and hash metadata, not
saved goal text. Names and metadata still contain private project context.

A record binds to the approved project profile, not current source correctness.
File hash values, default goal and model settings are excluded from that binding;
current loaded config/task raw bytes must nevertheless still match. Preset
planning deliberately does not read source bytes or qualify Run freshness.
Existing Run admission, checks and review requirements remain separate.

Save stages a new exclusive file, verifies the stage and current pins, publishes
with a no-overwrite hardlink, then reads back the result. Partial stages and
uncertain markers block further preset actions for that project without altering
Run admission. They are retained for private owner inspection: there is no
retry, overwrite, delete, import or export interface. A hardware/filesystem error
that prevents writing the uncertainty marker requires private inspection; no
transactional multiwriter or crash-durability proof is claimed. All guards assume
trusted stable single-owner storage. Hashes are integrity observations, not
ownership, authenticity or authorization proofs.

Existing workspace, archive, edit and recheck formats remain unchanged. Real
presets, goals, source, runtime configuration, bundles and evidence remain
excluded from public uploads. The original uncertain Java trial remains
unqualified, with cause and provider completion unknown. Its exact hold/result
hashes are unchanged. No model request, recovery, eviction, service change,
original-project adoption or license assignment occurred.
Earlier evidence remains in [version 0.19 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/451ed9054737a6d7957305fda94595ce3bffa680/VALIDATION.md).
Qualification used Python 3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting
Java 17 on Linux. Local passes are not GitHub CI passes. Licensing remains
**UNASSIGNED**; see [origins](ORIGINS.md).
