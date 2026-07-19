#!/usr/bin/env python3
"""Generate the stable LiteBoard Ed25519 signing keypair.

Writes the private key (base64url raw seed) to secrets/signing_key and prints
the public key to add to your .env as LITEBOARD_SERVER_PUBKEY.
"""

import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def main() -> None:
    os.makedirs("secrets", exist_ok=True)
    key_path = "secrets/signing_key"
    if os.path.exists(key_path):
        raise SystemExit(
            f"{key_path} already exists — refusing to overwrite. "
            "Delete it first if you really want a new key (this rotates all daemons)."
        )

    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    with open(key_path, "w") as fh:
        fh.write(b64u(seed))
    os.chmod(key_path, 0o600)

    print(f"\n✓ Private key written to {key_path} (mode 0600 — keep it safe!)")
    print("\nAdd this line to your .env file:\n")
    print(f"LITEBOARD_SERVER_PUBKEY={b64u(pub)}\n")


if __name__ == "__main__":
    main()
