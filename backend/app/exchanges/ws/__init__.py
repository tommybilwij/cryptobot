"""WebSocket client layer.

Implementations satisfy the ``WSClient`` Protocol in ``base.py``. Each adapter
owns one venue's user-data stream quirks (auth, listen-key lifecycle, message
shape); consumers (OMS, LiveStateFetcher) only see the Protocol.

Phase 11 ships the Protocol + ``PaperWSClient`` for tests. Real venue adapters
are stubs; live calibration is opt-in slow-test scope (Phase 11+).
"""
