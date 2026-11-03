"""dia run | report | demo"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .eval import metrics, report, run as runner


def _run(a) -> None:
    if a.resamples:
        metrics.set_resamples(a.resamples)
    out = Path(a.out)
    warnings: list[str] = []
    sp = dict(runner.SPLITS[a.split]) if a.split else {}
    n, seed = a.n or sp.pop("n", 1000), a.seed if a.seed is not None else sp.pop("seed", 1)
    sp.pop("n", None), sp.pop("seed", None)
    if a.india:
        sp["india"] = True
    rows = runner.run(a.buyers.split(","), a.configs.split(","), n, seed, out=out, **sp,
                      token_budget=a.token_budget, transcripts=a.transcripts, max_turns=a.max_turns,
                      repeat=a.repeat, warnings=warnings, paraphrase=a.paraphrase)
    print(report.render(rows))
    for w in warnings:
        print(f"\nWARNING: {w}")
    print(f"\n[wrote {len(rows)} rows to {out}]")


def _report(a) -> None:
    if a.resamples:
        metrics.set_resamples(a.resamples)
    print(report.render(runner.load(Path(a.path))))


def _paraphrase(a) -> None:
    from .arena.catalogue import build_catalogue
    from .arena.india import annotate
    from .arena.paraphrase import ParaphraseCache, generate_cache
    from .arena.scenario import generate
    kind, _, arg = a.provider.partition(":")
    provider = runner.make_provider(kind, arg)
    sp = dict(runner.SPLITS[a.split])
    n, seed, india = sp.pop("n"), sp.pop("seed"), sp.pop("india", False)
    cat = build_catalogue(7)
    if india:
        annotate(cat)
    scs = generate(cat, n=n, seed=seed, india=india, **sp)
    texts = list(dict.fromkeys(li.description for s in scs for li in s.market.listings.values()))
    texts = texts[: a.limit] if a.limit else texts
    print(f"{len(texts)} unique listing texts to rewrite with {a.provider} (mode={a.mode})")
    cache, stats = generate_cache(texts, provider, ParaphraseCache.load(a.out) if Path(a.out).exists() else None,
                                  mode=a.mode)
    cache.save(a.out)
    print(json.dumps(stats, indent=1), f"\n[wrote {len(cache.entries)} entries to {a.out}]")


def _x402(a) -> None:
    from .ap2.signing import KeyDirectory, SigningKey
    from .arena.catalogue import build_catalogue
    from .arena.scenario import generate
    from .eval.judge import judge_result
    from .intentcheck.verifier import IntentCheck
    from .x402 import (HDR_PAYMENT, HDR_REQUIRED, IntentGuard, LocalFacilitator, b64, payment_required, unb64,
                       unguarded_payment)

    cat = build_catalogue(7)
    scs = generate(cat, n=400, seed=a.seed)
    buyer = runner.make_buyer(a.buyer)
    user = SigningKey.from_seed("user-1", b"demo-user")
    users = KeyDirectory()
    users.register(user)
    guard = IntentGuard(IntentCheck(scs[0].market.keyring.directory, "full"), user)
    for i, sc in enumerate(scs):
        if sc.spotlight != a.profile or not sc.buyer_sees_constraints:
            continue
        res = buyer.run(sc.mandate, True, sc.market.session(a.buyer, i))
        if res.cart is None:
            continue
        j = judge_result(sc, res)
        prof = cat.sellers[res.cart.contents.x_line.seller_id].profile
        if (a.profile == "none") == j.violation or (a.profile != "none" and prof != a.profile):
            continue
        required = payment_required(res.cart, f"https://shop.example/{res.cart.contents.id}")
        req = required["accepts"][0]
        print(f"\nINTENT   : {sc.mandate.natural_language_description}")
        print(f"AGENT    : {a.buyer} chose {res.cart.contents.merchant_name} ({prof}); truth: "
              f"{'VIOLATION - ' + '; '.join(j.reasons) if j.violation else 'defensible choice'}")
        print(f"HTTP 402 : {HDR_REQUIRED}: x402Version={required['x402Version']} scheme={req['scheme']} "
              f"network={req['network']} amount={req['amount']} {req['asset']} payTo={req['payTo']}")
        out = guard.pay(required, res.cart, sc.mandate, res, sc.market.session("ic", 10_000 + i))
        print(f"GUARD    : {out.decision.upper()}  {out.reason}")
        fac = LocalFacilitator(users)
        if out.header:
            r = fac.settle(unb64(out.header), req)
            print(f"SETTLE   : {HDR_PAYMENT} accepted -> success={r['success']} tx={r['transaction'][:14]}...")
        else:
            print(f"SETTLE   : no {HDR_PAYMENT} header sent; nothing paid")
            r = fac.settle(unb64(unguarded_payment(user, required)), req)
            print(f"WITHOUT THE GUARD the facilitator would have returned success={r['success']} "
                  f"(valid signature, amount {req['amount']} paise)")
        return
    print(f"no matching scenario for profile={a.profile}")


def _confirm(a) -> None:
    from .eval import confirm
    rows = runner.load(Path(a.path))
    print(confirm.render(confirm.evaluate(rows, resamples=a.resamples or confirm.B)))


def _demo(a) -> None:
    from datetime import UTC, datetime  # noqa: F401
    from .ap2.facilitator import MockFacilitator
    from .ap2.models import PaymentMandate
    from .ap2.signing import KeyDirectory, SigningKey
    from .arena.catalogue import build_catalogue
    from .arena.scenario import generate
    from .eval.judge import judge_result
    from .intentcheck.verifier import IntentCheck

    cat = build_catalogue(7)
    scs = generate(cat, n=400, seed=a.seed)
    buyer = runner.make_buyer(a.buyer)
    user = SigningKey.from_seed("user-1", b"demo-user")
    users = KeyDirectory()
    users.register(user)
    ic = IntentCheck(scs[0].market.keyring.directory, a.config)
    fac = MockFacilitator(scs[0].market.keyring.directory, users)
    for i, sc in enumerate(scs):
        if sc.spotlight != a.profile:
            continue
        res = buyer.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session(a.buyer, i))
        if res.cart is None:
            continue
        j = judge_result(sc, res)
        if not sc.buyer_sees_constraints:
            continue  # keep the demo about the attack, not about an intent the buyer never fully saw
        chosen_profile = cat.sellers[res.cart.contents.x_line.seller_id].profile
        if a.profile == "none":
            if j.violation:
                continue  # show a good purchase going through
        else:
            if not j.violation or chosen_profile != a.profile:
                continue
        c = sc.constraints
        print(f"\nINTENT  : {sc.mandate.natural_language_description}")
        print(f"          (budget Rs {c.budget_total:,.0f}, within {c.deadline_days} days; "
              f"per-transaction limit Rs {c.per_txn_limit:,.0f})")
        line = res.cart.contents.x_line
        print(f"BUYER   : {a.buyer} chose {line.offer_id} from {res.cart.contents.merchant_name} "
              f"({cat.sellers[line.seller_id].profile})")
        print(f"CLAIMED : total Rs {res.claimed.total:,.0f}, delivery {res.claimed.delivery_days}d")
        print(f"SIGNED  : total Rs {res.cart.contents.total:,.0f}, delivery {line.delivery_days}d, "
              f"merchant signature {'valid' if res.cart.verify(sc.market.keyring.directory) else '?'}")
        print(f"TRUTH   : violation={j.violation}  {'; '.join(j.reasons) or 'defensible choice'}")
        v = ic.check(sc.mandate, res.cart, res, sc.market.session("ic", 10_000 + i))
        print(f"VERDICT : {v.decision.upper()}  ({a.config})\n          {v.explanation}")
        if v.decision == "allow":
            pm = PaymentMandate.for_cart(res.cart, user)
            r = fac.settle(res.cart, pm, c.per_txn_limit)
            print(f"PAYMENT : {'settled Rs %.0f to %s' % (r.amount, r.merchant) if r.ok else 'rejected: ' + r.reason}")
        else:
            pm = PaymentMandate.for_cart(res.cart, user)
            r = fac.settle(res.cart, pm, c.per_txn_limit)
            print(f"WITHOUT INTENTCHECK the facilitator would have {'SETTLED Rs %.0f' % r.amount if r.ok else 'rejected: ' + r.reason}"
                  f" (every signature valid)")
        return
    print(f"no matching scenario found for profile={a.profile}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="dia")
    sub = p.add_subparsers(required=True)
    r = sub.add_parser("run")
    r.add_argument("--buyers", default="oracle,naive,cautious")
    r.add_argument("--configs", default="full,no_rederivation,no_counterfactual,no_taint,hard_only,limit_only,"
                                        "full_partial_view")
    r.add_argument("--split", choices=sorted(runner.SPLITS), default=None,
                   help="named scenario split (sets seed, n, clean fraction, intent mix); --n/--seed override")
    r.add_argument("--n", type=int, default=None)
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--out", default="results/run.jsonl")
    r.add_argument("--resamples", type=int, default=0)
    r.add_argument("--token-budget", type=int, default=None,
                   help="hard cap on total LLM tokens for the whole run (recommended for any real model)")
    r.add_argument("--transcripts", default=None, help="record each LLM buyer's replies here (see llm:replay:<dir>)")
    r.add_argument("--max-turns", type=int, default=12)
    r.add_argument("--repeat", type=int, default=0, help="shift market latency seeds, for the variance subset")
    r.add_argument("--paraphrase", default=None, help="paraphrase cache JSON (see `dia paraphrase`)")
    r.add_argument("--india", action="store_true", help="India variant (COD / return-window); implied by india-dev")
    r.set_defaults(fn=_run)
    q = sub.add_parser("report")
    q.add_argument("path")
    q.add_argument("--resamples", type=int, default=0)
    q.set_defaults(fn=_report)
    pp = sub.add_parser("paraphrase", help="build a listing-text paraphrase cache with a live model (one-off)")
    pp.add_argument("--provider", required=True, help="e.g. anthropic:<model> or openai:<model>")
    pp.add_argument("--split", choices=sorted(runner.SPLITS), default="llm-test")
    pp.add_argument("--mode", choices=["strict", "free"], default="strict")
    pp.add_argument("--out", required=True)
    pp.add_argument("--limit", type=int, default=None, help="rewrite at most N unique texts (cost control)")
    pp.set_defaults(fn=_paraphrase)
    c = sub.add_parser("confirm", help="confirmatory analysis C1-C5 from PREREG.md")
    c.add_argument("path")
    c.add_argument("--resamples", type=int, default=0)
    c.set_defaults(fn=_confirm)
    x = sub.add_parser("x402", help="x402 v2 flow with the IntentCheck guard (local simulation)")
    x.add_argument("--profile", default="bait_and_switch",
                   choices=["none", "dark_pattern", "injection", "bait_and_switch", "colluding", "flaky"])
    x.add_argument("--buyer", default="naive")
    x.add_argument("--seed", type=int, default=11)
    x.set_defaults(fn=_x402)
    d = sub.add_parser("demo")
    d.add_argument("--profile", default="dark_pattern",
                   choices=["none", "dark_pattern", "injection", "bait_and_switch", "colluding", "flaky"])
    d.add_argument("--buyer", default="naive")
    d.add_argument("--config", default="full")
    d.add_argument("--seed", type=int, default=11)
    d.add_argument("--only-violations", action="store_true", default=True)
    d.set_defaults(fn=_demo)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
