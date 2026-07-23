"""Build the signed daemon self-update bundle from the packaged daemon source.

The daemon source files are copied into this package at build time (see the
server Dockerfile / Makefile) so the server can serve authenticated updates.
"""

from __future__ import annotations

import os
import re

from ..crypto.signer import Signer, bundle_files_b64

# Files that make up a daemon deployment.
DAEMON_FILES = [
    "liteboard_daemon.py",
    "protocol.py",
    "metrics.py",
    "netinspect.py",
    "selfupdate.py",
    "dockerapi.py",
    "images.py",
]

_SRC_DIR = os.path.join(os.path.dirname(__file__), "src")


def daemon_version() -> str:
    """Read VERSION from the packaged daemon source."""
    main = os.path.join(_SRC_DIR, "liteboard_daemon.py")
    if not os.path.isfile(main):
        return "unknown"
    text = open(main, encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def build_bundle(signer: Signer) -> dict:
    files = bundle_files_b64(_SRC_DIR, DAEMON_FILES)
    return signer.sign_bundle(daemon_version(), files)
