"""Phase 2+: cross-check OCR-extracted acta values against the Registraduría's
own published digitized results (preconteo/escrutinio) for the same mesa.

Not wired into the Fase 0 MVP pipeline yet — blocked on the user sourcing a
structured, mesa-keyed download of that official dataset (a code/data
availability blocker, not a design blocker; see docs plan §Hoja de ruta).

This check is the only one that can catch transcription/transmission fraud
between the physical acta and the system of record; it cannot catch fraud
that happened before the acta was signed (that's the statistics/ layer's job).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from rapidfuzz import process

from oscar.consistency.arithmetic_check import MesaExtraction


@dataclass
class CrossCheckResult:
    mesa_id: str
    matched_official_mesa_id: str | None
    match_score: float
    discrepancies: dict[str, tuple[int | None, int | None]]  # field -> (acta_value, official_value)

    @property
    def has_discrepancy(self) -> bool:
        return any(acta != official for acta, official in self.discrepancies.values())


def load_official_results(path: str) -> pd.DataFrame:
    """Load a Registraduría preconteo/escrutinio export.

    Expected columns (adjust once a real export is available):
    mesa_id, candidate_name, votes, total_votes.
    """
    return pd.read_csv(path)


def crosscheck_mesa(
    extraction: MesaExtraction, official: pd.DataFrame, mesa_id_column: str = "mesa_id"
) -> CrossCheckResult:
    """Fuzzy-match the extraction's mesa id against the official dataset (formats
    may differ between the OCR'd acta and the official export) and diff totals.
    """
    candidates = official[mesa_id_column].astype(str).tolist()
    match = process.extractOne(str(extraction.mesa_id), candidates) if candidates else None

    if match is None or match[1] < 90:
        return CrossCheckResult(
            mesa_id=extraction.mesa_id, matched_official_mesa_id=None, match_score=0.0, discrepancies={}
        )

    matched_id, score, _ = match
    official_row = official[official[mesa_id_column].astype(str) == matched_id].iloc[0]
    official_total = int(official_row["total_votes"]) if "total_votes" in official_row else None

    discrepancies = {"total_votes": (extraction.total_votes, official_total)}
    return CrossCheckResult(
        mesa_id=extraction.mesa_id,
        matched_official_mesa_id=matched_id,
        match_score=score / 100.0,
        discrepancies=discrepancies,
    )
