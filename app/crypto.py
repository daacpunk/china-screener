"""Encrypt/decrypt secrets at rest using Fernet derived from APP_SECRET.

If APP_SECRET is not set, a key is derived from a persisted random salt stored
next to the DB so values remain decryptable across restarts (less secure than a
real secret, but functional for demo/dev). Secrets are NEVER logged.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_SALT_FILENAME = ".secret_salt"


def _key_dir() -> Path:
    db_path = os.environ.get("DB_PATH", "./app.db")
    d = Path(db_path).expanduser().resolve().parent
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path(".").resolve()


def _derive_key() -> bytes:
    secret = os.environ.get("APP_SECRET", "").strip()
    if not secret:
        # derive/persist a random salt so encryption is stable across restarts
        salt_path = _key_dir() / _SALT_FILENAME
        if salt_path.exists():
            secret = salt_path.read_text().strip()
        else:
            secret = base64.urlsafe_b64encode(os.urandom(32)).decode()
            try:
                salt_path.write_text(secret)
            except Exception:
                pass
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_derive_key())


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        plaintext = ""
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def mask(secret: str) -> str:
    """Return masked representation showing only last 4 chars."""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "•" * len(secret)
    return "•" * (len(secret) - 4) + secret[-4:]
