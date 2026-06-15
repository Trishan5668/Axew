# Phase 1 Action/Emotion Retrieval Failure Analysis

Generated: 2026-06-15T14:03:27.972136+00:00

## Scope

This is diagnostic-only. The production dense/BM25/entity/fuzzy hybrid retrieval scaffold was not modified.
The benchmark uses available AXEW transcript fixtures rather than raw video/audio, so visual/audio labels are fixture-derived and mark where current transcript-heavy retrieval is expected to be weak.

## Summary

- Cases: 40 total, 40 completed, 0 errors.
- Overall IoU>=0.5: 77.5%.
- Overall mean IoU: 0.774.
- action: IoU>=0.5 60.0%, mean IoU 0.600, mean confidence 0.572
- emotion: IoU>=0.5 95.0%, mean IoU 0.949, mean confidence 0.516
- Strategy failures surfaced as typed errors: 0.
- Absolute confidence distribution: {'count': 40, 'min': 0.0939, 'p25': 0.4604, 'median': 0.5779, 'p75': 0.6544, 'max': 0.8198, 'mean': 0.5441, 'stddev': 0.1678, 'saturated_at_1_count': 0}.
- Candidate diversity: {'mean_candidate_count': 15.45, 'mean_unique_windows_top_5': 4.975, 'mean_unique_chunks_top_5': 4.975, 'mean_temporal_span_top_5': 434.3055}.

## Failure Modes

- action verb not in transcript at all: 3
- correct moment retrieved but wrong boundary: 1
- emotion expressed via tone/visual not text: 1
- high confidence on wrong segment: 1
- wrong semantic segment: 4

## Swallowed Exceptions Removed

- strategy_context: intelligence artifact construction.
- strategy_side_index: side-index construction for strategy artifacts.
- emotion: EmotionalStrategy candidate retrieval.
- action: EntityActionStrategy candidate retrieval.
- event_index: event-index candidate bridge.

## Winning Branch Distribution

- bm25: 35
- dense: 2
- entity: 1
- fuzzy: 1
- strategy:emotion: 1

## Per-Query Results

| ID | Category | Winning branch | Retrieved | Ground truth | Confidence | IoU | Failure modes |
|----|----------|----------------|-----------|--------------|------------|-----|---------------|
| act_mallya_001 | action | fuzzy | 92.50-108.00 | 92.50-108.00 | 0.721 | 1.000 | pass |
| act_mallya_002 | action | bm25 | 108.00-118.50 | 108.00-118.50 | 0.663 | 1.000 | pass |
| act_mallya_003 | action | bm25 | 740.00-755.00 | 755.00-770.00 | 0.429 | 0.000 | action verb not in transcript at all |
| act_mallya_004 | action | bm25 | 740.00-755.00 | 755.00-770.00 | 0.536 | 0.000 | action verb not in transcript at all |
| act_mallya_005 | action | bm25 | 285.00-302.00 | 285.00-302.00 | 0.554 | 1.000 | pass |
| act_mallya_006 | action | bm25 | 302.00-315.00 | 302.00-315.00 | 0.571 | 1.000 | pass |
| act_mallya_007 | action | bm25 | 215.50-228.00 | 228.00-245.00 | 0.680 | 0.000 | wrong semantic segment |
| act_mallya_008 | action | bm25 | 328.00-342.00 | 45.50-55.00 | 0.493 | 0.000 | action verb not in transcript at all |
| act_mallya_009 | action | bm25 | 108.00-118.50 | 108.00-118.50 | 0.689 | 1.000 | pass |
| act_mallya_010 | action | bm25 | 850.00-860.00 | 850.00-860.00 | 0.651 | 1.000 | pass |
| act_mallya_011 | action | entity | 535.00-552.00 | 565.00-578.00 | 0.760 | 0.000 | high confidence on wrong segment |
| act_mallya_012 | action | bm25 | 702.00-710.00 | 702.00-710.00 | 0.459 | 1.000 | pass |
| act_tech_001 | action | bm25 | 36.00-54.00 | 36.00-54.00 | 0.604 | 1.000 | pass |
| act_tech_002 | action | bm25 | 54.00-64.00 | 54.00-64.00 | 0.721 | 1.000 | pass |
| act_tech_003 | action | bm25 | 78.00-90.00 | 78.00-90.00 | 0.766 | 1.000 | pass |
| act_tech_004 | action | dense | 90.00-104.00 | 104.00-120.00 | 0.391 | 0.000 | wrong semantic segment |
| act_tech_005 | action | bm25 | 180.00-196.00 | 180.00-196.00 | 0.820 | 1.000 | pass |
| act_tech_006 | action | bm25 | 196.00-210.00 | 196.00-210.00 | 0.610 | 1.000 | pass |
| act_default_001 | action | dense | 38.94-41.82 | 29.28-34.82 | 0.237 | 0.000 | wrong semantic segment |
| act_default_002 | action | bm25 | 27.36-29.28 | 76.16-85.48 | 0.094 | 0.000 | wrong semantic segment |
| emo_mallya_001 | emotion | bm25 | 142.00-158.50 | 142.00-158.50 | 0.563 | 1.000 | pass |
| emo_mallya_002 | emotion | bm25 | 245.00-258.00 | 245.00-272.00 | 0.268 | 0.481 | emotion expressed via tone/visual not text, correct moment retrieved but wrong boundary |
| emo_mallya_003 | emotion | bm25 | 302.00-315.00 | 302.00-328.00 | 0.602 | 0.500 | pass |
| emo_mallya_004 | emotion | bm25 | 315.00-328.00 | 315.00-328.00 | 0.576 | 1.000 | pass |
| emo_mallya_005 | emotion | bm25 | 372.00-388.00 | 372.00-388.00 | 0.312 | 1.000 | pass |
| emo_mallya_006 | emotion | bm25 | 388.00-400.00 | 388.00-400.00 | 0.488 | 1.000 | pass |
| emo_mallya_007 | emotion | bm25 | 168.00-185.00 | 168.00-185.00 | 0.581 | 1.000 | pass |
| emo_mallya_008 | emotion | bm25 | 55.00-68.30 | 55.00-68.30 | 0.756 | 1.000 | pass |
| emo_mallya_009 | emotion | bm25 | 432.00-445.00 | 432.00-445.00 | 0.648 | 1.000 | pass |
| emo_mallya_010 | emotion | bm25 | 445.00-460.00 | 445.00-460.00 | 0.630 | 1.000 | pass |
| emo_mallya_011 | emotion | bm25 | 505.00-520.00 | 505.00-520.00 | 0.341 | 1.000 | pass |
| emo_mallya_012 | emotion | bm25 | 710.00-725.00 | 710.00-725.00 | 0.687 | 1.000 | pass |
| emo_mallya_013 | emotion | bm25 | 725.00-740.00 | 725.00-740.00 | 0.568 | 1.000 | pass |
| emo_mallya_014 | emotion | bm25 | 782.00-795.00 | 782.00-795.00 | 0.461 | 1.000 | pass |
| emo_tech_001 | emotion | bm25 | 9.00-22.00 | 9.00-22.00 | 0.420 | 1.000 | pass |
| emo_tech_002 | emotion | bm25 | 36.00-54.00 | 36.00-54.00 | 0.123 | 1.000 | pass |
| emo_tech_003 | emotion | bm25 | 104.00-120.00 | 104.00-120.00 | 0.507 | 1.000 | pass |
| emo_tech_004 | emotion | strategy:emotion | 134.00-150.00 | 134.00-150.00 | 0.579 | 1.000 | pass |
| emo_tech_005 | emotion | bm25 | 134.00-150.00 | 134.00-150.00 | 0.620 | 1.000 | pass |
| emo_tech_006 | emotion | bm25 | 164.00-180.00 | 164.00-180.00 | 0.584 | 1.000 | pass |

## Diagnostic Conclusions

- Current retrieval remains dominated by transcript-derived dense/BM25/fuzzy/entity evidence; action and emotion cases that require visual, facial, or paralinguistic confirmation are not directly observable.
- Reported confidence is the existing absolute final score. The percentile rank score is retained separately as rank_percentile because its top candidate is expected to equal 1.0 by construction.
- Strategy failures surface as StrategyExecutionError with structured query, strategy, exception type, and exception message fields; no strategy fallback result is emitted.
- Successful-case behavior comparison: {'prior_successful_cases': 25, 'identical_cases': 25, 'changed_case_ids': []}.
- Boundary failures are expected where query intent spans a question-answer exchange or a short reaction inside a longer transcript segment.
- No Phase 2 fixes were applied in this run.
