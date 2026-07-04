"""Noise-residual stream: a simplified Spatial Rich Model (SRM)-style high-pass
filter bank, following the "noise stream" half of the two-stream tamper
detection architecture (arxiv.org/pdf/1803.11276): splicing/editing disturbs
the sensor/compression noise pattern even when it's invisible to the eye.
"""

from __future__ import annotations

import cv2
import numpy as np

# A small subset of the classic SRM high-pass kernels (Fridrich & Kodovsky),
# not the full 30-kernel bank — sufficient as a second CNN input stream.
_SRM_KERNELS = [
    np.array([[0, 0, 0], [0, -1, 1], [0, 0, 0]], dtype=np.float32),
    np.array([[0, 0, 0], [0, -1, 0], [0, 1, 0]], dtype=np.float32),
    np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], dtype=np.float32) / 4.0,
    np.array([[0, -1, 0], [-1, 4, -1], [0, -1, 0]], dtype=np.float32) / 4.0,
]


def compute_noise_residual(image: np.ndarray) -> np.ndarray:
    """Apply the SRM-style kernel bank to a grayscale/RGB image, returning a
    stacked (H, W, len(kernels)) residual map.
    """
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image
    gray = gray.astype(np.float32)

    residuals = [cv2.filter2D(gray, -1, kernel) for kernel in _SRM_KERNELS]
    stacked = np.stack(residuals, axis=-1)
    return np.clip(np.abs(stacked), 0, 255).astype(np.uint8)
