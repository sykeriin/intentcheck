"""dia run | report | demo"""

from __future__ import annotations

import argparse
from pathlib import Path

from .eval import metrics, report, run as runner


def _run(a) -> None:
    if a.resamples:
        metrics.set_resamples(a.resamples)
    out = Path(a.out)
    rows = runner.run(a.buyers.split(","), a.configs.split(","), a.n, a.seed, out=out)
    print(report.render(rows))
    print(f"\n[wrote {len(rows)} rows to {out}]")


def _report(a) -> None:
    if a.resamples:
        metrics.set_resamples(a.resamples)
    print(report.render(runner.load(Path(a.path))))


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
    r.add_argument("--n", type=int, default=1000)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--out", default="results/run.jsonl")
    r.add_argument("--resamples", type=int, default=0)
    r.set_defaults(fn=_run)
    q = sub.add_parser("report")
    q.add_argument("path")
    q.add_argument("--resamples", type=int, default=0)
    q.set_defaults(fn=_report)
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
