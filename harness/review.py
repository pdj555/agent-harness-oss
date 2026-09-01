from __future__ import annotations

from pathlib import Path

from harness.fs import iter_files
from harness.isolation import Stage
from harness.provider import Provider
from harness.verification import Verification

TEST_DIR_NAMES = {"tests", "test", "spec", "__tests__"}
TEST_NAME_MARKERS = ("_test.", ".test.", "_spec.", ".spec.")


def _is_test_path(rel: str) -> bool:
    """Recognize a test by convention, in whatever language the project uses."""
    path = Path(rel)
    if any(part in TEST_DIR_NAMES for part in path.parts):
        return True
    name = path.name.lower()
    if name.startswith("test_") or name.startswith("spec_"):
        return True
    return any(marker in name for marker in TEST_NAME_MARKERS)


def _test_files(root: Path) -> list[Path]:
    return [path for path in iter_files(root) if _is_test_path(str(path.relative_to(root)))]


def inspect_change(stage: Stage) -> list[str]:
    files = stage.changed_files()
    diff = (stage.diff() or "").strip()
    findings: list[str] = []
    if not _test_files(stage.root):
        findings.append("no test files remain in the isolated worktree")
    impl_changed = [name for name in files if not _is_test_path(name)]
    tests_changed = [name for name in files if _is_test_path(name)]
    if not files and not diff:
        findings.append("review found no isolated change")
    if tests_changed and not impl_changed:
        findings.append("tests changed without an implementation change")
    return findings


def run_review(stage: Stage, verification: Verification, provider: Provider) -> dict:
    """Software-gated review. Check results are context, not the verdict."""
    del provider
    files = stage.changed_files()
    findings = inspect_change(stage)
    passed = not findings
    if passed:
        summary = "Implementation changed. Tests remain. No blocking findings."
    else:
        summary = "Review blocked: " + "; ".join(findings)
    return {
        "role": "reviewer",
        "passed": passed,
        "summary": summary,
        "findings": findings,
        "files_reviewed": files,
        "checks_passed": bool(verification.passed),
    }
