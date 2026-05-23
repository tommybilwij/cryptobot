"""CLI: python -m scripts.load_fixtures.

Imports every `profiles/*.json` into the DB.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from app.deps import get_session_factory
from app.profile.loader import load_fixtures

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "profiles"


async def main() -> int:
    if not FIXTURES_DIR.exists():
        print(f"fixtures dir not found: {FIXTURES_DIR}", file=sys.stderr)
        return 1
    factory = get_session_factory()
    async with factory() as session:
        loaded = await load_fixtures(session, FIXTURES_DIR)
    print(f"loaded {loaded} fixture(s) from {FIXTURES_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
