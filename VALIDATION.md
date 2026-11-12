# Version 0.21 validation

Final offline qualification on one Linux host passed **919 unit methods across
40 suites**: the prior 881, 22 pure comparison methods and 16 controller/HTTP
methods. Actual invented Python/Java private save → list → preview → separate
explicit Load → restart passed. Separate explicit fixed checks passed on selected
copies with loaded goals and unchanged scope, checks and budgets. All prior
acceptance probes also passed. Preview started no agent run and performed no
check, Git command, source read, record write, provider or model request.

| Area | Observed result |
| --- | --- |
| Explicit scope | Preview compares the supplied current draft with one compatible pinned private goal; it never assigns Task or selects project/model |
| Exact text | UTF-8 hashes retain Unicode, astral/combining text, CRLF and other valid controls without normalization or newline folding |
| Draft validation | Empty/blank drafts allowed; saved goals retain the nonblank rule; invalid type, NUL, Unicode and length/byte bounds refuse |
| Difference spans | Maximal shared prefix and nonoverlapping suffix identify one first-through-last-difference span, including insertion/deletion/identical edges |
| Current evidence | Existing loaded config/task/profile/history/record pins rechecked before and after comparison under the Manager lock |
| Failures | Cross-project/stale pins, config/task/history drift, incompatible bindings, unsafe/partial stores and changed evidence refuse without repair |
| Read-only planning | Private hashes and definitions unchanged; no new project directory, record, job, run, task or comparison cache file |
| HTTP | New explicit POST inherits session/Host/Origin and exact JSON/header/body bounds; malformed framing/auth/output cases tested |
| Python/Java | Actual independent fixed checks pass on selected copies; source/config/task/preset/hold bytes remain unchanged by preview |
| Restart | Both backend language comparisons repeat exactly; browser clears old comparison and selection before an explicit new request |
| Browser | Complete Unicode goals and highlights, empty draft, identical goals, literal markup, separate Load, Close and draft invalidation observed |
| Scripted Task | Preview works while the original Task remains read-only and Load stays disabled |
| Held state | Restarted preview reads the retained saved goal while Task/Run remain disabled, Task text unchanged and the invented hold retained |
| Preservation | Three private browser records survive unchanged; all source/config/task hashes and empty execution directories retained |
| Teardown | Both temporary owned servers stopped and the loopback listener was verified closed |

## Evidence classes and preserved outcomes

All selected projects, names and instructions are invented. Pure comparison tests
perform no filesystem, project, provider, Git, check or runtime operation.
Controller fixtures guard those boundaries and use actual private preset records
and bounded HTTP requests. The new actual acceptance starts no agent Run or
inference; its separate explicit Bubblewrap Python unittest and Java compilation/
protected-main checks are independent of preview. One Java test means one
protected main, not an assertion count. Prior scripted-client acceptance remains
separate from this milestone and does not qualify a real model.

The first pure run passed 22 methods; the first integration run passed 16. An
initial static UI inventory misclassified a CSS class as an element ID; that
inventory was corrected without changing application bytes, and the retained
second static log passed. The first full qualification passed all 919 methods/
40 suites and actual acceptance probes. All 96 qualified executable/static/input
hashes remained unchanged through browser qualification and freeze. Historical
failures, partial records and holds remain separate; no failed runtime request
or held job was retried, cleaned up, erased or relabelled.

Browser qualification used fresh invented fixtures, with agent Run, provider,
outbound HTTP and worker calls blocked and counted. Across two server sessions
it made seven explicit lists, three saves, five previews and two explicit Load
requests. No Run attempt, provider/outbound HTTP call or worker launch occurred.
Preview uses the existing pinned read-only goal reader internally; these counts
refer to browser HTTP actions. The same name was saved independently for Python
and Java. The Python comparison retained literal markup as text, showed complete
Unicode goals and two highlighted spans, and left Task at the draft. Explicit
Load filled Task and cleared preview; the next preview labelled goals identical
with no marks. Editing Task discarded comparison and selection. Java preview
accepted an empty draft without filling it; Close retained the draft/selection,
then separate Load filled Task. Scripted preview retained read-only Task and
Load disabled. Reload cleared cached selection/comparison. A subsequent Python
preview after restart retained saved text while an invented unrelated hold kept
Task and Run disabled. The hold and three 0600 single-link preset records remain
private. No captured browser warnings/errors occurred; the observed badge was
0.21. All browser source/config/task hashes remained unchanged and execution
record directories stayed empty.

## Bounds and trust limits

Draft: 0–2,000 Unicode codepoints, at most 8,000 UTF-8 bytes, no NUL or invalid
Unicode; whitespace-only drafts are valid. Saved goals retain the existing
nonblank 1–2,000/8,000 bounds. Exact text is returned without clipping. All preset
HTTP requests are at most 32,768 bytes and responses at most 65,536 bytes,
including both goals and comparison metadata. Worst-case escaped Unicode/control
examples fit the complete response bound. Existing names, 64-record capacity,
32,768-byte record and 2-MiB history bounds stay unchanged.

The highlight is one contiguous span from the first through last differing
codepoint. It may include unchanged middle text and is not a minimal edit script.
Matching goals use the entire text as the common prefix and zero suffix. Browser
textareas retain normal newline presentation; exact API text/hashes remain
separate from visual typography. The browser independently verifies both hashes
and the comparison boundaries before rendering text nodes, then repeats its
current-input guards after asynchronous hash validation.

Preview requires a compatible current project binding; it does not preview an
incompatible old profile or bypass existing Load/Run admission. It reads no source
bytes or holds and proves no current source correctness, model completion or
execution freshness. Config/task/profile and full-history checks are sequential
under a process-local lock on trusted stable single-owner storage, not an atomic
multiwriter filesystem snapshot or crash-durability guarantee. Hashes are
integrity observations, not ownership, authenticity or authorization proofs.
No new stored record or archive/recheck/edit schema is introduced.

Real presets, goals, source, comparisons, configuration, bundles and runtime
records remain excluded from public uploads. The original uncertain Java trial
remains unqualified, with cause and provider completion unknown; its exact hold/
result preservation hashes match unchanged. No inference, recovery, eviction,
service change, original-project adoption or license assignment occurred.
Earlier evidence remains in [version 0.20 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/f91fcd417e3a45b96f1cf2e927e92947131d6908/VALIDATION.md).
Qualification used Python 3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting
Java 17 on Linux. Local passes are not GitHub CI passes. Licensing remains
**UNASSIGNED**; see [origins](ORIGINS.md).
