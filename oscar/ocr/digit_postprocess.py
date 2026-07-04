"""Clean up raw OCR digit strings and cross-check digits against a written-out
words field (E14 forms record vote counts both as digits and in words).
"""

from __future__ import annotations

import re

# Common OCR digit confusions seen with handwritten/printed forms.
_CONFUSION_MAP = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})

_UNITS = {
    "cero": 0, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_TENS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90,
}
_HUNDREDS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600, "setecientos": 700,
    "ochocientos": 800, "novecientos": 900,
}


def clean_digit_string(raw: str) -> str:
    """Strip non-digit noise and correct common letter/digit confusions."""
    corrected = raw.translate(_CONFUSION_MAP)
    return re.sub(r"[^0-9]", "", corrected)


def _strip_accents(text: str) -> str:
    replacements = str.maketrans("áéíóúñ", "aeioun")
    return text.translate(replacements)


def words_to_number(text: str) -> int | None:
    """Best-effort parser for Spanish number words up to a few thousand.

    Covers the range realistically needed for a single mesa's vote counts
    (typically well under ~1000 registered voters). Returns None if the text
    doesn't parse as a number, rather than guessing.
    """
    text = _strip_accents(text.strip().lower())
    text = re.sub(r"\by\b", " ", text)  # "cien y veinte" style joiners, if present
    tokens = [t for t in re.split(r"[\s-]+", text) if t]
    if not tokens:
        return None

    total = 0
    remainder_thousand = 0
    i = 0
    matched_any = False
    while i < len(tokens):
        token = tokens[i]
        if token == "mil":
            remainder_thousand = (remainder_thousand or 1) * 1000
            total += remainder_thousand
            remainder_thousand = 0
            matched_any = True
        elif token in _HUNDREDS:
            remainder_thousand += _HUNDREDS[token]
            matched_any = True
        elif token in _TENS:
            remainder_thousand += _TENS[token]
            matched_any = True
        elif token in _UNITS:
            remainder_thousand += _UNITS[token]
            matched_any = True
        i += 1

    total += remainder_thousand
    return total if matched_any else None


def digits_match_words(digit_value: int | None, words_text: str) -> bool | None:
    """Cross-check the digit field against the words field. Returns None (not
    False) when the words field can't be parsed, so callers don't treat an
    unparseable words field as a mismatch.
    """
    if digit_value is None:
        return None
    words_value = words_to_number(words_text)
    if words_value is None:
        return None
    return digit_value == words_value
