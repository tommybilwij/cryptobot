# Cryptobot — common dev commands.
# Run `just` to list available recipes.

set dotenv-load
set positional-arguments

default:
    @just --list

# Bring up local postgres only
up:
    docker compose up -d postgres
    @echo "Waiting for postgres..."
    @until docker compose exec postgres pg_isready -U cryptobot -d cryptobot > /dev/null 2>&1; do sleep 1; done
    @echo "Postgres ready."

# Bring up ALL services (postgres + api + worker + strategy runners)
up-all:
    docker compose up -d --build
    @echo "Waiting for postgres..."
    @until docker compose exec postgres pg_isready -U cryptobot -d cryptobot > /dev/null 2>&1; do sleep 1; done
    @echo "All services started. Run 'docker compose ps' to see status."

# Tear down local services
down:
    docker compose down

# Tail logs from all services (or specify service names)
logs *args:
    docker compose logs -f "$@"

# Run backend tests
test *args:
    cd backend && uv run pytest "$@"

# Run typechecker (mypy strict)
typecheck:
    cd backend && uv run mypy app

# Run all linters
lint:
    cd backend && uv run ruff check app tests
    python3 scripts/lint_no_literals_in_strategies.py

# Apply ruff auto-fixes + formatter
fmt:
    cd backend && uv run ruff check --fix app tests
    cd backend && uv run ruff format app tests

# Run Alembic migration to head
mig-up:
    cd backend && uv run alembic upgrade head

# Generate a new migration via autogenerate
mig-new MESSAGE:
    cd backend && uv run alembic revision --autogenerate -m "{{MESSAGE}}"

# Run the API server in dev (auto-reload)
api:
    cd backend && uv run fastapi dev app/main.py

# Load profile fixtures into the DB
load-fixtures:
    cd backend && uv run python -m scripts.load_fixtures

# Run the refresh_data worker job once (uses the WORKER_JOB env)
refresh-data:
    cd backend && WORKER_JOB=refresh_data uv run python -m app.worker.main

# Run a single backtest by id (uses WORKER_JOB=run_backtest)
backtest BACKTEST_ID:
    cd backend && WORKER_JOB=run_backtest BACKTEST_ID={{BACKTEST_ID}} uv run python -m app.worker.main
