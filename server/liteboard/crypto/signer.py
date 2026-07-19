"""Server-side request signer.

Holds the single Ed25519 private key (loaded from the Docker secret) and signs
outbound requests to node daemons, plus signs daemon self-update bundles.
"""

from __future__ import annotations

import base64
import json
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

    def sign_bundle(self, version: str, files: dict[str, str]) -> dict:
        """Produce a self-update bundle signed with the server private key.

        ``files`` maps filename -> base64(file bytes). Must match the daemon's
        ``selfupdate._canonical_bundle_bytes`` exactly.
        """
        payload = {
            "version": version,
            "files": {name: files[name] for name in sorted(files)},
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = protocol.b64encode(self._priv.sign(canonical))
        return {"version": version, "files": payload["files"], "signature": signature}


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


def bundle_files_b64(source_dir: str, names: list[str]) -> dict[str, str]:
    """Read daemon source files and base64-encode them for a bundle."""
    import os

    out: dict[str, str] = {}
    for name in names:
        with open(os.path.join(source_dir, name), "rb") as fh:
            out[name] = base64.b64encode(fh.read()).decode()
    return out
