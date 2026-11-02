"""Buyer-agent interface and shared helpers (PLAN §6.7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..ap2.models import CartMandate, IntentConstraints, IntentMandate
from ..arena.market import MarketSession, ProvenanceItem
from ..arena.solver import Features


@dataclass
class ClaimedProps:
    """What the agent says it bought. Untrusted: compared against the signed cart by IntentCheck."""

    offer_id: str
    sku: str
    total: float
    delivery_days: int
    returnable: bool


@dataclass
class BuyerResult:
    cart: CartMandate | None            # None = abstain / ask the user
    claimed: ClaimedProps | None
    rationale: str = ""
    context_untrusted: list[ProvenanceItem] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


class BuyerAgent(Protocol):
    name: str

    def run(self, mandate: IntentMandate, sees_constraints: bool, session: MarketSession) -> BuyerResult: ...


NO_LIMIT = 1e9


def perceived_constraints(mandate: IntentMandate, sees_constraints: bool) -> IntentConstraints:
    """What a buyer can know about the intent.

    Precise intents ship structured constraints. For loose/underspecified intents the buyer has only the
    natural language: we let it recover a stated budget (a human reader would) and nothing else.
    """
    c = mandate.x_constraints
    assert c is not None
    if sees_constraints:
        return c
    m = re.search(r"Rs ([\d,]+)", mandate.natural_language_description)
    budget = float(m.group(1).replace(",", "")) if m else NO_LIMIT
    return IntentConstraints(category=c.category, budget_total=budget, deadline_days=99, must_have=[],
                             requires_refundability=False)


def buyer_score(f: Features, weights: dict, ref_total: float) -> float:
    """A buyer's own utility. Deliberately independent of solver.utility so it isn't the grader's function."""
    return (-weights.get("cost", 0.25) * f.total / ref_total
            - weights.get("delivery", 0.25) * f.delivery_days / 7
            + weights.get("rating", 0.25) * f.rating / 5
            + weights.get("quality", 0.25) * f.quality)


def claimed_from_cart(cart: CartMandate) -> ClaimedProps:
    line = cart.contents.x_line
    return ClaimedProps(line.offer_id, line.sku, cart.contents.total, line.delivery_days, line.returnable)
