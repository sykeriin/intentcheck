"""IntentCheck: decision-integrity verifier between CartMandate and PaymentMandate (PLAN §6.8).

Trust boundary: every decision is computed from TRUSTED data (merchant-signed cart, signed quotes, catalogue,
platform ratings, user-confirmed constraints). The only untrusted input is seller text, and it is touched
solely by deterministic regexes in taint.py: text can raise a flag, never clear one.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..ap2.models import CartMandate, IntentMandate
from ..ap2.signing import KeyDirectory, SignatureError, sha256_hex
from ..arena.market import MarketSession
from ..arena.solver import Features, eps_dominates, hard_violations, make_features, utility
from ..buyers.base import BuyerResult
from . import taint

ALLOW, STEP_UP, BLOCK = "allow", "step_up", "block"
_RANK = {ALLOW: 0, STEP_UP: 1, BLOCK: 2}


@dataclass(frozen=True)
class Config:
    name: str = "full"
    rederivation: bool = True
    counterfactual: bool = True
    taint: bool = True
    limit_only: bool = False           # Reserve Pay baseline: total <= per-transaction limit, nothing else
    view_coverage: float = 1.0         # fraction of sellers the verifier's own market view can reach
    search_timeout_ms: float = 5000
    search_retries: int = 2
    preview_k: int = 5


CONFIGS = {
    "full": Config(),
    "no_rederivation": Config(name="no_rederivation", rederivation=False),
    "no_counterfactual": Config(name="no_counterfactual", counterfactual=False),
    "no_taint": Config(name="no_taint", taint=False),
    "hard_only": Config(name="hard_only", counterfactual=False, taint=False),
    "limit_only": Config(name="limit_only", limit_only=True),
    "full_partial_view": Config(name="full_partial_view", view_coverage=0.7),
}


@dataclass
class Check:
    name: str
    outcome: str       # allow | step_up | block
    detail: str


@dataclass
class Verdict:
    decision: str
    explanation: str
    checks: list[Check]
    audit: dict
    compute_ms: float = 0.0
    sim_network_ms: float = 0.0
    better_offer_id: str | None = None


def _in_view(seller_id: str, coverage: float) -> bool:
    if coverage >= 1.0:
        return True
    h = int(hashlib.sha256(f"view:{seller_id}".encode()).hexdigest(), 16) % 1000
    return h < coverage * 1000


def _derive(session: MarketSession, cart: CartMandate) -> Features:
    """Cart properties from TRUSTED sources only: the signed cart, the catalogue, platform ratings."""
    line = cart.contents.x_line
    p = session.get_product(line.sku)
    return make_features(line.offer_id, line.seller_id, line.sku, cart.contents.total, line.delivery_days,
                         session.seller_rating(line.seller_id), p.quality, line.returnable, p.specs,
                         cod=line.cod, window=line.return_window_days)


def _from_claim(session: MarketSession, result: BuyerResult) -> Features:
    """no_rederivation ablation: believe the buyer's own account of what it bought."""
    cl = result.claimed
    p = session.get_product(cl.sku)
    seller = session.m.cat.offers[cl.offer_id].seller_id
    return make_features(cl.offer_id, seller, cl.sku, cl.total, cl.delivery_days,
                         session.seller_rating(seller), p.quality, cl.returnable, p.specs)


class IntentCheck:
    def __init__(self, directory: KeyDirectory, config: Config | str = "full"):
        self.dir = directory
        self.cfg = CONFIGS[config] if isinstance(config, str) else config

    # ------------------------------------------------------------------
    def check(self, mandate: IntentMandate, cart: CartMandate, result: BuyerResult,
              session: MarketSession) -> Verdict:
        t0 = time.perf_counter()
        net0 = session.sim_network_ms
        checks: list[Check] = []
        c = mandate.x_constraints
        assert c is not None, "IntentCheck requires user-confirmed structured constraints"

        if self.cfg.limit_only:
            limit = c.per_txn_limit if c.per_txn_limit is not None else c.budget_total
            ok = cart.contents.total <= limit + 1e-6
            checks.append(Check("spend_limit", ALLOW if ok else BLOCK,
                                f"total Rs {cart.contents.total:,.0f} vs limit Rs {limit:,.0f}"))
            return self._finish(mandate, cart, checks, t0, net0, session)

        # 1. Integrity ---------------------------------------------------
        try:
            cart.verify(self.dir)
            checks.append(Check("integrity", ALLOW, "merchant signature and cart hash valid"))
        except SignatureError as e:
            checks.append(Check("integrity", BLOCK, f"cart signature invalid: {e}"))
            return self._finish(mandate, cart, checks, t0, net0, session)
        if datetime.fromisoformat(cart.contents.cart_expiry) < datetime.now(UTC):
            checks.append(Check("integrity", BLOCK, "cart has expired"))
        if cart.contents.currency != c.currency:
            checks.append(Check("integrity", BLOCK, f"currency {cart.contents.currency} != {c.currency}"))
        if mandate.merchants and cart.contents.x_line.seller_id not in mandate.merchants:
            checks.append(Check("integrity", BLOCK, "merchant not in the mandate's allowed list"))
        if any(k.outcome == BLOCK for k in checks):
            return self._finish(mandate, cart, checks, t0, net0, session)

        # 2. Trusted re-derivation ----------------------------------------
        real = _derive(session, cart)
        if self.cfg.rederivation:
            chosen = real
            if result.claimed is not None:
                cl, notes = result.claimed, []
                if real.total > cl.total + 1.0:
                    notes.append(f"total Rs {real.total:,.0f} vs Rs {cl.total:,.0f} the agent expected")
                if real.sku != cl.sku:
                    notes.append("a different product than the agent believed it was buying")
                if real.delivery_days > cl.delivery_days:
                    notes.append(f"delivery in {real.delivery_days}d vs {cl.delivery_days}d expected")
                if cl.returnable and not real.returnable:
                    notes.append("item is not returnable though the agent expected it to be")
                checks.append(Check("rederivation", STEP_UP if notes else ALLOW,
                                    "; ".join(notes) if notes else "cart matches the agent's account"))
        else:
            chosen = _from_claim(session, result) if result.claimed else real
            checks.append(Check("rederivation", ALLOW, "skipped (ablation): using the agent's own account"))

        # 3. Hard constraints ---------------------------------------------
        hv = hard_violations(chosen, c, mandate.merchants)
        checks.append(Check("hard_constraints", BLOCK if hv else ALLOW, "; ".join(hv) if hv else "all satisfied"))

        # 4. Counterfactual alternatives + 5. Taint ------------------------
        better: Features | None = None
        view: list[Features] = []
        if not hv and (self.cfg.counterfactual or self.cfg.taint):
            view = self._market_view(session, c, mandate)
        if not hv and self.cfg.counterfactual:
            better = self._find_dominator(session, c, mandate, chosen, view)
            if better is not None:
                checks.append(Check(
                    "counterfactual", STEP_UP,
                    f"offer {better.offer_id} is at least as good on every axis and better on one: "
                    f"Rs {better.total:,.0f} vs Rs {chosen.total:,.0f}, {better.delivery_days}d vs "
                    f"{chosen.delivery_days}d, seller rating {better.rating} vs {chosen.rating}"))
            else:
                checks.append(Check("counterfactual", ALLOW, f"no dominating offer in a view of {len(view)} offers"))
        if not hv and self.cfg.taint:
            hits = sorted({h for item in result.context_untrusted if item.origin == chosen.seller_id
                           for h in taint.scan(item.text or "")})
            if hits:
                top_u = max((utility(f, c) for f in view if not hard_violations(f, c, mandate.merchants)),
                            default=float("-inf"))
                if utility(chosen, c) < top_u - 0.01:
                    checks.append(Check("taint", STEP_UP,
                                        f"the chosen seller's listing contained manipulation patterns "
                                        f"({', '.join(hits)}) and a better-scoring offer exists"))
                else:
                    checks.append(Check("taint", ALLOW, f"manipulation patterns ({', '.join(hits)}) "
                                                        f"but the choice is the best available"))
            else:
                checks.append(Check("taint", ALLOW, "no manipulation patterns from the chosen seller"))
        return self._finish(mandate, cart, checks, t0, net0, session, better)

    # ------------------------------------------------------------------
    def _market_view(self, session, c, mandate) -> list[Features]:
        """The verifier's OWN, independent look at the market via the public API (signed quotes only)."""
        listings = session.search(timeout_ms=self.cfg.search_timeout_ms, retries=self.cfg.search_retries)
        out = []
        for li in listings:
            if not _in_view(li.seller_id, self.cfg.view_coverage):
                continue
            q = session.get_quote(li.offer_id)  # only the identifier is taken from the untrusted listing
            p = session.get_product(q["sku"])
            out.append(make_features(q["offer_id"], q["seller_id"], q["sku"], q["total"], q["delivery_days"],
                                     session.seller_rating(q["seller_id"]), p.quality, q["returnable"], p.specs,
                                     cod=q.get("cod", True), window=q.get("return_window_days")))
        return out

    def _find_dominator(self, session, c, mandate, chosen, view) -> Features | None:
        cands = [f for f in view if f.offer_id != chosen.offer_id
                 and not hard_violations(f, c, mandate.merchants) and eps_dominates(f, chosen)]
        cands.sort(key=lambda f: f.total)
        confirmed = []
        for f in cands[: self.cfg.preview_k]:
            # A quote can hide fees or a swapped SKU: confirm on the real signed cart before accusing the buyer.
            real = _derive(session, session.checkout(f.offer_id))
            if not hard_violations(real, c, mandate.merchants) and eps_dominates(real, chosen):
                confirmed.append(real)
        return min(confirmed, key=lambda f: f.total) if confirmed else None

    def _finish(self, mandate, cart, checks, t0, net0, session, better: Features | None = None) -> Verdict:
        decision = max((k.outcome for k in checks), key=_RANK.get, default=ALLOW)
        why = [k.detail for k in checks if k.outcome == decision and decision != ALLOW]
        if decision == ALLOW:
            expl = "This purchase matches what you asked for."
        else:
            lead = "Blocked" if decision == BLOCK else "Please confirm"
            sent = [(w[0].upper() + w[1:]) if w else w for w in why[:2]]
            expl = f"{lead}: " + " ".join(s if s.endswith(".") else s + "." for s in sent)
        audit = {
            "config": self.cfg.name,
            "mandate_hash": sha256_hex(mandate.model_dump(mode="json", exclude={"intent_expiry"})),
            "cart_hash": cart.content_hash(),
            "checks": [{"name": k.name, "outcome": k.outcome, "detail": k.detail} for k in checks],
            "decision": decision,
        }
        return Verdict(decision, expl, checks, audit, (time.perf_counter() - t0) * 1000,
                       session.sim_network_ms - net0, better.offer_id if better else None)
