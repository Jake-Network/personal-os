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
