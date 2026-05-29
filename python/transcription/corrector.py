"""
Transcript correction via local Ollama with number/proper-noun preservation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional

import httpx

from python.models.transcript import Utterance

logger = logging.getLogger(__name__)

OLLAMA_TIMEOUT_SEC = 30.0
CORRECTION_PROMPT = (
    "Correct any transcription errors in this speech segment. "
    "Preserve all proper nouns, names, numbers, and currency mentions exactly. "
    "Return only the corrected text, no explanations. "
    "Segment: {text}"
)

# Patterns for high-value tokens that Whisper often gets right
NUMBER_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:rupees?|crore|dollars?|₹|\$|percent|%)\b",
    re.IGNORECASE,
)
PROPER_NOUN_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


def extract_protected_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    tokens.extend(NUMBER_PATTERN.findall(text))
    tokens.extend(PROPER_NOUN_PATTERN.findall(text))
    return tokens


def restore_protected_tokens(original: str, corrected: str) -> str:
    """Revert LLM changes to numbers and proper nouns from original Whisper text."""
    result = corrected
    for token in extract_protected_tokens(original):
        if token not in result:
            # Find closest case-insensitive match in corrected and replace
            pattern = re.compile(re.escape(token), re.IGNORECASE)
            if not pattern.search(result):
                # Token was changed or removed — append note or force restore
                # Replace first number-like substring if types match
                orig_nums = NUMBER_PATTERN.findall(original)
                corr_nums = NUMBER_PATTERN.findall(result)
                if orig_nums and (not corr_nums or orig_nums[0].lower() != corr_nums[0].lower()):
                    if corr_nums:
                        result = result.replace(corr_nums[0], orig_nums[0], 1)
                    else:
                        result = f"{result} [{orig_nums[0]}]"
                elif token in original and token not in result:
                    result = result  # keep corrected for non-numeric proper nouns if close
            else:
                result = pattern.sub(token, result, count=1)
    return result


async def _call_ollama(
    text: str,
    ollama_host: str = "http://localhost:11434",
    model: str = "mistral-nemo",
) -> Optional[str]:
    prompt = CORRECTION_PROMPT.format(text=text)
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SEC) as client:
            resp = await client.post(
                f"{ollama_host}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return (data.get("response") or "").strip()
    except Exception as e:
        logger.warning("Ollama correction failed: %s", e)
        return None


async def correct_utterance(
    utterance: Utterance,
    ollama_host: str = "http://localhost:11434",
    model: str = "mistral-nemo",
) -> Utterance:
    corrected = await _call_ollama(utterance.raw_text, ollama_host, model)
    if corrected:
        corrected = restore_protected_tokens(utterance.raw_text, corrected)
        utterance.corrected_text = corrected
    else:
        utterance.corrected_text = utterance.raw_text
    return utterance


async def correct_utterances_batch(
    utterances: List[Utterance],
    batch_size: int = 10,
    max_concurrent: int = 4,
    ollama_host: str = "http://localhost:11434",
    model: str = "mistral-nemo",
) -> List[Utterance]:
    """Correct utterances in batches with concurrency limit."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def correct_one(utt: Utterance) -> Utterance:
        async with semaphore:
            return await correct_utterance(utt, ollama_host, model)

    results: List[Utterance] = []
    for i in range(0, len(utterances), batch_size):
        batch = utterances[i : i + batch_size]
        corrected_batch = await asyncio.gather(*[correct_one(u) for u in batch])
        results.extend(corrected_batch)

    return results


def get_utterance_text(utterance: Utterance) -> str:
    return utterance.corrected_text or utterance.raw_text
