from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "sample-repo"


def copy_sample(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("tracker.py", "test_tracker.py", "README.md"):
        shutil.copy(FIXTURE / name, dest / name)
    return dest


def git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=dev@example.com",
            "-c",
            "user.name=Developer",
            "commit",
            "-m",
            "initial",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
