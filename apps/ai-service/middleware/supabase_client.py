"""Server-side Supabase client (service-role key).

Holds a single cached supabase-py client used by payment + OpusClip routers
for RPC calls (apply_payment_credits, deduct_credits, get_credit_summary).

Never expose this module's client to anything that handles untrusted input
directly — the service-role key bypasses RLS.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

try:
    from supabase import Client, create_client
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "supabase-py is required for cloud features. "
        "Install with: pip install supabase"
    ) from exc

from .cloud_config import CloudConfigError, cloud_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def supabase_admin() -> Client:
    """Return a cached Supabase admin client (service-role auth)."""
    settings = cloud_settings()
    settings.require_supabase()
    logger.info("Initializing Supabase admin client at %s", settings.supabase_url)
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def reset_supabase_client_cache() -> None:
    """Test-only helper to clear the cached client between configurations.

    Defensive: pytest fixtures sometimes monkeypatch ``supabase_admin`` to a
    plain lambda, in which case ``cache_clear`` does not exist. Swallow that
    quietly — the patch itself is the cache reset.
    """
    clear = getattr(supabase_admin, "cache_clear", None)
    if callable(clear):
        clear()


def rpc(name: str, params: dict[str, Any]) -> Any:
    """Invoke a Postgres function via the admin client.

    Raises CloudConfigError if cloud is misconfigured; otherwise propagates
    whatever supabase-py raises (callers wrap into HTTPException).
    """
    client = supabase_admin()
    try:
        return client.rpc(name, params).execute()
    except CloudConfigError:
        raise
    except Exception as exc:
        logger.error("Supabase RPC %s failed: %s", name, exc)
        raise
