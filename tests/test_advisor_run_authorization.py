"""Run authority is rechecked after token I/O, independently of browser lifetime."""
import asyncio
from datetime import timedelta

import pytest
from fastapi import Response

from app.modules.crud import app_setting_handler
from app.modules.database.model import AppSession, OAuthConnection
from app.modules.database.model.base import utcnow
from app.modules.llm import run_policy, transfer_policy
from app.modules.llm.errors import AdvisorError, AuthRequired
from app.modules.llm.llm_gateway_manager import LLMGatewayManager, MODEL_KEY, PROVIDER_KEY
from app.modules.llm.providers import ChatGPTPlanProvider
from app.modules.llm.types import LLMRequest, StreamEvent
from app.modules.security import session_manager
from app.router.security_router import lock_security


@pytest.mark.parametrize('during_retry', [False, True])
@pytest.mark.parametrize('change', ['provider', 'model', 'lock', 'account', 'browser_expiry'])
def test_run_authority_at_token_refresh_boundary(session, during_retry, change):
    connection = OAuthConnection(provider='chatgpt', status='connected',
        issuer='https://auth.openai.com', subject='synthetic-run-account',
        client_id='synthetic-client', ext_agent_host_id='synthetic-host', plan_usage_enabled=True)
    session.add(connection)
    session.commit()
    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
    token = session_manager.new_session(session)
    authorization = run_policy.capture(session)
    sent = []

    class OAuth:
        async def access_token(self, session, force_refresh=False):
            if force_refresh == during_retry:
                if change == 'provider':
                    app_setting_handler.set_value(session, PROVIDER_KEY, {'name': 'openai_api_key'})
                elif change == 'model':
                    app_setting_handler.set_value(session, MODEL_KEY, {'name': 'synthetic-new-model'})
                elif change == 'lock':
                    lock_security(Response(), session)
                elif change == 'account':
                    connection.subject = 'synthetic-other-account'
                    session.commit()
                    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
                else:
                    browser = session.get(AppSession, session_manager.digest(token))
                    browser.last_activity_at = utcnow() - timedelta(hours=1)
                session.commit()
            return connection, 'synthetic-access-token'

    class Client:
        async def stream(self, token, request):
            sent.append(request)
            if during_retry and len(sent) == 1:
                raise AuthRequired()
            yield StreamEvent('completed', usage={})

    gateway = LLMGatewayManager({'chatgpt_plan': ChatGPTPlanProvider(OAuth(), Client())})
    request = LLMRequest(model='synthetic-model', instructions='',
        input=[{'role': 'user', 'content': 'synthetic private record'}], authorization=authorization)

    async def collect():
        return [event async for event in gateway.stream(session, request)]

    if change == 'browser_expiry':
        assert asyncio.run(collect())[-1].type == 'completed'
        assert len(sent) == (2 if during_retry else 1)
        assert session_manager.active_session(session, token) is None
    else:
        with pytest.raises(AdvisorError):
            asyncio.run(collect())
        # An initial 401 can precede revocation; no second payload may follow it.
        assert len(sent) == (1 if during_retry else 0)
        if change == 'lock':
            assert session_manager.active_session(session, token) is None
