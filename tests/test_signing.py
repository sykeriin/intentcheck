import pytest

from dia.ap2.signing import KeyDirectory, SignatureError, SigningKey, canonical_json, sha256_hex


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [2, 3]}) == canonical_json({"a": [2, 3], "b": 1})
    assert sha256_hex({"x": 1, "y": 2}) == sha256_hex({"y": 2, "x": 1})


def test_sign_verify_roundtrip():
    k = SigningKey.generate("m1")
    d = KeyDirectory()
    d.register(k)
    p = d.verify(k.sign({"a": 1}))
    assert p["a"] == 1 and p["_kid"] == "m1"


def test_tampered_payload_rejected():
    k = SigningKey.generate("m1")
    d = KeyDirectory()
    d.register(k)
    h, p, s = k.sign({"amount": 100}).split(".")
    forged = SigningKey.generate("m1").sign({"amount": 1}).split(".")[1]
    with pytest.raises(SignatureError):
        d.verify(f"{h}.{forged}.{s}")


def test_unknown_kid_and_wrong_key_rejected():
    k, evil = SigningKey.generate("m1"), SigningKey.generate("m1")
    d = KeyDirectory()
    d.register(k)
    with pytest.raises(SignatureError):
        d.verify(evil.sign({"a": 1}))  # same kid, different key
    with pytest.raises(SignatureError):
        d.verify(SigningKey.generate("other").sign({"a": 1}))  # unknown kid


def test_malformed_token_rejected():
    with pytest.raises(SignatureError):
        KeyDirectory().verify("not-a-token")


def test_seeded_keys_are_deterministic():
    a = SigningKey.from_seed("k", b"s")
    b = SigningKey.from_seed("k", b"s")
    d = KeyDirectory()
    d.register(a)
    assert d.verify(b.sign({"z": 1}))["z"] == 1
