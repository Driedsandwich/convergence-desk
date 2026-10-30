"""All inputs are synthetic; tests prohibit accidental network access."""

import json
from pathlib import Path
import socket

import pytest

from convergence_desk.core import snapshot_from_json


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access is forbidden in core tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def snapshot():
    path = Path(__file__).parent / "fixtures" / "synthetic_test_engine_inputs.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["synthetic_for_tests"] is True
    return snapshot_from_json(data)
