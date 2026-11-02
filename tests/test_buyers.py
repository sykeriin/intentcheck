from collections import Counter

import pytest

from dia.arena.catalogue import build_catalogue
from dia.arena.scenario import generate
from dia.buyers.scripted import CautiousBuyer, NaiveBuyer, OracleBuyer
from dia.eval.judge import judge_result


@pytest.fixture(scope="module")
def world():
    cat = build_catalogue(7)
    return cat, generate(cat, n=400, seed=11)


def run_all(buyer, scs):
    out = []
    for i, sc in enumerate(scs):
        res = buyer.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session(buyer.name, i))
        out.append((sc, res, judge_result(sc, res)))
    return out


def rate(rows, pred=lambda sc: True):
    rows = [r for r in rows if pred(r[0])]
    return sum(j.violation for _, _, j in rows) / len(rows)


def test_oracle_has_zero_violations(world):
    _, scs = world
    rows = run_all(OracleBuyer(), scs)
    assert rate(rows) == 0.0
    # and abstains exactly when nothing acceptable exists
    assert all((res.cart is None) == sc.abstain_case for sc, res, _ in rows)


def test_naive_much_worse_than_cautious(world):
    _, scs = world
    naive, cautious = rate(run_all(NaiveBuyer(), scs)), rate(run_all(CautiousBuyer(), scs))
    print(f"naive={naive:.2%} cautious={cautious:.2%}")
    assert naive > 0.25
    assert naive > cautious + 0.15


def test_naive_fooled_by_each_attack_class(world):
    _, scs = world
    rows = run_all(NaiveBuyer(), scs)
    for p in ["dark_pattern", "injection", "bait_and_switch", "colluding"]:
        r = rate(rows, lambda sc: sc.spotlight == p)
        print(p, f"{r:.2%}")
        assert r > 0.3, p


def test_cautious_residual_is_only_omission(world):
    """With constraints visible, the cautious buyer has no hard violations and no abstain violations; every
    remaining violation is a dominated choice where a FLAKY seller (dropped on timeout) is a dominator."""
    _, scs = world
    rows = run_all(CautiousBuyer(), scs)
    seen = [(sc, j) for sc, _, j in rows if sc.buyer_sees_constraints]
    bad = [(sc, j) for sc, j in seen if j.violation]
    assert not [sc.sid for sc, j in seen if j.hard_violation]
    assert not [sc.sid for sc, j in seen if j.should_abstain and j.bought]
    assert all(j.dominated for _, j in bad)
    not_omission = [sc.sid for sc, j in bad
                    if not any(sc.market.cat.sellers[d.seller_id].profile == "flaky" for d in j.dominators)]
    print(f"cautious residual (constraints seen): {len(bad)}/{len(seen)} violations; "
          f"non-omission: {not_omission}")
    assert not not_omission


def test_underspecified_intents_hurt_cautious(world):
    """RQ4 sanity: without constraints, even a careful buyer breaks hard constraints it never saw."""
    _, scs = world
    rows = run_all(CautiousBuyer(), scs)
    seen = rate(rows, lambda sc: sc.specificity == "precise")
    unseen = rate(rows, lambda sc: sc.specificity != "precise")
    print(f"precise={seen:.2%} loose/underspecified={unseen:.2%}")
    assert unseen > seen
