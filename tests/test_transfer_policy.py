"""Unconfirmed/changed accounts never reach even a fake outbound provider."""
import asyncio

import pytest

from app.modules.database.model import OAuthConnection
from app.modules.llm import transfer_policy
from app.modules.llm.llm_gateway_manager import LLMGatewayManager
from app.modules.llm.types import LLMRequest


class Capture:
    name = 'chatgpt_plan'
    called = False

    async def stream(self, session, request):
        self.called = True
        yield None


def connection(session, subject='synthetic-a'):
    conn = OAuthConnection(provider='chatgpt', status='connected', issuer='https://auth.openai.com',
        subject=subject, client_id='synthetic-client', ext_agent_host_id='synthetic-host',
        plan_usage_enabled=True)
    session.add(conn)
    session.commit()
    return conn


def test_confirmation_is_bound_to_current_account_and_revocable(session):
    conn = connection(session)
    assert not transfer_policy.status(session, 'chatgpt_plan')['confirmed']
    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
    assert transfer_policy.status(session, 'chatgpt_plan')['confirmed']
    conn.subject = 'synthetic-b'
    session.commit()
    assert not transfer_policy.status(session, 'chatgpt_plan')['confirmed']
    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
    transfer_policy.invalidate(session)
    assert not transfer_policy.status(session, 'chatgpt_plan')['confirmed']


def test_gateway_blocks_before_provider_receives_payload(session):
    connection(session)
    capture = Capture()
    gateway = LLMGatewayManager({'chatgpt_plan': capture})
    async def collect():
        return [event async for event in gateway.stream(session, LLMRequest(model='fake', instructions='', input=[]))]
    with pytest.raises(transfer_policy.TransferNotConfirmed):
        asyncio.run(collect())
    assert capture.called is False


def test_disconnected_and_api_key_rotation_invalidate_confirmation(session, monkeypatch):
    conn = connection(session)
    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
    conn.status = 'disconnected'
    session.commit()
    assert not transfer_policy.status(session, 'chatgpt_plan')['confirmed']
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key-a')
    transfer_policy.confirm(session, 'openai_api_key', True, True)
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key-b')
    assert not transfer_policy.status(session, 'openai_api_key')['confirmed']
    assert 'synthetic-key' not in str(transfer_policy.status(session, 'openai_api_key'))


@pytest.mark.parametrize('during_retry', [False, True])
def test_oauth_refresh_rechecks_transfer_revocation_before_sending(session, during_retry):
    from app.modules.llm.providers import ChatGPTPlanProvider
    from app.modules.llm.errors import AuthRequired
    from app.modules.llm.types import StreamEvent

    conn = connection(session)
    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
    sent = []

    class OAuth:
        async def access_token(self, session, force_refresh=False):
            if force_refresh == during_retry:
                transfer_policy.invalidate(session)
                session.commit()
            return conn, 'synthetic-token'

    class Client:
        async def stream(self, token, request):
            sent.append(request)
            if during_retry and len(sent) == 1:
                raise AuthRequired()
            yield StreamEvent('completed', usage={})

    provider = ChatGPTPlanProvider(OAuth(), Client())
    gateway = LLMGatewayManager({'chatgpt_plan': provider})
    async def collect():
        return [event async for event in gateway.stream(session, LLMRequest(
            model='fake', instructions='', input=[{'role': 'user', 'content': 'synthetic private record'}]))]
    with pytest.raises(transfer_policy.TransferNotConfirmed):
        asyncio.run(collect())
    assert len(sent) == (1 if during_retry else 0)


def test_account_switch_during_token_resolution_cannot_authorize_old_account_token(session):
    from app.modules.llm.providers import ChatGPTPlanProvider
    from app.modules.llm.types import StreamEvent

    first_account = connection(session, 'synthetic-account-a')
    transfer_policy.confirm(session, 'chatgpt_plan', True, True)
    sent = []

    class OAuth:
        async def access_token(self, session, force_refresh=False):
            connection(session, 'synthetic-account-b')
            transfer_policy.confirm(session, 'chatgpt_plan', True, True)
            return first_account, 'synthetic-account-a-token'

    class Client:
        async def stream(self, token, request):
            sent.append((token, request))
            yield StreamEvent('completed', usage={})

    gateway = LLMGatewayManager({'chatgpt_plan': ChatGPTPlanProvider(OAuth(), Client())})
    async def collect():
        return [event async for event in gateway.stream(session, LLMRequest(
            model='fake', instructions='', input=[{'role': 'user', 'content': 'synthetic private record'}]))]
    with pytest.raises(transfer_policy.TransferNotConfirmed):
        asyncio.run(collect())
    assert sent == []
    assert transfer_policy.status(session, 'chatgpt_plan')['confirmed']
