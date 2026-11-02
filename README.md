# MarketArena + IntentCheck

Decision-integrity verification for agent payments (AP2 / x402 / UPI Reserve Pay).
Full plan: [PLAN.md](PLAN.md). Status: steps 1-6 of the build order are done (offline, scripted buyers only).
No LLM buyer has been run yet, so **no result here is evidence about real agents**.

```bash
pip install -e '.[dev]'
python -m pytest -q                                   # 53 tests
python -m dia.cli run --n 1000 --seed 1               # scripted buyers x 7 verifier configs -> results/run.jsonl + report
python -m dia.cli demo --profile bait_and_switch      # one end-to-end case, with and without IntentCheck
```

Layout: `ap2/` AP2-mirrored mandates + Ed25519 signing + mock facilitator; `arena/` catalogue, sellers,
market API, scenario generator, ground-truth solver; `buyers/` scripted buyers; `intentcheck/` the verifier;
`eval/` runner, metrics (bootstrap CIs), report.

Design notes that matter when reading the numbers:
- Spotlight markets contain honest sellers plus **only** the profile under test, so a violation is attributable.
  (An earlier version mixed all profiles into every market and the per-profile table was confounded.)
- "Violation" = signed cart is outside the defensible (eps-Pareto) set, breaks a hard constraint, or buys when
  nothing acceptable exists. Dev split = seed 1, test split (for LLM runs) must use a different seed.
- Scripted buyers see only a stated budget in loose/underspecified intents, so those columns are inflated.
- `reports/dev_seed1_scripted.md` is the current scripted-baseline report.
