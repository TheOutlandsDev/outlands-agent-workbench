"""Actual invented Python/Java search, edit, fresh checks and private export.

Navigation is read-only and guarded against execution. Actual fixed checks run
separately through the existing isolated worker, never through search or reads.
"""

import json

from agent import Refused, canonical, sha, write_new
from qa_bundle_workspace import _assert_source_git, _manager, _source_git
from qa_snapshot_editor import _checked
from qa_snapshot_recheck import _create_initial
from snapshot_export import verify_export
from test_bundle_workspace_integration import private_hashes
from test_snapshot_editor_integration import editor_guard, save_request
from test_snapshot_reexport_integration import (
    accept_request, archive_parts, assert_patch_snapshot, download_request, snapshot_reexport_guard,
)
from test_workspace_search_integration import (
    open_request, read_request, search_guard, search_request, selected_hit,
)


def acceptance(jdk, work):
    root = work / "workspace-search"
    manager, projects = _manager(root, jdk)
    observations, fixtures = {}, {}
    try:
        originals = {language: _source_git(manager, projects[language]) for language in ["python", "java"]}
        builder_before = private_hashes(root / "bundle-builder")
        for language in ["python", "java"]:
            fixture = _create_initial(manager, projects[language])
            before = private_hashes(root)
            with search_guard(manager):
                all_hits = manager.workspace_search(search_request(fixture, "add"))
                protected_hit = selected_hit(all_hits, editable=False)
                protected = manager.workspace_read(read_request(all_hits, protected_hit))
                assert protected["editable"] is False and protected["result"]["sha256"] == protected_hit["sha256"]
                result = manager.workspace_search(search_request(fixture, "a + b"))
                hit = selected_hit(result)
                focused = manager.workspace_read(read_request(result, hit))
                assert focused["editable"] is True and "a + b" in focused["result"]["lines"][0]["text"]
            with search_guard(manager, open_editor=True):
                try:
                    manager.workspace_search_open(open_request(all_hits, protected_hit))
                except Refused as error:
                    assert str(error) == "WORKSPACE_SEARCH_PROTECTED"
                else:
                    raise AssertionError("protected navigation result opened for editing")
                opened = manager.workspace_search_open(open_request(result, hit))
            assert before == private_hashes(root)
            assert opened["sha256"] == hit["sha256"] and not opened["admission"]["blocked"]
            with editor_guard(manager):
                preview = manager.snapshot_editor_preview({"workspace_id": fixture["workspace_id"], "path": hit["path"],
                    "expected_sha256": hit["sha256"], "old_text": "a + b", "new_text": "(a + b)"})
                saved = manager.snapshot_editor_save(save_request(preview))
            target = fixture["workspace"] / hit["path"]
            expected = opened["text"].encode().replace(b"a + b", b"(a + b)", 1)
            assert target.read_bytes() == expected and saved["after_sha256"] == sha(expected)
            edit_dir = manager.data / "snapshot-workspace-edits" / saved["edit_id"]
            prefix, relative = str(edit_dir.relative_to(root)) + "/", str(target.relative_to(root))
            after = private_hashes(root)
            assert {n: d for n, d in before.items() if n != relative} == {
                n: d for n, d in after.items() if n != relative and not n.startswith(prefix)}
            with search_guard(manager):
                try:
                    manager.workspace_read(read_request(result, hit))
                except Refused as error:
                    assert str(error) == "WORKSPACE_SEARCH_STALE"
                else:
                    raise AssertionError("pre-edit search result remained current")
                refreshed = manager.workspace_search(search_request(fixture))
                assert selected_hit(refreshed)["sha256"] == saved["after_sha256"]
            before_recheck = private_hashes(fixture["job_dir"])
            fresh = _checked(manager, fixture)
            assert before_recheck == private_hashes(fixture["job_dir"])
            assert fresh["checked_files"][hit["path"]] == sha(expected)
            attempt_dir = manager.data / "snapshot-workspace-rechecks" / fresh["id"]
            fixture.update(attempt_id=fresh["id"], attempt_dir=attempt_dir,
                recheck_receipt_sha256=sha((attempt_dir / "receipt.json").read_bytes()))
            fixtures[language] = fixture
            observations[language] = {"workspace": fixture["workspace_id"], "edit": saved,
                "search_snapshot_sha256": result["snapshot_sha256"], "focused_file_sha256": hit["sha256"],
                "protected_file_sha256": protected_hit["sha256"], "fresh_recheck": fresh["id"], "checks": fresh["checks"]}
            _assert_source_git(projects[language], originals[language])

        # Hold addition is an invented independent acceptance fixture, performed
        # only after actual checks. It is never removed, cleared or retried.
        hold = manager.data / "state/hold.json"
        hold_raw = canonical({"state": "REQUEST_UNSETTLED", "run": "Invented workspace navigation hold", "turn": 1})
        write_new(hold, hold_raw)
        before_held = private_hashes(root)
        fixture = fixtures["python"]
        with search_guard(manager):
            result = manager.workspace_search(search_request(fixture, "(a + b)"))
            hit = selected_hit(result)
            manager.workspace_read(read_request(result, hit))
        with search_guard(manager, open_editor=True):
            opened = manager.workspace_search_open(open_request(result, hit))
            assert opened["admission"]["blocked"]
        with editor_guard(manager):
            preview = manager.snapshot_editor_preview({"workspace_id": fixture["workspace_id"], "path": hit["path"],
                "expected_sha256": hit["sha256"], "old_text": "(a + b)", "new_text": "((a + b))"})
            try:
                manager.snapshot_editor_save(save_request(preview))
            except Refused as error:
                assert str(error) == "SNAPSHOT_EDITOR_BLOCKED"
            else:
                raise AssertionError("navigation bypassed held editor save admission")
        assert before_held == private_hashes(root)
        for language, fixture in fixtures.items():
            with snapshot_reexport_guard(manager):
                preview = manager.snapshot_reexport_preview({"attempt_id": fixture["attempt_id"]})
                accepted = manager.snapshot_reexport_accept(accept_request(preview, "Invented explicit workspace navigation review."))
                raw = manager.snapshot_reexport_download(download_request(accepted, preview))
            verified = verify_export(raw, preview["artifact"]["archive_sha256"])
            assert verified["version"] == 2
            parts = assert_patch_snapshot(fixture, raw)
            assert b"(a + b)" in parts["changes.diff"]
            assert b"Invented explicit workspace navigation review" not in b"".join(parts.values())
            assert all(str(root).encode() not in value for value in archive_parts(raw).values())
            write_new(work / ("invented-search-" + language + ".zip"), raw)
            observations[language].update(acceptance_id=accepted["acceptance_id"], archive_sha256=sha(raw), version=2)
            _assert_source_git(projects[language], originals[language])
            assert hold.read_bytes() == hold_raw
        assert builder_before == private_hashes(root / "bundle-builder")
        write_new(work / "workspace-search-acceptance.json", canonical({
            "observations": observations, "fixtures_are_invented": True,
            "navigation_execution_git_model_calls": 0, "actual_checks_performed_separately": True,
            "search_read_open_private_bytes_unchanged": True, "exact_target_and_new_edit_records_only": True,
            "original_source_git_unchanged": True, "historical_creation_and_checks_preserved": True,
            "stale_pre_edit_result_refused": True, "protected_read_allowed_edit_refused": True,
            "held_navigation_allowed_save_refused_without_writes": True, "hold_retained": True,
        }))
    finally:
        manager.close()
    return {"workspace_search_python_java_search_edit_recheck_export": True,
            "workspace_search_protected_read_edit_refusal": True,
            "workspace_search_stale_pins_refused": True,
            "workspace_search_original_source_git_unchanged": True,
            "workspace_search_held_navigation_save_blocked": True,
            "workspace_search_model_requests": 0}
