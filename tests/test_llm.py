import json

import pytest

from dia.arena.catalogue import build_catalogue
from dia.arena.scenario import generate
from dia.buyers import providers as P
from dia.buyers.llm import (SYSTEM_PROMPT, TOOLS, BudgetExceeded, DryRunProvider, LLMBuyer, TokenBudget, ToolEnv,
                            prompt_fingerprint, scenario_key, user_prompt)
from dia.buyers.providers import ProviderError, ProviderReply, ReplayProvider, ToolCall
from dia.eval import report, run as runner
from dia.eval.judge import judge_result
from dia.intentcheck.verifier import IntentCheck


@pytest.fixture(scope="module")
def world():
    cat = build_catalogue(7)
    return cat, generate(cat, n=60, seed=21)


class Script:
    """Provider that returns a fixed list of replies; counts calls."""
    name = "script"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def complete(self, system, messages, tools):
        self.calls += 1
        return self.replies.pop(0) if self.replies else ProviderReply("", [])


def call(name, i=0, **args):
    return ToolCall(f"c{i}", name, args)


# ------------------------------------------------------------------ wire formats (no network)

MSGS = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "text": "looking", "tool_calls": [{"id": "a1", "name": "search", "args": {}}]},
    {"role": "tool", "results": [{"id": "a1", "name": "search", "content": "{}"}]},
]


def test_anthropic_conversion():
    out = P.to_anthropic_messages(MSGS)
    assert out[1]["content"][0] == {"type": "text", "text": "looking"}
    assert out[1]["content"][1] == {"type": "tool_use", "id": "a1", "name": "search", "input": {}}
    assert out[2]["role"] == "user" and out[2]["content"][0]["tool_use_id"] == "a1"


def test_openai_conversion_and_parse():
    out = P.to_openai_messages("sys", MSGS)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert out[3] == {"role": "tool", "tool_call_id": "a1", "content": "{}"}
    body = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "x", "function": {"name": "buy", "arguments": "{\"offer_id\": \"o\"}"}}]}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    r = P.parse_openai_response(body)
    assert r.tool_calls[0].args == {"offer_id": "o"} and (r.input_tokens, r.output_tokens) == (7, 3)
    bad = P.parse_openai_response({"choices": [{"message": {"tool_calls": [
        {"id": "x", "function": {"name": "buy", "arguments": "{not json"}}]}}]})
    assert "_unparsed" in bad.tool_calls[0].args
    with pytest.raises(ProviderError):
        P.parse_openai_response({"error": "nope"})


def test_prompt_fingerprint_stable_and_sensitive(monkeypatch):
    a = prompt_fingerprint()
    assert a == prompt_fingerprint() and len(a) == 64
    import dia.buyers.llm as L
    monkeypatch.setattr(L, "SYSTEM_PROMPT", SYSTEM_PROMPT + " ")
    assert L.prompt_fingerprint() != a


def test_no_defensive_hints_in_baseline_prompt():
    """The baseline agent must not be warned about injections or told to distrust listings."""
    low = SYSTEM_PROMPT.lower()
    assert not any(w in low for w in ("inject", "untrusted", "ignore instructions", "suspicious", "manipulat"))
    assert {t["name"] for t in TOOLS} == {"search", "get_quote", "get_product", "seller_rating",
                                          "checkout_preview", "buy", "abstain"}


# ------------------------------------------------------------------ tool environment

def test_cannot_transact_with_unseen_offers(world):
    _, scs = world
    sc = scs[0]
    env = ToolEnv(sc.market.session("t", 0))
    for name, args in [("get_quote", {"offer_id": sc.market.offer_ids[0]}),
                       ("checkout_preview", {"offer_id": sc.market.offer_ids[0]}),
                       ("buy", {"offer_id": sc.market.offer_ids[0], "expected_total": 1,
                                "expected_delivery_days": 1, "expected_returnable": True})]:
        out = json.loads(env.execute(call(name, **args)))
        assert "error" in out and "search results" in out["error"]
    assert not env.finished


def test_tool_errors_are_returned_not_raised(world):
    _, scs = world
    env = ToolEnv(scs[0].market.session("t", 0))
    assert "error" in json.loads(env.execute(call("nope")))
    assert "error" in json.loads(env.execute(call("get_quote")))               # missing arg
    assert "error" in json.loads(env.execute(call("get_product", sku="zzz")))   # unknown sku
    assert "error" in json.loads(env.execute(ToolCall("c", "buy", {"_unparsed": "{x"})))


def test_preview_shows_hidden_fee_line_items(world):
    cat, scs = world
    sc = next(s for s in scs if s.spotlight == "dark_pattern")
    env = ToolEnv(sc.market.session("t", 0), search_timeout_ms=10_000)
    listings = json.loads(env.execute(call("search")))["results"]
    dark = next(l for l in listings if cat.sellers[l["seller_id"]].profile == "dark_pattern")
    q = json.loads(env.execute(call("get_quote", offer_id=dark["offer_id"])))
    pv = json.loads(env.execute(call("checkout_preview", offer_id=dark["offer_id"])))
    assert q["fees"] == 0 and pv["total"] > q["total"]
    assert any("fee" in i["label"].lower() for i in pv["line_items"])


def test_first_terminal_call_wins(world):
    _, scs = world
    env = ToolEnv(scs[0].market.session("t", 0), search_timeout_ms=10_000)
    oid = json.loads(env.execute(call("search")))["results"][0]["offer_id"]
    env.execute(call("abstain", reason="first"))
    env.execute(call("buy", offer_id=oid, expected_total=1, expected_delivery_days=1, expected_returnable=True))
    assert env.outcome[0] == "abstain"


def test_user_prompt_respects_constraint_visibility(world):
    _, scs = world
    m = scs[0].mandate
    assert "Requirements confirmed" in user_prompt(m, True)
    assert "Requirements confirmed" not in user_prompt(m, False)
    assert "per_txn" not in user_prompt(m, True)   # the spend limit is not leaked to the agent


# ------------------------------------------------------------------ the buyer loop

def test_dry_run_end_to_end_all_scenarios(world):
    cat, scs = world
    buyer = LLMBuyer(DryRunProvider())
    ic = IntentCheck(scs[0].market.keyring.directory)
    n_buy = 0
    for i, sc in enumerate(scs):
        res = buyer.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session("llm", i))
        assert res.status in ("ok", "abstained")
        assert res.tokens_in > 0 and res.tokens_out > 0
        j = judge_result(sc, res)
        if res.cart is not None:
            n_buy += 1
            res.cart.verify(sc.market.keyring.directory)           # a genuinely signed cart
            assert res.claimed.offer_id == res.cart.contents.x_line.offer_id
            assert res.context_untrusted                            # it read listings
            v = ic.check(sc.mandate, res.cart, res, sc.market.session("ic", 10_000 + i))
            assert v.decision in ("allow", "step_up", "block")
    assert n_buy > 40


def test_claim_comes_from_agent_args_and_untrusted_ctx_is_logged(world):
    cat, scs = world
    sc = next(s for s in scs if s.spotlight == "injection")
    s0 = sc.market.session("t", 0)
    env = ToolEnv(s0, search_timeout_ms=10_000)
    inj = next(l for l in json.loads(env.execute(call("search")))["results"]
               if cat.sellers[l["seller_id"]].profile == "injection")
    prov = Script([
        ProviderReply("", [call("search")]),
        ProviderReply("", [call("buy", offer_id=inj["offer_id"], expected_total=1.0,
                                expected_delivery_days=1, expected_returnable=True)]),
    ])
    res = LLMBuyer(prov, search_timeout_ms=10_000).run(sc.mandate, True, sc.market.session("t", 0))
    assert res.status == "ok" and res.claimed.total == 1.0           # the agent's (wrong) belief, recorded
    assert res.claimed.sku == inj["sku"]                              # sku taken from what it saw, not from args
    from dia.intentcheck import taint
    assert any(it.origin == inj["seller_id"] and "agent_instruction" in taint.scan(it.text or "")
               for it in res.context_untrusted)
    assert res.cart.contents.total > 1.0


def test_incomplete_and_nudge_paths(world):
    _, scs = world
    sc = scs[0]
    # never calls a terminal tool -> hits the turn limit
    p = Script([ProviderReply("", [call("search", i)]) for i in range(20)])
    r = LLMBuyer(p, max_turns=4).run(sc.mandate, True, sc.market.session("t", 0))
    assert r.cart is None and r.status == "incomplete" and p.calls == 4
    # answers in prose twice -> one nudge, then stops
    p = Script([ProviderReply("I think the first one."), ProviderReply("Yes, the first one.")])
    r = LLMBuyer(p).run(sc.mandate, True, sc.market.session("t", 0))
    assert r.cart is None and r.status == "incomplete" and p.calls == 2


def test_provider_error_is_an_error_row_not_a_crash(world):
    _, scs = world

    class Boom:
        name = "boom"

        def complete(self, *a):
            raise ProviderError("HTTP 500")

    r = LLMBuyer(Boom()).run(scs[0].mandate, True, scs[0].market.session("t", 0))
    assert r.status == "error" and "500" in r.rationale and r.cart is None


def test_token_budget_hard_stop(world):
    _, scs = world
    with pytest.raises(BudgetExceeded):
        LLMBuyer(DryRunProvider(), budget=TokenBudget(100)).run(scs[0].mandate, True, scs[0].market.session("t", 0))
    warnings = []
    rows = runner.run(["llm:dry"], ["full"], n=10, seed=3, token_budget=2_000, warnings=warnings)
    assert len(rows) < 10 and warnings and "token budget" in warnings[0]


def test_record_then_replay_is_exact(world, tmp_path):
    _, scs = world
    rec = LLMBuyer(DryRunProvider(), record_dir=str(tmp_path))
    first = [rec.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session("r", i))
             for i, sc in enumerate(scs[:15])]
    rdir = tmp_path / "llm_dry"
    assert len(list(rdir.glob("*.json"))) == 15
    replay = LLMBuyer(ReplayProvider(rdir))
    second = [replay.run(sc.mandate, sc.buyer_sees_constraints, sc.market.session("r", i))
              for i, sc in enumerate(scs[:15])]
    key = lambda r: (r.status, r.cart.contents.x_line.offer_id if r.cart else None,
                     r.claimed.total if r.claimed else None, r.tokens_in, r.tokens_out)
    assert [key(r) for r in first] == [key(r) for r in second]
    # a diverging run fails loudly instead of silently mixing recorded and live behaviour
    with pytest.raises(ProviderError):
        LLMBuyer(ReplayProvider(tmp_path / "missing")).run(scs[20].mandate, True, scs[20].market.session("r", 20))


def test_scenario_key_is_stable_and_distinct(world):
    _, scs = world
    k = [scenario_key(s.mandate, s.market.session("x", 0)) for s in scs]
    assert k == [scenario_key(s.mandate, s.market.session("y", 5)) for s in scs]
    assert len(set(k)) == len(k)


def test_runner_and_report_with_llm_spec(world):
    rows = runner.run(["oracle", "llm:dry"], ["full", "limit_only"], n=30, seed=4)
    assert all("status" in r for r in rows)
    md = report.render(rows)
    assert "Completion and cost" in md and "llm:dry" in md
    with pytest.raises(KeyError):
        runner.make_buyer("llm:nonsense:x")
    with pytest.raises(KeyError):
        runner.make_buyer("gpt-9000")


def test_repeat_changes_market_latency_not_scenarios():
    a = runner.run(["cautious"], ["full"], n=30, seed=4, repeat=0)
    b = runner.run(["cautious"], ["full"], n=30, seed=4, repeat=1)
    assert [r["sid"] for r in a] == [r["sid"] for r in b]
    net = lambda rows: [r["verdicts"]["full"]["net_ms"] for r in rows if "verdicts" in r]
    assert net(a) != net(b)   # different latency draws -> different simulated search times
