"""LangChain interfaces backed exclusively by the existing authorized gateway."""
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class GatewayChatModel(BaseChatModel):
    """Text-only adapter: native function calling is intentionally unavailable.

    The adapter never translates arbitrary LangChain messages into provider input.
    ContextAssembler owns the complete validated request on every invocation.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _gateway: Any = PrivateAttr()
    _session: Any = PrivateAttr()
    _request: Any = PrivateAttr()
    _conversation_id: int = PrivateAttr()
    _on_delta: Any = PrivateAttr()

    def __init__(self, gateway, session, request, conversation_id, on_delta=None, **kwargs):
        super().__init__(**kwargs)
        self._gateway, self._session, self._request = gateway, session, request
        self._conversation_id = conversation_id
        self._on_delta = on_delta

    @property
    def _llm_type(self):
        return 'personal-os-gateway'

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError('Use the asynchronous gateway')

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        if messages or stop or kwargs:
            raise ValueError('Only the ContextAssembler request can be sent')
        chunks = []
        async for event in self._gateway.stream(self._session, self._request, conversation_id=self._conversation_id):
            if event.type == 'delta':
                chunks.append(event.text)
                if self._on_delta and event.text:
                    await self._on_delta(event.text)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=''.join(chunks)))])


class ReadInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=4000)


def read_tools(assembler):
    """Expose only data already filtered and snapshotted by domain services."""
    from app.modules.context.context_tool_manager import CATEGORY_TOOLS
    registry = {}
    for category, tools in CATEGORY_TOOLS.items():
        for name, _ in tools:
            async def read(query, _name=name, _category=category):
                _, package = await assembler.assemble(query)
                if str(_category) not in package.categories:
                    raise ValueError('도구에 필요한 공유 범위가 허용되지 않았습니다')
                return {'data': package.payload.get('data', {}).get(_name),
                        'snapshot_id': package.snapshot_id,
                        'data_quality_flags': package.data_quality_flags}
            registry[name] = StructuredTool.from_function(
                coroutine=read, name=name, description=f'허용된 {_category_label(category)} 근거 조회', args_schema=ReadInput)

    async def documents(query):
        _, package = await assembler.assemble(query)
        return {'data': package.payload.get('data', {}).get('search_documents', {}),
                'snapshot_id': package.snapshot_id, 'data_quality_flags': package.data_quality_flags}

    async def history(query):
        _, package = await assembler.assemble(query)
        return {'data': {'messages': assembler.last_history,
                         'experiences': package.payload.get('data', {}).get('search_past_experiences', {})},
                'snapshot_id': package.snapshot_id, 'data_quality_flags': package.data_quality_flags}

    registry['search_documents'] = StructuredTool.from_function(coroutine=documents, name='search_documents',
        description='현재 공유 범위에서 문서를 검색하고 버전·발췌·인용 출처를 반환', args_schema=ReadInput)
    registry['search_history'] = StructuredTool.from_function(coroutine=history, name='search_history',
        description='공유 가능한 과거 대화·요약·결정을 검색. 당시 정보이며 현재 사실로 재사용하지 않음', args_schema=ReadInput)
    return registry


def _category_label(category):
    return str(category)
