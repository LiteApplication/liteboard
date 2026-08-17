"""Server-side request signer.

Holds the single Ed25519 private key (loaded from the Docker secret) and signs
outbound requests to node daemons.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import protocol


class Signer:
    def __init__(self, private_key_material: bytes) -> None:
        self._priv: Ed25519PrivateKey = protocol.load_private_key(private_key_material)
        self.public_key_b64 = protocol.public_key_b64(self._priv)
        self.key_id = protocol.key_id(self.public_key_b64)

    def sign_headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        """Return the auth headers for a request to a daemon."""
        signed = protocol.sign_request(
            self._priv, method, path, body, kid=self.key_id
        )
        return signed.as_dict()


def generate_signing_key(path: str | Path) -> str:
    """Generate a stable Ed25519 keypair, persist the private seed, return pubkey.

    Writes the base64url raw seed to ``path`` (mode 0600) and returns the
    matching base64url public key. Refuses to overwrite an existing key.
    """
    path = Path(path)
    if path.is_file():
        raise FileExistsError(f"{path} already exists — refusing to overwrite")
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(protocol.b64encode(seed))
    os.chmod(path, 0o600)
    return protocol.public_key_b64(priv)
