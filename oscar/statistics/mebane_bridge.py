"""Bridge to Walter Mebane's `eforensics` R package via subprocess.

Deliberately subprocess + a version-pinned Rscript (scripts/run_eforensics.R),
not rpy2: rpy2 couples the Python process to a specific R/Python ABI, which is
brittle to maintain over this project's ~4 year horizon. If R/JAGS aren't
installed, this degrades to "unavailable" without breaking the rest of the
pipeline (see docs/architecture.md).

Not wired into the Fase 0 MVP CLI yet — needs a large-enough per-mesa dataset
with appropriately-specified covariates (a modeling/data blocker, not a code
blocker; see run_eforensics.R's note on the formula placeholder).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_R_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_eforensics.R"


@dataclass
class MebaneResult:
    raw: dict


def is_available() -> tuple[bool, str | None]:
    """Check whether Rscript is on PATH. Does not verify the eforensics/JAGS
    packages are installed (that failure surfaces at run time in stderr)."""
    if shutil.which("Rscript") is None:
        return False, "Rscript no está instalado o no está en PATH."
    return True, None


def run_eforensics(mesa_csv_path: str | Path, output_path: str | Path, timeout: int = 3600) -> MebaneResult:
    available, reason = is_available()
    if not available:
        raise RuntimeError(f"eforensics no disponible: {reason}")

    output_path = Path(output_path)
    result = subprocess.run(
        ["Rscript", str(_R_SCRIPT), "--input", str(mesa_csv_path), "--output", str(output_path)],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"run_eforensics.R falló: {result.stderr}")

    return MebaneResult(raw=json.loads(output_path.read_text()))
