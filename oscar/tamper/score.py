"""Inference wrapper: image -> calibrated tamper probability/flag.

This is the module the pipeline actually calls; it owns the "experimental,
advisory-only" framing so no caller can accidentally present a raw model
score as a fraud determination.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from oscar.io.pdf_ingest import PageImage
from oscar.tamper.calibrate import Calibration, load_calibration
from oscar.tamper.ela import compute_ela
from oscar.tamper.model import TwoStreamTamperNet, load_model
from oscar.tamper.noise_residual import compute_noise_residual


@dataclass
class TamperAssessment:
    score: float | None
    is_flagged: bool | None
    threshold: float | None
    ela_meaningful: bool
    note: str


def _prepare_inputs(image: Image.Image, image_size: int = 256) -> tuple[torch.Tensor, torch.Tensor]:
    resized = image.convert("RGB").resize((image_size, image_size))
    ela = compute_ela(resized)
    ela_gray = np.asarray(Image.fromarray(ela).convert("L"))
    semantic = np.concatenate([np.asarray(resized), ela_gray[..., None]], axis=-1)
    noise = compute_noise_residual(np.asarray(resized))

    semantic_tensor = torch.from_numpy(semantic).permute(2, 0, 1).float().unsqueeze(0) / 255.0
    noise_tensor = torch.from_numpy(noise).permute(2, 0, 1).float().unsqueeze(0) / 255.0
    return semantic_tensor, noise_tensor


class TamperScorer:
    def __init__(
        self,
        model_path: str | Path | None = None,
        calibration_path: str | Path | None = None,
    ) -> None:
        self._model: TwoStreamTamperNet | None = None
        self._model_path = Path(model_path) if model_path else None
        self._calibration: Calibration | None = None
        self._calibration_path = Path(calibration_path) if calibration_path else None

    def _ensure_model(self) -> TwoStreamTamperNet | None:
        if self._model is not None:
            return self._model
        if self._model_path is None or not self._model_path.exists():
            return None
        self._model = load_model(str(self._model_path))
        return self._model

    def _ensure_calibration(self) -> Calibration | None:
        if self._calibration is not None:
            return self._calibration
        if self._calibration_path is None or not self._calibration_path.exists():
            return None
        self._calibration = load_calibration(self._calibration_path)
        return self._calibration

    def raw_score(self, image: Image.Image) -> float:
        model = self._ensure_model()
        if model is None:
            raise RuntimeError(
                "No hay checkpoint del modelo de manipulación entrenado todavía "
                "(ver scripts/train_tamper_model.py)."
            )
        semantic_tensor, noise_tensor = _prepare_inputs(image)
        with torch.no_grad():
            proba = model.predict_proba(semantic_tensor, noise_tensor)
        return float(proba.item())

    def assess(self, page_image: PageImage) -> TamperAssessment:
        if not page_image.ela_meaningful:
            return TamperAssessment(
                score=None,
                is_flagged=None,
                threshold=None,
                ela_meaningful=False,
                note=(
                    f"Imagen embebida con compresión '{page_image.compression_filter}': "
                    "ELA no es significativo para este tipo de compresión (no-JPEG). "
                    "Puntaje de manipulación no disponible para esta acta."
                ),
            )

        model = self._ensure_model()
        if model is None:
            return TamperAssessment(
                score=None, is_flagged=None, threshold=None, ela_meaningful=True,
                note="Modelo de manipulación no entrenado todavía; ejecutar scripts/train_tamper_model.py.",
            )

        score = self.raw_score(page_image.image)
        calibration = self._ensure_calibration()
        if calibration is None:
            return TamperAssessment(
                score=score, is_flagged=None, threshold=None, ela_meaningful=True,
                note=(
                    "Puntaje sin calibrar (falta `oscar calibrate --reference-genuine-dir ...`): "
                    "no se puede interpretar como bandera de riesgo todavía."
                ),
            )

        is_flagged = score >= calibration.threshold
        return TamperAssessment(
            score=score,
            is_flagged=is_flagged,
            threshold=calibration.threshold,
            ela_meaningful=True,
            note=(
                "Puntaje experimental/orientativo, no es una determinación de fraude. "
                f"Calibrado con {calibration.n_reference_images} actas genuinas de referencia."
            ),
        )
