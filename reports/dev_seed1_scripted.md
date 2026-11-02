# MarketArena results (1000 scenarios, 95% bootstrap CIs)

Scripted buyers validate the harness; they are **not** evidence about real agents.

## Buyer decision integrity

| buyer | violation rate | hard violations | mean regret (utility) |
|---|---|---|---|
| oracle | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.000 [0.000, 0.000] |
| naive | 49.2% [46.1%, 52.2%] | 41.4% [38.3%, 44.4%] | 0.051 [0.043, 0.059] |
| cautious | 42.6% [39.4%, 45.7%] | 41.7% [38.5%, 44.7%] | 0.011 [0.008, 0.014] |

## Violation rate by seller profile in the market (spotlight)

| buyer | none | dark_pattern | injection | bait_and_switch | colluding | flaky |
|---|---|---|---|---|---|---|
| oracle | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| naive | 38.9% | 51.6% | 57.5% | 58.5% | 40.7% | 51.3% |
| cautious | 38.9% | 46.5% | 41.9% | 42.1% | 36.0% | 51.3% |

## Violation rate by intent specificity (RQ4)

| buyer | precise (constraints visible) | loose | underspecified |
|---|---|---|---|
| oracle | 0.0% | 0.0% | 0.0% |
| naive | 16.0% | 70.2% | 80.7% |
| cautious | 1.9% | 68.1% | 81.8% |

Scripted buyers read only a stated budget from natural language, so the loose/underspecified columns overstate the effect for real (LLM) buyers.

## IntentCheck on `oracle` purchases

| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) | false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |
|---|---|---|---|---|---|---|---|
| full | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.39 / 4.91 | 5096 |
| no_rederivation | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.32 / 4.80 | 5096 |
| no_counterfactual | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.27 / 4.75 | 5095 |
| no_taint | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.29 / 4.74 | 5096 |
| hard_only | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.16 / 0.19 | 0 |
| limit_only | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.03 / 0.04 | 0 |
| full_partial_view | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 2.25 / 3.25 | 3277 |

Violations that pass a per-transaction spend limit set to the user's budget (UPI Reserve Pay style): **n/a**.

## IntentCheck on `naive` purchases

| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) | false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |
|---|---|---|---|---|---|---|---|
| full | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 19.6% [16.1%, 23.4%] | 84.8% [78.1%, 91.4%] | 0.0% [0.0%, 0.0%] | 4.36 / 4.81 | 5074 |
| no_rederivation | 93.5% [91.3%, 95.5%] | 0.0% [0.0%, 0.0%] | 12.4% [9.5%, 15.5%] | 53.3% [44.8%, 62.9%] | 0.0% [0.0%, 0.0%] | 4.34 / 4.76 | 5079 |
| no_counterfactual | 97.6% [96.1%, 99.0%] | 0.0% [0.0%, 0.0%] | 19.6% [16.1%, 23.4%] | 84.8% [78.1%, 91.4%] | 0.0% [0.0%, 0.0%] | 4.26 / 4.64 | 5071 |
| no_taint | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 9.7% [7.1%, 12.6%] | 41.9% [32.4%, 51.4%] | 0.0% [0.0%, 0.0%] | 4.23 / 4.63 | 5074 |
| hard_only | 84.8% [81.7%, 87.8%] | 0.0% [0.0%, 0.0%] | 9.7% [7.1%, 12.6%] | 41.9% [32.4%, 51.4%] | 0.0% [0.0%, 0.0%] | 0.15 / 0.21 | 0 |
| limit_only | 2.6% [1.4%, 4.1%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.03 / 0.04 | 0 |
| full_partial_view | 95.7% [93.9%, 97.4%] | 0.0% [0.0%, 0.0%] | 17.7% [14.3%, 21.2%] | 76.2% [68.6%, 83.8%] | 0.0% [0.0%, 0.0%] | 1.29 / 3.30 | 1950 |

Violations that pass a per-transaction spend limit set to the user's budget (UPI Reserve Pay style): **97.4% [95.9%, 98.6%]**.

## IntentCheck on `cautious` purchases

| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) | false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |
|---|---|---|---|---|---|---|---|
| full | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.27 / 4.48 | 5067 |
| no_rederivation | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.24 / 4.46 | 5067 |
| no_counterfactual | 97.9% [96.5%, 99.1%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.19 / 4.40 | 5066 |
| no_taint | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.22 / 4.44 | 5067 |
| hard_only | 97.9% [96.5%, 99.1%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.15 / 0.19 | 0 |
| limit_only | 0.5% [0.0%, 1.2%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.03 / 0.04 | 0 |
| full_partial_view | 98.1% [96.7%, 99.3%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 1.17 / 3.01 | 1935 |

Violations that pass a per-transaction spend limit set to the user's budget (UPI Reserve Pay style): **99.5% [98.8%, 100.0%]**.


[wrote 3000 rows to results/dev.jsonl]
