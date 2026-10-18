"""Search discovery, SSRF-safe collection and query-specific evidence selection."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx


class WebSearchError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class _ArticleParser(HTMLParser):
    _ignored = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg", "template"}
    _blocks = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "li", "tr", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored: list[str] = []
        self.in_title = False
        self.title = ""
        self.published_at: str | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.ignored:
            if tag in self._ignored:
                self.ignored.append(tag)
            return
        if tag in self._ignored:
            self.ignored.append(tag)
            return
        if tag == "title":
            self.in_title = True
        if tag == "meta" and (attrs.get("property") or attrs.get("name")) in {
            "article:published_time", "date", "datePublished", "pubdate",
        }:
            self.published_at = (attrs.get("content") or "")[:100] or None
        if tag in self._blocks:
            self.parts.append("\n")
        if tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "title":
            self.in_title = False
        if tag in self._blocks:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title += data
        else:
            self.parts.append(data)


def extract_evidence(text: str, query: str, *, html: bool) -> tuple[str, str | None, str, list[str]]:
    """Keep conditions/units with evidence; rank bounded passages, retain source order."""
    parser = _ArticleParser()
    if html:
        parser.feed(text)
        text = "".join(parser.parts)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in text.splitlines()]
    # Chunk long paragraphs without silently discarding their later sections.
    chunks = [p[i:i + 1200] for p in paragraphs if p for i in range(0, len(p), 1200)]
    chunks = list(dict.fromkeys(chunks))
    terms = set(re.findall(r"[\w가-힣]{2,}", query.casefold()))
    ranked = sorted(enumerate(chunks), key=lambda item: (-sum(term in item[1].casefold() for term in terms), item[0]))
    selected = sorted(ranked[:5])
    return parser.title.strip()[:300], parser.published_at, "\n".join(chunks), [chunk for _, chunk in selected]


async def _resolve(host: str, port: int) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(record[4][0] for record in records))


class WebSearchService:
    def __init__(
        self, api_key: str = "", *, max_pages: int = 3, max_bytes: int = 1_000_000,
        timeout_seconds: float = 25, transport: httpx.AsyncBaseTransport | None = None,
        resolver: Callable[[str, int], Awaitable[list[str]]] = _resolve,
    ):
        self.api_key = api_key
        self.max_pages = max(1, min(max_pages, 5))
        self.max_bytes = max(1024, min(max_bytes, 2_000_000))
        self.timeout_seconds = max(1, min(timeout_seconds, 60))
        self.transport = transport
        self.resolver = resolver

    async def _public_target(self, url: str) -> tuple[httpx.URL, str, str]:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
                    or parsed.password is not None or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}
                    or any(ord(c) < 32 for c in url) or "\\" in url):
                raise ValueError
            normalized = httpx.URL(url).copy_with(fragment=None)
            addresses = await self.resolver(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise ValueError
            return normalized, normalized.raw_host.decode('ascii'), addresses[0]
        except (ValueError, OSError, httpx.InvalidURL):
            raise WebSearchError("web_page_blocked", "공개 웹 주소만 수집할 수 있습니다.") from None

    async def _read(self, client: httpx.AsyncClient, url: httpx.URL | str, *, headers=None, extensions=None):
        async with client.stream("GET", url, headers=headers, extensions=extensions) as response:
            # Refuse compressed bodies: bound actual download and avoid decompression bombs.
            if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise WebSearchError("web_page_encoding", "압축된 응답을 수집하지 못했습니다.")
            data = bytearray()
            async for chunk in response.aiter_raw():
                data.extend(chunk)
                if len(data) > self.max_bytes:
                    raise WebSearchError("web_page_too_large", "본문 크기가 수집 한도를 초과했습니다.")
            return response.status_code, response.headers, bytes(data)

    def _client(self):
        return httpx.AsyncClient(
            transport=self.transport, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(8), headers={"Accept-Encoding": "identity", "User-Agent": "PersonalOS-WebResearch/1.0"},
        )

    async def _discover(self, query: str) -> list[dict]:
        url = httpx.URL("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": self.max_pages + 2})
        async with self._client() as client:
            status, _, body = await self._read(client, url, headers={"X-Subscription-Token": self.api_key})
        if status != 200:
            raise WebSearchError("web_search_provider_failed", "웹 검색 제공자 요청에 실패했습니다.")
        try:
            results = json.loads(body).get("web", {}).get("results", [])
            if not isinstance(results, list):
                raise ValueError
            return [item for item in results if isinstance(item, dict)][:self.max_pages + 2]
        except (ValueError, AttributeError):
            raise WebSearchError("web_search_provider_failed", "웹 검색 응답을 해석하지 못했습니다.") from None

    async def _collect(self, url: str, query: str, fallback_title: str) -> dict:
        for hop in range(4):
            original, host, address = await self._public_target(url)
            # Connect to the checked numeric IP. Host and TLS name remain the original
            # hostname, so certificate checks still apply and DNS cannot rebind.
            pinned = original.copy_with(host=address)
            async with self._client() as client:
                status, headers, body = await self._read(
                    client, pinned, headers={"Host": original.netloc.decode("ascii")},
                    extensions={"sni_hostname": host},
                )
            if status in {301, 302, 303, 307, 308}:
                if hop == 3 or not headers.get("location"):
                    raise WebSearchError("web_page_redirect_limit", "웹페이지 이동 한도를 초과했습니다.")
                url = urljoin(str(original), headers["location"])
                continue
            if status != 200:
                raise WebSearchError("web_page_fetch_failed", "웹페이지 본문을 가져오지 못했습니다.")
            media = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise WebSearchError("web_page_unsupported_type", "지원하지 않는 웹 문서 형식입니다.")
            encoding = httpx.Response(200, headers=headers).encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            title, published, full_text, excerpts = extract_evidence(text, query, html=media != "text/plain")
            if not excerpts:
                raise WebSearchError("web_page_empty", "웹페이지에서 본문을 추출하지 못했습니다.")
            return {"url": str(original), "title": title or fallback_title[:300], "published_at": published,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "content_hash": hashlib.sha256(full_text.encode()).hexdigest(), "excerpts": excerpts}
        raise AssertionError("unreachable")

    async def search(self, query: str) -> dict:
        if os.environ.get("PERSONAL_OS_PRODUCTION", "").lower() == "true":
            raise WebSearchError(
                "web_search_production_unsupported",
                "운영 Docker의 외부 연결 정책에서는 웹 본문 수집을 지원하지 않습니다. 로컬 실행을 사용하세요.",
            )
        query = query.strip()
        if not query or len(query) > 400:
            raise WebSearchError("web_search_invalid_query", "검색어는 1~400자로 입력해 주세요.")
        if not self.api_key:
            raise WebSearchError("web_search_unavailable", "웹 검색 API 키가 설정되지 않았습니다.")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                results = await self._discover(query)
                pages, flags, seen = [], [], set()
                for result in results:
                    url = result.get("url")
                    if not isinstance(url, str) or url in seen:
                        continue
                    seen.add(url)
                    try:
                        pages.append(await self._collect(url, query, str(result.get("title", ""))))
                    except WebSearchError as exc:
                        flags.append(exc.code)
                    except (httpx.HTTPError, OSError):
                        flags.append("web_page_fetch_failed")
                    if len(pages) >= self.max_pages:
                        break
                if not pages:
                    flags.append("web_search_no_body_evidence")
                return {"query": query, "pages": pages, "data_quality_flags": list(dict.fromkeys(flags))}
        except TimeoutError:
            raise WebSearchError("web_search_timeout", "웹 조사 시간이 한도를 초과했습니다.") from None
        except (httpx.HTTPError, OSError):
            raise WebSearchError("web_search_provider_failed", "웹 검색 제공자에 연결하지 못했습니다.") from None
