from collections import Counter

import pytest

from dia.arena.catalogue import build_catalogue
from dia.arena.scenario import generate


@pytest.fixture(scope="module")
def cat():
    return build_catalogue(7)


@pytest.fixture(scope="module")
def scs(cat):
    return generate(cat, n=300, seed=1)


def test_deterministic(cat):
    a, b = generate(cat, n=20, seed=5), generate(cat, n=20, seed=5)
    key = lambda s: (s.sid, s.category, s.spotlight, s.mandate.natural_language_description,
                     tuple(s.market.offer_ids), s.constraints.budget_total)
    assert [key(s) for s in a] == [key(s) for s in b]
    assert [key(s) for s in a] != [key(s) for s in generate(cat, n=20, seed=6)]


def test_feasibility_matches_abstain_flag(scs):
    for s in scs:
        if s.abstain_case:
            assert not s.gt.hard, s.sid
        else:
            assert s.gt.hard, s.sid
            assert s.gt.defensible and s.gt.best is not None


def test_mix_roughly_as_planned(scs):
    spot = Counter(s.spotlight for s in scs)
    assert 0.1 < spot["none"] / len(scs) < 0.3
    assert all(spot[p] > 20 for p in ["dark_pattern", "injection", "bait_and_switch", "colluding", "flaky"])
    ab = sum(s.abstain_case for s in scs) / len(scs)
    assert 0.02 < ab < 0.15
    assert {"precise", "loose", "underspecified"} == {s.specificity for s in scs}


def test_spotlight_seller_present_and_clean_markets_clean(scs, cat):
    for s in scs:
        profiles = {cat.sellers[cat.offers[o].seller_id].profile for o in s.market.offer_ids}
        if s.spotlight in ("none", "flaky"):
            assert profiles <= {"honest", "flaky"}, s.sid
            if s.spotlight == "flaky":
                assert "flaky" in profiles, s.sid
        else:
            # attack isolation: only honest sellers plus the spotlight profile
            assert profiles <= {"honest", s.spotlight} and s.spotlight in profiles, (s.sid, profiles)


def test_universe_uses_effective_terms(scs, cat):
    """Ground truth must reflect checkout terms (drip fees / swapped SKU), not the quote."""
    n_diff = 0
    for s in scs:
        by_id = {f.offer_id: f for f in s.universe}
        for oid in s.market.offer_ids:
            o = cat.offers[oid]
            assert by_id[oid].total == o.effective.total
            n_diff += o.checkout is not None
    assert n_diff > 0


def test_market_size_and_single_category(scs, cat):
    for s in scs:
        assert 2 <= len(s.market.offer_ids) <= 30 + 5
        assert {cat.products[cat.offers[o].quoted.sku].category for o in s.market.offer_ids} == {s.category}
