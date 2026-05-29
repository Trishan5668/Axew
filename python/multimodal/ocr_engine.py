"""
OCR for on-screen text in key frames (English + Hindi).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from python.multimodal.frame_extractor import FrameRecord

logger = logging.getLogger(__name__)

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr

            _reader = easyocr.Reader(["en", "hi"], gpu=False, verbose=False)
            logger.info("Loaded EasyOCR reader")
        except Exception as e:
            _reader = False
            logger.warning("EasyOCR unavailable: %s", e)
    return _reader if _reader is not False else None


@dataclass
class OCRResult:
    timestamp_sec: float
    frame_path: str
    text: str
    confidence: float


def extract_ocr_from_frames(frames: List[FrameRecord], min_confidence: float = 0.4) -> List[OCRResult]:
    reader = _get_reader()
    if reader is None:
        return []

    results: List[OCRResult] = []
    for rec in frames:
        if not rec.is_key_frame:
            continue
        try:
            detections = reader.readtext(rec.frame_path)
            texts = [t[1] for t in detections if t[2] >= min_confidence]
            if texts:
                combined = " ".join(texts)
                avg_conf = sum(t[2] for t in detections if t[2] >= min_confidence) / len(texts)
                results.append(
                    OCRResult(
                        timestamp_sec=rec.timestamp_sec,
                        frame_path=rec.frame_path,
                        text=combined,
                        confidence=avg_conf,
                    )
                )
        except Exception as e:
            logger.warning("OCR failed for %s: %s", rec.frame_path, e)

    return results
