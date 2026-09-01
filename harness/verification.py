from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 300
TIMEOUT_EXIT = 124
UNRUNNABLE_EXIT = 127
NO_TESTS_EXIT = 5
OUTPUT_LIMIT = 8000


@dataclass
class Verification:
    passed: bool
    command: str
    exit_code: int
    output: str

    def as_dict(self) -> dict:
        return asdict(self)


def run_checks(stage_root: Path, *, timeout: int = DEFAULT_TIMEOUT) -> Verification:
    """Run the project's tests in the isolated stage.

    This is the only source of `passed`. Every failure mode - a red suite, a
    hung suite, a suite that cannot start, a repository with no tests at all -
    returns evidence instead of raising, so a run always ends with a verdict a
    person can read.
    """
    command = "python -m pytest -q"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(stage_root / ".home"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    (stage_root / ".home").mkdir(exist_ok=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=stage_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = _text(exc.stdout) + _text(exc.stderr)
        return _result(
            command,
            TIMEOUT_EXIT,
            f"checks timed out after {timeout}s; no result was proven.\n{partial}",
        )
    except OSError as exc:
        return _result(command, UNRUNNABLE_EXIT, f"checks could not start: {exc}")

    output = (_text(proc.stdout) + _text(proc.stderr)).strip()
    if proc.returncode == NO_TESTS_EXIT:
        output = (
            "pytest collected no tests in the isolated worktree, so nothing proves "
            "this change. Add a test that fails without it.\n" + output
        )
    return _result(command, proc.returncode, output)


def _result(command: str, exit_code: int, output: str) -> Verification:
    return Verification(
        passed=exit_code == 0,
        command=command,
        exit_code=exit_code,
        output=output.strip()[-OUTPUT_LIMIT:],
    )


def _text(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream
