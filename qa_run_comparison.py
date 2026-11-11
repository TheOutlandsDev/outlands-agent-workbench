"""Compare invented saved Python/Java histories without reconciling or executing them."""

import json
from pathlib import Path

from test_run_comparison_integration import populate_saved_histories, private_hashes, saved_only_guard
from workbench import Manager, init_demo


def acceptance(work):
    root = work / "run-comparison"
    root.mkdir(mode=0o700)
    paths = init_demo(root / "workspace", None)
    manager = Manager(Path(paths["config"]), Path(paths["data_dir"]))
    try:
        ids = populate_saved_histories(manager)
        before = private_hashes(root)
        with saved_only_guard(manager):
            history = manager.comparison_history()
            pairs = {name: manager.compare(ids[left], ids[right]) for name, left, right in [
                ("python", "python_ok", "python_failed"),
                ("java", "java_ok", "java_failed"),
                ("uncertain", "python_ok", "python_uncertain"),
                ("legacy", "python_ok", "python_legacy"),
                ("different_language", "python_ok", "java_ok"),
                ("corrupt", "python_ok", "corrupt"),
                ("saved_running", "python_ok", "python_running"),
            ]}
        assert before == private_hashes(root), "comparison changed saved evidence"
        assert len(history["runs"]) == len(ids)
        assert pairs["python"]["comparable"] and pairs["java"]["comparable"]
        assert not pairs["different_language"]["comparable"] and not pairs["corrupt"]["comparable"]
        assert pairs["uncertain"]["right"]["state"] == "UNCERTAIN"
        assert pairs["saved_running"]["right"]["state"] == "RUNNING"
        assert pairs["legacy"]["right"]["metrics"]["request_bytes"] is None
        assert pairs["legacy"]["right"]["metrics"]["elapsed_ms"] is None
        assert pairs["python"]["metrics_delta"] == {"requests": 0, "request_bytes": 1000, "elapsed_ms": 150}
        assert (manager.data / "state/hold.json").read_bytes()
    finally:
        manager.close()
    (work / "run-comparison-acceptance.json").write_text(json.dumps({
        "history": history, "comparisons": pairs, "saved_bytes_unchanged": True,
        "fixture_hold_unchanged": True, "real_model_requests": 0,
        "records_are_invented": True,
    }, indent=2) + "\n")
    return {"comparison_python_java_histories_passed": True,
            "comparison_failed_uncertain_legacy_corrupt_histories_passed": True,
            "comparison_saved_running_not_reconciled": True,
            "comparison_saved_bytes_and_hold_unchanged": True,
            "comparison_real_model_requests": 0}
