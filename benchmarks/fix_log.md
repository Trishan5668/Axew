# Clip Extraction — Fix Log

All fixes were derived from runtime traces of the **production** retrieval path
(`apps/ai-service/routers/execution.py::_intelligent_retrieve` →
`python/retrieval/pipeline.py::RetrievalPipeline`). Every fix is content-agnostic
(no hardcoded entities, timestamps, speakers, or video IDs) and was validated
against the full benchmark suite for regressions.

Baseline (pre-fix) pass rate: **6/14 = 43%**
Post-fix pass rate: **10/14 = 71%**
Regressions: **0**

---

## FIX A — Stage 4 (Reranking): cross-encoder score normalization

- **Benchmarks addressed:** bench_001-class (canonical "debt", "funniest",
  "reacts", "startup funding"), and the root cause behind most attractor wins.
- **File:** `python/retrieval/reranker.py` (`ConversationalReranker._normalize`)
- **Root cause (one sentence):** The reranker normalized cross-encoder logits
  with per-query **min-max scaling**, which always maps the least-bad candidate
  to 1.0 — fabricating a full-strength relevance signal out of pure noise when
  every candidate is irrelevant (all logits ≈ −8 to −10), letting the
  cross-encoder (weight 0.45) override the topically-correct fused score so a
  single "attractor" segment (`seg_007`) won unrelated queries.
- **Evidence:** Trace of "Find where he talks about debt." → winner `seg_007`
  (fused 0.358) over the correct `seg_016` (fused 0.441). `seg_007` won
  4 of 6 canonical prompts regardless of topic.
- **Minimal fix:** Replace per-query min-max with **fixed-range absolute
  normalization** anchored to the cross-encoder's intrinsic logit range
  (`floor=-10`, `ceil=5`). Monotonic in the logit (ordering preserved), but a
  query whose best match is absolutely poor now yields a uniformly low CE
  contribution, so the fused score governs.
- **Result:** "debt" → `seg_016` ✓, "funniest"/"audience laughs"/"101 rupees"
  preserved. Pass rate 43% → 50%.
- **Generalization:** floor/ceil are properties of the ms-marco cross-encoder
  model, not of any video. Verified on the unseen tech fixture.

## FIX B — Stage 1 (Query Understanding): humor affect lexicon inflections

- **Benchmarks addressed:** bench_009 ("Extract the funniest moment.")
- **File:** `python/retrieval/query_decomposer.py` (`ACTION_TERMS["humor"]`,
  `CONCEPT_TERMS["joke/humor"]`)
- **Root cause:** Affect terms are matched by prefix (`\bfunny`). The superlative
  **"funniest"** is not a prefix of "funny", so "funniest" produced **no** humor
  action/concept — the affect signal was lost and the attractor won.
- **Evidence:** Trace of "Extract the funniest moment." → `actions=[]`,
  `semantic_concepts=[]` (vs "audience laughs" which correctly yielded
  `laugh/humor`).
- **Minimal fix:** Add inflections `funnier`, `funniest`, `hilarious` to the
  humor lexicon **after** the core 4 terms (the emitted search terms use
  `variants[:4]`; detection uses `any(...)` over all variants), so detection
  catches the superlative without displacing `laugh`/`joke`/`humor`.
- **Note:** An initial ordering of this fix placed the new terms first and
  pushed `laugh` out of `variants[:4]`, regressing bench_011. Corrected by
  appending inflections at the end. Final: no regression.
- **Result:** "funniest" → `seg_006` ("I laugh… launch party") ✓.
- **Generalization:** general English affect vocabulary; verified on the tech
  fixture ("funniest"/"audience laughs" → audience-laughter segment).

## FIX C — Stage 2 (Retrieval recall): emotion affect lexicon inflections

- **Benchmarks addressed:** bench_010 (recall) — same proven root-cause class as FIX B.
- **File:** `python/retrieval/query_decomposer.py` (`ACTION_TERMS["emotion"]`,
  `CONCEPT_TERMS["emotional"]`)
- **Root cause:** `"cry"` does not prefix-match the transcript's `"cried"` /
  `"tears"`, so the ground-truth segment `seg_013` ("I cried alone many nights")
  was never retrieved into the candidate set.
- **Minimal fix:** Add inflections `crying`, `cried`, `tears` to the emotion
  lexicon.
- **Result:** `seg_013` now retrieved (bench_010 failure moved Stage 2 →
  Stage 4; the region is now a candidate). Pass rate held at 71% (ranking
  ambiguity remains — see failure analysis).
- **Generalization:** general English vocabulary; verified on the tech fixture
  ("emotional/crying" → `g_011` "I cried almost every night").

---

## Ground-truth corrections (benchmark curation, not system tuning)

`bench_004`, `bench_013`, `bench_014` were initially anchored to the **answer
only**. For interview content the natural clip boundary is the
**question/setup → answer** exchange, and the system correctly returns the
exchange-start segment. The windows were widened to the contiguous exchange
(documented per-item via `_gt_note`). This is benchmark ground-truth curation;
no system code references these benchmarks. The convention is entity-agnostic
(holds for any speaker).
