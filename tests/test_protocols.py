import json
import time

import pytest

from dia.ap2 import adapter
from dia.ap2.models import PaymentMandate
from dia.ap2.signing import KeyDirectory, SignatureError, SigningKey
from dia.arena.catalogue import build_catalogue
from dia.arena.scenario import generate
from dia.buyers.base import BuyerResult, claimed_from_cart
from dia.buyers.scripted import NaiveBuyer, OracleBuyer
from dia.cli import main
from dia.eval.judge import judge_result
from dia.intentcheck.verifier import IntentCheck
from dia import x402


@pytest.fixture(scope="module")
def world():
    cat = build_catalogue(7)
    return cat, generate(cat, n=400, seed=11)


def an_oracle_cart(world, i=None):
    cat, scs = world
    i = next(k for k, s in enumerate(scs) if not s.abstain_case) if i is None else i
    sc = scs[i]
    res = OracleBuyer().run(sc.mandate, True, sc.market.session("o", i))
    return sc, res, i


def a_violation(world, profile="bait_and_switch"):
    cat, scs = world
    for i, sc in enumerate(scs):
        if sc.spotlight != profile or not sc.buyer_sees_constraints:
            continue
        res = NaiveBuyer().run(sc.mandate, True, sc.market.session("n", i))
        if res.cart and judge_result(sc, res).violation and \
                cat.sellers[res.cart.contents.x_line.seller_id].profile == profile:
            return sc, res, i
    raise AssertionError("no violating case found")


# ------------------------------------------------------------------ AP2 adapter

def test_exported_cart_uses_only_ap2_fields_and_verifies(world):
    sc, res, _ = an_oracle_cart(world)
    key = sc.market.keyring.keys[res.cart.contents.x_line.seller_id]
    d = adapter.export_cart(res.cart, key)
    assert adapter.conformance_errors("CartMandate", d) == []
    adapter.verify_exported_cart(d, sc.market.keyring.directory)
    d["contents"]["payment_request"]["details"]["total"]["amount"]["value"] -= 100
    with pytest.raises(SignatureError, match="cart_hash"):
        adapter.verify_exported_cart(d, sc.market.keyring.directory)


def test_our_native_cart_is_not_plain_ap2_and_the_gap_is_the_sku(world):
    sc, res, _ = an_oracle_cart(world)
    native = res.cart.model_dump(mode="json")
    errs = adapter.conformance_errors("CartMandate", native)
    assert any("x_line" in e for e in errs)                                   # our extension is flagged
    exported = adapter.export_cart(res.cart, sc.market.keyring.keys[res.cart.contents.x_line.seller_id])

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert not {"sku", "delivery_days", "returnable", "x_line"} & set(keys(exported["contents"]))


def test_exported_intent_and_payment_conform(world):
    sc, res, _ = an_oracle_cart(world)
    assert adapter.conformance_errors("IntentMandate", adapter.export_intent(sc.mandate)) == []
    assert "x_constraints" not in adapter.export_intent(sc.mandate)
    pm = PaymentMandate.for_cart(res.cart, SigningKey.generate("user"))
    assert adapter.conformance_errors("PaymentMandate", adapter.export_payment(pm)) == []


def test_conformance_checker_detects_problems():
    assert adapter.conformance_errors("PaymentCurrencyAmount", {"currency": "INR"}) == \
        ["PaymentCurrencyAmount: missing required field 'value'"]
    assert any("not an AP2 field" in e for e in
               adapter.conformance_errors("PaymentCurrencyAmount", {"currency": "INR", "value": 1, "x_y": 2}))
    nested = {"contents": {"id": "c", "user_cart_confirmation_required": False, "cart_expiry": "t",
                           "merchant_name": "m", "payment_request": {"method_data": [{"nope": 1}],
                                                                       "details": {"id": "i"}}}}
    errs = adapter.conformance_errors("CartMandate", nested)
    assert any("method_data[0]" in e and "supported_methods" in e for e in errs)
    assert any("details" in e and "display_items" in e for e in errs)


def test_manifest_covers_every_child_reference():
    for (parent, _), child in {**adapter._CHILD, **adapter._LIST_CHILD}.items():
        assert parent in adapter._MODELS and child in adapter._MODELS


# ------------------------------------------------------------------ x402

def setup_flow(world):
    sc, res, i = an_oracle_cart(world)
    user = SigningKey.from_seed("user-1", b"t")
    users = KeyDirectory()
    users.register(user)
    required = x402.payment_required(res.cart, "https://shop.example/x")
    return sc, res, i, user, users, required


def test_payment_required_shape(world):
    _, res, _, _, _, required = setup_flow(world)
    req = required["accepts"][0]
    assert required["x402Version"] == 2 and required["resource"]["url"].startswith("https://")
    assert {"scheme", "network", "amount", "asset", "payTo", "maxTimeoutSeconds"} <= set(req)
    assert req["amount"] == str(round(res.cart.contents.total * 100)) and isinstance(req["amount"], str)
    assert x402.unb64(x402.b64(required)) == required


def test_facilitator_happy_path_and_replay(world):
    _, _, _, user, users, required = setup_flow(world)
    req = required["accepts"][0]
    fac = x402.LocalFacilitator(users)
    payload = x402.build_payment(user, req, required["resource"])
    assert fac.verify(payload, req) == {"isValid": True, "payer": "user-1"}
    s = fac.settle(payload, req)
    assert s["success"] and s["transaction"].startswith("0x") and s["amount"] == req["amount"]
    assert fac.verify(payload, req) == {"isValid": False, "invalidReason": "nonce_reused"}
    assert fac.settle(payload, req)["success"] is False


def test_facilitator_rejects_tampering(world):
    _, _, _, user, users, required = setup_flow(world)
    req = required["accepts"][0]
    fac = x402.LocalFacilitator(users)
    good = lambda: x402.build_payment(user, req, required["resource"])
    p = good(); p["accepted"]["amount"] = "1"
    assert fac.verify(p, req)["invalidReason"] == "requirements_mismatch:amount"
    p = good(); p["accepted"]["extra"] = {"cartHash": "other"}
    assert fac.verify(p, req)["invalidReason"] == "signature_does_not_bind_payload"
    p = good(); p["payload"]["authorization"]["to"] = "attacker"
    assert fac.verify(p, req)["invalidReason"] in ("signature_does_not_bind_payload", "authorization_mismatch")
    p = good(); p["x402Version"] = 1
    assert fac.verify(p, req)["invalidReason"] == "unsupported_version"
    p = good()
    assert fac.verify(p, req, now=time.time() + 10_000)["invalidReason"] == "outside_validity_window"
    stranger = SigningKey.generate("stranger")
    assert fac.verify(x402.build_payment(stranger, req, required["resource"]), req)["invalidReason"] == "invalid_signature"
    assert fac.verify({"x402Version": 2}, req)["invalidReason"] == "malformed_payload"
    wrong_req = dict(req, payTo="someone-else")
    assert fac.verify(good(), wrong_req)["invalidReason"] == "requirements_mismatch:payTo"


def test_guard_allows_good_and_blocks_bad_where_facilitator_cannot(world):
    cat, scs = world
    # good purchase: guard allows, facilitator settles
    sc, res, i, user, users, required = setup_flow(world)
    guard = x402.IntentGuard(IntentCheck(sc.market.keyring.directory), user)
    out = guard.pay(required, res.cart, sc.mandate, res, sc.market.session("ic", 1))
    assert out.decision == "allow" and out.header
    fac = x402.LocalFacilitator(users)
    assert fac.settle(x402.unb64(out.header), required["accepts"][0])["success"]

    # bad purchase: every signature valid, the facilitator WOULD settle, the guard refuses
    sc, res, i = a_violation(world, "bait_and_switch")
    required = x402.payment_required(res.cart, "https://shop.example/y")
    guard = x402.IntentGuard(IntentCheck(sc.market.keyring.directory), user)
    out = guard.pay(required, res.cart, sc.mandate, res, sc.market.session("ic", 10_000 + i))
    assert out.decision == "block" and out.header is None and out.verdict is not None
    unguarded = x402.LocalFacilitator(users).settle(x402.unb64(x402.unguarded_payment(user, required)),
                                                    required["accepts"][0])
    assert unguarded["success"] is True


def test_guard_step_up_needs_the_human(world):
    sc, res, i = a_violation(world, "injection")
    user = SigningKey.from_seed("user-1", b"t")
    required = x402.payment_required(res.cart, "https://shop.example/z")
    ic = IntentCheck(sc.market.keyring.directory)
    verdict = ic.check(sc.mandate, res.cart, res, sc.market.session("ic", 10_000 + i))
    if verdict.decision != "step_up":
        pytest.skip("this case resolved to a block, not a step-up")
    no = x402.IntentGuard(ic, user).pay(required, res.cart, sc.mandate, res, sc.market.session("ic", 10_000 + i))
    assert no.decision == "step_up" and no.header is None
    asked = []
    yes = x402.IntentGuard(ic, user, confirm=lambda v: asked.append(v) or True)
    out = yes.pay(required, res.cart, sc.mandate, res, sc.market.session("ic", 10_000 + i))
    assert asked and out.decision == "allow" and out.header
    refuse = x402.IntentGuard(ic, user, confirm=lambda v: False)
    assert refuse.pay(required, res.cart, sc.mandate, res, sc.market.session("ic", 10_000 + i)).header is None


def test_guard_blocks_a_requirement_for_a_different_cart(world):
    """A hijacked / swapped 402 (different cart, or a different amount) is caught before anything is signed."""
    sc, res, i, user, users, required = setup_flow(world)
    guard = x402.IntentGuard(IntentCheck(sc.market.keyring.directory), user)
    other_sc, other_res, _ = a_violation(world, "dark_pattern")
    swapped = x402.payment_required(other_res.cart, "https://shop.example/evil")
    out = guard.pay(swapped, res.cart, sc.mandate, res, sc.market.session("ic", 3))
    assert out.decision == "block" and "not for the cart" in out.reason
    inflated = json.loads(json.dumps(required))
    inflated["accepts"][0]["amount"] = str(int(inflated["accepts"][0]["amount"]) + 50_000)
    out = guard.pay(inflated, res.cart, sc.mandate, res, sc.market.session("ic", 4))
    assert out.decision == "block" and "amount differs" in out.reason


def test_x402_cli_demo(capsys):
    main(["x402", "--profile", "bait_and_switch"])
    out = capsys.readouterr().out
    assert "HTTP 402" in out and "GUARD" in out and "WITHOUT THE GUARD" in out and "success=True" in out
