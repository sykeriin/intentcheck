"""AP2-shaped mandates.

Field names on IntentMandate / CartContents / CartMandate / PaymentMandateContents
/ PaymentMandate mirror google-agentic-commerce/AP2 `code/sdk/python/ap2/models/mandate.py`
(Apache-2.0). The W3C PaymentRequest is reduced to the fields we need.

Fields prefixed `x_` are OUR extensions, not part of AP2:
  - IntentMandate.x_constraints: structured, user-confirmed constraints. AP2 carries
    intent only as natural language, which is exactly why semantic fit is unchecked.
  - CartContents.x_line: structured line item (offer, SKU, delivery). AP2 carts carry
    only display labels + amounts; a verifier needs the SKU to re-derive properties.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .signing import KeyDirectory, SigningKey, sha256_hex


# --- W3C PaymentRequest (reduced) -------------------------------------------------

class PaymentCurrencyAmount(BaseModel):
    currency: str
    value: float


class PaymentItem(BaseModel):
    label: str
    amount: PaymentCurrencyAmount
    refund_period: int = 30


class PaymentDetailsInit(BaseModel):
    id: str
    display_items: list[PaymentItem]
    total: PaymentItem


class PaymentMethodData(BaseModel):
    supported_methods: str
    data: dict = Field(default_factory=dict)


class PaymentRequest(BaseModel):
    method_data: list[PaymentMethodData]
    details: PaymentDetailsInit


class PaymentResponse(BaseModel):
    request_id: str
    method_name: str
    details: dict = Field(default_factory=dict)


# --- Extensions -------------------------------------------------------------------

class SpecRequirement(BaseModel):
    key: str
    op: Literal["eq", "gte", "lte"]
    value: bool | int | float | str

    def satisfied_by(self, specs: dict) -> bool:
        if self.key not in specs:
            return False
        v = specs[self.key]
        if self.op == "eq":
            return v == self.value
        if self.op == "gte":
            return v >= self.value
        return v <= self.value

    def describe(self) -> str:
        sym = {"eq": "=", "gte": ">=", "lte": "<="}[self.op]
        return f"{self.key} {sym} {self.value}"


class IntentConstraints(BaseModel):
    """User-confirmed structured constraints (extension). Hard + soft."""

    category: str
    currency: str = "INR"
    budget_total: float = Field(..., description="Max total incl. fees and shipping.")
    deadline_days: int = Field(..., description="Must be delivered within N days.")
    must_have: list[SpecRequirement] = Field(default_factory=list)
    requires_refundability: bool = False
    cod_required: bool = False            # India variant: cash on delivery must be available
    min_return_window_days: int = 0       # India variant: minimum return window
    # Soft preferences: weights over (cost, delivery, rating, quality); sum to 1.
    weights: dict[str, float] = Field(
        default_factory=lambda: {"cost": 0.4, "delivery": 0.2, "rating": 0.2, "quality": 0.2}
    )
    # India / UPI Reserve Pay: the per-transaction limit the user set on the mandate.
    per_txn_limit: float | None = None


# --- AP2 mandates -------------------------------------------------------------------

class IntentMandate(BaseModel):
    user_cart_confirmation_required: bool = True
    natural_language_description: str
    merchants: list[str] | None = None
    skus: list[str] | None = None
    requires_refundability: bool | None = False
    intent_expiry: str
    x_constraints: IntentConstraints | None = None


class CartLine(BaseModel):
    offer_id: str
    seller_id: str
    sku: str
    delivery_days: int
    returnable: bool
    cod: bool = True
    return_window_days: int | None = None


class CartContents(BaseModel):
    id: str
    user_cart_confirmation_required: bool
    payment_request: PaymentRequest
    cart_expiry: str
    merchant_name: str
    x_line: CartLine

    @property
    def total(self) -> float:
        return self.payment_request.details.total.amount.value

    @property
    def currency(self) -> str:
        return self.payment_request.details.total.amount.currency


class CartMandate(BaseModel):
    contents: CartContents
    merchant_authorization: str | None = None

    def content_hash(self) -> str:
        return sha256_hex(self.contents.model_dump(mode="json"))

    def sign(self, key: SigningKey, now: datetime | None = None) -> "CartMandate":
        now = now or datetime.now(UTC)
        payload = {
            "iss": key.kid,
            "aud": "payment-processor",
            "iat": int(now.timestamp()),
            "jti": uuid.uuid4().hex,
            "cart_hash": self.content_hash(),
        }
        self.merchant_authorization = key.sign(payload)
        return self

    def verify(self, directory: KeyDirectory) -> dict:
        """Returns the verified JWT payload; raises SignatureError on failure."""
        from .signing import SignatureError

        if not self.merchant_authorization:
            raise SignatureError("cart is unsigned")
        payload = directory.verify(self.merchant_authorization)
        if payload["cart_hash"] != self.content_hash():
            raise SignatureError("cart_hash mismatch: contents altered after signing")
        if payload["_kid"] != self.contents.x_line.seller_id:
            raise SignatureError("cart signed by a key that is not the selling merchant")
        return payload


class PaymentMandateContents(BaseModel):
    payment_mandate_id: str
    payment_details_id: str
    payment_details_total: PaymentItem
    payment_response: PaymentResponse
    merchant_agent: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PaymentMandate(BaseModel):
    payment_mandate_contents: PaymentMandateContents
    user_authorization: str | None = None

    @classmethod
    def for_cart(cls, cart: CartMandate, user_key: SigningKey) -> "PaymentMandate":
        c = cart.contents
        pmc = PaymentMandateContents(
            payment_mandate_id=uuid.uuid4().hex,
            payment_details_id=c.payment_request.details.id,
            payment_details_total=c.payment_request.details.total,
            payment_response=PaymentResponse(request_id=c.payment_request.details.id, method_name="upi-reserve-pay"),
            merchant_agent=c.merchant_name,
        )
        pm = cls(payment_mandate_contents=pmc)
        pm.user_authorization = user_key.sign(
            {
                "aud": c.merchant_name,
                "nonce": uuid.uuid4().hex,
                "transaction_data": [cart.content_hash(), sha256_hex(pmc.model_dump(mode="json"))],
            }
        )
        return pm
