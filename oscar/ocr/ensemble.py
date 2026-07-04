"""Combine the primary (PaddleOCR) and fallback (Tesseract) engines per cell.

Agreement between two independent engines is itself a confidence signal: if
both read the same digits, trust it; if they disagree, flag for human review
rather than silently picking one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from oscar.config import OCRConfig
from oscar.ocr.digit_postprocess import clean_digit_string
from oscar.ocr.engines import OCREngine, OCRResult


@dataclass
class EnsembleResult:
    text: str
    confidence: float
    agreement: bool | None
    needs_review: bool
    results: list[OCRResult]


def _safe_read(engine: OCREngine, image: np.ndarray) -> OCRResult:
    """A single engine failing (e.g. PaddleOCR model download unavailable in
    this deployment) should degrade that cell's read, not crash the batch."""
    try:
        return engine.read(image)
    except Exception as exc:
        return OCRResult(text="", confidence=0.0, engine=f"{type(engine).__name__}_error:{exc}")


def read_digit_cell(
    image: np.ndarray, primary: OCREngine, fallback: OCREngine, config: OCRConfig | None = None
) -> EnsembleResult:
    config = config or OCRConfig()
    primary_result = _safe_read(primary, image)
    fallback_result = _safe_read(fallback, image)

    primary_digits = clean_digit_string(primary_result.text)
    fallback_digits = clean_digit_string(fallback_result.text)

    if primary_digits and primary_digits == fallback_digits:
        return EnsembleResult(
            text=primary_digits,
            confidence=max(primary_result.confidence, fallback_result.confidence),
            agreement=True,
            needs_review=False,
            results=[primary_result, fallback_result],
        )

    if primary_digits and fallback_digits and primary_digits != fallback_digits:
        best = primary_result if primary_result.confidence >= fallback_result.confidence else fallback_result
        best_digits = primary_digits if best is primary_result else fallback_digits
        return EnsembleResult(
            text=best_digits,
            confidence=best.confidence,
            agreement=False,
            needs_review=True,
            results=[primary_result, fallback_result],
        )

    # Only one engine (or neither) produced digits.
    text = primary_digits or fallback_digits
    confidence = primary_result.confidence if primary_digits else fallback_result.confidence
    return EnsembleResult(
        text=text,
        confidence=confidence,
        agreement=None,
        needs_review=(not text) or confidence < config.min_confidence,
        results=[primary_result, fallback_result],
    )


def read_text_cell(image: np.ndarray, engine: OCREngine) -> EnsembleResult:
    """For free-text cells (candidate names) a single general-purpose engine is used —
    voting doesn't generalize well to open-vocabulary text the way it does for digits."""
    result = _safe_read(engine, image)
    return EnsembleResult(
        text=result.text,
        confidence=result.confidence,
        agreement=None,
        needs_review=result.confidence < 0.5,
        results=[result],
    )
