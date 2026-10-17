"""The unauthenticated API only answers local callers: no DNS rebinding, no cross-site writes."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.database.model import ProposedAction
from app.modules.security.local_trust_middleware import LocalTrustMiddleware


@pytest.fixture
def proposal(session):
    p = ProposedAction(action="create_task", payload={"title": "t"}, status="pending")
    session.add(p)
    session.commit()
    return p.id


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "localhost.evil.example"])
def test_rebound_hostnames_are_refused(client, host):
    assert client.get("/api/health", headers={"host": host}).status_code == 421


def test_proxy_forwarded_host_is_checked_too(client):
    assert client.get("/api/health", headers={"x-forwarded-host": "evil.example:5173"}).status_code == 421
    assert client.get("/api/health", headers={"x-forwarded-host": "127.0.0.1:5173"}).status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://203.0.113.5"])
def test_cross_site_writes_are_refused_and_change_nothing(client, session, proposal, origin):
    res = client.post(f"/api/proposals/{proposal}/approve", headers={"origin": origin})
    assert res.status_code == 403
    session.expire_all()
    assert session.get(ProposedAction, proposal).status == "pending"


def test_cross_site_fetch_metadata_without_origin_is_refused(client, proposal):
    res = client.post(f"/api/proposals/{proposal}/reject", headers={"sec-fetch-site": "cross-site"})
    assert res.status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5173"])
def test_local_frontend_writes_are_allowed(client, proposal, origin):
    assert client.post(f"/api/proposals/{proposal}/reject", headers={"origin": origin}).status_code == 204


def test_same_origin_through_proxy_on_a_lan_ip_is_allowed(client, proposal):
    # Windows reaching the WSL Next server by its IP: Origin and forwarded host agree.
    headers = {"origin": "http://172.20.1.5:5173", "x-forwarded-host": "172.20.1.5:5173"}
    assert client.post(f"/api/proposals/{proposal}/reject", headers=headers).status_code == 204


def test_reads_without_origin_still_work(client):
    assert client.get("/api/health").status_code == 200


def test_operator_listed_hostnames_are_allowed():
    app = FastAPI()
    app.get("/ok")(lambda: {"ok": True})
    app.add_middleware(LocalTrustMiddleware, frontend_url="https://os.home.arpa",
                       allowed_hosts=("os.home.arpa",))
    with TestClient(app, base_url="https://os.home.arpa") as c:
        assert c.get("/ok").status_code == 200
        assert c.post("/ok", headers={"origin": "https://os.home.arpa"}).status_code == 405  # passed the check
        assert c.get("/ok", headers={"host": "other.home.arpa"}).status_code == 421
