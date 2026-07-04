"""Fetch the CASIA 2.0 (and optionally 1.0) tamper-detection datasets used to
pretrain oscar.tamper.model before any real acta-domain data exists.

CASIA is distributed via Google Drive/Baidu links on its source repos rather
than a stable direct-download URL, so this script clones the corrected
groundtruth repos (which mirror the images) instead of hardcoding a link that
may break:
    https://github.com/SunnyHaze/CASIA2.0-Corrected-Groundtruth
    https://github.com/namtpham/casia1groundtruth

Usage: python scripts/download_casia.py --dest data/casia
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

_REPOS = {
    "casia2": "https://github.com/SunnyHaze/CASIA2.0-Corrected-Groundtruth.git",
    "casia1": "https://github.com/namtpham/casia1groundtruth.git",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default="data/casia")
    parser.add_argument("--which", choices=["casia1", "casia2", "both"], default="casia2")
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    targets = _REPOS if args.which == "both" else {args.which: _REPOS[args.which]}
    for name, url in targets.items():
        target_dir = dest / name
        if target_dir.exists():
            print(f"{target_dir} ya existe, se omite.")
            continue
        subprocess.run(["git", "clone", "--depth", "1", url, str(target_dir)], check=True)

    print(
        "Descarga completa. Reorganiza manualmente las imágenes en "
        f"{dest}/authentic/ y {dest}/tampered/ según el layout esperado por "
        "oscar.tamper.dataset.CasiaTamperDataset (los repos de groundtruth "
        "documentan su propia estructura de carpetas, que varía por versión)."
    )


if __name__ == "__main__":
    main()
