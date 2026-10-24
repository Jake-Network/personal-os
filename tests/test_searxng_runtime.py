"""SearXNG selection preserves the public-query-only runtime egress boundary."""
from dataclasses import replace

import httpx

from app import config
from app.modules.web_search import WebSearchService
from test_web_research_runtime import (  # noqa: F401
    EXCERPT, FINAL, PAGE_URL, PUBLIC_QUERY, complete, create_web, runtime_env,
)
from test_web_search import public_resolver, response


def test_searxng_runtime_sends_only_public_query_to_selected_provider(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    private_question = "합성 비공개 개인 이력과 재무 기록"
    calls = []

    def handler(request):
        calls.append(request)
        assert private_question not in str(request.url) + str(request.headers) + request.content.decode()
        assert "X-Subscription-Token" not in request.headers
        if request.url.host == "searxng.local":
            assert dict(request.url.params) == {"q": PUBLIC_QUERY, "format": "json"}
            return response({"results": [{"url": PAGE_URL, "content": "unproven snippet"}]})
        assert request.url.host == "93.184.216.34"
        assert request.headers["Host"] == "example.com"
        return response(EXCERPT, content_type="text/plain")

    original_init = WebSearchService.__init__

    def network(self, *args, **kwargs):
        original_init(self, *args, **kwargs, transport=httpx.MockTransport(handler), resolver=public_resolver)

    monkeypatch.setattr(WebSearchService, "__init__", network)
    monkeypatch.setattr(config, "settings", replace(config.settings, web_search_provider="searxng",
        searxng_url="http://searxng.local:8080", web_search_api_key="synthetic-unused-key"))
    provider.replies.append({**FINAL, "answer": f"공개 채용 본문을 확인했습니다. [출처]({PAGE_URL})"})
    done = complete(client, database, create_web(client, message=private_question))
    assert done["status"] == "completed", done
    assert len(calls) == 2
    assert done["result"]["context"]["web_sources"][0]["url"] == PAGE_URL
