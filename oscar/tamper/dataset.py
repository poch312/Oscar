"""CASIA 1.0/2.0 dataset loader for pretraining the two-stream tamper model.

Expects the directory layout produced by scripts/download_casia.py:
    <root>/authentic/*.jpg
    <root>/tampered/*.jpg
(CASIA 2.0's ground-truth masks are not required for a binary
tampered/authentic classifier and are ignored here; a future
region-localization model could consume them from
oscar.tamper.dataset without changing this class's interface.)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

from oscar.tamper.ela import compute_ela
from oscar.tamper.noise_residual import compute_noise_residual

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


class CasiaTamperDataset(Dataset):
    def __init__(self, root: str | Path, image_size: int = 128) -> None:
        root = Path(root)
        self.image_size = image_size
        self.samples: list[tuple[Path, int]] = []
        for label, subdir in ((0, "authentic"), (1, "tampered")):
            for path in sorted((root / subdir).glob("*")):
                if path.suffix.lower() in _IMAGE_EXTENSIONS:
                    self.samples.append((path, label))
        if not self.samples:
            raise FileNotFoundError(
                f"No images found under {root}/authentic or {root}/tampered — "
                "run scripts/download_casia.py first."
            )

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        path, label = self.samples[index]
        image = Image.open(path).convert("RGB").resize((self.image_size, self.image_size))

        ela = compute_ela(image)
        ela_gray = np.asarray(Image.fromarray(ela).convert("L"))
        semantic = np.concatenate([np.asarray(image), ela_gray[..., None]], axis=-1)  # H,W,4

        noise = compute_noise_residual(np.asarray(image))  # H,W,4

        semantic_tensor = torch.from_numpy(semantic).permute(2, 0, 1).float() / 255.0
        noise_tensor = torch.from_numpy(noise).permute(2, 0, 1).float() / 255.0
        label_tensor = torch.tensor(label, dtype=torch.float32)
        return semantic_tensor, noise_tensor, label_tensor
