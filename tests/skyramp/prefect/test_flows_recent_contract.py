# Contract tests for GET /api/flows/recent and the neighbouring /api/flows/{id} routes.
# Scaffolded with skyramp_contract_test_generation (GET /api/flows/recent), refined by hand.

import json
import os
import uuid
from datetime import datetime

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


@pytest.fixture
def created_flows(client):
    """Tracks flows created by a test and deletes them afterwards."""
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


def _create_flows(client, created_flows, prefix, n):
    return [
        _create_flow(client, created_flows, f"{prefix}-{RUN}-{i:02d}")
        for i in range(1, n + 1)
    ]


def _ts(value):
    # ISO-8601 (trailing Z is parsed as UTC on Python >=3.11)
    return datetime.fromisoformat(value)


def _get_recent(client, query_params=None):
    response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
        query_params=query_params,
    )
    assert response.status_code == 200
    body = json.loads(response.response_body)
    assert isinstance(body, list)
    return body


def test_recent_order_desc(client, created_flows):
    _create_flows(client, created_flows, "order", 2)
    body = _get_recent(client)
    assert len(body) >= 2
    created = [item["created"] for item in body]
    # every adjacent pair is created-descending
    assert all(_ts(created[i]) >= _ts(created[i + 1]) for i in range(len(created) - 1))


def test_recent_schema_keys(client, created_flows):
    new = _create_flow(client, created_flows, f"schema-keys-{RUN}")
    body = _get_recent(client)
    assert body[0]["id"] == new["id"]
    assert ",".join(sorted(body[0].keys())) == "created,id,labels,name,tags,updated"


def test_recent_ignores_limit(client, created_flows):
    _create_flows(client, created_flows, "limit", 11)
    body = _get_recent(client, query_params={"limit": "50"})
    assert len(body) == 10


def test_recent_ignores_offset(client, created_flows):
    flows = _create_flows(client, created_flows, "offset", 11)
    f11 = flows[-1]
    body = _get_recent(client, query_params={"offset": "5"})
    assert len(body) == 10
    assert body[0]["id"] == f11["id"]


def test_recent_ignores_sort(client, created_flows):
    # created first -> 'z-…', created last -> 'q-…', so NAME_ASC differs from created-desc
    flows = [_create_flow(client, created_flows, f"{c}-{RUN}") for c in "zyxwvutsrq"]
    expected_ids = [f["id"] for f in reversed(flows)]
    body = _get_recent(client, query_params={"sort": "NAME_ASC"})
    assert len(body) == 10
    assert ",".join(item["id"] for item in body) == ",".join(expected_ids)


def test_recent_malformed_param_ignored(client):
    response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
        query_params={"limit": "abc"},
    )
    assert response.status_code == 200
    assert isinstance(json.loads(response.response_body), list)


def test_route_uuid_still_resolves(client, created_flows):
    created = _create_flow(client, created_flows, f"uuid-route-{RUN}")
    response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="GET",
        headers=_headers(),
        path_params={"id": created["id"]},
    )
    assert response.status_code == 200
    body = json.loads(response.response_body)
    assert isinstance(body, dict)
    assert body["id"] == created["id"]
    assert body["name"] == f"uuid-route-{RUN}"


def test_route_non_uuid_404(client):
    response = client.send_request(
        url=URL,
        path="/api/flows/not-a-uuid",
        method="GET",
        headers=_headers(),
    )
    assert response.status_code == 404
