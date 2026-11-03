"""Offline rehearsal of the whole confirmatory pipeline, so the first real-model run is not also the first time
run -> rows -> `dia confirm` has been wired together.

The stand-in policy is recorded, then replayed under a NON-dry buyer name (llm:replay:...), which is what makes
`confirm` treat it as an LLM buyer. The numbers mean nothing; only that every stage connects."""

import pytest

from dia.cli import main
from dia.eval import confirm, run as runner

SP = {k: v for k, v in runner.SPLITS["llm-test"].items() if k not in ("n", "seed")}


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    d = tmp_path_factory.mktemp("rehearsal")
    first = runner.run(["llm:dry"], ["full"], n=80, seed=2026, transcripts=str(d), **SP)
    return d, first


def test_replay_reproduces_the_recorded_run_exactly(recorded):
    d, first = recorded
    rdir = d / "llm_dry"
    assert len(list(rdir.glob("*.json"))) == 80
    again = runner.run([f"llm:replay:{rdir}"], ["full", "limit_only"], n=80, seed=2026, **SP)
    key = lambda r: (r["sid"], r["bought"], r["violation"], r["hard_violation"], r.get("total"), r["status"])
    assert [key(r) for r in first] == [key(r) for r in again]
    assert {r["buyer"] for r in again} == {f"llm:replay:{rdir}"}


def test_rows_flow_into_the_confirmatory_analysis(recorded, tmp_path):
    d, _ = recorded
    out = tmp_path / "rows.jsonl"
    name = f"llm:replay:{d / 'llm_dry'}"
    rows = runner.run([name], ["full", "limit_only"], n=80, seed=2026, out=out, **SP)
    res = confirm.evaluate(rows, resamples=300)
    assert res["buyers"] == [name]
    for c in ("C1", "C2", "C3", "C4", "C5"):
        assert "verdict" in res[c], c
    text = confirm.render(res)
    assert all(f"## {c}" in text for c in ("C1", "C2", "C3", "C4", "C5"))
    # the dry stand-in ignores every constraint, so it must make errors the verifier can see
    assert res["C3"]["catch"][3] > 0


def test_confirm_cli_reads_the_jsonl(recorded, tmp_path, capsys):
    d, _ = recorded
    out = tmp_path / "rows.jsonl"
    runner.run([f"llm:replay:{d / 'llm_dry'}"], ["full"], n=80, seed=2026, out=out, **SP)
    main(["confirm", str(out), "--resamples", "200"])
    printed = capsys.readouterr().out
    assert "Confirmatory results" in printed and "C5" in printed


def test_dry_buyer_alone_is_not_confirmatory(recorded, tmp_path, capsys):
    _, first = recorded
    assert confirm.evaluate(first)["buyers"] == []
