"""Market API scoped to one scenario, with simulated latency and provenance labels.

Trust labels on everything returned:
  trusted   - catalogue specs, platform ratings, seller-signed quotes/carts (binding commitments)
  untrusted - listing free text and claimed fields authored by sellers
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..ap2.models import (
    CartContents, CartLine, CartMandate, PaymentCurrencyAmount, PaymentDetailsInit, PaymentItem,
    PaymentMethodData, PaymentRequest,
)
from ..ap2.signing import KeyDirectory, SigningKey
from .catalogue import Catalogue, Offer, Product, Terms
from .sellers import Listing, make_listing, sample_latency_ms


@dataclass
class ProvenanceItem:
    kind: str           # search_result | quote | product | rating | cart
    source: str         # trusted | untrusted
    origin: str         # seller_id | catalogue | platform
    offer_id: str | None
    text: str | None = None


class Keyring:
    """Deterministic per-seller keys + a trusted directory."""

    def __init__(self, cat: Catalogue):
        self.keys = {sid: SigningKey.from_seed(sid, f"{cat.seed}:{sid}".encode()) for sid in cat.sellers}
        self.directory = KeyDirectory()
        for k in self.keys.values():
            self.directory.register(k)


@dataclass
class Market:
    cat: Catalogue
    keyring: Keyring
    offer_ids: list[str]
    category: str
    seed: int
    listings: dict[str, Listing] = field(default_factory=dict)

    def __post_init__(self):
        rng = random.Random(self.seed)
        offers = [self.cat.offers[o] for o in self.offer_ids]
        for o in offers:
            self.listings[o.offer_id] = make_listing(o, self.cat, offers, rng)

    @property
    def offers(self) -> list[Offer]:
        return [self.cat.offers[o] for o in self.offer_ids]

    def session(self, actor: str, rng_seed: int) -> "MarketSession":
        return MarketSession(self, actor, random.Random(rng_seed))


def _cart_from_terms(offer: Offer, t: Terms, product: Product, seller_name: str, currency: str) -> CartMandate:
    now = datetime.now(UTC)
    items = [PaymentItem(label=product.title, amount=PaymentCurrencyAmount(currency=currency, value=t.price),
                         refund_period=30 if t.returnable else 0)]
    if t.fees:
        items.append(PaymentItem(label="Convenience & platform fee",
                                 amount=PaymentCurrencyAmount(currency=currency, value=t.fees)))
    if t.shipping:
        items.append(PaymentItem(label="Shipping & handling",
                                 amount=PaymentCurrencyAmount(currency=currency, value=t.shipping)))
    details = PaymentDetailsInit(
        id=f"pr-{offer.offer_id}-{int(now.timestamp() * 1000)}",
        display_items=items,
        total=PaymentItem(label="Total", amount=PaymentCurrencyAmount(currency=currency, value=t.total)),
    )
    contents = CartContents(
        id=f"cart-{offer.offer_id}", user_cart_confirmation_required=False,
        payment_request=PaymentRequest(method_data=[PaymentMethodData(supported_methods="upi-reserve-pay")],
                                       details=details),
        cart_expiry=(now + timedelta(minutes=15)).isoformat(), merchant_name=seller_name,
        x_line=CartLine(offer_id=offer.offer_id, seller_id=offer.seller_id, sku=t.sku,
                        delivery_days=t.delivery_days, returnable=t.returnable),
    )
    return CartMandate(contents=contents)


class MarketSession:
    """One actor's view of the market. Logs every response with provenance."""

    def __init__(self, market: Market, actor: str, rng: random.Random):
        self.m = market
        self.actor = actor
        self.rng = rng
        self.log: list[ProvenanceItem] = []
        self.sim_network_ms = 0.0

    # ---- untrusted ----
    def search(self, timeout_ms: float = 1000, retries: int = 0) -> list[Listing]:
        """Fan-out search to sellers in the scenario. Late/failed sellers are silently dropped."""
        arrived: dict[str, Listing] = {}
        elapsed = 0.0
        for _attempt in range(retries + 1):
            slowest = 0.0
            for oid in self.m.offer_ids:
                if oid in arrived:
                    continue
                prof = self.m.cat.sellers[self.m.cat.offers[oid].seller_id].profile
                lat = sample_latency_ms(prof, self.rng)
                if lat is not None and lat <= timeout_ms:
                    arrived[oid] = self.m.listings[oid]
                    slowest = max(slowest, lat)
                else:
                    slowest = timeout_ms
            elapsed += slowest
        self.sim_network_ms += elapsed
        out = list(arrived.values())
        for li in out:
            self.log.append(ProvenanceItem("search_result", "untrusted", li.seller_id, li.offer_id, li.text()))
        return out

    # ---- trusted ----
    def get_quote(self, offer_id: str) -> dict:
        """Seller-signed quote of the offer's binding terms (as the seller states them pre-checkout)."""
        o = self.m.cat.offers[offer_id]
        q = o.quoted
        payload = {"offer_id": offer_id, "seller_id": o.seller_id, "sku": q.sku, "price": q.price,
                   "fees": q.fees, "shipping": q.shipping, "total": q.total,
                   "delivery_days": q.delivery_days, "returnable": q.returnable}
        token = self.m.keyring.keys[o.seller_id].sign(payload)
        self.sim_network_ms += 150
        self.log.append(ProvenanceItem("quote", "trusted", o.seller_id, offer_id))
        verified = self.m.keyring.directory.verify(token)
        verified.pop("_kid", None)
        return verified

    def get_product(self, sku: str) -> Product:
        self.log.append(ProvenanceItem("product", "trusted", "catalogue", None))
        return self.m.cat.products[sku]

    def seller_rating(self, seller_id: str) -> float:
        self.log.append(ProvenanceItem("rating", "trusted", "platform", None))
        return self.m.cat.sellers[seller_id].rating

    def checkout(self, offer_id: str, currency: str = "INR") -> CartMandate:
        """Ask the merchant for a signed CartMandate. Adversarial sellers mutate terms here."""
        o = self.m.cat.offers[offer_id]
        t = o.effective
        s = self.m.cat.sellers[o.seller_id]
        cart = _cart_from_terms(o, t, self.m.cat.products[t.sku], s.name, currency)
        cart.sign(self.m.keyring.keys[o.seller_id])
        self.sim_network_ms += 300
        self.log.append(ProvenanceItem("cart", "trusted", o.seller_id, offer_id))
        return cart

    def untrusted_texts(self) -> list[ProvenanceItem]:
        return [p for p in self.log if p.source == "untrusted"]
