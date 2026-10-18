"""Public consultation entry point; HTTP observes work owned by the server."""
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.types import AskOptions
from app.modules.advisor.runtime import authorization
from app.modules.crud import message_handler
from app.modules.llm.llm_gateway_manager import llm_gateway_manager


class ConversationRuntime:
    def __init__(self, manager=advisor_manager):
        self.manager = manager

    async def create(self, session, conversation_id, body, *, single_response=False):
        from app.modules.advisor.runtime.persistence import RunRepository
        repository = RunRepository(session)
        # Idempotent retries must return the original run without resolving credentials again.
        from sqlalchemy import select
        from app.modules.database.model.advisor_runtime import AdvisorRun
        existing = session.scalar(select(AdvisorRun).where(
            AdvisorRun.conversation_id == conversation_id, AdvisorRun.request_id == body.request_id))
        if existing:
            return repository.create(conversation_id, body)
        try:
            conversation = self.manager.get_conversation(session, conversation_id)
        except LookupError as exc:
            from fastapi import HTTPException
            raise HTTPException(404, '상담을 찾을 수 없습니다.') from exc
        self.manager.preview(session, body.message, conversation, body.options())
        auth = authorization.capture(session)
        model = await llm_gateway_manager.resolve_model(session)
        run = repository.create(conversation_id, body)
        run.provider, run.model, run.account_binding = auth['provider'], model, auth['account_binding']
        run.authorization = auth
        run.runtime_metadata = {**(run.runtime_metadata or {}), 'single_response': single_response}
        session.commit()
        return run

    def preview(self, *args, **kwargs):
        return self.manager.preview(*args, **kwargs)

    async def single_response(self, session, conversation, query, options=None):
        """Legacy event shape observing the same graph and gateway token stream."""
        import asyncio
        from contextlib import suppress
        from langsmith import tracing_context
        from app.modules.advisor.runtime.graph import build_conversation_graph, initial_state
        from app.modules.advisor.proposals import extract_blocks
        from app.modules.advisor.proposal_manager import proposal_manager
        from app.modules.llm.errors import AdvisorError
        options = options or AskOptions()
        user, task = None, None
        parts, snapshot_id, model = [], None, None
        queue = asyncio.Queue()

        async def emit(event):
            await queue.put(event)

        try:
            model = await self.manager.gateway.resolve_model(session)
            graph = build_conversation_graph(session, self.manager, conversation, options, model, on_stream=emit)

            async def execute():
                try:
                    with tracing_context(enabled=False):
                        result = await graph.ainvoke(initial_state(query, single_response=True))
                    await queue.put({'type': '_result', 'state': result})
                except BaseException as exc:
                    await queue.put({'type': '_exception', 'exception': exc})

            task = asyncio.create_task(execute())
            while True:
                event = await queue.get()
                if event['type'] == '_exception':
                    raise event['exception']
                if event['type'] == '_result':
                    state = event['state']
                    break
                if event['type'] == 'context':
                    snapshot_id = event.get('context_snapshot_id')
                    user = message_handler.create(session, {'conversation_id': conversation.id, 'role': 'user',
                        'content': query, 'context_snapshot_id': snapshot_id})
                    session.commit()
                elif event['type'] == 'delta':
                    parts.append(event['text'])
                yield event
            answer, proposals, memories = extract_blocks(state.get('answer', ''))
            reply = message_handler.create(session, {'conversation_id': conversation.id, 'role': 'assistant',
                'content': answer, 'context_snapshot_id': snapshot_id, 'model': model})
            actions, mems = proposal_manager.record(session, conversation.id, reply.id, proposals, memories)
            session.commit()
            user = None
            yield {'type': 'done', 'message_id': reply.id, 'context_snapshot_id': snapshot_id,
                   'proposals': [{'id': a.id, 'action': a.action, 'payload': a.payload, 'rationale': a.rationale} for a in actions],
                   'memory_proposals': [{'id': m.id, 'kind': m.kind, 'content': m.content} for m in mems]}
        except AdvisorError as exc:
            session.rollback()
            yield {'type': 'error', **exc.as_dict()}
        except Exception:
            session.rollback()
            yield {'type': 'error', **AdvisorError().as_dict()}
        finally:
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
            if user is not None:
                user.status = 'failed'
                if parts:
                    message_handler.create(session, {'conversation_id': conversation.id, 'role': 'assistant',
                        'content': ''.join(parts), 'status': 'incomplete', 'context_snapshot_id': snapshot_id, 'model': model})
                session.commit()


conversation_runtime = ConversationRuntime()
