import numpy as np

from oscar.statistics.digit_heuristics import benford_first_digit_test, last_digit_uniformity_test


def test_insufficient_n_returns_none():
    assert benford_first_digit_test([123, 456]) is None
    assert last_digit_uniformity_test([123, 456]) is None


def test_benford_compliant_data_not_flagged():
    rng = np.random.default_rng(42)
    # Sample from a log-uniform distribution over [1, 10000): satisfies Benford's law.
    values = (10 ** rng.uniform(0, 4, size=2000)).astype(int)
    result = benford_first_digit_test(list(values))
    assert result is not None
    assert not result.flagged


def test_all_same_first_digit_is_flagged():
    values = [1000 + i for i in range(200)]  # every value starts with digit 1
    result = benford_first_digit_test(values)
    assert result is not None
    assert result.flagged


def test_last_digit_uniform_not_flagged():
    values = list(range(0, 1000))  # last digit cycles 0-9 uniformly
    result = last_digit_uniformity_test(values)
    assert result is not None
    assert not result.flagged


def test_last_digit_all_zero_is_flagged():
    values = [10 * i for i in range(100)]  # every value ends in 0
    result = last_digit_uniformity_test(values)
    assert result is not None
    assert result.flagged
