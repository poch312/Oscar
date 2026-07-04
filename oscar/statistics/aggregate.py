"""Append-only per-mesa results table, the shared input for both
digit_heuristics.py and mebane_bridge.py.

Kept as a plain CSV (not a database) for Fase 0 — this is meant to accumulate
across repeated `oscar audit` runs over the course of election night, so
appends must be idempotent on mesa_id.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from oscar.consistency.arithmetic_check import MesaExtraction

_COLUMNS = [
    "mesa_id", "total_votes", "blank_votes", "null_votes", "registered_voters",
    "is_consistent", "n_candidates",
]


def extraction_to_row(extraction: MesaExtraction, is_consistent: bool) -> dict:
    return {
        "mesa_id": extraction.mesa_id,
        "total_votes": extraction.total_votes,
        "blank_votes": extraction.blank_votes,
        "null_votes": extraction.null_votes,
        "registered_voters": extraction.registered_voters,
        "is_consistent": is_consistent,
        "n_candidates": len(extraction.candidates),
    }


def append_row(store_path: str | Path, row: dict) -> None:
    """Append one mesa's row, replacing any existing row for the same mesa_id
    (a re-run/correction supersedes the earlier read rather than duplicating it).
    """
    store_path = Path(store_path)
    if store_path.exists():
        df = pd.read_csv(store_path)
        df = df[df["mesa_id"].astype(str) != str(row["mesa_id"])]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row], columns=_COLUMNS)
    df.to_csv(store_path, index=False)


def load_store(store_path: str | Path) -> pd.DataFrame:
    store_path = Path(store_path)
    if not store_path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    return pd.read_csv(store_path)
