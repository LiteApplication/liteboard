"""Tests for the signed-request protocol shared with the daemon."""

import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from liteboard.crypto import protocol


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


def test_sign_and_verify_roundtrip(keypair):
    priv, pub = keypair
    headers = protocol.sign_request(priv, "GET", "/metrics").as_dict()
    protocol.verify_request(pub, "GET", "/metrics", headers, b"")


def test_verify_rejects_tampered_path(keypair):
    priv, pub = keypair
    headers = protocol.sign_request(priv, "GET", "/metrics").as_dict()
    with pytest.raises(protocol.VerificationError):
        protocol.verify_request(pub, "GET", "/networks", headers, b"")


def test_verify_rejects_tampered_body(keypair):
    priv, pub = keypair
    headers = protocol.sign_request(priv, "POST", "/update", b"real").as_dict()
    with pytest.raises(protocol.VerificationError):
        protocol.verify_request(pub, "POST", "/update", headers, b"forged")


def test_verify_rejects_wrong_key(keypair):
    priv, _ = keypair
    other = Ed25519PrivateKey.generate().public_key()
    headers = protocol.sign_request(priv, "GET", "/metrics").as_dict()
    with pytest.raises(protocol.VerificationError):
        protocol.verify_request(other, "GET", "/metrics", headers, b"")


def test_verify_rejects_stale_timestamp(keypair):
    priv, pub = keypair
    old = str(int(time.time()) - 120)
    headers = protocol.sign_request(priv, "GET", "/metrics", timestamp=old).as_dict()
    with pytest.raises(protocol.VerificationError):
        protocol.verify_request(pub, "GET", "/metrics", headers, b"", max_skew=30)


def test_verify_rejects_replayed_nonce(keypair):
    priv, pub = keypair
    headers = protocol.sign_request(priv, "GET", "/metrics").as_dict()
    seen = set()

    def seen_nonce(n):
        if n in seen:
            return True
        seen.add(n)
        return False

    protocol.verify_request(pub, "GET", "/metrics", headers, b"", seen_nonce=seen_nonce)
    with pytest.raises(protocol.VerificationError):
        protocol.verify_request(
            pub, "GET", "/metrics", headers, b"", seen_nonce=seen_nonce
        )


def test_public_key_roundtrip(keypair):
    priv, _ = keypair
    b64 = protocol.public_key_b64(priv)
    loaded = protocol.load_public_key(b64)
    headers = protocol.sign_request(priv, "GET", "/version").as_dict()
    protocol.verify_request(loaded, "GET", "/version", headers, b"")
