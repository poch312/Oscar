from oscar.consistency.arithmetic_check import CandidateVote, MesaExtraction, check_arithmetic


def _extraction(**overrides) -> MesaExtraction:
    defaults = dict(
        mesa_id="001",
        candidates=[CandidateVote("A", 50, 0.9), CandidateVote("B", 30, 0.9)],
        total_votes=80,
        total_votes_words=None,
        blank_votes=0,
        null_votes=0,
        registered_voters=200,
    )
    defaults.update(overrides)
    return MesaExtraction(**defaults)


def test_consistent_extraction_has_no_critical_flags():
    result = check_arithmetic(_extraction())
    assert result.is_consistent
    assert result.computed_total == 80


def test_sum_mismatch_is_critical():
    result = check_arithmetic(_extraction(total_votes=999))
    assert not result.is_consistent
    assert any(f.code == "sum_mismatch" for f in result.flags)


def test_total_exceeds_census_is_critical():
    result = check_arithmetic(_extraction(registered_voters=10))
    assert not result.is_consistent
    assert any(f.code == "total_exceeds_census" for f in result.flags)


def test_missing_candidate_votes_is_warning_not_critical():
    extraction = _extraction(candidates=[CandidateVote("A", 50, 0.9), CandidateVote("B", None, 0.0)])
    result = check_arithmetic(extraction)
    assert any(f.code == "missing_candidate_votes" and f.severity == "warning" for f in result.flags)
    # sum_mismatch should NOT fire when candidates are missing (nothing to compare)
    assert not any(f.code == "sum_mismatch" for f in result.flags)


def test_digits_words_match_and_mismatch():
    consistent = check_arithmetic(_extraction(total_votes=80, total_votes_words="ochenta"))
    assert consistent.is_consistent

    inconsistent = check_arithmetic(_extraction(total_votes=80, total_votes_words="setenta"))
    assert any(f.code == "digits_words_mismatch" for f in inconsistent.flags)
