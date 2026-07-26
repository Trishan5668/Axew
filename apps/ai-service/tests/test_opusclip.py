"""Unit tests for the AXEW <-> OpusClip integration.

Architecture under test:

  POST /opusclip/process       -> 202, returns job_id, kicks off background worker
  GET  /opusclip/status/{id}   -> stage transitions queued -> processing -> completed
  GET  /opusclip/result/{id}   -> normalized clip results, credits deducted exactly once

External calls are mocked with `respx`. The background worker is an
asyncio Task; tests await it via JobStore's stored handle so they are
deterministic without sleeping.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient


_VIDEO_URL = "https://media.axew.test/sample.mp4"
_OPUS_BASE = "https://api.opusclip.test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_response(project_id: str, stage: str = "QUEUED") -> dict[str, Any]:
    """Mimic POST /api/clip-projects (and the subsequent GET) responses."""
    return {
        "id": project_id,
        "projectId": project_id,
        "userId": "google-oauth2|test",
        "orgId": "org_test",
        "stage": stage,
        "model": "ClipBasic",
        "sourcePlatform": "YOUTUBE",
        "sourceId": "yt_test",
        "productTier": "PRO",
    }


def _exportable_clip(
    project_id: str,
    curation_id: str = "CU000001",
    *,
    viral: float | None = None,
    duration_ms: int = 30_000,
    title: str = "Clip Title",
    description: str = "An exciting moment.",
    hashtags: str = "#ax #ew",
    keywords: list[str] | None = None,
    include_export_url: bool = True,
    include_preview_url: bool = True,
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": f"{project_id}.{curation_id}",
        "projectId": project_id,
        "curationId": curation_id,
        "runId": "run-test",
        "orgId": "org_test",
        "userId": "google-oauth2|test",
        "storageUsed": 12345,
        "durationMs": duration_ms,
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "keywords": keywords if keywords is not None else ["axew", "opus"],
        "text": "transcript here",
        "createdAt": "2026-06-23T12:00:00Z",
        "updatedAt": "2026-06-23T12:05:00Z",
        "productTier": "PRO",
        "renderPref": {"enableCaption": True, "enableBroll": True},
    }
    if include_export_url:
        obj["uriForExport"] = f"https://cdn.opus.pro/{project_id}/export.mp4"
    if include_preview_url:
        obj["uriForPreview"] = f"https://cdn.opus.pro/{project_id}/preview.mp4"
    if viral is not None:
        obj["viralityScore"] = viral
    return obj


async def _await_job(job_id: str, timeout: float = 5.0) -> None:
    """Wait for the background worker on a job to finish."""
    from services.opusclip_jobs import get_job_store

    job = get_job_store().get(job_id)
    if job is None or job.background_task is None:
        return
    try:
        await asyncio.wait_for(job.background_task, timeout=timeout)
    except asyncio.TimeoutError:
        pass


def _make_async_client():
    """Build an httpx.AsyncClient bound to the FastAPI app in the CURRENT
    event loop. We need this for tests that have to await the background
    `asyncio.create_task` produced inside POST /opusclip/process — the
    synchronous TestClient pins each request to its own portal loop,
    leaving the background task orphaned to the test's loop.
    """
    import sys as _sys
    main_mod = _sys.modules["main"]
    transport = httpx.ASGITransport(app=main_mod.app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture(autouse=True)
def _short_poll_interval(client, monkeypatch):
    """Slash the worker's poll interval so tests don't sit at 15s/tick.

    Depends on the `client` fixture so the monkeypatch is applied AFTER
    conftest reloads the `routers.opusclip` module; otherwise the patch
    lands on a stale module reference.
    """
    import sys as _sys
    router_mod = _sys.modules["routers.opusclip"]
    monkeypatch.setattr(router_mod, "_WORKER_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(router_mod, "_WORKER_MAX_RUNTIME_S", 5.0)


@pytest.fixture(autouse=True)
def _reset_job_store():
    from services.opusclip_jobs import reset_job_store_for_tests
    reset_job_store_for_tests()
    yield
    reset_job_store_for_tests()


# ===========================================================================
# Unit tests: opusclip_client defensive parsing
# ===========================================================================


def test_parse_project_id_handles_documented_and_nested_shapes() -> None:
    from services.opusclip_client import parse_project_id

    assert parse_project_id({"projectId": "P_abc"}) == "P_abc"
    assert parse_project_id({"id": "P_xyz", "projectId": "P_xyz"}) == "P_xyz"
    assert parse_project_id({"data": {"projectId": "P_nested"}}) == "P_nested"
    assert parse_project_id({"project_id": "P_snake"}) == "P_snake"
    assert parse_project_id({}) is None
    assert parse_project_id(None) is None
    assert parse_project_id("not-a-dict") is None  # type: ignore[arg-type]


def test_parse_project_stage_handles_aliases() -> None:
    from services.opusclip_client import parse_project_stage

    assert parse_project_stage({"stage": "QUEUED"}) == "QUEUED"
    assert parse_project_stage({"status": "RUNNING"}) == "RUNNING"
    assert parse_project_stage({"data": {"stage": "COMPLETE"}}) == "COMPLETE"
    assert parse_project_stage({}) is None


def test_parse_exportable_clips_normalizes_units_and_finds_urls() -> None:
    from services.opusclip_client import parse_exportable_clips
    from models.opusclip import ClipRange

    source = ClipRange(start_seconds=10.0, end_seconds=70.0)
    raw = [
        _exportable_clip("P_a", "CU1", duration_ms=45_000, viral=87.5),
        # Wrapped shape returned by some intermediaries
    ]
    results = parse_exportable_clips(raw, source)
    assert len(results) == 1
    r = results[0]
    assert r.duration_seconds == 45.0
    assert str(r.clip_url).endswith("/export.mp4")
    assert r.viral_score == 87.5
    assert r.keywords == ["axew", "opus"]
    assert r.title == "Clip Title"
    assert r.opusclip_id == "P_a.CU1"
    assert r.source_range == source


def test_parse_exportable_clips_skips_malformed_entries() -> None:
    """Defensive parsing: one bad clip must not break the batch."""
    from services.opusclip_client import parse_exportable_clips
    from models.opusclip import ClipRange

    source = ClipRange(start_seconds=0.0, end_seconds=10.0)
    raw = [
        # missing all URLs -> skipped
        {"id": "broken", "projectId": "P_x", "durationMs": 1000},
        # good one -> kept
        _exportable_clip("P_y"),
        # not a dict -> skipped silently
        "garbage",
    ]
    results = parse_exportable_clips(raw, source)
    assert len(results) == 1
    assert results[0].project_id == "P_y"


def test_parse_exportable_clips_handles_wrapped_response() -> None:
    """OpusClip's documented shape is a top-level array. Some gateways
    wrap it in {data: [...]}. Both must work."""
    from services.opusclip_client import parse_exportable_clips
    from models.opusclip import ClipRange

    source = ClipRange(start_seconds=0.0, end_seconds=10.0)
    raw = {"data": [_exportable_clip("P_w")]}
    results = parse_exportable_clips(raw, source)
    assert len(results) == 1


def test_parse_exportable_clips_viral_score_missing_is_none() -> None:
    """The documented public API doesn't include viralityScore — must
    not crash, must surface None."""
    from services.opusclip_client import parse_exportable_clips
    from models.opusclip import ClipRange

    source = ClipRange(start_seconds=0.0, end_seconds=10.0)
    results = parse_exportable_clips([_exportable_clip("P_a", viral=None)], source)
    assert results[0].viral_score is None


def test_parse_exportable_clips_prefers_export_falls_back_to_preview() -> None:
    from services.opusclip_client import parse_exportable_clips
    from models.opusclip import ClipRange

    source = ClipRange(start_seconds=0.0, end_seconds=10.0)
    # Only preview URL present
    raw = [_exportable_clip("P_p", include_export_url=False, include_preview_url=True)]
    results = parse_exportable_clips(raw, source)
    assert "preview.mp4" in str(results[0].clip_url)


def test_build_create_project_payload_clipbasic_passes_keywords() -> None:
    from services.opusclip_client import build_create_project_payload
    from models.opusclip import ClipRange, OpusClipRequest

    req = OpusClipRequest(
        video_url="https://x.test/v.mp4",
        user_id=uuid.uuid4(),
        clips=[ClipRange(start_seconds=10, end_seconds=70)],
        curation_model="ClipBasic",
        topic_keywords=["finance", "ai"],
    )
    payload = build_create_project_payload(req, req.clips[0])
    assert payload["videoUrl"] == "https://x.test/v.mp4"
    assert payload["curationPref"]["model"] == "ClipBasic"
    assert payload["curationPref"]["topicKeywords"] == ["finance", "ai"]
    assert payload["curationPref"]["range"] == {"startSec": 10.0, "endSec": 70.0}
    assert payload["renderPref"]["quickstartConfig"]["enableRemoveFillerWords"] is True
    assert payload["renderPref"]["enableCaption"] is True


def test_build_create_project_payload_clipanything_uses_prompt() -> None:
    from services.opusclip_client import build_create_project_payload
    from models.opusclip import ClipRange, OpusClipRequest

    req = OpusClipRequest(
        video_url="https://x.test/v.mp4",
        user_id=uuid.uuid4(),
        clips=[ClipRange(start_seconds=0, end_seconds=10)],
        curation_model="ClipAnything",
        custom_prompt="Find the funniest moments",
        topic_keywords=["ignored"],  # ClipAnything ignores this — verify
    )
    payload = build_create_project_payload(req, req.clips[0])
    assert payload["curationPref"]["model"] == "ClipAnything"
    assert payload["curationPref"]["customPrompt"] == "Find the funniest moments"
    assert "topicKeywords" not in payload["curationPref"]


# ===========================================================================
# Endpoint tests
# ===========================================================================


@respx.mock
@pytest.mark.asyncio
async def test_happy_path_submit_poll_result(
    client: TestClient, make_user, make_jwt
) -> None:
    # NOTE: `client` is included in the signature only to trigger the
    # fixture chain (env vars + supabase fake + main module reload). The
    # actual HTTP traffic in this test uses an in-loop async client so we
    # can await the background asyncio.Task the route creates.
    user_id = make_user(credits=100.0)
    token = make_jwt(user_id)

    # 1. Mock OpusClip's POST /api/clip-projects
    captured_payloads: list[dict[str, Any]] = []

    def _create(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        pid = f"P_{len(captured_payloads):04d}"
        return httpx.Response(200, json=_project_response(pid, stage="QUEUED"))

    respx.post(f"{_OPUS_BASE}/api/clip-projects").mock(side_effect=_create)

    # 2. Mock GET /api/clip-projects/{id} — first call PENDING, second COMPLETE
    status_calls: dict[str, int] = {}

    def _status(request: httpx.Request) -> httpx.Response:
        pid = request.url.path.rsplit("/", 1)[-1]
        status_calls[pid] = status_calls.get(pid, 0) + 1
        stage = "COMPLETE" if status_calls[pid] >= 2 else "RENDER"
        return httpx.Response(200, json=_project_response(pid, stage=stage))

    respx.get(url__regex=rf"^{_OPUS_BASE}/api/clip-projects/P_\d+$").mock(side_effect=_status)

    # 3. Mock GET /api/exportable-clips
    def _clips(request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        pid = params["projectId"][0]
        return httpx.Response(200, json=[
            _exportable_clip(pid, "CU01", viral=82.0),
            _exportable_clip(pid, "CU02", viral=66.0),
        ])

    respx.get(f"{_OPUS_BASE}/api/exportable-clips").mock(side_effect=_clips)

    auth_headers = {"Authorization": f"Bearer {token}"}
    body = {
        "video_url": _VIDEO_URL,
        "user_id": user_id,
        "clips": [
            {"start_seconds": 0.0, "end_seconds": 60.0, "label": "intro"},
            {"start_seconds": 120.0, "end_seconds": 180.0, "label": "punchline"},
        ],
        "topic_keywords": ["axew"],
    }

    async with _make_async_client() as ac:
        # 4. Submit
        submit = await ac.post("/opusclip/process", json=body, headers=auth_headers)
        assert submit.status_code == 202, submit.text
        accepted = submit.json()
        job_id = accepted["job_id"]
        assert accepted["stage"] == "queued"
        assert accepted["minutes_required"] == 2.0  # 120s / 60
        assert accepted["credits_balance_before"] == 100.0
        assert f"/opusclip/status/{job_id}" in accepted["poll_status_url"]
        assert f"/opusclip/result/{job_id}" in accepted["poll_result_url"]

        # 5. Drive the worker to completion (deterministically)
        await _await_job(job_id, timeout=5.0)

        # 6. Status now reports completed
        status_resp = await ac.get(f"/opusclip/status/{job_id}", headers=auth_headers)
        assert status_resp.status_code == 200
        sjson = status_resp.json()
        assert sjson["stage"] == "completed"
        assert len(sjson["projects"]) == 2
        assert all(p["stage"] == "COMPLETE" for p in sjson["projects"])

        # 7. Result endpoint returns normalized clips + deducted balance
        result_resp = await ac.get(f"/opusclip/result/{job_id}", headers=auth_headers)
        assert result_resp.status_code == 200, result_resp.text
        rjson = result_resp.json()
        assert rjson["stage"] == "completed"
        assert rjson["minutes_processed"] == 2.0
        assert rjson["credits_remaining"] == 98.0  # 100 - 2
        assert len(rjson["results"]) == 4  # 2 projects * 2 clips
        first = rjson["results"][0]
        assert "uriForExport" not in first  # normalized away
        assert first["clip_url"].endswith("export.mp4")
        assert first["duration_seconds"] == 30.0  # 30_000 ms -> 30 s
        assert first["viral_score"] == 82.0

    # 8. Verify the OpusClip request payloads carried our settings
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["videoUrl"] == _VIDEO_URL
    assert captured_payloads[0]["curationPref"]["range"]["startSec"] == 0.0
    assert captured_payloads[0]["renderPref"]["quickstartConfig"]["enableRemoveFillerWords"] is True


def test_insufficient_credits_returns_402_and_never_calls_opusclip(
    client: TestClient, make_user, make_jwt
) -> None:
    user_id = make_user(credits=0.5)  # less than 1 minute
    token = make_jwt(user_id)

    with respx.mock(assert_all_called=False) as router:
        opusclip_call = router.post(f"{_OPUS_BASE}/api/clip-projects").mock(
            return_value=httpx.Response(200, json={"projectId": "should-not-happen"}),
        )
        resp = client.post(
            "/opusclip/process",
            json={
                "video_url": _VIDEO_URL,
                "user_id": user_id,
                "clips": [{"start_seconds": 0.0, "end_seconds": 60.0}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 402
    assert "Insufficient credits" in resp.json()["detail"]
    assert opusclip_call.called is False


def test_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/opusclip/status/whatever")
    assert resp.status_code == 401


def test_status_cross_user_returns_404(
    client: TestClient, make_user, make_jwt
) -> None:
    actor = make_user(credits=10.0)
    victim = make_user(credits=10.0)

    # Manually seed a job for the victim
    from services.opusclip_jobs import get_job_store
    from models.opusclip import ClipRange

    store = get_job_store()
    job = store.create(
        user_id=victim,
        ranges=[ClipRange(start_seconds=0, end_seconds=10)],
        minutes_required=10/60.0,
    )

    resp = client.get(
        f"/opusclip/status/{job.job_id}",
        headers={"Authorization": f"Bearer {make_jwt(actor)}"},
    )
    assert resp.status_code == 404  # not 403 — don't leak existence


def test_result_before_completion_returns_425(
    client: TestClient, make_user, make_jwt
) -> None:
    user_id = make_user(credits=10.0)
    token = make_jwt(user_id)

    from services.opusclip_jobs import get_job_store
    from models.opusclip import ClipRange

    job = get_job_store().create(
        user_id=user_id,
        ranges=[ClipRange(start_seconds=0, end_seconds=60)],
        minutes_required=1.0,
    )
    # Leave stage='queued' — not completed yet
    resp = client.get(
        f"/opusclip/result/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 425
    assert "still" in resp.json()["detail"].lower()


def test_result_after_failure_returns_409(
    client: TestClient, make_user, make_jwt
) -> None:
    user_id = make_user(credits=10.0)
    token = make_jwt(user_id)

    from services.opusclip_jobs import get_job_store
    from models.opusclip import ClipRange

    store = get_job_store()
    job = store.create(
        user_id=user_id,
        ranges=[ClipRange(start_seconds=0, end_seconds=60)],
        minutes_required=1.0,
    )
    store.update(job.job_id, stage="failed", error_message="OpusClip exploded")

    resp = client.get(
        f"/opusclip/result/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "exploded" in resp.json()["detail"]


@respx.mock
@pytest.mark.asyncio
async def test_failed_project_marks_job_failed_and_skips_deduction(
    client: TestClient, make_user, make_jwt, fake_supabase
) -> None:
    user_id = make_user(credits=10.0)
    token = make_jwt(user_id)

    respx.post(f"{_OPUS_BASE}/api/clip-projects").mock(
        return_value=httpx.Response(400, json={"code": "invalid_video", "message": "bad URL"}),
    )

    auth_headers = {"Authorization": f"Bearer {token}"}
    async with _make_async_client() as ac:
        submit = await ac.post(
            "/opusclip/process",
            json={
                "video_url": _VIDEO_URL,
                "user_id": user_id,
                "clips": [{"start_seconds": 0, "end_seconds": 60}],
            },
            headers=auth_headers,
        )
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]

        await _await_job(job_id)

        status_resp = await ac.get(f"/opusclip/status/{job_id}", headers=auth_headers)
    body = status_resp.json()
    assert body["stage"] == "failed"
    assert "invalid_video" in body["error_message"]
    # Credits untouched
    assert fake_supabase.profiles[user_id]["credit_balance"] == 10.0


@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_triggers_backoff_then_succeeds(
    client: TestClient, make_user, make_jwt
) -> None:
    """Verifies the OpusClipClient honors 429s without bubbling them up."""
    user_id = make_user(credits=10.0)
    token = make_jwt(user_id)

    # First call rate-limited, second call succeeds.
    calls = {"n": 0}

    def _create(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json=_project_response("P_001"))

    respx.post(f"{_OPUS_BASE}/api/clip-projects").mock(side_effect=_create)
    respx.get(url__regex=rf"^{_OPUS_BASE}/api/clip-projects/P_\d+$").mock(
        return_value=httpx.Response(200, json=_project_response("P_001", stage="COMPLETE")),
    )
    respx.get(f"{_OPUS_BASE}/api/exportable-clips").mock(
        return_value=httpx.Response(200, json=[_exportable_clip("P_001")]),
    )

    auth_headers = {"Authorization": f"Bearer {token}"}
    async with _make_async_client() as ac:
        submit = await ac.post(
            "/opusclip/process",
            json={
                "video_url": _VIDEO_URL,
                "user_id": user_id,
                "clips": [{"start_seconds": 0, "end_seconds": 60}],
            },
            headers=auth_headers,
        )
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]
        await _await_job(job_id)

        status_resp = (await ac.get(f"/opusclip/status/{job_id}", headers=auth_headers)).json()
    assert status_resp["stage"] == "completed"
    assert calls["n"] == 2  # one 429, one success


def test_cross_account_submit_forbidden(
    client: TestClient, make_user, make_jwt
) -> None:
    actor = make_user(credits=100.0)
    victim = make_user(credits=100.0)
    token = make_jwt(actor)

    resp = client.post(
        "/opusclip/process",
        json={
            "video_url": _VIDEO_URL,
            "user_id": victim,  # try to act on someone else's behalf
            "clips": [{"start_seconds": 0, "end_seconds": 60}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_job_limit_per_user_returns_429(
    client: TestClient, make_user, make_jwt
) -> None:
    user_id = make_user(credits=100.0)
    token = make_jwt(user_id)

    from services.opusclip_jobs import get_job_store, MAX_ACTIVE_JOBS_PER_USER
    from models.opusclip import ClipRange

    store = get_job_store()
    # Saturate the per-user limit with synthetic jobs.
    for _ in range(MAX_ACTIVE_JOBS_PER_USER):
        store.create(
            user_id=user_id,
            ranges=[ClipRange(start_seconds=0, end_seconds=60)],
            minutes_required=1.0,
        )

    with respx.mock(assert_all_called=False):
        resp = client.post(
            "/opusclip/process",
            json={
                "video_url": _VIDEO_URL,
                "user_id": user_id,
                "clips": [{"start_seconds": 0, "end_seconds": 60}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 429
    assert "already have" in resp.json()["detail"].lower()
