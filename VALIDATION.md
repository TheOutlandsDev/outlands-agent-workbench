# Version 0.17 validation

Final offline qualification on one Linux host passed **744 unit methods across
32 suites**: the prior 701, 19 new engine/verifier methods and 24 controller/HTTP
methods. Actual Python/Java checked snapshots were reviewed and exported as v2,
then consumed by the project checker and fresh workspace imports with passing
fixed checks. All prior acceptance probes passed. Export itself made zero check,
Git, worker, provider or model calls. Real bundles and runtime evidence stay
private.

| Area | Observed result |
| --- | --- |
| Strict versions | Exact integer version/format/evidence/hash-keyset/README tuples select v1 or v2; mixed and unknown tuples refused |
| Legacy behavior | V1 constants, generation bytes and meaning retained; existing v1 regression suites passed |
| Typed provenance | V2 records snapshot-workspace recheck evidence; upstream `import_archive_sha256` is separate from the new packet digest |
| Exact patch | Complete original-approved-baseline to saved tested snapshot, including earlier imported fix and later selected manual edits |
| Source evidence | Initial/request/creation/archive/full checks/task/config/source/Git and copied tested bytes pinned and reread |
| Read-only export | Guarded preview/download perform no checks, Git, providers, workers, runtime reconciliation, hold reads or writes |
| Explicit acceptance | Only separate new private receipt/review metadata written after pinned review; private notes excluded from ZIP |
| History | Changed recheck/acceptance tips invalidate old pins; damaged/failed/unfinished/partial evidence blocks without older-approval fallback |
| Bounds and errors | Counts, aggregate receipts/reserve, unsafe ancestors, malformed evidence, strict HTTP framing and fixed errors tested |
| Restart | Explicit saved-approval selection works under retained hold; no automatic acceptance or new preview required |
| Python/Java roundtrip | V2 verifier, baseline comparison/reconstruction and fresh actual imported-workspace checks passed |
| Preservation | Original source/Git/worktrees/creation/rechecks/holds and earlier acceptances remain unchanged |
| Browser | Java/Python preview, notes, explicit acceptance/download, invalidation and restart selection observed under an unrelated hold |
| Download integrity | Both browser ZIP hashes, version2, recorded checks and tested selected hashes match their private receipts |
| Teardown | Both owned preview servers stopped; listener closed; final restart retained every saved byte |

## Evidence classes and retained development result

Unit and controller fixtures use invented selected projects and saved observations.
Engine tests do not execute Git, project checks or a provider. Controller fixtures
use real private Git where stated and fake check observations where documented.
These are separate from the full runner's actual Bubblewrap Python/Java checks
and from the browser's saved actual Python four-test and Java one-main results.
One reported Java test means one executed protected main, not assertion count.

The first focused engine run passed 18 methods and had one incorrect test
expectation: corrupting only one ZIP size field correctly caused a framing
refusal before the intended size-limit check. The log remains retained. The test
then changed both size fields to reach that bound; a separate 19-method run
passed. Controller runs of 19 and then 24 methods passed; final full qualification
passed on its fresh root. No failed runtime job or held request was retried,
cleaned up or relabelled. Earlier milestone evidence remains separate.

Actual acceptance constructs and checks invented Python/Java snapshots, then
adds an unrelated synthetic hold. Export runs under guards forbidding checks,
Git, providers and hold access; only explicit acceptance may add metadata.
Separate fresh, hold-free import fixtures compare and reconstruct the v2 packets,
create private Git workspaces and run actual fixed checks. This is a new
compatibility trial, not a retry or resolution of the held exporter. Original
holds and all earlier records remain intact.

Browser trials reviewed combined patches and both imported/new archive hashes,
saved private Unicode notes, explicitly accepted and downloaded Java/Python
packets. Packet hashes, check observations and tested file hashes match; notes,
acceptance IDs and internal metadata paths were absent. Workspace/input changes
disabled old acceptance/download state. After server restart, the history left
its deliberate placeholder selected until explicit approval selection; only
then did Download enable, while Accept stayed disabled and normal Run remained
hold-blocked. No extra approval or check was performed during restart inspection.

## Version, privacy and trust limits

V1 remains `outlands-reviewed-snapshot-export-v1` with legacy workspace-recheck
evidence. V2 is `outlands-reviewed-snapshot-export-v2` with recorded passing
snapshot-workspace recheck evidence and `import_archive_sha256`. No legacy
`bundle_sha256` record is invented for v2. The four fixed members remain
`changes.diff`, `verification.json`, `README.txt` and `SHA256SUMS`.

Current verifier, selected-project comparator and snapshot-workspace importer
explicitly support both strict formats. Older versions support v1 only; v2 needs
this version's tools. Private acceptance uses the separate
`outlands-snapshot-reexport-acceptance-v1` type/store; old creation/recheck/export
records are not converted. Saved human notes and acceptance assertions do not
enter the deterministic packet. Full output, prompts/responses and raw record
metadata stay private; the patch and relative paths still contain private source.

| Input/output | Bound |
| --- | --- |
| Selected snapshot | 32 UTF-8 files, 32,768 bytes/file, 131,072 aggregate |
| Archive / patch / verification | 2 MiB / 1 MiB / 262,144 bytes |
| Full check evidence / clipped receipt display | 2 MiB / 4,096 characters per check |
| Diff preview | 240 lines and 8,192 UTF-8 bytes, explicit clipping |
| Prepared summary / preview | 65,536 / 131,072 bytes |
| Private acceptance history | 200 entries, 2 MiB aggregate raw receipts |
| Receipt reserve / saved review / history JSON | 32,768 / 131,072 / 262,144 bytes |
| Note | 1,000 Unicode code points, 2,000 UTF-8 bytes, no NUL/invalid Unicode |
| Preview | One memory draft, five minutes, one explicit acceptance |

Export reconstructs the exact saved tested snapshot and still requires current
source/task/config/worktree/Git evidence to agree. Later untested edits refuse
the old result. Sequential trusted-store guards are not atomic multiwriter
transactions or proof of no transient mutation. Unsigned hashes and recorded
passing fixed checks do not prove authenticity, source correctness, model
competence, provider completion or permission to adopt changes. Nothing is
extracted, applied, committed, deployed or published by the export flow.

The original uncertain Java trial remains unqualified; its cause and provider
completion remain unknown. Its hold/result hashes are unchanged. No model
request, recovery, eviction, service change or license assignment occurred.
Earlier evidence remains in [version 0.16 validation](https://github.com/TheOutlandsDev/outlands-agent-workbench/blob/a1ad0443038d2f17ca7df56b40fd6c5e52ec2182/VALIDATION.md).
Qualification used Python 3.10.12, Git 2.34.1 and Temurin JDK 21.0.13+9 targeting
Java 17 on Linux. Local passes are not GitHub CI passes. Licensing remains
**UNASSIGNED**; see [origins](ORIGINS.md).
