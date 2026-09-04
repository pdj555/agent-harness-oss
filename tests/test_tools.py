from __future__ import annotations

from pathlib import Path

import pytest
from harness.authority import PathDenied, PermissionDenied
from harness.isolation import create_stage
from harness.tools import ToolError, execute, software_helper
from tests.helpers import copy_sample, git_init


def _ctx(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-tools")
    return stage


def _symlink_or_skip(link: Path, target: Path | str) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")


def test_list_search_read_edit_and_shell_under_authority(tmp_path: Path):
    stage = _ctx(tmp_path)
    listed = execute("list_files", {"pattern": "*.py"}, stage=stage, role="principal")
    assert "tracker.py" in listed
    found = execute("search", {"query": "classify_priority"}, stage=stage, role="principal")
    assert "tracker.py" in found
    text = execute("read_file", {"path": "tracker.py"}, stage=stage, role="principal")
    assert "classify_priority" in text
    execute(
        "edit_file",
        {"path": "tracker.py", "old": 'return "low"', "new": 'return "high"'},
        stage=stage,
        role="principal",
    )
    edited = (stage.root / "tracker.py").read_text(encoding="utf-8")
    assert 'return "high"' in edited
    shell = execute("run_shell", {"command": "python3 -m pytest -q"}, stage=stage, role="principal")
    assert "test" in shell.lower() or "fail" in shell.lower() or "pass" in shell.lower()
    status = execute("git_status", {}, stage=stage, role="principal")
    diff = execute("git_diff", {}, stage=stage, role="principal")
    assert "tracker.py" in status or "tracker.py" in diff


def test_tools_reject_path_outside_stage(tmp_path: Path):
    stage = _ctx(tmp_path)
    try:
        execute("read_file", {"path": "/etc/passwd"}, stage=stage, role="principal")
    except (PathDenied, ToolError) as exc:
        assert "deny" in str(exc).lower() or "path" in str(exc).lower() or "outside" in str(exc).lower()
    else:
        raise AssertionError("read of /etc/passwd must be denied")


def test_tools_fail_closed_after_shell_creates_escaping_symlink(tmp_path: Path):
    stage = _ctx(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside target\n", encoding="utf-8")
    probe = tmp_path / "symlink-probe"
    _symlink_or_skip(probe, outside)
    probe.unlink()
    command = (
        "python3 -c \"from pathlib import Path; target = Path('tracker.py'); "
        f"target.unlink(); target.symlink_to({str(outside)!r})\""
    )

    with pytest.raises(ToolError, match="symlink escapes"):
        execute("run_shell", {"command": command}, stage=stage, role="principal")
    with pytest.raises(ToolError, match="symlink escapes"):
        execute("read_file", {"path": "tracker.py"}, stage=stage, role="principal")


def test_delegate_inspects_without_user_management(tmp_path: Path):
    stage = _ctx(tmp_path)
    result = execute(
        "delegate",
        {"objective": "Find the priority classifier."},
        stage=stage,
        role="principal",
        helper=lambda objective: software_helper(objective, stage),
    )
    assert "tracker.py" in result


def test_reviewer_cannot_edit(tmp_path: Path):
    stage = _ctx(tmp_path)
    try:
        execute(
            "edit_file",
            {"path": "tracker.py", "old": "low", "new": "high"},
            stage=stage,
            role="reviewer",
        )
    except (ToolError, PermissionDenied) as exc:
        assert "reviewer" in str(exc).lower() or "permission" in str(exc).lower()
    else:
        raise AssertionError("reviewer must not edit")


def test_shell_python_resolves_to_the_repository_interpreter(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    (source / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    git_init(source)
    fake = source / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\necho \"project-venv $*\"\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    stage = create_stage(source, tmp_path / "stages", "run-shell-venv")
    output = execute("run_shell", {"command": "python -m pytest -q"}, stage=stage, role="principal")
    assert output.splitlines()[0] == "exit 0"
    assert "project-venv -m pytest -q" in output
    assert stage.changed_files() == []


def test_shell_timeout_is_reported_not_raised_through(tmp_path: Path):
    stage = _ctx(tmp_path)
    try:
        execute("run_shell", {"command": "sleep 5"}, stage=stage, role="principal", timeout=1)
    except ToolError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("a hung command must surface as a tool error")


def test_search_skips_binary_and_oversized_files(tmp_path: Path):
    from harness.tools import MAX_SEARCH_BYTES

    stage = _ctx(tmp_path)
    (stage.root / "blob.bin").write_bytes(b"needle\0binary")
    (stage.root / "huge.txt").write_text("needle\n" + "x" * MAX_SEARCH_BYTES, encoding="utf-8")
    (stage.root / "small.txt").write_text("needle here\n", encoding="utf-8")
    found = execute("search", {"query": "needle"}, stage=stage, role="principal")
    assert "small.txt:1" in found
    assert "blob.bin" not in found
    assert "huge.txt" not in found
