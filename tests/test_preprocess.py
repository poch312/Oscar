import cv2
import numpy as np

from oscar.vision.preprocess import estimate_skew_angle


def _page_with_table_and_text(width=900, height=1200):
    """A synthetic upright page: grid lines + scattered text-like ink blobs,
    the shape that previously made minAreaRect misfire (see regression below).
    """
    img = np.full((height, width), 255, dtype=np.uint8)
    for y in (50, 300, 550, 800, 1050):
        cv2.line(img, (0, y), (width - 1, y), 0, thickness=3)
    for x in (50, 400, 650, 850):
        cv2.line(img, (x, 0), (x, height - 1), 0, thickness=3)
    rng = np.random.default_rng(0)
    for _ in range(40):
        x, y = rng.integers(60, width - 60), rng.integers(60, height - 60)
        cv2.putText(img, "Candidato", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 2)
    return img


def test_upright_scattered_content_is_not_misread_as_90_degree_skew():
    """Regression test: minAreaRect over a whole page's scattered ink can
    degenerate to a near-90-degree angle even when the page is upright;
    estimate_skew_angle must not blindly report that as real skew."""
    img = _page_with_table_and_text()
    angle = estimate_skew_angle(img)
    assert abs(angle) <= 15.0


def test_blank_page_returns_zero_skew():
    blank = np.full((200, 300), 255, dtype=np.uint8)
    assert estimate_skew_angle(blank) == 0.0
