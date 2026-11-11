"""Offline private bundle acceptance with invented saved Python/Java artifacts."""

import json
from pathlib import Path

from agent import Refused, write_new
from patch_bundle import verify_bundle
from test_patch_bundle_integration import populate_bundle_runs, private_hashes, rewrite_json, saved_only_guard
from workbench import Manager, init_demo


def acceptance(work):
    root = work / "patch-bundle"
    root.mkdir(mode=0o700)
    paths = init_demo(root / "workspace", None)
    manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
    observations = {}
    try:
        ids = populate_bundle_runs(manager, root)
        hold = manager.data / "state/hold.json"
        hold_raw = hold.read_bytes()
        before = private_hashes(root)
        bundles = {}
        with saved_only_guard(manager):
            for language, run_id in ids.items():
                preview = manager.bundle_preview(run_id)
                raw = manager.bundle_export(run_id, preview["bundle_sha256"])
                assert preview == verify_bundle(raw, preview["bundle_sha256"])
                assert preview == manager.bundle_preview(run_id)
                assert raw == manager.bundle_export(run_id, preview["bundle_sha256"])
                observations[language] = preview
                bundles[language] = raw
        assert before == private_hashes(root)
        assert hold.read_bytes() == hold_raw
        # Saved downloads are deliberately outside the tree covered by the
        # no-mutation assertion, and remain private acceptance artifacts.
        for language, raw in bundles.items():
            write_new(work / ("invented-" + language + "-reviewed-bundle.zip"), raw)

        source = manager.projects["bundle_python"]["source"] / "arithmetic.py"
        source.write_bytes(source.read_bytes() + b"# intentional later invented source edit\n")
        before_stale = private_hashes(root)
        with saved_only_guard(manager):
            try:
                manager.bundle_preview(ids["python"])
            except Refused as exc:
                assert str(exc) == "BUNDLE_SOURCE_CHANGED"
            else:
                raise AssertionError("stale source was bundled")
        assert before_stale == private_hashes(root)

        review = manager.run_path(ids["java"]) / "review-000.json"
        rewrite_json(review, lambda row: row.update(note="intentional later invented review note"))
        before_pin = private_hashes(root)
        with saved_only_guard(manager):
            try:
                manager.bundle_export(ids["java"], observations["java"]["bundle_sha256"])
            except Refused as exc:
                assert str(exc) == "BUNDLE_CHANGED"
            else:
                raise AssertionError("stale download pin was accepted")
        assert before_pin == private_hashes(root)
        assert hold.read_bytes() == hold_raw
    finally:
        manager.close()
    (work / "patch-bundle-acceptance.json").write_text(json.dumps({
        "observations": observations, "records_are_invented": True,
        "saved_bytes_unchanged_per_operation": True, "unrelated_fixture_hold_retained": True,
        "bundle_checks_executed": 0, "bundle_model_requests": 0,
    }, indent=2) + "\n")
    return {"bundle_python_java_roundtrip": True, "bundle_deterministic": True,
            "bundle_stale_download_pin_refused": True, "bundle_stale_source_refused": True,
            "bundle_private_bytes_unchanged": True, "bundle_unrelated_hold_retained": True,
            "bundle_checks_executed": 0, "bundle_model_requests": 0}
