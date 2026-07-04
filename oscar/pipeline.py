"""I/O-agnostic pipeline orchestrator.

Deliberately takes/returns plain dataclasses (no argparse/click, no file-path
side effects beyond what's passed in) so a future FastAPI layer can call
`run_audit`/`calibrate_from_reference` directly without restructuring this
module — see docs/architecture.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from oscar.config import PipelineConfig
from oscar.consistency.arithmetic_check import CandidateVote, MesaExtraction, check_arithmetic
from oscar.io.file_discovery import DiscoveredDocument, discover_documents, find_duplicate_hashes
from oscar.io.metadata_hash import (
    extract_pdf_metadata,
    find_near_duplicates,
    perceptual_hash,
)
from oscar.io.pdf_ingest import PageImage, ingest_pdf
from oscar.ocr.engines import PaddleOCREngine, TesseractDigitEngine, TesseractTextEngine
from oscar.ocr.ensemble import read_digit_cell, read_text_cell
from oscar.scoring.risk_model import MesaRiskReport, RiskInputs, compute_risk
from oscar.tamper.calibrate import compute_calibration, save_calibration
from oscar.tamper.score import TamperScorer
from oscar.vision.cell_segmentation import FieldRole, SegmentedTable, segment_table
from oscar.vision.preprocess import preprocess
from oscar.vision.table_detection import Cell, crop_cell, detect_table_grid


@dataclass
class PipelineResult:
    reports: list[MesaRiskReport]
    duplicate_file_hashes: dict[str, list[str]]
    duplicate_page_images: list[tuple[str, str, int]]
    documents_failed: list[tuple[str, str]]  # (mesa_id, error message)


class OCREngines:
    """Bundles the OCR engines so they're constructed (and PaddleOCR lazily
    loaded) once per pipeline run rather than once per cell."""

    def __init__(self, config) -> None:
        self.primary = PaddleOCREngine()
        self.fallback = TesseractDigitEngine(config)
        self.text = TesseractTextEngine()


def _extract_mesa_data(
    mesa_id: str, gray: np.ndarray, segmented: SegmentedTable, engines: OCREngines, config
) -> MesaExtraction:
    """Turn a semantically-labeled cell grid into vote counts.

    For each row containing a CANDIDATE_NAME cell, reads the candidate's name
    (free-text engine) and the vote count in that same row's VOTE_COUNT column
    (digit ensemble). TOTAL_VOTES/TOTAL_BALLOTS/VOTES_IN_WORDS are read once
    from wherever they were located, regardless of row.
    """
    by_row: dict[int, dict[FieldRole, Cell]] = {}
    singleton_cells: dict[FieldRole, Cell] = {}
    for sc in segmented.cells:
        if sc.cell.row == 0:
            continue  # header row (column titles), not a data row
        if sc.role in (FieldRole.CANDIDATE_NAME, FieldRole.VOTE_COUNT):
            by_row.setdefault(sc.cell.row, {})[sc.role] = sc.cell
        elif sc.role != FieldRole.UNKNOWN:
            singleton_cells.setdefault(sc.role, sc.cell)

    candidates: list[CandidateVote] = []
    for row, roles in sorted(by_row.items()):
        name_cell = roles.get(FieldRole.CANDIDATE_NAME)
        vote_cell = roles.get(FieldRole.VOTE_COUNT)
        if name_cell is None or vote_cell is None:
            continue
        name_result = read_text_cell(crop_cell(gray, name_cell), engines.text)
        vote_result = read_digit_cell(crop_cell(gray, vote_cell), engines.primary, engines.fallback, config)
        votes = int(vote_result.text) if vote_result.text.isdigit() else None
        candidates.append(CandidateVote(
            name=name_result.text or f"fila_{row}",
            votes=votes,
            confidence=vote_result.confidence,
        ))

    def _read_digit_singleton(role: FieldRole) -> int | None:
        cell = singleton_cells.get(role)
        if cell is None:
            return None
        result = read_digit_cell(crop_cell(gray, cell), engines.primary, engines.fallback, config)
        return int(result.text) if result.text.isdigit() else None

    def _read_text_singleton(role: FieldRole) -> str | None:
        cell = singleton_cells.get(role)
        if cell is None:
            return None
        return read_text_cell(crop_cell(gray, cell), engines.text).text or None

    # NOTE: VOTES_IN_WORDS is treated as a single acta-wide field (the first
    # matching cell wins) and cross-checked only against total_votes. If a
    # real E14 layout turns out to have a separate "en letras" cell per
    # candidate row rather than one for the total, this should become a
    # per-CandidateVote field instead of a MesaExtraction singleton — left as
    # a singleton until validated against real forms (see docs/architecture.md).
    return MesaExtraction(
        mesa_id=mesa_id,
        candidates=candidates,
        total_votes=_read_digit_singleton(FieldRole.TOTAL_VOTES),
        total_votes_words=_read_text_singleton(FieldRole.VOTES_IN_WORDS),
        blank_votes=None,
        null_votes=None,
        registered_voters=_read_digit_singleton(FieldRole.TOTAL_BALLOTS),
    )


def _process_document(
    doc: DiscoveredDocument, engines: OCREngines, tamper_scorer: TamperScorer, config: PipelineConfig
) -> tuple[MesaRiskReport | None, str | None, "np.ndarray | None"]:
    """Returns (report, error, page_gray_for_phash)."""
    try:
        pages = ingest_pdf(doc.path, dpi=config.dpi)
    except Exception as exc:
        return None, f"pdf_ingest_failed: {exc}", None
    if not pages:
        return None, "no_pages_found", None

    page_image: PageImage = pages[0]
    try:
        metadata = extract_pdf_metadata(doc.path)
    except Exception:
        metadata = None

    pre = preprocess(np.asarray(page_image.image))
    grid = detect_table_grid(pre.binary, config.table)

    def ocr_text_fn(cell_img: np.ndarray) -> str:
        return engines.text.read(cell_img).text

    segmented = segment_table(pre.gray, grid, ocr_text_fn)
    extraction = _extract_mesa_data(doc.mesa_id, pre.gray, segmented, engines, config.ocr)
    arithmetic = check_arithmetic(extraction)
    tamper = tamper_scorer.assess(page_image)

    risk = compute_risk(RiskInputs(
        mesa_id=doc.mesa_id,
        arithmetic=arithmetic,
        tamper=tamper,
        metadata=metadata,
        table_needs_review=grid.needs_review,
        ocr_needs_review=segmented.needs_review,
    ))
    return risk, None, pre.gray


def run_audit(input_dir: str | Path, config: PipelineConfig | None = None) -> PipelineResult:
    config = config or PipelineConfig()
    documents = discover_documents(input_dir)
    duplicate_hashes = {
        h: [str(p) for p in paths] for h, paths in find_duplicate_hashes(documents).items()
    }

    engines = OCREngines(config.ocr)
    tamper_scorer = TamperScorer(config.tamper.model_path, config.tamper.calibration_path)

    reports: list[MesaRiskReport] = []
    failed: list[tuple[str, str]] = []
    page_hashes = {}

    for doc in documents:
        report, error, gray = _process_document(doc, engines, tamper_scorer, config)
        if error is not None:
            failed.append((doc.mesa_id, error))
            continue
        reports.append(report)
        if gray is not None:
            page_hashes[doc.mesa_id] = perceptual_hash(Image.fromarray(gray))

    duplicate_pages = find_near_duplicates(page_hashes)

    # Re-flag risk for mesas whose page image duplicates another mesa's.
    duplicate_map: dict[str, list[str]] = {}
    for a, b, _dist in duplicate_pages:
        duplicate_map.setdefault(a, []).append(b)
        duplicate_map.setdefault(b, []).append(a)
    if duplicate_map:
        reports = [
            r if r.mesa_id not in duplicate_map else compute_risk(RiskInputs(
                mesa_id=r.mesa_id, arithmetic=r.arithmetic, tamper=r.tamper, metadata=r.metadata,
                duplicate_of=duplicate_map[r.mesa_id],
            ))
            for r in reports
        ]

    return PipelineResult(
        reports=reports,
        duplicate_file_hashes=duplicate_hashes,
        duplicate_page_images=duplicate_pages,
        documents_failed=failed,
    )


def calibrate_from_reference(reference_dir: str | Path, config: PipelineConfig | None = None) -> Path:
    """Compute and save a tamper-score calibration threshold from a directory
    of known-genuine reference actas (see oscar.tamper.calibrate)."""
    config = config or PipelineConfig()
    documents = discover_documents(reference_dir)
    scorer = TamperScorer(model_path=config.tamper.model_path)

    scores = []
    for doc in documents:
        pages = ingest_pdf(doc.path, dpi=config.dpi)
        if not pages or not pages[0].ela_meaningful:
            continue
        scores.append(scorer.raw_score(pages[0].image))

    calibration = compute_calibration(scores, percentile=config.tamper.calibration_percentile)
    save_calibration(calibration, config.tamper.calibration_path)
    return Path(config.tamper.calibration_path)
