"""Walk an input directory for acta PDFs and assign a stable mesa/document id."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# E14 filenames from the Registraduría typically embed the mesa code, e.g.
# "E14_05001000123_001.pdf". Fall back to the file stem if no such code is found.
_MESA_CODE_RE = re.compile(r"(\d{6,12})")


@dataclass
class DiscoveredDocument:
    path: Path
    mesa_id: str
    sha256: str


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_mesa_id(path: Path) -> str:
    match = _MESA_CODE_RE.search(path.stem)
    return match.group(1) if match else path.stem


def discover_documents(input_dir: str | Path) -> list[DiscoveredDocument]:
    """Find every PDF under input_dir and compute its mesa id + content hash.

    Deduplication (identical sha256 appearing under different mesa ids) is left
    to the caller/report layer to flag, rather than silently dropped here.
    """
    input_dir = Path(input_dir)
    documents = []
    for path in sorted(input_dir.rglob("*.pdf")):
        documents.append(
            DiscoveredDocument(path=path, mesa_id=_guess_mesa_id(path), sha256=_sha256_of(path))
        )
    return documents


def find_duplicate_hashes(documents: list[DiscoveredDocument]) -> dict[str, list[Path]]:
    """Group documents whose file content is byte-identical (same sha256)."""
    by_hash: dict[str, list[Path]] = {}
    for doc in documents:
        by_hash.setdefault(doc.sha256, []).append(doc.path)
    return {h: paths for h, paths in by_hash.items() if len(paths) > 1}
