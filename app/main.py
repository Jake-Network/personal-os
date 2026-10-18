from contextlib import asynccontextmanager, suppress
import asyncio

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.modules.database import db
from app.modules.llm.errors import AdvisorError
from app.router import (
    advisor_router,
    ai_provider_router,
    dashboard_router,
    health_router,
    memory_router,
    oauth_callback_router,
    personal_data_router,
    privacy_router,
    proposal_router,
    portfolio_router,
    google_oauth_router,
    document_router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if db.engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db.init(settings.resolved_database_url)
        db.migrate_schema()
    from app.modules.documents.document_manager import process_pending
    stop = asyncio.Event()
    worker = asyncio.create_task(process_pending(db, stop))
    try:
        yield
    finally:
        stop.set()
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


def _operation_id(route: APIRoute) -> str:
    # Handler name as operationId so orval generates `listConversations`, not `listConversationsApiAdvisor...Get`.
    # Google connection handlers share names with AI settings handlers.
    if "google-sheets" in route.tags:
        return f"google_sheets_{route.name}"
    return route.name


app = FastAPI(title="Personal OS", version="0.2.0", lifespan=lifespan, generate_unique_id_function=_operation_id)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(AdvisorError)
async def advisor_error_handler(_request: Request, exc: AdvisorError):
    return JSONResponse(status_code=exc.http_status, content=exc.as_dict())


for module in (health_router, oauth_callback_router, ai_provider_router, privacy_router, advisor_router,
               proposal_router, memory_router, personal_data_router, dashboard_router, portfolio_router, google_oauth_router, document_router):
    app.include_router(module.router)
