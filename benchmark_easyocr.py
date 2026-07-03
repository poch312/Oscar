#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
benchmark_easyocr.py — Mide la precisión de EasyOCR contra valores conocidos
=============================================================================
Corre EasyOCR sobre las 3 actas de consulado y compara lo leído contra los
valores verificados visualmente. Pega el resultado en el chat.

USO (en la misma carpeta que auditor_e14_v2.py y actas_nuevas/):
  pip install easyocr
  python3 benchmark_easyocr.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import auditor_e14_v2 as A

# Valores verdaderos verificados visualmente en las actas
VERDAD = {
    "Dep88Mun815Zona005Puesto86Mesa005T0748.pdf": {
        "total_votantes": 88, "total_votos_urna": 88,
        "cepeda": 16, "de_la_espriella": 72, "suma_total": 88,
    },
    "Dep88Mun815Zona065Puesto08Mesa001T0748.pdf": {
        "total_votantes": 51, "total_votos_urna": 51,
        "cepeda": 5, "de_la_espriella": 46,
        "voto_en_blanco": 0, "votos_nulos": 0, "no_marcados": 0,
    },
}

def main():
    carpeta = Path(__file__).parent / "actas_nuevas"
    if not carpeta.exists():
        print(f"[ERROR] No existe {carpeta}/ — pon ahí los 3 PDFs de consulado.")
        return
    print("Cargando EasyOCR (la primera vez descarga ~110 MB)...")
    reco = A.ReconocedorEasyOCR()
    cfg = A.Config()
    out = Path("salida_benchmark")
    out.mkdir(exist_ok=True)

    aciertos = errores = sin_leer = 0
    for pdf in sorted(carpeta.glob("*.pdf")):
        if pdf.name not in VERDAD:
            continue
        print(f"\n=== {pdf.name}")
        acta = A.procesar_pdf_pasada1(pdf, reco, cfg, out)
        esperados = VERDAD[pdf.name]
        for campo, esperado in esperados.items():
            leido = (acta.votos.get(campo) if campo in cfg.candidatos
                     else getattr(acta, campo, None))
            conf = acta.confianza.get(campo)
            conf_s = f"{conf:.0%}" if conf is not None else "—"
            if leido is None:
                marca = "SIN LEER"; sin_leer += 1
            elif leido == esperado:
                marca = "OK"; aciertos += 1
            else:
                marca = "MAL"; errores += 1
            print(f"  {campo:<18} esperado={esperado:>3}  "
                  f"leido={leido if leido is not None else '?':>3}  "
                  f"conf={conf_s:>5}  [{marca}]")

    total = aciertos + errores + sin_leer
    print(f"\n{'='*50}")
    print(f"RESULTADO EasyOCR: {aciertos}/{total} campos correctos "
          f"({aciertos/max(1,total):.0%})")
    print(f"  mal leídos: {errores} | sin leer: {sin_leer}")
    print("Pega esta salida completa en el chat.")

if __name__ == "__main__":
    main()
