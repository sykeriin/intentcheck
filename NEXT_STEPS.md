# Next steps

Written 3 Nov 2026. State of the project: the arena, the verifier, the confirmatory analysis, the LLM adapter, the
India variant, the typed-only buyer, the AP2 export and the x402 simulation are built and tested offline
(`python -m pytest -q`). **No real LLM has been run.** Everything below is what stands between this repo and a result.

Work through A, then B, in order. C and D can run in parallel with B.

---

## A. Decisions only you can make (this week)

1. **License.** The repo has none yet, so by default nobody may reuse it. The plan assumed Apache-2.0, which matches
   AP2 (whose field names the models mirror). Add `LICENSE` (and a short `NOTICE` crediting AP2's schemas) or choose
   another; I did not choose for you.
2. **Visibility.** Check whether `sykeriin/intentcheck` is public or private. Keep it private until step 3 is done.
3. **Freeze the pre-registration.** Read [PREREG.md](PREREG.md) §6 and §2. The rule most worth challenging is C4(b),
   the *strict* false step-up criterion, which I chose after seeing the dev data. If you accept it:
   ```bash
   git tag -a prereg-v1 -m "pre-registration frozen before any llm-test run"
   git push origin prereg-v1
   ```
   After the tag, the body of PREREG.md is never edited, only the *Amendments* section (§11).
4. **Budget and models.** Decide how much you will spend and which models. See B.

## B. Needs model access (target: keys by 23 Nov)

Minimum credible set from the plan: two LLM buyers (one open model, one cheap API model), plus the typed-only
`camel:` variant on the same open model, on the 300-scenario `llm-test` split.

Rough size: 300 scenarios x about 40-70k input tokens each is 12-21M input tokens per model, more for the repeat
subset. Check current prices and free tiers yourself; I could not verify them. Every run below takes a hard
`--token-budget`.

**Order matters:**

1. **Live smoke test on the dev split** (the live providers have never run against a real API):
   ```bash
   export OPENAI_API_KEY=... OPENAI_BASE_URL=https://.../v1     # any OpenAI-compatible endpoint
   scripts/smoke_live.sh llm:openai:<model> 300000
   # or: export ANTHROPIC_API_KEY=... ; pip install -e '.[llm]' ; scripts/smoke_live.sh llm:anthropic:<model>
   ```
   Open `results/smoke.jsonl` and the transcripts. Any `error` / `incomplete` row is a harness or provider bug.
   Fix it now: fixes made before the first `llm-test` run are legitimate; later ones need an amendment.
2. **Amendment A1** (PREREG.md §11), before the first `llm-test` run. Template:
   ```markdown
   ### A1 (YYYY-MM-DD): models, budgets, dates
   | Buyer spec | Model id (exact) | Provider / endpoint | Temperature | Token budget | Planned run date |
   |---|---|---|---|---|---|
   | llm:<provider>:<model> | ... | ... | 0 (or "API default", say which) | ... | ... |
   | camel:<provider>:<model> | ... | ... | ... | ... | ... |
   Smoke-test findings and code fixes since prereg-v1: ... (commit hashes)
   ```
   Commit and push it before the run.
3. **Optional, before the main run: paraphrase cache** (a threat-to-validity mitigation, needs a live model):
   ```bash
   python -m dia.cli paraphrase --provider openai:<model> --split llm-test --mode strict --out data/paraphrase_strict.json
   ```
   Decide before looking at any result whether the main run uses it, and record that in A1. Report `free` mode
   (which can drop the exact trigger phrases) separately, never mixed with `strict`.
4. **The registered run** (once, on `llm-test`; never tune on it):
   ```bash
   python -m dia.cli run --split llm-test \
     --buyers oracle,naive,cautious,llm:<provider>:<model>,camel:<provider>:<model> \
     --configs full,no_rederivation,no_counterfactual,no_taint,hard_only,limit_only,full_partial_view \
     --token-budget <N> --transcripts transcripts/ --out results/llm_test.jsonl
   python -m dia.cli confirm results/llm_test.jsonl        # C1-C5 verdicts exactly as registered
   ```
   Infrastructure failures (HTTP 5xx, timeouts) are re-run once; agent-caused incompleteness never is (PREREG §5).
5. **Variance subset:** the first 100 scenarios, repeats 0, 1, 2: `--n 100 --repeat 1` (and `--repeat 2`).
6. **India run with the same models** (exploratory, uses the dev-style India split): `--split india-dev --n 300`.

## C. Reading and verification (do not skip; this is what makes the claims safe)

- **Three brief citations were never opened:** arXiv 2604.15367, 2604.03733, 2605.30998. Read them and check that
  what [docs/WRITEUP.md](docs/WRITEUP.md) says about each is true.
- **AIP-Bench (2607.21824):** I only read the abstract. Read the paper and check the claim that it does not measure
  decision quality or intent binding. If it does, the novelty statement changes.
- **Novelty re-check** in weeks 5 and 9 (mid-Dec, early Jan): search for new work on agent-payment verification.
  The field moves monthly.
- **Re-verify the AP2 manifest** (`src/dia/ap2/ap2_manifest.json`) and the x402 header names against the live specs;
  both were transcribed on 3 Nov 2026 from pages that were only partly readable.
- **India:** confirm current UPI Reserve Pay mechanics (the per-transaction limit assumption in
  `IntentConstraints.per_txn_limit`) against Razorpay / NPCI sources before quoting the Reserve Pay numbers.

## D. Engineering backlog (not blocked on keys)

In rough value order:

1. Full CaMeL-style planner (a capability interpreter), if you want to claim a real CaMeL baseline. Today's
   `camel:` buyer is typed-fields-only and is named "CaMeL-inspired" everywhere.
2. x402 testnet flow with a funded wallet and a real facilitator (the current flow is a local simulation).
3. Real AP2 SDK round trip (clone upstream into its own directory, treat as untrusted, validate exported mandates
   with its models).
4. Quick-commerce item substitution with per-unit pricing (planned, not built; see PLAN.md §18).
5. Adaptive sellers (prompt-optimise a listing against a fixed buyer) and the tacit-collusion study.
6. Public leaderboard page; a 2-minute demo GIF (`dia demo`, `dia x402`).
7. Reduce the verifier's simulated network time (about 5 s p50 on dev): shorter timeout, cached market view, or
   asynchronous search. The < 1 s target failed.

## E. Write-up and outreach (after results)

1. Fill the TBD sections of [docs/WRITEUP.md](docs/WRITEUP.md) from `dia confirm` and the reports. Report C1-C5
   verdicts as registered, including *inconclusive* ones, and the all-purchases false step-up next to the strict one.
2. Target: workshop or arXiv, 6-10 pages. Frame it as benchmark + trust-boundary design + measurements, not as a new
   algorithm.
3. Outreach only after you have numbers: Razorpay agentic-payments engineers (through LinkedIn rather than the CEO),
   NPCI, Juspay, Cashfree, Pine Labs, and the authors of the papers in the brief.

## F. Things that will bite you

- The live providers are untested. Expect a bug on the first call (tool-argument formats, temperature support on
  some models, rate limits).
- Frozen tests hash scenarios built with Python's `random`. Use Python 3.13 (CI is pinned to it); other minor
  versions may change the hashes without any code change.
- Do not run, look at, or tune against `llm-test` before the registered run. Debug on `dev`.
- Abstaining buyers look safe: always read the purchase rate beside the violation rate.
- Scripted-buyer numbers in the repo are harness checks, not findings about real agents.
- With about 52 clean and 118 attack precise scenarios, intervals are wide. A rule can come out inconclusive; that
  is an honest result.

## G. Done means

- [ ] LICENSE decided; `prereg-v1` tagged; A1 committed before the run
- [ ] Smoke test clean; registered run complete; `dia confirm` output committed under `reports/`
- [ ] Three unread papers and AIP-Bench read; citations verified
- [ ] Write-up complete with limitations; repo public
- [ ] Demo GIF and one-page explainer; outreach list ready
