from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def workspace_root(tmp_path, monkeypatch) -> Iterator:
    monkeypatch.setattr(settings, "MODEL_COUNCIL_WORKSPACE_ROOT", str(tmp_path))
    yield tmp_path


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
