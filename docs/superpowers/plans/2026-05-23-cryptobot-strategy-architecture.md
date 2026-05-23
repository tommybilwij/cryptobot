# Cryptobot — Phase 1 + Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational scaffolding (Phase 1) + the load-bearing profile system (Phase 2) for the cryptobot, per the research doc at `docs/superpowers/research/cryptobot-strategy-architecture.md`.

**Architecture:** Multi-service via Docker Compose (`postgres` + `api`). Backend follows FastAPI + SQLAlchemy 2.x async + Pydantic v2 + Alembic. Profile system uses three typed registry dicts (numeric / string / dict) + Pydantic v2 schemas + Postgres JSONB storage + atomic apply transaction that walks the registry to enforce leak-gap prevention. Constraint #1 (no hardcoded values in strategies) enforced by a custom 20-line AST lint script.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.x async + asyncpg, Pydantic v2, Alembic, pytest + pytest-asyncio, ruff, mypy `--strict`, uv (deps), Docker Compose, Postgres 16.

**Scope:** Phase 1 (repo skeleton + CI) + Phase 2 (profile system end-to-end with HTTP API + fixtures). Out of scope (later plans): data pipeline (Phase 3), backtester (Phase 4), exchange adapters (Phase 5), strategy implementations (Phase 6+), frontend (Phase 8), monitoring (Phase 9).

**Definition of done (gate to Phase 3):**
- `docker compose up -d` boots postgres + api cleanly
- `curl localhost:8000/api/v1/health` returns 200
- `POST /api/v1/strategy-profiles` + `POST /api/v1/strategy-profiles/{id}/apply` work
- Apply A → B → A round-trip preserves zero leaked keys (test passes)
- AST lint catches a deliberately-injected numeric literal in `backend/app/strategies/`
- `mypy --strict backend/app` passes
- CI green (test + typecheck + lint)

---

## Phase 1.1: Project scaffolding

### Task 1: Initialise backend Python project with uv

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "cryptobot-backend"
version = "0.1.0"
description = "Cryptobot backend — FastAPI + profile system"
requires-python = ">=3.12"
dependencies = [
    "fastapi[standard]>=0.115",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "mypy>=1.10",
    "ruff>=0.5",
    "aiosqlite>=0.20",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "PL"]
ignore = ["E501", "PLR0913"]

[tool.ruff.lint.per-file-ignores]
"backend/tests/**" = ["PLR2004"]                  # magic numbers OK in tests
"backend/app/strategies/**" = []                   # NO exceptions — strict zero-literals here

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
exclude = ["alembic/versions/.*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `backend/.python-version`**

```
3.12
```

- [ ] **Step 3: Run uv lock + sync**

Run from `backend/`:
```bash
cd backend && uv lock && uv sync
```
Expected: `uv.lock` is created, `.venv/` populated.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/.python-version backend/uv.lock
git commit -m "chore: scaffold backend Python project with uv"
```

---

### Task 2: Docker Compose with Postgres

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: cryptobot-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: cryptobot
      POSTGRES_USER: cryptobot
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-devpass}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cryptobot -d cryptobot"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
```

- [ ] **Step 2: Create `.env.example`**

```dotenv
POSTGRES_PASSWORD=devpass
DATABASE_URL=postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot
DATABASE_URL_SYNC=postgresql+psycopg://cryptobot:devpass@localhost:5432/cryptobot
TEST_DATABASE_URL=postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot_test
```

- [ ] **Step 3: Bring postgres up**

```bash
docker compose up -d postgres
docker compose ps
```
Expected: postgres status `(healthy)` within ~15s.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore: add docker-compose with local postgres"
```

---

### Task 3: FastAPI app shell + health endpoint

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Write failing health test**

`backend/tests/conftest.py`:
```python
"""Pytest fixtures for the cryptobot backend."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient


@pytest.fixture
def client() -> TestClient:
    """Synchronous TestClient — fine for endpoints that don't touch the DB."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Async client for endpoints that touch the async DB session."""
    from app.main import app

    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
```

`backend/tests/__init__.py`:
```python
```

`backend/tests/test_health.py`:
```python
"""Health endpoint smoke test."""
from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Verify test fails**

```bash
cd backend && uv run pytest tests/test_health.py -v
```
Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create app shell**

`backend/app/__init__.py`:
```python
```

`backend/app/config.py`:
```python
"""Application configuration loaded from environment variables."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded from env / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://cryptobot:devpass@localhost:5432/cryptobot",
        alias="DATABASE_URL_SYNC",
    )
    test_database_url: str = Field(
        default="postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot_test",
        alias="TEST_DATABASE_URL",
    )


settings = Settings()
```

`backend/app/api/__init__.py`:
```python
```

`backend/app/api/health.py`:
```python
"""Health endpoint."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}
```

`backend/app/main.py`:
```python
"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import health

app = FastAPI(title="cryptobot", version="0.1.0")
app.include_router(health.router)
```

- [ ] **Step 4: Verify test passes**

```bash
cd backend && uv run pytest tests/test_health.py -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: add FastAPI app shell with health endpoint"
```

---

### Task 4: Alembic initialisation + base migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/.gitkeep`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/base.py`

- [ ] **Step 1: Create SQLAlchemy declarative base**

`backend/app/models/__init__.py`:
```python
"""ORM models. Import models here so Alembic autogenerate picks them up."""
from app.models.base import Base

__all__ = ["Base"]
```

`backend/app/models/base.py`:
```python
"""SQLAlchemy 2.x declarative base for all ORM models."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common declarative base."""

    pass
```

- [ ] **Step 2: Create `backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 3: Create `backend/alembic/env.py`**

```python
"""Alembic environment — sync engine for migrations, reads project settings."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Create `backend/alembic/script.py.mako`**

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 5: Add psycopg sync driver for migrations**

```bash
cd backend && uv add 'psycopg[binary]'
```

- [ ] **Step 6: Add dependencies to project**

```bash
cd backend && uv sync
```

- [ ] **Step 7: Create versions dir**

```bash
mkdir -p backend/alembic/versions
touch backend/alembic/versions/.gitkeep
```

- [ ] **Step 8: Verify Alembic config loads**

```bash
cd backend && uv run alembic current
```
Expected: empty output (no migrations yet, but no error).

- [ ] **Step 9: Commit**

```bash
git add backend/alembic.ini backend/alembic backend/app/models backend/pyproject.toml backend/uv.lock
git commit -m "chore: scaffold alembic with sync engine"
```

---

### Task 5: Custom AST lint script for "no literals in strategies"

**Files:**
- Create: `scripts/lint_no_literals_in_strategies.py`
- Create: `backend/app/strategies/__init__.py`

- [ ] **Step 1: Create strategies dir sentinel**

`backend/app/strategies/__init__.py`:
```python
"""Strategy implementations. CI-lint-protected: no numeric literals allowed.

Every parameter must come from the profile registry via `ProfileParams.get(path)`.
See `backend/app/profile/defaults.py` for the registry.
"""
__all__: list[str] = []
```

- [ ] **Step 2: Create the lint script**

`scripts/lint_no_literals_in_strategies.py`:
```python
#!/usr/bin/env python3
"""Lint: no numeric literals in backend/app/strategies/**.

Enforces Constraint #1 from the research doc — every parameter in a strategy
file must come from the profile registry, never from a hardcoded value.

Allowed literals: 0, 1, -1 (loop bounds, sentinels). Everything else fails CI.

Run: python scripts/lint_no_literals_in_strategies.py
Exit code: 0 if clean, 1 if violations found.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ALLOWED: set[int | float] = {0, 1, -1}
SCAN_DIR = pathlib.Path(__file__).parent.parent / "backend" / "app" / "strategies"


def main() -> int:
    if not SCAN_DIR.exists():
        print(f"lint: scan dir {SCAN_DIR} does not exist; nothing to check")
        return 0

    violations: list[tuple[pathlib.Path, int, float | int]] = []
    for py_file in SCAN_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if isinstance(node.value, bool):  # bools are ints in Python; allow
                    continue
                if node.value not in ALLOWED:
                    violations.append((py_file, node.lineno, node.value))

    if violations:
        for path, lineno, value in violations:
            print(
                f"{path}:{lineno}: numeric literal {value!r} - move to profile registry",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Make executable**

```bash
chmod +x scripts/lint_no_literals_in_strategies.py
```

- [ ] **Step 4: Test the lint against an empty strategies dir**

```bash
python scripts/lint_no_literals_in_strategies.py
echo "exit: $?"
```
Expected: `exit: 0` (no .py files in strategies/ yet beyond `__init__.py` which has zero literals).

- [ ] **Step 5: Commit**

```bash
git add scripts/lint_no_literals_in_strategies.py backend/app/strategies/__init__.py
git commit -m "feat: add AST lint enforcing no literals in strategy files"
```

---

### Task 6: Justfile for common commands

**Files:**
- Create: `justfile`

- [ ] **Step 1: Create `justfile`**

```just
# Cryptobot — common dev commands.
# Run `just` to list available recipes.

set dotenv-load
set positional-arguments

default:
    @just --list

# Bring up local postgres
up:
    docker compose up -d postgres
    @echo "Waiting for postgres..."
    @until docker compose exec postgres pg_isready -U cryptobot -d cryptobot > /dev/null 2>&1; do sleep 1; done
    @echo "Postgres ready."

# Tear down local services
down:
    docker compose down

# Run backend tests
test *args:
    cd backend && uv run pytest "$@"

# Run typecheck
typecheck:
    cd backend && uv run mypy app

# Run all linters
lint:
    cd backend && uv run ruff check app tests
    python scripts/lint_no_literals_in_strategies.py

# Apply ruff fixes
fmt:
    cd backend && uv run ruff check --fix app tests
    cd backend && uv run ruff format app tests

# Run Alembic migration up
mig-up:
    cd backend && uv run alembic upgrade head

# Generate a new migration
mig-new MESSAGE:
    cd backend && uv run alembic revision --autogenerate -m "{{MESSAGE}}"

# Run the API server (dev mode)
api:
    cd backend && uv run fastapi dev app/main.py
```

- [ ] **Step 2: Verify justfile parses**

```bash
just --list
```
Expected: list of recipes (up, down, test, typecheck, lint, ...).

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "chore: add justfile for common dev commands"
```

---

### Task 7: Update CI workflow with real jobs

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read existing CI workflow**

```bash
cat .github/workflows/ci.yml
```

The file already exists (placeholder from PR #1) with `typecheck` and `test` jobs as no-ops.

- [ ] **Step 2: Replace contents**

`.github/workflows/ci.yml`:
```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Set up Python
        run: cd backend && uv python install
      - name: Install dependencies
        run: cd backend && uv sync --frozen
      - name: Run mypy --strict
        run: cd backend && uv run mypy app
      - name: Run ruff
        run: cd backend && uv run ruff check app tests
      - name: AST lint strategies
        run: python scripts/lint_no_literals_in_strategies.py

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: cryptobot_test
          POSTGRES_USER: cryptobot
          POSTGRES_PASSWORD: devpass
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U cryptobot -d cryptobot_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot_test
      DATABASE_URL: postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot_test
      DATABASE_URL_SYNC: postgresql+psycopg://cryptobot:devpass@localhost:5432/cryptobot_test
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Set up Python
        run: cd backend && uv python install
      - name: Install dependencies
        run: cd backend && uv sync --frozen
      - name: Run Alembic migrations
        run: cd backend && uv run alembic upgrade head
      - name: Run pytest
        run: cd backend && uv run pytest -v
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: wire real typecheck + test jobs"
```

---

## Phase 2.1: Strategy profile model + migration

### Task 8: StrategyProfile ORM model

**Files:**
- Create: `backend/app/models/strategy_profile.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the ORM model**

`backend/app/models/strategy_profile.py`:
```python
"""StrategyProfile ORM: named, versioned JSONB bundles of strategy config."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StrategyProfile(Base):
    """A named, versioned strategy profile.

    `config` is the full JSONB blob (universe + strategies + risk + execution
    + backtest sections). `is_active` is true for exactly one row at a time;
    `apply_profile` walks the registry atomically to switch.
    """

    __tablename__ = "strategy_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 2: Register model in `app/models/__init__.py`**

`backend/app/models/__init__.py`:
```python
"""ORM models. Import models here so Alembic autogenerate picks them up."""
from app.models.base import Base
from app.models.strategy_profile import StrategyProfile

__all__ = ["Base", "StrategyProfile"]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models
git commit -m "feat: add StrategyProfile ORM model"
```

---

### Task 9: Initial Alembic migration for strategy_profiles

**Files:**
- Create: `backend/alembic/versions/0001_create_strategy_profiles.py`

- [ ] **Step 1: Autogenerate the migration**

```bash
just up                                          # ensure local postgres is up
cd backend && uv run alembic revision --autogenerate -m "create strategy_profiles"
mv backend/alembic/versions/*.py backend/alembic/versions/0001_create_strategy_profiles.py
```
(Rename to use 0001 prefix for deterministic ordering.)

- [ ] **Step 2: Open the file, verify it creates `strategy_profiles`**

The autogenerated file should have an `upgrade()` containing `op.create_table('strategy_profiles', ...)` and `downgrade()` containing `op.drop_table('strategy_profiles')`. If revision/down_revision values aren't `0001`/`None`, hand-edit them.

Final file shape (replace `<revid>` with the autogen UUID — keep autogenerated, just normalize the header):
```python
"""create strategy_profiles

Revision ID: 0001
Revises:
Create Date: 2026-05-23 ...

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_strategy_profiles_active",
        "strategy_profiles",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_profiles_active", table_name="strategy_profiles")
    op.drop_table("strategy_profiles")
```

- [ ] **Step 3: Run migration**

```bash
just mig-up
```
Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> 0001, create strategy_profiles`

- [ ] **Step 4: Verify table exists**

```bash
docker compose exec postgres psql -U cryptobot -d cryptobot -c "\d strategy_profiles"
```
Expected: column list matching the model.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0001_create_strategy_profiles.py
git commit -m "feat: alembic migration creating strategy_profiles table"
```

---

### Task 10: DB session + deps wiring

**Files:**
- Create: `backend/app/deps.py`

- [ ] **Step 1: Create async session factory + dependency**

`backend/app/deps.py`:
```python
"""Dependency injection: async DB session + engine lifecycle."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an async session per request."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Engine lifecycle — disposed at shutdown."""
    yield
    if _engine is not None:
        await _engine.dispose()
```

- [ ] **Step 2: Wire lifespan into the app**

`backend/app/main.py`:
```python
"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import health
from app.deps import lifespan

app = FastAPI(title="cryptobot", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
```

- [ ] **Step 3: Run tests + ensure existing pass**

```bash
just test
```
Expected: 1 passed (health test).

- [ ] **Step 4: Commit**

```bash
git add backend/app/deps.py backend/app/main.py
git commit -m "feat: async db session factory + lifespan"
```

---

### Task 11: Test fixtures with isolated test DB

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Extend conftest with DB fixtures**

`backend/tests/conftest.py`:
```python
"""Pytest fixtures for the cryptobot backend."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.deps import get_db
from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Session-scoped engine pointing at the test DB."""
    engine = create_async_engine(settings.test_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    """Per-test session that rolls back on teardown."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def client(db_session: AsyncSession) -> TestClient:
    """Sync TestClient with DB dependency overridden to use the test session."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Create the test DB**

```bash
docker compose exec postgres createdb -U cryptobot cryptobot_test || true
```

- [ ] **Step 3: Run tests**

```bash
just test
```
Expected: 1 passed (health). DB fixtures are set up but no DB-using test exists yet.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: async db session fixture with per-test rollback"
```

---

## Phase 2.2: Profile registry (the heart of Constraint #1)

### Task 12: PROFILE_SCOPED_DEFAULTS (numeric + bool registry)

**Files:**
- Create: `backend/app/profile/__init__.py`
- Create: `backend/app/profile/defaults.py`

- [ ] **Step 1: Create profile package**

`backend/app/profile/__init__.py`:
```python
"""Profile system — registry, accessor, apply mechanism."""
```

- [ ] **Step 2: Create initial numeric registry**

`backend/app/profile/defaults.py`:
```python
"""Single source of truth for profile-scoped keys + safe defaults.

Constraint #1: every numeric / string / dict value a strategy reads must be
listed here. Constraint #3: applying a profile walks this registry; any key
absent from the new profile resets to its default (leak-gap prevention).

Booleans are stored as 0.0 / 1.0 floats in PROFILE_SCOPED_DEFAULTS to keep
the JSONB shape uniform with stockbot's pattern.
"""
from __future__ import annotations

from typing import Any

# ── PROFILE_SCOPED_DEFAULTS ──────────────────────────────────────────────
# Numeric + boolean (stored as 0.0/1.0) profile keys with their safe defaults.

PROFILE_SCOPED_DEFAULTS: dict[str, float] = {
    # ── Strategy A — funding arb ─────────────────────────────────────────
    "strategies.funding_arb.enabled": 1.0,
    "strategies.funding_arb.allocation_pct": 0.40,
    "strategies.funding_arb.entry_bps_per_8h": 8.0,
    "strategies.funding_arb.exit_bps_per_8h": 4.0,
    "strategies.funding_arb.basis_halt_bps": 80.0,
    "strategies.funding_arb.basis_warn_bps": 50.0,
    "strategies.funding_arb.max_position_pct": 0.10,
    "strategies.funding_arb.max_gross_pct": 1.50,
    "strategies.funding_arb.hedge_drift_halt_pct": 0.05,
    "strategies.funding_arb.spot_post_only_ttl_s": 60,
    "strategies.funding_arb.use_predicted_funding": 1.0,
    "strategies.funding_arb.reconcile_interval_s": 15,

    # ── Strategy B — factor portfolio ────────────────────────────────────
    "strategies.factor_portfolio.enabled": 1.0,
    "strategies.factor_portfolio.allocation_pct": 0.20,
    "strategies.factor_portfolio.top_decile_pct": 0.10,
    "strategies.factor_portfolio.bottom_decile_pct": 0.10,
    "strategies.factor_portfolio.shorts_enabled": 0.0,
    "strategies.factor_portfolio.lookback_minutes": 1440,
    "strategies.factor_portfolio.cs_alpha": 0.30,
    "strategies.factor_portfolio.scoring.thresholds.strong_buy": 10.0,
    "strategies.factor_portfolio.scoring.thresholds.buy": 7.0,
    "strategies.factor_portfolio.scoring.thresholds.watch": 4.0,
    "strategies.factor_portfolio.scoring.thresholds.llm_gate": 1.0,

    # ── Meta-allocator ──────────────────────────────────────────────────
    "strategies.meta_allocator.enabled": 1.0,
    "strategies.meta_allocator.lookback_days": 30,
    "strategies.meta_allocator.min_weight_pct": 0.10,
    "strategies.meta_allocator.max_weight_pct": 0.70,

    # ── Universe ─────────────────────────────────────────────────────────
    "universe.alt_universe_size": 100,
    "universe.min_daily_volume_usd": 5_000_000,
    "universe.min_listing_age_days": 30,

    # ── Risk (global, applied across all strategies) ─────────────────────
    "risk.max_gross_leverage": 1.50,
    "risk.max_net_leverage": 0.50,
    "risk.max_drawdown_pct": 0.20,
    "risk.daily_drawdown_halt_pct": 0.05,
    "risk.max_gross_per_asset_pct": 0.15,
    "risk.hedge_pair_protection": 1.0,
    "risk.deadman_timeout_s": 60,
    "risk.reconcile_interval_s": 15,
    "risk.position_mismatch_halt": 1.0,
    "risk.kelly.enabled": 0.0,
    "risk.kelly.fraction": 0.25,
    "risk.kelly.baseline_cap": 0.02,
    "risk.vol_target.enabled": 1.0,
    "risk.vol_target.target_pct": 0.015,
    "risk.vol_target.lookback_days": 60,
    "risk.drawdown_brake.enabled": 1.0,
    "risk.drawdown_brake.trigger_pct": 0.05,
    "risk.drawdown_brake.full_pct": 0.15,
    "risk.drawdown_brake.min_mult": 0.25,
    "risk.black_swan_circuit.enabled": 1.0,
    "risk.black_swan_circuit.move_pct": 0.08,
    "risk.black_swan_circuit.window_minutes": 5,

    # ── Execution (global) ───────────────────────────────────────────────
    "execution.max_slippage_bps": 20,
    "execution.taker_fallback_after_s": 60,
    "execution.min_notional_usd": 10,
    "execution.max_retry_attempts": 3,
    "execution.retry_backoff_ms": 500,

    # ── Backtest assumptions ────────────────────────────────────────────
    "backtest.starting_capital_usd": 10000,
    "backtest.warmup_days": 60,
    "backtest.funding_accrual": 1.0,
    "backtest.survivorship_bias_safe": 1.0,
    "backtest.use_predicted_funding_in_bt": 1.0,
    "backtest.constant_slippage_bps": 3,

    # ── Data health ─────────────────────────────────────────────────────
    "data_health.max_age_s.trades": 60,
    "data_health.max_age_s.klines": 120,
    "data_health.max_age_s.funding": 900,
    "data_health.max_age_s.oi": 900,
    "data_health.max_age_s.on_chain": 86400,
    "data_health.min_health_pct": 0.99,
    "data_health.halt_on_missing": 1.0,
}


# ── PROFILE_SCOPED_STRING_DEFAULTS ───────────────────────────────────────
# String / enum profile keys with their safe defaults.

PROFILE_SCOPED_STRING_DEFAULTS: dict[str, str] = {
    "strategies.funding_arb.perp_execution": "market",
    "strategies.funding_arb.sub_account": "strategy_a_arb",
    "strategies.factor_portfolio.rebalance_cron": "0 8 * * *",
    "strategies.factor_portfolio.neutral_holding": "USDC",
    "strategies.factor_portfolio.sub_account": "strategy_b_pf",
    "strategies.meta_allocator.method": "sharpe_weighted",
    "strategies.meta_allocator.rebalance_cron": "0 0 * * SUN",
    "execution.default_order_type": "post_only_limit",
    "execution.client_order_id_prefix": "cb",
    "backtest.fee_model": "per_exchange",
    "backtest.slippage_model": "book_proxy",
    "backtest.rebalance_clock": "exchange_time",
    "backtest.data_source": "parquet",
}


# ── PROFILE_SCOPED_DICT_DEFAULTS ────────────────────────────────────────
# Nested-dict profile keys (e.g. weights, sector caps) with safe defaults.

PROFILE_SCOPED_DICT_DEFAULTS: dict[str, dict[str, Any]] = {
    "universe.core_pairs": {"value": ["BTCUSDT", "ETHUSDT"]},
    "universe.exclusions": {"value": ["USDT", "WBTC", "STETH"]},
    "universe.sector_caps_pct": {
        "DeFi": 0.30,
        "L1": 0.40,
        "L2": 0.30,
        "AI": 0.25,
        "Memes": 0.05,
    },
    "strategies.funding_arb.venues_spot": {"value": ["binance"]},
    "strategies.funding_arb.venues_perp": {"value": ["hyperliquid"]},
    "strategies.funding_arb.funding_period_minutes": {
        "binance": 480,
        "bybit": 480,
        "hyperliquid": 60,
    },
    "strategies.factor_portfolio.scoring.weights": {
        "momentum": 0.18,
        "vol_adj_momentum": 0.12,
        "oi_delta": 0.08,
        "funding_persistence": 0.08,
        "on_chain_flow": 0.10,
        "tokenomics": 0.08,
        "narrative_momentum": 0.10,
        "liquidity_health": 0.06,
        "ml": 0.10,
        "trade_aggressor": 0.04,
        "unlock_pressure": 0.03,
        "social": 0.03,
    },
    "strategies.factor_portfolio.scoring.max_scores": {
        "momentum": 5.0,
        "vol_adj_momentum": 5.0,
        "oi_delta": 3.0,
        "funding_persistence": 3.0,
        "on_chain_flow": 5.0,
        "tokenomics": 4.0,
        "narrative_momentum": 3.0,
        "liquidity_health": 3.0,
        "ml": 5.0,
        "trade_aggressor": 3.0,
        "unlock_pressure": 3.0,
        "social": 3.0,
    },
    "risk.counterparty_caps_pct": {
        "binance": 0.30,
        "bybit": 0.30,
        "hyperliquid": 0.25,
        "cold_storage": 0.30,
    },
    "risk.stable_mix_pct": {"USDT": 0.40, "USDC": 0.40, "AUD": 0.20},
}


def all_profile_keys() -> set[str]:
    """Return every key registered across all three typed registries."""
    return (
        set(PROFILE_SCOPED_DEFAULTS)
        | set(PROFILE_SCOPED_STRING_DEFAULTS)
        | set(PROFILE_SCOPED_DICT_DEFAULTS)
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/profile
git commit -m "feat: profile registry with three typed sub-dicts"
```

---

### Task 13: Registry self-consistency test

**Files:**
- Create: `backend/tests/test_profile_registry.py`

- [ ] **Step 1: Write the registry consistency tests**

`backend/tests/test_profile_registry.py`:
```python
"""Tests for profile registry self-consistency."""
from __future__ import annotations

from app.profile.defaults import (
    PROFILE_SCOPED_DEFAULTS,
    PROFILE_SCOPED_DICT_DEFAULTS,
    PROFILE_SCOPED_STRING_DEFAULTS,
    all_profile_keys,
)


def test_no_key_appears_in_more_than_one_registry() -> None:
    """A path cannot be registered as both numeric and string, etc."""
    numeric = set(PROFILE_SCOPED_DEFAULTS)
    string = set(PROFILE_SCOPED_STRING_DEFAULTS)
    dictv = set(PROFILE_SCOPED_DICT_DEFAULTS)
    assert numeric & string == set(), "key in both numeric + string registries"
    assert numeric & dictv == set(), "key in both numeric + dict registries"
    assert string & dictv == set(), "key in both string + dict registries"


def test_all_profile_keys_is_union() -> None:
    """all_profile_keys() returns the union of the three registries."""
    expected = (
        set(PROFILE_SCOPED_DEFAULTS)
        | set(PROFILE_SCOPED_STRING_DEFAULTS)
        | set(PROFILE_SCOPED_DICT_DEFAULTS)
    )
    assert all_profile_keys() == expected


def test_numeric_defaults_are_numeric() -> None:
    """PROFILE_SCOPED_DEFAULTS values must be int or float."""
    for key, value in PROFILE_SCOPED_DEFAULTS.items():
        assert isinstance(value, (int, float)), (
            f"non-numeric default for {key}: {value!r}"
        )


def test_string_defaults_are_strings() -> None:
    """PROFILE_SCOPED_STRING_DEFAULTS values must be str."""
    for key, value in PROFILE_SCOPED_STRING_DEFAULTS.items():
        assert isinstance(value, str), f"non-string default for {key}: {value!r}"


def test_dict_defaults_are_dicts() -> None:
    """PROFILE_SCOPED_DICT_DEFAULTS values must be dict."""
    for key, value in PROFILE_SCOPED_DICT_DEFAULTS.items():
        assert isinstance(value, dict), f"non-dict default for {key}: {value!r}"


def test_dotted_paths_are_valid_identifiers() -> None:
    """Every dotted path segment must be a valid identifier — no spaces / hyphens."""
    for key in all_profile_keys():
        for segment in key.split("."):
            assert segment.isidentifier(), (
                f"non-identifier segment {segment!r} in path {key!r}"
            )
```

- [ ] **Step 2: Run the tests**

```bash
just test tests/test_profile_registry.py
```
Expected: all 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_profile_registry.py
git commit -m "test: profile registry self-consistency"
```

---

## Phase 2.3: ProfileParams accessor

### Task 14: ProfileParams class with TDD

**Files:**
- Create: `backend/app/profile/params.py`
- Create: `backend/tests/test_profile_params.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_profile_params.py`:
```python
"""Tests for ProfileParams — the single accessor for profile values."""
from __future__ import annotations

import pytest

from app.profile.params import ProfileParams, UnknownParamPath


def test_get_returns_profile_value_when_present() -> None:
    profile = {
        "strategies": {"funding_arb": {"entry_bps_per_8h": 12.0}}
    }
    params = ProfileParams(profile)
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == 12.0


def test_get_returns_registry_default_when_missing_from_profile() -> None:
    """A path NOT in the profile falls back to its registered default."""
    params = ProfileParams({})
    # default for entry_bps_per_8h is 8.0 per defaults.py
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == 8.0


def test_get_unknown_path_raises() -> None:
    params = ProfileParams({})
    with pytest.raises(UnknownParamPath):
        params.get("strategies.funding_arb.does_not_exist")


def test_get_string_value() -> None:
    profile = {
        "strategies": {"funding_arb": {"sub_account": "custom_sub"}}
    }
    params = ProfileParams(profile)
    assert params.get("strategies.funding_arb.sub_account") == "custom_sub"


def test_get_dict_value() -> None:
    profile: dict = {
        "risk": {"counterparty_caps_pct": {"binance": 0.50, "bybit": 0.20}}
    }
    params = ProfileParams(profile)
    assert params.get("risk.counterparty_caps_pct") == {
        "binance": 0.50,
        "bybit": 0.20,
    }


def test_get_dict_default_used_when_profile_omits_key() -> None:
    params = ProfileParams({})
    caps = params.get("risk.counterparty_caps_pct")
    assert caps["binance"] == 0.30                    # from registry default
```

- [ ] **Step 2: Run, verify FAILS**

```bash
just test tests/test_profile_params.py
```
Expected: `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Implement ProfileParams**

`backend/app/profile/params.py`:
```python
"""ProfileParams: the single accessor for every profile-scoped value.

Constraint #1 cashes out here: strategy code calls `params.get(path)` and
nothing else. If a path isn't in the registry, boot fails — no silent
fallbacks to literals.
"""
from __future__ import annotations

from typing import Any

from app.profile.defaults import (
    PROFILE_SCOPED_DEFAULTS,
    PROFILE_SCOPED_DICT_DEFAULTS,
    PROFILE_SCOPED_STRING_DEFAULTS,
    all_profile_keys,
)

_MISSING = object()


class UnknownParamPath(KeyError):
    """Raised when a path is requested that isn't in any registry."""


class ProfileParams:
    """Resolves dotted-path lookups against a profile JSONB blob.

    Lookup order:
      1. Profile JSONB (nested via dotted path).
      2. Registry default (numeric / string / dict).
      3. UnknownParamPath if path not in any registry.
    """

    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile

    def get(self, path: str) -> Any:
        value = _walk(self._profile, path)
        if value is not _MISSING:
            return value
        if path in PROFILE_SCOPED_DEFAULTS:
            return PROFILE_SCOPED_DEFAULTS[path]
        if path in PROFILE_SCOPED_STRING_DEFAULTS:
            return PROFILE_SCOPED_STRING_DEFAULTS[path]
        if path in PROFILE_SCOPED_DICT_DEFAULTS:
            return PROFILE_SCOPED_DICT_DEFAULTS[path]
        raise UnknownParamPath(
            f"path {path!r} is not in PROFILE_SCOPED_DEFAULTS, _STRING_, or _DICT_"
        )

    def keys(self) -> set[str]:
        """Return every registered path (registry contents)."""
        return all_profile_keys()


def _walk(d: dict[str, Any], path: str) -> Any:
    """Nested dict lookup via dotted path. Returns _MISSING if absent."""
    cur: Any = d
    for segment in path.split("."):
        if not isinstance(cur, dict) or segment not in cur:
            return _MISSING
        cur = cur[segment]
    return cur
```

- [ ] **Step 4: Verify all tests pass**

```bash
just test tests/test_profile_params.py
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/profile/params.py backend/tests/test_profile_params.py
git commit -m "feat: ProfileParams accessor with registry-default fallback"
```

---

## Phase 2.4: Apply mechanism (Constraint #3 — leak-gap prevention)

### Task 15: apply_profile with atomic transaction

**Files:**
- Create: `backend/app/profile/apply.py`
- Create: `backend/tests/test_profile_apply.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_profile_apply.py`:
```python
"""Tests for apply_profile — atomic switch with leak-gap prevention."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile
from app.profile.apply import apply_profile, get_active_profile_config
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS


@pytest.mark.asyncio
async def test_apply_switches_active_flag(db_session: AsyncSession) -> None:
    a = StrategyProfile(name="a", config={}, is_active=True)
    b = StrategyProfile(name="b", config={}, is_active=False)
    db_session.add_all([a, b])
    await db_session.flush()

    await apply_profile(db_session, b.id)
    await db_session.flush()

    refreshed_a = (await db_session.execute(select(StrategyProfile).where(StrategyProfile.id == a.id))).scalar_one()
    refreshed_b = (await db_session.execute(select(StrategyProfile).where(StrategyProfile.id == b.id))).scalar_one()
    assert refreshed_a.is_active is False
    assert refreshed_b.is_active is True


@pytest.mark.asyncio
async def test_apply_unknown_id_raises(db_session: AsyncSession) -> None:
    with pytest.raises(LookupError):
        await apply_profile(db_session, uuid.uuid4())


@pytest.mark.asyncio
async def test_apply_round_trip_a_b_a_preserves_a_values(db_session: AsyncSession) -> None:
    """Switching A -> B -> A leaves no leaked keys from B."""
    a_config = {
        "strategies": {
            "funding_arb": {"entry_bps_per_8h": 12.0},
        }
    }
    b_config = {
        "strategies": {
            "funding_arb": {"entry_bps_per_8h": 20.0},
        }
    }
    a = StrategyProfile(name="aggressive", config=a_config, is_active=True)
    b = StrategyProfile(name="more_aggressive", config=b_config, is_active=False)
    db_session.add_all([a, b])
    await db_session.flush()

    await apply_profile(db_session, b.id)
    config_after_b = await get_active_profile_config(db_session)
    assert config_after_b["strategies"]["funding_arb"]["entry_bps_per_8h"] == 20.0

    await apply_profile(db_session, a.id)
    config_after_a = await get_active_profile_config(db_session)
    assert config_after_a["strategies"]["funding_arb"]["entry_bps_per_8h"] == 12.0


@pytest.mark.asyncio
async def test_apply_resets_omitted_keys_to_defaults(db_session: AsyncSession) -> None:
    """Apply walks the registry: any path absent from the new profile resolves
    to its registry default via ProfileParams (no in-DB rewriting needed;
    ProfileParams handles fallback)."""
    from app.profile.params import ProfileParams

    a = StrategyProfile(
        name="custom",
        config={"strategies": {"funding_arb": {"entry_bps_per_8h": 50.0}}},
        is_active=True,
    )
    b = StrategyProfile(name="defaulty", config={}, is_active=False)
    db_session.add_all([a, b])
    await db_session.flush()

    await apply_profile(db_session, b.id)
    config = await get_active_profile_config(db_session)
    params = ProfileParams(config)
    # b's profile is empty, so this resolves to the registry default:
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == (
        PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.entry_bps_per_8h"]
    )
```

- [ ] **Step 2: Run, verify FAILS**

```bash
just test tests/test_profile_apply.py
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement apply_profile**

`backend/app/profile/apply.py`:
```python
"""apply_profile: atomic switch of the active strategy profile.

Constraint #3 (leak-gap prevention) is enforced *at read time* via
ProfileParams, which falls back to the registry default for any key the new
active profile doesn't carry. Apply itself only flips the is_active flags;
ProfileParams does the per-key default resolution on every get().

This design means we never have to rewrite JSONB blobs at apply time — the
registry is the source of truth, and the profile is treated as a sparse
override layer.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


class NoActiveProfile(LookupError):
    """Raised when no profile has is_active = True."""


async def apply_profile(session: AsyncSession, profile_id: uuid.UUID) -> StrategyProfile:
    """Switch the active flag from whatever is current to `profile_id`.

    Runs in a single transaction (the session's existing transaction):
      1. Verify target profile exists.
      2. Clear is_active on all rows.
      3. Set is_active on the target.
    """
    target_q = select(StrategyProfile).where(StrategyProfile.id == profile_id)
    target = (await session.execute(target_q)).scalar_one_or_none()
    if target is None:
        raise LookupError(f"strategy profile {profile_id} not found")

    await session.execute(
        update(StrategyProfile).where(StrategyProfile.is_active).values(is_active=False)
    )
    await session.execute(
        update(StrategyProfile)
        .where(StrategyProfile.id == profile_id)
        .values(is_active=True)
    )
    await session.flush()
    await session.refresh(target)
    return target


async def get_active_profile_config(session: AsyncSession) -> dict[str, Any]:
    """Return the active profile's JSONB config blob.

    Raises NoActiveProfile if no profile is active.
    """
    q = select(StrategyProfile).where(StrategyProfile.is_active)
    profile = (await session.execute(q)).scalar_one_or_none()
    if profile is None:
        raise NoActiveProfile("no active strategy profile")
    return dict(profile.config)
```

- [ ] **Step 4: Verify tests pass**

```bash
just test tests/test_profile_apply.py
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/profile/apply.py backend/tests/test_profile_apply.py
git commit -m "feat: apply_profile atomic switch with leak-gap prevention"
```

---

## Phase 2.5: Pydantic schemas

### Task 16: Profile JSON schema (Pydantic v2)

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/strategy_profile.py`
- Create: `backend/tests/test_profile_schemas.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_profile_schemas.py`:
```python
"""Tests for Pydantic schemas validating profile JSONB."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.strategy_profile import StrategyProfileConfig


def test_minimal_valid_profile_parses() -> None:
    config = {
        "meta": {"name": "balanced_v1", "version": 1},
    }
    parsed = StrategyProfileConfig.model_validate(config)
    assert parsed.meta.name == "balanced_v1"


def test_full_profile_parses() -> None:
    config = {
        "meta": {"name": "balanced_v1", "version": 1},
        "universe": {
            "core_pairs": ["BTCUSDT", "ETHUSDT"],
            "alt_universe_size": 100,
        },
        "strategies": {
            "funding_arb": {
                "enabled": True,
                "allocation_pct": 0.40,
                "entry_bps_per_8h": 8.0,
            },
            "factor_portfolio": {
                "enabled": True,
                "allocation_pct": 0.20,
            },
        },
        "risk": {
            "max_gross_leverage": 1.50,
        },
    }
    parsed = StrategyProfileConfig.model_validate(config)
    assert parsed.strategies.funding_arb.entry_bps_per_8h == 8.0


def test_allocation_pct_out_of_range_rejects() -> None:
    config = {
        "meta": {"name": "x", "version": 1},
        "strategies": {"funding_arb": {"allocation_pct": 1.5}},  # > 1.0
    }
    with pytest.raises(ValidationError):
        StrategyProfileConfig.model_validate(config)


def test_negative_leverage_rejects() -> None:
    config = {
        "meta": {"name": "x", "version": 1},
        "risk": {"max_gross_leverage": -1.0},
    }
    with pytest.raises(ValidationError):
        StrategyProfileConfig.model_validate(config)
```

- [ ] **Step 2: Run, verify FAILS**

```bash
just test tests/test_profile_schemas.py
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the schemas**

`backend/app/schemas/__init__.py`:
```python
```

`backend/app/schemas/strategy_profile.py`:
```python
"""Pydantic v2 schemas validating strategy profile JSONB.

Schemas mirror the registry structure but enforce ranges. Schema validation is
the *boundary check* — internal code reads via ProfileParams which trusts the
profile is already validated.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProfileMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    description: str | None = None


class FundingArbConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    allocation_pct: float = Field(ge=0.0, le=1.0, default=0.40)
    entry_bps_per_8h: float = Field(ge=-100.0, le=100.0, default=8.0)
    exit_bps_per_8h: float = Field(ge=-100.0, le=100.0, default=4.0)
    basis_halt_bps: float = Field(ge=0.0, le=10_000.0, default=80.0)
    max_position_pct: float = Field(ge=0.0, le=1.0, default=0.10)
    hedge_drift_halt_pct: float = Field(ge=0.0, le=1.0, default=0.05)
    venues_spot: list[str] = Field(default_factory=lambda: ["binance"])
    venues_perp: list[str] = Field(default_factory=lambda: ["hyperliquid"])
    sub_account: str = "strategy_a_arb"


class FactorPortfolioConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    allocation_pct: float = Field(ge=0.0, le=1.0, default=0.20)
    top_decile_pct: float = Field(ge=0.0, le=0.50, default=0.10)
    bottom_decile_pct: float = Field(ge=0.0, le=0.50, default=0.10)
    shorts_enabled: bool = False
    rebalance_cron: str = "0 8 * * *"
    sub_account: str = "strategy_b_pf"


class MetaAllocatorConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    method: str = Field(
        default="sharpe_weighted",
        pattern="^(sharpe_weighted|risk_parity|static|kelly)$",
    )
    lookback_days: int = Field(ge=1, le=365, default=30)
    min_weight_pct: float = Field(ge=0.0, le=1.0, default=0.10)
    max_weight_pct: float = Field(ge=0.0, le=1.0, default=0.70)
    rebalance_cron: str = "0 0 * * SUN"


class StrategiesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    funding_arb: FundingArbConfig = Field(default_factory=FundingArbConfig)
    factor_portfolio: FactorPortfolioConfig = Field(default_factory=FactorPortfolioConfig)
    meta_allocator: MetaAllocatorConfig = Field(default_factory=MetaAllocatorConfig)


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    core_pairs: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    alt_universe_size: int = Field(ge=1, le=1000, default=100)
    min_daily_volume_usd: float = Field(ge=0.0, default=5_000_000.0)
    min_listing_age_days: int = Field(ge=0, le=365, default=30)


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    max_gross_leverage: float = Field(ge=0.0, le=10.0, default=1.50)
    max_net_leverage: float = Field(ge=0.0, le=10.0, default=0.50)
    max_drawdown_pct: float = Field(ge=0.0, le=1.0, default=0.20)
    daily_drawdown_halt_pct: float = Field(ge=0.0, le=1.0, default=0.05)
    max_gross_per_asset_pct: float = Field(ge=0.0, le=1.0, default=0.15)
    deadman_timeout_s: int = Field(ge=1, le=3600, default=60)


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    default_order_type: str = Field(
        default="post_only_limit",
        pattern="^(post_only_limit|limit|market|ioc)$",
    )
    max_slippage_bps: int = Field(ge=0, le=10_000, default=20)
    taker_fallback_after_s: int = Field(ge=0, le=3600, default=60)
    min_notional_usd: float = Field(ge=0.0, default=10.0)


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    starting_capital_usd: float = Field(ge=0.0, default=10_000.0)
    fee_model: str = Field(default="per_exchange", pattern="^(per_exchange|constant_bps)$")
    slippage_model: str = Field(
        default="book_proxy", pattern="^(book_proxy|atr_based|constant_bps)$"
    )
    funding_accrual: bool = True
    survivorship_bias_safe: bool = True
    start_date: str | None = None
    end_date: str | None = None


class StrategyProfileConfig(BaseModel):
    """Root schema for the profile JSONB blob."""

    model_config = ConfigDict(extra="allow")
    meta: ProfileMeta
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
```

- [ ] **Step 4: Verify tests pass**

```bash
just test tests/test_profile_schemas.py
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/tests/test_profile_schemas.py
git commit -m "feat: pydantic v2 schemas for strategy profile JSONB"
```

---

## Phase 2.6: Repository + Service layers

### Task 17: StrategyProfileRepository (DB queries)

**Files:**
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/app/repositories/strategy_profile.py`

- [ ] **Step 1: Create the repository**

`backend/app/repositories/__init__.py`:
```python
```

`backend/app/repositories/strategy_profile.py`:
```python
"""Repository layer for StrategyProfile (DB queries only — no business logic)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


class StrategyProfileRepository:
    """Async DB queries for the strategy_profiles table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: uuid.UUID) -> StrategyProfile | None:
        return (
            await self._session.execute(
                select(StrategyProfile).where(StrategyProfile.id == profile_id)
            )
        ).scalar_one_or_none()

    async def list_all(self) -> list[StrategyProfile]:
        result = await self._session.execute(
            select(StrategyProfile).order_by(StrategyProfile.updated_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_name(self, name: str) -> list[StrategyProfile]:
        result = await self._session.execute(
            select(StrategyProfile)
            .where(StrategyProfile.name == name)
            .order_by(StrategyProfile.version.desc())
        )
        return list(result.scalars().all())

    async def get_active(self) -> StrategyProfile | None:
        return (
            await self._session.execute(
                select(StrategyProfile).where(StrategyProfile.is_active)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        config: dict[str, Any],
        description: str | None = None,
    ) -> StrategyProfile:
        prior_versions = await self.list_by_name(name)
        next_version = (prior_versions[0].version + 1) if prior_versions else 1
        profile = StrategyProfile(
            name=name,
            description=description,
            config=config,
            version=next_version,
            is_active=False,
        )
        self._session.add(profile)
        await self._session.flush()
        return profile
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/repositories
git commit -m "feat: StrategyProfileRepository for CRUD"
```

---

### Task 18: ProfileService (business logic)

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/profile_service.py`

- [ ] **Step 1: Create the service**

`backend/app/services/__init__.py`:
```python
```

`backend/app/services/profile_service.py`:
```python
"""ProfileService — orchestrates validation, persistence, and apply mechanics."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile
from app.profile.apply import apply_profile, get_active_profile_config
from app.repositories.strategy_profile import StrategyProfileRepository
from app.schemas.strategy_profile import StrategyProfileConfig


class ProfileService:
    """High-level operations on strategy profiles.

    Validates JSONB via Pydantic on save; persists via the repository;
    coordinates the atomic apply via profile.apply.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = StrategyProfileRepository(session)

    async def create(
        self, *, name: str, config: dict[str, Any], description: str | None = None
    ) -> StrategyProfile:
        StrategyProfileConfig.model_validate(config)  # raises ValidationError on failure
        return await self._repo.create(name=name, config=config, description=description)

    async def get(self, profile_id: uuid.UUID) -> StrategyProfile | None:
        return await self._repo.get(profile_id)

    async def list_all(self) -> list[StrategyProfile]:
        return await self._repo.list_all()

    async def list_by_name(self, name: str) -> list[StrategyProfile]:
        return await self._repo.list_by_name(name)

    async def get_active(self) -> StrategyProfile | None:
        return await self._repo.get_active()

    async def get_active_config(self) -> dict[str, Any]:
        return await get_active_profile_config(self._session)

    async def apply(self, profile_id: uuid.UUID) -> StrategyProfile:
        return await apply_profile(self._session, profile_id)

    async def clone(
        self, profile_id: uuid.UUID, *, new_name: str
    ) -> StrategyProfile:
        source = await self._repo.get(profile_id)
        if source is None:
            raise LookupError(f"strategy profile {profile_id} not found")
        return await self._repo.create(
            name=new_name, config=dict(source.config), description=source.description
        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services
git commit -m "feat: ProfileService orchestrating validate + persist + apply"
```

---

## Phase 2.7: API endpoints

### Task 19: Strategy profile API endpoints

**Files:**
- Create: `backend/app/api/strategy_profiles.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/__init__.py`
- Create: `backend/tests/api/test_strategy_profiles.py`

- [ ] **Step 1: Write the failing API test**

`backend/tests/api/__init__.py`:
```python
```

`backend/tests/api/test_strategy_profiles.py`:
```python
"""Integration tests for the strategy-profiles API."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_get_profile(client: TestClient) -> None:
    payload = {
        "name": "test_a",
        "config": {
            "meta": {"name": "test_a", "version": 1},
            "strategies": {"funding_arb": {"allocation_pct": 0.30}},
        },
    }
    created = client.post("/api/v1/strategy-profiles", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    profile_id = body["id"]
    assert body["name"] == "test_a"
    assert body["version"] == 1
    assert body["is_active"] is False

    fetched = client.get(f"/api/v1/strategy-profiles/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == profile_id


def test_create_invalid_profile_rejects(client: TestClient) -> None:
    payload = {
        "name": "bad",
        "config": {
            "meta": {"name": "bad", "version": 1},
            "strategies": {"funding_arb": {"allocation_pct": 2.0}},  # > 1.0
        },
    }
    r = client.post("/api/v1/strategy-profiles", json=payload)
    assert r.status_code == 422


def test_list_returns_all_profiles(client: TestClient) -> None:
    for name in ["one", "two", "three"]:
        client.post(
            "/api/v1/strategy-profiles",
            json={
                "name": name,
                "config": {"meta": {"name": name, "version": 1}},
            },
        )
    r = client.get("/api/v1/strategy-profiles")
    assert r.status_code == 200
    body = r.json()
    names = [p["name"] for p in body]
    assert {"one", "two", "three"}.issubset(set(names))


def test_apply_makes_profile_active(client: TestClient) -> None:
    a = client.post(
        "/api/v1/strategy-profiles",
        json={"name": "a", "config": {"meta": {"name": "a", "version": 1}}},
    ).json()
    b = client.post(
        "/api/v1/strategy-profiles",
        json={"name": "b", "config": {"meta": {"name": "b", "version": 1}}},
    ).json()

    client.post(f"/api/v1/strategy-profiles/{a['id']}/apply")
    active = client.get("/api/v1/strategy-profiles/active").json()
    assert active["id"] == a["id"]

    client.post(f"/api/v1/strategy-profiles/{b['id']}/apply")
    active = client.get("/api/v1/strategy-profiles/active").json()
    assert active["id"] == b["id"]


def test_clone_creates_new_row_same_config(client: TestClient) -> None:
    src = client.post(
        "/api/v1/strategy-profiles",
        json={
            "name": "src",
            "config": {
                "meta": {"name": "src", "version": 1},
                "strategies": {"funding_arb": {"entry_bps_per_8h": 12.0}},
            },
        },
    ).json()

    cloned = client.post(
        f"/api/v1/strategy-profiles/{src['id']}/clone",
        json={"new_name": "src_copy"},
    )
    assert cloned.status_code == 201
    body = cloned.json()
    assert body["id"] != src["id"]
    assert body["name"] == "src_copy"
    assert body["config"]["strategies"]["funding_arb"]["entry_bps_per_8h"] == 12.0
```

- [ ] **Step 2: Run, verify FAILS**

```bash
just test tests/api/test_strategy_profiles.py
```
Expected: 404s on every endpoint.

- [ ] **Step 3: Implement the API**

`backend/app/api/strategy_profiles.py`:
```python
"""HTTP API for managing strategy profiles."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/v1/strategy-profiles", tags=["strategy-profiles"])


# ── DTOs ─────────────────────────────────────────────────────────────────

class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    config: dict[str, Any]


class CloneRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=120)


class ProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    config: dict[str, Any]
    version: int
    is_active: bool


# ── Routes ───────────────────────────────────────────────────────────────

@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(
    req: ProfileCreateRequest, db: AsyncSession = Depends(get_db)
) -> ProfileResponse:
    service = ProfileService(db)
    try:
        created = await service.create(
            name=req.name, description=req.description, config=req.config
        )
    except ValueError as e:  # pydantic ValidationError subclasses ValueError
        raise HTTPException(status_code=422, detail=str(e)) from e
    await db.commit()
    return ProfileResponse.model_validate(created, from_attributes=True)


@router.get("", response_model=list[ProfileResponse])
async def list_profiles(db: AsyncSession = Depends(get_db)) -> list[ProfileResponse]:
    service = ProfileService(db)
    rows = await service.list_all()
    return [ProfileResponse.model_validate(r, from_attributes=True) for r in rows]


@router.get("/active", response_model=ProfileResponse)
async def get_active(db: AsyncSession = Depends(get_db)) -> ProfileResponse:
    service = ProfileService(db)
    row = await service.get_active()
    if row is None:
        raise HTTPException(status_code=404, detail="no active profile")
    return ProfileResponse.model_validate(row, from_attributes=True)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ProfileResponse:
    service = ProfileService(db)
    row = await service.get(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return ProfileResponse.model_validate(row, from_attributes=True)


@router.post("/{profile_id}/apply", response_model=ProfileResponse)
async def apply(
    profile_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ProfileResponse:
    service = ProfileService(db)
    try:
        row = await service.apply(profile_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await db.commit()
    return ProfileResponse.model_validate(row, from_attributes=True)


@router.post(
    "/{profile_id}/clone",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone(
    profile_id: uuid.UUID,
    req: CloneRequest,
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    service = ProfileService(db)
    try:
        row = await service.clone(profile_id, new_name=req.new_name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await db.commit()
    return ProfileResponse.model_validate(row, from_attributes=True)
```

- [ ] **Step 4: Register the router**

`backend/app/main.py`:
```python
"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import health, strategy_profiles
from app.deps import lifespan

app = FastAPI(title="cryptobot", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(strategy_profiles.router)
```

- [ ] **Step 5: Verify tests pass**

```bash
just test tests/api/test_strategy_profiles.py
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/strategy_profiles.py backend/app/main.py backend/tests/api
git commit -m "feat: strategy-profiles HTTP API (create, list, get, apply, clone)"
```

---

## Phase 2.8: Fixture profiles

### Task 20: Named profile JSON fixtures

**Files:**
- Create: `profiles/paper_safari.json`
- Create: `profiles/conservative_funding_only.json`
- Create: `profiles/balanced_v1.json`

- [ ] **Step 1: Create `profiles/paper_safari.json`**

```json
{
  "meta": {
    "name": "paper_safari",
    "version": 1,
    "description": "Tiny sizes for paper-trading reality testing. Set Freqtrade dry_run=true."
  },
  "universe": {
    "core_pairs": ["BTCUSDT", "ETHUSDT"],
    "alt_universe_size": 20
  },
  "strategies": {
    "funding_arb": {
      "enabled": true,
      "allocation_pct": 0.01,
      "max_position_pct": 0.01
    },
    "factor_portfolio": {
      "enabled": true,
      "allocation_pct": 0.01
    },
    "meta_allocator": {
      "enabled": false,
      "method": "static"
    }
  },
  "risk": {
    "max_gross_leverage": 1.0,
    "max_gross_per_asset_pct": 0.02
  },
  "execution": {
    "default_order_type": "post_only_limit",
    "max_slippage_bps": 50
  }
}
```

- [ ] **Step 2: Create `profiles/conservative_funding_only.json`**

```json
{
  "meta": {
    "name": "conservative_funding_only",
    "version": 1,
    "description": "First weeks live: only Strategy A (funding arb) active. B disabled."
  },
  "strategies": {
    "funding_arb": {
      "enabled": true,
      "allocation_pct": 0.30,
      "entry_bps_per_8h": 10.0,
      "exit_bps_per_8h": 5.0
    },
    "factor_portfolio": {
      "enabled": false,
      "allocation_pct": 0.0
    },
    "meta_allocator": {
      "enabled": false,
      "method": "static"
    }
  },
  "risk": {
    "max_gross_leverage": 1.0,
    "drawdown_brake.trigger_pct": 0.05,
    "drawdown_brake.full_pct": 0.15
  }
}
```

- [ ] **Step 3: Create `profiles/balanced_v1.json`**

```json
{
  "meta": {
    "name": "balanced_v1",
    "version": 1,
    "description": "Default after both strategies have 30+ days live. Round 5 allocation: A heavier than B."
  },
  "universe": {
    "core_pairs": ["BTCUSDT", "ETHUSDT"],
    "alt_universe_size": 100,
    "min_listing_age_days": 30,
    "min_daily_volume_usd": 5000000
  },
  "strategies": {
    "funding_arb": {
      "enabled": true,
      "allocation_pct": 0.40,
      "entry_bps_per_8h": 8.0,
      "venues_spot": ["binance"],
      "venues_perp": ["hyperliquid"],
      "sub_account": "strategy_a_arb"
    },
    "factor_portfolio": {
      "enabled": true,
      "allocation_pct": 0.20,
      "rebalance_cron": "0 8 * * *",
      "top_decile_pct": 0.10,
      "shorts_enabled": false,
      "sub_account": "strategy_b_pf"
    },
    "meta_allocator": {
      "enabled": true,
      "method": "sharpe_weighted",
      "rebalance_cron": "0 0 * * SUN",
      "lookback_days": 30
    }
  },
  "risk": {
    "max_gross_leverage": 1.50,
    "max_gross_per_asset_pct": 0.15
  },
  "execution": {
    "default_order_type": "post_only_limit",
    "max_slippage_bps": 20
  },
  "backtest": {
    "start_date": "2024-01-01",
    "end_date": "2026-04-30",
    "fee_model": "per_exchange",
    "funding_accrual": true,
    "survivorship_bias_safe": true,
    "starting_capital_usd": 10000.0
  }
}
```

- [ ] **Step 4: Verify each fixture validates via Pydantic**

Add to `backend/tests/test_profile_schemas.py`:
```python
import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "profiles"


@pytest.mark.parametrize(
    "fixture_path",
    [
        FIXTURES_DIR / "paper_safari.json",
        FIXTURES_DIR / "conservative_funding_only.json",
        FIXTURES_DIR / "balanced_v1.json",
    ],
)
def test_named_fixture_validates(fixture_path: pathlib.Path) -> None:
    with open(fixture_path) as f:
        config = json.load(f)
    StrategyProfileConfig.model_validate(config)
```

- [ ] **Step 5: Run tests**

```bash
just test tests/test_profile_schemas.py
```
Expected: 7 passed (4 original + 3 fixture).

- [ ] **Step 6: Commit**

```bash
git add profiles backend/tests/test_profile_schemas.py
git commit -m "feat: ship named profile fixtures (paper_safari, conservative_funding_only, balanced_v1)"
```

---

### Task 21: Fixture loader CLI

**Files:**
- Create: `backend/app/profile/loader.py`
- Create: `backend/scripts/load_fixtures.py`

- [ ] **Step 1: Create the loader logic**

`backend/app/profile/loader.py`:
```python
"""Load named profile fixtures from `profiles/` into the DB."""
from __future__ import annotations

import json
import pathlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.strategy_profile import StrategyProfileRepository
from app.schemas.strategy_profile import StrategyProfileConfig


async def load_fixtures(session: AsyncSession, fixtures_dir: pathlib.Path) -> int:
    """Import every `*.json` in fixtures_dir as a new profile row.

    Each fixture's filename (minus `.json`) is used as the profile name.
    Skips fixtures whose name already exists.
    """
    repo = StrategyProfileRepository(session)
    loaded = 0
    for path in sorted(fixtures_dir.glob("*.json")):
        with open(path) as f:
            config: dict[str, Any] = json.load(f)
        StrategyProfileConfig.model_validate(config)
        name = path.stem
        existing = await repo.list_by_name(name)
        if existing:
            continue
        await repo.create(
            name=name,
            config=config,
            description=config.get("meta", {}).get("description"),
        )
        loaded += 1
    await session.commit()
    return loaded
```

- [ ] **Step 2: Create the CLI script**

`backend/scripts/__init__.py`:
```python
```

`backend/scripts/load_fixtures.py`:
```python
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
```

- [ ] **Step 3: Run the loader locally**

```bash
just mig-up
cd backend && uv run python -m scripts.load_fixtures
```
Expected: `loaded 3 fixture(s)`.

- [ ] **Step 4: Verify via API**

```bash
cd backend && uv run fastapi dev app/main.py &
sleep 3
curl -s http://localhost:8000/api/v1/strategy-profiles | python -m json.tool
kill %1
```
Expected: JSON array with three profiles.

- [ ] **Step 5: Add a justfile recipe**

Append to `justfile`:
```just
# Load profile fixtures into the DB
load-fixtures:
    cd backend && uv run python -m scripts.load_fixtures
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/profile/loader.py backend/scripts justfile
git commit -m "feat: fixture loader for named profile JSON files"
```

---

## Phase 2.9: Strategy interface stub + AST lint integration test

### Task 22: Strategy Protocol skeleton

**Files:**
- Create: `backend/app/strategies/base.py`

- [ ] **Step 1: Create the Strategy Protocol**

`backend/app/strategies/base.py`:
```python
"""Strategy interface (Protocol). Implementations live in sibling modules.

Per Constraint #1 + #2:
  - `evaluate(state, params)` is a pure function — same code in backtest + live.
  - `required_param_paths()` enumerates registry paths the strategy reads;
    boot fails if any path isn't in the registry.

Implementations MUST NOT contain numeric literals. The AST lint at
`scripts/lint_no_literals_in_strategies.py` enforces this in CI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any, Protocol

from app.profile.params import ProfileParams


class ActionType(str, Enum):
    FLAT = "flat"
    LONG_SPOT_SHORT_PERP = "long_spot_short_perp"
    SHORT_SPOT_LONG_PERP = "short_spot_long_perp"
    LONG = "long"
    SHORT = "short"
    HOLD = "hold"
    HALT = "halt"


@dataclass(frozen=True)
class MarketState:
    """Snapshot of relevant market data at a decision moment.

    Per-strategy state shape varies; this is the union surface.
    """

    ts_ms: int
    instrument: str
    spot_price: float | None = None
    perp_price: float | None = None
    predicted_funding_bps_8h: float | None = None
    basis_bps: float | None = None
    open_interest: float | None = None
    features: dict[str, Any] | None = None


@dataclass(frozen=True)
class Action:
    """Decision output. `target_size_pct` is fraction of strategy allocation."""

    type: ActionType
    target_size_pct: float = 0.0
    reason: str = ""


class Strategy(Protocol):
    """Pure-function decision interface."""

    name: str

    @classmethod
    def required_param_paths(cls) -> set[str]:
        """Registry paths this strategy reads. Boot fails if any missing."""
        ...

    def evaluate(self, state: MarketState, params: ProfileParams) -> Action:
        """Return the desired Action given state + profile params."""
        ...

    def warmup_required(self, params: ProfileParams) -> timedelta:
        """Historical data needed before first decision."""
        ...
```

- [ ] **Step 2: Verify AST lint still passes**

```bash
python scripts/lint_no_literals_in_strategies.py && echo "lint: clean"
```
Expected: `lint: clean`.

Note: `base.py` contains no numeric literals (the `target_size_pct: float = 0.0` is a `0.0` literal, which is in the ALLOWED set with `{0, 1, -1}` — but `0.0` is technically a float `0.0` which **does not equal** `0`. **Fix:** update ALLOWED to include `0.0` and `1.0`).

- [ ] **Step 3: Update the ALLOWED set**

Edit `scripts/lint_no_literals_in_strategies.py`:
```python
ALLOWED: set[int | float] = {0, 1, -1, 0.0, 1.0, -1.0}
```

- [ ] **Step 4: Re-run AST lint**

```bash
python scripts/lint_no_literals_in_strategies.py && echo "lint: clean"
```
Expected: `lint: clean`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/strategies/base.py scripts/lint_no_literals_in_strategies.py
git commit -m "feat: Strategy Protocol with MarketState + Action"
```

---

### Task 23: AST lint detects a deliberate literal

**Files:**
- Create: `backend/tests/test_ast_lint.py`

- [ ] **Step 1: Write the test**

`backend/tests/test_ast_lint.py`:
```python
"""Tests for the AST lint script."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile


REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
LINT_SCRIPT = REPO_ROOT / "scripts" / "lint_no_literals_in_strategies.py"
STRATEGIES_DIR = REPO_ROOT / "backend" / "app" / "strategies"


def test_lint_passes_on_clean_strategies_dir() -> None:
    result = subprocess.run(
        [sys.executable, str(LINT_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"unexpected lint failure on clean tree:\n{result.stderr}"
    )


def test_lint_catches_injected_literal(tmp_path: pathlib.Path) -> None:
    """Drop a file with a numeric literal into strategies/ and expect failure."""
    offending = STRATEGIES_DIR / "_lint_probe.py"
    offending.write_text(
        '"""Test probe for AST lint."""\n'
        "def evaluate() -> float:\n"
        "    return 8.0\n"   # literal — must fail lint
    )
    try:
        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "_lint_probe.py" in result.stderr
        assert "8.0" in result.stderr
    finally:
        offending.unlink(missing_ok=True)
```

- [ ] **Step 2: Run the test**

```bash
just test tests/test_ast_lint.py
```
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_ast_lint.py
git commit -m "test: AST lint catches injected numeric literals in strategies/"
```

---

### Task 24: pytest cross-check — registry ↔ strategy params.get calls

**Files:**
- Modify: `backend/tests/test_profile_registry.py`

- [ ] **Step 1: Add cross-check test**

Append to `backend/tests/test_profile_registry.py`:
```python
import ast
import pathlib

from app.profile.defaults import all_profile_keys

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
STRATEGIES_DIR = REPO_ROOT / "backend" / "app" / "strategies"


def _collect_params_get_paths(py_file: pathlib.Path) -> list[str]:
    """Return every string passed to a `.get(...)` method call in py_file."""
    tree = ast.parse(py_file.read_text())
    paths: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            paths.append(node.args[0].value)
    return paths


def test_every_params_get_path_is_in_registry() -> None:
    """If a strategy calls `params.get('foo.bar')`, 'foo.bar' must be registered."""
    registered = all_profile_keys()
    for py_file in STRATEGIES_DIR.rglob("*.py"):
        if py_file.name == "base.py":
            continue
        for path in _collect_params_get_paths(py_file):
            assert path in registered, (
                f"{py_file}: params.get({path!r}) but path not in registry"
            )
```

- [ ] **Step 2: Run the test**

```bash
just test tests/test_profile_registry.py
```
Expected: 6 passed (existing 5 + new 1; strategies dir is empty except base.py so cross-check is vacuously true).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_profile_registry.py
git commit -m "test: cross-check params.get paths against registry"
```

---

## Phase 2.10: Finishing up

### Task 25: Full smoke test — end-to-end profile flow

**Files:**
- Create: `backend/tests/test_end_to_end.py`

- [ ] **Step 1: Write the test**

`backend/tests/test_end_to_end.py`:
```python
"""End-to-end smoke test: create -> apply -> read active -> ProfileParams."""
from __future__ import annotations

import json
import pathlib

from fastapi.testclient import TestClient

from app.profile.params import ProfileParams

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "profiles"


def test_full_flow_create_apply_read_resolve(client: TestClient) -> None:
    with open(FIXTURES_DIR / "balanced_v1.json") as f:
        config = json.load(f)

    created = client.post(
        "/api/v1/strategy-profiles",
        json={"name": "balanced_v1", "config": config},
    ).json()
    assert created["is_active"] is False

    client.post(f"/api/v1/strategy-profiles/{created['id']}/apply")
    active = client.get("/api/v1/strategy-profiles/active").json()
    assert active["id"] == created["id"]

    params = ProfileParams(active["config"])
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == 8.0
    assert params.get("strategies.funding_arb.allocation_pct") == 0.40
    assert params.get("strategies.factor_portfolio.allocation_pct") == 0.20
    # Path NOT in the balanced_v1 profile resolves to registry default:
    assert params.get("execution.min_notional_usd") == 10
```

- [ ] **Step 2: Run the test**

```bash
just test tests/test_end_to_end.py
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "test: end-to-end create -> apply -> read -> ProfileParams"
```

---

### Task 26: Full test sweep + mypy + lint pass

- [ ] **Step 1: Run the full test suite**

```bash
just test
```
Expected: ~30 tests pass (5 registry + 6 params + 4 apply + 7 schemas + 5 api + 2 ast_lint + 1 end_to_end + 1 health = 31).

- [ ] **Step 2: Run mypy --strict**

```bash
just typecheck
```
Expected: `Success: no issues found`. If any issues are reported, fix them inline (add explicit return type annotations, narrow `Any`, etc.).

- [ ] **Step 3: Run ruff + AST lint**

```bash
just lint
```
Expected: no findings.

- [ ] **Step 4: If anything fails, fix and re-commit**

For each failure: read the message, locate the cause, fix the offending file, re-run the failing check, then `git add` + `git commit -m "fix: <what>"`.

---

### Task 27: README quickstart

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create the README**

`README.md`:
```markdown
# cryptobot

Multi-strategy crypto trading system. Phase 1 + Phase 2 ships the foundational scaffolding and the profile system.

## Architecture

See [`docs/superpowers/research/cryptobot-strategy-architecture.md`](docs/superpowers/research/cryptobot-strategy-architecture.md) for the full research. Phase 1 + Phase 2 implementation plan: [`docs/superpowers/plans/2026-05-23-cryptobot-strategy-architecture.md`](docs/superpowers/plans/2026-05-23-cryptobot-strategy-architecture.md).

## Local dev quickstart

```bash
# 1. Boot postgres
just up

# 2. Install deps + migrate
cd backend && uv sync
cd .. && just mig-up

# 3. Load named profile fixtures
just load-fixtures

# 4. Run the API
just api

# 5. In another shell, query
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/strategy-profiles | python -m json.tool
```

## Common commands

- `just test` — run pytest
- `just typecheck` — mypy --strict
- `just lint` — ruff + AST lint
- `just fmt` — ruff auto-format
- `just mig-new "message"` — generate Alembic migration
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with local dev quickstart"
```

---

### Task 28: Finalise + PR

- [ ] **Step 1: Verify everything passes**

```bash
just test && just typecheck && just lint && echo "ALL GREEN"
```
Expected: `ALL GREEN`.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/cryptobot-strategy-architecture
```

- [ ] **Step 3: Open PR via `/pr-summary`** (per using-dev-toolkit "PR / release flow" rule)

Run the bare-word shortcut:
```
pr-summary
```

It will analyse the commits, classify them, bump VERSION if applicable (likely PATCH since this is a chore/feat-heavy phase but no public API yet), update CHANGELOG, push with `--follow-tags`, and open the PR. Approve the proposed title + body when prompted.

---

## Self-review checklist (performed)

**1. Spec coverage**

| Research doc requirement | Task implementing it |
|---|---|
| Repo structure (Round 6) | Tasks 1, 2, 4, 5, 6, 7 |
| Postgres + Alembic + SQLAlchemy 2.x async | Tasks 2, 4, 9, 10, 11 |
| FastAPI + Pydantic v2 | Tasks 3, 16, 19 |
| Constraint #1 (no hardcoded values) | Task 5 (AST lint), Task 24 (cross-check) |
| Constraint #2 (same profile drives backtest+live) | Task 22 (Strategy Protocol — `evaluate(state, params)`) |
| Constraint #3 (leak-gap prevention) | Tasks 14, 15 (ProfileParams + apply mechanism) |
| Constraint #4 (UI tunability) — partial | Task 19 (API endpoints; UI in later plan) |
| Constraint #5 (decision audit) | Deferred to Phase 3+ (trade_decisions table) |
| Constraint #6 (CI lints enforce above) | Tasks 5, 7, 23, 24, 26 |
| Three typed registry dicts (Round 4) | Task 12 |
| ~40 initial registry keys (Round 6) | Task 12 |
| balanced_v1 fixture (Round 6) | Task 20 |
| Strategy Protocol | Task 22 |
| Multi-service Docker Compose | Task 2 (postgres + api), worker / strategy / frontend in later plans per scope |

**2. Placeholder scan:** scanned for "TODO", "implement later", "similar to Task N", "TBD", "fill in" — none present in committed plan content.

**3. Type consistency:** every Pydantic schema referenced is defined in `app.schemas.strategy_profile`. `ProfileParams`, `apply_profile`, `get_active_profile_config`, `Strategy`, `MarketState`, `Action`, `ActionType` are consistently named across tasks. Repository + service method signatures match between definition (Tasks 17–18) and usage (Task 19).

---

## What's deferred to subsequent plans

The research doc lays out Phases 3–20+. Each gets its own plan when we reach its DoD gate:

- **Phase 3 plan** (data pipeline): Binance Vision + Bybit public + HL archive downloaders → Parquet → DuckDB; symbol manifest snapshots; data-health crons.
- **Phase 4 plan** (backtester): event-driven engine, fee model per exchange, funding accrual, survivorship-safe universe replay.
- **Phase 5 plan** (exchange adapters): unified `ExchangeAdapter` Protocol; CCXT-backed Binance + Bybit; HL SDK adapter; idempotent OMS; reconciliation cron.
- **Phase 6 plan** (Strategy A): `funding_arb.py` implementation; Freqtrade strategy class bridge; AST lint enforced on the real strategy.
- **Phase 7–9 plans** (testnet → dry-run → live $500 for Strategy A).
- **Phase 10–13 plan** (scale A, add pairs).
- **Phase 14–17 plans** (Strategy B: scoring engine fork from stockbot; component scorers; paper → live).
- **Phase 18+ plans** (meta-allocator; UI build; monitoring; capital scaling).

Each subsequent plan should follow the same shape: Goal → Architecture → Tech Stack → Scope → DoD gate → bite-sized TDD tasks → self-review.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-cryptobot-strategy-architecture.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a plan this size (28 tasks).

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`. Batch execution with checkpoints for review.

**Which approach?**
