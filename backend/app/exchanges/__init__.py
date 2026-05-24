"""Exchange adapter layer.

Implementations satisfy the ``Exchange`` Protocol in ``base.py``. Each adapter
owns one venue's quirks (URLs, auth, response shape); the OMS only sees the
Protocol.
"""
