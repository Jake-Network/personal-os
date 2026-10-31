"""Backend for browser E2E tests: the real app with a deterministic fake model provider.

Never use this for real data. It refuses to start unless DATABASE_URL names a database ending
in `_e2e`, and it never contacts a model provider. The fake answers each structured step of
the consultation graph from the schema title in the prompt, so flows run end to end without
an LLM. Production code is unchanged; everything here is patched at process start.

    DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:55432/personal_os_e2e \\
    FRONTEND_URL=http://127.0.0.1:5174 OAUTH_CALLBACK_PORT=18000 \\
    uv run python scripts/e2e_server.py --reset
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATABASE = urlsplit(os.environ.get("DATABASE_URL", "")).path.rsplit("/", 1)[-1]
if not DATABASE.endswith("_e2e"):
    sys.exit("e2e_server: DATABASE_URL must name a disposable database ending in '_e2e'")

if "--reset" in sys.argv:
    # Only the guarded `_e2e` database is wiped; the app migrates the empty schema on start.
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    engine.dispose()

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from app.modules.auth.oauth_manager import oauth_manager  # noqa: E402
from app.modules.llm import transfer_policy  # noqa: E402
from app.modules.llm.llm_gateway_manager import llm_gateway_manager  # noqa: E402
from app.modules.llm.types import StreamEvent  # noqa: E402

SCHEMA = re.compile(r"JSON 객체만 반환하세요\. 스키마: (\{.*)", re.S)
E2E_TASK = "E2E 합성 할 일"
REPLIES = {
    "DataCommandPlan": {"commands": [], "message": ""},
    "Plan": {"objective": "합성 질문 확인", "tasks": []},
    "Review": {"valid": True},
    "HistorySummary": {"content": "합성 요약"},
    "FinalAnswer": {
        "answer": "합성 답변입니다. 이번 주에 할 일 하나를 제안합니다.",
        "proposals": [{"action": "create_task", "payload": {"title": E2E_TASK}, "rationale": "합성 제안"}],
        "memories": [],
    },
}


def _schema_title(request) -> str | None:
    texts = [request.instructions, *(str(item.get("content", "")) for item in request.input)]
    for text in texts:
        match = SCHEMA.search(text or "")
        if match:
            try:
                return json.JSONDecoder().raw_decode(match.group(1))[0].get("title")
            except ValueError:
                return None
    return None


class E2EProvider:
    name = "chatgpt_plan"

    async def list_models(self, session):
        return ["e2e-fake-model"]

    async def stream(self, session, request):
        title = _schema_title(request)
        if request.json_mode or title:
            text = json.dumps(REPLIES.get(title, {}), ensure_ascii=False)
        else:
            text = "연결됨"
        yield StreamEvent("delta", text=text)
        yield StreamEvent("completed", usage={"input_tokens": 1, "output_tokens": 1})


llm_gateway_manager.providers["chatgpt_plan"] = E2EProvider()
oauth_manager.status = lambda session: {"connected": True, "status": "connected", "email": "e2e@example.invalid",
                                        "display_name": "E2E", "plan_usage_enabled": True, "scopes": [],
                                        "access_expires_at": None, "last_error_code": None, "usage_url": ""}
transfer_policy.account_binding = lambda session, provider: "e2e-account" if provider == "chatgpt_plan" else None

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("OAUTH_CALLBACK_PORT", "18000")), log_level="warning")
