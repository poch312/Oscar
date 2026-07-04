"""Emit per-mesa + batch-summary reports as JSON/CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from oscar.scoring.risk_model import MesaRiskReport


def _report_to_dict(report: MesaRiskReport) -> dict:
    return {
        "mesa_id": report.mesa_id,
        "risk_level": report.risk_level,
        "needs_manual_review": report.needs_manual_review,
        "reasons": report.reasons,
        "arithmetic": {
            "computed_total": report.arithmetic.computed_total,
            "is_consistent": report.arithmetic.is_consistent,
            "flags": [
                {"code": f.code, "message": f.message, "severity": f.severity}
                for f in report.arithmetic.flags
            ],
        },
        "tamper": {
            "score": report.tamper.score,
            "is_flagged": report.tamper.is_flagged,
            "threshold": report.tamper.threshold,
            "ela_meaningful": report.tamper.ela_meaningful,
            "note": report.tamper.note,
        },
        "metadata": (
            {
                "producer": report.metadata.producer,
                "creator": report.metadata.creator,
                "incremental_update_count": report.metadata.incremental_update_count,
                "has_suspicious_mod_after_creation": report.metadata.has_suspicious_mod_after_creation,
            }
            if report.metadata is not None
            else None
        ),
    }


def write_json_report(reports: list[MesaRiskReport], path: str | Path) -> None:
    payload = {
        "n_mesas": len(reports),
        "n_flagged_for_review": sum(r.needs_manual_review for r in reports),
        "n_high_risk": sum(r.risk_level == "high" for r in reports),
        "mesas": [_report_to_dict(r) for r in reports],
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def write_csv_report(reports: list[MesaRiskReport], path: str | Path) -> None:
    fieldnames = [
        "mesa_id", "risk_level", "needs_manual_review", "reasons",
        "computed_total", "is_consistent", "tamper_score", "tamper_flagged",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            writer.writerow({
                "mesa_id": r.mesa_id,
                "risk_level": r.risk_level,
                "needs_manual_review": r.needs_manual_review,
                "reasons": ";".join(r.reasons),
                "computed_total": r.arithmetic.computed_total,
                "is_consistent": r.arithmetic.is_consistent,
                "tamper_score": r.tamper.score,
                "tamper_flagged": r.tamper.is_flagged,
            })
