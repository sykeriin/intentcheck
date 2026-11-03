# MarketArena + IntentCheck

Decision-integrity verification for agent payments (AP2 / x402 / UPI Reserve Pay).
Full plan: [PLAN.md](PLAN.md). Pre-registration: [PREREG.md](PREREG.md) (DRAFT until tagged `prereg-v1`).
Status: steps 1-6 done; the LLM-buyer adapter (step 7) is built and tested offline with a stand-in policy.
No real LLM has been run, so **no result here is evidence about real agents**.

```bash
pip install -e '.[dev]'
python -m pytest -q                                   # 88 tests
python -m dia.cli run --n 1000 --seed 1               # scripted buyers x 7 verifier configs -> results/run.jsonl + report
python -m dia.cli demo --profile bait_and_switch      # one end-to-end case, with and without IntentCheck
python -m dia.cli run --split llm-test --buyers llm:dry --n 30   # exercise the LLM tool loop with no model or key
python -m dia.cli confirm results/run.jsonl           # confirmatory C1-C5 from PREREG.md
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

LLM buyers (`llm:anthropic:<model>`, `llm:openai:<model>` for any OpenAI-compatible endpoint, `llm:replay:<dir>`,
`llm:dry`) need `--token-budget` for any real model. The live providers have not been run against a real API yet.
