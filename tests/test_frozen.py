"""Guards for what PREREG.md freezes. If one of these fails, an 'opt-in' feature has leaked into default behaviour
(or the arena was changed on purpose, in which case PREREG.md needs a dated amendment and these hashes a new value)."""

import hashlib
import json

import pytest

from dia.arena.catalogue import build_catalogue
from dia.arena.scenario import generate
from dia.eval.run import SPLITS, run

CATALOGUE = "760e988183a6015257d93bbc43a474e386c52f459c351010f6c62614dcb56617"
DEV = "6675b7d26255f99cc6aa1086469210bd2aba815e97651dc54b885cf292d9089a"
LLM_TEST = "ce34972283814fa4e815c794bf00cb060e9b22043f7c9814f5109e6f3bb704e2"
RESULTS_DEV_100 = "9afa33f263c7cb84d68b463c37131c17f0435184a04888275cdeb9bcc721235c"
PROMPT = "bd93407af3fa22e53fe84fc7697a584f1fe33d73f1062f915c0706931acc1118"


def h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def sc_key(s):
    c = s.constraints
    return [s.sid, s.spotlight, s.specificity, s.abstain_case, s.mandate.natural_language_description,
            list(s.market.offer_ids), c.budget_total, c.deadline_days, c.weights,
            [r.describe() for r in c.must_have], c.requires_refundability]


@pytest.fixture(scope="module")
def cat():
    return build_catalogue(7)


def test_catalogue_is_frozen(cat):
    assert h([[o.offer_id, o.seller_id, o.quoted.sku, o.quoted.price, o.quoted.fees, o.quoted.shipping,
               o.quoted.delivery_days, o.quoted.returnable,
               (o.checkout.sku, o.checkout.price, o.checkout.fees, o.checkout.shipping, o.checkout.delivery_days)
               if o.checkout else None] for o in cat.offers.values()]) == CATALOGUE


@pytest.mark.parametrize("name,expected", [("dev", DEV), ("llm-test", LLM_TEST)])
def test_splits_are_frozen(cat, name, expected):
    sp = dict(SPLITS[name])
    n, seed = sp.pop("n"), sp.pop("seed")
    assert h([sc_key(s) for s in generate(cat, n=n, seed=seed, **sp)]) == expected


def test_scripted_results_are_frozen():
    rows = run(["oracle", "naive", "cautious"], ["full", "hard_only", "limit_only"], n=100, seed=1)
    strip = [[r["sid"], r["buyer"], r["bought"], r["violation"], r["hard_violation"], r["reasons"], r.get("total"),
              {k: v["decision"] for k, v in r.get("verdicts", {}).items()}] for r in rows]
    assert h(strip) == RESULTS_DEV_100


def test_baseline_prompt_is_frozen():
    from dia.buyers.llm import prompt_fingerprint
    assert prompt_fingerprint() == PROMPT
