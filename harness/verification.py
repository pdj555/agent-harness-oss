from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.isolation import command_env, stage_home

DEFAULT_TIMEOUT = 300


@dataclass
class Verification:
    passed: bool
    command: str
    exit_code: int
    output: str

    def as_dict(self) -> dict:
        return asdict(self)


def run_checks(
    stage_root: Path,
    *,
    python: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Verification:
    """Run the project's tests in the stage. The exit code is the only verdict.

    ``python`` is the repository's own interpreter when it has one; otherwise the
    harness interpreter. A timeout is a failed verification, never an exception,
    so a slow or hung suite cannot leave a run stuck in ``running``.
    """
    interpreter = python or sys.executable
    command = "python -m pytest -q"
    env = command_env(stage_home(stage_root), interpreter)
    try:
        proc = subprocess.run(
            [interpreter, "-m", "pytest", "-q"],
            cwd=stage_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = _text(exc.stdout) + _text(exc.stderr)
        return Verification(
            passed=False,
            command=command,
            exit_code=-1,
            output=(f"checks timed out after {timeout}s\n" + partial.strip())[-8000:],
        )
    except OSError as exc:
        return Verification(
            passed=False,
            command=command,
            exit_code=-1,
            output=f"checks could not start: {exc}",
        )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return Verification(
        passed=proc.returncode == 0,
        command=command,
        exit_code=proc.returncode,
        output=output[-8000:],
    )


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
