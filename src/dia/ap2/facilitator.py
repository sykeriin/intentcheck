"""Mock payment facilitator: verifies the AP2 chain the way a payment processor would.

It checks EXECUTION integrity only (signatures, hash binding, amount within the user's per-transaction limit).
That is the point of the project: everything here can pass while the decision was still wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CartMandate, PaymentMandate
from .signing import KeyDirectory, SignatureError, sha256_hex


@dataclass
class Receipt:
    ok: bool
    reason: str
    amount: float = 0.0
    merchant: str = ""


class MockFacilitator:
    def __init__(self, merchant_directory: KeyDirectory, user_directory: KeyDirectory):
        self.merchants, self.users = merchant_directory, user_directory

    def settle(self, cart: CartMandate, pm: PaymentMandate, per_txn_limit: float | None = None) -> Receipt:
        try:
            cart.verify(self.merchants)
        except SignatureError as e:
            return Receipt(False, f"merchant authorization invalid: {e}")
        if not pm.user_authorization:
            return Receipt(False, "missing user authorization")
        try:
            auth = self.users.verify(pm.user_authorization)
        except SignatureError as e:
            return Receipt(False, f"user authorization invalid: {e}")
        expected = [cart.content_hash(), sha256_hex(pm.payment_mandate_contents.model_dump(mode="json"))]
        if auth.get("transaction_data") != expected:
            return Receipt(False, "user authorization does not bind this cart and payment mandate")
        total = pm.payment_mandate_contents.payment_details_total.amount.value
        if abs(total - cart.contents.total) > 1e-6:
            return Receipt(False, "payment total differs from cart total")
        if per_txn_limit is not None and total > per_txn_limit + 1e-6:
            return Receipt(False, f"exceeds per-transaction limit Rs {per_txn_limit:,.0f}")
        return Receipt(True, "settled", total, cart.contents.merchant_name)
