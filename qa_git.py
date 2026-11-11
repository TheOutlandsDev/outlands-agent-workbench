"""Actual owned workspace worker and prerequisite acceptance; no model inference."""

import json
import time

from launch import doctor
from test_workbench import decision, manager_fixture


def acceptance(jdk, work):
    prerequisite = doctor([], jdk)
    assert prerequisite["status"] == "PASS" and prerequisite["inference_requests"] == 0
    with manager_fixture(seed=True) as (_, manager, run_id):
        source = manager.projects["arithmetic"]["source"]
        original = (source / "calculator.py").read_bytes()
        manager.review(decision(manager, run_id))
        view = manager.view(run_id)
        request = {"id": run_id, "result_sha256": view["result_sha256"], "patch_sha256": view["patch_sha256"]}
        first = manager.create_workspace(request)
        assert first["status"] == "PREPARING"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            receipt = manager.workspace_receipt(run_id)
            if receipt["status"] != "PREPARING" and run_id not in manager.workspace_children:
                break
            time.sleep(0.05)
        assert receipt["status"] == "VERIFIED" and receipt["checks"]["unit"]["tests_ran"] == 4
        assert manager.admission() is None
        assert manager.create_workspace(request) == receipt
        assert (source / "calculator.py").read_bytes() == original
        assert manager.workspace_children == {}
    (work / "git-acceptance.json").write_text(json.dumps({"prerequisites": prerequisite,
        "owned_worker": "PASS", "accepted_patch_rechecked": True, "original_preserved": True,
        "idempotent_no_reapplication": True}, indent=2) + "\n")
    return {"git_workspace_worker_passed": True, "git_recheck_tests": 4,
            "launcher_prerequisites_passed": True, "inference_requests": 0}
