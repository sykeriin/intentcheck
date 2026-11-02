"""Ed25519 signing over canonical JSON, as compact JWS-style tokens.

AP2's reference docs describe RS256 JWTs carrying a `cart_hash`. We use EdDSA
(Ed25519) with the same structure: header.payload.signature, base64url, with the
payload carrying a SHA-256 hash of the canonical JSON of the signed object.
The security property (integrity + issuer authenticity) is identical; an adapter
can re-sign as RS256 if exact wire compatibility is needed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SignatureError(Exception):
    pass


@dataclass
class SigningKey:
    kid: str
    _sk: Ed25519PrivateKey

    @classmethod
    def generate(cls, kid: str) -> "SigningKey":
        return cls(kid, Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, kid: str, seed: bytes) -> "SigningKey":
        """Deterministic key from a 32-byte seed (arena reproducibility only)."""
        return cls(kid, Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed).digest()))

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._sk.public_key()

    def sign(self, payload: dict) -> str:
        header = {"alg": "EdDSA", "kid": self.kid, "typ": "JWT"}
        signing_input = f"{_b64(canonical_json(header))}.{_b64(canonical_json(payload))}"
        sig = self._sk.sign(signing_input.encode())
        return f"{signing_input}.{_b64(sig)}"


@dataclass
class KeyDirectory:
    """Trusted kid -> public key directory (e.g. a merchant registry)."""

    keys: dict[str, Ed25519PublicKey] = field(default_factory=dict)

    def register(self, key: SigningKey) -> None:
        self.keys[key.kid] = key.public_key

    def verify(self, token: str) -> dict:
        try:
            h, p, s = token.split(".")
            header = json.loads(_unb64(h))
            payload = json.loads(_unb64(p))
        except Exception as e:  # malformed token
            raise SignatureError(f"malformed token: {e}") from e
        if header.get("alg") != "EdDSA":
            raise SignatureError("unsupported alg")
        pk = self.keys.get(header.get("kid"))
        if pk is None:
            raise SignatureError(f"unknown kid {header.get('kid')!r}")
        try:
            pk.verify(_unb64(s), f"{h}.{p}".encode())
        except InvalidSignature as e:
            raise SignatureError("bad signature") from e
        payload["_kid"] = header["kid"]
        return payload
