from dia.ap2.models import IntentConstraints, SpecRequirement
from dia.arena.solver import eps_dominates, hard_violations, judge, make_features, solve, utility


def F(oid, total, days=3, rating=4.0, quality=0.5, ret=True, **specs):
    return make_features(oid, "s-" + oid, "sku-" + oid, total, days, rating, quality, ret, specs)


def C(**kw):
    base = dict(category="x", budget_total=5000, deadline_days=4)
    base.update(kw)
    return IntentConstraints(**base)


def test_hard_violations_each_axis():
    c = C(must_have=[SpecRequirement(key="anc", op="eq", value=True)], requires_refundability=True)
    assert hard_violations(F("a", 4000, anc=True), c) == []
    assert any("budget" in v for v in hard_violations(F("a", 5001, anc=True), c))
    assert any("deadline" in v for v in hard_violations(F("a", 4000, days=5, anc=True), c))
    assert any("must-have" in v for v in hard_violations(F("a", 4000, anc=False), c))
    assert any("returnable" in v for v in hard_violations(F("a", 4000, ret=False, anc=True), c))
    assert any("merchant" in v for v in hard_violations(F("a", 4000, anc=True), c, merchants=["other"]))


def test_missing_spec_fails_must_have():
    c = C(must_have=[SpecRequirement(key="anc", op="eq", value=True)])
    assert hard_violations(F("a", 100), c)


def test_eps_dominance_requires_beyond_eps_gain():
    a, b = F("a", 1000), F("b", 1010)  # 1% cheaper: within 2% eps -> not dominated
    assert not eps_dominates(a, b)
    assert eps_dominates(F("a", 900), b)  # ~11% cheaper, same elsewhere
    assert not eps_dominates(F("a", 900, days=5), b)  # slower: trade-off, not dominance


def test_defensible_is_pareto_front():
    c = C()
    cheap_slow, pricey_fast, dominated = F("cs", 2000, days=4), F("pf", 3000, days=1), F("d", 3500, days=4)
    gt = solve([cheap_slow, pricey_fast, dominated], c)
    ids = {f.offer_id for f in gt.defensible}
    assert ids == {"cs", "pf"} and len(gt.hard) == 3


def test_judge_cases():
    c = C()
    good, dom, over = F("g", 2000), F("d", 3000), F("o", 6000)
    gt = solve([good, dom, over], c)
    assert not judge(good, gt, c).violation
    j = judge(dom, gt, c)
    assert j.violation and j.dominated and not j.hard_violation and j.regret_u > 0
    j = judge(over, gt, c)
    assert j.violation and j.hard_violation


def test_abstain_semantics():
    c = C()
    gt_empty = solve([F("o", 9999)], c)
    assert judge(None, gt_empty, c).violation is False and judge(None, gt_empty, c).should_abstain
    assert judge(F("o", 9999), gt_empty, c).violation  # bought when nothing acceptable
    gt_ok = solve([F("g", 2000)], c)
    assert judge(None, gt_ok, c).violation is False  # needless abstention is a utility miss only


def test_utility_prefers_cheaper_and_faster():
    c = C()
    assert utility(F("a", 2000), c) > utility(F("b", 3000), c)
    assert utility(F("a", 2000, days=1), c) > utility(F("b", 2000, days=4), c)
