"""End-to-end smoke test: create -> apply -> read active -> ProfileParams."""

from __future__ import annotations

import json
import pathlib

from httpx import AsyncClient

from app.profile.params import ProfileParams

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "profiles"


async def test_full_flow_create_apply_read_resolve(async_client: AsyncClient) -> None:
    with open(FIXTURES_DIR / "balanced_v1.json") as f:
        config = json.load(f)

    created = (
        await async_client.post(
            "/api/v1/strategy-profiles",
            json={"name": "balanced_v1", "config": config},
        )
    ).json()
    assert created["is_active"] is False

    await async_client.post(f"/api/v1/strategy-profiles/{created['id']}/apply")
    active = (await async_client.get("/api/v1/strategy-profiles/active")).json()
    assert active["id"] == created["id"]

    params = ProfileParams(active["config"])
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == 8.0
    assert params.get("strategies.funding_arb.allocation_pct") == 0.40
    assert params.get("strategies.factor_portfolio.allocation_pct") == 0.20
    # Path NOT in the balanced_v1 profile resolves to registry default:
    assert params.get("execution.min_notional_usd") == 10
