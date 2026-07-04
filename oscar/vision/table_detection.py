"""Automatic table/cell-grid detection via line morphology + connected components.

Deliberately does NOT use fixed pixel coordinates (per the project's binding
constraint): E14 scans vary in rotation, DPI, and minor layout differences
across ~100k+ mesas, so the grid is detected fresh from each image's own
horizontal/vertical rule lines.

This is flagged in the project plan as the highest-technical-risk module.
When detection confidence is low, cells are marked needs_review rather than
silently returning a low-confidence guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from oscar.config import TableDetectionConfig


@dataclass
class Cell:
    row: int
    col: int
    bbox: tuple[int, int, int, int]  # x, y, w, h in image pixel coordinates
    confidence: float


@dataclass
class TableGrid:
    cells: list[Cell]
    n_rows: int
    n_cols: int
    needs_review: bool
    review_reason: str | None = None


def _line_masks(binary_inv: np.ndarray, config: TableDetectionConfig) -> tuple[np.ndarray, np.ndarray]:
    h, w = binary_inv.shape
    horiz_len = max(int(w * config.morph_kernel_frac), 5)
    vert_len = max(int(h * config.morph_kernel_frac), 5)

    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horiz_len, 1))
    horizontal = cv2.erode(binary_inv, horiz_kernel)
    horizontal = cv2.dilate(horizontal, horiz_kernel)

    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vert_len))
    vertical = cv2.erode(binary_inv, vert_kernel)
    vertical = cv2.dilate(vertical, vert_kernel)

    return horizontal, vertical


def _cluster_positions(positions: list[int], tolerance: int) -> list[int]:
    """Merge nearby coordinate values (e.g. line positions with a few px jitter)."""
    if not positions:
        return []
    positions = sorted(positions)
    clusters: list[list[int]] = [[positions[0]]]
    for pos in positions[1:]:
        if pos - clusters[-1][-1] <= tolerance:
            clusters[-1].append(pos)
        else:
            clusters.append([pos])
    return [int(np.mean(c)) for c in clusters]


def detect_table_grid(binary: np.ndarray, config: TableDetectionConfig | None = None) -> TableGrid:
    """Detect a grid of cells from a binarized (thresholded) page image.

    `binary` is expected to be the output of oscar.vision.preprocess.binarize
    (white background, dark ink) for a single page/region believed to contain
    the E14 vote table.
    """
    config = config or TableDetectionConfig()
    binary_inv = cv2.bitwise_not(binary)

    horizontal, vertical = _line_masks(binary_inv, config)
    grid_mask = cv2.bitwise_or(horizontal, vertical)

    h_positions = _cluster_positions(
        [int(y) for y in np.where(horizontal.sum(axis=1) > horizontal.shape[1] * 0.3 * 255)[0]],
        tolerance=max(binary.shape[0] // 200, 1),
    )
    v_positions = _cluster_positions(
        [int(x) for x in np.where(vertical.sum(axis=0) > vertical.shape[0] * 0.3 * 255)[0]],
        tolerance=max(binary.shape[1] // 200, 1),
    )

    n_rows = max(len(h_positions) - 1, 0)
    n_cols = max(len(v_positions) - 1, 0)

    if n_rows < 1 or n_cols < 1:
        return TableGrid(
            cells=[], n_rows=0, n_cols=0, needs_review=True,
            review_reason="no_grid_lines_detected",
        )

    cells: list[Cell] = []
    min_area = (binary.shape[0] * binary.shape[1]) * 1e-4
    for row in range(n_rows):
        y0, y1 = h_positions[row], h_positions[row + 1]
        for col in range(n_cols):
            x0, x1 = v_positions[col], v_positions[col + 1]
            width, height = x1 - x0, y1 - y0
            area = width * height
            # Confidence: penalize implausibly small/degenerate cells (likely
            # spurious line intersections rather than real table cells).
            confidence = 1.0 if area >= min_area and width > 3 and height > 3 else 0.2
            cells.append(Cell(row=row, col=col, bbox=(x0, y0, width, height), confidence=confidence))

    low_conf_frac = sum(c.confidence < config.min_cell_confidence for c in cells) / len(cells)
    needs_review = low_conf_frac > 0.15 or n_rows < 2 or n_cols < 2
    reason = "too_many_low_confidence_cells" if needs_review and low_conf_frac > 0.15 else (
        "degenerate_grid_shape" if needs_review else None
    )

    return TableGrid(cells=cells, n_rows=n_rows, n_cols=n_cols, needs_review=needs_review, review_reason=reason)


def crop_cell(image: np.ndarray, cell: Cell, padding: int = 2) -> np.ndarray:
    x, y, w, h = cell.bbox
    y0, y1 = max(y + padding, 0), min(y + h - padding, image.shape[0])
    x0, x1 = max(x + padding, 0), min(x + w - padding, image.shape[1])
    return image[y0:y1, x0:x1]
