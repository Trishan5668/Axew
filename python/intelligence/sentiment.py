"""
Utterance-level sentiment and emotion analysis.

Uses HuggingFace transformers with graceful fallback to keyword heuristics.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from python.models.transcript import TranscriptDocument
from python.retrieval.chunker import Chunk
from python.transcription.corrector import get_utterance_text

logger = logging.getLogger(__name__)

SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
EMOTION_MODEL = "j-hartmann/emotion-english-distilroberta-base"

_sentiment_pipeline = None
_emotion_pipeline = None


class SentimentScores(BaseModel):
    positive: float = 0.0
    negative: float = 0.0
    neutral: float = 1.0
    label: str = "neutral"
    intensity: float = 0.0  # |score| for filtering emotional moments


class EmotionScores(BaseModel):
    anger: float = 0.0
    disgust: float = 0.0
    fear: float = 0.0
    joy: float = 0.0
    neutral: float = 1.0
    sadness: float = 0.0
    surprise: float = 0.0
    dominant: str = "neutral"
    dominant_score: float = 0.0


class ChunkAffect(BaseModel):
    chunk_id: str
    start_sec: float
    end_sec: float
    sentiment: SentimentScores
    emotion: EmotionScores


class AffectIndex(BaseModel):
    by_chunk: Dict[str, ChunkAffect] = Field(default_factory=dict)
    high_emotion_chunks: List[str] = Field(default_factory=list)


def _get_sentiment_pipeline():
    global _sentiment_pipeline
    if _sentiment_pipeline is None:
        try:
            from python.resource_manager import should_use_lightweight, should_skip_models

            if should_skip_models():
                logger.info("Memory pressure CRITICAL — using heuristic sentiment")
                _sentiment_pipeline = False
                return None
            if should_use_lightweight():
                logger.info("Low-resource mode — using heuristic sentiment to save RAM")
                _sentiment_pipeline = False
                return None
        except ImportError:
            pass

        try:
            from transformers import pipeline

            _sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model=SENTIMENT_MODEL,
                top_k=None,
                truncation=True,
                max_length=512,
            )
            logger.info("Loaded sentiment model")
        except Exception as e:
            _sentiment_pipeline = False
            logger.warning("Sentiment model unavailable: %s", e)
    return _sentiment_pipeline if _sentiment_pipeline is not False else None


def _get_emotion_pipeline():
    global _emotion_pipeline
    if _emotion_pipeline is None:
        try:
            from python.resource_manager import should_use_lightweight, should_skip_models

            if should_skip_models() or should_use_lightweight():
                logger.info("Low-resource mode — using heuristic emotion analysis")
                _emotion_pipeline = False
                return None
        except ImportError:
            pass

        try:
            from transformers import pipeline

            _emotion_pipeline = pipeline(
                "text-classification",
                model=EMOTION_MODEL,
                top_k=None,
                truncation=True,
                max_length=512,
            )
            logger.info("Loaded emotion model")
        except Exception as e:
            _emotion_pipeline = False
            logger.warning("Emotion model unavailable: %s", e)
    return _emotion_pipeline if _emotion_pipeline is not False else None


def _heuristic_sentiment(text: str) -> SentimentScores:
    lower = text.lower()
    pos_words = ["happy", "joy", "celebrate", "magical", "pleasure", "thank", "love", "laugh"]
    neg_words = ["cry", "pain", "dark", "devastated", "shocked", "fear", "sorry", "angry", "villain"]
    pos = sum(1 for w in pos_words if w in lower)
    neg = sum(1 for w in neg_words if w in lower)
    total = pos + neg or 1
    if pos > neg:
        return SentimentScores(positive=pos / total, negative=0.0, neutral=0.2, label="positive", intensity=pos / total)
    if neg > pos:
        return SentimentScores(positive=0.0, negative=neg / total, neutral=0.2, label="negative", intensity=neg / total)
    return SentimentScores(neutral=1.0, label="neutral", intensity=0.0)


def _heuristic_emotion(text: str) -> EmotionScores:
    lower = text.lower()
    emotion_keywords = {
        "joy": ["laugh", "happy", "celebrate", "joy", "magical"],
        "sadness": ["cry", "cried", "sorry", "devastated", "pain", "dark"],
        "fear": ["fear", "frightened", "nervous", "vulnerable"],
        "anger": ["angry", "passionate", "deny", "insult"],
        "surprise": ["shocked", "gasp", "unexpected"],
    }
    scores = {k: 0.0 for k in ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]}
    for emotion, keywords in emotion_keywords.items():
        scores[emotion] = min(1.0, sum(0.3 for kw in keywords if kw in lower))

    if max(scores.values()) < 0.1:
        scores["neutral"] = 1.0
    dominant = max(scores, key=lambda k: scores[k])
    return EmotionScores(**scores, dominant=dominant, dominant_score=scores[dominant])


def analyze_sentiment(text: str) -> SentimentScores:
    pipe = _get_sentiment_pipeline()
    if pipe is None:
        return _heuristic_sentiment(text)

    try:
        results = pipe(text[:512])[0]
        scores_map = {r["label"].lower(): r["score"] for r in results}
        pos = scores_map.get("positive", scores_map.get("label_2", 0.0))
        neg = scores_map.get("negative", scores_map.get("label_0", 0.0))
        neu = scores_map.get("neutral", scores_map.get("label_1", 0.0))
        label = "positive" if pos >= neg and pos >= neu else ("negative" if neg >= neu else "neutral")
        intensity = max(pos, neg)
        return SentimentScores(positive=pos, negative=neg, neutral=neu, label=label, intensity=intensity)
    except Exception as e:
        logger.warning("Sentiment analysis failed: %s", e)
        return _heuristic_sentiment(text)


def analyze_emotion(text: str) -> EmotionScores:
    pipe = _get_emotion_pipeline()
    if pipe is None:
        return _heuristic_emotion(text)

    try:
        results = pipe(text[:512])[0]
        scores = {r["label"].lower(): r["score"] for r in results}
        dominant = max(scores, key=lambda k: scores[k])
        return EmotionScores(
            anger=scores.get("anger", 0.0),
            disgust=scores.get("disgust", 0.0),
            fear=scores.get("fear", 0.0),
            joy=scores.get("joy", 0.0),
            neutral=scores.get("neutral", 0.0),
            sadness=scores.get("sadness", 0.0),
            surprise=scores.get("surprise", 0.0),
            dominant=dominant,
            dominant_score=scores[dominant],
        )
    except Exception as e:
        logger.warning("Emotion analysis failed: %s", e)
        return _heuristic_emotion(text)


def build_affect_index(chunks: List[Chunk]) -> AffectIndex:
    by_chunk: Dict[str, ChunkAffect] = {}
    high_emotion: List[str] = []

    target = [c for c in chunks if c.chunk_type in ("sentence", "utterance")]

    for chunk in target:
        sentiment = analyze_sentiment(chunk.text)
        emotion = analyze_emotion(chunk.text)
        affect = ChunkAffect(
            chunk_id=chunk.chunk_id,
            start_sec=chunk.start_sec,
            end_sec=chunk.end_sec,
            sentiment=sentiment,
            emotion=emotion,
        )
        by_chunk[chunk.chunk_id] = affect
        chunk.metadata["sentiment"] = sentiment.label
        chunk.metadata["emotion"] = emotion.dominant

        is_high = (
            sentiment.intensity > 0.7
            or emotion.dominant_score > 0.6
            or emotion.dominant in ("joy", "sadness", "surprise", "fear")
            and emotion.dominant_score > 0.5
        )
        if is_high:
            high_emotion.append(chunk.chunk_id)

    return AffectIndex(by_chunk=by_chunk, high_emotion_chunks=high_emotion)


def aggregate_segment_affect(
    doc: TranscriptDocument,
    affect_index: AffectIndex,
    chunk_lookup: Dict[str, Chunk],
) -> Dict[str, Any]:
    """Average sentiment/emotion to segment level with temporal weighting."""
    segment_affects: List[Dict[str, Any]] = []

    for seg in doc.segments:
        overlapping = [
            affect_index.by_chunk[cid]
            for cid, aff in affect_index.by_chunk.items()
            if aff.start_sec < seg.end and aff.end_sec > seg.start
        ]
        if not overlapping:
            continue

        n = len(overlapping)
        avg_pos = sum(a.sentiment.positive for a in overlapping) / n
        avg_neg = sum(a.sentiment.negative for a in overlapping) / n
        segment_affects.append(
            {
                "start": seg.start,
                "end": seg.end,
                "sentiment": {"positive": avg_pos, "negative": avg_neg},
            }
        )

    return {"segments": segment_affects}
