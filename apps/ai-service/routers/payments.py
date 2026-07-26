"""Razorpay payment routes: order creation + idempotent webhook delivery.

Endpoints:
  POST /payments/create-order  -> auth-required, creates Razorpay order
  POST /payments/webhook       -> verifies HMAC, applies credits atomically

The credit-application RPC (apply_payment_credits) is itself idempotent —
replaying the same webhook payload twice cannot double-credit.

Verification-pending: against a live Razorpay test account + tunneled
webhook (ngrok/cloudflared). Tests use razorpay's own utility helpers to
forge signatures and assert acceptance vs rejection.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

try:
    import razorpay
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "razorpay is required for cloud-mode billing. "
        "Install with: pip install razorpay"
    ) from exc

from middleware.auth import CurrentUser
from middleware.cloud_config import (
    PLAN_CATALOG,
    CloudConfigError,
    cloud_settings,
)
from middleware.supabase_client import rpc, supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

PlanId = Literal["starter", "creator", "pro"]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    plan_id: PlanId


class CreateOrderResponse(BaseModel):
    order_id: str
    payment_id: str  # AXEW internal payment row id
    amount: int = Field(description="Amount in paise")
    currency: str = "INR"
    key_id: str
    plan_label: str
    credits_purchased: int


class WebhookAck(BaseModel):
    ok: bool
    note: str | None = None


# ---------------------------------------------------------------------------
# Razorpay client
# ---------------------------------------------------------------------------


def _razorpay_client() -> razorpay.Client:
    settings = cloud_settings()
    settings.require_razorpay()
    client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    return client


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------


@router.post("/create-order", response_model=CreateOrderResponse)
def create_order(body: CreateOrderRequest, current_user: CurrentUser) -> CreateOrderResponse:
    try:
        settings = cloud_settings()
        settings.require_razorpay()
        settings.require_supabase()
    except CloudConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    plan = PLAN_CATALOG.get(body.plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown plan: {body.plan_id}",
        )

    amount_paise = int(plan["amount_paise"])
    credits_purchased = int(plan["credits"])

    rzp = _razorpay_client()
    try:
        order = rzp.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "axew_user_id": str(current_user.user_id),
                "axew_plan_id": body.plan_id,
            },
        })
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Razorpay rejected the order request: {exc}",
        ) from exc

    order_id = order.get("id")
    if not order_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay did not return an order id.",
        )

    # Persist the payment intent in our ledger. status='created' until webhook.
    supabase = supabase_admin()
    try:
        insert = supabase.table("payments").insert({
            "user_id": str(current_user.user_id),
            "razorpay_order_id": order_id,
            "plan_id": body.plan_id,
            "amount_inr": amount_paise,
            "credits_purchased": credits_purchased,
            "status": "created",
        }).execute()
    except Exception as exc:
        logger.exception("Failed to persist payment row for order %s", order_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not record your order. Please try again.",
        ) from exc

    payment_row = (insert.data or [{}])[0]
    payment_id = payment_row.get("id")
    if not payment_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order recorded but no row id returned. Contact support.",
        )

    return CreateOrderResponse(
        order_id=order_id,
        payment_id=str(payment_id),
        amount=amount_paise,
        currency="INR",
        key_id=settings.razorpay_key_id,
        plan_label=str(plan["label"]),
        credits_purchased=credits_purchased,
    )


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 verification per Razorpay's documented webhook protocol.

    Returns True iff the signature matches. NEVER short-circuit this check.
    """
    if not signature or not secret:
        return False
    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Per-event webhook handlers. Kept as small functions so individual events
# can be unit-tested in isolation.
# ---------------------------------------------------------------------------


def _lookup_payment_by_order(order_id: str) -> dict[str, Any] | None:
    """Return the (single) AXEW payment row for the given Razorpay order id."""
    supabase = supabase_admin()
    lookup = (
        supabase.table("payments")
        .select("id, status, credits_purchased, amount_inr, user_id, plan_id")
        .eq("razorpay_order_id", order_id)
        .limit(1)
        .execute()
    )
    rows = lookup.data or []
    return rows[0] if rows else None


def _lookup_payment_by_razorpay_payment_id(razorpay_payment_id: str) -> dict[str, Any] | None:
    """Find an AXEW payment row by the gateway's payment id (used for refunds)."""
    supabase = supabase_admin()
    lookup = (
        supabase.table("payments")
        .select("id, status, credits_purchased, user_id")
        .eq("razorpay_payment_id", razorpay_payment_id)
        .limit(1)
        .execute()
    )
    rows = lookup.data or []
    return rows[0] if rows else None


def _validate_amount_and_currency(payment_row: dict[str, Any], entity: dict[str, Any]) -> str | None:
    """Return an error string if amount/currency don't match the order we created.

    NEVER credit a payment whose amount or currency disagrees with what we
    set up — that would let a bad actor (or a Razorpay misconfiguration)
    purchase the Pro plan for ₹1.
    """
    expected_amount = int(payment_row.get("amount_inr", 0))
    actual_amount = int(entity.get("amount", 0))
    if expected_amount != actual_amount:
        return (
            f"amount mismatch (expected {expected_amount} paise, got {actual_amount})"
        )

    expected_currency = "INR"
    actual_currency = (entity.get("currency") or "").upper()
    if actual_currency and actual_currency != expected_currency:
        return f"currency mismatch (expected {expected_currency}, got {actual_currency})"
    return None


def _handle_payment_captured(
    entity: dict[str, Any], signature: str
) -> WebhookAck:
    order_id = entity.get("order_id")
    razorpay_payment_id = entity.get("id")
    if not order_id or not razorpay_payment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payment.captured webhook is missing order_id or payment id.",
        )

    payment_row = _lookup_payment_by_order(order_id)
    if not payment_row:
        logger.error("Webhook order_id %s not found in payments table", order_id)
        return WebhookAck(ok=True, note="unknown order_id; ignored")

    mismatch = _validate_amount_and_currency(payment_row, entity)
    if mismatch:
        logger.error(
            "Refusing to credit payment %s due to %s",
            payment_row["id"], mismatch,
        )
        # Mark the payment failed so the user sees a clear status, but
        # ack 200 so Razorpay stops retrying — the issue is structural.
        try:
            rpc(
                "mark_payment_failed",
                {"p_payment_id": payment_row["id"], "p_reason": mismatch},
            )
        except Exception:
            logger.exception("Failed to mark payment %s as failed", payment_row["id"])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook rejected: {mismatch}",
        )

    if payment_row.get("status") == "paid":
        return WebhookAck(ok=True, note="already paid")

    apply = rpc(
        "apply_payment_credits",
        {
            "p_payment_id": payment_row["id"],
            "p_razorpay_payment_id": razorpay_payment_id,
            "p_razorpay_signature": signature,
        },
    )
    applied = bool(apply.data)
    return WebhookAck(ok=True, note="credited" if applied else "no-op (already paid)")


def _handle_payment_failed(entity: dict[str, Any]) -> WebhookAck:
    order_id = entity.get("order_id")
    if not order_id:
        return WebhookAck(ok=True, note="payment.failed without order_id; ignored")
    payment_row = _lookup_payment_by_order(order_id)
    if not payment_row:
        return WebhookAck(ok=True, note="unknown order_id; ignored")
    if payment_row.get("status") == "paid":
        # Razorpay sent payment.failed AFTER a successful capture — likely a
        # late retry. Don't downgrade a paid order.
        return WebhookAck(ok=True, note="payment already captured; failure ignored")
    reason = (
        entity.get("error_description")
        or entity.get("error_reason")
        or entity.get("error_code")
        or "payment failed"
    )
    try:
        rpc("mark_payment_failed", {"p_payment_id": payment_row["id"], "p_reason": reason})
    except Exception:
        logger.exception("Failed to mark payment %s as failed", payment_row["id"])
    return WebhookAck(ok=True, note=f"marked failed: {reason}")


def _handle_refund(entity: dict[str, Any]) -> WebhookAck:
    razorpay_payment_id = entity.get("payment_id")
    if not razorpay_payment_id:
        return WebhookAck(ok=True, note="refund event without payment_id; ignored")

    payment_row = _lookup_payment_by_razorpay_payment_id(razorpay_payment_id)
    if not payment_row:
        return WebhookAck(ok=True, note="unknown payment_id; ignored")
    if payment_row.get("status") != "paid":
        return WebhookAck(ok=True, note=f"payment not in 'paid' state ({payment_row.get('status')}); ignored")

    refund = rpc("refund_payment_credits", {"p_payment_id": payment_row["id"]})
    applied = bool(refund.data)
    return WebhookAck(ok=True, note="refunded" if applied else "no-op (not paid)")


@router.post("/webhook", response_model=WebhookAck)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
) -> WebhookAck:
    try:
        settings = cloud_settings()
        settings.require_razorpay()
        settings.require_supabase()
    except CloudConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    raw_body = await request.body()

    if not x_razorpay_signature or not verify_webhook_signature(
        raw_body, x_razorpay_signature, settings.razorpay_webhook_secret
    ):
        # NOTE: 400, not 401 — Razorpay treats 4xx as do-not-retry signal.
        # See: https://razorpay.com/docs/webhooks/#webhook-retries
        logger.warning("Rejected webhook with invalid or missing signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature.",
        )

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body is not valid JSON.",
        ) from exc

    event = payload.get("event", "")
    logger.info("Received Razorpay webhook event=%s", event)

    if event == "payment.captured":
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        return _handle_payment_captured(entity, x_razorpay_signature)

    if event == "payment.failed":
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        return _handle_payment_failed(entity)

    if event in ("refund.created", "refund.processed"):
        entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        return _handle_refund(entity)

    return WebhookAck(ok=True, note=f"ignored event: {event}")


# ---------------------------------------------------------------------------
# Plan listing — public, used by frontend BillingPage
# ---------------------------------------------------------------------------


class PlanInfo(BaseModel):
    id: PlanId
    label: str
    minutes: int
    credits: int
    amount_paise: int


class PlansResponse(BaseModel):
    plans: list[PlanInfo]
    currency: str = "INR"


@router.get("/plans", response_model=PlansResponse)
def list_plans() -> PlansResponse:
    """Return the plan catalog. Public so the BillingPage works pre-auth."""
    return PlansResponse(
        plans=[
            PlanInfo(
                id=plan_id,  # type: ignore[arg-type]
                label=str(p["label"]),
                minutes=int(p["minutes"]),
                credits=int(p["credits"]),
                amount_paise=int(p["amount_paise"]),
            )
            for plan_id, p in PLAN_CATALOG.items()
        ]
    )


# ---------------------------------------------------------------------------
# Payment status reconciliation
# ---------------------------------------------------------------------------


class PaymentStatusResponse(BaseModel):
    payment_id: str
    razorpay_order_id: str
    razorpay_payment_id: str | None
    plan_id: PlanId
    status: Literal["created", "paid", "failed", "refunded"]
    amount_paise: int
    credits_purchased: int
    paid_at: str | None
    failure_reason: str | None


@router.get("/{payment_id}/status", response_model=PaymentStatusResponse)
def payment_status(payment_id: str, current_user: CurrentUser) -> PaymentStatusResponse:
    """Return the current state of a single payment.

    Used by the BillingPage's post-checkout polling loop. It's racier to ask
    "has my balance gone up?" — if a previous OpusClip job deducted credits
    between the check and the new charge, the balance reading lies. This
    endpoint resolves that by reading the payment row directly.

    Auth required, and the row's user_id must match the caller — users can
    never look up other users' payments.
    """
    try:
        cloud_settings().require_supabase()
    except CloudConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    supabase = supabase_admin()
    resp = (
        supabase.table("payments")
        .select(
            "id, user_id, razorpay_order_id, razorpay_payment_id, plan_id, "
            "amount_inr, credits_purchased, status, paid_at, failure_reason"
        )
        .eq("id", payment_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found.",
        )
    row = rows[0]
    if str(row["user_id"]) != str(current_user.user_id):
        # Treat as 404 — never leak the existence of another user's payment.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found.",
        )

    return PaymentStatusResponse(
        payment_id=str(row["id"]),
        razorpay_order_id=row["razorpay_order_id"],
        razorpay_payment_id=row.get("razorpay_payment_id"),
        plan_id=row["plan_id"],
        status=row["status"],
        amount_paise=int(row["amount_inr"]),
        credits_purchased=int(row["credits_purchased"]),
        paid_at=row.get("paid_at"),
        failure_reason=row.get("failure_reason"),
    )


# Public alias kept for completeness; never used by hot path.
def _redact_secret(value: Any) -> str:
    return "***" if value else ""
