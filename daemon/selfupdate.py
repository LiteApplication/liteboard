"""Secure daemon self-update.

The server pushes a new daemon bundle to the daemon's (already authenticated)
``/update`` endpoint. On top of the request signature, the bundle payload itself
carries an Ed25519 signature over the code, verified with the same server public
key. Only after both checks pass does the daemon atomically replace its own files
and re-exec. There is no unauthenticated update path.

A "bundle" is a JSON object::

    {
      "version": "1.4.0",
      "files": {"liteboard_daemon.py": "<b64>", "metrics.py": "<b64>", ...},
      "signature": "<b64 Ed25519 over the canonical bundle bytes>"
    }
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from protocol import VerificationError, b64decode


def _canonical_bundle_bytes(version: str, files: dict[str, str]) -> bytes:
    """Deterministic bytes signed by the server: version + sorted file digests."""
    payload = {
        "version": version,
        "files": {name: files[name] for name in sorted(files)},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def verify_bundle(pub: Ed25519PublicKey, bundle: dict) -> None:
    version = bundle.get("version")
    files = bundle.get("files")
    signature = bundle.get("signature")
    if not isinstance(version, str) or not isinstance(files, dict) or not signature:
        raise VerificationError("malformed bundle")
    from cryptography.exceptions import InvalidSignature

    try:
        pub.verify(b64decode(signature), _canonical_bundle_bytes(version, files))
    except (InvalidSignature, ValueError) as exc:
        raise VerificationError("bad bundle signature") from exc


def apply_bundle(pub: Ed25519PublicKey, bundle: dict, install_dir: str) -> str:
    """Verify and atomically install a bundle. Returns the new version.

    Files are written to temp files in the install dir then os.replace'd so a
    crash mid-write can never leave a half-written daemon file.
    """
    verify_bundle(pub, bundle)
    version = bundle["version"]
    for name, b64 in bundle["files"].items():
        if os.path.sep in name or name.startswith("."):
            raise VerificationError(f"illegal filename in bundle: {name!r}")
        content = base64.b64decode(b64)
        dst = os.path.join(install_dir, name)
        fd, tmp = tempfile.mkstemp(dir=install_dir, prefix=f".{name}.")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return version


def restart() -> None:
    """Re-exec the daemon process in place, picking up the new code."""
    os.execv(sys.executable, [sys.executable] + sys.argv)
