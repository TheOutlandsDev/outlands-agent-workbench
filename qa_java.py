"""Offline Java sandbox acceptance with invented input; no inference or downloads."""

import json
import shutil
from pathlib import Path

from java_check import check


def acceptance(jdk, work):
    root = work / "java-checks"
    root.mkdir(mode=0o700)
    source = Path(__file__).resolve().parent / "examples/java_selection"
    shutil.copytree(source / "selection", root / "selection")
    spec = {"kind": "java-main", "sources": ["selection/SelectionOrder.java", "selection/SelectionOrderTest.java"], "main_class": "selection.SelectionOrderTest"}
    results = {}
    results["baseline"] = check(root, spec, 10, jdk)
    assert results["baseline"]["phase"] == "run" and results["baseline"]["exit_code"] != 0
    file = root / "selection/SelectionOrder.java"
    file.write_bytes(file.read_bytes().replace(b"new TreeSet<>(values)", b"new LinkedHashSet<>(values)"))
    results["fixed"] = check(root, spec, 10, jdk)
    assert results["fixed"]["exit_code"] == 0 and "6 protected assertions passed" in results["fixed"]["output"]
    file.write_text("this is not Java\n")
    results["compile_error"] = check(root, spec, 10, jdk)
    assert results["compile_error"]["phase"] == "compile" and results["compile_error"]["exit_code"] != 0 and not results["compile_error"]["infrastructure_error"]
    probe = root / "Boundary.java"
    probe.write_text('''import java.nio.file.*;
import java.net.*;
public class Boundary {
    public static void main(String[] args) throws Exception {
        for (String root : new String[]{"/home", "/srv", "/run", "/etc"})
            if (Files.exists(Path.of(root))) throw new AssertionError("root exposed");
        try { Files.writeString(Path.of("/work/forbidden"), "x"); throw new AssertionError("write allowed"); }
        catch (java.io.IOException expected) { }
        try (Socket socket = new Socket()) {
            try { socket.connect(new InetSocketAddress("127.0.0.1", 11434), 100); throw new AssertionError("host network exposed"); }
            catch (java.io.IOException expected) { }
        }
        System.out.println("namespace probes passed");
    }
}
''')
    probe_spec = {"kind": "java-main", "sources": ["Boundary.java"], "main_class": "Boundary"}
    results["boundary"] = check(root, probe_spec, 10, jdk)
    assert results["boundary"]["exit_code"] == 0 and not (root / "forbidden").exists()
    probe.write_text('public class Boundary { public static void main(String[] args) throws Exception { Thread.sleep(30000); } }\n')
    results["timeout"] = check(root, probe_spec, 3, jdk)
    assert results["timeout"]["timed_out"]
    probe.write_text('public class Boundary { public static void main(String[] args) { for(int i=0;i<100000;i++) System.out.print("x"); } }\n')
    results["output_limit"] = check(root, probe_spec, 10, jdk)
    assert results["output_limit"]["output_limited"]
    (work / "java-acceptance.json").write_text(json.dumps(results, indent=2) + "\n")
    return {"java_baseline_failed": True, "java_final_passed": True, "java_protected_assertions": 6,
            "java_compile_error_recorded": True, "java_boundary_passed": True,
            "java_timeout_enforced": True, "java_output_limit_enforced": True}
