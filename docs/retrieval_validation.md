# Retrieval Validation

This document describes the standard validation workflow for AXEW retrieval benchmarks. These checks are diagnostic and regression-only: they exercise the production retrieval path without modifying retrieval behavior.

## Purpose

The validation suite protects known-good retrieval capabilities from silent regressions introduced by routing, fusion, action/emotion strategy work, or other pipeline changes.

| Benchmark | Focus |
| --------- | ----- |
| `phrase_topic_regression` | Exact phrase retrieval, semantic topic retrieval, entity hits, timestamp integrity, confidence calibration |
| `action_emotion_phase1` | Action/emotion diagnostic metrics and failure categorization |
| `action_emotion_production_trace` | Production-path evidence for strategy invocation, fusion, expansion, and reranking |

All benchmarks call `RetrievalPipeline.retrieve()` and therefore traverse:

```text
RetrievalPipeline.retrieve()
  -> HybridRetriever.retrieve()
  -> ContextExpander.expand()
  -> ConversationalReranker.rerank()
```

## Success Thresholds

### Phrase & topic regression (`test_phrase_topic_regression`)

| Metric | Target |
| ------ | ------ |
| Phrase IoU >= 0.5 | >= 90% of phrase queries |
| Topic IoU >= 0.5 | >= 85% of topic queries |
| Candidate coverage | >= 95% of all queries |
| Timestamp regressions | 0 |
| Confidence NaN count | 0 |

Candidate coverage means at least one production candidate overlaps the labeled ground-truth window with IoU >= 0.5, even if the final winner is wrong.

### Action/emotion benchmarks

The action/emotion unit tests validate benchmark helper logic and production-trace diagnostics. They do not enforce clip-quality thresholds; see the generated reports under `reports/` for diagnostic interpretation.

## Validation Procedure

From the repository root:

```bash
python -m unittest \
  python.benchmarks.test_phrase_topic_regression \
  python.benchmarks.test_action_emotion_phase1 \
  python.benchmarks.test_action_emotion_production_trace
```

To regenerate benchmark artifacts manually:

```bash
python python/benchmarks/phrase_topic_regression.py
python python/benchmarks/action_emotion_phase1.py
python python/benchmarks/action_emotion_production_trace.py
```

Outputs:

- `python/benchmarks/results/phrase_topic_regression_current.json`
- `reports/phrase_topic_regression.md`
- `python/benchmarks/results/action_emotion_phase1_current.json`
- `reports/action_emotion_phase1_failure_analysis.md`
- `python/benchmarks/results/action_emotion_production_trace.json`
- `reports/action_emotion_production_trace.md`

## Fixtures

Phrase/topic regression reuses existing transcript corpora:

- `python/evaluation/fixtures/interview_segments.json` (Mallya interview)
- `python/evaluation/fixtures/generalization_tech_interview.json` (tech generalization interview)
- `data/default/transcript_enriched.json` (noisy Hinglish ASR, including IPL / Royal Challengers Bangalore and monetary phrases)

Labeled cases live in `python/benchmarks/fixtures/phrase_topic_regression.json`.

## Known Limitations

- Benchmarks run on transcript fixtures, not raw video/audio. Visual or paralinguistic cues referenced in natural-language queries may be absent from the transcript.
- Temporal IoU is sensitive to segment boundaries. Adjacent question/answer spans can lower IoU even when the correct chunk is retrieved.
- The default Hinglish fixture contains ASR noise; phrase queries for that corpus use transcript-aligned wording.
- First run loads embedding and reranker models and is slower than subsequent runs in the same process.
- Phrase/topic regression encodes current known-good behavior. A failing test may indicate a real regression or outdated fixture labels after intentional retrieval changes.

## When a Regression Test Fails

1. Run the individual benchmark runner to inspect per-query IoU, branch winners, and candidate coverage in the JSON report.
2. Read `reports/phrase_topic_regression.md` for the human-readable table.
3. If the behavior change is intentional, update fixture labels only after verifying the new output is correct.
4. Do not relax thresholds to mask retrieval regressions.
