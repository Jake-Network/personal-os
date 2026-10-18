"""Network trust boundary alongside the separate application-session middleware.

The application is local-only; host/origin checks add protection against browser attacks:

1. DNS rebinding: a web page on attacker.example can rebind its hostname to 127.0.0.1 and then
   read the API same-origin. The browser still sends `Host: attacker.example`, so every request's
   Host, and the X-Forwarded-Host set by the Next.js proxy, must name a loopback host, an IP
   literal (rebinding needs a hostname the attacker controls), or a host the operator listed in
   PERSONAL_OS_ALLOWED_HOSTS.
2. CSRF: any page can fire a "simple" cross-site POST (e.g. /api/proposals/1/approve) without a
   CORS preflight. State-changing requests carrying an Origin must come from the configured
   frontend, a loopback origin, or the same origin they are addressed to. `Origin: null` and
   `Sec-Fetch-Site: cross-site` are refused. Requests with neither header (curl, tests, the Next
   server itself) are allowed: they cannot be forged by a web page.

These checks do not replace AppAuthMiddleware. Remote exposure requires a separate
authentication and TLS design; the application remains a local single-user service.
"""

import ipaddress
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_NAMES = frozenset({"localhost"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _hostname(netloc: str) -> str:
    return (urlsplit(f"//{netloc}").hostname or "").lower()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_loopback(host: str) -> bool:
    return host in LOOPBACK_NAMES or (_is_ip(host) and ipaddress.ip_address(host).is_loopback)


class LocalTrustMiddleware:
    def __init__(self, app: ASGIApp, frontend_url: str, allowed_hosts: tuple[str, ...] = ()):
        self.app = app
        parts = urlsplit(frontend_url)
        self.frontend_origin = f"{parts.scheme}://{parts.netloc}".lower()
        self.allowed_hosts = frozenset(h.strip().lower() for h in allowed_hosts if h.strip())

    def host_allowed(self, netloc: str) -> bool:
        host = _hostname(netloc)
        return bool(host) and (_is_loopback(host) or _is_ip(host) or host in self.allowed_hosts)

    def origin_allowed(self, origin: str, request_netloc: str) -> bool:
        if origin == "null":
            return False
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        return (origin.lower() == self.frontend_origin
                or _is_loopback(parts.hostname or "")
                or parts.netloc.lower() == request_netloc.lower())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        forwarded = headers.get("x-forwarded-host", "").split(",")[0].strip()
        if not self.host_allowed(host) or (forwarded and not self.host_allowed(forwarded)):
            await JSONResponse({"detail": "untrusted host"}, status_code=421)(scope, receive, send)
            return
        if scope["method"] in UNSAFE_METHODS:
            origin = headers.get("origin")
            cross_site = headers.get("sec-fetch-site") == "cross-site"
            if (origin is not None and not self.origin_allowed(origin, forwarded or host)) \
                    or (origin is None and cross_site):
                # Name the configured frontend so a user on another origin (e.g. a WSL IP) knows where to go.
                detail = f"cross-origin request refused; open the app at {self.frontend_origin}"
                await JSONResponse({"detail": detail}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
