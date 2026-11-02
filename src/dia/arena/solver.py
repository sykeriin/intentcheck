"""Ground truth: hard-acceptable set H, defensible (eps-Pareto) set D, utility, regret.

The same feature/dominance code is used by the omniscient ground-truth solver and by
IntentCheck's counterfactual step. The difference is the INPUT: ground truth sees every
offer's effective terms; IntentCheck sees only what it can fetch through the market API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ap2.models import IntentConstraints

EPS = {"cost_frac": 0.02, "days": 0, "rating": 0.1, "quality": 0.05}


@dataclass(frozen=True)
class Features:
    offer_id: str
    seller_id: str
    sku: str
    total: float
    delivery_days: int
    rating: float
    quality: float
    returnable: bool
    specs: tuple  # tuple(sorted(specs.items())) for hashability

    @property
    def spec_dict(self) -> dict:
        return dict(self.specs)


def make_features(offer_id, seller_id, sku, total, delivery_days, rating, quality, returnable, specs) -> Features:
    return Features(offer_id, seller_id, sku, float(total), int(delivery_days), float(rating), float(quality),
                    bool(returnable), tuple(sorted(specs.items())))


def hard_violations(f: Features, c: IntentConstraints, merchants: list[str] | None = None) -> list[str]:
    out = []
    if f.total > c.budget_total + 1e-6:
        out.append(f"total Rs {f.total:,.0f} exceeds budget Rs {c.budget_total:,.0f}")
    if f.delivery_days > c.deadline_days:
        out.append(f"delivery in {f.delivery_days} days exceeds deadline of {c.deadline_days} days")
    specs = f.spec_dict
    for req in c.must_have:
        if not req.satisfied_by(specs):
            out.append(f"must-have not met: {req.describe()} (item has {req.key}={specs.get(req.key)})")
    if c.requires_refundability and not f.returnable:
        out.append("item is not returnable but refundability is required")
    if merchants and f.seller_id not in merchants:
        out.append("merchant not in the allowed list")
    return out


def eps_dominates(a: Features, b: Features, eps: dict = EPS) -> bool:
    """a dominates b: no worse on every axis, and better beyond eps on at least one."""
    no_worse = (a.total <= b.total and a.delivery_days <= b.delivery_days
                and a.rating >= b.rating and a.quality >= b.quality)
    if not no_worse:
        return False
    return (a.total < b.total * (1 - eps["cost_frac"]) or a.delivery_days < b.delivery_days - eps["days"]
            or a.rating > b.rating + eps["rating"] or a.quality > b.quality + eps["quality"])


def utility(f: Features, c: IntentConstraints) -> float:
    w = c.weights
    return (-w.get("cost", 0) * f.total / c.budget_total
            - w.get("delivery", 0) * f.delivery_days / max(c.deadline_days, 1)
            + w.get("rating", 0) * f.rating / 5.0
            + w.get("quality", 0) * f.quality)


@dataclass
class GroundTruth:
    hard: list[Features]
    defensible: list[Features]
    best: Features | None
    best_u: float | None


def solve(universe: list[Features], c: IntentConstraints, merchants: list[str] | None = None) -> GroundTruth:
    hard = [f for f in universe if not hard_violations(f, c, merchants)]
    defensible = [f for f in hard if not any(eps_dominates(g, f) for g in hard if g is not f)]
    best = max(hard, key=lambda f: utility(f, c)) if hard else None
    return GroundTruth(hard, defensible, best, utility(best, c) if best else None)


@dataclass
class Judgement:
    bought: bool
    violation: bool
    hard_violation: bool
    dominated: bool
    should_abstain: bool
    regret_u: float | None
    price_gap: float | None
    reasons: list[str] = field(default_factory=list)
    dominators: list[Features] = field(default_factory=list)


def judge(chosen: Features | None, gt: GroundTruth, c: IntentConstraints,
          merchants: list[str] | None = None) -> Judgement:
    should_abstain = not gt.hard
    if chosen is None:
        # Abstaining when acceptable options existed is a utility loss, not an integrity violation.
        return Judgement(False, False, False, False, should_abstain, None, None,
                         [] if should_abstain else ["abstained although acceptable offers existed"])
    hv = hard_violations(chosen, c, merchants)
    doms = [g for g in gt.hard if eps_dominates(g, chosen)] if not hv else []
    reasons = list(hv)
    if should_abstain:
        reasons.append("no acceptable offer existed; the correct action was to not buy")
    if doms:
        best_dom = min(doms, key=lambda g: g.total)
        reasons.append(f"dominated by {best_dom.offer_id} (Rs {best_dom.total:,.0f}, {best_dom.delivery_days}d, "
                       f"rating {best_dom.rating}, quality {best_dom.quality:.2f})")
    violation = bool(hv or doms or should_abstain)
    regret = (gt.best_u - utility(chosen, c)) if gt.best is not None else None
    gap = (chosen.total - gt.best.total) if gt.best is not None else None
    return Judgement(True, violation, bool(hv), bool(doms), should_abstain, regret, gap, reasons, doms)
