"""Threshold calibration using a handful of known-genuine reference actas.

Implements the DOCFORGE-BENCH-inspired idea the user supplied: because
manipulated regions in documents are a tiny fraction of pixels, an
off-the-shelf tamper-model threshold performs poorly on this domain unless
recalibrated using ~10 reference genuine documents from the *actual*
deployment distribution (real acta scans, not CASIA's natural photos).

IMPORTANT — this only moves a decision threshold on the existing model's
score distribution. It does not, and cannot, correct for the model having
learned natural-photo-splicing features that may not transfer to document
tampering. Treat any resulting flag as advisory, not a fraud determination
(see docs/architecture.md risks section).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Calibration:
    threshold: float
    percentile: float
    n_reference_images: int
    reference_score_mean: float
    reference_score_std: float
    calibrated_at: str
    advisory_only: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def compute_calibration(reference_scores: list[float], percentile: float = 95.0) -> Calibration:
    if len(reference_scores) < 3:
        raise ValueError(
            f"Se requieren al menos ~10 actas genuinas de referencia para calibrar "
            f"(recibidas: {len(reference_scores)}); con muy pocas, el umbral no es confiable."
        )
    sorted_scores = sorted(reference_scores)
    index = min(int(len(sorted_scores) * percentile / 100.0), len(sorted_scores) - 1)
    threshold = sorted_scores[index]
    mean = sum(reference_scores) / len(reference_scores)
    variance = sum((s - mean) ** 2 for s in reference_scores) / len(reference_scores)
    return Calibration(
        threshold=threshold,
        percentile=percentile,
        n_reference_images=len(reference_scores),
        reference_score_mean=mean,
        reference_score_std=variance ** 0.5,
        calibrated_at=datetime.now(timezone.utc).isoformat(),
    )


def save_calibration(calibration: Calibration, path: str | Path) -> None:
    Path(path).write_text(calibration.to_json())


def load_calibration(path: str | Path) -> Calibration:
    data = json.loads(Path(path).read_text())
    return Calibration(**data)
