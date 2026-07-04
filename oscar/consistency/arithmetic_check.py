"""Per-acta arithmetic self-consistency checks.

Zero ML, zero external data dependency — runs on every processed acta from
day one and is the cheapest, highest-signal-to-effort check in the system.
Catches internal contradictions (sum != total, digits != words) whether they
come from sloppy tampering or plain transcription error; it cannot detect a
self-consistent falsification (see docs/architecture.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oscar.ocr.digit_postprocess import digits_match_words


@dataclass
class CandidateVote:
    name: str
    votes: int | None
    confidence: float = 1.0


@dataclass
class MesaExtraction:
    mesa_id: str
    candidates: list[CandidateVote]
    total_votes: int | None
    total_votes_words: str | None = None
    blank_votes: int | None = None
    null_votes: int | None = None
    registered_voters: int | None = None


@dataclass
class ArithmeticFlag:
    code: str
    message: str
    severity: str  # "info" | "warning" | "critical"


@dataclass
class ArithmeticCheckResult:
    mesa_id: str
    computed_total: int | None
    flags: list[ArithmeticFlag] = field(default_factory=list)

    @property
    def is_consistent(self) -> bool:
        return not any(f.severity == "critical" for f in self.flags)


def check_arithmetic(extraction: MesaExtraction) -> ArithmeticCheckResult:
    flags: list[ArithmeticFlag] = []

    missing_candidates = [c.name for c in extraction.candidates if c.votes is None]
    if missing_candidates:
        flags.append(ArithmeticFlag(
            code="missing_candidate_votes",
            message=f"No se pudo leer el voto de: {', '.join(missing_candidates)}",
            severity="warning",
        ))

    candidate_sum = sum(c.votes for c in extraction.candidates if c.votes is not None)
    computed_total = candidate_sum + (extraction.blank_votes or 0) + (extraction.null_votes or 0)

    if extraction.total_votes is not None and not missing_candidates:
        if computed_total != extraction.total_votes:
            flags.append(ArithmeticFlag(
                code="sum_mismatch",
                message=(
                    f"Suma de votos por candidato + blancos/nulos ({computed_total}) "
                    f"no coincide con el total del acta ({extraction.total_votes})"
                ),
                severity="critical",
            ))

    if extraction.registered_voters is not None and extraction.total_votes is not None:
        if extraction.total_votes > extraction.registered_voters:
            flags.append(ArithmeticFlag(
                code="total_exceeds_census",
                message=(
                    f"Total de votos ({extraction.total_votes}) supera el censo de "
                    f"la mesa ({extraction.registered_voters})"
                ),
                severity="critical",
            ))

    if extraction.total_votes_words:
        match = digits_match_words(extraction.total_votes, extraction.total_votes_words)
        if match is False:
            flags.append(ArithmeticFlag(
                code="digits_words_mismatch",
                message=(
                    f"El total en dígitos ({extraction.total_votes}) no coincide con "
                    f"el total escrito en letras ('{extraction.total_votes_words}')"
                ),
                severity="critical",
            ))

    low_confidence = [c.name for c in extraction.candidates if c.votes is not None and c.confidence < 0.55]
    if low_confidence:
        flags.append(ArithmeticFlag(
            code="low_ocr_confidence",
            message=f"Lectura de baja confianza para: {', '.join(low_confidence)}",
            severity="warning",
        ))

    return ArithmeticCheckResult(mesa_id=extraction.mesa_id, computed_total=computed_total, flags=flags)
