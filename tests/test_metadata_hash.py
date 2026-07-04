import fitz
import numpy as np
from PIL import Image

from oscar.io.metadata_hash import extract_pdf_metadata, find_near_duplicates, perceptual_hash


def test_extract_pdf_metadata_reads_producer_and_counts_updates(tmp_path):
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.set_metadata({"producer": "TestProducer", "creator": "TestCreator"})
    doc.save(str(path))
    doc.close()

    report = extract_pdf_metadata(path)
    assert report.producer == "TestProducer"
    assert report.incremental_update_count == 0


def test_find_near_duplicates_detects_identical_images():
    image_a = Image.fromarray(np.full((50, 50, 3), 128, dtype=np.uint8))
    image_b = Image.fromarray(np.full((50, 50, 3), 128, dtype=np.uint8))
    image_c = Image.fromarray(np.random.default_rng(0).integers(0, 255, (50, 50, 3), dtype=np.uint8))

    hashes = {
        "mesa_1": perceptual_hash(image_a),
        "mesa_2": perceptual_hash(image_b),
        "mesa_3": perceptual_hash(image_c),
    }
    matches = find_near_duplicates(hashes, max_hamming_distance=4)
    matched_pairs = {frozenset((a, b)) for a, b, _ in matches}
    assert frozenset(("mesa_1", "mesa_2")) in matched_pairs
    assert frozenset(("mesa_1", "mesa_3")) not in matched_pairs
