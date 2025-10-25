from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def hash_code() -> str:
    # Hash qloop package files for a simple fingerprint
    h = hashlib.sha256()
    pkg = resources.files("qloop")
    for p in pkg.rglob("*"):
        if p.is_file():
            try:
                data = p.read_bytes()
            except Exception:
                continue
            h.update(data)
    return h.hexdigest()[:12]