from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.environment import display_python, stage_runtime

DEFAULT_COMMAND = ("python", "-m", "pytest", "-q")
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


def run_checks(
    stage_root: Path,
    *,
    project_root: Path | None = None,
    command: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Verification:
    """Run the project's checks in the isolated stage.

    This is the only source of `passed`. Every failure mode - a red suite, a
    hung suite, a suite that cannot start, a repository with no tests at all -
    returns evidence instead of raising, so a run always ends with a verdict a
    person can read.

    The checks run with the project's own interpreter when its tree carries a
    virtualenv, because a repository's tests need the repository's
    dependencies. The command defaults to pytest. An operator can name another
    one in `harness.toml`; a model cannot, and neither can the repository under
    work.
    """
    python, env = stage_runtime(stage_root, project_root)
    argv = _argv(command, python)
    label = " ".join(
        str(part) for part in (command or (display_python(python, project_root), *DEFAULT_COMMAND[1:]))
    )
    try:
        proc = subprocess.run(
            argv,
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
            label,
            TIMEOUT_EXIT,
            f"checks timed out after {timeout}s; no result was proven.\n{partial}",
        )
    except OSError as exc:
        return _result(label, UNRUNNABLE_EXIT, f"checks could not start: {exc}")

    output = (_text(proc.stdout) + _text(proc.stderr)).strip()
    if proc.returncode == NO_TESTS_EXIT and not command:
        output = (
            "pytest collected no tests in the isolated worktree, so nothing proves "
            "this change. Add a test that fails without it.\n" + output
        )
    return _result(label, proc.returncode, output)


def _argv(command: list[str] | None, python: Path) -> list[str]:
    if not command:
        return [str(python), "-m", "pytest", "-q"]
    argv = [str(part) for part in command]
    if argv[0] in {"python", "python3"}:
        argv[0] = str(python)
    return argv


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
