"""Classify a detected grid's cells into semantic E14 fields by header anchoring.

Rather than assuming fixed row/column positions for "candidate name" or "vote
count" (rejected per the project's binding constraint), this reads the text of
header-row/column cells with OCR and fuzzy-matches it against known E14
vocabulary to figure out what each column/row means. This generalizes the
fixed-offset template idea from supersuyash/electoral-roll-extraction-OCR into
something that tolerates layout drift across mesas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from rapidfuzz import fuzz

from oscar.vision.table_detection import Cell, TableGrid, crop_cell

# Known E14 header vocabulary (Spanish). Extend as real-world layout variants
# are observed; kept as a plain constant rather than config since it's
# domain vocabulary, not a tunable.
HEADER_VOCAB = {
    "candidato": "candidate_name",
    "partido": "candidate_name",
    "votos": "vote_count",
    "total": "total_votes",
    "sufragantes": "total_ballots",
    "mesa": "mesa_id",
    "puesto": "polling_place_id",
    "en letras": "votes_in_words",
    "letras": "votes_in_words",
}

FUZZY_MATCH_THRESHOLD = 75


class FieldRole(str, Enum):
    CANDIDATE_NAME = "candidate_name"
    VOTE_COUNT = "vote_count"
    TOTAL_VOTES = "total_votes"
    TOTAL_BALLOTS = "total_ballots"
    MESA_ID = "mesa_id"
    POLLING_PLACE_ID = "polling_place_id"
    VOTES_IN_WORDS = "votes_in_words"
    UNKNOWN = "unknown"


@dataclass
class SegmentedCell:
    cell: Cell
    role: FieldRole
    confidence: float


@dataclass
class SegmentedTable:
    cells: list[SegmentedCell]
    needs_review: bool
    review_reason: str | None = None

    def cells_with_role(self, role: FieldRole) -> list[SegmentedCell]:
        return [c for c in self.cells if c.role == role]


def _match_header(text: str) -> tuple[FieldRole, float]:
    text = text.strip().lower()
    if not text:
        return FieldRole.UNKNOWN, 0.0
    best_role, best_score = FieldRole.UNKNOWN, 0.0
    for phrase, role_value in HEADER_VOCAB.items():
        score = fuzz.partial_ratio(text, phrase)
        if score > best_score:
            best_role, best_score = FieldRole(role_value), score
    if best_score < FUZZY_MATCH_THRESHOLD:
        return FieldRole.UNKNOWN, best_score / 100.0
    return best_role, best_score / 100.0


def segment_table(image: np.ndarray, grid: TableGrid, ocr_text_fn) -> SegmentedTable:
    """Assign a semantic role to each header cell (row 0 and col 0), then
    propagate: cells in a "vote_count" column, non-header row, become the
    per-candidate vote count for that row's candidate.

    `ocr_text_fn(cell_image: np.ndarray) -> str` is injected (rather than
    importing oscar.ocr directly) to keep vision/ independent of the OCR
    engine choice/availability.
    """
    if grid.needs_review or not grid.cells:
        return SegmentedTable(cells=[], needs_review=True, review_reason=grid.review_reason)

    header_row_cells = [c for c in grid.cells if c.row == 0]
    header_col_cells = [c for c in grid.cells if c.col == 0]

    col_roles: dict[int, FieldRole] = {}
    for cell in header_row_cells:
        text = ocr_text_fn(crop_cell(image, cell))
        role, _ = _match_header(text)
        col_roles[cell.col] = role

    row_roles: dict[int, FieldRole] = {}
    for cell in header_col_cells:
        text = ocr_text_fn(crop_cell(image, cell))
        role, _ = _match_header(text)
        row_roles[cell.row] = role

    # Rows labeled (via their col-0 cell) as a special total/ballot row override
    # the generic VOTE_COUNT column role for that row: the number in a "TOTAL"
    # row's vote-count column is the acta's total, not another candidate's vote.
    row_special_roles = {
        row: role for row, role in row_roles.items()
        if role in (FieldRole.TOTAL_VOTES, FieldRole.TOTAL_BALLOTS)
    }

    segmented: list[SegmentedCell] = []
    for cell in grid.cells:
        role = col_roles.get(cell.col, FieldRole.UNKNOWN)
        if cell.col != 0 and role == FieldRole.VOTE_COUNT and cell.row in row_special_roles:
            role = row_special_roles[cell.row]
        elif role is FieldRole.UNKNOWN and cell.row in row_roles:
            role = row_roles[cell.row]
        confidence = cell.confidence if role != FieldRole.UNKNOWN else 0.0
        segmented.append(SegmentedCell(cell=cell, role=role, confidence=confidence))

    vote_cols = {c for c, r in col_roles.items() if r == FieldRole.VOTE_COUNT}
    needs_review = len(vote_cols) == 0
    reason = "no_vote_count_column_identified" if needs_review else None
    return SegmentedTable(cells=segmented, needs_review=needs_review, review_reason=reason)
