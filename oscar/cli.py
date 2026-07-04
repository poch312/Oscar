"""CLI entry point: `oscar ingest|audit|calibrate|analyze-batch`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from oscar.config import PipelineConfig
from oscar.io.file_discovery import discover_documents
from oscar.io.pdf_ingest import ingest_pdf
from oscar.pipeline import calibrate_from_reference, run_audit
from oscar.scoring.report import write_csv_report, write_json_report
from oscar.statistics.aggregate import load_store
from oscar.statistics.digit_heuristics import benford_first_digit_test, last_digit_uniformity_test

app = typer.Typer(help="Auditor forense de actas E14")
console = Console()


@app.command()
def ingest(input_dir: Path) -> None:
    """Debug/smoke-test: ingest every PDF in a folder and report page
    compression filters (determines whether ELA will be meaningful)."""
    documents = discover_documents(input_dir)
    table = Table("mesa_id", "archivo", "páginas", "fuente", "filtro", "ela_util")
    for doc in documents:
        try:
            pages = ingest_pdf(doc.path)
        except Exception as exc:
            table.add_row(doc.mesa_id, doc.path.name, "-", "ERROR", str(exc), "-")
            continue
        for page in pages:
            table.add_row(
                doc.mesa_id, doc.path.name, str(page.page_index), page.source,
                str(page.compression_filter), str(page.ela_meaningful),
            )
    console.print(table)


@app.command()
def audit(
    input_dir: Path,
    output: Path = typer.Option(Path("report.json"), "-o", "--output"),
    csv_output: Path | None = typer.Option(None, "--csv"),
) -> None:
    """Run the full audit pipeline over every acta PDF in input_dir."""
    config = PipelineConfig()
    result = run_audit(input_dir, config)

    write_json_report(result.reports, output)
    if csv_output:
        write_csv_report(result.reports, csv_output)

    console.print(f"[bold]{len(result.reports)}[/bold] actas procesadas, "
                  f"[bold]{len(result.documents_failed)}[/bold] fallidas.")
    high_risk = [r for r in result.reports if r.risk_level == "high"]
    console.print(f"[red]{len(high_risk)} actas de riesgo alto[/red] "
                  f"({sum(r.needs_manual_review for r in result.reports)} requieren revisión manual).")
    if result.duplicate_file_hashes:
        console.print(f"[yellow]{len(result.duplicate_file_hashes)} grupos de archivos "
                       f"idénticos (mismo hash) detectados.[/yellow]")
    if result.duplicate_page_images:
        console.print(f"[yellow]{len(result.duplicate_page_images)} pares de páginas "
                       f"casi-idénticas entre mesas distintas.[/yellow]")
    if result.documents_failed:
        for mesa_id, error in result.documents_failed:
            console.print(f"  [red]FALLO[/red] {mesa_id}: {error}")
    console.print(f"Reporte escrito en {output}")


@app.command()
def calibrate(
    reference_genuine_dir: Path = typer.Option(..., "--reference-genuine-dir"),
) -> None:
    """Calibrate the tamper-detection threshold using ~10+ known-genuine actas."""
    config = PipelineConfig()
    path = calibrate_from_reference(reference_genuine_dir, config)
    console.print(f"Calibración guardada en {path}")


@app.command("analyze-batch")
def analyze_batch(
    store: Path = typer.Option(Path("mesa_results.csv"), "--store"),
) -> None:
    """Run batch-level digit heuristics (Benford, last-digit uniformity) over
    the accumulated per-mesa results table."""
    df = load_store(store)
    if df.empty:
        console.print("[yellow]No hay datos acumulados todavía en el store.[/yellow]")
        raise typer.Exit(code=1)

    totals = df["total_votes"].dropna().astype(int).tolist()
    benford = benford_first_digit_test(totals)
    last_digit = last_digit_uniformity_test(totals)

    for result in (benford, last_digit):
        if result is None:
            console.print("[yellow]N insuficiente para una de las pruebas (se requieren ~50+ mesas).[/yellow]")
            continue
        flag = "[red]ANOMALÍA[/red]" if result.flagged else "[green]normal[/green]"
        console.print(
            f"{result.test_name}: n={result.n_observations} "
            f"p={result.p_value:.4f} -> {flag}"
        )


if __name__ == "__main__":
    app()
