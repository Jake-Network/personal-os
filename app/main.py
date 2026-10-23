from contextlib import asynccontextmanager, suppress
import asyncio
import os

from fastapi import FastAPI, Request
from sqlalchemy import inspect
from fastapi.routing import APIRoute
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.modules.database import db
from app.modules.llm.errors import AdvisorError
from app.modules.security.local_trust_middleware import LocalTrustMiddleware
from app.modules.security.app_auth_middleware import AppAuthMiddleware
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
    security_router,
    transfer_policy_router,
    career_router,
    reviews_router,
    jobs_router,
    market_data_router,
    advisor_runtime_router,
    locale_router,
    playbook_router,
    agent_router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("PERSONAL_OS_PRODUCTION", "").lower() == "true":
        from app.modules.security.deployment_checks import validate_local_services
        validate_local_services(settings.resolved_database_url, settings.embedding_url)
    if db.engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db.init(settings.resolved_database_url)
        db.migrate_schema()
    from app.modules.security.session_manager import revoke_all
    from app.modules.database.model import Base
    tables = set(inspect(db.engine).get_table_names())
    checkpoint_tables = {'checkpoints', 'writes'} if db.engine.dialect.name == 'sqlite' else {
        'checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations'}
    _app.state.security_schema_ready = (set(Base.metadata.tables) | checkpoint_tables).issubset(tables)
    if _app.state.security_schema_ready:
        with db.session() as session:
            revoke_all(session)
    from app.modules.documents.document_manager import process_pending
    from app.modules.jobs.job_manager import process_pending as process_jobs
    from app.modules.advisor.runtime.worker import process_pending as process_consultations
    from app.modules.agent.reflection import process_pending as process_reflections
    stop = asyncio.Event()
    workers = []
    if _app.state.security_schema_ready:
        workers = [asyncio.create_task(process_pending(db, stop)),
                   asyncio.create_task(process_jobs(db, stop)),
                   asyncio.create_task(process_consultations(db, stop)),
                   asyncio.create_task(process_reflections(db, stop))]
    try:
        yield
    finally:
        stop.set()
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with suppress(asyncio.CancelledError):
                await worker


def _operation_id(route: APIRoute) -> str:
    # Handler name as operationId so orval generates `listConversations`, not `listConversationsApiAdvisor...Get`.
    # Google connection handlers share names with AI settings handlers.
    if "google-sheets" in route.tags:
        return f"google_sheets_{route.name}"
    return route.name


app = FastAPI(title="Personal OS", version="0.2.0", lifespan=lifespan, generate_unique_id_function=_operation_id)
app.add_middleware(AppAuthMiddleware, frontend_url=settings.frontend_url)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# Added last so it runs first: reject rebound hosts and cross-site writes before anything else.
app.add_middleware(LocalTrustMiddleware, frontend_url=settings.frontend_url, allowed_hosts=settings.allowed_hosts)


@app.exception_handler(AdvisorError)
async def advisor_error_handler(_request: Request, exc: AdvisorError):
    return JSONResponse(status_code=exc.http_status, content=exc.as_dict())


for module in (health_router, oauth_callback_router, ai_provider_router, privacy_router, advisor_router,
               proposal_router, memory_router, personal_data_router, dashboard_router, portfolio_router, google_oauth_router, document_router, security_router,
               transfer_policy_router, career_router, reviews_router, jobs_router, market_data_router, advisor_runtime_router,
               locale_router, playbook_router, agent_router):
    app.include_router(module.router)
