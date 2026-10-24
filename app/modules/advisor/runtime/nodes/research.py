"""Parallel read-tool research and the explicitly allowed web search."""
from langgraph.types import Send
from langsmith import tracing_context

from app.modules.advisor.runtime.nodes.planning import signature
from app.modules.advisor.runtime.schemas import ResearchTask


def pending_tasks(state):
    return [task for task in state['plan']['tasks'] if state.get('results', {}).get(task['id']) is None]


def dispatch(state):
    done = {key for key, value in state.get('results', {}).items() if value is not None}
    tasks = state['plan']['tasks']
    ready = [t for t in tasks if t['id'] not in done and set(t['depends_on']) <= done]
    if not ready:
        return 'analyze'
    return [Send('research', {'task': task, 'query': state['query'], 'sources': state.get('sources', []),
        'execution_id': f"{task['id']}:{state['replans']}:{signature(task)}"}) for task in ready]


async def research(ctx, state):
    task = ResearchTask.model_validate(state['task'])
    await ctx.progress('research_started', task_id=task.id, tool=task.tool)
    ctx.assembler.baseline_snapshot_id = None
    # Calls share an ORM Session, so ContextAssembler serializes its DB access.
    with tracing_context(enabled=False):
        result = await ctx.tools[task.tool].ainvoke({'query': task.query}, config={'callbacks': []})
    await ctx.progress('research_finished', task_id=task.id, tool=task.tool)
    return {'results': {task.id: result}, 'tool_executions': {state['execution_id']: True}}


def collected(ctx, state):
    sources = [r['snapshot_id'] for r in state['results'].values() if r is not None]
    return {'tool_calls': len(state.get('tool_executions', {})),
            'sources': list(dict.fromkeys([*state['sources'], *sources]))}


async def web_research(ctx, state):
    await ctx.progress('web_searching')
    snapshot_id = await ctx.assembler.search_web()
    return {'web_snapshot_id': snapshot_id, 'sources': [*state['sources'], snapshot_id],
            'tool_calls': state['tool_calls'] + 1, 'tool_executions': {'web_search': True},
            'single_response': False}
