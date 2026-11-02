import pytest

from dia.arena.catalogue import build_catalogue
from dia.arena.market import Keyring, Market
from dia.ap2.signing import SignatureError, SigningKey


@pytest.fixture(scope="module")
def cat():
    return build_catalogue(7)


def _market(cat, offer_ids):
    return Market(cat, Keyring(cat), offer_ids, "x", seed=1)


def test_catalogue_size_and_unique_skus(cat):
    assert len(cat.products) == 2000
    assert len(cat.sellers) == 40
    assert 5500 < len(cat.offers) < 7000


def test_catalogue_is_deterministic():
    a, b = build_catalogue(3), build_catalogue(3)
    assert [(o.offer_id, o.quoted.price) for o in a.offers.values()] == \
           [(o.offer_id, o.quoted.price) for o in b.offers.values()]


def test_cart_roundtrip_verifies(cat):
    oid = next(iter(cat.offers))
    m = _market(cat, [oid])
    cart = m.session("t", 0).checkout(oid)
    payload = cart.verify(m.keyring.directory)
    assert payload["cart_hash"] == cart.content_hash()


def test_cart_tamper_after_signing_detected(cat):
    oid = next(iter(cat.offers))
    m = _market(cat, [oid])
    cart = m.session("t", 0).checkout(oid)
    cart.contents.payment_request.details.total.amount.value -= 500
    with pytest.raises(SignatureError, match="cart_hash"):
        cart.verify(m.keyring.directory)


def test_cart_signed_by_wrong_merchant_detected(cat):
    oid = next(iter(cat.offers))
    other = next(s for s in cat.sellers if s != cat.offers[oid].seller_id)
    m = _market(cat, [oid])
    cart = m.session("t", 0).checkout(oid)
    cart.sign(m.keyring.keys[other])
    with pytest.raises(SignatureError, match="not the selling merchant"):
        cart.verify(m.keyring.directory)


def test_unsigned_cart_rejected(cat):
    oid = next(iter(cat.offers))
    m = _market(cat, [oid])
    cart = m.session("t", 0).checkout(oid)
    cart.merchant_authorization = None
    with pytest.raises(SignatureError):
        cart.verify(m.keyring.directory)


def test_dark_pattern_fee_only_appears_in_signed_cart(cat):
    o = next(o for o in cat.offers.values() if cat.sellers[o.seller_id].profile == "dark_pattern")
    m = _market(cat, [o.offer_id])
    s = m.session("t", 0)
    assert s.get_quote(o.offer_id)["fees"] == 0
    assert s.checkout(o.offer_id).contents.total > o.quoted.total


def test_bait_and_switch_changes_cart_not_quote(cat):
    o = next(o for o in cat.offers.values()
             if cat.sellers[o.seller_id].profile == "bait_and_switch" and o.checkout)
    m = _market(cat, [o.offer_id])
    s = m.session("t", 0)
    cart = s.checkout(o.offer_id)
    assert s.get_quote(o.offer_id)["sku"] == o.quoted.sku
    assert cart.contents.x_line.sku != o.quoted.sku or \
        cart.contents.x_line.delivery_days > o.quoted.delivery_days


def test_payment_mandate_binds_cart_hash(cat):
    from dia.ap2.models import PaymentMandate
    oid = next(iter(cat.offers))
    m = _market(cat, [oid])
    cart = m.session("t", 0).checkout(oid)
    user = SigningKey.generate("user")
    pm = PaymentMandate.for_cart(cart, user)
    assert pm.user_authorization
    assert pm.payment_mandate_contents.payment_details_total.amount.value == cart.contents.total
