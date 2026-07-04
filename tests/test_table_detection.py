import cv2
import numpy as np

from oscar.config import TableDetectionConfig
from oscar.vision.table_detection import detect_table_grid


def _synthetic_grid_binary(width=300, height=200, rows_y=(0, 50, 100, 150, 199), cols_x=(0, 100, 200, 299)):
    """White background (255) with black (0) grid lines, matching the output
    format of oscar.vision.preprocess.binarize (dark ink on light background)."""
    img = np.full((height, width), 255, dtype=np.uint8)
    for y in rows_y:
        cv2.line(img, (0, y), (width - 1, y), 0, thickness=2)
    for x in cols_x:
        cv2.line(img, (x, 0), (x, height - 1), 0, thickness=2)
    return img


def test_detects_clean_grid_shape():
    binary = _synthetic_grid_binary()
    grid = detect_table_grid(binary, TableDetectionConfig())
    assert grid.n_rows == 4
    assert grid.n_cols == 3
    assert not grid.needs_review
    assert len(grid.cells) == 4 * 3


def test_blank_image_flags_needs_review():
    blank = np.full((200, 300), 255, dtype=np.uint8)
    grid = detect_table_grid(blank, TableDetectionConfig())
    assert grid.needs_review
    assert grid.review_reason == "no_grid_lines_detected"
