#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descargador_e14.py — Descarga masiva de actas E-14 desde el portal de la Registraduría
=======================================================================================
Los PDFs quedan nombrados con el patrón que espera auditor_e14_v2.py:
  Dep{dep}-Mun{mun}-Zona{zona}-Puesto{puesto}-Mesa{mesa}.pdf

USO:
  # Descarga usando un CSV con la lista de mesas
  python3 descargador_e14.py --lista mesas.csv --salida actas/

  # Descarga usando rangos numéricos (si la URL sigue un patrón secuencial)
  python3 descargador_e14.py --salida actas/

  # Verificar integridad de los PDFs ya descargados
  python3 descargador_e14.py --verificar --salida actas/

FORMATO DEL CSV (--lista):
  dep,mun,zona,puesto,mesa
  15,001,000,001,001
  15,001,000,001,002
  ...

CONFIGURACIÓN OBLIGATORIA:
  Edita la sección "── CONFIGURA AQUÍ ──" más abajo con la URL real.
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
from datetime import datetime

# ===========================================================================
# ── CONFIGURA AQUÍ ──────────────────────────────────────────────────────────
# Cambia esta función con la URL real del portal de la Registraduría.
# La función recibe los campos del acta y debe devolver la URL del PDF.
# ===========================================================================

def construir_url(dep: str, mun: str, zona: str, puesto: str, mesa: str) -> str:
    """
    Devuelve la URL del PDF para una mesa dada.

    EJEMPLOS de patrones comunes (descomenta el que corresponda o crea el tuyo):

    # Patrón 1: URL con parámetros GET
    # return (f"https://resultados.registraduria.gov.co/actas/e14.php"
    #         f"?dep={dep}&mun={mun}&zona={zona}&puesto={puesto}&mesa={mesa}")

    # Patrón 2: URL con ruta jerárquica
    # return (f"https://resultados.registraduria.gov.co/actas"
    #         f"/{dep}/{mun}/{zona}/{puesto}/{mesa}/e14.pdf")

    # Patrón 3: archivo con nombre fijo
    # return (f"https://cdn.registraduria.gov.co/e14"
    #         f"/{dep}{mun}{zona}{puesto}{mesa}.pdf")
    """
    # ↓↓↓ PON LA URL REAL AQUÍ ↓↓↓
    raise NotImplementedError(
        "Edita construir_url() en descargador_e14.py con la URL real del portal."
    )


# ===========================================================================
# ── FIN DE CONFIGURACIÓN ────────────────────────────────────────────────────
# ===========================================================================

REINTENTOS    = 4          # Intentos por archivo
PAUSA_BASE    = 2.0        # Segundos entre reintentos (backoff exponencial)
PAUSA_ENTRE   = 0.5        # Segundos entre descargas exitosas (no saturar el servidor)
TIMEOUT       = 30         # Segundos de timeout por descarga


def nombre_archivo(dep: str, mun: str, zona: str, puesto: str, mesa: str) -> str:
    """Nombre de archivo que espera auditor_e14_v2.py."""
    return f"Dep{dep}-Mun{mun}-Zona{zona}-Puesto{puesto}-Mesa{mesa}.pdf"


def sha256_archivo(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def es_pdf_valido(path: Path) -> bool:
    """Verifica que el archivo empiece con el magic bytes de PDF."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception:
        return False


def descargar_uno(url: str, destino: Path) -> tuple[bool, str]:
    """
    Descarga un PDF con reintentos y backoff exponencial.
    Devuelve (éxito, mensaje).
    """
    for intento in range(1, REINTENTOS + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (auditor electoral, contacto: pochomath@gmail.com)"
                }
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                contenido = resp.read()

            if len(contenido) < 100:
                return False, f"Respuesta muy pequeña ({len(contenido)} bytes)"

            destino.write_bytes(contenido)

            if not es_pdf_valido(destino):
                destino.unlink(missing_ok=True)
                return False, "El archivo descargado no es un PDF válido"

            return True, f"{len(contenido):,} bytes"

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, f"HTTP 404 — acta no encontrada"
            if e.code in (429, 503) and intento < REINTENTOS:
                espera = PAUSA_BASE * (2 ** (intento - 1))
                print(f"      HTTP {e.code} — reintentando en {espera:.0f}s...")
                time.sleep(espera)
            else:
                return False, f"HTTP {e.code}"

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if intento < REINTENTOS:
                espera = PAUSA_BASE * (2 ** (intento - 1))
                print(f"      Error de red ({e}) — reintentando en {espera:.0f}s...")
                time.sleep(espera)
            else:
                return False, str(e)

    return False, "Agotados los reintentos"


def leer_lista_csv(ruta_csv: str) -> list[dict]:
    """Lee el CSV de mesas. Columnas: dep,mun,zona,puesto,mesa"""
    mesas = []
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for fila in reader:
            mesas.append({
                "dep":    fila["dep"].zfill(2),
                "mun":    fila["mun"].zfill(3),
                "zona":   fila["zona"].zfill(3),
                "puesto": fila["puesto"].zfill(2),
                "mesa":   fila["mesa"].zfill(3),
            })
    return mesas


def descargar_lote(mesas: list[dict], salida: Path) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    log_path = salida / "descarga_log.json"

    # Cargar log previo (para reanudar descargas interrumpidas)
    log: dict = {}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text())
        except Exception:
            log = {}

    ok = err = omitidos = 0
    total = len(mesas)

    print(f"\n[INICIO] {total} mesas  →  {salida}/")
    print(f"         Reanudar desde log: {len(log)} ya procesadas\n")

    for i, m in enumerate(mesas, 1):
        nombre = nombre_archivo(**m)
        destino = salida / nombre

        # Omitir si ya está descargado y es válido
        if destino.exists() and es_pdf_valido(destino):
            log[nombre] = {"estado": "ok", "omitido": True}
            omitidos += 1
            continue

        url = construir_url(**m)
        print(f"  [{i:5d}/{total}] {nombre[:55]:<55}", end=" ", flush=True)

        exito, msg = descargar_uno(url, destino)

        if exito:
            sha = sha256_archivo(destino)
            log[nombre] = {"estado": "ok", "sha256": sha, "url": url}
            print(f"✓  {msg}")
            ok += 1
        else:
            log[nombre] = {"estado": "error", "error": msg, "url": url}
            print(f"✗  {msg}")
            err += 1

        # Guardar log después de cada descarga (tolerante a interrupciones)
        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))

        time.sleep(PAUSA_ENTRE)

    print(f"\n── RESUMEN ───────────────────────────────")
    print(f"  Total mesas:    {total:>6}")
    print(f"  Descargadas OK: {ok:>6}")
    print(f"  Omitidas (ya existían): {omitidos:>6}")
    print(f"  Errores:        {err:>6}")
    print(f"  Log:            {log_path}")

    return {"ok": ok, "errores": err, "omitidos": omitidos}


def verificar_lote(salida: Path):
    """Verifica que todos los PDFs en la carpeta sean válidos."""
    pdfs = sorted(salida.glob("Dep*-Mesa*.pdf"))
    print(f"\n[VERIFICAR] {len(pdfs)} PDFs en {salida}/\n")
    corruptos = []
    for pdf in pdfs:
        if es_pdf_valido(pdf):
            print(f"  ✓  {pdf.name}")
        else:
            print(f"  ✗  {pdf.name}  ← CORRUPTO o no es PDF")
            corruptos.append(pdf.name)
    print(f"\n  Válidos: {len(pdfs)-len(corruptos)}  /  Corruptos: {len(corruptos)}")
    if corruptos:
        Path(salida / "corruptos.txt").write_text("\n".join(corruptos))
        print(f"  Lista guardada en: {salida}/corruptos.txt")


def main():
    p = argparse.ArgumentParser(
        description="Descargador de actas E-14 — Colombia 2026 2ª vuelta",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EJEMPLOS:
  python3 descargador_e14.py --lista mesas.csv --salida actas/
  python3 descargador_e14.py --verificar --salida actas/

FORMATO CSV (--lista):
  dep,mun,zona,puesto,mesa
  15,001,000,001,001
        """)
    p.add_argument("--lista",     help="CSV con columnas: dep,mun,zona,puesto,mesa")
    p.add_argument("--salida",    default="actas_e14", help="Carpeta de destino")
    p.add_argument("--verificar", action="store_true",
                   help="Solo verificar integridad de los PDFs ya descargados")
    args = p.parse_args()

    salida = Path(args.salida)

    if args.verificar:
        verificar_lote(salida)
        return

    if not args.lista:
        p.print_help()
        print("\n[ERROR] Debes proporcionar --lista con el CSV de mesas.", file=sys.stderr)
        sys.exit(1)

    # Probar que construir_url() está configurada antes de empezar
    try:
        construir_url("15", "001", "000", "001", "001")
    except NotImplementedError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    mesas = leer_lista_csv(args.lista)
    print(f"[OK] {len(mesas)} mesas leídas de {args.lista}")

    descargar_lote(mesas, salida)

    print(f"\n[SIGUIENTE PASO]")
    print(f"  python3 auditor_e14_v2.py {salida}/ --ocr google --google-key clave.json")


if __name__ == "__main__":
    main()
