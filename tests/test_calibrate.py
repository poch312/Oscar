import pytest

from oscar.tamper.calibrate import compute_calibration, load_calibration, save_calibration


def test_too_few_reference_scores_raises():
    with pytest.raises(ValueError):
        compute_calibration([0.1, 0.2])


def test_calibration_threshold_is_a_high_percentile():
    scores = [0.05 * i for i in range(20)]  # 0.0, 0.05, ..., 0.95
    calibration = compute_calibration(scores, percentile=95.0)
    assert calibration.threshold >= max(scores) * 0.9
    assert calibration.n_reference_images == 20
    assert calibration.advisory_only is True


def test_save_and_load_roundtrip(tmp_path):
    scores = [0.1 * i for i in range(10)]
    calibration = compute_calibration(scores, percentile=90.0)
    path = tmp_path / "calibration.json"
    save_calibration(calibration, path)

    loaded = load_calibration(path)
    assert loaded.threshold == calibration.threshold
    assert loaded.n_reference_images == calibration.n_reference_images
