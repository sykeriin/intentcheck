"""Export our mandates in AP2's wire shape, and check that shape against a hand-transcribed field manifest.

What this does and does not show:
  - Our models mirror AP2's field names, plus `x_` extensions. Export strips every `x_` field and re-signs, so the
    result is what a stock AP2 participant would see. The merchant JWT is re-issued over the STRIPPED contents
    (AP2's cart_hash covers the canonical JSON of CartContents), using EdDSA rather than the RS256 in AP2's
    example docstring. A stock AP2 verifier that insists on RS256 would reject it; the signature property
    (issuer authenticity + content integrity) is the same.
  - It makes one limitation concrete: after stripping `x_line` the cart no longer carries a structured SKU,
    delivery estimate or returnability. That is precisely the information IntentCheck needs, which is why this
    project proposes the extension rather than reading display labels.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import CartMandate, IntentMandate, PaymentMandate
from .signing import KeyDirectory, SignatureError, SigningKey, sha256_hex

MANIFEST = json.loads((Path(__file__).parent / "ap2_manifest.json").read_text())
_MODELS = {k: v for k, v in MANIFEST.items() if not k.startswith("_")}


def strip_extensions(obj: Any) -> Any:
    """Drop every `x_*` key, recursively."""
    if isinstance(obj, dict):
        return {k: strip_extensions(v) for k, v in obj.items() if not k.startswith("x_")}
    if isinstance(obj, list):
        return [strip_extensions(v) for v in obj]
    return obj


def export_intent(m: IntentMandate) -> dict:
    return strip_extensions(m.model_dump(mode="json"))


def export_cart(cart: CartMandate, key: SigningKey, now: datetime | None = None, ttl_s: int = 900) -> dict:
    """AP2-shaped CartMandate, merchant-signed over the contents WITHOUT our extensions."""
    contents = strip_extensions(cart.contents.model_dump(mode="json"))
    iat = int((now or datetime.now(UTC)).timestamp())
    token = key.sign({"iss": key.kid, "sub": key.kid, "aud": "payment-processor", "iat": iat, "exp": iat + ttl_s,
                      "jti": uuid.uuid4().hex, "cart_hash": sha256_hex(contents)})
    return {"contents": contents, "merchant_authorization": token}


def verify_exported_cart(d: dict, directory: KeyDirectory, now: float | None = None) -> dict:
    """What a stock verifier does: signature, expiry, and cart_hash over the contents it received."""
    payload = directory.verify(d["merchant_authorization"])
    if payload["cart_hash"] != sha256_hex(d["contents"]):
        raise SignatureError("cart_hash mismatch")
    if payload.get("exp", float("inf")) < (now if now is not None else time.time()):
        raise SignatureError("merchant authorization expired")
    return payload


def export_payment(pm: PaymentMandate) -> dict:
    return strip_extensions(pm.model_dump(mode="json"))


# ----------------------------------------------------------------------------- conformance

# which nested key holds which AP2 model, for recursive checking
_CHILD = {
    ("CartMandate", "contents"): "CartContents",
    ("CartContents", "payment_request"): "PaymentRequest",
    ("PaymentRequest", "details"): "PaymentDetailsInit",
    ("PaymentDetailsInit", "total"): "PaymentItem",
    ("PaymentItem", "amount"): "PaymentCurrencyAmount",
    ("PaymentMandate", "payment_mandate_contents"): "PaymentMandateContents",
    ("PaymentMandateContents", "payment_details_total"): "PaymentItem",
    ("PaymentMandateContents", "payment_response"): "PaymentResponse",
}
_LIST_CHILD = {
    ("PaymentRequest", "method_data"): "PaymentMethodData",
    ("PaymentDetailsInit", "display_items"): "PaymentItem",
}


def conformance_errors(model: str, d: dict, path: str = "") -> list[str]:
    """Empty list = the dict uses only AP2 field names and has every AP2-required field."""
    spec = _MODELS[model]
    allowed = set(spec["required"]) | set(spec["optional"])
    errs = [f"{path or model}: missing required field {k!r}" for k in spec["required"] if k not in d]
    errs += [f"{path or model}: field {k!r} is not an AP2 field" for k in d if k not in allowed]
    for k, v in d.items():
        if v is None:
            continue
        if (model, k) in _CHILD and isinstance(v, dict):
            errs += conformance_errors(_CHILD[(model, k)], v, f"{path or model}.{k}")
        if (model, k) in _LIST_CHILD and isinstance(v, list):
            for i, item in enumerate(v):
                errs += conformance_errors(_LIST_CHILD[(model, k)], item, f"{path or model}.{k}[{i}]")
    return errs
