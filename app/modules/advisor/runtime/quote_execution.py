"""A quote worker owns its sessions; the graph never shares its ORM session."""
import asyncio
from copy import deepcopy


def _refresh_owned(session_factory, *, run_id, owner, generation, authorization,
                   sources, options, model, client_factory=None):
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.quote_refresh import refresh_quotes
    from app.modules.advisor.runtime.persistence import RunRepository, LeaseLost
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.base import utcnow
    from sqlalchemy import select
    from app.modules.advisor.runtime.authorization import require
    from app.modules.agent.briefing import require_run_authorized
    from app.modules.context.source_policy import require_live_request_sources
    from app.modules.llm.types import LLMRequest

    def check(session, *, for_write=False):
        if for_write:
            run = RunRepository(session).fence(run_id, owner, generation)
        else:
            run = session.scalar(select(AdvisorRun).where(AdvisorRun.id == run_id,
                AdvisorRun.lease_owner == owner, AdvisorRun.lease_generation == generation,
                AdvisorRun.status == 'running', AdvisorRun.lease_until > utcnow()))
            if run is None:
                raise LeaseLost(run_id)
        require(session, authorization)
        require_run_authorized(session, run)
        excluded = advisor_manager.sharing_exclusions(session, options)
        for source in sources:
            require_live_request_sources(session, LLMRequest(
                model=model, instructions='', input=[], source_snapshot_id=source,
                excluded_categories=tuple(str(category) for category in excluded)), outbound=False)
        return excluded

    # This context and every access to quote_session are confined to this thread.
    with session_factory() as quote_session:
        def read_authorization():
            # Rechecking authorization must never commit pending price/FX writes.
            with session_factory() as checking:
                check(checking)
                checking.commit()

        def write_authorization():
            # The fence remains in the same transaction as result/audit writes.
            check(quote_session, for_write=True)

        read_authorization()
        excluded = advisor_manager.sharing_exclusions(quote_session, options)
        client_options = {'client': client_factory(quote_session)} if client_factory else {}
        return refresh_quotes(quote_session, excluded=excluded,
            authorization_check=read_authorization, write_authorization_check=write_authorization, **client_options)


async def execute_quote_refresh(session_factory, **arguments):
    """Finish the owned thread before cancellation closes its composition scope."""
    arguments = {**arguments, 'authorization': deepcopy(arguments['authorization']),
                 'sources': tuple(arguments['sources'])}
    task = asyncio.create_task(asyncio.to_thread(_refresh_owned, session_factory, **arguments))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # More than one shutdown/cancel signal must not detach the owned thread.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()  # Consume a provider error while preserving cancellation.
        raise
