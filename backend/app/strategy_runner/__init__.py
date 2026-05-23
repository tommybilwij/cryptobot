"""Per-strategy runner process.

Phase 1+2: heartbeat stub. In Phase 6+ this hosts a Strategy Protocol
implementation. The Freqtrade-vs-own-asyncio-loop decision is deferred
to Phase 6 when the bridge-layer design is locked in; the container
boundary itself exists from day 1.
"""
