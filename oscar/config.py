"""Tunables shared across the pipeline: paths, thresholds, DPI, engine choices."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OCRConfig:
    primary_engine: str = "paddleocr"
    fallback_engine: str = "tesseract"
    tesseract_digit_config: str = "-c tessedit_char_whitelist=0123456789 --psm 6"
    min_confidence: float = 0.55


@dataclass
class TableDetectionConfig:
    min_line_length_frac: float = 0.3
    morph_kernel_frac: float = 0.02
    min_cell_confidence: float = 0.5


@dataclass
class TamperConfig:
    model_path: Path = Path("models/casia_pretrained.pt")
    calibration_path: Path = Path("models/calibration.json")
    calibration_percentile: float = 95.0
    ela_quality: int = 90


@dataclass
class PipelineConfig:
    dpi: int = 300
    ocr: OCRConfig = field(default_factory=OCRConfig)
    table: TableDetectionConfig = field(default_factory=TableDetectionConfig)
    tamper: TamperConfig = field(default_factory=TamperConfig)
