"""x402 (v2) message flow with IntentCheck as a client-side guard. LOCAL SIMULATION, not a testnet run.

Message shapes follow coinbase/x402 `specs/x402-specification-v2.md` as read on 2026-11-03:
  PaymentRequired {x402Version: 2, resource{url,...}, accepts[PaymentRequirements]}   (header PAYMENT-REQUIRED)
  PaymentRequirements {scheme, network, amount (atomic units, string), asset, payTo, maxTimeoutSeconds, extra}
  PaymentPayload {x402Version, resource, accepted, payload{signature, authorization{from,to,value,validAfter,
                  validBefore,nonce}}}                                                  (header PAYMENT-SIGNATURE)
  facilitator POST /verify -> {isValid, invalidReason, payer}
  facilitator POST /settle -> {success, errorReason, payer, transaction, network, amount}
Header names for the payload and the settlement response were only partly specified in the text I could read
(PAYMENT-SIGNATURE appears in an example; PAYMENT-RESPONSE was named on the repo page). Verify against the live
spec before relying on them.

What is NOT real here: there is no chain. `asset` is the ISO 4217 code INR (the spec allows a fiat code), `amount` is
in paise, the network is the placeholder "mock:upi" (not a registered CAIP-2 chain), and the payment signature is our
Ed25519 token rather than an EIP-3009 authorization. The structure and the checks are faithful; settlement is not.
Where IntentCheck sits is the point: between "the agent has a 402 for the cart it chose" and "the client signs".
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .ap2.models import CartMandate, IntentMandate
from .ap2.signing import KeyDirectory, SignatureError, SigningKey, canonical_json
from .arena.market import MarketSession
from .buyers.base import BuyerResult
from .intentcheck.verifier import IntentCheck, Verdict

X402_VERSION = 2
HDR_REQUIRED, HDR_PAYMENT, HDR_RESPONSE = "PAYMENT-REQUIRED", "PAYMENT-SIGNATURE", "PAYMENT-RESPONSE"
NETWORK, ASSET, SCHEME = "mock:upi", "INR", "exact"


def b64(obj) -> str:
    return base64.b64encode(canonical_json(obj)).decode()


def unb64(s: str):
    return json.loads(base64.b64decode(s))


def paise(amount_inr: float) -> str:
    return str(round(amount_inr * 100))


def payment_required(cart: CartMandate, resource_url: str) -> dict:
    """What a merchant's server answers with (HTTP 402) for the cart it signed."""
    c = cart.contents
    return {
        "x402Version": X402_VERSION,
        "resource": {"url": resource_url, "description": f"{c.merchant_name}: cart {c.id}",
                     "mimeType": "application/json"},
        "accepts": [{"scheme": SCHEME, "network": NETWORK, "amount": paise(c.total), "asset": ASSET,
                     "payTo": c.x_line.seller_id, "maxTimeoutSeconds": 300,
                     "extra": {"cartHash": cart.content_hash(), "unit": "paise"}}],
    }


def build_payment(user_key: SigningKey, req: dict, resource: dict, now: float | None = None) -> dict:
    now = int(now if now is not None else time.time())
    req = json.loads(json.dumps(req))   # copy: the payload must not alias (and so cannot silently alter) the requirements
    auth = {"from": user_key.kid, "to": req["payTo"], "value": req["amount"], "validAfter": now - 1,
            "validBefore": now + int(req["maxTimeoutSeconds"]), "nonce": uuid.uuid4().hex}
    return {"x402Version": X402_VERSION, "resource": resource, "accepted": req,
            "payload": {"signature": user_key.sign({"authorization": auth, "accepted": req}), "authorization": auth}}


class LocalFacilitator:
    """Verifies and 'settles' payloads. It checks EXECUTION integrity only: signature, binding, amount, window,
    replay. Everything it checks can pass while the agent bought the wrong thing."""

    def __init__(self, users: KeyDirectory):
        self.users, self.seen_nonces, self.settled = users, set(), []

    def verify(self, payload: dict, requirements: dict, now: float | None = None) -> dict:
        bad = lambda r: {"isValid": False, "invalidReason": r}
        now = now if now is not None else time.time()
        try:
            if payload.get("x402Version") != X402_VERSION:
                return bad("unsupported_version")
            acc, pl = payload["accepted"], payload["payload"]
            for k in ("scheme", "network", "amount", "asset", "payTo"):
                if acc.get(k) != requirements.get(k):
                    return bad(f"requirements_mismatch:{k}")
            auth = pl["authorization"]
            signed = self.users.verify(pl["signature"])
            if signed.get("authorization") != auth or signed.get("accepted") != acc:
                return bad("signature_does_not_bind_payload")
            if auth["to"] != requirements["payTo"] or auth["value"] != requirements["amount"]:
                return bad("authorization_mismatch")
            if not auth["validAfter"] <= now <= auth["validBefore"]:
                return bad("outside_validity_window")
            if auth["nonce"] in self.seen_nonces:
                return bad("nonce_reused")
            return {"isValid": True, "payer": auth["from"]}
        except SignatureError:
            return bad("invalid_signature")
        except (KeyError, TypeError):
            return bad("malformed_payload")

    def settle(self, payload: dict, requirements: dict, now: float | None = None) -> dict:
        v = self.verify(payload, requirements, now)
        if not v["isValid"]:
            return {"success": False, "errorReason": v["invalidReason"], "transaction": "", "network": NETWORK}
        nonce = payload["payload"]["authorization"]["nonce"]
        self.seen_nonces.add(nonce)
        tx = "0x" + hashlib.sha256(nonce.encode()).hexdigest()
        self.settled.append((tx, requirements["amount"], requirements["payTo"]))
        return {"success": True, "payer": v["payer"], "transaction": tx, "network": NETWORK,
                "amount": requirements["amount"]}


@dataclass
class GuardOutcome:
    decision: str                 # allow | step_up | block
    reason: str
    verdict: Verdict | None = None
    header: str | None = None     # base64 PaymentPayload for the PAYMENT-SIGNATURE header, only if allowed


class IntentGuard:
    """Client-side hook: decide whether the agent's wallet may sign a 402 payment for this cart.

    Two layers: (1) x402-level binding, the requirement must be for exactly the cart the agent chose (a hijacked or
    swapped payment request is a decision-integrity failure the facilitator cannot see); (2) IntentCheck.
    `confirm` is called with the verdict on a step-up; it models asking the human. No callback means no payment.
    """

    def __init__(self, verifier: IntentCheck, user_key: SigningKey,
                 confirm: Callable[[Verdict], bool] | None = None):
        self.verifier, self.user_key, self.confirm = verifier, user_key, confirm

    def pay(self, required: dict, cart: CartMandate, mandate: IntentMandate, result: BuyerResult,
            session: MarketSession) -> GuardOutcome:
        req = required["accepts"][0]
        if req.get("extra", {}).get("cartHash") != cart.content_hash():
            return GuardOutcome("block", "the payment request is not for the cart the agent chose")
        if req["amount"] != paise(cart.contents.total):
            return GuardOutcome("block", "the payment request amount differs from the cart total")
        verdict = self.verifier.check(mandate, cart, result, session)
        if verdict.decision == "block":
            return GuardOutcome("block", verdict.explanation, verdict)
        if verdict.decision == "step_up" and not (self.confirm and self.confirm(verdict)):
            return GuardOutcome("step_up", verdict.explanation, verdict)
        return GuardOutcome("allow", verdict.explanation, verdict,
                            b64(build_payment(self.user_key, req, required["resource"])))


def unguarded_payment(user_key: SigningKey, required: dict) -> str:
    """What an agent wallet does today: sign whatever the 402 asks for."""
    return b64(build_payment(user_key, required["accepts"][0], required["resource"]))
