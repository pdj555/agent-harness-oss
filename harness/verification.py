from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Verification:
    passed: bool
    command: str
    exit_code: int
    output: str

    def as_dict(self) -> dict:
        return asdict(self)


def run_checks(stage_root: Path) -> Verification:
    command = "python -m pytest -q"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(stage_root / ".home"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    (stage_root / ".home").mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=stage_root,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return Verification(
        passed=proc.returncode == 0,
        command=command,
        exit_code=proc.returncode,
        output=output[-8000:],
    )
