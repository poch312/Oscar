"""Batch-level digit-distribution heuristics (Benford's law, last-digit
uniformity) — a fast, dependency-free complement to the full Mebane/eforensics
model (oscar.statistics.mebane_bridge).

These are statements about a *distribution across many mesas*, not about a
single acta — a single vote count has no "first-digit distribution" to test.
Feed this module the accumulated per-mesa table from
oscar.statistics.aggregate, not a single extraction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

# Benford's law expected first-digit frequencies (digits 1-9).
_BENFORD_EXPECTED = np.array([np.log10(1 + 1 / d) for d in range(1, 10)])


@dataclass
class DigitTestResult:
    test_name: str
    n_observations: int
    statistic: float
    p_value: float
    flagged: bool  # p_value below alpha => distribution looks anomalous


def _first_digit(n: int) -> int | None:
    n = abs(n)
    while n >= 10:
        n //= 10
    return n if n > 0 else None


def _last_digit(n: int) -> int:
    return abs(n) % 10


def benford_first_digit_test(values: list[int], alpha: float = 0.01) -> DigitTestResult | None:
    """Chi-square goodness-of-fit against Benford's law first-digit distribution.

    Requires a reasonably large N (Benford's law is a population-level
    statement); returns None rather than a misleading result below ~50 values.
    """
    digits = [d for v in values if (d := _first_digit(v)) is not None]
    if len(digits) < 50:
        return None

    observed_counts = np.array([digits.count(d) for d in range(1, 10)])
    expected_counts = _BENFORD_EXPECTED * len(digits)
    statistic, p_value = stats.chisquare(observed_counts, expected_counts)
    return DigitTestResult(
        test_name="benford_first_digit",
        n_observations=len(digits),
        statistic=float(statistic),
        p_value=float(p_value),
        flagged=p_value < alpha,
    )


def last_digit_uniformity_test(values: list[int], alpha: float = 0.01) -> DigitTestResult | None:
    """Chi-square test for uniformity of the last digit (0-9).

    Genuine hand-counted vote totals are expected to have an approximately
    uniform last digit; systematic manipulation (e.g. round-number padding)
    tends to skew this distribution.
    """
    digits = [_last_digit(v) for v in values]
    if len(digits) < 50:
        return None

    observed_counts = np.array([digits.count(d) for d in range(10)])
    expected_counts = np.full(10, len(digits) / 10.0)
    statistic, p_value = stats.chisquare(observed_counts, expected_counts)
    return DigitTestResult(
        test_name="last_digit_uniformity",
        n_observations=len(digits),
        statistic=float(statistic),
        p_value=float(p_value),
        flagged=p_value < alpha,
    )
