"""LiteBoard signed-request protocol (shared by server and daemon).

The server holds a stable Ed25519 *private* key (a Docker secret). Every node
daemon is given only the matching *public* key via its environment. To query a
daemon, the server signs a canonical string built from the request; the daemon
verifies it with the public key. A timestamp + nonce defeat replay attacks.

This file is the single source of truth for the wire format. It is copied
verbatim into ``server/liteboard/crypto/protocol.py`` so the daemon can stay
dependency-light (only ``cryptography``) while the server reuses the exact same
canonicalisation. Keep the two copies identical.
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Header names carrying the authentication envelope.
HEADER_TIMESTAMP = "X-LB-Timestamp"
HEADER_NONCE = "X-LB-Nonce"
HEADER_SIGNATURE = "X-LB-Signature"
HEADER_KEY_ID = "X-LB-Key-Id"

# Requests older than this (seconds) are rejected as replays / stale.
DEFAULT_MAX_SKEW = 30

# Domain-separation prefix so a LiteBoard signature can never be mistaken for a
# signature over some other protocol's bytes.
_DOMAIN = b"liteboard/v1"


def b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def body_digest(body: bytes) -> str:
    """Hex SHA-256 of the request/response body (empty allowed)."""
    return hashlib.sha256(body or b"").hexdigest()


def canonical_string(
    method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> bytes:
    """Build the exact bytes that get signed.

    Both sides MUST assemble this identically. ``path`` is the request path
    including any query string, without the scheme/host, so the same daemon
    endpoint proxied through different hostnames still verifies.
    """
    parts = "\n".join(
        [
            method.upper(),
            path,
            str(timestamp),
            nonce,
            body_digest(body),
        ]
    )
    return _DOMAIN + b"\n" + parts.encode("utf-8")


# --------------------------------------------------------------------------- #
# Key helpers
# --------------------------------------------------------------------------- #
def load_private_key(pem_or_raw: bytes) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from PEM or raw 32-byte seed."""
    stripped = pem_or_raw.strip()
    if stripped.startswith(b"-----BEGIN"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_private_key(stripped, password=None)  # type: ignore[return-value]
    if len(stripped) == 32:
        return Ed25519PrivateKey.from_private_bytes(stripped)
    # base64 seed
    return Ed25519PrivateKey.from_private_bytes(b64decode(stripped.decode()))


def load_public_key(text: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from a base64url-encoded 32-byte value."""
    return Ed25519PublicKey.from_public_bytes(b64decode(text.strip()))


def public_key_b64(priv: Ed25519PrivateKey) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return b64encode(raw)


def key_id(pub_b64: str) -> str:
    """Short stable identifier for a public key (first 12 hex of its hash)."""
    return hashlib.sha256(pub_b64.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Signing / verifying
# --------------------------------------------------------------------------- #
@dataclass
class SignedHeaders:
    timestamp: str
    nonce: str
    signature: str
    key_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            HEADER_TIMESTAMP: self.timestamp,
            HEADER_NONCE: self.nonce,
            HEADER_SIGNATURE: self.signature,
            HEADER_KEY_ID: self.key_id,
        }


def sign_request(
    priv: Ed25519PrivateKey,
    method: str,
    path: str,
    body: bytes = b"",
    *,
    nonce: str | None = None,
    timestamp: str | None = None,
    kid: str | None = None,
) -> SignedHeaders:
    import os

    ts = timestamp if timestamp is not None else str(int(time.time()))
    nc = nonce if nonce is not None else b64encode(os.urandom(16))
    msg = canonical_string(method, path, ts, nc, body)
    sig = priv.sign(msg)
    return SignedHeaders(
        timestamp=ts,
        nonce=nc,
        signature=b64encode(sig),
        key_id=kid or key_id(public_key_b64(priv)),
    )


class VerificationError(Exception):
    """Raised when a request fails authentication."""


def verify_request(
    pub: Ed25519PublicKey,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    *,
    max_skew: int = DEFAULT_MAX_SKEW,
    seen_nonce: "callable | None" = None,
    now: float | None = None,
) -> None:
    """Verify a signed request or raise :class:`VerificationError`.

    ``headers`` is looked up case-insensitively. ``seen_nonce`` (if given) is a
    callable ``nonce -> bool`` that records the nonce and returns ``True`` if it
    was already used (replay).
    """
    lower = {k.lower(): v for k, v in headers.items()}
    ts = lower.get(HEADER_TIMESTAMP.lower())
    nonce = lower.get(HEADER_NONCE.lower())
    sig = lower.get(HEADER_SIGNATURE.lower())
    if not ts or not nonce or not sig:
        raise VerificationError("missing authentication headers")

    try:
        ts_int = int(ts)
    except ValueError as exc:
        raise VerificationError("invalid timestamp") from exc

    current = now if now is not None else time.time()
    if abs(current - ts_int) > max_skew:
        raise VerificationError("timestamp outside allowed window")

    msg = canonical_string(method, path, ts, nonce, body)
    try:
        pub.verify(b64decode(sig), msg)
    except (InvalidSignature, ValueError) as exc:
        raise VerificationError("bad signature") from exc

    # Only reject as a replay AFTER the signature is proven valid, so an
    # attacker cannot poison the nonce cache with forged requests.
    if seen_nonce is not None and seen_nonce(nonce):
        raise VerificationError("nonce already used (replay)")
