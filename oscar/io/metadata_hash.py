"""Cheap first-pass forensic checks: PDF metadata/revision history + perceptual hashing.

This is the awesome-forensics-style layer: fast, no ML, catches a different
fraud mechanism than the image-tampering model (a file re-saved/re-edited
after the original scan, or the same image reused across supposedly-distinct
mesas) without needing to look at pixel content at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import imagehash
import pikepdf
from PIL import Image


@dataclass
class PdfMetadataReport:
    producer: str | None
    creator: str | None
    creation_date: str | None
    mod_date: str | None
    incremental_update_count: int

    @property
    def has_suspicious_mod_after_creation(self) -> bool:
        """True when the PDF's own metadata records a modification distinct from creation.

        This is a weak signal (many legitimate scanner/export pipelines set
        both timestamps identically or omit ModDate), so it is surfaced as a
        flag for the risk scorer to weigh, never as a standalone verdict.
        """
        return bool(self.mod_date) and self.mod_date != self.creation_date


def _count_incremental_updates(path: Path) -> int:
    """Count '%%EOF' markers in the raw file; N>1 means the PDF was saved/appended N-1 times."""
    data = path.read_bytes()
    count = data.count(b"%%EOF")
    return max(count - 1, 0)


def extract_pdf_metadata(path: str | Path) -> PdfMetadataReport:
    path = Path(path)
    with pikepdf.open(path) as pdf:
        docinfo = pdf.docinfo or {}
        producer = str(docinfo.get("/Producer", "")) or None
        creator = str(docinfo.get("/Creator", "")) or None
        creation_date = str(docinfo.get("/CreationDate", "")) or None
        mod_date = str(docinfo.get("/ModDate", "")) or None
    return PdfMetadataReport(
        producer=producer,
        creator=creator,
        creation_date=creation_date,
        mod_date=mod_date,
        incremental_update_count=_count_incremental_updates(path),
    )


def perceptual_hash(image: Image.Image) -> imagehash.ImageHash:
    return imagehash.phash(image)


def find_near_duplicates(
    hashes: dict[str, imagehash.ImageHash], max_hamming_distance: int = 4
) -> list[tuple[str, str, int]]:
    """Return (id_a, id_b, distance) triples for documents with near-identical page images.

    A near-duplicate across two different mesa ids is suspicious: it suggests
    the same scanned page was reused/copy-pasted rather than being a distinct
    mesa's original acta.
    """
    ids = list(hashes)
    matches = []
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            distance = hashes[id_a] - hashes[id_b]
            if distance <= max_hamming_distance:
                matches.append((id_a, id_b, distance))
    return matches
