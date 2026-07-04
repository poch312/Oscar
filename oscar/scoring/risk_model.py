"""Combine the independent per-acta signals into one explainable risk report.

Per the project's central design principle, this does NOT collapse everything
into a single opaque number: each signal (metadata, arithmetic, tamper) stays
visible in the output, and the composite risk_level is a simple, auditable
rule over them — not a learned/black-box combination.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oscar.consistency.arithmetic_check import ArithmeticCheckResult
from oscar.io.metadata_hash import PdfMetadataReport
from oscar.tamper.score import TamperAssessment


@dataclass
class RiskInputs:
    mesa_id: str
    arithmetic: ArithmeticCheckResult
    tamper: TamperAssessment
    metadata: PdfMetadataReport | None = None
    table_needs_review: bool = False
    ocr_needs_review: bool = False
    duplicate_of: list[str] = field(default_factory=list)


@dataclass
class MesaRiskReport:
    mesa_id: str
    risk_level: str  # "low" | "medium" | "high"
    needs_manual_review: bool
    reasons: list[str]
    arithmetic: ArithmeticCheckResult
    tamper: TamperAssessment
    metadata: PdfMetadataReport | None


def compute_risk(inputs: RiskInputs) -> MesaRiskReport:
    reasons: list[str] = []
    risk_level = "low"
    needs_review = False

    critical_arithmetic = [f for f in inputs.arithmetic.flags if f.severity == "critical"]
    if critical_arithmetic:
        risk_level = "high"
        needs_review = True
        reasons.extend(f.code for f in critical_arithmetic)

    if inputs.duplicate_of:
        risk_level = "high"
        needs_review = True
        reasons.append(f"duplicate_image_of:{','.join(inputs.duplicate_of)}")

    if inputs.tamper.is_flagged:
        risk_level = "high" if risk_level != "high" else risk_level
        risk_level = "medium" if risk_level == "low" else risk_level
        needs_review = True
        reasons.append("tamper_score_above_calibrated_threshold")

    if inputs.metadata is not None:
        if inputs.metadata.incremental_update_count > 0:
            risk_level = "medium" if risk_level == "low" else risk_level
            reasons.append(f"pdf_incremental_updates:{inputs.metadata.incremental_update_count}")
        if inputs.metadata.has_suspicious_mod_after_creation:
            reasons.append("pdf_mod_date_differs_from_creation")

    if inputs.table_needs_review or inputs.ocr_needs_review:
        needs_review = True
        reasons.append("low_confidence_extraction")

    warning_arithmetic = [f for f in inputs.arithmetic.flags if f.severity == "warning"]
    if warning_arithmetic and risk_level == "low":
        risk_level = "medium"
    reasons.extend(f.code for f in warning_arithmetic if f.code not in reasons)

    return MesaRiskReport(
        mesa_id=inputs.mesa_id,
        risk_level=risk_level,
        needs_manual_review=needs_review,
        reasons=reasons,
        arithmetic=inputs.arithmetic,
        tamper=inputs.tamper,
        metadata=inputs.metadata,
    )
