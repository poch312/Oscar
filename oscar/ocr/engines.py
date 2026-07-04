"""OCR engine adapters: PaddleOCR (primary, handwritten-digit accuracy) and
Tesseract (fallback, digit-whitelisted) behind one common interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pytesseract

from oscar.config import OCRConfig


@dataclass
class OCRResult:
    text: str
    confidence: float  # 0.0-1.0
    engine: str


class OCREngine(Protocol):
    def read(self, image: np.ndarray) -> OCRResult: ...


class PaddleOCREngine:
    """Lazy-loads PaddleOCR on first use (model download/init is expensive).

    Targets the PaddleOCR 3.x pipeline API (`predict`, dict-like per-page
    results with `rec_texts`/`rec_scores`) rather than the older 2.x
    `ocr(img, cls=True)` list-of-lines API. Doc-orientation/unwarping and
    textline-orientation sub-models are disabled: orientation correction
    already happens in oscar.vision.preprocess, and cells are pre-cropped, so
    those extra models would only add download/inference cost.
    """

    def __init__(self, lang: str = "es") -> None:
        self._lang = lang
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang=self._lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._ocr

    def read(self, image: np.ndarray) -> OCRResult:
        results = self._get_ocr().predict(image)
        if not results:
            return OCRResult(text="", confidence=0.0, engine="paddleocr")
        page = results[0]
        texts = list(page.get("rec_texts", []))
        scores = list(page.get("rec_scores", []))
        return OCRResult(
            text=" ".join(texts).strip(),
            confidence=float(np.mean(scores)) if scores else 0.0,
            engine="paddleocr",
        )


class TesseractDigitEngine:
    """Digit-whitelisted Tesseract, following the pattern from
    supersuyash/electoral-roll-extraction-OCR (`tessedit_char_whitelist` + PSM 6).
    """

    def __init__(self, config: OCRConfig | None = None) -> None:
        self._config = config or OCRConfig()

    def read(self, image: np.ndarray) -> OCRResult:
        data = pytesseract.image_to_data(
            image, config=self._config.tesseract_digit_config, output_type=pytesseract.Output.DICT
        )
        words = [w for w in data["text"] if w.strip()]
        confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
        return OCRResult(
            text="".join(words),
            confidence=(sum(confs) / len(confs) / 100.0) if confs else 0.0,
            engine="tesseract",
        )


class TesseractTextEngine:
    """General-purpose Tesseract (better for names/free text than the digit-whitelisted engine)."""

    def read(self, image: np.ndarray) -> OCRResult:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = [w for w in data["text"] if w.strip()]
        confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
        return OCRResult(
            text=" ".join(words),
            confidence=(sum(confs) / len(confs) / 100.0) if confs else 0.0,
            engine="tesseract_text",
        )
