# MarketArena results (1000 scenarios, 95% bootstrap CIs)

Scripted buyers validate the harness; they are **not** evidence about real agents.

## Buyer decision integrity

| buyer | violation rate | hard violations | mean regret (utility) |
|---|---|---|---|
| oracle | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.000 [0.000, 0.000] |
| naive | 49.9% [46.5%, 52.9%] | 43.9% [40.1%, 46.8%] | 0.045 [0.038, 0.053] |
| cautious | 44.4% [41.1%, 47.2%] | 43.4% [40.1%, 46.2%] | 0.010 [0.008, 0.013] |

## Completion and cost

| buyer | purchased | abstained | incomplete | error | input tokens | output tokens |
|---|---|---|---|---|---|---|
| oracle | 1000 | 0 | 0 | 0 | 0 | 0 |
| naive | 1000 | 0 | 0 | 0 | 0 | 0 |
| cautious | 1000 | 0 | 0 | 0 | 0 | 0 |

## Violation rate by seller profile in the market (spotlight)

| buyer | none | dark_pattern | injection | bait_and_switch | colluding | flaky |
|---|---|---|---|---|---|---|
| oracle | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| naive | 43.1% | 51.6% | 54.4% | 58.5% | 42.7% | 51.3% |
| cautious | 43.1% | 46.5% | 45.0% | 42.8% | 38.0% | 51.3% |

## Violation rate by intent specificity (RQ4)

| buyer | precise (constraints visible) | loose | underspecified |
|---|---|---|---|
| oracle | 0.0% | 0.0% | 0.0% |
| naive | 16.2% | 71.5% | 81.2% |
| cautious | 2.4% | 71.3% | 83.9% |

Scripted buyers read only a stated budget from natural language, so the loose/underspecified columns overstate the effect for real (LLM) buyers.

## IntentCheck on `oracle` purchases

| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) | false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |
|---|---|---|---|---|---|---|---|
| full | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.38 / 6.29 | 5096 |
| hard_only | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.16 / 0.24 | 0 |
| limit_only | n/a | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.03 / 0.04 | 0 |

Violations that pass a per-transaction spend limit set to the user's budget (UPI Reserve Pay style): **n/a**.

## IntentCheck on `naive` purchases

| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) | false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |
|---|---|---|---|---|---|---|---|
| full | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 19.0% [15.6%, 22.7%] | 80.8% [74.0%, 88.5%] | 0.0% [0.0%, 0.0%] | 4.40 / 4.80 | 5065 |
| hard_only | 88.4% [85.7%, 90.9%] | 0.0% [0.0%, 0.0%] | 8.8% [6.4%, 11.4%] | 37.5% [28.8%, 47.1%] | 0.0% [0.0%, 0.0%] | 0.16 / 0.20 | 0 |
| limit_only | 2.4% [1.2%, 3.8%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.03 / 0.04 | 0 |

Violations that pass a per-transaction spend limit set to the user's budget (UPI Reserve Pay style): **97.6% [96.2%, 98.8%]**.

## IntentCheck on `cautious` purchases

| config | catch rate | false block | false step-up | false step-up (adversarial seller chosen) | false step-up (honest/flaky chosen) | compute p50/p95 ms | sim. network p50 ms |
|---|---|---|---|---|---|---|---|
| full | 100.0% [100.0%, 100.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 4.34 / 4.59 | 5060 |
| hard_only | 97.7% [96.4%, 99.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.16 / 0.20 | 0 |
| limit_only | 0.5% [0.0%, 1.1%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.03 / 0.04 | 0 |

Violations that pass a per-transaction spend limit set to the user's budget (UPI Reserve Pay style): **99.5% [98.9%, 100.0%]**.


[wrote 3000 rows to results/india_dev.jsonl]
