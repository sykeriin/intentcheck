"""Markdown report from result rows."""

from __future__ import annotations

from . import metrics as M

PROFILES = ["none", "dark_pattern", "injection", "bait_and_switch", "colluding", "flaky"]


def pct(t) -> str:
    r, lo, hi, n = t
    return "n/a" if n == 0 else f"{r:.1%} [{lo:.1%}, {hi:.1%}]"


def render(rows: list[dict]) -> str:
    buyers = list(dict.fromkeys(r["buyer"] for r in rows))
    cfgs = list(next((r["verdicts"] for r in rows if "verdicts" in r), {}).keys())
    out = []
    n_sc = len({r["sid"] for r in rows})
    out.append(f"# MarketArena results ({n_sc} scenarios, 95% bootstrap CIs)\n")
    out.append("Scripted buyers validate the harness; they are **not** evidence about real agents.\n")

    out.append("## Buyer decision integrity\n")
    out.append("| buyer | violation rate | hard violations | mean regret (utility) |\n|---|---|---|---|")
    for b in buyers:
        rs = M.select(rows, buyer=b)
        rg = M.regret(rs)
        out.append(f"| {b} | {pct(M.violation_rate(rs))} | {pct(M.hard_rate(rs))} | "
                   f"{rg[0]:.3f} [{rg[1]:.3f}, {rg[2]:.3f}] |" if rg[3] else
                   f"| {b} | {pct(M.violation_rate(rs))} | {pct(M.hard_rate(rs))} | n/a |")

    out.append("\n## Completion and cost\n")
    out.append("| buyer | purchased | abstained | incomplete | error | input tokens | output tokens |\n"
               "|---|---|---|---|---|---|---|")
    for b in buyers:
        rs = M.select(rows, buyer=b)
        st = lambda s: sum(1 for r in rs if r.get("status", "ok" if r.get("bought") else "abstained") == s)
        out.append(f"| {b} | {st('ok')} | {st('abstained')} | {st('incomplete')} | {st('error')} | "
                   f"{sum(r['tokens_in'] for r in rs):,} | {sum(r['tokens_out'] for r in rs):,} |")

    out.append("\n## Violation rate by seller profile in the market (spotlight)\n")
    out.append("| buyer | " + " | ".join(PROFILES) + " |\n|---|" + "---|" * len(PROFILES))
    for b in buyers:
        out.append(f"| {b} | " + " | ".join(f"{M.violation_rate(M.select(rows, buyer=b, spotlight=p))[0]:.1%}"
                                            for p in PROFILES) + " |")

    out.append("\n## Violation rate by intent specificity (RQ4)\n")
    out.append("| buyer | precise (constraints visible) | loose | underspecified |\n|---|---|---|---|")
    for b in buyers:
        out.append(f"| {b} | " + " | ".join(f"{M.violation_rate(M.select(rows, buyer=b, specificity=s))[0]:.1%}"
                                            for s in ("precise", "loose", "underspecified")) + " |")
    out.append("\nScripted buyers read only a stated budget from natural language, so the loose/underspecified "
               "columns overstate the effect for real (LLM) buyers.\n")

    for b in buyers:
        rs = M.select(rows, buyer=b)
        if not cfgs or not any("verdicts" in r for r in rs):
            continue
        out.append(f"## IntentCheck on `{b}` purchases\n")
        out.append("| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) "
                   "| false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |")
        out.append("|---|---|---|---|---|---|---|---|")
        for c in cfgs:
            fb, fs = M.false_flag_rates(rs, c)
            _, fs_adv = M.false_flag_rates(rs, c, adversarial=True)
            _, fs_hon = M.false_flag_rates(rs, c, adversarial=False)
            lat = M.latency(rs, c)
            out.append(f"| {c} | {pct(M.catch_rate(rs, c))} | {pct(fb)} | {pct(fs)} | {pct(fs_adv)} | "
                       f"{pct(fs_hon)} | {lat['compute_p50']:.2f} / {lat['compute_p95']:.2f} | "
                       f"{lat['net_p50']:.0f} |")
        lp = M.limit_pass_rate(rs)
        out.append(f"\nViolations that pass a per-transaction spend limit set to the user's budget "
                   f"(UPI Reserve Pay style): **{pct(lp)}**.\n")
    return "\n".join(out)
