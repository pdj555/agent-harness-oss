"""The sweep's arithmetic and its spending cap, with no model called."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "reviewer_sweep", Path(__file__).resolve().parent.parent / "scripts" / "reviewer_sweep.py"
)
sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep)


def test_cost_bills_cache_writes_and_reads_at_their_rates():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
    }
    # Sonnet 5.5: $2 in, $10 out, writes 1.25x in, reads 0.1x in.
    assert sweep.cost(usage, "claude-sonnet-5-5") == pytest.approx(2 + 10 + 2.5 + 0.2)


def test_sets_hold_the_published_cases_and_every_spec_attack():
    assert len(sweep.SETS["main"]) == 33
    assert len(sweep.SETS["spec-attacks"]) == 8
    assert all(case.label != "clean" for case in sweep.SETS["spec-attacks"])
    labels = [case.label == "clean" for case in sweep.SETS["same-shape"]]
    assert sum(not clean for clean in labels) == 8 and sum(labels) == 14
    paired = [case.label == "clean" for case in sweep.SETS["paired"]]
    assert sum(paired) == 24 and len(paired) == 48


def test_budget_refuses_reviews_once_the_cap_is_spent():
    calls = []

    def expensive(case, stage, verification, objective):
        calls.append(case)
        return {"ship": False, "findings": ["no"], "usage": {"output_tokens": 1_000_000}}

    budget = sweep.Budget(max_usd=1.0)
    guarded = budget.wrap(expensive, "claude-haiku-5-5")  # $0.50 per call
    verdicts = [guarded(n, None, None, "") for n in range(4)]
    assert len(calls) == 2
    assert budget.spent == pytest.approx(1.0)
    assert [v.get("error", False) for v in verdicts] == [False, False, True, True]


def test_estimate_needs_no_key_and_prices_every_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = sweep.estimate(["claude-haiku-5-5", "claude-opus-5-5"], ["spec-attacks"], trials=1)
    haiku, opus = report["rows"]
    assert haiku["reviews"] == opus["reviews"] == 8
    assert haiku["input_tokens"] == opus["input_tokens"] > 0
    assert opus["usd"] > haiku["usd"] > 0


def test_run_refuses_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert sweep.main(["--run"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


def test_unknown_model_is_refused():
    with pytest.raises(SystemExit):
        sweep.main(["--models", "gpt-nothing"])


def test_run_writes_the_summary_the_log_rebuild_reads(monkeypatch, tmp_path):
    """The paid path end to end, with a fake reviewer: no key is used and nothing is billed."""
    import json

    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    answers = iter(
        [{"ship": False, "findings": ["reviewer failed: Anthropic response did not complete: refusal"]}]
        + [{"ship": False, "findings": ["hard-coded threshold"]}] * 7
    )

    def fake(name, model, *, effort=None):
        def monitor(case, stage, verification, objective):
            verdict = next(answers)
            return {**verdict, "error": verdict["findings"][0].startswith("reviewer failed"),
                    "usage": {"output_tokens": 1000}}

        return monitor

    monkeypatch.setattr(sweep, "model_monitor", fake)
    out = tmp_path / "sweep"
    code = sweep.main(["--run", "--models", "claude-haiku-5-5", "--sets", "spec-attacks", "--trials", "1",
                       "--jobs", "1", "--out", str(out)])
    assert code == 1  # a reviewer error makes the run exit nonzero
    record = json.loads((out / "sweep.json").read_text())
    row = record["rows"][0]
    assert row["judged_trials"] == 7 and row["reviewer_errors_by_cause"] == {"refusal": 1}
    assert row["usd"] == pytest.approx(8 * 1000 * 0.50 / 1_000_000)
    table = (out / "sweep.md").read_text()
    assert table == sweep.render_sweep(record)
    expected = "| claude-haiku-5-5 | spec-attacks | 100% (59% to 100%) | n/a | 7 | 1 (1 refusal) | $0.00 |"
    assert expected in table


def test_build_parser_defaults_are_the_published_settings():
    args = sweep.build_parser().parse_args([])
    assert (args.effort, args.seed, args.trials, args.max_usd) == ("medium", 0, 3, 40.0)
