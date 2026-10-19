"""Production proxy denies unapproved hosts and alternate ports before networking."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("local_egress", Path(__file__).parents[1] / "docker/egress/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


@pytest.mark.parametrize("target", ["example.com:443", "api.openai.com:80", "api.openai.com.evil.example:443", "127.0.0.1:443", "auth.openai.com:8443"])
def test_proxy_denies_destination_before_opening_socket(monkeypatch, target):
    connect = Mock()
    monkeypatch.setattr(proxy.socket, "create_connection", connect)
    request = object.__new__(proxy.Proxy)
    request.path = target
    request.send_error = Mock()
    request.do_CONNECT()
    request.send_error.assert_called_once_with(403, "Destination is not allowed")
    connect.assert_not_called()


def test_google_sheets_transport_can_use_production_egress_proxy(monkeypatch):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://egress:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,db,embeddings")
    # Bundled discovery and synthetic credentials: no Google request or private data.
    service = build("sheets", "v4", credentials=Credentials(token="synthetic"), cache_discovery=False)
    proxy_info = service._http.http.proxy_info("https")
    assert proxy_info is not None
    assert proxy_info.isgood(), "Google Sheets proxy support must be installed in production"
    assert (proxy_info.proxy_host, proxy_info.proxy_port) == ("egress", 3128)
    assert proxy_info.applies_to("sheets.googleapis.com")
    assert not proxy_info.applies_to("127.0.0.1")
