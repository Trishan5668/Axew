"""Shared pytest fixtures for AXEW cloud-mode tests.

These tests run WITHOUT live Supabase / Razorpay / OpusClip accounts:
- supabase_admin() is replaced with an in-memory fake.
- razorpay.Client.order.create is patched per-test.
- httpx calls to OpusClip are mocked via respx.

Verification-pending: end-to-end tests against real services. Run
locally with the env vars in docs/CLOUD_INTEGRATION.md.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

# Make the ai-service package importable without installing it.
_SVC_DIR = Path(__file__).resolve().parents[1]
if str(_SVC_DIR) not in sys.path:
    sys.path.insert(0, str(_SVC_DIR))

JWT_SECRET = "test-secret-do-not-use-in-production-32-chars"


# ---------------------------------------------------------------------------
# Env setup — applied BEFORE any cloud_config import happens.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cloud_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AXEW_CLOUD_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key-test")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key_id")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_key_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_test_webhook_secret")
    monkeypatch.setenv("OPUSCLIP_API_KEY", "sk-test-opusclip-key")
    monkeypatch.setenv("OPUSCLIP_BASE_URL", "https://api.opusclip.test")

    # Clear caches so the new env is picked up
    from middleware import cloud_config, supabase_client

    cloud_config.reset_cloud_settings_cache()
    supabase_client.reset_supabase_client_cache()
    yield
    cloud_config.reset_cloud_settings_cache()
    supabase_client.reset_supabase_client_cache()


# ---------------------------------------------------------------------------
# Fake Supabase client
# ---------------------------------------------------------------------------


class _FakeRPCResponse:
    def __init__(self, data: Any) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, parent: "_FakeTable") -> None:
        self.parent = parent
        self._filters: list[tuple[str, str]] = []
        self._limit: int | None = None
        self._select: str | None = None

    def select(self, columns: str) -> "_FakeQuery":
        self._select = columns
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self._filters.append((column, str(value)))
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def execute(self) -> _FakeRPCResponse:
        rows = list(self.parent.rows)
        for col, val in self._filters:
            rows = [r for r in rows if str(r.get(col)) == val]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _FakeRPCResponse(rows)


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def insert(self, payload: dict[str, Any]) -> "_FakeInsert":
        return _FakeInsert(self, payload)

    def select(self, columns: str) -> _FakeQuery:
        q = _FakeQuery(self)
        return q.select(columns)


class _FakeInsert:
    def __init__(self, table: _FakeTable, payload: dict[str, Any]) -> None:
        self.table = table
        self.payload = payload

    def execute(self) -> _FakeRPCResponse:
        row = dict(self.payload)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("status", "created")
        self.table.rows.append(row)
        return _FakeRPCResponse([row])


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, _FakeTable] = {}
        self.rpc_log: list[tuple[str, dict[str, Any]]] = []
        # Profile balance state for credit RPCs
        self.profiles: dict[str, dict[str, Any]] = {}

    def table(self, name: str) -> _FakeTable:
        return self.tables.setdefault(name, _FakeTable())

    def rpc(self, name: str, params: dict[str, Any]):
        self.rpc_log.append((name, params))

        if name == "get_credit_summary":
            uid = str(params["p_user_id"])
            profile = self.profiles.get(uid, {"credit_balance": 0.0, "total_minutes_processed": 0.0})
            data = [{
                "credit_balance": profile["credit_balance"],
                "total_minutes_processed": profile["total_minutes_processed"],
                "free_tier_minutes": 10,
            }]
            return _Executable(_FakeRPCResponse(data))

        if name == "deduct_credits":
            uid = str(params["p_user_id"])
            mins = float(params["p_minutes"])
            profile = self.profiles.setdefault(uid, {"credit_balance": 0.0, "total_minutes_processed": 0.0})
            if profile["credit_balance"] < mins:
                raise RuntimeError("insufficient_credits")
            profile["credit_balance"] -= mins
            profile["total_minutes_processed"] += mins
            return _Executable(_FakeRPCResponse(profile["credit_balance"]))

        if name == "apply_payment_credits":
            payment_id = str(params["p_payment_id"])
            for row in self.table("payments").rows:
                if str(row["id"]) != payment_id:
                    continue
                if row.get("status") == "paid":
                    return _Executable(_FakeRPCResponse(False))
                row["status"] = "paid"
                row["razorpay_payment_id"] = params["p_razorpay_payment_id"]
                row["razorpay_signature"] = params["p_razorpay_signature"]
                row["paid_at"] = time.time()
                uid = str(row["user_id"])
                profile = self.profiles.setdefault(uid, {"credit_balance": 0.0, "total_minutes_processed": 0.0})
                profile["credit_balance"] += int(row["credits_purchased"])
                return _Executable(_FakeRPCResponse(True))
            raise RuntimeError("payment_not_found")

        if name == "mark_payment_failed":
            payment_id = str(params["p_payment_id"])
            for row in self.table("payments").rows:
                if str(row["id"]) == payment_id and row.get("status") == "created":
                    row["status"] = "failed"
                    row["failure_reason"] = params.get("p_reason")
            return _Executable(_FakeRPCResponse(None))

        if name == "refund_payment_credits":
            payment_id = str(params["p_payment_id"])
            for row in self.table("payments").rows:
                if str(row["id"]) != payment_id:
                    continue
                if row.get("status") != "paid":
                    return _Executable(_FakeRPCResponse(False))
                row["status"] = "refunded"
                uid = str(row["user_id"])
                profile = self.profiles.setdefault(uid, {"credit_balance": 0.0, "total_minutes_processed": 0.0})
                profile["credit_balance"] = max(
                    0.0, profile["credit_balance"] - int(row["credits_purchased"]),
                )
                return _Executable(_FakeRPCResponse(True))
            raise RuntimeError("payment_not_found")

        return _Executable(_FakeRPCResponse(None))


class _Executable:
    """Wraps a response to mimic supabase-py's .execute() chaining."""

    def __init__(self, resp: _FakeRPCResponse) -> None:
        self._resp = resp

    def execute(self) -> _FakeRPCResponse:
        return self._resp


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> FakeSupabase:
    fake = FakeSupabase()
    from middleware import supabase_client

    monkeypatch.setattr(supabase_client, "supabase_admin", lambda: fake)
    monkeypatch.setattr(
        supabase_client,
        "rpc",
        lambda name, params: fake.rpc(name, params).execute(),
    )

    # Routers do `from middleware.supabase_client import rpc, supabase_admin`
    # at module load. Those bindings are captured once and won't update when
    # we monkeypatch supabase_client. If the routers are already in
    # sys.modules from a previous test, patch the bindings on them too.
    for mod_name in ("routers.payments", "routers.opusclip"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        if hasattr(mod, "supabase_admin"):
            monkeypatch.setattr(mod, "supabase_admin", lambda: fake)
        if hasattr(mod, "rpc"):
            monkeypatch.setattr(
                mod, "rpc", lambda name, params: fake.rpc(name, params).execute()
            )
    return fake


# ---------------------------------------------------------------------------
# Auth helper: build a signed JWT the middleware accepts
# ---------------------------------------------------------------------------


@pytest.fixture
def make_jwt():
    from jose import jwt

    def _make(user_id: str, email: str = "user@example.com", expires_in: int = 3600) -> str:
        now = int(time.time())
        claims = {
            "sub": user_id,
            "email": email,
            "role": "authenticated",
            "aud": "authenticated",
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, JWT_SECRET, algorithm="HS256")

    return _make


# ---------------------------------------------------------------------------
# FastAPI TestClient — built after env + fakes are wired
# ---------------------------------------------------------------------------


@pytest.fixture
def client(fake_supabase: FakeSupabase) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    # Force a fresh import of the routers + main so the `from middleware...
    # import supabase_admin, rpc` bindings pick up the freshly-monkeypatched
    # references for THIS test's fake_supabase instance.
    #
    # Deleting from sys.modules isn't enough on its own: Python's package
    # machinery keeps the submodule as an attribute on the parent package,
    # so `from routers import payments` short-circuits the import. We
    # delattr the parent's reference too.
    import routers  # type: ignore[import-not-found]

    for mod_name in ("main", "routers.payments", "routers.opusclip"):
        sys.modules.pop(mod_name, None)
    for sub in ("payments", "opusclip"):
        if hasattr(routers, sub):
            try:
                delattr(routers, sub)
            except AttributeError:
                pass
    import main  # type: ignore[import-not-found]

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def make_user(fake_supabase: FakeSupabase):
    """Create a test profile with a known credit balance."""

    def _make(credits: float = 100.0) -> str:
        user_id = str(uuid.uuid4())
        fake_supabase.profiles[user_id] = {
            "credit_balance": credits,
            "total_minutes_processed": 0.0,
        }
        return user_id

    return _make
