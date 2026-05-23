"""Historical market-data pipeline.

Downloaders implement the `MarketDataSource` protocol from `base.py` and write
into the shared `ParquetStore`. `DuckDBQuery` is the read-side API used by the
backtester (Phase 4) and live feature pipelines (Phase 14).
"""
