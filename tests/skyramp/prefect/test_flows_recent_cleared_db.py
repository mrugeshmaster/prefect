# Tests for GET /api/flows/recent and GET /api/flows/name/{name} that need an empty flows table.
# DESTRUCTIVE: each test empties the flows table via POST /api/flows/bulk_delete (which also
# deletes the flows' deployments and cascades to flow runs). Run only against a disposable SUT.
# Scaffolded with skyramp_contract_test_generation / skyramp_integration_test_generation,
# refined by hand. Tests run in file order: route-name-recent-404 precedes route-name-recent-found.

import json
import os
import uuid

import pytest
import skyramp

URL = skyramp.get_base_url("SKYRAMP_TEST_BASE_URL", "http://localhost:4200")
RUN = uuid.uuid4().hex[:8]


def _headers():
    headers = {}
    if os.getenv("SKYRAMP_TEST_TOKEN") is not None:
        headers["Authorization"] = "Bearer " + os.getenv("SKYRAMP_TEST_TOKEN")
    return headers


@pytest.fixture
def client():
    return skyramp.Client()


def _count_flows(client):
    response = client.send_request(
        url=URL,
        path="/api/flows/count",
        method="POST",
        body="{}",
        headers=_headers(),
    )
    assert response.status_code == 200
    return int(json.loads(response.response_body))


@pytest.fixture
def empty_flows(client):
    """Empties the flows table: bulk_delete (max 50 per call) until count returns 0."""
    for _ in range(1000):
        if _count_flows(client) == 0:
            break
        response = client.send_request(
            url=URL,
            path="/api/flows/bulk_delete",
            method="POST",
            body=json.dumps({"limit": 50}),
            headers=_headers(),
        )
        assert response.status_code == 200
    assert _count_flows(client) == 0
    yield


@pytest.fixture
def created_flows(client):
    ids = []
    yield ids
    for flow_id in ids:
        client.send_request(
            url=URL,
            path="/api/flows/{id}",
            method="DELETE",
            headers=_headers(),
            path_params={"id": flow_id},
        )


def _create_flow(client, created_flows, name):
    response = client.send_request(
        url=URL,
        path="/api/flows/",
        method="POST",
        body=json.dumps({"name": name}),
        headers=_headers(),
    )
    assert response.status_code == 201
    body = json.loads(response.response_body)
    created_flows.append(body["id"])
    return body


def test_recent_empty(client, empty_flows):
    response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
    )
    assert response.status_code == 200
    body = json.loads(response.response_body)
    assert isinstance(body, list)
    assert len(body) == 0


def test_recent_fewer_than_10(client, empty_flows, created_flows):
    f1 = _create_flow(client, created_flows, f"few-{RUN}-1")
    f2 = _create_flow(client, created_flows, f"few-{RUN}-2")
    f3 = _create_flow(client, created_flows, f"few-{RUN}-3")
    response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
    )
    assert response.status_code == 200
    body = json.loads(response.response_body)
    assert len(body) == 3
    assert ",".join(item["id"] for item in body) == ",".join(
        [f3["id"], f2["id"], f1["id"]]
    )


def test_route_name_recent_404(client, empty_flows):
    response = client.send_request(
        url=URL,
        path="/api/flows/name/recent",
        method="GET",
        headers=_headers(),
    )
    assert response.status_code == 404
    assert not isinstance(json.loads(response.response_body), list)


def test_route_name_recent_found(client, empty_flows, created_flows):
    created = _create_flow(client, created_flows, "recent")
    response = client.send_request(
        url=URL,
        path="/api/flows/name/recent",
        method="GET",
        headers=_headers(),
    )
    assert response.status_code == 200
    body = json.loads(response.response_body)
    assert isinstance(body, dict)
    assert body["id"] == created["id"]
    assert body["name"] == "recent"
