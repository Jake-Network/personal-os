"""Types held by the OAuth sign-in flow."""

from dataclasses import dataclass


@dataclass
class PendingLogin:
    """PKCE state kept between the authorize redirect and the callback."""

    verifier: str
    nonce: str
    client_id: str
    created: float
    generation: str | None = None
