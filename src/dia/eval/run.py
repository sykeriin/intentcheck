"""Evaluation runner: scenarios x buyers x verifier configs -> JSONL (PLAN §7)."""

from __future__ import annotations

import json
from pathlib import Path

from ..arena.catalogue import build_catalogue
from ..arena.scenario import generate
from ..buyers.llm import BudgetExceeded, LLMBuyer, TokenBudget
from ..buyers.llm import DryRunProvider
from ..buyers.providers import AnthropicProvider, OpenAICompatProvider, ReplayProvider
from ..buyers.scripted import CautiousBuyer, NaiveBuyer, OracleBuyer
from ..intentcheck.verifier import CONFIGS, IntentCheck
from .judge import judge_result

# Named scenario splits. 'dev' is for building and tuning the harness and verifier (scripted buyers only).
# 'llm-test' is the confirmatory split for LLM buyers: it is never used to tune anything (see PREREG.md).
SPLITS = {
    "dev": dict(seed=1, n=1000, clean_frac=0.2, specificity_weights=(0.4, 0.4, 0.2)),
    "llm-test": dict(seed=2026, n=300, clean_frac=0.3, specificity_weights=(0.7, 0.2, 0.1)),
}

ADVERSARIAL = {"dark_pattern", "injection", "bait_and_switch", "colluding"}
BUYERS = {"oracle": OracleBuyer, "naive": NaiveBuyer, "cautious": CautiousBuyer}


def make_buyer(name: str, budget: TokenBudget | None = None, transcripts: str | None = None,
               max_turns: int = 12):
    """Scripted buyers by name; LLM buyers by spec:
         llm:dry                      deterministic stand-in policy (no model, no key)
         llm:anthropic:<model>        Anthropic Messages API (ANTHROPIC_API_KEY)
         llm:openai:<model>           any OpenAI-compatible endpoint (OPENAI_BASE_URL, OPENAI_API_KEY)
         llm:replay:<dir>             replay recorded transcripts (no model access)
    """
    if name in BUYERS:
        return BUYERS[name]()
    if name.startswith("llm:"):
        _, kind, *rest = name.split(":", 2)
        arg = rest[0] if rest else ""
        if kind == "dry":
            provider = DryRunProvider()
        elif kind == "anthropic":
            provider = AnthropicProvider(arg)
        elif kind == "openai":
            provider = OpenAICompatProvider(arg)
        elif kind == "replay":
            provider = ReplayProvider(arg)
        else:
            raise KeyError(f"unknown LLM provider {kind!r}")
        return LLMBuyer(provider, max_turns=max_turns, budget=budget, record_dir=transcripts)
    raise KeyError(f"unknown buyer {name!r}; scripted: {sorted(BUYERS)}; LLM: llm:dry | llm:anthropic:<model> | "
                   f"llm:openai:<model> | llm:replay:<dir>")


def run(buyer_names: list[str], configs: list[str], n: int, seed: int, catalogue_seed: int = 7,
        out: Path | None = None, token_budget: int | None = None, transcripts: str | None = None,
        max_turns: int = 12, repeat: int = 0, warnings: list[str] | None = None,
        clean_frac: float = 0.2, specificity_weights: tuple[float, float, float] = (0.4, 0.4, 0.2)) -> list[dict]:
    """`repeat` shifts the market's latency seeds (not model sampling) for the variance subset."""
    cat = build_catalogue(catalogue_seed)
    scs = generate(cat, n=n, seed=seed, clean_frac=clean_frac, specificity_weights=specificity_weights)
    directory = scs[0].market.keyring.directory
    checkers = {c: IntentCheck(directory, c) for c in configs}
    budget = TokenBudget(token_budget) if token_budget else None
    rows = []
    for bname in buyer_names:
        buyer = make_buyer(bname, budget, transcripts, max_turns)
        for i, sc in enumerate(scs):
            try:
                res = buyer.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session(bname, i + 100_000 * repeat))
            except BudgetExceeded as e:
                msg = f"{bname}: stopped after {i} of {len(scs)} scenarios: {e}"
                if warnings is not None:
                    warnings.append(msg)
                break
            j = judge_result(sc, res)
            row = {
                "sid": sc.sid, "buyer": bname, "category": sc.category, "spotlight": sc.spotlight,
                "specificity": sc.specificity, "abstain_case": sc.abstain_case,
                "sees_constraints": sc.buyer_sees_constraints,
                "bought": j.bought, "violation": j.violation, "hard_violation": j.hard_violation,
                "dominated": j.dominated, "regret_u": j.regret_u, "price_gap": j.price_gap,
                "reasons": j.reasons, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                "status": res.status,
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
                    v = ic.check(sc.mandate, res.cart, res, sc.market.session("ic:" + cname, 10_000 + i + 100_000 * repeat))
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
