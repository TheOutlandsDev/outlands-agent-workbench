# Version 0.10 validation

Offline qualification on one Linux development host passed **416 unit methods**:
the prior 377, 24 bundle/project engine and CLI methods, and 15
controller/HTTP methods. The full runner also passed actual isolated Python/Java,
Java-client parity, Git worker, namespace, timeout/output, prerequisite, refresh,
comparison, readiness and v0.9 bundle acceptance. No real-model requests were
made. Real bundles, private projects, reports, uploaded archives and runtime
records remain excluded from the public source package.

| Area | Observed result |
| --- | --- |
| Retained unit suites | All prior 377 methods passed |
| Bundle/project engine and CLI | 24 methods passed |
| Controller and binary HTTP | 15 methods passed |
| Python/Java observations | Baseline and candidate matches, configured-pin differences and JDK-free inspection passed |
| Mixed and changed files | A two-editable-file fixture reported mixed baseline/candidate bytes; arbitrary/protected drift, missing and unsafe evidence stayed distinct |
| Profile guards | Format, scope, permission, check and budget mismatches skipped all selected-source reads |
| Bounds and storage | Unicode/empty/line-ending and 32-file cases, task/record/source limits, links, unsafe ancestors and read stability checked |
| Input integrity | Invalid/tampered archives and external digest failures refused before selected-source reads |
| Read-only boundary | Source/data file hashes and unrelated synthetic hold unchanged per inspection; live-state/provider/process/check/network paths guarded |
| HTTP | Exact raw ZIP body, length/MIME/transfer/hash headers, Host/session/Origin guards, short bodies and no-store JSON responses checked |
| Browser | Python baseline, Java candidate with configured pins false, mixed bytes, digest failure and scope mismatch observed |
| Browser controls | Explicit submit, input invalidation, keyboard Enter, reset after closing and mutual exclusion with all three existing inspectors checked |
| Browser layout | Desktop and 390-pixel viewport inspected; client/scroll widths both 375 pixels, including final shared-path permission wording |
| Final source smoke | Fresh private workspace with final code returned baseline match; file-tree bytes unchanged; both owned previews stopped |

During focused test development, the selected-file helper exposed a shared path
refusal instead of the new fixed public code. That helper boundary was corrected.
A separate direct-manager test expected the HTTP layer's digest code, while the
manager correctly retained the existing archive verifier's allowed code; only
that assertion was aligned with the contract. Both initial failures are retained
privately. Final focused suites and complete acceptance passed; no failed run was
relabelled or used as permission to retry the original uncertain Java task.

## Evidence classes and browser observations

Fixtures contain invented Python/Java sources, protected tests, two-file mixed
edits and directly saved accepted v0.9 records. Their recorded check rows are
invented evidence for comparison logic. The new inspector does not run those
tests, compile Java or use a model. The full runner's actual isolated Python/Java
execution checks are separate from these saved records.

The browser used private synthetic archives and the real binary endpoint.
Choosing a local file left results hidden until explicit submission. A baseline
Python report matched CLI observations; after deliberate fixture preparation,
Java matched candidate bytes while configured pins stayed false, and a two-file
Python project reported mixed bytes. CLI returned 0 for baseline/candidate and 1
for mixed, matching its stated exit contract.

A wrong trusted digest refused the request and hid the old report. A Java archive
checked against the Python task showed scope/check differences, out-of-scope
rows and Unknown current hashes/sizes. Unit guards independently proved no
selected-source read occurs in such profile-mismatch cases. Changing inputs
invalidated the report. Closing cleared the file/digest fields and required a
new file selection. Readiness, comparison and bundle inspectors remained
mutually exclusive with the new panel. An unrelated saved hold continued to
block new tasks while allowing this read-only inspection.

Java candidate and mixed source states were prepared manually between read
stages. Those intentional fixture changes are distinct from inspector behavior;
within each stage, all source/data hashes stayed unchanged. A fresh final-source
preview was inspected again and stopped. No real bundle or original operational
project was used for browser testing.

## Scope, fingerprints and selected bytes

The controller accepts an already configured project ID, verifies exact current
config/task bytes against its cached fingerprints, and uses only that cached
source root and task scope. Drift or unavailable fingerprints refuse the check
before source reads. No replacement path or definition is adopted. The report
binds the inspected bundle/task/config bytes by SHA-256 and carries a dated
observation; these hashes are not authenticity evidence.

The existing v0.9 archive verifier runs before selected-source reads. Format,
selected path set, editable/protected permissions on shared paths, check specs
and budgets are compared with the named task. Any mismatch skips every source
read. Bundle-only paths are never adopted into project scope; project-only paths
and permission differences remain visible.

Matching profiles permit only declared relative files. Readers refuse links in
every path component, hardlinks and nonregular files, enforce size and UTF-8/NUL
guards, and detect size/mtime changes during a read. Unknown or unsafe file
observations retain null size/hash values; they never become zero or a match.

Per-file states distinguish unchanged bytes, baseline, candidate, arbitrary
change, missing, unreadable, limited, binary, invalid UTF-8, uninspected and
out-of-scope inputs. A changed protected file is an arbitrary change. Configured
task hashes and their current-byte match booleans are displayed separately:
a later revision can pin candidate bytes, and a source can match a bundle while
its configured task pin is stale.

Overall reports distinguish baseline, candidate, mixed, different and needs
inspection. A match describes selected bytes only. Missing, unsafe, unknown,
limited or mismatched-profile evidence prevents a complete match. Sequential
observations can become stale and are not an atomic snapshot or multiwriter
transaction. The host/store remains trusted.

## Privacy and action boundaries

The browser submits a raw ZIP only after an explicit action, with a selected
configured ID and optional trusted archive digest. It sends no filename or
multipart/base64 envelope. The endpoint keeps the archive in memory and creates
no cache, report, run, revision or hold record. Source contents, absolute paths,
archive filenames, task goals, prompts, review notes, raw logs and exceptions
are absent from the selected report. Relative names, profiles and hashes remain
private project information. Text is rendered without interpreting HTML.

The inspector does not extract, apply, run checks, launch processes, contact a
provider, inspect ownership, reconcile workers or read/change a hold. It calls
no normal history/view/admission/export workflow. Closing the panel resumes
normal polling; that separate run view retains its existing behavior.

Every comparison leaves these six areas **Not checked**:

- Task goal.
- Check rerun.
- Provider completion.
- Source correctness.
- Patch applicability.
- Git adoption.

Embedded archive checksums remain unsigned integrity evidence. A separately
trusted expected digest detects archive replacement, but no report establishes
who authored or accepted it. Existing v0.9 archive semantics and format are
unchanged. No status authorizes Run or manual patch adoption.

## Bounds and CLI

| Input/output | Bound |
| --- | --- |
| Binary ZIP body | 1 byte to 2 MiB, exact declared length |
| Named task file | 262,144 bytes |
| Approved selected scope | At most 32 files, 32,768 bytes/file |
| Selected total eligibility | 131,072 bytes; truthful known total may exceed this and prevents a match |
| Engine/CLI JSON | 65,536 bytes |
| Manager envelope | 131,072 bytes |
| Earlier live-poll wait | Cancellable, ten seconds |

The total is an eligibility threshold after bounded inspection, not a 128-KiB
physical read budget. If any size is unavailable, the total remains Unknown.
The ZIP's existing fixed six-member stored format retains all v0.9 structural,
checksum and payload limits. Invalid binary framing, duplicate length/hash
headers, transfer encoding, wrong media type, short body or bad supplied digest
are refused safely. Existing JSON endpoint bounds remain unchanged.

The offline CLI reads an explicitly named archive, project root and task file
through guarded paths, prints selected JSON and writes nothing. It returns 0 for
a complete baseline/candidate match, 1 for nonmatch/inspection and 2 for invalid
or refused input. Java source comparison needs no JDK. The CLI performs no
extraction, application, checks, inference or provider request.

The original uncertain real-model Java outcome and hold/result hashes remain
unchanged. Cause/provider completion remain unknown; no replay, retry, recovery,
model eviction, deployment or new real-model qualification occurred.
Earlier evidence and platform limits remain in
[version 0.9 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/447e09b56af4a73dab76b037ba8358b5b7fff207/VALIDATION.md).
Acceptance used Python 3.12.7, isolated system Python 3.10.12, Git 2.34.1 and
Temurin JDK 21.0.13+9 targeting Java 17 on Linux. No GitHub CI pass is claimed
for local results. Licensing remains **UNASSIGNED**; see [origins](ORIGINS.md).
