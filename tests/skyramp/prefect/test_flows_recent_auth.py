# In-process auth test for GET /api/flows/recent.
# The live SUT runs without PREFECT_SERVER_API_AUTH_STRING, so this builds the API app
# in-process under temporary_settings (same pattern as tests/server/test_app.py) and checks
# that the token_validation middleware also guards the new route.
# Needs the repo environment (prefect importable), e.g. `uv run pytest <this file>`.

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from prefect.server.api.server import create_app
from prefect.settings import PREFECT_SERVER_API_AUTH_STRING, temporary_settings

AUTH_STRING = "admin:test"


@pytest.fixture()
def anonymous_client() -> Generator[TestClient, None, None]:
    with temporary_settings({PREFECT_SERVER_API_AUTH_STRING: AUTH_STRING}):
        app = create_app(ignore_cache=True)
        yield TestClient(app)


def test_recent_requires_auth(anonymous_client: TestClient):
    response = anonymous_client.get("/api/flows/recent")
    assert response.status_code == 401
    assert response.json() == {"exception_message": "Unauthorized"}


def test_flow_by_id_requires_auth_baseline(anonymous_client: TestClient):
    response = anonymous_client.get(f"/api/flows/{uuid4()}")
    assert response.status_code == 401


def test_recent_wrong_credentials_rejected(anonymous_client: TestClient):
    response = anonymous_client.get(
        "/api/flows/recent", headers={"Authorization": "Basic d3Jvbmc6Y3JlZHM="}
    )
    assert response.status_code == 401
