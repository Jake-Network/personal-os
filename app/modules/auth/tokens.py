"""Reading provider token responses and merging rotated tokens into the stored record."""

import httpx


def provider_error_code(resp: httpx.Response) -> str | None:
    """The provider's error code from a token-endpoint response, if it sent one."""
    try:
        body = resp.json()
    except ValueError:
        return None
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("code") or err.get("type")
    return err or body.get("code")


def merged_token_record(tokens: dict, previous: dict) -> dict:
    """Rotation: always keep the latest refresh token; keep the old one if none returned."""
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token") or previous.get("refresh_token"),
        "id_token": tokens.get("id_token") or previous.get("id_token"),
        "token_type": tokens.get("token_type", "Bearer"),
    }
