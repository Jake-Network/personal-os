"""Per-run dependencies shared by consultation graph nodes."""
import inspect
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Callable

from langsmith import tracing_context

from app.modules.llm.errors import AdvisorError


PROGRESS_MESSAGES = {
    'planning': '질문과 필요한 근거를 확인하고 있습니다.',
    'research_started': '공유가 허용된 최신 기록을 확인하고 있습니다.',
    'research_finished': '기록 확인을 마쳤습니다.',
    'analyzing': '확인한 근거와 조건을 정리하고 있습니다.',
    'reviewing': '근거와 제약이 빠지지 않았는지 검토하고 있습니다.',
    'answering': '답변을 작성하고 있습니다. 검증을 마치면 표시합니다.',
    'model_finished': '모델 응답을 받았습니다. 결과를 확인하고 있습니다.',
    'structured_output_invalid': '응답 형식을 확인하고 다시 정리하고 있습니다.',
    'summarizing': '이전 대화에서 필요한 맥락을 정리하고 있습니다.',
    'loading_playbook': '선택한 상담 절차를 불러와 조사 계획에 반영하고 있습니다.',
    'web_searching': '허용한 공개 검색어로 웹 자료를 확인하고 있습니다.',
}


def structured_response(content, schema):
    """Accept one complete JSON object, optionally wrapped in a Markdown fence."""
    value = str(content).strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', value, re.I)
    if fenced:
        value = fenced.group(1).strip()
    return schema.model_validate_json(value)


def limits(state):
    """(model calls, tool calls, replans) allowed for the consultation depth."""
    return (12, 24, 3) if state.get('depth') == 'deep' else (6, 12, 2)


@dataclass
class NodeContext:
    session: Any
    manager: Any
    conversation: Any
    options: Any
    assembler: Any
    tools: dict
    chat_model: Callable
    current_message_id: int | None = None
    on_progress: Callable | None = None
    on_stream: Callable | None = None
    command_guard: Callable | None = None
    on_data_operations: Callable | None = None
    recorded_operations: list | None = None
    recorded_command_plan: list | None = None
    recorded_command_query: str | None = None
    recorded_command_source_ids: list | None = None
    data_commands_allowed: bool = True
    on_quote_refresh: Callable | None = None

    def __post_init__(self):
        self.base_options = self.options
        self.explicit_playbooks = bool(getattr(self.options, 'playbook_ids', ())
                                       or getattr(self.options, 'playbook_slugs', ()))

    def apply_playbooks(self, state):
        # A plan's choice persists in the checkpoint; a user's explicit choice always wins.
        if self.options is not None and not self.explicit_playbooks and state.get('playbook_slugs'):
            self.assembler.options = replace(self.base_options, playbook_slugs=tuple(state['playbook_slugs']))

    def playbook_catalog(self, query, exclude_slugs=()):
        if self.options is None or self.session is None:
            return {}, []
        from app.modules.playbooks.selection import catalog_context
        return catalog_context(self.session, self.manager.sharing_exclusions(self.session, self.options), query,
                               exclude_slugs=exclude_slugs)

    async def progress(self, stage, **metadata):
        if self.on_progress:
            if stage == 'model_started':
                message = ('답변을 작성하고 있습니다. 검증을 마치면 표시합니다.'
                           if metadata.get('schema') == 'FinalAnswer' else '질문에 필요한 내용을 검토하고 있습니다.')
            else:
                message = PROGRESS_MESSAGES.get(stage, '상담을 진행하고 있습니다.')
            await self.on_progress({'stage': stage, 'message': message, **metadata})

    async def call(self, state, instruction, schema=None, derived=None, history_source_ids=(), context_data=None,
                   context_flags=()):
        max_calls, _, _ = limits(state)
        self.assembler.baseline_snapshot_id = state.get('baseline_snapshot_id')
        attempts = 2 if schema else 1
        validation_errors = []
        self.apply_playbooks(state)
        self.assembler.run_catalog_refs = list(state.get('catalog_refs', []))
        for attempt in range(attempts):
            if state['model_calls'] >= max_calls:
                raise AdvisorError('상담 모델 호출 한도에 도달했습니다.', provider_code='analysis_budget_exceeded')
            state['model_calls'] += 1
            prompt = instruction
            if schema:
                prompt += '\nJSON 객체만 반환하세요. 스키마: ' + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            if attempt:
                prompt += '\n직전 출력이 스키마 검증에 실패했습니다. 스키마에 맞게 한 번 수정하세요.'
                prompt += '\n검증 오류(필드 경로와 오류 유형만): ' + json.dumps(validation_errors, ensure_ascii=False)
                prompt += '\n필수 필드와 자료형을 확인하고, 스키마에 없는 필드와 JSON 밖의 설명은 빼세요.'
            extra = {'history_source_ids': history_source_ids} if history_source_ids else {}
            if context_data or context_flags:
                extra.update(context_data=context_data, context_flags=context_flags)
            request, package = await self.assembler.assemble(state['query'], instruction=prompt,
                derived=derived, sources=state.get('sources', []), structured_output=schema is not None, **extra)
            state['sources'] = list(dict.fromkeys([*state.get('sources', []), package.snapshot_id]))
            state['snapshot_id'], state['context'] = package.snapshot_id, self.assembler.last_context
            offered = [{key: value for key, value in ref.items() if key != 'role'}
                       for ref in getattr(package, 'record_references', []) if ref.get('role') == 'catalog']
            if offered:
                state['catalog_refs'] = offered
            state['numeric_basis'] = getattr(package, 'payload', {}).get('data', {})
            async def stream_delta(text):
                if self.on_stream:
                    await self.on_stream({'type': 'delta', 'text': text})
            if state.get('single_response') and self.on_stream:
                await self.on_stream(state['context'])
            adapter = self.chat_model(self.manager.gateway, self.session, request, self.conversation.id,
                **({'on_delta': stream_delta} if state.get('single_response') and self.on_stream else {}))
            await self.progress('model_started', model_calls=state['model_calls'], snapshot_id=package.snapshot_id,
                                schema=schema.__name__ if schema else None)
            with tracing_context(enabled=False):
                response = await adapter.ainvoke([], config={'callbacks': []})
            await self.progress('model_finished', model_calls=state['model_calls'], snapshot_id=package.snapshot_id,
                                schema=schema.__name__ if schema else None)
            if schema is None:
                return str(response.content)
            try:
                return structured_response(response.content, schema)
            except ValueError as exc:
                # Content may contain private data; record only schema field names and error kinds.
                errors = exc.errors(include_input=False, include_context=False, include_url=False) if hasattr(exc, 'errors') else []
                validation_errors = [
                    {'type': item['type'], 'path': [str(part) for part in item['loc']
                        if not isinstance(part, str) or part in schema.model_fields]}
                    for item in errors[:8]]
                await self.progress('structured_output_invalid', schema=schema.__name__, attempt=attempt + 1,
                                    errors=validation_errors)
                if attempt == attempts - 1:
                    raise AdvisorError('모델의 구조화된 분석 결과를 검증하지 못했습니다.', provider_code='invalid_structured_output')


def bind(node, ctx):
    """Expose a ``node(ctx, state)`` function as a LangGraph ``node(state)``."""
    if inspect.iscoroutinefunction(node):
        async def bound(state):
            return await node(ctx, state)
    else:
        def bound(state):
            return node(ctx, state)
    bound.__name__ = node.__name__
    return bound
