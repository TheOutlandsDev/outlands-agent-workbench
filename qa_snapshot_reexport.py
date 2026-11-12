"""Actual Python/Java checked snapshots exported without running or changing them."""

import json
from pathlib import Path

from agent import Refused, canonical, sha, write_new
from qa_bundle_workspace import _assert_source_git, _manager, _source_git
from qa_snapshot_recheck import _create_initial, _wait_recheck
from test_bundle_workspace_integration import no_provider_calls, private_hashes
from test_snapshot_reexport_integration import (
    accept_request, archive_parts, assert_patch_snapshot, download_request, export_path, snapshot_reexport_guard,
)
from test_snapshot_recheck_integration import manual_comment, recheck_preview_guard, recheck_request


def acceptance(jdk, work):
    from snapshot_reexport import prepare
    from snapshot_export import verify_export
    root = work / "snapshot-reexport"
    manager, projects = _manager(root, jdk)
    observations, fixtures, approvals = {}, {}, {}
    try:
        originals = {language: _source_git(manager, projects[language]) for language in ["python", "java"]}
        builder_before = private_hashes(root / "bundle-builder")
        for language in ["python", "java"]:
            fixture = _create_initial(manager, projects[language])
            manual_comment(fixture, language)
            creation_before = private_hashes(fixture["job_dir"])
            with recheck_preview_guard(manager):
                preview = manager.snapshot_recheck_preview({"workspace_id": fixture["workspace_id"]})
            with no_provider_calls():
                started = manager.snapshot_recheck_start(recheck_request(preview))
                receipt = _wait_recheck(manager, started["id"])
            assert receipt["status"] == "VERIFIED"
            assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 for row in receipt["checks"].values())
            assert creation_before == private_hashes(fixture["job_dir"])
            fixture.update(attempt_id=receipt["id"], attempt_dir=manager.data / "snapshot-workspace-rechecks" / receipt["id"],
                recheck_receipt_sha256=sha((manager.data / "snapshot-workspace-rechecks" / receipt["id"] / "receipt.json").read_bytes()))
            fixtures[language] = fixture

        # This separate invented hold is added only after checks have finished.
        # Export inspection, acceptance and download never read or alter it.
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented unrelated snapshot-reexport hold", "turn": 1})
        write_new(hold, hold_raw)
        immutable = private_hashes(root)
        accepted_records = {}
        for language, fixture in fixtures.items():
            before = private_hashes(root)
            with snapshot_reexport_guard(manager):
                preview = manager.snapshot_reexport_preview({"attempt_id": fixture["attempt_id"]})
                prepared = prepare(fixture["attempt_dir"])
                assert prepared["archive"] == prepare(fixture["attempt_dir"])["archive"]
            assert before == private_hashes(root)
            assert preview["artifact"] == prepared["summary"]
            with snapshot_reexport_guard(manager):
                accepted = manager.snapshot_reexport_accept(accept_request(preview, "Invented explicit review; not a model result."))
            prefix = str(export_path(manager, accepted["acceptance_id"]).relative_to(root)) + "/"
            after = private_hashes(root)
            assert before == {name: value for name, value in after.items() if not name.startswith(prefix)}
            assert {name[len(prefix):] for name in after if name.startswith(prefix)} == {"receipt.json", "review.json"}
            with snapshot_reexport_guard(manager):
                raw = manager.snapshot_reexport_download(download_request(accepted, preview))
                assert raw == manager.snapshot_reexport_download(download_request(accepted, preview))
                verified = verify_export(raw, preview["artifact"]["archive_sha256"])
                history = manager.snapshot_reexport_history(fixture["attempt_id"])
            assert after == private_hashes(root)
            assert raw == prepared["archive"] and sha(raw) == preview["artifact"]["archive_sha256"]
            parts = assert_patch_snapshot(fixture, raw)
            verification = json.loads(parts["verification.json"])
            assert verification["hashes"]["receipt_sha256"] == fixture["recheck_receipt_sha256"]
            assert b"a + b" in parts["changes.diff"] and "café".encode() in parts["changes.diff"]
            assert all(str(root).encode() not in value for value in parts.values())
            assert history["acceptances"][-1]["id"] == accepted["acceptance_id"]
            assert all(private_hashes(path) == hashes for path, hashes in accepted_records.items())
            accepted_records[export_path(manager, accepted["acceptance_id"])] = private_hashes(export_path(manager, accepted["acceptance_id"]))
            # Private packets are deliberately outside the tree whose immutability is checked.
            write_new(work / ("invented-" + language + "-snapshot-reexport.zip"), raw)
            # Importing is a separate fresh qualification fixture, never a retry of
            # the unrelated held exporter or its saved jobs. Original holds persist.
            importer, import_projects = _manager(work / ("snapshot-reexport-import-" + language), jdk)
            try:
                import_project = import_projects[language]
                from snapshot_workspace import prepare as prepare_import
                from qa_snapshot_workspace import _wait as wait_import
                from test_bundle_workspace_integration import create_request
                from test_snapshot_workspace_integration import preview_guard as import_preview_guard
                from test_snapshot_project_check_integration import saved_only_guard as snapshot_project_guard
                source_before = private_hashes(import_project["source"])
                with snapshot_project_guard(importer):
                    compared = importer.snapshot_project_check(import_project["project_id"], raw, sha(raw))
                assert compared["comparison"]["status"] == "BASELINE_MATCH"
                assert compared["comparison"]["reconstruction"]["status"] == "VERIFIED"
                with import_preview_guard(importer):
                    imported_preview = importer.snapshot_workspace_preview(import_project["project_id"], raw, sha(raw))
                expected = prepare_import(raw, import_project["source"], importer.projects[import_project["project_id"]]["task_raw"], sha(raw))["snapshot"]
                with no_provider_calls():
                    created = importer.snapshot_workspace_create(create_request(imported_preview))
                    imported = wait_import(importer, created["id"])
                assert imported["status"] == "VERIFIED"
                assert imported["archive_sha256"] == sha(raw)
                assert imported["snapshot"] == {name: sha(value) for name, value in expected.items()}
                assert all(row["exit_code"] == 0 and row["tests_ran"] > 0 for row in imported["checks"].values())
                assert source_before == private_hashes(import_project["source"])
                assert {name: (Path(imported["path"]) / name).read_bytes() for name in expected} == expected
                observations[language + "_reimport"] = {"format": verified["format"], "version": verified["version"], "receipt": imported}
            finally:
                importer.close()
            approvals[language] = (accepted, preview)
            observations[language] = {"attempt_id": fixture["attempt_id"], "acceptance": accepted,
                "artifact": preview["artifact"], "verified": verified}

        before = private_hashes(root)
        accepted, preview = approvals["python"]
        with snapshot_reexport_guard(manager):
            try:
                manager.snapshot_reexport_download(download_request(accepted, preview))
            except Refused as error:
                assert str(error) == "SNAPSHOT_REEXPORT_HISTORY_CHANGED"
            else:
                raise AssertionError("later acceptance failed to invalidate earlier download")
        assert before == private_hashes(root)
        prefix = str((manager.data / "snapshot-reexports").relative_to(root)) + "/"
        assert immutable == {name: value for name, value in private_hashes(root).items() if not name.startswith(prefix)}
        assert builder_before == private_hashes(root / "bundle-builder")
        assert hold.read_bytes() == hold_raw
        for language in ["python", "java"]:
            _assert_source_git(projects[language], originals[language])

        # Separate deliberate negative stage: retain the changed snapshot and all
        # old approvals. Failed reads neither rewrite nor replace their evidence.
        selected = fixtures["java"]["attempt_dir"] / "snapshot/sample/Sum.java"
        selected.write_bytes(selected.read_bytes() + b"// intentional untested snapshot change\n")
        before = private_hashes(root)
        accepted, preview = approvals["java"]
        with snapshot_reexport_guard(manager):
            for operation, request in [(manager.snapshot_reexport_preview, {"attempt_id": fixtures["java"]["attempt_id"]}),
                                       (manager.snapshot_reexport_download, download_request(accepted, preview))]:
                try:
                    operation(request)
                except Refused as error:
                    assert str(error).startswith("SNAPSHOT_REEXPORT_")
                else:
                    raise AssertionError("altered snapshot was exportable")
        assert before == private_hashes(root)
        assert all(private_hashes(path) == hashes for path, hashes in accepted_records.items())
        assert hold.read_bytes() == hold_raw
    finally:
        manager.close()

    (work / "snapshot-reexport-acceptance.json").write_text(json.dumps({"observations": observations,
        "fixtures_are_invented": True, "actual_initial_and_recheck_checks": True,
        "approved_baseline_to_exact_tested_snapshot": True, "deterministic_four_member_archives": True,
        "old_records_source_worktree_git_and_hold_preserved": True,
        "later_acceptance_invalidates_earlier_download": True, "altered_snapshot_refused": True,
        "export_checks_executed": 0, "export_model_requests": 0}, indent=2) + "\n")
    return {"snapshot_reexport_v2_python_java_reimport_passed": True, "snapshot_reexport_python_java_roundtrip": True, "snapshot_reexport_exact_tested_patch": True,
            "snapshot_reexport_deterministic_four_members": True, "snapshot_reexport_old_bytes_unchanged": True,
            "snapshot_reexport_unrelated_hold_retained": True, "snapshot_reexport_history_pin_refused": True,
            "snapshot_reexport_altered_snapshot_refused": True, "snapshot_reexport_checks_executed": 0,
            "snapshot_reexport_model_requests": 0}
