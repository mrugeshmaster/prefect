import base64
import json
import pathlib
import random
from datetime import UTC, datetime
from itertools import pairwise
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from starlette import status

from prefect.server.api.server import create_app
from prefect.settings import PREFECT_SERVER_API_AUTH_STRING, temporary_settings

pytestmark = pytest.mark.clear_db

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


async def create_flows(client, count: int, prefix: str | None = None) -> list[dict]:
    """Create `count` flows sequentially and return them in creation order."""
    prefix = prefix or f"recent-{uuid4().hex[:8]}"
    flows = []
    for i in range(count):
        response = await client.post("/flows/", json={"name": f"{prefix}-{i}"})
        assert response.status_code == status.HTTP_201_CREATED
        flows.append(response.json())
    return flows


def ids(items: list[dict]) -> list[str]:
    return [item["id"] for item in items]


class TestReadRecentFlows:
    async def test_returns_empty_list_without_flows(self, client):
        response = await client.get("/flows/recent")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_returns_exactly_ten_when_more_exist(self, client):
        await create_flows(client, 12)

        response = await client.get("/flows/recent")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 10

    async def test_returns_newest_ten_in_reverse_creation_order(self, client):
        created = await create_flows(client, 12)

        response = await client.get("/flows/recent")

        assert response.status_code == status.HTTP_200_OK
        returned = ids(response.json())
        assert returned == ids(created[2:])[::-1]
        assert created[0]["id"] not in returned
        assert created[1]["id"] not in returned

    async def test_matches_filter_sorted_by_created_desc(self, client):
        await create_flows(client, 12)

        recent = await client.get("/flows/recent")
        filtered = await client.post(
            "/flows/filter", json={"sort": "CREATED_DESC", "limit": 10}
        )

        assert recent.status_code == status.HTTP_200_OK
        assert filtered.status_code == status.HTTP_200_OK
        assert ids(recent.json()) == ids(filtered.json())

    async def test_created_is_non_increasing(self, client):
        created = await create_flows(client, 12)

        response = await client.get("/flows/recent")

        items = response.json()
        timestamps = [datetime.fromisoformat(item["created"]) for item in items]
        assert all(a >= b for a, b in pairwise(timestamps))
        assert items[0]["id"] == created[-1]["id"]

    async def test_fewer_than_ten_then_rolls_over(self, client):
        assert (await client.get("/flows/recent")).json() == []

        first = await create_flows(client, 3, prefix="few-a")
        response = await client.get("/flows/recent")
        assert ids(response.json()) == ids(first)[::-1]

        second = await create_flows(client, 7, prefix="few-b")
        response = await client.get("/flows/recent")
        assert ids(response.json()) == ids(first + second)[::-1]

        third = await create_flows(client, 1, prefix="few-c")
        response = await client.get("/flows/recent")
        assert ids(response.json()) == ids(first[1:] + second + third)[::-1]

    async def test_item_matches_single_read_representation(self, client):
        response = await client.post(
            "/flows/",
            json={
                "name": f"shape-{uuid4().hex[:8]}",
                "tags": ["t1"],
                "labels": {"team": "data", "priority": 2},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        flow_id = response.json()["id"]

        recent = (await client.get("/flows/recent")).json()
        item = next(i for i in recent if i["id"] == flow_id)

        single = (await client.get(f"/flows/{flow_id}")).json()
        filtered = (
            await client.post(
                "/flows/filter", json={"flows": {"id": {"any_": [flow_id]}}}
            )
        ).json()

        assert set(item) >= {"id", "created", "updated", "name", "tags", "labels"}
        UUID(item["id"])
        assert isinstance(item["tags"], list)
        assert item == single
        assert item == filtered[0]

    async def test_deleted_flows_are_excluded(self, client):
        flow_a, flow_b = await create_flows(client, 2)

        response = await client.delete(f"/flows/{flow_b['id']}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        returned = ids((await client.get("/flows/recent")).json())
        assert flow_b["id"] not in returned
        assert returned[0] == flow_a["id"]

    async def test_update_does_not_change_position(self, client):
        flow_a, flow_b = await create_flows(client, 2)

        response = await client.patch(f"/flows/{flow_a['id']}", json={"tags": ["x"]})
        assert response.status_code == status.HTTP_204_NO_CONTENT

        returned = ids((await client.get("/flows/recent")).json())
        assert returned[:2] == [flow_b["id"], flow_a["id"]]

    async def test_upsert_of_existing_name_does_not_change_position(self, client):
        flow_a, flow_b = await create_flows(client, 2)

        response = await client.post("/flows/", json={"name": flow_a["name"]})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == flow_a["id"]

        returned = ids((await client.get("/flows/recent")).json())
        assert returned[:2] == [flow_b["id"], flow_a["id"]]

    async def test_query_params_are_ignored(self, client):
        await create_flows(client, 12)

        plain = await client.get("/flows/recent")
        with_params = await client.get(
            "/flows/recent", params={"limit": 50, "offset": 5, "sort": "NAME_ASC"}
        )

        assert with_params.status_code == status.HTTP_200_OK
        assert len(with_params.json()) == 10
        assert ids(with_params.json()) == ids(plain.json())

    @pytest.mark.parametrize("method", ["POST", "DELETE", "PATCH"])
    async def test_other_methods_not_allowed(self, client, method):
        await create_flows(client, 2)
        before = (await client.post("/flows/count")).json()

        kwargs = {"json": {}} if method in ("POST", "PATCH") else {}
        response = await client.request(method, "/flows/recent", **kwargs)

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert (await client.post("/flows/count")).json() == before

    async def test_ties_on_created_are_ordered_deterministically(self, client, db):
        """Flows sharing a `created` timestamp must still come back in a stable,
        tie-broken order so the 10-item cut-off does not depend on storage order."""
        shared = datetime(2024, 1, 1, tzinfo=UTC)
        rows = [
            {
                "id": uuid4(),
                "name": f"tie-{i:02d}",
                "created": shared,
                "updated": shared,
            }
            for i in range(12)
        ]
        # insert in an order unrelated to either id or name
        random.Random(1234).shuffle(rows)
        async with db.session_context(begin_transaction=True) as session:
            await session.execute(sa.insert(db.Flow), rows)

        responses = [ids((await client.get("/flows/recent")).json()) for _ in range(5)]
        assert all(r == responses[0] for r in responses)

        returned = responses[0]
        names = {str(r["id"]): r["name"] for r in rows}
        by_id_desc = sorted((str(r["id"]) for r in rows), reverse=True)[:10]
        by_id_asc = sorted(str(r["id"]) for r in rows)[:10]
        by_name_desc = sorted(names, key=names.get, reverse=True)[:10]
        by_name_asc = sorted(names, key=names.get)[:10]
        assert returned in (by_id_desc, by_id_asc, by_name_desc, by_name_asc)


class TestNeighbouringFlowRoutes:
    async def test_read_flow_by_id(self, client):
        (flow,) = await create_flows(client, 1)

        response = await client.get(f"/flows/{flow['id']}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == flow["id"]

        response = await client.get(f"/flows/{uuid4()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_flow_named_recent(self, client):
        response = await client.post("/flows/", json={"name": "recent"})
        assert response.status_code == status.HTTP_201_CREATED
        flow_id = response.json()["id"]

        by_name = await client.get("/flows/name/recent")
        assert by_name.status_code == status.HTTP_200_OK
        assert by_name.json()["name"] == "recent"

        recent = await client.get("/flows/recent")
        assert recent.status_code == status.HTTP_200_OK
        assert isinstance(recent.json(), list)
        assert flow_id in ids(recent.json())

    async def test_filter_and_paginate(self, client):
        await create_flows(client, 6)

        filtered = await client.post("/flows/filter", json={"limit": 5})
        assert filtered.status_code == status.HTTP_200_OK
        assert isinstance(filtered.json(), list)
        assert len(filtered.json()) == 5

        paginated = await client.post("/flows/paginate", json={"limit": 5})
        assert paginated.status_code == status.HTTP_200_OK
        body = paginated.json()
        assert len(body["results"]) == 5
        assert body["count"] == 6
        assert body["limit"] == 5
        assert body["pages"] == 2
        assert body["page"] == 1

    async def test_count(self, client):
        await create_flows(client, 3)

        response = await client.post("/flows/count")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == 3

    async def test_trailing_slash_returns_same_list(self, client):
        await create_flows(client, 3)

        plain = await client.get("/flows/recent")
        slashed = await client.get("/flows/recent/", follow_redirects=True)

        assert slashed.status_code < 500
        assert slashed.status_code == status.HTTP_200_OK
        assert slashed.json() == plain.json()

    async def test_non_uuid_id(self, client):
        response = await client.get("/flows/not-a-uuid")
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class TestRecentFlowsSchemaAndAuth:
    async def test_listed_in_openapi_as_flow_array(self, client):
        response = await client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        schema = response.json()

        operation = schema["paths"]["/flows/recent"]["get"]
        response_schema = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert response_schema["type"] == "array"
        assert response_schema["items"] == {"$ref": "#/components/schemas/Flow"}

    def test_auth_string_required(self):
        auth_string = "admin:test"
        header = "Basic " + base64.b64encode(auth_string.encode()).decode()
        with temporary_settings({PREFECT_SERVER_API_AUTH_STRING: auth_string}):
            client = TestClient(create_app(ignore_cache=True))

            assert client.get("/api/flows/recent").status_code == 401
            # matches the other read routes under /api/flows
            assert client.get(f"/api/flows/{uuid4()}").status_code == 401

            response = client.get(
                "/api/flows/recent", headers={"Authorization": header}
            )
            assert response.status_code == 200
            assert isinstance(response.json(), list)

    def test_listed_in_docs_rest_api_reference(self):
        schema_path = REPO_ROOT / "docs/v3/api-ref/rest-api/server/schema.json"
        schema = json.loads(schema_path.read_text())

        assert "/flows/recent" in schema["paths"]
