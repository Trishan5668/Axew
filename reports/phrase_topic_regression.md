# Phrase & Topic Retrieval Regression

Generated: 2026-06-16T11:54:43.716032+00:00

## Scope

Regression-only benchmark over the production retrieval path:
RetrievalPipeline.retrieve() -> HybridRetriever.retrieve() -> ContextExpander.expand() -> ConversationalReranker.rerank().
No retrieval behavior was modified for this run.

## Summary

- Queries: 34 total, 34 completed, 0 errors.
- Phrase IoU>=0.5: 100.0% (17 queries).
- Topic IoU>=0.5: 100.0% (17 queries).
- Overall candidate coverage: 100.0%.
- Timestamp regressions: 0.
- Confidence NaN count: 0.
- Winning branches: {'bm25': 28, 'entity': 2, 'strategy:action': 1, 'strategy:emotion+action': 3}.

## Per-Query Results

| ID | Type | Branch | Winner chunk | Retrieved | Ground truth | Confidence | IoU | Coverage | GT rank |
|----|------|--------|--------------|-----------|--------------|------------|-----|----------|---------|
| phrase_mallya_001 | phrase | bm25 | seg_016 | 185.00-198.00 | 185.00-198.00 | 0.705 | 1.000 | yes | 1 |
| phrase_mallya_002 | phrase | bm25 | seg_019 | 228.00-245.00 | 228.00-245.00 | 0.911 | 1.000 | yes | 1 |
| phrase_mallya_003 | phrase | bm25 | seg_062 | 810.00-825.00 | 810.00-825.00 | 0.870 | 1.000 | yes | 1 |
| phrase_mallya_004 | phrase | bm25 | seg_058 | 755.00-770.00 | 755.00-770.00 | 0.692 | 1.000 | yes | 1 |
| phrase_mallya_005 | phrase | bm25 | seg_011 | 118.50-130.00 | 118.50-130.00 | 0.756 | 1.000 | yes | 1 |
| phrase_mallya_006 | phrase | bm25 | seg_040 | 535.00-552.00 | 535.00-552.00 | 0.835 | 1.000 | yes | 1 |
| phrase_mallya_007 | phrase | bm25 | seg_048 | 648.00-662.00 | 648.00-662.00 | 0.630 | 1.000 | yes | 1 |
| phrase_mallya_008 | phrase | bm25 | seg_032 | 415.00-432.00 | 415.00-432.00 | 0.572 | 1.000 | yes | 1 |
| phrase_mallya_009 | phrase | bm25 | seg_009 | 92.50-108.00 | 92.50-108.00 | 0.740 | 1.000 | yes | 1 |
| phrase_mallya_010 | phrase | strategy:emotion+action | seg_004 | 28.00-45.50 | 28.00-45.50 | 0.595 | 1.000 | yes | 1 |
| phrase_mallya_011 | phrase | entity | seg_001 | 0.00-8.50 | 0.00-8.50 | 0.873 | 1.000 | yes | 1 |
| phrase_mallya_012 | phrase | bm25 | seg_024 | 302.00-315.00 | 302.00-315.00 | 0.652 | 1.000 | yes | 1 |
| phrase_default_001 | phrase | bm25 | 25 | 37.06-38.94 | 37.06-38.94 | 0.710 | 1.000 | yes | 1 |
| phrase_default_002 | phrase | bm25 | 45 | 77.46-85.48 | 77.46-85.48 | 0.491 | 1.000 | yes | 1 |
| phrase_default_003 | phrase | strategy:emotion+action | 26 | 38.94-41.82 | 38.94-41.82 | 0.287 | 1.000 | yes | 1 |
| phrase_tech_001 | phrase | bm25 | g_004 | 36.00-54.00 | 36.00-54.00 | 0.692 | 1.000 | yes | 1 |
| phrase_tech_002 | phrase | bm25 | g_013 | 164.00-180.00 | 164.00-180.00 | 0.707 | 1.000 | yes | 1 |
| topic_mallya_001 | topic | strategy:emotion+action | seg_004 | 28.00-45.50 | 28.00-45.50 | 0.575 | 1.000 | yes | 1 |
| topic_mallya_002 | topic | bm25 | seg_013 | 142.00-158.50 | 142.00-158.50 | 0.673 | 1.000 | yes | 1 |
| topic_mallya_003 | topic | bm25 | seg_023 | 285.00-302.00 | 285.00-302.00 | 0.667 | 1.000 | yes | 1 |
| topic_mallya_004 | topic | entity | seg_040 | 535.00-552.00 | 535.00-552.00 | 0.869 | 1.000 | yes | 1 |
| topic_mallya_005 | topic | bm25 | seg_036 | 475.00-492.00 | 475.00-492.00 | 0.911 | 1.000 | yes | 1 |
| topic_mallya_006 | topic | bm25 | seg_060 | 782.00-795.00 | 782.00-795.00 | 0.601 | 1.000 | yes | 1 |
| topic_mallya_007 | topic | bm25 | seg_056 | 725.00-740.00 | 725.00-740.00 | 0.650 | 1.000 | yes | 1 |
| topic_mallya_008 | topic | bm25 | seg_018 | 215.50-228.00 | 215.50-228.00 | 0.921 | 1.000 | yes | 1 |
| topic_mallya_009 | topic | bm25 | seg_012 | 130.00-142.00 | 130.00-142.00 | 0.653 | 1.000 | yes | 1 |
| topic_mallya_010 | topic | bm25 | seg_006 | 55.00-68.30 | 55.00-68.30 | 0.588 | 1.000 | yes | 1 |
| topic_mallya_011 | topic | strategy:action | seg_029 | 372.00-388.00 | 372.00-388.00 | 0.519 | 1.000 | yes | 1 |
| topic_mallya_012 | topic | bm25 | seg_025 | 315.00-328.00 | 315.00-328.00 | 0.627 | 1.000 | yes | 1 |
| topic_tech_001 | topic | bm25 | g_004 | 36.00-54.00 | 36.00-54.00 | 0.721 | 1.000 | yes | 1 |
| topic_tech_002 | topic | bm25 | g_011 | 134.00-150.00 | 134.00-150.00 | 0.643 | 1.000 | yes | 1 |
| topic_tech_003 | topic | bm25 | g_015 | 196.00-210.00 | 196.00-210.00 | 0.593 | 1.000 | yes | 1 |
| topic_tech_004 | topic | bm25 | g_006 | 64.00-78.00 | 64.00-78.00 | 0.560 | 1.000 | yes | 1 |
| topic_default_001 | topic | bm25 | 30 | 46.76-49.64 | 46.76-49.64 | 0.562 | 1.000 | yes | 1 |
