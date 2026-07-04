"""PDF -> page image(s).

Prefers extracting the raw embedded image stream over re-rasterizing the page,
because ELA (oscar.tamper.ela) depends on the original JPEG compression
artifacts being preserved. Re-rasterizing (e.g. via get_pixmap) re-encodes the
page and destroys that signal.

Logs the embedded image's PDF filter (/DCTDecode, /CCITTFaxDecode, a
Flate/lossless filter, ...) for every page, since that determines whether ELA
is even meaningful for a given document (see docs/architecture risks).
"""

from __future__ import annotations

import io as _io
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

KNOWN_FILTERS = {
    "DCTDecode": "jpeg",
    "JPXDecode": "jpeg2000",
    "CCITTFaxDecode": "fax_g4",
    "FlateDecode": "lossless",
    "LZWDecode": "lossless",
}


@dataclass
class PageImage:
    page_index: int
    image: Image.Image
    source: str  # "embedded" | "rasterized"
    compression_filter: str | None  # raw PDF /Filter name, or None if rasterized
    compression_kind: str | None  # "jpeg" | "jpeg2000" | "fax_g4" | "lossless" | None
    dpi: int

    @property
    def ela_meaningful(self) -> bool:
        """ELA's premise (recompression residual) only holds for JPEG-family sources."""
        return self.compression_kind in ("jpeg", "jpeg2000")


def _extract_single_embedded_image(doc: fitz.Document, page: fitz.Page, dpi: int) -> PageImage | None:
    """Return the page's raw embedded image if the page is a simple single-image scan."""
    images = page.get_images(full=True)
    if len(images) != 1:
        return None

    xref = images[0][0]
    try:
        filt = doc.xref_get_key(xref, "Filter")
        filter_value = filt[1] if filt and filt[0] != "null" else None
        if isinstance(filter_value, str):
            filter_value = filter_value.strip("[]/ ").split()[0] if filter_value.strip("[]") else None
    except Exception:
        filter_value = None

    try:
        extracted = doc.extract_image(xref)
    except Exception:
        return None

    image_bytes = extracted.get("image")
    if not image_bytes:
        return None

    try:
        pil_image = Image.open(_io.BytesIO(image_bytes))
        pil_image.load()
    except Exception:
        return None

    ext = extracted.get("ext", "")
    filter_name = filter_value or {"jpg": "DCTDecode", "jpeg": "DCTDecode", "jp2": "JPXDecode"}.get(ext)
    compression_kind = KNOWN_FILTERS.get(filter_name) if filter_name else (
        "jpeg" if ext in ("jpg", "jpeg") else None
    )

    return PageImage(
        page_index=page.number,
        image=pil_image.convert("RGB"),
        source="embedded",
        compression_filter=filter_name,
        compression_kind=compression_kind,
        dpi=dpi,
    )


def _rasterize_page(page: fitz.Page, dpi: int) -> PageImage:
    zoom = dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    mode = "RGB" if pixmap.alpha == 0 else "RGBA"
    pil_image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples).convert("RGB")
    return PageImage(
        page_index=page.number,
        image=pil_image,
        source="rasterized",
        compression_filter=None,
        compression_kind=None,
        dpi=dpi,
    )


def ingest_pdf(path: str | Path, dpi: int = 300) -> list[PageImage]:
    """Convert every page of a PDF into a PageImage, preferring raw embedded images."""
    path = Path(path)
    doc = fitz.open(path)
    pages: list[PageImage] = []
    try:
        for page in doc:
            page_image = _extract_single_embedded_image(doc, page, dpi)
            if page_image is None:
                page_image = _rasterize_page(page, dpi)
            pages.append(page_image)
    finally:
        doc.close()
    return pages


def page_image_to_array(page_image: PageImage) -> np.ndarray:
    return np.array(page_image.image)
