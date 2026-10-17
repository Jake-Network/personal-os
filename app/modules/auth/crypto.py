"""At-rest encryption for OAuth token sets."""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


def load_or_create_key(secret: str, data_dir: Path) -> bytes:
    if secret:
        return secret.encode()
    path = data_dir / "secret.key"
    if path.exists():
        return path.read_bytes().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


class TokenCipher:
    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt(self, tokens: dict) -> bytes:
        return self._fernet.encrypt(json.dumps(tokens).encode())

    def decrypt(self, blob: bytes) -> dict:
        return json.loads(self._fernet.decrypt(blob))
