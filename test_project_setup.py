"""Setup transaction and Java task validation; invented temporary projects only."""

import copy
import tempfile
import time
import unittest
from pathlib import Path

from agent import Refused, canonical, validate_task
from project_setup import prepare
from test_workbench import manager_fixture
from workbench import Manager


def request(root):
    source = root / "selected"
    source.mkdir()
    (source / "module.py").write_text("def value(): return 1\n")
    (source / "test_module.py").write_text("import unittest\n")
    (source / "not_selected.txt").write_text("invented ignored content")
    return {"id": "selected", "name": "Selected example", "source": str(source),
            "language": "python", "files": ["module.py", "test_module.py"],
            "editable": ["module.py"], "check": "test_module.py", "goal": "Check the selected value."}


class SetupTests(unittest.TestCase):
    def test_review_save_and_reload_without_source_changes(self):
        with manager_fixture() as (root, manager, _):
            req = request(root)
            before = {p.name: p.read_bytes() for p in Path(req["source"]).iterdir()}
            preview = manager.project_preview(req)
            self.assertEqual({r["path"] for r in preview["files"]}, set(req["files"]))
            self.assertNotIn("selected", manager.projects)
            result = manager.project_save({"draft": preview["draft"]})
            self.assertEqual(result["id"], "selected")
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(req["source"]).iterdir()})
            self.assertEqual(manager.history(), [])
            config = manager.config_path
            other_data = root / "other-data"
            with self.assertRaisesRegex(Refused, "DRAFT_EXPIRED"):
                manager.project_save({"draft": preview["draft"]})
            other = Manager(config, other_data)
            try:
                self.assertEqual(other.projects["selected"]["definition"], manager.projects["selected"]["definition"])
            finally:
                other.close()

    def test_changed_source_between_review_and_save_refused(self):
        with manager_fixture() as (root, manager, _):
            req = request(root); preview = manager.project_preview(req)
            (Path(req["source"]) / "module.py").write_text("def value(): return 2\n")
            with self.assertRaisesRegex(Refused, "SETUP_SOURCE_CHANGED"):
                manager.project_save({"draft": preview["draft"]})
            self.assertNotIn("selected", manager.projects)

    def test_external_config_change_preserved(self):
        with manager_fixture() as (root, manager, _):
            req = request(root); preview = manager.project_preview(req)
            raw = manager.config_raw + b" \n"
            manager.config_path.write_bytes(raw)
            with self.assertRaisesRegex(Refused, "CONFIG_CHANGED"):
                manager.project_save({"draft": preview["draft"]})
            self.assertEqual(manager.config_path.read_bytes(), raw)
            self.assertFalse((manager.data / "projects/selected.json").exists())

    def test_expired_draft_refused(self):
        with manager_fixture() as (root, manager, _):
            preview = manager.project_preview(request(root))
            manager.drafts[preview["draft"]]["expires"] = time.monotonic() - 1
            with self.assertRaisesRegex(Refused, "DRAFT_EXPIRED"):
                manager.project_save({"draft": preview["draft"]})

    def test_duplicate_project_does_not_overwrite(self):
        with manager_fixture() as (root, manager, _):
            req = request(root); preview = manager.project_preview(req)
            manager.project_save({"draft": preview["draft"]})
            raw = manager.config_path.read_bytes()
            with self.assertRaisesRegex(Refused, "PROJECT_EXISTS_OR_LIMIT"):
                manager.project_preview(req)
            self.assertEqual(raw, manager.config_path.read_bytes())

    def test_private_and_escaping_file_selection_refused(self):
        with tempfile.TemporaryDirectory() as d:
            req = request(Path(d))
            for name in ["../outside.py", ".env", ".ssh/config", "private.pem", ".git/config"]:
                changed = copy.deepcopy(req); changed["files"] = [name]
                with self.assertRaises(Refused): prepare(changed, False)

    def test_symlink_and_hardlink_selection_refused(self):
        with tempfile.TemporaryDirectory() as d:
            req = request(Path(d)); source = Path(req["source"])
            (source / "alias.py").symlink_to(source / "module.py")
            req["files"].append("alias.py")
            with self.assertRaises(OSError): prepare(req, False)
            req["files"].remove("alias.py")
            (source / "hard.py").hardlink_to(source / "module.py")
            with self.assertRaisesRegex(Refused, "INPUT_TYPE"): prepare(req, False)

    def test_test_entrypoint_cannot_be_editable(self):
        with tempfile.TemporaryDirectory() as d:
            req = request(Path(d)); req["editable"].append("test_module.py")
            with self.assertRaisesRegex(Refused, "CHECK_PROTECTED"): prepare(req, False)

    def test_uncertainty_blocks_setup(self):
        with manager_fixture() as (root, manager, _):
            (manager.data / "state/hold.json").write_bytes(canonical({"state": "fictional hold"}))
            with self.assertRaisesRegex(Refused, "UNCERTAIN_REQUEST_HELD"):
                manager.project_preview(request(root))

    def test_stale_or_unknown_draft_cannot_save(self):
        with manager_fixture() as (_, manager, _):
            with self.assertRaisesRegex(Refused, "DRAFT_EXPIRED"):
                manager.project_save({"draft": "unknown"})

    def test_selected_duplicate_refused(self):
        with tempfile.TemporaryDirectory() as d:
            req = request(Path(d)); req["files"].append("module.py")
            with self.assertRaisesRegex(Refused, "DUPLICATE_FILE"): prepare(req, False)

    def test_java_requires_configured_jdk_and_protected_main(self):
        with tempfile.TemporaryDirectory() as d:
            req = request(Path(d)); source = Path(req["source"])
            (source / "Thing.java").write_text("class Thing {}\n")
            (source / "ThingTest.java").write_text("class ThingTest {}\n")
            req.update(language="java", files=["Thing.java", "ThingTest.java"], editable=["Thing.java"], check="ThingTest")
            with self.assertRaisesRegex(Refused, "JDK_REQUIRED"): prepare(req, False)
            _, task, _ = prepare(req, True)
            self.assertEqual(task["checks"]["unit"]["sources"], req["files"])
            req["editable"].append("ThingTest.java")
            with self.assertRaisesRegex(Refused, "CHECK_PROTECTED"): prepare(req, True)

    def test_java_task_rejects_arguments_traversal_and_undeclared_sources(self):
        task = {"format": "outlands-coding-agent-v2", "goal": "Check Java", "files": {"Thing.java": "a" * 64, "ThingTest.java": "b" * 64}, "editable": ["Thing.java"], "checks": {"unit": {"kind": "java-main", "sources": ["Thing.java", "ThingTest.java"], "main_class": "ThingTest"}}, "max_turns": 12, "request_seconds": 120}
        for replacement in [{"main_class": "ThingTest --shell"}, {"sources": ["../Thing.java"]}, {"sources": ["unknown.java"]}, {"main_class": "Missing"}]:
            changed = copy.deepcopy(task); changed["checks"]["unit"].update(replacement)
            with self.assertRaises(Refused): validate_task(changed)

    def test_java_project_without_jdk_refuses_before_child_start(self):
        with manager_fixture() as (_, manager, _):
            manager.projects["arithmetic"]["definition"]["checks"] = {"unit": {"kind": "java-main"}}
            with self.assertRaisesRegex(Refused, "JDK_REQUIRED"):
                manager.start({"project": "arithmetic", "model": "fictional-model", "goal": "Inspect Java"})
            self.assertEqual(manager.history(), [])


if __name__ == "__main__":
    unittest.main()
