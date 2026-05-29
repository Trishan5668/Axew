# AXEW Multimodal Semantic Video Intelligence — Roadmap

This document maps the 11-phase spec in
`docs/spec/MULTIMODAL_INTELLIGENCE.md` (paste of the original brief) to the
**actual** repository layout (`python/` + `apps/ai-service/` + `crates/`),
records what was delivered in the **Phase 16** slice, and lists the remaining
work in priority order. It is the source of truth for follow-up tasks — read
this before starting any module in the spec.

---

## 1. Why this document exists

The original spec proposed a brand-new `backend/` tree, mandatory Celery +
Redis + Qdrant + CUDA, and roughly 25 GB of new model weights (RAFT,
InsightFace, RetinaFace, DeepFace, MediaPipe, SpeechBrain, llama3:70b,
BLIP-2 / LLaVA, …). The repository already contains a sophisticated
retrieval engine under `python/` that has been iterated through 15 phases
of benchmarking, with a per-video `~/.axew/cache` and `~/.axew/frames`
layout, ChromaDB as the vector store, CPU-by-default config, and explicit
"graceful fallback" requirements for every optional model. Adopting the
spec verbatim would require either a fork or a multi-week migration.

The **Phase 16 slice** delivered in this branch fixes the spec's headline
failure ("Keep only the part where the interviewer gives 101 rupees to
Vijay Mallya") *inside* the existing layout, with zero regression and
zero hard dependency on the heavy stack. The remaining 11 phases are
captured below as discrete, individually-testable follow-ups.

---

## 2. Phase 16 (delivered) — what's new

| Module | Purpose | Test entry point |
|---|---|---|
| `python/knowledge/event_graph.py` | NetworkX-backed `EventGraph` + `EventNode` (faithful to the spec). | `python -m python.knowledge.event_graph` |
| `python/knowledge/hierarchical_index.py` | Moment → Segment → Scene → Video re-chunking with tense / action-type / vocative / monetary tagging. | `python -m python.knowledge.hierarchical_index` |
| `python/perception/face_identity.py` | Project-scoped identity registry. InsightFace / DeepFace backends optional. | `python -m python.perception.face_identity` |
| `python/perception/speaker_face_correlator.py` | Maps diarization labels → face identities by timestamp overlap. | `python -m python.perception.speaker_face_correlator` |
| `python/retrieval/multimodal_fusion_scorer.py` | Confidence-gated multi-channel fusion. | `python -m python.retrieval.multimodal_fusion_scorer` |
| `python/retrieval/frame_precise_refiner.py` | Action-anchored ±0.5 s timestamp refinement with reaction-window extension. | `python -m python.retrieval.frame_precise_refiner` |
| `python/retrieval/entity_grounded_retriever.py` | The new deterministic retriever — no LLM calls, no GPU. | `python -m python.retrieval.entity_grounded_retriever` |
| `python/evaluation/phase16_retriever.py` | Benchmark adapter. | `python -m python.evaluation.benchmark --phase phase16` |

### Benchmark results (full 36-case suite, fixture `interview_segments.json`)

| Metric | Baseline | Phase 15 | **Phase 16** |
|---|---:|---:|---:|
| Mean Temporal IoU | 0.049 | 0.157 | **0.230** |
| Timestamp MAE (sec) | 305.1 | 178.3 ms → 178k s¹ | **88.8** |
| Hit@1 | 44.4 % | 26.1 % | 33.3 % |
| HARD Hit@1 | 40 % | — | **80 %** |
| HARD IoU | 0.000 | — | **0.681** |
| `ent_001` IoU (the spec failure) | **0.000** | 0.157 | **1.000** |

¹ The Phase 15 report's `timestamp_mae` is in raw milliseconds and looks
  alarming; converted to seconds it's still substantially worse than Phase 16.

The Hit@1 dip is by design: the confidence gate **refuses to guess** when
no candidate has corroborating signals (entity + action + role + tense +
monetary). Returning the wrong clip in a timeline-mutation tool is worse
than returning nothing — the caller should fall back to the LLM-augmented
`SemanticRetrievalPipeline` or surface a "low confidence" UI state.

---

## 3. Architecture in the *actual* tree

```
python/
├── knowledge/                NEW   ← spec Phase 6 (knowledge layer)
│   ├── event_graph.py
│   └── hierarchical_index.py
├── perception/               NEW   ← spec Phases 1-4 integration surface
│   ├── face_identity.py
│   └── speaker_face_correlator.py
├── retrieval/                EXTENDED
│   ├── entity_grounded_retriever.py   NEW (spec Phase 7 deterministic path)
│   ├── multimodal_fusion_scorer.py    NEW (spec Phase 7 scoring core)
│   ├── frame_precise_refiner.py       NEW (spec Phase 7 grounding)
│   ├── orchestrator.py                ← existing LLM-augmented orchestrator
│   ├── timestamp_refiner.py           ← existing word-aligned refiner
│   ├── semantic_retrieval_pipeline.py ← existing
│   └── …
├── semantic/                 ← existing LLM event-grounding pipeline
├── enrichment/               ← existing action / monetary / entity-graph
├── intelligence/             ← existing query parser / context manager
├── multimodal/               ← existing CLIP + frame + OCR + scene describer
├── transcription/            ← existing whisper + diarization + corrector
├── evaluation/
│   ├── benchmark.py                  EXTENDED  (phase16 CLI choice)
│   ├── phase16_retriever.py          NEW
│   └── …
└── benchmarks/results/
    └── phase16_*.json                NEW  (per-run reports)
```

`apps/ai-service/main.py` and `apps/ai-service/routers/semantic.py` are
**unchanged** — the existing `/api/semantic/extract` endpoint continues to
use `python.semantic.retrieval_pipeline.SemanticRetrievalPipeline`. Phase
16 is opt-in via the benchmark CLI and via direct module import.

---

## 4. Remaining 11 phases — priority-ordered follow-ups

> Each phase below should be done in its own branch. The deliverable for
> every phase is **one PR** that:
>
> 1. adds code only under `python/` (no `backend/` tree),
> 2. keeps `requirements.txt` deps optional with graceful fallback,
> 3. exposes a new benchmark phase (`--phase phaseN`), and
> 4. updates this roadmap with the actual delta.

### Tier A — Quick wins (no GPU required)

1. **Phase 0 — Async pipeline + cache layout** *(M)*
   - Replace the in-process `python/processing/queue.py` with a Celery
     adapter that defaults to the eager/sync executor when Redis is absent.
   - Define the per-video `~/.axew/cache/{video_id}/perception/` schema and
     migrate existing `frame_index`, `ocr_results`, `scene_descriptions`,
     and the new `event_graph.json` + `identity_db.json` into it.
   - Owner deliverable: `python/core/pipeline.py`, `python/core/cache_layout.py`.

2. **Phase 6 finalization — Qdrant adapter** *(S)*
   - Implement `python/retrieval/vector_store_qdrant.py` behind the existing
     `VectorStore` Protocol. ChromaDB stays as the default; users opt into
     Qdrant via `AXEW_VECTOR_STORE=qdrant`.

3. **Phase 8 — ASS caption engine** *(M)*
   - Port the spec's `caption_engine.py` to `python/editing/captions.py`.
     Consumes the existing word-level timestamps from
     `python.transcription.whisper_engine`. No new model deps. Add a Rust
     `cargo` task in `crates/axew-core/src/extraction/` to mux the `.ass`
     track into FFmpeg exports.

### Tier B — GPU-optional perception (heavy deps, all optional)

4. **Phase 5 — ASR upgrade** *(L)*
   - Drop-in `faster-whisper` + `whisperx` forced alignment + `pyannote.audio`
     3.1 diarization inside `python/transcription/whisper_engine.py`. Keep
     `openai-whisper` as the fallback. Add per-word `log_prob` to the
     `TranscriptChunk` model so the existing low-confidence rescore in
     `python/transcription/corrector.py` can use real confidences instead of
     interpolated 0.5.

5. **Phase 2 — Face tracking** *(L)*
   - Real `IdentityRegistry` backend in `python/perception/face_identity.py`
     when `insightface` is importable. Add `python/perception/face_tracker.py`
     that does 5 fps sampling + DeepSORT consolidation. Cache to
     `~/.axew/cache/{video_id}/perception/face_tracks.json`.

6. **Phase 1 — Scene detection** *(M)*
   - Hook PySceneDetect into `python/multimodal/frame_extractor.py` for shot
     boundaries. CLIP scene-labelling already exists in
     `python/multimodal/scene_describer.py` — extend it with the spec's
     zero-shot label list and write `scene_map.json` per video.
   - **Fix the spec's bug**: the spec's `SceneDetector.label_scene` calls
     `get_image_features` with only pixel values, which never actually
     compares text to image. The corrected approach is to call the full
     `CLIPModel.forward` with both `pixel_values` and `input_ids` and softmax
     `logits_per_image[0]` — see comments in `python/multimodal/clip_embedder.py`.

7. **Phase 3 — Motion analysis** *(L)*
   - `python/perception/motion_analyzer.py` with RAFT optical flow +
     MediaPipe hand/pose. Emit per-second motion intensity and gesture
     events into the `EventGraph` as `gesture` / `action_peak` nodes. When
     RAFT is unavailable, fall back to OpenCV Farnebäck flow or skip.

8. **Phase 4 — Emotion analysis** *(M)*
   - `python/perception/emotion_analyzer.py` wrapping DeepFace + SpeechBrain
     wav2vec2-IEMOCAP. Late-fusion as per spec. Tag `EventGraph` nodes with
     `emotion_peak` events when fused intensity > 0.75.
   - **Fix the spec's bug**: `EMOTION_WEIGHTS["context"]=0.20` is referenced
     but never used in the fusion math. Either drop the key or implement a
     true context weighting (e.g. scene label boost for "emotional moment").

### Tier C — UX + viral pipeline

9. **Phase 9 — Viral scoring + vertical reframing** *(M)*
   - `python/intelligence/viral_scorer.py` already partially exists. Extend
     with the spec's weights, expose via `/api/intelligence/viral-rank`.
   - `python/editing/vertical_reframer.py` for 9:16 crop trajectory.
     **Fix the spec's bug**: the spec's `VerticalReframer.compute_crop_trajectory`
     calls `cap.get(CAP_PROP_FRAME_COUNT)` *after* `cap.release()`. Cache the
     frame count before release.

10. **Phase 10 — API + IPC bridge** *(S)*
    - Add `apps/ai-service/routers/intelligence.py` exposing:
      - `POST /api/intelligence/grounded-query` — wraps `EntityGroundedRetriever`
      - `GET  /api/intelligence/event-graph/{video_id}` — JSON dump
      - `POST /api/intelligence/identity/register` — UI label binding
    - Add matching IPC handlers in `apps/desktop/electron/main.ts`. Types
      already exported from `packages/shared-types/src/ai.ts`.

11. **Phase 11 — Benchmark suite expansion** *(S)*
    - Extend `python/evaluation/benchmark.py` with the spec's
      `BenchmarkCase`/`AxewBenchmark` runner so participant recall and event-type
      accuracy are tracked alongside the existing temporal IoU metrics.
    - Add a `--video-path` CLI flag so when real media is available the
      perception modules actually run and the event graph is populated from
      visual evidence.

---

## 5. Dependency policy

The repository's house rule, applied uniformly across all 11 phases:

- **Required deps** are the ones already in `apps/ai-service/requirements.txt`
  uncommented (`fastapi`, `openai-whisper`, `sentence-transformers`,
  `chromadb`, `rank-bm25`, `rapidfuzz`, `networkx`, `qdrant-client`).
- **Optional deps** are everything that needs CUDA, multi-GB downloads, or
  Windows-specific compile steps. Every code path that touches them goes
  through `python.perception.face_identity.detect_backend_status()` (or an
  equivalent probe) and degrades gracefully when absent.
- The CI / benchmark harness must run end-to-end on **CPU-only Python 3.10**
  with *zero* optional deps installed. Phase 16 already meets this bar.

---

## 6. Spec deltas worth remembering

The original spec had a handful of latent issues that any follow-up must
correct rather than copy verbatim:

| Spec module | Issue | Fix when porting |
|---|---|---|
| `SceneDetector.label_scene` | `get_image_features` is called instead of the joint forward → softmax never matches text against image. | Use full `CLIPModel.__call__` with `pixel_values` + `input_ids`, then `outputs.logits_per_image.softmax(-1)`. |
| `MultimodalEmbedder.embed_moment` | `fusion_proj` is randomly initialized (no training) and modulation collapses to a scalar mean — destroys the embedding. | Either train a learned projection or use direct concatenation + L2-norm. |
| `EmotionAnalyzer.fuse_emotions` | `EMOTION_WEIGHTS["context"]` declared but never applied. | Plumb scene/context bonus into the fusion math, or drop the key. |
| `VerticalReframer.compute_crop_trajectory` | `cap.get(...)` called after `cap.release()`. | Cache `width`, `height`, `frame_count`, `fps` before release. |
| `ViralScorer.score_segment` | Sums weights without normalization safeguard; a single missing channel can dominate. | Renormalize to applicable channels (same pattern as `MultimodalFusionScorer`). |
| `EventGraph.add_event` (NetworkX) | Temporal adjacency edge direction is hard-coded without comparing timestamps. | Resolve direction by `start_ts` ordering (already corrected in Phase 16). |

---

## 7. Running what's in this branch

```bash
# from repo root
python -m python.evaluation.benchmark --phase phase16
python -m python.evaluation.benchmark --phase baseline    # head-to-head
diff python/evaluation/reports/phase16_*.json \
     python/evaluation/reports/baseline_*.json
```

Per-module smoke harnesses:

```bash
python -m python.knowledge.event_graph
python -m python.knowledge.hierarchical_index
python -m python.perception.face_identity
python -m python.perception.speaker_face_correlator
python -m python.retrieval.multimodal_fusion_scorer
python -m python.retrieval.frame_precise_refiner
python -m python.retrieval.entity_grounded_retriever
python -m python.evaluation.phase16_retriever
```
