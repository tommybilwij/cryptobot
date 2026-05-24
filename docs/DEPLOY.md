# Cryptobot Deploy Runbook

Production deploy of cryptobot. Targets: bare-metal Python + Postgres OR Docker Compose.

## Prerequisites

- Linux host (Ubuntu 22.04+ or Debian 12+)
- Python 3.12 (via uv: https://docs.astral.sh/uv/)
- Postgres 16+
- Static IP for API-key whitelisting

## Env vars (REQUIRED before live trading)

```bash
# Exchange API keys (set only the venues you trade on)
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...
export HYPERLIQUID_WALLET_PRIVATE_KEY=0x...

# Optional: per-strategy sub-account keys (Phase 13)
export BINANCE_API_KEY_FUNDING_ARB=...
export BINANCE_API_SECRET_FUNDING_ARB=...

# Anthropic for LLM overlay (optional — empty disables)
export ANTHROPIC_API_KEY=sk-ant-...

# Database
export DATABASE_URL=postgresql+asyncpg://cryptobot:STRONGPASS@localhost:5432/cryptobot
export DATABASE_URL_SYNC=postgresql+psycopg://cryptobot:STRONGPASS@localhost:5432/cryptobot
```

## Bare-metal install

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker Compose

```bash
just up        # postgres + api + worker + 2 strategy-runner heartbeats
just mig-up    # apply migrations

# Start the live runner (paper mode by default)
docker compose --profile live up -d worker-live-trade
```

## Backups

Postgres dump every 6h to S3 / object storage:

```bash
# crontab -e
0 */6 * * * pg_dump cryptobot | gzip | aws s3 cp - s3://your-bucket/cryptobot-$(date +\%F-\%H).sql.gz
```

## Log aggregation

`app.main` calls `setup_logging()` which emits structured JSON on stdout. Pipe to your log aggregator of choice:

- **Docker → Loki/Promtail** — tail container stdout
- **systemd → journald → Loki** — `journalctl -u cryptobot.service -f`
- **CloudWatch** — Docker `awslogs` driver

## Monitoring

`GET /api/v1/metrics` returns Prometheus format. Scrape every 30s:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: cryptobot
    scrape_interval: 30s
    metrics_path: /api/v1/metrics
    static_configs:
      - targets: ["cryptobot:8000"]
```

Halt-class events also fire via webhook (`alerts.webhook_url` in active profile).

## Rollback procedure

1. `POST /api/v1/oms/kill` → halts dispatches
2. `POST /api/v1/live/stop` → exits runner loop
3. `docker compose --profile live stop worker-live-trade`
4. If urgent funds extraction needed: log into venue web UI and close positions manually

## v1.0.0 — feature complete

After this release, focus shifts to operational tuning rather than new feature code. Subsequent versions are bug fixes + parameter tweaks.
