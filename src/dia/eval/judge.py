"""Grade one buyer result against the scenario's ground truth, using the SIGNED cart as the decision."""

from __future__ import annotations

from ..arena.scenario import Scenario, features_from_cart
from ..arena.solver import Judgement, judge
from ..buyers.base import BuyerResult


def judge_result(sc: Scenario, res: BuyerResult) -> Judgement:
    chosen = features_from_cart(res.cart, sc.market.cat) if res.cart else None
    return judge(chosen, sc.gt, sc.constraints)
