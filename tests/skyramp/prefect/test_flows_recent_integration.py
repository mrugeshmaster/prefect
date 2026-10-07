# Integration tests for GET /api/flows/recent: write through POST/PATCH/DELETE /api/flows,
# read back through /recent. Scaffolded with skyramp_integration_test_generation
# (POST -> GET {id} -> PATCH -> DELETE on /api/flows), refined by hand.

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


def _create_flow(client, created_flows, name, tags=None, labels=None):
    payload = {"name": name}
    if tags is not None:
        payload["tags"] = tags
    if labels is not None:
        payload["labels"] = labels
    response = client.send_request(
        url=URL,
        path="/api/flows/",
        method="POST",
        body=json.dumps(payload),
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


def _get_recent(client):
    response = client.send_request(
        url=URL,
        path="/api/flows/recent",
        method="GET",
        headers=_headers(),
    )
    assert response.status_code == 200
    body = json.loads(response.response_body)
    assert isinstance(body, list)
    return body


def _get_flow(client, flow_id):
    response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="GET",
        headers=_headers(),
        path_params={"id": flow_id},
    )
    assert response.status_code == 200
    return json.loads(response.response_body)


def _patch_tags(client, flow_id, tags):
    response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="PATCH",
        body=json.dumps({"tags": tags}),
        headers=_headers(),
        path_params={"id": flow_id},
    )
    assert response.status_code == 204


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


def _ts(value):
    return datetime.fromisoformat(value)


def _item(body, flow_id):
    matches = [item for item in body if item["id"] == flow_id]
    assert len(matches) == 1, f"flow {flow_id} not found exactly once in /recent"
    return matches[0]


def test_recent_limit_10_newest_set(client, created_flows):
    flows = _create_flows(client, created_flows, "cap", 11)
    body = _get_recent(client)
    response_ids = [item["id"] for item in body]
    expected_ids = [f["id"] for f in reversed(flows[1:])]  # f11..f2
    assert len(body) == 10
    assert ",".join(response_ids) == ",".join(expected_ids)
    assert flows[0]["id"] not in response_ids


def test_recent_schema_echo_detail(client, created_flows):
    new = _create_flow(
        client,
        created_flows,
        f"echo-{RUN}",
        tags=["alpha", "beta"],
        labels={"team": "data"},
    )
    body = _get_recent(client)
    recent_item = _item(body, new["id"])
    detail = _get_flow(client, new["id"])
    assert recent_item["id"] == detail["id"]
    assert json.dumps(recent_item, sort_keys=True) == json.dumps(detail, sort_keys=True)


def test_recent_stored_values_read_back(client, created_flows):
    new = _create_flow(
        client,
        created_flows,
        f"readback-{RUN}",
        tags=["alpha", "beta"],
        labels={"team": "data"},
    )
    item = _item(_get_recent(client), new["id"])
    assert item["name"] == f"readback-{RUN}"
    assert ",".join(item["tags"]) + "|" + item["labels"]["team"] == "alpha,beta|data"


def test_recent_new_flow_on_top(client, created_flows):
    created = _create_flow(client, created_flows, f"on-top-{RUN}")
    body = _get_recent(client)
    assert len(body) >= 1
    assert body[0]["id"] == created["id"]


def test_recent_new_flow_evicts_oldest(client, created_flows):
    _create_flows(client, created_flows, "evict", 10)
    before = [item["id"] for item in _get_recent(client)]
    assert len(before) == 10
    n = _create_flow(client, created_flows, f"evict-new-{RUN}")
    after = [item["id"] for item in _get_recent(client)]
    assert len(after) == 10
    assert before[9] not in after
    assert ",".join(after) == ",".join([n["id"]] + before[0:9])


def test_recent_update_reorder_and_tags(client, created_flows):
    a = _create_flow(client, created_flows, f"update-a-{RUN}", tags=["original"])
    b = _create_flow(client, created_flows, f"update-b-{RUN}")
    _patch_tags(client, a["id"], ["patched"])
    body = _get_recent(client)
    ids = [item["id"] for item in body]
    assert ids[0] == b["id"]
    assert ids.index(a["id"]) == 1
    assert ",".join(body[ids.index(a["id"])]["tags"]) == "patched"


def test_recent_update_timestamps(client, created_flows):
    a = _create_flow(client, created_flows, f"timestamps-{RUN}", tags=["before"])
    pre = _item(_get_recent(client), a["id"])
    _patch_tags(client, a["id"], ["after"])
    post = _item(_get_recent(client), a["id"])
    assert post["tags"] == ["after"]
    observed = (
        str(post["created"] == pre["created"]).lower()
        + ","
        + str(_ts(post["updated"]) > _ts(pre["updated"])).lower()
    )
    assert observed == "true,true", f"created unchanged,updated advanced -> {observed}"


def test_recent_read_only_count(client, created_flows):
    _create_flows(client, created_flows, "ro-count", 3)
    count_before = _count_flows(client)
    _get_recent(client)
    _get_recent(client)
    count_after = _count_flows(client)
    assert count_after - count_before == 0


def test_recent_read_only_updated(client, created_flows):
    _create_flows(client, created_flows, "ro-updated", 3)
    ids = [item["id"] for item in _get_recent(client)]
    assert len(ids) >= 3
    before = {flow_id: _get_flow(client, flow_id)["updated"] for flow_id in ids}
    _get_recent(client)
    after = {flow_id: _get_flow(client, flow_id)["updated"] for flow_id in ids}
    for flow_id in ids:
        assert after[flow_id] == before[flow_id], f"updated changed for {flow_id}"
    assert all(after[flow_id] == before[flow_id] for flow_id in ids)


def test_recent_delete_drops_flow(client, created_flows):
    flows = _create_flows(client, created_flows, "delete", 11)
    f1, f11 = flows[0], flows[-1]
    before = [item["id"] for item in _get_recent(client)]
    assert before[0] == f11["id"]
    response = client.send_request(
        url=URL,
        path="/api/flows/{id}",
        method="DELETE",
        headers=_headers(),
        path_params={"id": f11["id"]},
    )
    assert response.status_code == 204
    created_flows.remove(f11["id"])
    after = [item["id"] for item in _get_recent(client)]
    assert f11["id"] not in after
    assert ",".join(after) == ",".join(before[1:10] + [f1["id"]])
