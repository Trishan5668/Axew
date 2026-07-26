"""Unit tests for the Razorpay payment routes.

Coverage:
  - test_create_order: valid JWT + plan_id -> order created, payment row inserted.
  - test_webhook_signature_rejection: invalid HMAC -> 400, no credits applied.
  - test_idempotent_webhook: same payload twice -> credits applied exactly once.
  - test_unknown_plan_id: unknown plan -> 400.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def patched_razorpay(monkeypatch):
    """Patch razorpay.Client so .order.create returns a fake order."""
    from routers import payments as payments_mod

    fake_order = {"id": "order_test_abc", "amount": 199900, "currency": "INR"}

    fake_client = MagicMock()
    fake_client.order.create.return_value = fake_order

    monkeypatch.setattr(payments_mod, "_razorpay_client", lambda: fake_client)
    return fake_client, fake_order


def test_create_order_inserts_payment_row(
    client: TestClient, make_user, make_jwt, fake_supabase, patched_razorpay
) -> None:
    fake_client, fake_order = patched_razorpay
    user_id = make_user(credits=10.0)
    token = make_jwt(user_id)

    resp = client.post(
        "/payments/create-order",
        json={"plan_id": "starter"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["order_id"] == "order_test_abc"
    assert body["amount"] == 199900
    assert body["currency"] == "INR"
    assert body["credits_purchased"] == 100
    assert body["plan_label"] == "Starter"

    rows = fake_supabase.table("payments").rows
    assert len(rows) == 1
    assert rows[0]["razorpay_order_id"] == "order_test_abc"
    assert rows[0]["status"] == "created"
    assert str(rows[0]["user_id"]) == user_id
    fake_client.order.create.assert_called_once()


def test_unknown_plan_id_rejected(
    client: TestClient, make_user, make_jwt, patched_razorpay
) -> None:
    user_id = make_user()
    token = make_jwt(user_id)
    resp = client.post(
        "/payments/create-order",
        json={"plan_id": "enterprise"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # pydantic Literal rejects unknown values before reaching the handler.
    assert resp.status_code == 422


def test_webhook_signature_rejection_no_credit_applied(
    client: TestClient, make_user, fake_supabase, patched_razorpay
) -> None:
    user_id = make_user(credits=10.0)
    # Pre-seed a payment row so the request actually has something to credit.
    fake_supabase.table("payments").rows.append({
        "id": "payment-1",
        "user_id": user_id,
        "razorpay_order_id": "order_x",
        "plan_id": "starter",
        "amount_inr": 199900,
        "credits_purchased": 100,
        "status": "created",
    })

    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "order_id": "order_x", "id": "pay_x",
            "amount": 199900, "currency": "INR",
        }}},
    }).encode()

    resp = client.post(
        "/payments/webhook",
        content=body,
        headers={
            "X-Razorpay-Signature": "definitely-not-the-right-signature",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    # Credits unchanged
    assert fake_supabase.profiles[user_id]["credit_balance"] == 10.0


def test_idempotent_webhook_credits_exactly_once(
    client: TestClient, make_user, fake_supabase, patched_razorpay, monkeypatch
) -> None:
    # Override env so we sign with the same value the route validates against.
    secret = "rzp_test_webhook_secret"
    user_id = make_user(credits=10.0)

    fake_supabase.table("payments").rows.append({
        "id": "payment-1",
        "user_id": user_id,
        "razorpay_order_id": "order_x",
        "plan_id": "starter",
        "amount_inr": 199900,
        "credits_purchased": 100,
        "status": "created",
    })

    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "order_id": "order_x", "id": "pay_x",
            "amount": 199900, "currency": "INR",
        }}},
    }).encode()
    sig = _sign(secret, body)

    headers = {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}

    resp1 = client.post("/payments/webhook", content=body, headers=headers)
    assert resp1.status_code == 200, resp1.text
    assert fake_supabase.profiles[user_id]["credit_balance"] == 110.0

    resp2 = client.post("/payments/webhook", content=body, headers=headers)
    assert resp2.status_code == 200, resp2.text
    # No double-credit
    assert fake_supabase.profiles[user_id]["credit_balance"] == 110.0
    assert resp2.json()["note"] in {"already paid", "no-op (already paid)"}


def test_webhook_ignores_non_captured_events(
    client: TestClient, fake_supabase, patched_razorpay
) -> None:
    secret = "rzp_test_webhook_secret"
    body = json.dumps({"event": "subscription.activated", "payload": {}}).encode()
    sig = _sign(secret, body)
    resp = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert "ignored" in (resp.json().get("note") or "").lower()


def test_plans_endpoint_is_public(client: TestClient) -> None:
    resp = client.get("/payments/plans")
    assert resp.status_code == 200
    body = resp.json()
    ids = [p["id"] for p in body["plans"]]
    assert ids == ["starter", "creator", "pro"]


# ---------------------------------------------------------------------------
# Amount + currency mismatch validation (security-critical)
# ---------------------------------------------------------------------------


def test_webhook_amount_mismatch_rejected(
    client: TestClient, make_user, fake_supabase, patched_razorpay
) -> None:
    secret = "rzp_test_webhook_secret"
    user_id = make_user(credits=10.0)
    fake_supabase.table("payments").rows.append({
        "id": "payment-1", "user_id": user_id,
        "razorpay_order_id": "order_x", "plan_id": "starter",
        "amount_inr": 199900, "credits_purchased": 100, "status": "created",
    })

    # Razorpay reports a much smaller amount than the order — this is the
    # exact attack vector amount-validation prevents.
    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "order_id": "order_x", "id": "pay_x",
            "amount": 100, "currency": "INR",
        }}},
    }).encode()
    sig = _sign(secret, body)

    resp = client.post("/payments/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "Content-Type": "application/json",
    })
    assert resp.status_code == 400
    assert "amount mismatch" in resp.json()["detail"].lower()
    # Balance unchanged
    assert fake_supabase.profiles[user_id]["credit_balance"] == 10.0
    # Payment marked failed for audit trail
    payment_row = fake_supabase.table("payments").rows[0]
    assert payment_row["status"] == "failed"
    assert "amount mismatch" in payment_row["failure_reason"].lower()


def test_webhook_currency_mismatch_rejected(
    client: TestClient, make_user, fake_supabase, patched_razorpay
) -> None:
    secret = "rzp_test_webhook_secret"
    user_id = make_user(credits=10.0)
    fake_supabase.table("payments").rows.append({
        "id": "payment-1", "user_id": user_id,
        "razorpay_order_id": "order_x", "plan_id": "starter",
        "amount_inr": 199900, "credits_purchased": 100, "status": "created",
    })

    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "order_id": "order_x", "id": "pay_x",
            "amount": 199900, "currency": "USD",
        }}},
    }).encode()
    sig = _sign(secret, body)

    resp = client.post("/payments/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "Content-Type": "application/json",
    })
    assert resp.status_code == 400
    assert "currency mismatch" in resp.json()["detail"].lower()
    assert fake_supabase.profiles[user_id]["credit_balance"] == 10.0


# ---------------------------------------------------------------------------
# payment.failed handling
# ---------------------------------------------------------------------------


def test_webhook_payment_failed_marks_row_failed(
    client: TestClient, make_user, fake_supabase, patched_razorpay
) -> None:
    secret = "rzp_test_webhook_secret"
    user_id = make_user(credits=10.0)
    fake_supabase.table("payments").rows.append({
        "id": "payment-1", "user_id": user_id,
        "razorpay_order_id": "order_x", "plan_id": "starter",
        "amount_inr": 199900, "credits_purchased": 100, "status": "created",
    })

    body = json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "order_id": "order_x", "id": "pay_x",
            "error_description": "Card declined",
        }}},
    }).encode()
    sig = _sign(secret, body)

    resp = client.post("/payments/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "Content-Type": "application/json",
    })
    assert resp.status_code == 200
    payment_row = fake_supabase.table("payments").rows[0]
    assert payment_row["status"] == "failed"
    assert payment_row["failure_reason"] == "Card declined"
    # Credits not touched
    assert fake_supabase.profiles[user_id]["credit_balance"] == 10.0


def test_webhook_payment_failed_after_capture_is_noop(
    client: TestClient, make_user, fake_supabase, patched_razorpay
) -> None:
    """Razorpay can deliver payment.failed AFTER payment.captured on a retry.
    We must never downgrade a paid order back to 'failed'."""
    secret = "rzp_test_webhook_secret"
    user_id = make_user(credits=10.0)
    fake_supabase.table("payments").rows.append({
        "id": "payment-1", "user_id": user_id,
        "razorpay_order_id": "order_x", "plan_id": "starter",
        "amount_inr": 199900, "credits_purchased": 100, "status": "paid",
    })

    body = json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "order_id": "order_x", "id": "pay_x",
            "error_description": "Whatever",
        }}},
    }).encode()
    sig = _sign(secret, body)

    resp = client.post("/payments/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "Content-Type": "application/json",
    })
    assert resp.status_code == 200
    payment_row = fake_supabase.table("payments").rows[0]
    assert payment_row["status"] == "paid"


# ---------------------------------------------------------------------------
# Refund handling
# ---------------------------------------------------------------------------


def test_webhook_refund_subtracts_credits(
    client: TestClient, make_user, fake_supabase, patched_razorpay
) -> None:
    secret = "rzp_test_webhook_secret"
    user_id = make_user(credits=110.0)  # 10 free + 100 from starter
    fake_supabase.table("payments").rows.append({
        "id": "payment-1", "user_id": user_id,
        "razorpay_order_id": "order_x",
        "razorpay_payment_id": "pay_x",
        "plan_id": "starter", "amount_inr": 199900,
        "credits_purchased": 100, "status": "paid",
    })

    body = json.dumps({
        "event": "refund.processed",
        "payload": {"refund": {"entity": {
            "payment_id": "pay_x",
            "amount": 199900, "currency": "INR",
        }}},
    }).encode()
    sig = _sign(secret, body)

    resp = client.post("/payments/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "Content-Type": "application/json",
    })
    assert resp.status_code == 200
    payment_row = fake_supabase.table("payments").rows[0]
    assert payment_row["status"] == "refunded"
    # 110 - 100 = 10 (back to free-tier baseline)
    assert fake_supabase.profiles[user_id]["credit_balance"] == 10.0


def test_webhook_refund_unknown_payment_id_is_noop(
    client: TestClient, fake_supabase, patched_razorpay
) -> None:
    secret = "rzp_test_webhook_secret"
    body = json.dumps({
        "event": "refund.created",
        "payload": {"refund": {"entity": {"payment_id": "pay_ghost"}}},
    }).encode()
    sig = _sign(secret, body)
    resp = client.post("/payments/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "Content-Type": "application/json",
    })
    assert resp.status_code == 200
    assert "unknown" in resp.json()["note"].lower()


# ---------------------------------------------------------------------------
# Payment status reconciliation
# ---------------------------------------------------------------------------


def test_payment_status_returns_current_state(
    client: TestClient, make_user, make_jwt, fake_supabase
) -> None:
    user_id = make_user(credits=10.0)
    token = make_jwt(user_id)
    fake_supabase.table("payments").rows.append({
        "id": "payment-1", "user_id": user_id,
        "razorpay_order_id": "order_x",
        "razorpay_payment_id": "pay_x",
        "plan_id": "creator", "amount_inr": 499900,
        "credits_purchased": 300, "status": "paid",
        "paid_at": "2026-06-23T12:00:00Z",
        "failure_reason": None,
    })

    resp = client.get("/payments/payment-1/status",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_id"] == "payment-1"
    assert body["status"] == "paid"
    assert body["plan_id"] == "creator"
    assert body["credits_purchased"] == 300
    assert body["amount_paise"] == 499900


def test_payment_status_cross_user_returns_404(
    client: TestClient, make_user, make_jwt, fake_supabase
) -> None:
    """A user looking up another user's payment must get 404, never 403 —
    the existence of the payment is itself information we don't leak."""
    actor = make_user(credits=10.0)
    victim = make_user(credits=10.0)
    token = make_jwt(actor)
    fake_supabase.table("payments").rows.append({
        "id": "payment-victim", "user_id": victim,
        "razorpay_order_id": "order_v",
        "plan_id": "starter", "amount_inr": 199900,
        "credits_purchased": 100, "status": "paid",
    })

    resp = client.get("/payments/payment-victim/status",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_payment_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/payments/some-id/status")
    assert resp.status_code == 401
