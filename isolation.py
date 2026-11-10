"""Linux-only execution of a named unittest check in a networkless namespace."""

import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path


def check(work, pattern, seconds):
    argv = [
        "/usr/bin/bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for directory in ["/lib", "/lib64"]:
        if Path(directory).exists():
            argv += ["--ro-bind", directory, directory]
    argv += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        str(work),
        "/work",
        "--chdir",
        "/work",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "/usr/bin/python3",
        "-I",
        "-B",
        "-m",
        "unittest",
        "discover",
        "-s",
        "/work",
        "-p",
        pattern,
        "-v",
    ]
    argv = [
        "/usr/bin/prlimit",
        "--core=0",
        "--fsize=65536",
        "--as=1073741824",
        "--",
    ] + argv
    with tempfile.TemporaryFile() as stream:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True,
        )
        timed_out = False
        try:
            child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Kill any remaining namespace children even after the parent exits.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        stream.seek(0)
        raw = stream.read(65537)
    output = raw[:65536].decode("utf-8", "replace")
    count = re.search(r"\bRan ([0-9]+) tests? in ", output)
    tests_ran = int(count.group(1)) if count else 0
    infrastructure = output.startswith("bwrap:") or tests_ran == 0
    return {
        "exit_code": child.returncode,
        "timed_out": timed_out,
        "output_limited": len(raw) >= 65536,
        "infrastructure_error": infrastructure,
        "output": output,
        "tests_ran": tests_ran,
    }
