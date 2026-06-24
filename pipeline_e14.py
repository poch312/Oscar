#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_e14.py — Descarga + Auditoría de Actas E-14 en un solo comando
=========================================================================
Paso 1: Descarga los PDFs desde el portal de la Registraduría.
Paso 2: Corre el auditor forense completo sobre los PDFs descargados.
Paso 3: Genera reporte HTML, CSV priorizado y JSON.

USO:
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/ --ocr google --google-key clave.json
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/ --oficiales preconteo.json
  python3 pipeline_e14.py --solo-auditar resultados/actas/   # saltar descarga

FORMATO DEL CSV (--lista):
  dep,mun,zona,puesto,mesa
  15,001,000,001,001
  15,001,000,001,002
"""

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ===========================================================================
# ── CONFIGURA AQUÍ ──────────────────────────────────────────────────────────
# Edita esta función con la URL real del portal de la Registraduría.
# ===========================================================================

def construir_url(dep: str, mun: str, zona: str, puesto: str, mesa: str) -> str:
    """
    Devuelve la URL del PDF para una mesa dada.

    EJEMPLOS (descomenta el patrón correcto o escribe el tuyo):

    # Patrón con parámetros GET:
    # return (f"https://resultados.registraduria.gov.co/actas/e14.php"
    #         f"?dep={dep}&mun={mun}&zona={zona}&puesto={puesto}&mesa={mesa}")

    # Patrón con ruta jerárquica:
    # return (f"https://resultados.registraduria.gov.co/actas"
    #         f"/{dep}/{mun}/{zona}/{puesto}/{mesa}/e14.pdf")
    """
    # ↓↓↓ PON LA URL REAL AQUÍ ↓↓↓
    raise NotImplementedError(
        "Edita construir_url() en pipeline_e14.py con la URL real del portal.\n"
        "Si ya tienes los PDFs descargados, usa: --solo-auditar <carpeta>"
    )

# ===========================================================================
# ── FIN DE CONFIGURACIÓN ────────────────────────────────────────────────────
# ===========================================================================

REINTENTOS  = 4
PAUSA_BASE  = 2.0
PAUSA_ENTRE = 0.5
TIMEOUT     = 30


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def _nombre_pdf(dep, mun, zona, puesto, mesa) -> str:
    return f"Dep{dep}-Mun{mun}-Zona{zona}-Puesto{puesto}-Mesa{mesa}.pdf"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def _es_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception:
        return False


def _descargar_uno(url: str, destino: Path) -> tuple[bool, str]:
    for intento in range(1, REINTENTOS + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (auditor-e14-colombia)"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                contenido = resp.read()
            if len(contenido) < 100:
                return False, f"Respuesta muy pequeña ({len(contenido)} bytes)"
            destino.write_bytes(contenido)
            if not _es_pdf(destino):
                destino.unlink(missing_ok=True)
                return False, "Archivo descargado no es un PDF válido"
            return True, f"{len(contenido):,} bytes"

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, "HTTP 404 — acta no encontrada"
            if e.code in (429, 503) and intento < REINTENTOS:
                espera = PAUSA_BASE * (2 ** (intento - 1))
                print(f"      HTTP {e.code} — reintentando en {espera:.0f}s...")
                time.sleep(espera)
            else:
                return False, f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if intento < REINTENTOS:
                espera = PAUSA_BASE * (2 ** (intento - 1))
                print(f"      Error de red — reintentando en {espera:.0f}s...")
                time.sleep(espera)
            else:
                return False, str(e)
    return False, "Agotados los reintentos"


def _leer_csv(ruta: str) -> list[dict]:
    mesas = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            mesas.append({
                "dep":    fila["dep"].zfill(2),
                "mun":    fila["mun"].zfill(3),
                "zona":   fila["zona"].zfill(3),
                "puesto": fila["puesto"].zfill(2),
                "mesa":   fila["mesa"].zfill(3),
            })
    return mesas


def paso_descarga(mesas: list[dict], carpeta_pdfs: Path) -> int:
    """Descarga todos los PDFs. Devuelve cantidad de PDFs disponibles al final."""
    carpeta_pdfs.mkdir(parents=True, exist_ok=True)
    log_path = carpeta_pdfs / "_descarga_log.json"
    log: dict = {}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text())
        except Exception:
            pass

    total = len(mesas)
    ok = err = omitidos = 0

    print(f"\n{'='*60}")
    print(f"  PASO 1/2 — DESCARGA")
    print(f"  {total} mesas  →  {carpeta_pdfs}/")
    if log:
        print(f"  Reanudando (ya procesadas: {len(log)})")
    print(f"{'='*60}\n")

    for i, m in enumerate(mesas, 1):
        nombre = _nombre_pdf(**m)
        destino = carpeta_pdfs / nombre

        if destino.exists() and _es_pdf(destino):
            log[nombre] = {"estado": "ok", "omitido": True}
            omitidos += 1
            continue

        url = construir_url(**m)
        print(f"  [{i:5d}/{total}] {nombre[:55]:<55}", end=" ", flush=True)
        exito, msg = _descargar_uno(url, destino)

        if exito:
            log[nombre] = {"estado": "ok", "sha256": _sha256(destino), "url": url}
            print(f"✓  {msg}")
            ok += 1
        else:
            log[nombre] = {"estado": "error", "error": msg, "url": url}
            print(f"✗  {msg}")
            err += 1

        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))
        time.sleep(PAUSA_ENTRE)

    pdfs_disponibles = ok + omitidos
    print(f"\n  Descargadas: {ok}  |  Ya existían: {omitidos}  |  Errores: {err}")
    print(f"  PDFs disponibles para auditar: {pdfs_disponibles}\n")
    return pdfs_disponibles


# ---------------------------------------------------------------------------
# Auditoría (llama a auditor_e14_v2.main)
# ---------------------------------------------------------------------------

def paso_auditoria(carpeta_pdfs: Path, salida: Path,
                   oficiales_path, ocr_motor, google_key):
    print(f"{'='*60}")
    print(f"  PASO 2/2 — AUDITORÍA FORENSE")
    print(f"  PDFs: {carpeta_pdfs}/")
    print(f"  Salida: {salida}/")
    print(f"{'='*60}\n")

    # Importar el auditor desde el mismo directorio
    import importlib.util, os
    script_dir = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "auditor_e14_v2", script_dir / "auditor_e14_v2.py")
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)

    auditor.main(
        carpeta=str(carpeta_pdfs),
        salida=str(salida),
        oficiales_path=oficiales_path,
        eleccion=None,
        ocr_motor=ocr_motor,
        google_key=google_key,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Pipeline E-14: descarga + auditoría en un solo comando",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EJEMPLOS:
  # Descarga y audita (OCR local, sin preconteo)
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/

  # Con preconteo oficial y OCR de Google
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/ \\
      --oficiales preconteo.json --ocr google --google-key clave.json

  # Saltar descarga, auditar PDFs que ya tengo
  python3 pipeline_e14.py --solo-auditar actas/ --salida resultados/
        """)

    p.add_argument("--lista",         help="CSV con columnas: dep,mun,zona,puesto,mesa")
    p.add_argument("--salida",        default="resultados_e14",
                                      help="Carpeta raíz de salida (default: resultados_e14/)")
    p.add_argument("--solo-auditar",  metavar="CARPETA_PDFS",
                                      help="Saltar descarga y auditar PDFs en esta carpeta")
    p.add_argument("--oficiales",     default=None,
                                      help="JSON con preconteo oficial por mesa")
    p.add_argument("--ocr",           default="tesseract",
                                      choices=["tesseract", "google"])
    p.add_argument("--google-key",    default=None,
                                      help="Credenciales Google Cloud Vision (.json)")
    args = p.parse_args()

    salida      = Path(args.salida)
    carpeta_pdfs = salida / "actas"

    # ── Modo: solo auditar ────────────────────────────────────────────────
    if args.solo_auditar:
        carpeta_pdfs = Path(args.solo_auditar)
        if not carpeta_pdfs.exists():
            print(f"[ERROR] Carpeta no existe: {carpeta_pdfs}", file=sys.stderr)
            sys.exit(1)
        paso_auditoria(carpeta_pdfs, salida / "auditoria",
                       args.oficiales, args.ocr, args.google_key)
        return

    # ── Modo: descarga + auditoría ─────────────────────────────────────────
    if not args.lista:
        p.print_help()
        print("\n[ERROR] Debes indicar --lista <mesas.csv> o --solo-auditar <carpeta>.",
              file=sys.stderr)
        sys.exit(1)

    # Verificar que construir_url() está configurada
    try:
        construir_url("15", "001", "000", "001", "001")
    except NotImplementedError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    mesas = _leer_csv(args.lista)
    print(f"[OK] {len(mesas)} mesas leídas de {args.lista}")

    n_pdfs = paso_descarga(mesas, carpeta_pdfs)

    if n_pdfs == 0:
        print("[ERROR] No hay PDFs para auditar. Revisa errores de descarga.", file=sys.stderr)
        sys.exit(1)

    paso_auditoria(carpeta_pdfs, salida / "auditoria",
                   args.oficiales, args.ocr, args.google_key)

    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETO")
    print(f"  PDFs descargados: {carpeta_pdfs}/")
    print(f"  Reporte:          {salida}/auditoria/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
