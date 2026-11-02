import json

from dia.cli import main
from dia.eval import metrics, report, run as runner


def test_run_is_deterministic_and_complete(tmp_path):
    a = runner.run(["oracle", "naive"], ["full", "limit_only"], n=40, seed=3, out=tmp_path / "a.jsonl")
    b = runner.run(["oracle", "naive"], ["full", "limit_only"], n=40, seed=3)
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("verdicts",)} |
                          {"d": {c: x["decision"] for c, x in r.get("verdicts", {}).items()}} for r in rows]
    assert strip(a) == strip(b)
    assert len(a) == 80
    loaded = runner.load(tmp_path / "a.jsonl")
    assert len(loaded) == 80 and loaded[0]["sid"] == a[0]["sid"]


def test_regret_excludes_hard_violations_and_is_nonnegative():
    rows = runner.run(["oracle", "naive", "cautious"], ["full"], n=120, seed=4)
    for b in ("oracle", "naive", "cautious"):
        r, lo, hi, n = metrics.regret(metrics.select(rows, buyer=b))
        assert n > 0 and r >= -1e-9, (b, r)


def test_bootstrap_ci_brackets_rate():
    r, lo, hi, n = metrics.rate_ci([True] * 30 + [False] * 70)
    assert n == 100 and abs(r - 0.3) < 1e-9 and lo < r < hi and hi - lo < 0.25
    assert metrics.rate_ci([])[3] == 0


def test_report_renders_all_sections():
    rows = runner.run(["oracle", "naive"], ["full", "hard_only", "limit_only"], n=60, seed=5)
    md = report.render(rows)
    for needle in ("Buyer decision integrity", "by seller profile", "specificity", "IntentCheck on `naive`",
                   "spend limit"):
        assert needle in md


def test_demo_cli_runs(capsys):
    main(["demo", "--profile", "dark_pattern", "--buyer", "naive"])
    out = capsys.readouterr().out
    assert "INTENT" in out and "VERDICT" in out and "valid" in out


def test_demo_shows_facilitator_would_have_settled_a_violation(capsys):
    main(["demo", "--profile", "bait_and_switch", "--buyer", "naive"])
    out = capsys.readouterr().out
    assert "BLOCK" in out or "STEP_UP" in out
    assert "WITHOUT INTENTCHECK" in out and "SETTLED" in out
