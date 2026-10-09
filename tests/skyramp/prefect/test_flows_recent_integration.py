# Scaffolded by Skyramp v1.3.51 (skyramp generate integration rest
# http://localhost:4200/api/flows --chaining-key id), then refined to read
# back through GET /api/flows/recent.
# Integration tests for GET /api/flows/recent.

# Import of required libraries
import json
import os
from datetime import datetime

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


def _get_flow_by_name(client: skyramp.Client, name: str):
    return client.send_request(
        url=URL,
        path="/api/flows/name/{name}",
        method="GET",
        headers=_headers(),
        path_params={"name": name},
    )


def _delete_flow(client: skyramp.Client, flow_id: str):
    return client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="DELETE",
        headers=_headers(),
        path_params={"id": flow_id},
    )


def _delete_flow_by_name(client: skyramp.Client, name: str) -> None:
    by_name = _get_flow_by_name(client, name)
    if by_name.status_code == 200:
        _delete_flow(client, json.loads(by_name.response_body)["id"])


def _post_flow(client: skyramp.Client, body: dict):
    return client.send_request(
        url=URL,
        path="/api/flows/",
        method="POST",
        body=json.dumps(body),
        headers=_headers(),
    )


def _get_recent(client: skyramp.Client) -> list:
    recent_GET_response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
    )
    assert recent_GET_response.status_code == 200
    body = json.loads(recent_GET_response.response_body)
    assert isinstance(body, list)
    return body


def _count_flows(client: skyramp.Client) -> int:
    count_response = client.send_request(
        url=URL,
        path="/api/flows/count",
        method="POST",
        body="{}",
        headers=_headers(),
    )
    assert count_response.status_code == 200
    return int(json.loads(count_response.response_body))


@pytest.fixture
def flows():
    """Creates flows by name (deleting stale copies first) and deletes them afterwards."""
    client = skyramp.Client()
    names: list[str] = []

    def create(name: str, **fields) -> dict:
        _delete_flow_by_name(client, name)
        names.append(name)
        flows_POST_response = _post_flow(client, {"name": name, **fields})
        assert flows_POST_response.status_code == 201, flows_POST_response.response_body
        return json.loads(flows_POST_response.response_body)

    yield create

    for name in names:
        _delete_flow_by_name(client, name)


def test_recent_caps_at_ten_and_drops_oldest(flows):
    client = skyramp.Client()
    for i in range(1, 12):
        flows(f"recent-b1-{i:02d}")

    body = _get_recent(client)
    names = [item["name"] for item in body]

    # recent-caps-at-ten: 11 flows exist, so a missing limit returns >= 11
    assert len(body) == 10
    # recent-excludes-oldest: the kept ten are exactly recent-b1-02..11, so
    # recent-b1-01 (the 11th newest) is dropped while the newest ten remain;
    # an ascending/unsorted build returns other flows or keeps recent-b1-01
    assert sorted(names) == [f"recent-b1-{i:02d}" for i in range(2, 12)]
    assert "recent-b1-01" not in names
    assert "recent-b1-11" in names


def test_recent_orders_by_created_desc(flows):
    client = skyramp.Client()
    for i in range(1, 12):
        flows(f"recent-b2-{i:02d}")

    body = _get_recent(client)

    assert len(body) == 10
    assert (
        ",".join(item["name"] for item in body)
        == "recent-b2-11,recent-b2-10,recent-b2-09,recent-b2-08,recent-b2-07,recent-b2-06,recent-b2-05,recent-b2-04,recent-b2-03,recent-b2-02"
    )


def test_recent_returns_all_when_fewer_than_ten(flows):
    client = skyramp.Client()
    if _count_flows(client) != 0:
        pytest.skip("needs a database holding no other flows (shared SUT is not empty)")
    flows("recent-b3-a")
    flows("recent-b3-b")
    flows("recent-b3-c")

    body = _get_recent(client)

    assert len(body) == 3
    assert (
        ",".join(item["name"] for item in body) == "recent-b3-c,recent-b3-b,recent-b3-a"
    )


def test_recent_empty_db_returns_empty_list():
    client = skyramp.Client()
    if _count_flows(client) != 0:
        pytest.skip("needs a database holding no flows (shared SUT is not empty)")

    recent_GET_response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
    )

    assert recent_GET_response.status_code == 200
    body = json.loads(recent_GET_response.response_body)
    assert isinstance(body, list)
    assert len(body) == 0


def test_recent_item_matches_get_by_id_and_stored_fields(flows):
    client = skyramp.Client()
    created = flows("recent-b4", tags=["alpha", "beta"], labels={"team": "data"})

    flows_id_GET_response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="GET",
        headers=_headers(),
        path_params={"id": created["id"]},
    )
    assert flows_id_GET_response.status_code == 200
    by_id = json.loads(flows_id_GET_response.response_body)

    body = _get_recent(client)

    assert body[0]["id"] == created["id"]
    # recent-item-matches-get-by-id: full object equality with the by-id body
    assert body[0] == by_id
    # recent-item-tags-stored
    assert ",".join(body[0]["tags"]) == "alpha,beta"
    # recent-item-labels-stored
    assert body[0]["labels"]["team"] == "data"


def test_name_route_still_reachable_for_flow_named_recent(flows):
    client = skyramp.Client()
    created = flows("recent")

    # the new static /recent route serves the list, with the flow named
    # "recent" as its newest item, not the by-name or by-id handler
    recent_GET_response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
    )
    assert recent_GET_response.status_code == 200
    recent_body = json.loads(recent_GET_response.response_body)
    assert isinstance(recent_body, list)
    assert recent_body[0]["id"] == created["id"]
    assert recent_body[0]["name"] == "recent"

    # and /name/recent still reaches the by-name handler for that same flow
    by_name_response = _get_flow_by_name(client, "recent")

    assert by_name_response.status_code == 200
    by_name = json.loads(by_name_response.response_body)
    assert isinstance(by_name, dict)
    assert by_name["name"] == "recent"
    assert by_name["id"] == created["id"]


def test_recent_drops_deleted_flow(flows):
    client = skyramp.Client()
    flows("recent-ref-old")
    newest = flows("recent-ref-new")

    flows_id_DELETE_response = _delete_flow(client, newest["id"])
    assert flows_id_DELETE_response.status_code == 204

    body = _get_recent(client)

    assert newest["id"] not in [item["id"] for item in body]
    assert body[0]["name"] == "recent-ref-old"


def test_recent_reflects_patched_tags(flows):
    client = skyramp.Client()
    created = flows("recent-rb", tags=["original"])

    flows_id_PATCH_response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="PATCH",
        body=json.dumps({"tags": ["patched"]}),
        headers=_headers(),
        path_params={"id": created["id"]},
    )
    assert flows_id_PATCH_response.status_code == 204

    body = _get_recent(client)
    matching = [item for item in body if item["name"] == "recent-rb"]

    assert len(matching) == 1
    assert ",".join(matching[0]["tags"]) == "patched"


def test_recent_update_does_not_reorder(flows):
    client = skyramp.Client()
    older = flows("recent-ord-a")
    flows("recent-ord-b")

    flows_id_PATCH_response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="PATCH",
        body=json.dumps({"tags": ["touched"]}),
        headers=_headers(),
        path_params={"id": older["id"]},
    )
    assert flows_id_PATCH_response.status_code == 204

    body = _get_recent(client)

    assert body[0]["name"] == "recent-ord-b"
    assert body[1]["name"] == "recent-ord-a"
    # the patch bumped recent-ord-a's `updated` past recent-ord-b's, so an
    # UPDATED_DESC sort would have put recent-ord-a first
    assert datetime.fromisoformat(body[1]["updated"]) > datetime.fromisoformat(
        body[0]["updated"]
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
