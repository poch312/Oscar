"""Error Level Analysis (ELA): recompress the image at a known JPEG quality and
diff against the original. Regions edited after the original compression
re-compress differently, producing a brighter residual.

Only meaningful for JPEG-family sources (see oscar.io.pdf_ingest.PageImage.ela_meaningful):
CCITT-fax or lossless-encoded scans have no original JPEG compression artifact
for this technique to exploit.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def compute_ela(image: Image.Image, quality: int = 90) -> np.ndarray:
    """Return the per-pixel absolute difference (H, W, 3) between `image` and a
    JPEG-recompressed copy of itself, scaled to use the full 0-255 range.
    """
    rgb = image.convert("RGB")
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    recompressed = Image.open(buffer)

    original_arr = np.asarray(rgb, dtype=np.int16)
    recompressed_arr = np.asarray(recompressed, dtype=np.int16)
    diff = np.abs(original_arr - recompressed_arr)

    max_diff = diff.max()
    scale = 255.0 / max_diff if max_diff > 0 else 1.0
    return (diff * scale).clip(0, 255).astype(np.uint8)
