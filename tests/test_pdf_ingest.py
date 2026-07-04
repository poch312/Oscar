import io

import fitz
import numpy as np
from PIL import Image

from oscar.io.pdf_ingest import ingest_pdf


def _make_pdf_with_embedded_jpeg(path, size=(200, 150)) -> None:
    image = Image.fromarray(np.full((size[1], size[0], 3), 200, dtype=np.uint8))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)

    doc = fitz.open()
    page = doc.new_page(width=size[0], height=size[1])
    page.insert_image(fitz.Rect(0, 0, size[0], size[1]), stream=buffer.getvalue())
    doc.save(str(path))
    doc.close()


def test_ingest_extracts_embedded_jpeg_and_flags_ela_meaningful(tmp_path):
    pdf_path = tmp_path / "acta.pdf"
    _make_pdf_with_embedded_jpeg(pdf_path)

    pages = ingest_pdf(pdf_path)
    assert len(pages) == 1
    page = pages[0]
    assert page.source == "embedded"
    assert page.compression_kind == "jpeg"
    assert page.ela_meaningful


def test_ingest_falls_back_to_rasterize_for_vector_only_page(tmp_path):
    pdf_path = tmp_path / "vector.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=150)
    page.draw_rect(fitz.Rect(10, 10, 100, 100))  # vector content, no embedded image
    doc.save(str(pdf_path))
    doc.close()

    pages = ingest_pdf(pdf_path)
    assert len(pages) == 1
    assert pages[0].source == "rasterized"
    assert not pages[0].ela_meaningful
