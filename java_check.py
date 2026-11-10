"""Fixed Linux Java compile/main check; no shell, downloads or annotation processors."""

import json
import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path

JVM = ["-Xmx128m", "-XX:ActiveProcessorCount=2", "-XX:CompressedClassSpaceSize=32m",
       "-XX:ReservedCodeCacheSize=32m", "-XX:+UseSerialGC"]


def validate_jdk(home):
    if not isinstance(home, Path) or not home.is_absolute():
        raise ValueError("absolute JDK directory required")
    home = home.resolve(strict=True)
    if not all((home / "bin" / n).is_file() and os.access(home / "bin" / n, os.X_OK)
               for n in ["java", "javac"]):
        raise ValueError("JDK tools required")
    return home


def check(work, spec, seconds, jdk_home):
    home = validate_jdk(jdk_home)
    # The engine validates source names and the protected main before this call.
    if (not isinstance(spec, dict) or set(spec) != {"kind", "sources", "main_class"}
            or spec["kind"] != "java-main"
            or not isinstance(spec["sources"], list) or not 1 <= len(spec["sources"]) <= 32
            or any(not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_/-]+[.]java", s)
                   or any(p in ["", ".", ".."] for p in s.split("/")) for s in spec["sources"])
            or not isinstance(spec["main_class"], str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:[.][A-Za-z_][A-Za-z0-9_]*)*", spec["main_class"])):
        raise ValueError("invalid Java check")
    with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryFile() as output:
        config = Path(directory) / "check.json"
        config.write_text(json.dumps(spec))
        argv = ["/usr/bin/prlimit", "--core=0", "--fsize=65536", "--as=2147483648", "--",
                "/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
                "--cap-drop", "ALL", "--clearenv", "--ro-bind", "/usr", "/usr"]
        for lib in ["/lib", "/lib64"]:
            if Path(lib).exists():
                argv += ["--ro-bind", lib, lib]
        argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--ro-bind", str(work), "/work", "--ro-bind", str(home), "/jdk",
                 "--ro-bind", str(Path(__file__).resolve()), "/runner.py",
                 "--ro-bind", str(config), "/check.json", "--chdir", "/work",
                 "--setenv", "HOME", "/tmp", "--setenv", "LANG", "C.UTF-8",
                 "/usr/bin/python3", "-I", "-B", "/runner.py"]
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, env={"PATH": "/usr/bin:/bin"},
                                 start_new_session=True)
        timed_out = False
        try:
            child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        output.seek(0)
        raw = output.read(65537)
    text = raw[:65536].decode("utf-8", "replace")
    # A count denotes execution of one protected main program, not its assertions.
    matches = re.findall(r"^OUTLANDS_JAVA_RESULT (compile|run) (-?[0-9]+)$", text, re.M)
    completed = matches[-1] if matches else None
    return {"exit_code": child.returncode, "timed_out": timed_out,
            "output_limited": len(raw) >= 65536,
            "infrastructure_error": completed is None and not timed_out and len(raw) < 65536,
            "output": text, "tests_ran": int(completed is not None and completed[0] == "run"),
            "kind": "java-main", "phase": completed[0] if completed else "incomplete"}


def inside():
    spec = json.loads(Path("/check.json").read_text())
    Path("/tmp/classes").mkdir()
    compile_args = ["/jdk/bin/javac"] + ["-J" + flag for flag in JVM] + [
        "-proc:none", "--release", "17", "-encoding", "UTF-8", "-d", "/tmp/classes",
        "-classpath", "/tmp/classes", "-sourcepath", "/work"]
    outcome = subprocess.run(compile_args + ["/work/" + n for n in spec["sources"]],
                             stdin=subprocess.DEVNULL, check=False)
    phase = "compile"
    if outcome.returncode == 0:
        phase = "run"
        outcome = subprocess.run(["/jdk/bin/java"] + JVM + ["-Djava.io.tmpdir=/tmp",
                                 "-cp", "/tmp/classes", spec["main_class"]],
                                 stdin=subprocess.DEVNULL, check=False)
    print("OUTLANDS_JAVA_RESULT", phase, outcome.returncode, flush=True)
    return outcome.returncode


if __name__ == "__main__":
    raise SystemExit(inside())
