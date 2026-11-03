import json

import pytest

from dia.ap2.models import IntentConstraints
from dia.arena.catalogue import build_catalogue
from dia.arena.india import annotate
from dia.arena.scenario import generate
from dia.arena.solver import hard_violations, make_features
from dia.buyers.llm import ToolEnv
from dia.buyers.providers import ToolCall
from dia.buyers.scripted import CautiousBuyer, NaiveBuyer
from dia.cli import main
from dia.eval import run as runner
from dia.eval.judge import judge_result
from dia.intentcheck.verifier import IntentCheck


@pytest.fixture(scope="module")
def base():
    return build_catalogue(7)


@pytest.fixture(scope="module")
def ind():
    return annotate(build_catalogue(7))


def test_annotate_leaves_every_base_term_untouched(base, ind):
    assert ind.india and not base.india
    for oid, o in base.offers.items():
        a, b = o.quoted, ind.offers[oid].quoted
        assert (a.sku, a.price, a.fees, a.shipping, a.delivery_days, a.returnable) == \
               (b.sku, b.price, b.fees, b.shipping, b.delivery_days, b.returnable)
        if o.checkout:
            a, b = o.checkout, ind.offers[oid].checkout
            assert (a.sku, a.price, a.fees, a.shipping, a.delivery_days) == \
                   (b.sku, b.price, b.fees, b.shipping, b.delivery_days)


def test_seller_mutations(ind):
    bait = dark = 0
    for o in ind.offers.values():
        prof = ind.sellers[o.seller_id].profile
        if prof == "bait_and_switch" and o.quoted.cod:
            assert o.checkout is not None and not o.checkout.cod      # COD advertised, prepaid-only at checkout
            bait += 1
        if prof == "dark_pattern" and o.quoted.window_days > 0:
            assert o.checkout.window_days < o.quoted.window_days       # return window quietly shortened
            dark += 1
        if prof in ("honest", "injection", "colluding", "flaky"):
            assert o.effective.cod == o.quoted.cod and o.effective.window_days == o.quoted.window_days
    assert bait > 50 and dark > 50


def test_window_and_returnable_stay_consistent(ind):
    for o in ind.offers.values():
        for t in (o.quoted, o.effective):
            assert (t.window_days > 0) == t.returnable, o.offer_id


def test_hard_violations_for_cod_and_return_window():
    c = IntentConstraints(category="x", budget_total=1000, deadline_days=3, cod_required=True,
                          min_return_window_days=15)
    bad = make_features("o", "s", "k", 100, 1, 4.0, 0.5, True, {}, cod=False, window=7)
    v = hard_violations(bad, c)
    assert len(v) == 2 and any("cash on delivery" in x for x in v) and any("return window" in x for x in v)
    assert hard_violations(make_features("o", "s", "k", 100, 1, 4.0, 0.5, True, {}, cod=True, window=30), c) == []
    # constraints at their defaults never look at the India fields
    plain = IntentConstraints(category="x", budget_total=1000, deadline_days=3)
    assert hard_violations(make_features("o", "s", "k", 100, 1, 4.0, 0.5, True, {}, cod=False, window=0), plain) == []


def test_india_scenarios_share_the_base_markets_and_stay_feasible(base, ind):
    a, b = generate(base, n=150, seed=5), generate(ind, n=150, seed=5, india=True)
    assert [(s.sid, s.spotlight, s.specificity, s.abstain_case, tuple(s.market.offer_ids)) for s in a] == \
           [(s.sid, s.spotlight, s.specificity, s.abstain_case, tuple(s.market.offer_ids)) for s in b]
    # Budgets match except where the India mutation really changes ground truth: a dark-pattern seller's signed cart
    # can lose its return window (hence become non-returnable), so a scenario that requires refundability needs
    # a larger budget to stay feasible. Anything else differing would be a leak.
    for x, y in zip(a, b):
        if x.constraints.budget_total != y.constraints.budget_total:
            assert x.spotlight == "dark_pattern" and x.constraints.requires_refundability, x.sid
    assert all(s.gt.hard for s in b if not s.abstain_case)
    assert all(not s.gt.hard for s in b if s.abstain_case)
    assert any(s.constraints.cod_required for s in b) and any(s.constraints.min_return_window_days for s in b)
    for s in b:
        if s.specificity == "precise" and s.constraints.cod_required:
            assert "cash on delivery" in s.mandate.natural_language_description
        if s.constraints.min_return_window_days and s.specificity == "precise":
            assert "return window" in s.mandate.natural_language_description


def test_india_effect_on_buyers_and_verifier(ind):
    scs = generate(ind, n=300, seed=1, india=True)
    ic = IntentCheck(scs[0].market.keyring.directory)
    naive_india_viol = caught = 0
    for i, sc in enumerate(scs):
        for B in (NaiveBuyer(), CautiousBuyer()):
            res = B.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session(B.name, i))
            if res.cart is None:
                continue
            j = judge_result(sc, res)
            india_reason = any("cash on delivery" in r or "return window" in r for r in j.reasons)
            if B.name == "cautious" and sc.buyer_sees_constraints:
                assert not india_reason, (sc.sid, j.reasons)     # it previews carts and re-derives COD / window
            if B.name == "naive" and india_reason:
                naive_india_viol += 1
                caught += ic.check(sc.mandate, res.cart, res, sc.market.session("ic", 10_000 + i)).decision == "block"
    assert naive_india_viol > 5
    assert caught == naive_india_viol                            # hard constraints => block


def test_llm_tools_expose_india_fields_only_in_india_mode(base, ind):
    for cat, expect in ((base, False), (ind, True)):
        sc = generate(cat, n=3, seed=2, india=expect)[0]
        env = ToolEnv(sc.market.session("t", 0), 10_000)
        r = json.loads(env.execute(ToolCall("c", "search", {})))["results"][0]
        assert ("cod" in r and "return_window_days" in r) is expect
        q = json.loads(env.execute(ToolCall("c", "get_quote", {"offer_id": r["offer_id"]})))
        assert ("cod" in q) is expect
        pv = json.loads(env.execute(ToolCall("c", "checkout_preview", {"offer_id": r["offer_id"]})))
        assert ("cod" in pv) is expect


def test_india_split_runs_end_to_end_and_via_cli(tmp_path):
    assert runner.SPLITS["india-dev"]["india"] is True
    rows = runner.run(["naive"], ["full", "limit_only"], n=40, seed=1, india=True)
    assert len(rows) == 40
    out = tmp_path / "i.jsonl"
    main(["run", "--split", "india-dev", "--n", "30", "--buyers", "naive", "--configs", "full", "--out", str(out)])
    assert len(runner.load(out)) == 30
