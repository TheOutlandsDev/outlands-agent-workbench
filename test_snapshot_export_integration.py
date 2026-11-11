"""Invented verified snapshots, private reviewed exports and bounded HTTP contracts."""

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack, contextmanager
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from agent import Refused, canonical, review_diff, sha, write_new
from bundle_workspace import _apply
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_workspace_recheck_integration import (
    attempt_path, fake_recheck, manual_comment, passing_checks, populate_recheck_workspaces, recheck_request,
)
from workbench import Manager, init_demo, make_handler


PRIVATE_SENTINEL = "invented-private-snapshot-export-sentinel"
MEMBERS = {"changes.diff", "verification.json", "README.txt", "SHA256SUMS"}


def populate_snapshot_exports(manager, root, languages=("python", "java")):
    """Seed real private Git and saved rechecks with fake checks, never inference.

    The separate bundle-builder's synthetic hold stays intact. Only invented
    sources and approved task profiles enter this hold-free target Manager.
    """
    from workspace_recheck import build
    fixtures = populate_recheck_workspaces(manager, root, languages)
    for language, fixture in fixtures.items():
        manual_comment(fixture, language)
        preview = manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
        previous_jdk = manager.jdk_home
        try:
            if language == "java" and previous_jdk is None:
                manager.jdk_home = root / "unexecuted-export-unit-jdk-marker"
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(preview))
                attempt = attempt_path(manager, started["id"])
                receipt = build(attempt, manager.jdk_home, passing_checks)
                assert receipt["status"] == "VERIFIED"
                child.poll.return_value = 0
                assert manager.recheck_view(started["id"])["owned_active"] is False
        finally:
            manager.jdk_home = previous_jdk
        fixture.update(attempt_id=started["id"], attempt_dir=attempt,
            recheck_receipt_sha256=sha((attempt / "receipt.json").read_bytes()))
    return fixtures


@contextmanager
def snapshot_fixture(languages=("python",)):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = init_demo(root / "workspace", None)
        manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
        fixtures = populate_snapshot_exports(manager, root, languages)
        try:
            yield root, manager, fixtures
        finally:
            manager.close()


@contextmanager
def snapshot_export_guard(manager):
    """Export metadata may change only through the explicitly invoked acceptance."""
    with no_provider_calls(), ExitStack() as stack:
        for name in ["history", "refresh", "admission", "view", "export", "verified_artifact", "request_hold",
                     "owns_active", "workspace_receipt", "bundle_preview", "bundle_export", "bundle_workspace_view",
                     "bundle_workspaces", "recheck_view", "rechecks", "project_readiness"]:
            stack.enter_context(patch.object(manager, name, side_effect=AssertionError("snapshot export reached " + name)))
        for name in ["workbench.subprocess.Popen", "workbench.subprocess.run", "workbench.process_stamp",
                     "agent.Session.checks", "isolation.check", "java_check.check", "git_workspace.git"]:
            stack.enter_context(patch(name, side_effect=AssertionError("snapshot export reached " + name)))
        yield


def accept_request(preview, note="Invented owner review of the exact tested snapshot."):
    return {"preview_id": preview["preview_id"], "preview_sha256": preview["preview_sha256"], "note": note}


def download_request(accepted, preview):
    return {"acceptance_id": accepted["acceptance_id"], "receipt_sha256": accepted["receipt_sha256"],
            "archive_sha256": preview["artifact"]["archive_sha256"]}


def export_path(manager, acceptance_id):
    return manager.data / "snapshot-exports" / acceptance_id


def archive_parts(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert len(archive.infolist()) == 4 and set(archive.namelist()) == MEMBERS
        parts = {name: archive.read(name) for name in archive.namelist()}
    lines = parts["SHA256SUMS"].decode("ascii").splitlines()
    assert len(lines) == 3
    assert {line[66:]: line[:64] for line in lines} == {
        name: sha(value) for name, value in parts.items() if name != "SHA256SUMS"}
    return parts


def assert_patch_snapshot(fixture, raw):
    """Independently regenerate and apply the baseline-to-tested-byte patch."""
    parts = archive_parts(raw)
    task = json.loads((fixture["attempt_dir"] / "task.json").read_bytes())
    baseline = {name: (fixture["source"] / name).read_bytes() for name in sorted(task["files"])}
    selected = {name: (fixture["attempt_dir"] / "snapshot" / name).read_bytes() for name in sorted(task["files"])}
    changed = [name for name in baseline if baseline[name] != selected[name]]
    expected = "".join(review_diff(name, baseline[name], selected[name]) for name in baseline).encode()
    assert parts["changes.diff"] == expected
    assert _apply(parts["changes.diff"], baseline, changed) == selected
    assert all(name in task["editable"] for name in changed)
    return parts


class SnapshotExportIntegrationTests(unittest.TestCase):
    def preview(self, root, manager, fixture):
        before = private_hashes(root)
        with snapshot_export_guard(manager):
            result = manager.snapshot_export_preview({"attempt_id": fixture["attempt_id"]})
        self.assertEqual(before, private_hashes(root))
        self.assertEqual(result["preview_sha256"], sha(canonical({"prepared": result["artifact"],
            "recheck_history_sha256": result["recheck_history_sha256"],
            "acceptance_history_sha256": result["acceptance_history_sha256"]})))
        self.assertNotIn(str(root), json.dumps(result))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result))
        self.assertLessEqual(len(canonical(result)), 131072)
        return result

    def refused(self, root, operation, *args, codes=None):
        before = private_hashes(root)
        with self.assertRaises(Refused) as caught:
            operation(*args)
        reason = str(caught.exception)
        self.assertRegex(reason, r"^SNAPSHOT_EXPORT_[A-Z_]+$")
        if codes:
            self.assertIn(reason, codes)
        self.assertNotIn(PRIVATE_SENTINEL, reason)
        self.assertEqual(before, private_hashes(root))

    def test_python_java_reviewed_download_is_deterministic_and_reconstructs_tested_snapshot(self):
        from snapshot_export import prepare
        with snapshot_fixture(("python", "java")) as (root, manager, fixtures):
            self.assertIsNone(manager.jdk_home)
            for language, fixture in fixtures.items():
                with self.subTest(language=language):
                    preview = self.preview(root, manager, fixture)
                    before = private_hashes(root)
                    with snapshot_export_guard(manager):
                        prepared = prepare(fixture["attempt_dir"])
                        again = prepare(fixture["attempt_dir"])
                        self.assertEqual(prepared["archive"], again["archive"])
                        self.assertEqual(prepared["summary"], preview["artifact"])
                        accepted = manager.snapshot_export_accept(accept_request(preview, PRIVATE_SENTINEL))
                    prefix = str(export_path(manager, accepted["acceptance_id"]).relative_to(root)) + "/"
                    after = private_hashes(root)
                    self.assertEqual(before, {name: digest for name, digest in after.items() if not name.startswith(prefix)})
                    self.assertEqual({name[len(prefix):] for name in after if name.startswith(prefix)}, {"receipt.json", "review.json"})
                    self.assertEqual(accepted["receipt_sha256"], sha((export_path(manager, accepted["acceptance_id"]) / "receipt.json").read_bytes()))
                    with snapshot_export_guard(manager):
                        raw = manager.snapshot_export_download(download_request(accepted, preview))
                        self.assertEqual(raw, manager.snapshot_export_download(download_request(accepted, preview)))
                    self.assertEqual(after, private_hashes(root))
                    self.assertEqual(raw, prepared["archive"])
                    self.assertEqual(sha(raw), preview["artifact"]["archive_sha256"])
                    parts = assert_patch_snapshot(fixture, raw)
                    self.assertIn(b"a + b", parts["changes.diff"])
                    self.assertIn("café".encode(), parts["changes.diff"])
                    for value in parts.values():
                        self.assertNotIn(str(root).encode(), value)
                        self.assertNotIn(PRIVATE_SENTINEL.encode(), value)
                    history_before = private_hashes(root)
                    with snapshot_export_guard(manager):
                        history = manager.snapshot_export_history(fixture["attempt_id"])
                    self.assertEqual(history_before, private_hashes(root))
                    self.assertEqual(history["acceptances"][-1]["id"], accepted["acceptance_id"])

    def test_hold_is_not_read_or_changed_during_preview_acceptance_or_download(self):
        with snapshot_fixture() as (root, manager, fixtures):
            hold = manager.data / "state/hold.json"
            raw = canonical({"state": "REQUEST_UNSETTLED", "run": PRIVATE_SENTINEL, "turn": 1})
            write_new(hold, raw)
            preview = self.preview(root, manager, fixtures["python"])
            with snapshot_export_guard(manager):
                accepted = manager.snapshot_export_accept(accept_request(preview))
                before = private_hashes(root)
                manager.snapshot_export_download(download_request(accepted, preview))
            self.assertEqual(before, private_hashes(root))
            self.assertEqual(hold.read_bytes(), raw)

    def test_expired_replaced_consumed_and_cross_attempt_previews_cannot_accept(self):
        with snapshot_fixture(("python", "java")) as (root, manager, fixtures):
            with patch("workbench.time.monotonic", return_value=1000):
                expired = self.preview(root, manager, fixtures["python"])
            with snapshot_export_guard(manager), patch("workbench.time.monotonic", return_value=1301):
                self.refused(root, manager.snapshot_export_accept, accept_request(expired), codes={"SNAPSHOT_EXPORT_PREVIEW_EXPIRED"})
            first = self.preview(root, manager, fixtures["python"])
            second = self.preview(root, manager, fixtures["java"])
            with snapshot_export_guard(manager):
                self.refused(root, manager.snapshot_export_accept, accept_request(first), codes={"SNAPSHOT_EXPORT_PREVIEW_CHANGED"})
                self.refused(root, manager.snapshot_export_accept,
                    {**accept_request(second), "preview_sha256": first["preview_sha256"]}, codes={"SNAPSHOT_EXPORT_PREVIEW_CHANGED"})
                accepted = manager.snapshot_export_accept(accept_request(second))
                self.refused(root, manager.snapshot_export_accept, accept_request(second), codes={"SNAPSHOT_EXPORT_PREVIEW_REQUIRED"})
                manager.snapshot_export_download(download_request(accepted, second))

    def test_fields_notes_and_unknown_attempts_refuse_without_paths_or_writes(self):
        with snapshot_fixture() as (root, manager, fixtures):
            preview = self.preview(root, manager, fixtures["python"])
            with snapshot_export_guard(manager):
                for value in [[], {"id": fixtures["python"]["attempt_id"]}, {"attempt_id": "../" + PRIVATE_SENTINEL},
                              {"attempt_id": "f" * 16}, {"attempt_id": fixtures["python"]["attempt_id"], "path": PRIVATE_SENTINEL}]:
                    with self.subTest(value=value):
                        self.refused(root, manager.snapshot_export_preview, value)
            preview = self.preview(root, manager, fixtures["python"])
            with snapshot_export_guard(manager):
                for note in [42, None, "\x00", "x" * 1001, "界" * 1000]:
                    self.refused(root, manager.snapshot_export_accept, accept_request(preview, note), codes={"SNAPSHOT_EXPORT_NOTE_INVALID"})
                for value in [{**accept_request(preview), "path": PRIVATE_SENTINEL}, {"preview_id": preview["preview_id"]}]:
                    self.refused(root, manager.snapshot_export_accept, value, codes={"SNAPSHOT_EXPORT_FIELDS"})
                self.refused(root, manager.snapshot_export_accept,
                    {key: preview[key] for key in ["preview_id", "preview_sha256"]}, codes={"SNAPSHOT_EXPORT_FIELDS"})
                # The note is optional user input, represented by an empty DTO string.
                accepted = manager.snapshot_export_accept(accept_request(preview, ""))
                request = download_request(accepted, preview)
                for value in [{**request, "receipt_sha256": "a" * 64}, {**request, "archive_sha256": "b" * 64},
                              {**request, "acceptance_id": "../" + PRIVATE_SENTINEL}, {**request, "path": PRIVATE_SENTINEL}]:
                    self.refused(root, manager.snapshot_export_download, value)

    def test_config_task_and_live_input_drift_refuse_before_acceptance_write(self):
        for mode in ["config", "task", "source", "editable", "protected", "git"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                if mode == "config":
                    manager.config_path.write_bytes(manager.config_raw + b" \n")
                elif mode == "task":
                    fixture["task"].write_bytes(fixture["task"].read_bytes() + b" \n")
                elif mode == "source":
                    path = fixture["source"] / "arithmetic.py"; path.write_bytes(path.read_bytes() + b"# original drift\n")
                elif mode in ["editable", "protected"]:
                    path = fixture["workspace"] / ("arithmetic.py" if mode == "editable" else "test_arithmetic.py")
                    path.write_bytes(path.read_bytes() + b"# live worktree drift\n")
                else:
                    path = fixture["job_dir"] / "workspace/baseline-repo/.git/worktrees/review/HEAD"
                    path.write_bytes(b"ref: refs/heads/invented-other-branch\n")
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_accept, accept_request(preview))
                self.assertEqual(list((manager.data / "snapshot-exports").iterdir()), [])

    def test_config_or_task_drift_skips_all_selected_source_reads(self):
        for mode in ["config", "task"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                path = manager.config_path if mode == "config" else fixture["task"]
                path.write_bytes(path.read_bytes() + b" \n")
                with snapshot_export_guard(manager), ExitStack() as stack:
                    for target in ["snapshot_export.read_selected", "workspace_recheck.read_selected", "bundle_workspace.read_selected"]:
                        stack.enter_context(patch(target, side_effect=AssertionError("drifted profile reached selected source")))
                    self.refused(root, manager.snapshot_export_accept, accept_request(preview), codes={"SNAPSHOT_EXPORT_PROJECT_CHANGED"})
                    self.refused(root, manager.snapshot_export_preview, {"attempt_id": fixture["attempt_id"]}, codes={"SNAPSHOT_EXPORT_PROJECT_CHANGED"})

    def test_changed_saved_evidence_never_becomes_exportable(self):
        for mode in ["snapshot", "task", "request", "initial", "receipt", "checks", "checks_missing"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                attempt = fixture["attempt_dir"]
                if mode == "snapshot":
                    path = attempt / "snapshot/arithmetic.py"; path.write_bytes(path.read_bytes() + b"# untested snapshot drift\n")
                elif mode in ["task", "request", "initial"]:
                    path = attempt / {"task": "task.json", "request": "request.json", "initial": "initial-receipt.json"}[mode]
                    if mode == "task":
                        path.write_bytes(path.read_bytes() + b" \n")
                    else:
                        value = json.loads(path.read_bytes())
                        value["history_sha256"] = "a" * 64
                        path.write_bytes(canonical(value))
                elif mode == "receipt":
                    path = attempt / "receipt.json"; row = json.loads(path.read_bytes()); row["status"] = "FAILED"
                    path.write_bytes(canonical(row))
                elif mode == "checks":
                    path = attempt / "checks.json"; path.write_bytes(path.read_bytes() + b" \n")
                else:
                    (attempt / "checks.json").unlink()
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_preview, {"attempt_id": fixture["attempt_id"]})

    def test_consistently_rehashed_invalid_check_shapes_cannot_fake_verification(self):
        for mode in ["extra", "missing", "bool_exit", "bool_count", "failed", "timed_out"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]; attempt = fixture["attempt_dir"]
                checks = json.loads((attempt / "checks.json").read_bytes())
                name = next(iter(checks)); row = checks[name]
                if mode == "extra": checks["invented_extra"] = dict(row)
                elif mode == "missing": checks = {}
                elif mode == "bool_exit": row["exit_code"] = False
                elif mode == "bool_count": row["tests_ran"] = True
                elif mode == "failed": row["exit_code"] = 1
                else: row["timed_out"] = True
                raw = canonical(checks); (attempt / "checks.json").write_bytes(raw)
                receipt = json.loads((attempt / "receipt.json").read_bytes())
                receipt.update(checks=checks, checks_sha256=sha(raw))
                (attempt / "receipt.json").write_bytes(canonical(receipt))
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_preview, {"attempt_id": fixture["attempt_id"]})

    def test_noop_verified_baseline_snapshot_has_no_patch_to_accept(self):
        from workspace_recheck import build
        with snapshot_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            path = fixture["workspace"] / "arithmetic.py"
            path.write_bytes((fixture["source"] / "arithmetic.py").read_bytes())
            preview = manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(preview))
                build(attempt_path(manager, started["id"]), checker=passing_checks)
                child.poll.return_value = 0
                manager.recheck_view(started["id"])
            with snapshot_export_guard(manager):
                self.refused(root, manager.snapshot_export_preview, {"attempt_id": started["id"]}, codes={"SNAPSHOT_EXPORT_NO_CHANGES"})

    def test_later_acceptance_invalidates_older_download_without_rewriting_it(self):
        with snapshot_fixture(("python", "java")) as (root, manager, fixtures):
            first = self.preview(root, manager, fixtures["python"])
            with snapshot_export_guard(manager):
                accepted = manager.snapshot_export_accept(accept_request(first))
            old = private_hashes(export_path(manager, accepted["acceptance_id"]))
            second = self.preview(root, manager, fixtures["java"])
            with snapshot_export_guard(manager):
                newest = manager.snapshot_export_accept(accept_request(second))
                self.refused(root, manager.snapshot_export_download, download_request(accepted, first), codes={"SNAPSHOT_EXPORT_HISTORY_CHANGED"})
                manager.snapshot_export_download(download_request(newest, second))
            self.assertEqual(old, private_hashes(export_path(manager, accepted["acceptance_id"])))

    def test_new_recheck_invalidates_download_even_when_original_snapshot_is_intact(self):
        from workspace_recheck import build
        with snapshot_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            preview = self.preview(root, manager, fixture)
            with snapshot_export_guard(manager):
                accepted = manager.snapshot_export_accept(accept_request(preview))
            old = private_hashes(fixture["attempt_dir"])
            another = manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
            with fake_recheck(manager) as (child, _):
                started = manager.recheck_start(recheck_request(another))
                build(attempt_path(manager, started["id"]), checker=passing_checks)
                child.poll.return_value = 0
                manager.recheck_view(started["id"])
            self.assertEqual(old, private_hashes(fixture["attempt_dir"]))
            with snapshot_export_guard(manager):
                self.refused(root, manager.snapshot_export_download, download_request(accepted, preview), codes={"SNAPSHOT_EXPORT_HISTORY_CHANGED"})

    def test_unsafe_record_and_snapshot_ancestors_refuse_without_outside_reads(self):
        for mode in ["snapshot_link", "snapshot_hardlink", "attempt_root", "export_store"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                outside = root / "outside-private-records"; outside.mkdir()
                write_new(outside / "sentinel", PRIVATE_SENTINEL.encode())
                if mode.startswith("snapshot_"):
                    path = fixture["attempt_dir"] / "snapshot/arithmetic.py"
                    other = outside / "arithmetic.py"; other.write_bytes(path.read_bytes()); path.unlink()
                    path.symlink_to(other) if mode.endswith("link") and mode != "snapshot_hardlink" else path.hardlink_to(other)
                else:
                    path = fixture["attempt_dir"] if mode == "attempt_root" else manager.data / "snapshot-exports"
                    path.rename(root / ("retained-" + mode)); path.symlink_to(outside, target_is_directory=True)
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_preview, {"attempt_id": fixture["attempt_id"]})

    def test_new_execution_preview_invalidates_export_review_without_export_writes(self):
        with snapshot_fixture() as (root, manager, fixtures):
            fixture = fixtures["python"]
            preview = self.preview(root, manager, fixture)
            before = private_hashes(root)
            manager.recheck_preview({"workspace_id": fixture["workspace_id"]})
            self.assertEqual(before, private_hashes(root))
            with snapshot_export_guard(manager):
                self.refused(root, manager.snapshot_export_accept, accept_request(preview), codes={"SNAPSHOT_EXPORT_PREVIEW_REQUIRED"})

    def test_failed_acceptance_is_retained_and_blocks_new_acceptance_and_old_download(self):
        for mode in ["fresh_validation", "review_write", "own_review"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                first = self.preview(root, manager, fixture)
                with snapshot_export_guard(manager):
                    accepted = manager.snapshot_export_accept(accept_request(first))
                old_approval = private_hashes(export_path(manager, accepted["acceptance_id"]))
                preview = self.preview(root, manager, fixture)
                before = private_hashes(root)
                original_prepare, original_write = manager._snapshot_prepared, write_new
                calls = []

                def prepare_again(*args):
                    calls.append(args)
                    if mode == "fresh_validation" and len(calls) == 2:
                        raise Refused("SNAPSHOT_EXPORT_STALE")
                    prepared = original_prepare(*args)
                    if mode == "own_review" and len(calls) == 2:
                        pending = next(path for path in (manager.data / "snapshot-exports").iterdir()
                            if json.loads((path / "receipt.json").read_bytes())["status"] == "PREPARING")
                        (pending / "review.json").write_bytes(b"[]")
                    return prepared

                def partial_write(path, raw):
                    if path.name == "review.json":
                        raise OSError(PRIVATE_SENTINEL)
                    return original_write(path, raw)

                target = patch("workbench.write_new", side_effect=partial_write) if mode == "review_write" else patch.object(manager, "_snapshot_prepared", side_effect=prepare_again)
                with snapshot_export_guard(manager), target:
                    with self.assertRaisesRegex(Refused, "^SNAPSHOT_EXPORT_ACCEPT_FAILED$"):
                        manager.snapshot_export_accept(accept_request(preview))
                self.assertEqual(old_approval, private_hashes(export_path(manager, accepted["acceptance_id"])))
                added = set(private_hashes(root)) - set(before)
                self.assertTrue(added)
                self.assertTrue(all(name.startswith(str((manager.data / "snapshot-exports").relative_to(root)) + "/") for name in added))
                with snapshot_export_guard(manager):
                    history = manager.snapshot_export_history(fixture["attempt_id"])
                    failed = next(row for row in history["acceptances"] if row["status"] == "FAILED")
                    self.assertEqual(failed["reason"], "SNAPSHOT_EXPORT_ACCEPT_FAILED")
                    self.assertEqual(failed["archive_sha256"], preview["artifact"]["archive_sha256"])
                    self.refused(root, manager.snapshot_export_accept, accept_request(preview), codes={"SNAPSHOT_EXPORT_PREVIEW_REQUIRED"})
                    self.refused(root, manager.snapshot_export_download, download_request(accepted, first), codes={"SNAPSHOT_EXPORT_HISTORY_UNRESOLVED"})
                fresh = self.preview(root, manager, fixture)
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_accept, accept_request(fresh), codes={"SNAPSHOT_EXPORT_HISTORY_UNRESOLVED"})

    def test_malformed_unfinished_and_partial_history_never_falls_back_to_old_approval(self):
        for mode in ["preparing", "malformed", "missing_review", "next"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                with snapshot_export_guard(manager):
                    accepted = manager.snapshot_export_accept(accept_request(preview))
                directory = export_path(manager, accepted["acceptance_id"])
                receipt = directory / "receipt.json"
                if mode == "preparing":
                    value = json.loads(receipt.read_bytes()); value["status"] = "PREPARING"; value.pop("finished")
                    receipt.write_bytes(canonical(value))
                elif mode == "malformed": receipt.write_bytes(b"[]")
                elif mode == "missing_review": (directory / "review.json").unlink()
                else: write_new(directory / "receipt.json.next", receipt.read_bytes())
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_download, download_request(accepted, preview))
                before = private_hashes(root)
                self.assertEqual(before, private_hashes(root))

    def test_damaged_prior_review_blocks_unrelated_acceptance_download_preview_and_history(self):
        for mode in ["corrupt", "symlink"]:
            with self.subTest(mode=mode), snapshot_fixture(("python", "java")) as (root, manager, fixtures):
                first = self.preview(root, manager, fixtures["python"])
                with snapshot_export_guard(manager):
                    accepted = manager.snapshot_export_accept(accept_request(first))
                pending = self.preview(root, manager, fixtures["java"])
                review = export_path(manager, accepted["acceptance_id"]) / "review.json"
                if mode == "corrupt":
                    review.write_bytes(b"[]")
                else:
                    outside = root / "outside-private-review.json"; outside.write_text(PRIVATE_SENTINEL)
                    review.unlink(); review.symlink_to(outside)
                with snapshot_export_guard(manager):
                    self.refused(root, manager.snapshot_export_accept, accept_request(pending))
                    self.refused(root, manager.snapshot_export_download, download_request(accepted, first))
                    self.refused(root, manager.snapshot_export_history, fixtures["java"]["attempt_id"])
                    self.refused(root, manager.snapshot_export_preview, {"attempt_id": fixtures["java"]["attempt_id"]})

    def test_acceptance_count_and_aggregate_reserve_refuse_before_new_record(self):
        for mode in ["count", "aggregate"]:
            with self.subTest(mode=mode), snapshot_fixture() as (root, manager, fixtures):
                fixture = fixtures["python"]
                preview = self.preview(root, manager, fixture)
                with snapshot_export_guard(manager):
                    accepted = manager.snapshot_export_accept(accept_request(preview))
                template = accepted["receipt"]
                review_raw = (export_path(manager, accepted["acceptance_id"]) / "review.json").read_bytes()
                count = 200 if mode == "count" else 65
                for number in range(count - 1):
                    identifier = f"{number:016x}"
                    directory = export_path(manager, identifier); directory.mkdir(mode=0o700)
                    raw = canonical({**template, "id": identifier})
                    if mode == "aggregate": raw += b" " * (32400 - len(raw))
                    write_new(directory / "receipt.json", raw)
                    write_new(directory / "review.json", review_raw)
                preview = self.preview(root, manager, fixture)
                prepared = {"summary": preview["artifact"]}
                with snapshot_export_guard(manager), patch.object(manager, "_snapshot_prepared", return_value=prepared):
                    self.refused(root, manager.snapshot_export_accept, accept_request(preview), codes={"SNAPSHOT_EXPORT_LIMIT"})
                self.assertEqual(len(list((manager.data / "snapshot-exports").iterdir())), count)


@contextmanager
def snapshot_http_fixture():
    with snapshot_fixture() as (root, manager, fixtures):
        handler_type = make_handler(manager, "invented-snapshot-export-token", "http://127.0.0.1:8765")

        def request(method, path, value=None, headers=None):
            raw = canonical(value) if value is not None else b""
            supplied = {"Host": "127.0.0.1:8765", "X-Workbench-Token": "invented-snapshot-export-token"}
            if method == "POST":
                supplied.update({"Origin": "http://127.0.0.1:8765", "Content-Type": "application/json", "Content-Length": str(len(raw))})
            duplicate = headers if isinstance(headers, list) else []
            if isinstance(headers, dict): supplied.update(headers)
            handler = handler_type.__new__(handler_type)
            handler.command, handler.path = method, path
            handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
            handler.headers = Message()
            for key, item in list(supplied.items()) + duplicate: handler.headers[key] = item
            handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
            getattr(handler, "do_" + method)()
            head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            response_headers = dict(line.decode().split(": ", 1) for line in head.split(b"\r\n")[1:])
            value = body if response_headers.get("Content-Type") == "application/zip" else json.loads(body)
            return int(head.split(b" ", 2)[1]), response_headers, value

        yield root, manager, fixtures, request


class SnapshotExportHTTPTests(unittest.TestCase):
    def test_explicit_review_then_binary_download_and_read_only_history(self):
        with snapshot_http_fixture() as (root, manager, fixtures, request):
            fixture = fixtures["python"]
            before = private_hashes(root)
            with snapshot_export_guard(manager):
                code, _, preview = request("POST", "/api/snapshot-export-preview", {"attempt_id": fixture["attempt_id"]})
            self.assertEqual(code, 200)
            self.assertEqual(before, private_hashes(root))
            with snapshot_export_guard(manager):
                code, headers, accepted = request("POST", "/api/snapshot-export-accept", accept_request(preview))
            self.assertEqual((code, headers["Content-Type"].split(";", 1)[0]), (200, "application/json"))
            before = private_hashes(root)
            with snapshot_export_guard(manager):
                code, headers, raw = request("POST", "/api/snapshot-export-download", download_request(accepted, preview))
                self.assertEqual((code, headers["Content-Type"]), (200, "application/zip"))
                self.assertEqual(int(headers["Content-Length"]), len(raw))
                self.assertIn("attachment;", headers["Content-Disposition"])
                self.assertNotIn(str(root), headers["Content-Disposition"])
                self.assertEqual(sha(raw), preview["artifact"]["archive_sha256"])
                assert_patch_snapshot(fixture, raw)
                code, _, history = request("GET", "/api/snapshot-export-history/" + fixture["attempt_id"])
                self.assertEqual(code, 200)
                self.assertEqual(history["acceptances"][-1]["id"], accepted["acceptance_id"])
            self.assertEqual(before, private_hashes(root))

    def test_framing_host_token_origin_and_fetch_guards_precede_all_export_actions(self):
        with snapshot_http_fixture() as (root, manager, fixtures, request):
            bodies = [("preview", {"attempt_id": fixtures["python"]["attempt_id"]}),
                ("accept", {"preview_id": "1" * 16, "preview_sha256": "a" * 64, "note": ""}),
                ("download", {"acceptance_id": "1" * 16, "receipt_sha256": "a" * 64, "archive_sha256": "b" * 64})]
            before = private_hashes(root)
            for action, body in bodies:
                with patch.object(manager, "snapshot_export_" + action, side_effect=AssertionError("bad HTTP reached manager")) as invoke:
                    for headers in [{"Transfer-Encoding": "chunked"}, {"Content-Length": str(len(canonical(body)) + 1)},
                                    [("Content-Length", str(len(canonical(body))))], {"Content-Length": "32769"},
                                    {"Content-Length": "0"}, {"Content-Length": "-1"}]:
                        code, _, value = request("POST", "/api/snapshot-export-" + action, body, headers)
                        self.assertEqual(code, 409)
                        self.assertRegex(value["error"], r"^[A-Z_]+$")
                    for headers, error in [({"Host": "malicious.invalid"}, "HOST_REFUSED"),
                                           ({"X-Workbench-Token": ""}, "SESSION_REQUIRED"),
                                           ({"Origin": "https://malicious.invalid"}, "ORIGIN_REFUSED"),
                                           ({"Sec-Fetch-Site": "cross-site"}, "CROSS_SITE_REFUSED")]:
                        code, _, value = request("POST", "/api/snapshot-export-" + action, body, headers)
                        self.assertEqual((code, value["error"]), (409, error))
                    invoke.assert_not_called()
            self.assertEqual(before, private_hashes(root))


if __name__ == "__main__":
    unittest.main()
