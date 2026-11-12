"""Actual Python/Java edit, isolated recheck and reviewed private v2 export.

All projects are invented. Editor operations are guarded against execution;
fresh checks run separately through the existing fixed-check worker.
"""

import json

from agent import Refused, canonical, sha, write_new
from qa_bundle_workspace import _assert_source_git, _manager, _source_git
from qa_snapshot_recheck import _create_initial, _wait_recheck
from snapshot_export import verify_export
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_snapshot_editor_integration import editor_guard, editor_preview, save_request
from test_snapshot_recheck_integration import recheck_preview_guard, recheck_request
from test_snapshot_reexport_integration import (
    accept_request, archive_parts, assert_patch_snapshot, download_request, snapshot_reexport_guard,
)


def _checked(manager, fixture):
    with recheck_preview_guard(manager):
        preview = manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
    with no_provider_calls():
        started = manager.snapshot_recheck_start(recheck_request(preview))
        receipt = _wait_recheck(manager, started["id"])
    assert receipt["status"] == "VERIFIED", receipt.get("reason")
    assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 and not any(row[key] for key in
               ["timed_out", "output_limited", "infrastructure_error"]) for row in receipt["checks"].values())
    return receipt


def acceptance(jdk, work):
    root = work / "snapshot-editor"
    manager, projects = _manager(root, jdk)
    observations, fixtures, old_attempts = {}, {}, {}
    try:
        originals = {language: _source_git(manager, projects[language]) for language in ["python", "java"]}
        builder_before = private_hashes(root / "bundle-builder")
        for language in ["python", "java"]:
            fixture = _create_initial(manager, projects[language])
            old = _checked(manager, fixture)
            old_dir = manager.data / "snapshot-workspace-rechecks" / old["id"]
            old_attempts[old_dir] = private_hashes(old_dir)
            before = private_hashes(root)
            with editor_guard(manager):
                opened, preview = editor_preview(manager, fixture)
            assert before == private_hashes(root)
            assert not opened["admission"]["blocked"] and not preview["admission"]["blocked"]
            with editor_guard(manager):
                saved = manager.snapshot_editor_save(save_request(preview))
            target = fixture["workspace"] / opened["path"]
            expected = opened["text"].encode().replace(b"a + b", b"(a + b)", 1)
            assert target.read_bytes() == expected and saved["after_sha256"] == sha(expected)
            relative = str(target.relative_to(root))
            edit_dir = manager.data / "snapshot-workspace-edits" / saved["edit_id"]
            prefix = str(edit_dir.relative_to(root)) + "/"
            after = private_hashes(root)
            assert {name: value for name, value in before.items() if name != relative} == {
                name: value for name, value in after.items() if name != relative and not name.startswith(prefix)}
            assert {name[len(prefix):] for name in after if name.startswith(prefix)} == {
                "receipt.json", "original.bin", "candidate.bin"}
            edit_receipt = json.loads((edit_dir / "receipt.json").read_bytes())
            assert edit_receipt["status"] == "SAVED" and old["id"] in edit_receipt["prior_recheck_ids"]
            with snapshot_reexport_guard(manager):
                try:
                    manager.snapshot_reexport_preview({"attempt_id": old["id"]})
                except Refused as error:
                    assert str(error) == "SNAPSHOT_REEXPORT_RECHECK_REQUIRED"
                else:
                    raise AssertionError("pre-edit checked snapshot authorized a later edited export")
            before_recheck = private_hashes(fixture["job_dir"])
            fresh = _checked(manager, fixture)
            assert before_recheck == private_hashes(fixture["job_dir"])
            assert fresh["id"] not in edit_receipt["prior_recheck_ids"]
            assert fresh["checked_files"][opened["path"]] == sha(expected)
            attempt_dir = manager.data / "snapshot-workspace-rechecks" / fresh["id"]
            fixture.update(attempt_id=fresh["id"], attempt_dir=attempt_dir,
                recheck_receipt_sha256=sha((attempt_dir / "receipt.json").read_bytes()))
            fixtures[language] = fixture
            observations[language] = {"creation": fixture["workspace_id"], "edit": saved,
                "old_recheck": old["id"], "fresh_recheck": fresh["id"], "checks": fresh["checks"]}
            assert all(private_hashes(path) == hashes for path, hashes in old_attempts.items())
            _assert_source_git(projects[language], originals[language])

        # A separate invented hold is preserved after actual checks finish. It
        # blocks browser saves while allowing read-only review and private export.
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented editor qualification hold", "turn": 1})
        write_new(hold, hold_raw)
        before_block = private_hashes(root)
        with editor_guard(manager):
            _, held_preview = editor_preview(manager, fixtures["python"], "(a + b)", "((a + b))")
            assert held_preview["admission"]["blocked"]
            try:
                manager.snapshot_editor_save(save_request(held_preview))
            except Refused as error:
                assert str(error) == "SNAPSHOT_EDITOR_BLOCKED"
            else:
                raise AssertionError("held edit was saved")
        assert before_block == private_hashes(root)
        for language, fixture in fixtures.items():
            before = private_hashes(root)
            with snapshot_reexport_guard(manager):
                preview = manager.snapshot_reexport_preview({"attempt_id": fixture["attempt_id"]})
            assert before == private_hashes(root)
            with snapshot_reexport_guard(manager):
                accepted = manager.snapshot_reexport_accept(accept_request(preview, "Invented explicit editor qualification review."))
                raw = manager.snapshot_reexport_download(download_request(accepted, preview))
            verified = verify_export(raw, preview["artifact"]["archive_sha256"])
            assert verified["version"] == 2
            parts = assert_patch_snapshot(fixture, raw)
            assert b"(a + b)" in parts["changes.diff"]
            assert b"Invented explicit editor qualification review" not in b"".join(parts.values())
            assert all(str(root).encode() not in value for value in archive_parts(raw).values())
            write_new(work / ("invented-editor-" + language + ".zip"), raw)
            observations[language].update(acceptance_id=accepted["acceptance_id"],
                archive_sha256=sha(raw), version=verified["version"])
            _assert_source_git(projects[language], originals[language])
            assert all(private_hashes(path) == hashes for path, hashes in old_attempts.items())
            assert hold.read_bytes() == hold_raw
        assert builder_before == private_hashes(root / "bundle-builder")
        write_new(work / "snapshot-editor-acceptance.json", canonical({
            "observations": observations, "fixtures_are_invented": True,
            "editor_execution_model_git_calls": 0, "actual_checks_performed_separately": True,
            "exact_target_and_new_edit_records_only": True, "original_source_git_unchanged": True,
            "old_rechecks_and_creation_evidence_preserved": True, "pre_edit_attempts_refused": True,
            "held_save_refused_without_writes": True, "hold_retained": True,
        }))
    finally:
        manager.close()
    return {"snapshot_editor_python_java_edit_recheck_export": True,
            "snapshot_editor_pre_edit_attempts_refused": True,
            "snapshot_editor_original_source_git_unchanged": True,
            "snapshot_editor_prior_evidence_preserved": True,
            "snapshot_editor_held_save_refused": True,
            "snapshot_editor_model_requests": 0}
