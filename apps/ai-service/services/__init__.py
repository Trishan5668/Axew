"""Internal services backing the AXEW AI-service routers.

Each module here is router-agnostic and side-effect-free at import time —
they read configuration lazily so the unit-test suite can monkeypatch them
without paying the cost of a live HTTP client / DB connection.
"""
