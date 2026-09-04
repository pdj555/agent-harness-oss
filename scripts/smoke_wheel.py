from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

DEMO_FILES = {
    "harness/sample-repo/README.md",
    "harness/sample-repo/test_tracker.py",
    "harness/sample-repo/tracker.py",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_wheel.py path/to/package.whl", file=sys.stderr)
        return 2
    wheel = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="agent-harness-wheel-") as temp:
        root = Path(temp)
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            packaged_demo = {
                name for name in names if name.startswith("harness/sample-repo/")
            }
            if packaged_demo != DEMO_FILES:
                print("wheel demo fixture does not match the allowlist", file=sys.stderr)
                return 1
            for name in names:
                destination = (root / name).resolve()
                if not destination.is_relative_to(root):
                    print(f"wheel contains an unsafe path: {name}", file=sys.stderr)
                    return 1
            archive.extractall(root)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "HARNESS_PROVIDER": "deterministic",
        }
        proc = subprocess.run(
            [sys.executable, "-m", "harness", "demo"],
            cwd=root,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if output:
        print(output)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
