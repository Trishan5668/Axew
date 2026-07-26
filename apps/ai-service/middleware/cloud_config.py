"""Cloud-feature configuration for AXEW's AI service.

AXEW is local-first by default. Cloud-only routers (auth, payments, OpusClip
post-processing) MUST refuse to register or service requests unless the
operator has explicitly opted in by setting ``AXEW_CLOUD_ENABLED=true`` AND
provided the required secrets via environment variables.

This module is the single source of truth for that gate; every cloud router
should call :func:`require_cloud_enabled` at startup and :func:`cloud_settings`
at runtime. Never read os.environ for these values from anywhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

# ---------------------------------------------------------------------------
# Plan catalog — single source of truth across payments + credit gating.
# Amounts are paise (INR * 100) per Razorpay's API contract.
# ---------------------------------------------------------------------------

PLAN_CATALOG: Final[dict[str, dict[str, object]]] = {
    "starter": {"label": "Starter", "minutes": 100,  "credits": 100,  "amount_paise": 199900},
    "creator": {"label": "Creator", "minutes": 300,  "credits": 300,  "amount_paise": 499900},
    "pro":     {"label": "Pro",     "minutes": 1000, "credits": 1000, "amount_paise": 1499900},
}

FREE_TIER_CREDITS: Final[int] = 10


@dataclass(frozen=True)
class CloudSettings:
    """Validated bundle of cloud-mode environment configuration."""

    enabled: bool
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str
    razorpay_key_id: str
    razorpay_key_secret: str
    razorpay_webhook_secret: str
    opusclip_api_key: str
    opusclip_base_url: str

    def require_supabase(self) -> None:
        if not self.supabase_url or not self.supabase_service_role_key:
            raise CloudConfigError(
                "Supabase is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY in the AI service environment."
            )

    def require_supabase_jwt(self) -> None:
        if not self.supabase_jwt_secret:
            raise CloudConfigError(
                "Supabase JWT verification is not configured. "
                "Set SUPABASE_JWT_SECRET in the AI service environment."
            )

    def require_razorpay(self) -> None:
        if not (self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret):
            raise CloudConfigError(
                "Razorpay is not configured. Set RAZORPAY_KEY_ID, "
                "RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET."
            )

    def require_opusclip(self) -> None:
        if not self.opusclip_api_key:
            raise CloudConfigError(
                "OpusClip is not configured. Set OPUSCLIP_API_KEY in the "
                "AI service environment."
            )


class CloudConfigError(RuntimeError):
    """Raised when a cloud feature is invoked without complete configuration."""


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


@lru_cache(maxsize=1)
def cloud_settings() -> CloudSettings:
    """Return the validated cloud settings. Cached; safe to call repeatedly."""
    enabled_raw = _env("AXEW_CLOUD_ENABLED", "false").lower()
    return CloudSettings(
        enabled=enabled_raw in {"1", "true", "yes", "on"},
        supabase_url=_env("SUPABASE_URL"),
        supabase_service_role_key=_env("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_jwt_secret=_env("SUPABASE_JWT_SECRET"),
        razorpay_key_id=_env("RAZORPAY_KEY_ID"),
        razorpay_key_secret=_env("RAZORPAY_KEY_SECRET"),
        razorpay_webhook_secret=_env("RAZORPAY_WEBHOOK_SECRET"),
        opusclip_api_key=_env("OPUSCLIP_API_KEY"),
        opusclip_base_url=_env("OPUSCLIP_BASE_URL", "https://api.opus.pro"),
    )


def require_cloud_enabled() -> CloudSettings:
    """Return cloud settings, or raise if cloud features are disabled."""
    s = cloud_settings()
    if not s.enabled:
        raise CloudConfigError(
            "AXEW cloud features are disabled. Set AXEW_CLOUD_ENABLED=true "
            "to enable auth, payments and OpusClip integration."
        )
    return s


def reset_cloud_settings_cache() -> None:
    """Test-only helper to clear the LRU cache between configurations."""
    cloud_settings.cache_clear()
