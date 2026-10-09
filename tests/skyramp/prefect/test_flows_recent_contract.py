# Scaffolded by Skyramp v1.3.51 (skyramp generate contract rest
# http://localhost:4200/api/flows/recent --method GET --provider), then refined.
# Provider contract tests for GET /api/flows/recent.

# Import of required libraries
import json
import os

import pytest
import skyramp

# URL for test requests
URL = skyramp.get_base_url("SKYRAMP_TEST_BASE_URL", "http://localhost:4200")


def _headers() -> dict:
    # Definition of authentication header
    headers = {}
    if os.getenv("SKYRAMP_TEST_TOKEN") is not None:
        headers["Authorization"] = "Bearer " + os.getenv("SKYRAMP_TEST_TOKEN")
    return headers


def _delete_flow_by_name(client: skyramp.Client, name: str) -> None:
    by_name = client.send_request(
        url=URL,
        path="/api/flows/name/{name}",
        method="GET",
        headers=_headers(),
        path_params={"name": name},
    )
    if by_name.status_code == 200:
        client.send_request(
            url=URL,
            path="/api/flows/{id}",
            method="DELETE",
            headers=_headers(),
            path_params={"id": json.loads(by_name.response_body)["id"]},
        )


def _create_flow(client: skyramp.Client, name: str) -> dict:
    response = client.send_request(
        url=URL,
        path="/api/flows/",
        method="POST",
        body=json.dumps({"name": name}),
        headers=_headers(),
    )
    assert response.status_code == 201, response.response_body
    return json.loads(response.response_body)


def _get_recent(client: skyramp.Client, query_params=None, headers=None):
    return client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=headers if headers is not None else _headers(),
        query_params=query_params,
    )


@pytest.fixture
def flows():
    """Creates flows by name (deleting stale copies first) and deletes them afterwards."""
    client = skyramp.Client()
    names: list[str] = []

    def create(name: str) -> dict:
        _delete_flow_by_name(client, name)
        names.append(name)
        return _create_flow(client, name)

    yield create

    for name in names:
        _delete_flow_by_name(client, name)


# contract test for /api/flows/recent GET
def test_recent_get_returns_200_from_dedicated_handler(flows):
    client = skyramp.Client()
    flows("recent-c-route")

    # Expected Response Body
    expected_recent_GET_response_body = r"""[
        {
            "created": "2026-10-09T22:18:26.110112Z",
            "id": "cb134fc1-850b-4b0a-a7d8-ca4c7a0140d3",
            "name": "recent-c-route",
            "updated": "2026-10-09T22:18:26.110121Z"
        }
    ]"""

    # Execute Request
    recent_GET_response = _get_recent(client)

    # recent-route-not-captured: /{id:uuid} would answer 404/422 for "recent"
    assert recent_GET_response.status_code == 200
    assert skyramp.check_schema(recent_GET_response, expected_recent_GET_response_body)
    body = json.loads(recent_GET_response.response_body)
    assert isinstance(body, list)
    assert skyramp.get_response_value(recent_GET_response, "0.id") is not None


def test_recent_item_keyset_is_exactly_flow_schema(flows):
    client = skyramp.Client()
    flows("recent-c-keys")

    recent_GET_response = _get_recent(client)

    assert recent_GET_response.status_code == 200
    body = json.loads(recent_GET_response.response_body)
    assert len(body) >= 1
    assert ",".join(sorted(body[0].keys())) == "created,id,labels,name,tags,updated"
    for item in body:
        assert sorted(item.keys()) == [
            "created",
            "id",
            "labels",
            "name",
            "tags",
            "updated",
        ]


def test_recent_ignores_limit_query_param(flows):
    client = skyramp.Client()
    for i in range(1, 12):
        flows(f"recent-b10-{i:02d}")

    recent_GET_response = _get_recent(client, query_params={"limit": "50"})

    assert recent_GET_response.status_code == 200
    body = json.loads(recent_GET_response.response_body)
    # 11 flows were just created, so a honoured limit=50 would return >= 11
    assert len(body) == 10


def test_recent_ignores_sort_query_param(flows):
    client = skyramp.Client()
    flows("aaa-b9-older")
    flows("zz-b9-newest")

    recent_GET_response = _get_recent(client, query_params={"sort": "NAME_ASC"})

    assert recent_GET_response.status_code == 200
    body = json.loads(recent_GET_response.response_body)
    assert len(body) >= 2
    assert body[0]["name"] == "zz-b9-newest"
    assert body[1]["name"] == "aaa-b9-older"


def test_recent_ignores_malformed_query_params():
    client = skyramp.Client()

    recent_GET_response = _get_recent(
        client, query_params={"limit": "-1", "sort": "garbage"}
    )

    assert recent_GET_response.status_code == 200
    body = json.loads(recent_GET_response.response_body)
    assert isinstance(body, list)
    assert len(body) <= 10


def test_recent_enforces_minimum_api_version():
    client = skyramp.Client()
    headers = _headers()
    headers["X-PREFECT-API-VERSION"] = "0.1.0"

    recent_GET_response = _get_recent(client, headers=headers)

    assert recent_GET_response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
