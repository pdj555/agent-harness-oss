from __future__ import annotations

from pathlib import Path

from harness.authority import PathDenied, PermissionDenied
from harness.isolation import create_stage
from harness.tools import ToolError, execute, software_helper
from tests.helpers import copy_sample, git_init


def _ctx(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-tools")
    return stage


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


def test_listing_and_search_ignore_dependency_and_cache_trees(tmp_path: Path):
    stage = _ctx(tmp_path)
    vendored = stage.root / "node_modules" / "left-pad" / "index.js"
    vendored.parent.mkdir(parents=True)
    vendored.write_text("classify_priority = 'vendored noise'\n", encoding="utf-8")
    cached = stage.root / "__pycache__" / "tracker.cpython-313.pyc"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"\x00\x01binary classify_priority")
    environment = stage.root / ".venv" / "lib" / "site.py"
    environment.parent.mkdir(parents=True)
    environment.write_text("classify_priority = 'installed dependency'\n", encoding="utf-8")

    listed = execute("list_files", {"pattern": "*"}, stage=stage, role="principal")
    found = execute("search", {"query": "classify_priority"}, stage=stage, role="principal")

    assert "tracker.py" in listed
    assert "node_modules" not in listed
    assert "__pycache__" not in listed
    assert ".venv" not in listed
    assert "node_modules" not in found
    assert ".venv" not in found
    assert "tracker.py" in found


def test_search_says_when_it_stopped_early(tmp_path: Path):
    stage = _ctx(tmp_path)
    (stage.root / "many.py").write_text("needle = 1\n" * 200, encoding="utf-8")

    found = execute("search", {"query": "needle"}, stage=stage, role="principal")

    lines = found.splitlines()
    assert len(lines) <= 51
    assert "narrow the query" in lines[-1]


def test_write_file_creates_a_file_inside_the_stage(tmp_path: Path):
    stage = _ctx(tmp_path)
    result = execute(
        "write_file",
        {"path": "pkg/test_new.py", "content": "def test_new():\n    assert True\n"},
        stage=stage,
        role="principal",
    )
    assert "pkg/test_new.py" in result
    assert (stage.root / "pkg" / "test_new.py").read_text(encoding="utf-8").startswith("def test_new")
    assert "pkg/test_new.py" in stage.changed_files()


def test_write_file_cannot_escape_the_stage(tmp_path: Path):
    stage = _ctx(tmp_path)
    outside = tmp_path / "outside.txt"
    for target in ("../outside.txt", str(outside)):
        try:
            execute("write_file", {"path": target, "content": "no"}, stage=stage, role="principal")
        except (PathDenied, ToolError):
            pass
        else:
            raise AssertionError(f"write outside the stage must be denied: {target}")
    assert not outside.exists()


def test_reviewer_cannot_write_and_stop_blocks_writing(tmp_path: Path):
    stage = _ctx(tmp_path)
    for role, stopped, expected in (("reviewer", False, PermissionDenied), ("principal", True, ToolError)):
        try:
            execute(
                "write_file",
                {"path": "sneaky.py", "content": "x = 1\n"},
                stage=stage,
                role=role,
                stopped=stopped,
            )
        except expected:
            pass
        else:
            raise AssertionError(f"{role} stopped={stopped} must not write")
    assert not (stage.root / "sneaky.py").exists()


def test_read_file_returns_a_labelled_window_of_a_long_file(tmp_path: Path):
    stage = _ctx(tmp_path)
    (stage.root / "long.py").write_text(
        "".join(f"line{number}\n" for number in range(1, 2001)), encoding="utf-8"
    )

    whole = execute("read_file", {"path": "long.py"}, stage=stage, role="principal")
    window = execute(
        "read_file", {"path": "long.py", "offset": 900, "limit": 3}, stage=stage, role="principal"
    )

    assert "of 2000" in whole.splitlines()[0]
    assert whole.splitlines()[1] == "line1"
    assert window.splitlines()[1:] == ["line900", "line901", "line902"]
    assert "lines 900-902 of 2000" in window.splitlines()[0]


def test_edit_file_errors_say_how_to_recover(tmp_path: Path):
    stage = _ctx(tmp_path)
    try:
        execute(
            "edit_file",
            {"path": "tracker.py", "old": "not in this file", "new": "x"},
            stage=stage,
            role="principal",
        )
    except ToolError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("a missing anchor must fail")

    try:
        execute(
            "edit_file",
            {"path": "tracker.py", "old": "return", "new": "x"},
            stage=stage,
            role="principal",
        )
    except ToolError as exc:
        assert "times" in str(exc) and "unique" in str(exc)
    else:
        raise AssertionError("an ambiguous anchor must fail")


def test_the_shell_timeout_is_configurable(tmp_path: Path):
    stage = _ctx(tmp_path)
    try:
        execute(
            "run_shell",
            {"command": "python3 -c 'import time; time.sleep(30)'"},
            stage=stage,
            role="principal",
            shell_timeout=1,
        )
    except ToolError as exc:
        assert "timed out after 1s" in str(exc)
    else:
        raise AssertionError("a hung command must be reported, not awaited")


def test_search_can_be_scoped_to_a_file_pattern(tmp_path: Path):
    stage = _ctx(tmp_path)
    (stage.root / "notes.md").write_text("classify_priority is documented here\n", encoding="utf-8")

    everywhere = execute("search", {"query": "classify_priority"}, stage=stage, role="principal")
    scoped = execute(
        "search", {"query": "classify_priority", "pattern": "*.md"}, stage=stage, role="principal"
    )

    assert "notes.md" in everywhere and "tracker.py" in everywhere
    assert "notes.md" in scoped
    assert "tracker.py" not in scoped


def test_a_blank_pattern_lists_everything_instead_of_nothing(tmp_path: Path):
    stage = _ctx(tmp_path)
    for blank in ("", "   ", None):
        listed = execute("list_files", {"pattern": blank}, stage=stage, role="principal")
        assert "tracker.py" in listed
    scoped = execute(
        "search", {"query": "classify_priority", "pattern": "  "}, stage=stage, role="principal"
    )
    assert "tracker.py" in scoped


def test_git_diff_reports_a_written_file_back_to_the_agent(tmp_path: Path):
    stage = _ctx(tmp_path)
    execute(
        "write_file",
        {"path": "helpers.py", "content": "def helper():\n    return 42\n"},
        stage=stage,
        role="principal",
    )

    diff = execute("git_diff", {}, stage=stage, role="principal")
    status = execute("git_status", {}, stage=stage, role="principal")

    assert "helpers.py" in diff
    assert "return 42" in diff
    assert "helpers.py" in status
