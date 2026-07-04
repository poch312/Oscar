import numpy as np

from oscar.config import OCRConfig
from oscar.ocr.engines import OCRResult
from oscar.ocr.ensemble import read_digit_cell


class _FixedEngine:
    def __init__(self, text: str, confidence: float, name: str = "fixed"):
        self._text, self._confidence, self._name = text, confidence, name

    def read(self, image: np.ndarray) -> OCRResult:
        return OCRResult(text=self._text, confidence=self._confidence, engine=self._name)


_DUMMY_IMAGE = np.zeros((10, 10), dtype=np.uint8)


def test_agreement_between_engines_is_not_flagged():
    result = read_digit_cell(_DUMMY_IMAGE, _FixedEngine("45", 0.8), _FixedEngine("45", 0.7), OCRConfig())
    assert result.text == "45"
    assert result.agreement is True
    assert not result.needs_review


def test_disagreement_flags_for_review():
    result = read_digit_cell(_DUMMY_IMAGE, _FixedEngine("45", 0.9), _FixedEngine("48", 0.5), OCRConfig())
    assert result.agreement is False
    assert result.needs_review
    assert result.text == "45"  # higher-confidence engine wins


def test_only_one_engine_reads_digits():
    result = read_digit_cell(_DUMMY_IMAGE, _FixedEngine("", 0.0), _FixedEngine("12", 0.6), OCRConfig())
    assert result.text == "12"
    assert result.agreement is None


def test_neither_engine_reads_digits_flags_review():
    result = read_digit_cell(_DUMMY_IMAGE, _FixedEngine("", 0.0), _FixedEngine("", 0.0), OCRConfig())
    assert result.text == ""
    assert result.needs_review
