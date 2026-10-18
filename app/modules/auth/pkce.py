"""PKCE (S256) values and the one-way hash used for stored OAuth state."""

import base64
import hashlib
import secrets


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode()).digest())


def pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(48))
    return verifier, pkce_challenge(verifier)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
