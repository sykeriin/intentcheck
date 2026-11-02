"""Evaluation runner: scenarios x buyers x verifier configs -> JSONL (PLAN §7)."""

from __future__ import annotations

import json
from pathlib import Path

from ..arena.catalogue import build_catalogue
from ..arena.scenario import generate
from ..buyers.scripted import CautiousBuyer, NaiveBuyer, OracleBuyer
from ..intentcheck.verifier import CONFIGS, IntentCheck
from .judge import judge_result

ADVERSARIAL = {"dark_pattern", "injection", "bait_and_switch", "colluding"}
BUYERS = {"oracle": OracleBuyer, "naive": NaiveBuyer, "cautious": CautiousBuyer}


def make_buyer(name: str):
    if name in BUYERS:
        return BUYERS[name]()
    raise KeyError(f"unknown buyer {name!r}; available: {sorted(BUYERS)}")


def run(buyer_names: list[str], configs: list[str], n: int, seed: int, catalogue_seed: int = 7,
        out: Path | None = None) -> list[dict]:
    cat = build_catalogue(catalogue_seed)
    scs = generate(cat, n=n, seed=seed)
    directory = scs[0].market.keyring.directory
    checkers = {c: IntentCheck(directory, c) for c in configs}
    rows = []
    for bname in buyer_names:
        buyer = make_buyer(bname)
        for i, sc in enumerate(scs):
            res = buyer.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session(bname, i))
            j = judge_result(sc, res)
            row = {
                "sid": sc.sid, "buyer": bname, "category": sc.category, "spotlight": sc.spotlight,
                "specificity": sc.specificity, "abstain_case": sc.abstain_case,
                "sees_constraints": sc.buyer_sees_constraints,
                "bought": j.bought, "violation": j.violation, "hard_violation": j.hard_violation,
                "dominated": j.dominated, "regret_u": j.regret_u, "price_gap": j.price_gap,
                "reasons": j.reasons, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
            }
            if res.cart is not None:
                line = res.cart.contents.x_line
                prof = sc.market.cat.sellers[line.seller_id].profile
                limit = sc.constraints.per_txn_limit
                row.update({"chosen_profile": prof, "chosen_adversarial": prof in ADVERSARIAL,
                            "total": res.cart.contents.total, "per_txn_limit": limit,
                            "within_limit": limit is None or res.cart.contents.total <= limit + 1e-6,
                            "verdicts": {}})
                for cname, ic in checkers.items():
                    v = ic.check(sc.mandate, res.cart, res, sc.market.session("ic:" + cname, 10_000 + i))
                    row["verdicts"][cname] = {"decision": v.decision, "compute_ms": v.compute_ms,
                                              "net_ms": v.sim_network_ms,
                                              "causes": [k.name for k in v.checks if k.outcome != "allow"]}
            rows.append(row)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")
    return rows


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
