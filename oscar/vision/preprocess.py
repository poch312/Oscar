"""Deskew, denoise, binarize, and orientation-correct a scanned acta page.

Runs before table_detection.py so the line/contour detection there sees a
clean, upright, roughly-axis-aligned image regardless of how the mesa's scan
was originally oriented.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=10)


def binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 25, 15
    )


_MAX_PLAUSIBLE_SKEW_DEG = 15.0


def estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate the small (sub-90-degree) skew angle in degrees via minAreaRect on text pixels.

    minAreaRect over a whole page's scattered ink (table lines + multiple text
    blocks, not one tight blob) is only reliable for a genuine few-degree
    scanner tilt; on a square-ish/ambiguous point cloud it can return a
    near-90-degree angle that would wrongly rotate an already-upright page.
    Real large rotations (90/180/270) are handled separately by
    correct_orientation, so any estimate outside a plausible small-tilt range
    is treated as noise and ignored rather than applied.
    """
    inv = cv2.bitwise_not(binarize(gray))
    coords = cv2.findNonZero(inv)
    if coords is None:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    angle = -angle
    return angle if abs(angle) <= _MAX_PLAUSIBLE_SKEW_DEG else 0.0


def rotate(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    if abs(angle_degrees) < 0.05:
        return image
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    border_value = 255 if image.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(
        image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value,
    )


def correct_orientation(image: np.ndarray) -> tuple[np.ndarray, int]:
    """Correct 90/180/270-degree orientation using Tesseract's orientation detection (OSD).

    Returns the corrected image and the rotation applied (0/90/180/270). Falls
    back to (image, 0) if OSD cannot determine orientation confidently (e.g.
    too little text, common on a mostly-blank or low-quality scan).
    """
    try:
        osd = pytesseract.image_to_osd(image)
        rotate_deg = int([line for line in osd.splitlines() if "Rotate:" in line][0].split(":")[1])
    except Exception:
        return image, 0

    if rotate_deg == 0:
        return image, 0

    rot_map = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    code = rot_map.get(rotate_deg)
    if code is None:
        return image, 0
    return cv2.rotate(image, code), rotate_deg


@dataclass
class PreprocessResult:
    gray: np.ndarray
    binary: np.ndarray
    skew_angle_deg: float
    orientation_correction_deg: int


def preprocess(image: np.ndarray) -> PreprocessResult:
    oriented, orientation_correction = correct_orientation(image)
    gray = to_grayscale(oriented)
    gray = denoise(gray)
    skew_angle = estimate_skew_angle(gray)
    gray = rotate(gray, skew_angle)
    binary = binarize(gray)
    return PreprocessResult(
        gray=gray,
        binary=binary,
        skew_angle_deg=skew_angle,
        orientation_correction_deg=orientation_correction,
    )
