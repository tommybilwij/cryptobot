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
