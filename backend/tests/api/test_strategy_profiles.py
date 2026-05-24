"""Integration tests for the strategy-profiles API."""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_and_get_profile(async_client: AsyncClient) -> None:
    payload = {
        "name": "test_a",
        "config": {
            "meta": {"name": "test_a", "version": 1},
            "strategies": {"funding_arb": {"allocation_pct": 0.30}},
        },
    }
    created = await async_client.post("/api/v1/strategy-profiles", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    profile_id = body["id"]
    assert body["name"] == "test_a"
    assert body["version"] == 1
    assert body["is_active"] is False

    fetched = await async_client.get(f"/api/v1/strategy-profiles/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == profile_id


async def test_create_invalid_profile_rejects(async_client: AsyncClient) -> None:
    payload = {
        "name": "bad",
        "config": {
            "meta": {"name": "bad", "version": 1},
            "strategies": {"funding_arb": {"allocation_pct": 2.0}},
        },
    }
    r = await async_client.post("/api/v1/strategy-profiles", json=payload)
    assert r.status_code == 422


async def test_list_returns_all_profiles(async_client: AsyncClient) -> None:
    for name in ["one", "two", "three"]:
        await async_client.post(
            "/api/v1/strategy-profiles",
            json={
                "name": name,
                "config": {"meta": {"name": name, "version": 1}},
            },
        )
    r = await async_client.get("/api/v1/strategy-profiles")
    assert r.status_code == 200
    body = r.json()
    names = [p["name"] for p in body]
    assert {"one", "two", "three"}.issubset(set(names))


async def test_apply_makes_profile_active(async_client: AsyncClient) -> None:
    a = (
        await async_client.post(
            "/api/v1/strategy-profiles",
            json={"name": "a", "config": {"meta": {"name": "a", "version": 1}}},
        )
    ).json()
    b = (
        await async_client.post(
            "/api/v1/strategy-profiles",
            json={"name": "b", "config": {"meta": {"name": "b", "version": 1}}},
        )
    ).json()

    await async_client.post(f"/api/v1/strategy-profiles/{a['id']}/apply")
    active = (await async_client.get("/api/v1/strategy-profiles/active")).json()
    assert active["id"] == a["id"]

    await async_client.post(f"/api/v1/strategy-profiles/{b['id']}/apply")
    active = (await async_client.get("/api/v1/strategy-profiles/active")).json()
    assert active["id"] == b["id"]


async def test_update_config_bumps_version_and_persists(
    async_client: AsyncClient,
) -> None:
    created = (
        await async_client.post(
            "/api/v1/strategy-profiles",
            json={
                "name": "upd",
                "config": {
                    "meta": {"name": "upd", "version": 1},
                    "strategies": {"funding_arb": {"allocation_pct": 0.30}},
                },
            },
        )
    ).json()
    profile_id = created["id"]
    assert created["version"] == 1

    new_config = {
        "meta": {"name": "upd", "version": 2},
        "strategies": {"funding_arb": {"allocation_pct": 0.42}},
    }
    r = await async_client.post(
        f"/api/v1/strategy-profiles/{profile_id}/update-config",
        json={"config": new_config},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 2
    assert body["config"] == new_config

    refetched = (await async_client.get(f"/api/v1/strategy-profiles/{profile_id}")).json()
    assert refetched["version"] == 2
    assert refetched["config"]["strategies"]["funding_arb"]["allocation_pct"] == 0.42


async def test_update_config_404_on_missing(async_client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    r = await async_client.post(
        f"/api/v1/strategy-profiles/{missing}/update-config",
        json={"config": {"meta": {"name": "x", "version": 1}}},
    )
    assert r.status_code == 404


async def test_clone_creates_new_row_same_config(async_client: AsyncClient) -> None:
    src = (
        await async_client.post(
            "/api/v1/strategy-profiles",
            json={
                "name": "src",
                "config": {
                    "meta": {"name": "src", "version": 1},
                    "strategies": {"funding_arb": {"entry_bps_per_8h": 12.0}},
                },
            },
        )
    ).json()

    cloned = await async_client.post(
        f"/api/v1/strategy-profiles/{src['id']}/clone",
        json={"new_name": "src_copy"},
    )
    assert cloned.status_code == 201
    body = cloned.json()
    assert body["id"] != src["id"]
    assert body["name"] == "src_copy"
    assert body["config"]["strategies"]["funding_arb"]["entry_bps_per_8h"] == 12.0
