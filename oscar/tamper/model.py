"""Two-stream CNN for acta tamper detection (PyTorch), architecture inspired by:
- the semantic + noise-residual two-stream design (arxiv.org/pdf/1803.11276)
- the ELA+CNN pipelines in aws-samples/document-tampering-detection,
  harshita3002/imageforgeryDetection, KulkarniShrinivas/Image-Forgery-Detection

Reimplemented from scratch in PyTorch per the project's framework decision —
no code ported from those (TensorFlow/Keras) repos, only the architectural
pattern.

Untrained out of the box: weights are produced by scripts/train_tamper_model.py
against CASIA 2.0 (see oscar.tamper.dataset), then the *decision threshold*
(not the model) is calibrated per-deployment via oscar.tamper.calibrate.
"""

from __future__ import annotations

import torch
from torch import nn


class _StreamEncoder(nn.Module):
    """Small conv backbone shared by both streams (kept lightweight since input
    is a per-cell/per-region crop, not a full-resolution page)."""

    def __init__(self, in_channels: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.features(x).flatten(1)


class TwoStreamTamperNet(nn.Module):
    """Stream A: RGB + ELA residual (4 channels). Stream B: noise-residual bank
    (n_noise_channels). Fused through a small classifier head -> tamper logit.
    """

    def __init__(self, n_noise_channels: int = 4) -> None:
        super().__init__()
        self.semantic_stream = _StreamEncoder(in_channels=4)  # RGB (3) + ELA (1, grayscale)
        self.noise_stream = _StreamEncoder(in_channels=n_noise_channels)
        self.classifier = nn.Sequential(
            nn.Linear(128 + 128, 64),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
        )

    def forward(self, semantic_input: torch.Tensor, noise_input: torch.Tensor) -> torch.Tensor:
        semantic_features = self.semantic_stream(semantic_input)
        noise_features = self.noise_stream(noise_input)
        fused = torch.cat([semantic_features, noise_features], dim=1)
        return self.classifier(fused).squeeze(-1)  # raw logit; caller applies sigmoid

    def predict_proba(self, semantic_input: torch.Tensor, noise_input: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            logit = self.forward(semantic_input, noise_input)
            return torch.sigmoid(logit)


def load_model(checkpoint_path: str | None, n_noise_channels: int = 4) -> TwoStreamTamperNet:
    """Load a trained checkpoint, or return a randomly-initialized model if
    none exists yet (Fase 0: model.py is buildable/testable before real
    training data exists; see oscar.tamper.score for the "no checkpoint"
    honesty framing surfaced to the report).
    """
    model = TwoStreamTamperNet(n_noise_channels=n_noise_channels)
    if checkpoint_path:
        state_dict = torch.load(checkpoint_path, map_location="cpu")
        model.load_state_dict(state_dict)
    model.eval()
    return model
