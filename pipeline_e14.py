#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_e14.py — Descarga + Auditoría de Actas E-14 en un solo script
=======================================================================
TODO en un archivo: descarga los PDFs y los audita.

PASO 1 — Descarga
  Lee el CSV con la lista de mesas, baja los PDFs del portal de la
  Registraduría y los nombra con el patrón que necesita el auditor:
    Dep{dep}-Mun{mun}-Zona{zona}-Puesto{puesto}-Mesa{mesa}.pdf

PASO 2 — Auditoría forense (triple capa)
  Pasada 1: extracción de señales visuales por PDF
  Pasada 2: calibración batch + scoring
  Pasada 3: Benford + cross-mesa

USO:
  # Descarga + audita
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/

  # Con preconteo oficial y OCR de Google
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/ \\
      --oficiales preconteo.json --ocr google --google-key clave.json

  # Ya tengo los PDFs, solo auditar
  python3 pipeline_e14.py --solo-auditar actas/ --salida resultados/

  # Verificar integridad de PDFs descargados
  python3 pipeline_e14.py --verificar actas/

  # Test interno sin PDFs
  python3 pipeline_e14.py --autotest

FORMATO CSV (--lista):
  dep,mun,zona,puesto,mesa
  15,001,000,001,001
  15,001,000,001,002

DEPENDENCIAS AUDITORÍA: pip install pymupdf opencv-python numpy pytesseract
DEPENDENCIAS OCR GOOGLE: pip install google-cloud-vision
"""
from __future__ import annotations

import argparse, base64, csv, hashlib, json, math, re, sys, time
import urllib.request, urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import numpy as np
    import cv2
    HAY_CV = True
except Exception:
    HAY_CV = False
try:
    import fitz
    HAY_FITZ = True
except Exception:
    HAY_FITZ = False
try:
    import pytesseract
    HAY_TESS = True
except Exception:
    HAY_TESS = False

VERSION = "2.1.0"


# ===========================================================================
# ── CONFIGURA AQUÍ ──────────────────────────────────────────────────────────
# Edita esta función con la URL real del portal de la Registraduría.
# La función recibe los campos del acta y debe devolver la URL del PDF.
# ===========================================================================

def construir_url(dep: str, mun: str, zona: str, puesto: str, mesa: str) -> str:
    """
    Devuelve la URL del PDF para una mesa dada.

    EJEMPLOS de patrones comunes (descomenta el que corresponda):

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
        "Si ya tienes los PDFs descargados usa: --solo-auditar <carpeta>"
    )

# ===========================================================================
# ── FIN DE CONFIGURACIÓN ────────────────────────────────────────────────────
# ===========================================================================


# ===========================================================================
# SECCIÓN 1 — DESCARGA
# ===========================================================================
_REINTENTOS  = 4
_PAUSA_BASE  = 2.0
_PAUSA_ENTRE = 0.5
_TIMEOUT     = 30


def _nombre_pdf(dep, mun, zona, puesto, mesa) -> str:
    return f"Dep{dep}-Mun{mun}-Zona{zona}-Puesto{puesto}-Mesa{mesa}.pdf"


def _sha256_bytes(path: Path) -> str:
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
    for intento in range(1, _REINTENTOS + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (auditor-e14-colombia)"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                contenido = resp.read()
            if len(contenido) < 100:
                return False, f"Respuesta muy pequeña ({len(contenido)} bytes)"
            destino.write_bytes(contenido)
            if not _es_pdf(destino):
                destino.unlink(missing_ok=True)
                return False, "Archivo descargado no es PDF válido"
            return True, f"{len(contenido):,} bytes"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, "HTTP 404 — acta no encontrada"
            if e.code in (429, 503) and intento < _REINTENTOS:
                espera = _PAUSA_BASE * (2 ** (intento - 1))
                print(f"      HTTP {e.code} — reintentando en {espera:.0f}s...")
                time.sleep(espera)
            else:
                return False, f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if intento < _REINTENTOS:
                espera = _PAUSA_BASE * (2 ** (intento - 1))
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
    """Descarga los PDFs. Devuelve cantidad disponible al final."""
    carpeta_pdfs.mkdir(parents=True, exist_ok=True)
    log_path = carpeta_pdfs / "_descarga_log.json"
    log: dict = {}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text())
        except Exception:
            pass

    total = len(mesas)
    ok_n = err = omitidos = 0

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
            log[nombre] = {"estado": "ok", "sha256": _sha256_bytes(destino), "url": url}
            print(f"✓  {msg}")
            ok_n += 1
        else:
            log[nombre] = {"estado": "error", "error": msg, "url": url}
            print(f"✗  {msg}")
            err += 1
        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))
        time.sleep(_PAUSA_ENTRE)

    pdfs_ok = ok_n + omitidos
    print(f"\n  Descargadas: {ok_n}  |  Ya existían: {omitidos}  |  Errores: {err}")
    print(f"  PDFs disponibles para auditar: {pdfs_ok}\n")
    return pdfs_ok


def verificar_pdfs(carpeta: Path):
    """Verifica que todos los PDFs en la carpeta sean válidos."""
    pdfs = sorted(carpeta.glob("Dep*-Mesa*.pdf"))
    print(f"\n[VERIFICAR] {len(pdfs)} PDFs en {carpeta}/\n")
    corruptos = []
    for pdf in pdfs:
        if _es_pdf(pdf):
            print(f"  ✓  {pdf.name}")
        else:
            print(f"  ✗  {pdf.name}  ← CORRUPTO o no es PDF")
            corruptos.append(pdf.name)
    print(f"\n  Válidos: {len(pdfs)-len(corruptos)}  /  Corruptos: {len(corruptos)}")
    if corruptos:
        (carpeta / "corruptos.txt").write_text("\n".join(corruptos))
        print(f"  Lista guardada en: {carpeta}/corruptos.txt")


# ===========================================================================
# SECCIÓN 2 — AUDITORÍA (todo el motor de auditor_e14_v2)
# ===========================================================================

# ── Configuración ──────────────────────────────────────────────────────────
@dataclass
class Config:
    candidatos: tuple       = ("cepeda", "de_la_espriella")
    eleccion_esperada: str  = "presidencia_2v_2026"
    dpi: int                = 300
    score_umbral_urgente: float = 40.0
    score_umbral_revisar: float = 20.0
    n_sigma_outlier: float  = 2.0
    min_familias_coocurrentes: int = 2
    umbral_confianza_ocr: float = 0.70
    max_sufragantes_mesa: int   = 400
    tolerancia_nivelacion: int  = 2
    umbral_incineracion: float  = 0.10
    z_cross_mesa: float     = 3.0
    chi2_benford_critico: float = 20.09
    umbral_firma_jurado: float  = 0.015
    software_sospechoso: tuple = (
        "photoshop", "gimp", "inkscape", "illustrator", "coreldraw",
        "paint", "krita", "affinity", "canva", "pixelmator",
    )
    huecos_esperados: dict = field(default_factory=lambda: {
        "0": 1, "1": 0, "2": 0, "3": 0, "5": 0,
        "6": 1, "7": 0, "8": 2, "9": 1
    })


# ── Modelo de datos ────────────────────────────────────────────────────────
class Tier(Enum):
    URGENTE = "URGENTE"
    REVISAR = "REVISAR"
    MANUAL  = "MANUAL"
    LIMPIA  = "LIMPIA"

@dataclass
class SeñalesRaw:
    campo: str
    casilla: int
    densidad: float = 0.0
    n_componentes: int = 0
    n_huecos: int = 0
    dens_interior_lazo: float = 0.0
    cv_ancho_trazo: float = 0.0
    tiene_trazo_horiz: bool = False
    tiene_trazo_h_top: bool = False  # trazo horizontal en el tercio superior (señal de 7/4)
    borrado_score: float = 0.0
    digito_ocr: Optional[str] = None
    conf_ocr: float = 0.0
    clase: str = "vacia"

@dataclass
class Hallazgo:
    familia: str
    campo: str
    mensaje: str
    score_aporte: float
    evidencia_img: Optional[str] = None

@dataclass
class ActaE14:
    archivo: str
    hash_sha256: Optional[str] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    zona: Optional[str] = None
    puesto: Optional[str] = None
    mesa: Optional[str] = None
    votos: dict = field(default_factory=dict)
    total_votos_urna: Optional[int] = None
    total_votantes: Optional[int] = None
    votos_incinerados: Optional[int] = None
    voto_en_blanco: Optional[int] = None
    votos_nulos: Optional[int] = None
    no_marcados: Optional[int] = None
    suma_total: Optional[int] = None
    confianza: dict = field(default_factory=dict)
    señales_raw: list = field(default_factory=list)
    hallazgos: list = field(default_factory=list)
    score: float = 0.0
    tier: Tier = Tier.LIMPIA
    dir_evidencia: Optional[str] = None
    alineacion_ok: Optional[bool] = None
    fallo_extraccion: Optional[str] = None
    pdf_software: Optional[str] = None
    pdf_fecha_creacion: Optional[str] = None
    firmas_jurados: Optional[list] = None

    @property
    def id_mesa(self) -> str:
        return "-".join(x or "?" for x in [
            self.departamento, self.municipio, self.zona, self.puesto, self.mesa])

    @property
    def id_puesto(self) -> str:
        return "-".join(x or "?" for x in [
            self.departamento, self.municipio, self.zona, self.puesto])


# ── OCR ────────────────────────────────────────────────────────────────────
class Reconocedor:
    def leer(self, roi_gris) -> tuple[Optional[str], float]:
        raise NotImplementedError

class ReconocedorTesseract(Reconocedor):
    _CONFIGS = [
        "--psm 10 -c tessedit_char_whitelist=0123456789",
        "--psm 8  -c tessedit_char_whitelist=0123456789",
        "--psm 7  -c tessedit_char_whitelist=0123456789",
        "--psm 13 -c tessedit_char_whitelist=0123456789",
    ]

    def leer(self, roi):
        if not HAY_TESS:
            return None, 0.0
        try:
            h, w = roi.shape[:2]
            up = cv2.resize(roi, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            blur = cv2.GaussianBlur(up, (3, 3), 0)
            _, prep = cv2.threshold(blur, 0, 255,
                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        except Exception:
            prep = roi

        best_txt, best_conf = None, -1.0
        for cfg in self._CONFIGS:
            try:
                data = pytesseract.image_to_data(
                    prep, config=cfg,
                    output_type=pytesseract.Output.DICT)
                for txt, conf in zip(data["text"], data["conf"]):
                    txt = txt.strip()
                    try:
                        conf = float(conf)
                    except Exception:
                        continue
                    if txt.isdigit() and conf > best_conf:
                        best_txt, best_conf = txt[0], conf
                if best_conf >= 60.0:
                    break
            except Exception:
                continue
        return (best_txt, max(0.0, best_conf) / 100.0) if best_txt else (None, 0.0)

class ReconocedorGoogleVision(Reconocedor):
    def __init__(self, clave_json: str):
        try:
            import os
            from google.cloud import vision as gv
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = clave_json
            self.client = gv.ImageAnnotatorClient()
            self.vision = gv
        except ImportError:
            raise RuntimeError("pip install google-cloud-vision")

    def leer(self, roi):
        _, buf = cv2.imencode(".png", roi)
        img = self.vision.Image(content=bytes(buf))
        resp = self.client.text_detection(image=img)
        for ann in resp.text_annotations[1:]:
            t = ann.description.strip()
            if t.isdigit() and len(t) == 1:
                return t, 0.95
        return None, 0.0


# ── Utilidades ─────────────────────────────────────────────────────────────
_PATRON_NOMBRE = re.compile(
    r"Dep(\d+)-?Mun(\d+)-?Zona(\d+)-?Puesto(\d+)-?Mesa(\d+)", re.I)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()

def identidad_desde_nombre(acta: ActaE14, path: Path) -> bool:
    m = _PATRON_NOMBRE.search(path.name)
    if not m: return False
    acta.departamento, acta.municipio, acta.zona, acta.puesto, acta.mesa = m.groups()
    return True

def _preprocess(gris: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gris)

def _detectar_borrado(roi_gris: np.ndarray) -> float:
    H, W = roi_gris.shape
    if H * W < 50:
        return 0.0
    zona = (roi_gris >= 130) & (roi_gris <= 220)
    frac = float(np.mean(zona))
    if frac < 0.08:
        return 0.0
    pixeles = roi_gris[zona]
    if pixeles.size < 20:
        return 0.0
    varianza = float(np.std(pixeles))
    if varianza < 5.0:
        return 0.0
    return min(1.0, frac * varianza / 180.0)


# ── Detección de estructura ────────────────────────────────────────────────
def detectar_lineas_horizontales(gris: np.ndarray) -> list[int]:
    H, W = gris.shape
    _, b = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (W // 3, 2))
    h = cv2.morphologyEx(b, cv2.MORPH_OPEN, k)
    cnts, _ = cv2.findContours(h, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ys_raw = sorted(
        cv2.boundingRect(c)[1] + cv2.boundingRect(c)[3] // 2
        for c in cnts if cv2.boundingRect(c)[2] > W // 3)
    ys: list[int] = []
    for y in ys_raw:
        if not ys or y - ys[-1] > 30:
            ys.append(y)
    return ys

def detectar_columna_nums(gris: np.ndarray) -> tuple[int, int]:
    H, W = gris.shape
    _, b = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, H // 8))
    v = cv2.morphologyEx(b, cv2.MORPH_OPEN, k)
    cnts, _ = cv2.findContours(v, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    xs = sorted(
        cv2.boundingRect(c)[0] for c in cnts
        if cv2.boundingRect(c)[3] > H // 8 and cv2.boundingRect(c)[0] > W * 0.6)
    if len(xs) >= 4:
        return xs[-4], (W - 40) - xs[-4]
    return int(W * 0.84), int(W * 0.13)

def asignar_filas(ys: list[int], candidatos: tuple,
                  gris: Optional[np.ndarray] = None) -> dict[str, tuple[int, int]]:
    filas = [(ys[i], ys[i+1]) for i in range(len(ys)-1) if ys[i+1]-ys[i] > 80]
    if len(filas) < 8:
        return {}
    asig: dict[str, tuple[int, int]] = {}

    # Candidatos: las N filas más altas en la zona media, asignadas de arriba hacia abajo.
    n_cands = max(len(candidatos), 1)
    filas_por_altura = sorted(filas[5:-5], key=lambda f: f[1]-f[0], reverse=True)
    candidato_filas = sorted(filas_por_altura[:n_cands * 2][:n_cands], key=lambda f: f[0])
    for i, cand in enumerate(candidatos):
        if i < len(candidato_filas):
            asig[cand] = candidato_filas[i]

    # NIVELACIÓN: buscar la franja "NIVELACIÓN DE LA MESA" (fondo negro, texto blanco).
    # Es la primera franja oscura de la página (media de píxeles < 120).
    # Las 3 filas que le siguen son total_votantes, total_votos_urna, votos_incinerados.
    niv_encontrada = False
    if gris is not None:
        for i, (y1, y2) in enumerate(filas):
            if float(np.mean(gris[y1:y2, :])) < 120 and i + 3 < len(filas):
                niv = filas[i + 1: i + 4]
                asig["total_votantes"]    = niv[0]
                asig["total_votos_urna"]  = niv[1]
                asig["votos_incinerados"] = niv[2]
                niv_encontrada = True
                break

    if not niv_encontrada:
        # Fallback sin imagen: 3 filas antes de donde empiezan los candidatos
        cands_ordenadas = sorted(candidato_filas[:max(len(candidatos), 1)], key=lambda f: f[0])
        inicio_cands = cands_ordenadas[0][0] if cands_ordenadas else filas[4][1]
        filas_antes = [f for f in filas if f[1] <= inicio_cands]
        if len(filas_antes) >= 3:
            niv = filas_antes[-3:]
            asig["total_votantes"]    = niv[0]
            asig["total_votos_urna"]  = niv[1]
            asig["votos_incinerados"] = niv[2]
        else:
            asig["total_votantes"]    = filas[1]
            asig["total_votos_urna"]  = filas[2]
            asig["votos_incinerados"] = filas[3]

    # Pie: últimas filas del formulario
    asig["voto_en_blanco"] = filas[-5]
    asig["votos_nulos"]    = filas[-4]
    asig["no_marcados"]    = filas[-3]
    asig["suma_total"]     = filas[-2]
    return asig


# ── Pasada 1: extracción de señales raw ────────────────────────────────────
def _clasificar_blob(binaria: np.ndarray, area_min: int,
                     gris_original: Optional[np.ndarray] = None) -> tuple[str, dict]:
    H, W = binaria.shape
    area_celda = max(1, H * W)
    info: dict = {"densidad": float(np.mean(binaria > 0))}
    if info["densidad"] < 0.005:
        return "vacia", info
    n, _, stats, _ = cv2.connectedComponentsWithStats(binaria, 8)
    comps = [(i, stats[i]) for i in range(1, n)
             if stats[i, cv2.CC_STAT_AREA] >= area_min]
    if not comps:
        return "vacia", info
    _, stat_dom = max(comps, key=lambda x: x[1][cv2.CC_STAT_AREA])
    bw = max(1, int(stat_dom[cv2.CC_STAT_WIDTH]))
    bh = max(1, int(stat_dom[cv2.CC_STAT_HEIGHT]))
    area_dom  = int(stat_dom[cv2.CC_STAT_AREA])
    frac_celda = area_dom / area_celda
    fill_ratio = area_dom / max(1, bw * bh)
    aspect     = min(bw, bh) / max(bw, bh)
    info.update({"frac_celda": frac_celda, "fill_ratio": fill_ratio, "aspect": aspect})
    es_blob = fill_ratio > 0.55 and aspect > 0.30 and frac_celda > 0.02
    if not es_blob:
        return "digito", info
    bx = int(stat_dom[cv2.CC_STAT_LEFT])
    by = int(stat_dom[cv2.CC_STAT_TOP])
    info["cv_intensidad_blob"] = 0.0
    if gris_original is not None:
        roi_b = gris_original[by:by+bh, bx:bx+bw]
        oscuros = roi_b[roi_b < 200]
        if oscuros.size >= 20:
            m_g = float(np.mean(oscuros))
            cv_int = float(np.std(oscuros) / m_g) if m_g > 0 else 0.0
            info["cv_intensidad_blob"] = cv_int
            if cv_int > 0.12:
                return "void_con_digito", info
    return "void", info


def extraer_señales_casilla(roi_gris: np.ndarray, cfg: Config,
                             campo: str, casilla_idx: int,
                             reco: Reconocedor,
                             ruta_recorte: Path) -> SeñalesRaw:
    s = SeñalesRaw(campo=campo, casilla=casilla_idx)
    roi_prep = _preprocess(roi_gris)
    _, b = cv2.threshold(roi_prep, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2)))
    W_b = b.shape[1]
    # 90 % umbral: elimina líneas de tabla (~100 % ancho) pero preserva trazos de dígitos
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, W_b * 9 // 10), 2))
    bordes_h = cv2.morphologyEx(b, cv2.MORPH_OPEN, k_h)
    b = cv2.bitwise_and(b, cv2.bitwise_not(bordes_h))
    area_total = b.shape[0] * b.shape[1]
    area_min = max(10, int(area_total * 0.005))
    clase_blob, info_blob = _clasificar_blob(b, area_min, gris_original=roi_gris)
    s.densidad = info_blob["densidad"]
    if clase_blob == "vacia":
        s.clase = "vacia"
        s.borrado_score = _detectar_borrado(roi_gris)
        return s
    if clase_blob == "void":
        s.clase = "void"
        return s
    if clase_blob == "void_con_digito":
        s.clase = "void_con_digito"
        cv2.imwrite(str(ruta_recorte), roi_gris)
        return s
    s.clase = "digito"
    cv2.imwrite(str(ruta_recorte), roi_gris)
    s.borrado_score = _detectar_borrado(roi_gris)
    n, _, stats_cc, _ = cv2.connectedComponentsWithStats(b, 8)
    s.n_componentes = sum(1 for i in range(1, n)
                          if stats_cc[i, cv2.CC_STAT_AREA] >= area_min)
    cont, jer = cv2.findContours(b, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if jer is not None:
        jer = jer[0]
        for i, c in enumerate(cont):
            if jer[i][3] == -1 or cv2.contourArea(c) < area_min:
                continue
            s.n_huecos += 1
            m = np.zeros(b.shape, np.uint8)
            cv2.drawContours(m, [c], -1, 255, cv2.FILLED)
            m = cv2.erode(m, np.ones((3, 3), np.uint8), 2)
            if cv2.countNonZero(m):
                s.dens_interior_lazo = max(
                    s.dens_interior_lazo,
                    float(np.mean(b[m == 255] > 0)))
    dist = cv2.distanceTransform(b, cv2.DIST_L2, 5)
    v = dist[dist > 0.5]
    if v.size >= 10:
        m_v = float(np.mean(v))
        s.cv_ancho_trazo = float(np.std(v) / m_v) if m_v > 0 else 0.0
    largo = max(3, int(W_b * 0.55))
    k_t = cv2.getStructuringElement(cv2.MORPH_RECT, (largo, 1))
    s.tiene_trazo_horiz = cv2.countNonZero(
        cv2.morphologyEx(b, cv2.MORPH_OPEN, k_t)) > 0
    # Tercio superior del DÍGITO normalizado al ancho real del dígito (no al de la casilla).
    # Filas que son "trazo de dígito": entre 5 % y 92 % del ancho de la casilla.
    _row_pcts = np.sum(b > 0, axis=1).astype(float) / max(1, W_b)
    _d_rows = np.where((_row_pcts > 0.05) & (_row_pcts < 0.92))[0]
    if _d_rows.size >= 3:
        _dg_mask = np.zeros_like(b); _dg_mask[_d_rows] = b[_d_rows]
        _xs_dig = np.where(np.sum(_dg_mask > 0, axis=0) > 0)[0]
        _W_dig = int(_xs_dig.max()) - int(_xs_dig.min()) + 1 if _xs_dig.size > 0 else W_b
        _largo_dig = max(3, int(_W_dig * 0.55))
        _k_t_dig = cv2.getStructuringElement(cv2.MORPH_RECT, (_largo_dig, 1))
        _y0_d = int(_d_rows.min()); _h_d = max(1, int(_d_rows.max()) - _y0_d)
        b_dig_top = b[_y0_d : _y0_d + _h_d // 3, :]
        s.tiene_trazo_h_top = cv2.countNonZero(
            cv2.morphologyEx(b_dig_top, cv2.MORPH_OPEN, _k_t_dig)) > 0
    else:
        s.tiene_trazo_h_top = False
    s.digito_ocr, s.conf_ocr = reco.leer(roi_gris)
    if not s.digito_ocr:
        s.clase = "ilegible"
    return s


def _segmentar_casillas(roi_num: np.ndarray) -> list[tuple[int, int]]:
    W = roi_num.shape[1]
    if W < 9:
        paso = max(1, W // 3)
        return [(0, paso), (paso, 2*paso), (2*paso, W)]
    dark = (roi_num < 100).astype(np.float32)
    proj = dark.mean(axis=0)
    k = max(1, W // 20)
    proj_s = np.convolve(proj, np.ones(k) / k, mode="same")
    margin = max(2, W // 8)
    cortes: list[int] = []
    for tercio in [W // 3, 2 * W // 3]:
        a, b_ = max(0, tercio - margin), min(W, tercio + margin)
        zona = proj_s[a:b_]
        if zona.size > 0:
            cortes.append(a + int(np.argmin(zona)))
    if len(cortes) == 2 and cortes[0] < cortes[1]:
        return [(0, cortes[0]), (cortes[0], cortes[1]), (cortes[1], W)]
    paso = W // 3
    return [(0, paso), (paso, 2*paso), (2*paso, W)]


def _componer_valor(señales: list[SeñalesRaw], cfg: Config) -> tuple[Optional[int], float]:
    slots = sorted(señales, key=lambda s: s.casilla)
    digitos: list[str] = []
    conf_total = 0.0
    n = 0
    toda_vacia = True
    for s in slots:
        if s.clase == "vacia":
            digitos.append("0"); conf_total += 1.0; n += 1
        elif s.clase == "void":
            return None, 0.0
        elif s.clase == "void_con_digito":
            digitos.append(s.digito_ocr or "?"); conf_total += 0.3; n += 1; toda_vacia = False
        elif s.clase == "digito" and s.digito_ocr:
            digitos.append(s.digito_ocr); conf_total += s.conf_ocr; n += 1; toda_vacia = False
        else:
            return None, 0.0
    if toda_vacia:
        return 0, 1.0
    valor_str = "".join(digitos).lstrip("0") or "0"
    if "?" in valor_str:
        return None, 0.0
    try:
        return int(valor_str), conf_total / max(1, n)
    except ValueError:
        return None, 0.0


_CAMPOS_DIRECTOS = {
    "total_votos_urna", "total_votantes", "votos_incinerados",
    "voto_en_blanco", "votos_nulos", "no_marcados", "suma_total",
}

def _analizar_metadata_pdf(doc, acta: ActaE14, cfg: Config) -> list[Hallazgo]:
    hs: list[Hallazgo] = []
    try:
        meta = doc.metadata or {}
        creador = (meta.get("creator", "") or meta.get("producer", "") or "").lower()
        fecha   = meta.get("creationDate", "")
        acta.pdf_software = creador
        acta.pdf_fecha_creacion = fecha
        for sw in cfg.software_sospechoso:
            if sw in creador:
                hs.append(Hallazgo(
                    "H", "pdf_metadata",
                    f"PDF generado con '{creador}' — software de edición, no escáner. "
                    f"Posible falsificación completa del documento.", 70.0))
                break
        if not creador and not meta.get("title"):
            hs.append(Hallazgo(
                "H", "pdf_metadata",
                "PDF sin metadatos de origen — inusual en escáneres oficiales.", 15.0))
    except Exception:
        pass
    return hs


def _auditar_firmas_jurados(doc, acta: ActaE14, cfg: Config,
                             out: Path) -> list[Hallazgo]:
    """
    Familia J: detecta si las 6 firmas de jurados están presentes (página 2).
    Divide la franja inferior de la página en 2 filas × 3 columnas y mide
    densidad de tinta en la zona de firma (mitad inferior de cada celda,
    para evitar el texto "JURADO N" en la mitad superior).
    """
    if not HAY_CV or doc.page_count < 2:
        return []
    try:
        pix = doc.load_page(1).get_pixmap(dpi=150)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(
            pix.height, pix.width, pix.n)
        gris = cv2.cvtColor(
            cv2.cvtColor(arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR),
            cv2.COLOR_BGR2GRAY)
    except Exception:
        return []
    H, W = gris.shape
    # Las firmas ocupan la franja 60-95% de la altura de la página 2
    y1 = int(H * 0.60)
    y2 = int(H * 0.95)
    zona = gris[y1:y2, :]
    Hz = zona.shape[0]
    firmas: list[bool] = []
    for fila in range(2):
        y_ini = int(fila * Hz / 2)
        y_fin = int((fila + 1) * Hz / 2)
        y_firma = y_ini + (y_fin - y_ini) // 2  # mitad inferior → zona manuscrita
        for col in range(3):
            x_ini = int(col * W / 3) + 10
            x_fin = int((col + 1) * W / 3) - 10
            roi = zona[y_firma:y_fin, x_ini:x_fin]
            if roi.size == 0:
                firmas.append(False)
                continue
            densidad = float(np.mean(roi < 128))
            tiene_firma = densidad > cfg.umbral_firma_jurado
            firmas.append(tiene_firma)
            n_jurado = fila * 3 + col + 1
            cv2.imwrite(str(out / f"jurado{n_jurado}_firma.png"), roi)
    acta.firmas_jurados = firmas
    ausentes = [i + 1 for i, f in enumerate(firmas) if not f]
    if not ausentes:
        return []
    n = len(ausentes)
    aporte = min(50.0, n * 12.0)
    return [Hallazgo(
        "J", "firmas_jurados",
        f"Faltan {n}/6 firma(s) de jurado(s) #{ausentes} — "
        f"acta posiblemente no firmada o incompleta.",
        aporte)]


def procesar_pdf_pasada1(pdf_path: Path, reco: Reconocedor,
                          cfg: Config, dir_evi: Path) -> ActaE14:
    acta = ActaE14(archivo=str(pdf_path))
    acta.hash_sha256 = sha256(pdf_path)
    identidad_desde_nombre(acta, pdf_path)
    slug = re.sub(r"[^A-Za-z0-9_-]", "_",
                  f"{acta.id_mesa}_{(acta.hash_sha256 or 'x')[:8]}")
    out = dir_evi / slug
    out.mkdir(parents=True, exist_ok=True)
    acta.dir_evidencia = str(out)
    try:
        doc = fitz.open(pdf_path)
        _meta_hallazgos  = _analizar_metadata_pdf(doc, acta, cfg)
        _firma_hallazgos = _auditar_firmas_jurados(doc, acta, cfg, out)
        pix = doc.load_page(0).get_pixmap(dpi=cfg.dpi)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        img_bgr = cv2.cvtColor(
            arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR)
        gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    except Exception as e:
        acta.fallo_extraccion = f"No se pudo rasterizar: {e}"
        return acta
    H, W = gris.shape
    ys = detectar_lineas_horizontales(gris)
    if len(ys) < 10:
        acta.fallo_extraccion = f"Solo {len(ys)} líneas horizontales; PDF ilegible."
        return acta
    x_col, w_col = detectar_columna_nums(gris)
    asig = asignar_filas(ys, cfg.candidatos, gris)
    if not asig:
        acta.fallo_extraccion = "No se pudo asignar filas al acta."
        return acta
    acta._meta_hallazgos  = _meta_hallazgos   # type: ignore[attr-defined]
    acta._firma_hallazgos = _firma_hallazgos  # type: ignore[attr-defined]
    for campo, (y1, y2) in asig.items():
        try:
            y1c, y2c = max(0, y1+5), min(H, y2-5)
            roi_campo = gris[y1c:y2c, max(0, x_col): min(W, x_col+w_col)]
            if roi_campo.size == 0:
                continue
            dens_rows = np.mean(roi_campo < 100, axis=1)
            filas_tinta = np.where(dens_rows > 0.01)[0]
            if len(filas_tinta) == 0:
                continue
            if filas_tinta[-1] - filas_tinta[0] < roi_campo.shape[0] * 0.4:
                pad = 10
                roi_num = roi_campo[
                    max(0, filas_tinta[0]-pad):
                    min(roi_campo.shape[0], filas_tinta[-1]+pad), :]
            else:
                roi_num = roi_campo
            casillas = _segmentar_casillas(roi_num)
            señales_campo: list[SeñalesRaw] = []
            for ci, (x0, x1) in enumerate(casillas):
                cas = roi_num[:, x0:x1]
                if cas.size == 0:
                    continue
                rp = out / f"{campo}_cas{ci}.png"
                señal = extraer_señales_casilla(cas, cfg, campo, ci, reco, rp)
                acta.señales_raw.append(señal)
                señales_campo.append(señal)
            valor, conf = _componer_valor(señales_campo, cfg)
            if valor is not None:
                acta.confianza[campo] = conf
                if campo in cfg.candidatos:
                    acta.votos[campo] = valor
                elif campo in _CAMPOS_DIRECTOS:
                    setattr(acta, campo, valor)
        except Exception:
            pass
    return acta


# ── Pasada 2: calibración + scoring ────────────────────────────────────────
@dataclass
class EstadisticasBatch:
    por_campo: dict = field(default_factory=dict)

def calcular_estadisticas_batch(actas: list[ActaE14]) -> EstadisticasBatch:
    from collections import defaultdict
    eb = EstadisticasBatch()
    acum: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for acta in actas:
        for s in acta.señales_raw:
            if s.clase not in ("digito", "ilegible", "vacia"):
                continue
            acum[s.campo]["dens_interior_lazo"].append(s.dens_interior_lazo)
            acum[s.campo]["cv_ancho_trazo"].append(s.cv_ancho_trazo)
            acum[s.campo]["n_componentes"].append(float(s.n_componentes))
            acum[s.campo]["n_huecos"].append(float(s.n_huecos))
            acum[s.campo]["borrado_score"].append(s.borrado_score)
    for campo, señales in acum.items():
        eb.por_campo[campo] = {}
        for señal, valores in señales.items():
            if len(valores) < 3:
                eb.por_campo[campo][señal] = (0.0, float("inf"), float("inf"))
            else:
                a = np.array(valores, dtype=float)
                mu  = float(np.mean(a))
                std = float(np.std(a))
                q1  = float(np.percentile(a, 25))
                q3  = float(np.percentile(a, 75))
                iqr = q3 - q1
                eb.por_campo[campo][señal] = (mu, max(std, 1e-6), q3 + 1.5 * iqr)
    return eb

def es_outlier(valor: float, media: float, std: float, n_sigma: float,
               upper_iqr: float = float("inf")) -> bool:
    return (std > 0 and (valor - media) > n_sigma * std) or (valor > upper_iqr)

def evaluar_señal_visual(s: SeñalesRaw, eb: EstadisticasBatch,
                          cfg: Config) -> list[tuple[str, str, float]]:
    hallazgos: list[tuple[str, str, float]] = []
    stats = eb.por_campo.get(s.campo, {})
    def _get(señal: str) -> tuple[float, float, float]:
        return stats.get(señal, (0.0, 1e-6, float("inf")))
    m, std, uiqr = _get("borrado_score")
    if s.borrado_score > 0.10 and es_outlier(s.borrado_score, m, std, cfg.n_sigma_outlier, uiqr):
        msg_extra = " (casilla vacía — número fue borrado)" if s.clase == "vacia" else ""
        hallazgos.append(("G",
            f"Grafito residual de borrado (score={s.borrado_score:.2f}){msg_extra}", 25.0))
    if s.clase in ("vacia", "void", "void_con_digito"):
        return hallazgos
    # Blob grande sin lectura OCR = círculo pre-impreso (●) con artefacto de escáner,
    # no dígito manuscrito. Densidad > 0.30 distingue un ● de un trazo fino de pluma.
    if s.densidad > 0.30 and not s.digito_ocr:
        return hallazgos
    if s.digito_ocr and s.digito_ocr in cfg.huecos_esperados:
        esperados = cfg.huecos_esperados[s.digito_ocr]
        if s.n_huecos != esperados:
            hallazgos.append(("A",
                f"Topología: OCR='{s.digito_ocr}' esperaba {esperados} hueco(s), "
                f"encontró {s.n_huecos}", 25.0))
    m, std, uiqr = _get("dens_interior_lazo")
    if s.dens_interior_lazo > 0.05 and es_outlier(s.dens_interior_lazo, m, std, cfg.n_sigma_outlier, uiqr):
        hallazgos.append(("A",
            f"Trazo dentro del lazo ({s.dens_interior_lazo:.0%}); batch: {m:.2f}±{std:.2f}", 30.0))
    m, std, uiqr = _get("cv_ancho_trazo")
    if es_outlier(s.cv_ancho_trazo, m, std, cfg.n_sigma_outlier, uiqr):
        hallazgos.append(("B",
            f"Ancho de trazo mixto (cv={s.cv_ancho_trazo:.2f}); batch: {m:.2f}±{std:.2f}", 20.0))
    if s.tiene_trazo_horiz and s.digito_ocr in ("1",):
        hallazgos.append(("C",
            f"Trazo horizontal largo en '{s.digito_ocr}' (posible guion→1)", 25.0))
    m, std, uiqr = _get("n_componentes")
    if es_outlier(float(s.n_componentes), m, std, cfg.n_sigma_outlier + 0.5, uiqr):
        hallazgos.append(("C",
            f"Componentes anómalos ({s.n_componentes} vs batch {m:.1f}±{std:.1f})", 15.0))
    return hallazgos

def scoring_acta(acta: ActaE14, eb: EstadisticasBatch,
                  cfg: Config, oficiales: dict) -> None:
    acta.hallazgos = []
    score = 0.0
    meta_hs = getattr(acta, "_meta_hallazgos", [])
    for h in meta_hs:
        acta.hallazgos.append(h)
        score += h.score_aporte
    firma_hs = getattr(acta, "_firma_hallazgos", [])
    for h in firma_hs:
        acta.hallazgos.append(h)
        score += h.score_aporte
    for s in acta.señales_raw:
        if s.clase == "void_con_digito":
            ruta = str(Path(acta.dir_evidencia or ".") / f"{s.campo}_cas{s.casilla}.png")
            acta.hallazgos.append(Hallazgo(
                "A", s.campo,
                f"Casilla {s.casilla+1} de '{s.campo}': blob ● con trazos adicionales — "
                f"posible dígito escrito encima.", 65.0, ruta))
            score += 65.0
    # G — Dígito de centenas con trazo horizontal en el tercio SUPERIOR cuando votantes ≤ 299
    if acta.total_votantes is not None and acta.total_votantes <= 299:
        for s in acta.señales_raw:
            if (s.campo in cfg.candidatos
                    and s.casilla == 0
                    and s.tiene_trazo_h_top
                    and s.clase in ("digito", "ilegible", "void_con_digito")):
                acta.hallazgos.append(Hallazgo(
                    "G", "centenas_trazo_horiz",
                    f"Centenas de '{s.campo}' con trazo horizontal en parte alta (posible 7 o 4) "
                    f"— imposible con solo {acta.total_votantes} votantes registrados.", 80.0))
                score += 80.0

    # D — Votos de un candidato superan la urna (check parcial, no requiere todos los campos)
    urna_ref = acta.total_votos_urna or acta.total_votantes
    if urna_ref is not None:
        for cand, voto in acta.votos.items():
            if voto is not None and voto > urna_ref:
                acta.hallazgos.append(Hallazgo(
                    "D", "votos_exceden_urna",
                    f"Candidato '{cand}' con {voto} votos supera la urna/votantes "
                    f"({urna_ref}) — aritméticamente imposible.", 100.0))
                score += 100.0

    # D — Aritmética completa
    comp = [acta.votos.get(c) for c in cfg.candidatos]
    comp += [acta.voto_en_blanco, acta.votos_nulos, acta.no_marcados]
    if all(v is not None for v in comp) and acta.total_votos_urna is not None:
        suma = sum(comp)
        if suma != acta.total_votos_urna:
            campos_ocr = list(cfg.candidatos) + ["voto_en_blanco", "votos_nulos",
                                                  "no_marcados", "total_votos_urna"]
            conf_min = min((acta.confianza.get(c, 1.0) for c in campos_ocr), default=1.0)
            if conf_min >= cfg.umbral_confianza_ocr:
                dif = suma - acta.total_votos_urna
                acta.hallazgos.append(Hallazgo(
                    "D", "aritmetica", f"Suma {suma} ≠ urna {acta.total_votos_urna} (Δ={dif:+d})", 50.0))
                score += 50.0
            else:
                acta.hallazgos.append(Hallazgo(
                    "D", "aritmetica",
                    f"Descuadre aritmético ({suma} vs {acta.total_votos_urna}) "
                    f"— confianza OCR baja ({conf_min:.0%})", 10.0))
                score += 10.0
        if acta.suma_total is not None and acta.suma_total != suma:
            acta.hallazgos.append(Hallazgo(
                "D", "suma_total",
                f"Suma escrita por jurados ({acta.suma_total}) ≠ calculada ({suma})", 40.0))
            score += 40.0
    V, U, I = acta.total_votantes, acta.total_votos_urna, acta.votos_incinerados
    if V is not None and U is not None:
        if U > V:
            acta.hallazgos.append(Hallazgo(
                "E", "nivelacion", f"Urna ({U}) > votantes E-11 ({V}): físicamente imposible", 60.0))
            score += 60.0
        elif U < V:
            dif = V - U
            sev = 60.0 if dif > cfg.tolerancia_nivelacion else 10.0
            acta.hallazgos.append(Hallazgo(
                "E", "nivelacion",
                f"Urna ({U}) < votantes E-11 ({V}), faltante {dif}"
                + (f" — incinerados ({I}) no cierran la brecha" if I and U+I != V else ""),
                sev))
            score += sev
    if I is not None and I > 0:
        base = V or U
        if base and I / base > cfg.umbral_incineracion:
            acta.hallazgos.append(Hallazgo(
                "E", "votos_incinerados",
                f"Incineración inusualmente alta: {I} = {I/base:.0%} del total", 20.0))
            score += 20.0
    if oficiales:
        of = oficiales.get(acta.id_mesa, {})
        for campo in list(cfg.candidatos) + ["voto_en_blanco", "votos_nulos",
                                              "no_marcados", "total_votos_urna"]:
            leido = (acta.votos.get(campo) if campo in cfg.candidatos
                     else getattr(acta, campo, None))
            ov = of.get(campo)
            if leido is not None and ov is not None and leido != ov:
                acta.hallazgos.append(Hallazgo(
                    "F", campo,
                    f"E-14={leido} vs preconteo oficial={ov} (Δ={leido-ov:+d})", 55.0))
                score += 55.0
    señales_por_campo: dict[str, list[SeñalesRaw]] = {}
    for s in acta.señales_raw:
        señales_por_campo.setdefault(s.campo, []).append(s)
    alertas_candidatos: dict[str, list] = {}
    for campo, señales_campo in señales_por_campo.items():
        hallazgos_campo: list[tuple[str, str, float]] = []
        ruta_evidencia = None
        for s in señales_campo:
            h = evaluar_señal_visual(s, eb, cfg)
            hallazgos_campo.extend(h)
            if h and s.clase == "digito":
                ruta_evidencia = str(
                    Path(acta.dir_evidencia or ".") / f"{campo}_cas{s.casilla}.png")
        familias = set(fam for fam, _, _ in hallazgos_campo)
        if len(familias) >= cfg.min_familias_coocurrentes:
            aporte = sum(ap for _, _, ap in hallazgos_campo)
            desc = "; ".join(f"[{fam}] {msg}" for fam, msg, _ in hallazgos_campo)
            acta.hallazgos.append(Hallazgo(
                "ABC", campo,
                f"Enmendadura posible ({len(familias)} familias): {desc}",
                aporte, ruta_evidencia))
            score += aporte
            if campo in cfg.candidatos:
                alertas_candidatos[campo] = hallazgos_campo
    if len(alertas_candidatos) >= 2:
        score += 35.0
        acta.hallazgos.append(Hallazgo(
            "ABC", "AMBOS_CANDIDATOS",
            "AMBOS candidatos tienen señales — posible manipulación balanceada "
            "(votos movidos entre candidatos; suma cuadra pero valores alterados).", 35.0))
    acta.score = min(score, 100.0)
    det = any(h.familia in ("D","E","F") or
              (h.familia == "G" and h.campo == "centenas_trazo_horiz")
              for h in acta.hallazgos)
    manipulacion_directa = any(
        h.familia in ("A", "H") and h.score_aporte >= 40.0 for h in acta.hallazgos)
    vis = any(h.familia in ("ABC",) for h in acta.hallazgos)
    # ≥3 firmas ausentes (aporte ≥ 36 = 3×12) → acta sospechosa
    firmas_criticas = any(
        h.familia == "J" and h.score_aporte >= 36.0 for h in acta.hallazgos)
    if det or manipulacion_directa or firmas_criticas:
        acta.tier = Tier.URGENTE
    elif vis or any(h.familia == "J" for h in acta.hallazgos):
        acta.tier = Tier.REVISAR
    elif any(s.clase == "ilegible" for s in acta.señales_raw):
        acta.tier = Tier.MANUAL
    else:
        acta.tier = Tier.LIMPIA


# ── Pasada 3: análisis de lote ─────────────────────────────────────────────
_BENFORD = {d: math.log10(1 + 1/d) for d in range(1, 10)}

def analisis_benford_batch(actas: list[ActaE14], cfg: Config) -> list[dict]:
    resultados = []
    for cand in cfg.candidatos:
        valores = [acta.votos.get(cand) for acta in actas
                   if acta.votos.get(cand) is not None and acta.votos.get(cand) > 0]
        if len(valores) < 30:
            continue
        n = len(valores)
        obs = {d: 0 for d in range(1, 10)}
        for v in valores:
            obs[int(str(v)[0])] += 1
        chi2 = sum(
            (obs[d] - n * _BENFORD[d]) ** 2 / (n * _BENFORD[d])
            for d in range(1, 10))
        sospechoso = chi2 > cfg.chi2_benford_critico
        resultados.append({
            "candidato": cand, "n": n, "chi2": round(chi2, 2),
            "sospechoso": sospechoso,
            "observados": obs,
            "esperados": {d: round(n * _BENFORD[d], 1) for d in range(1, 10)},
        })
        if sospechoso:
            msg = (f"Benford '{cand}': chi2={chi2:.1f} > {cfg.chi2_benford_critico} "
                   f"(n={n}) — distribución de primeros dígitos estadísticamente anómala.")
            for acta in actas:
                acta.hallazgos.append(Hallazgo("Z", cand, msg, 20.0))
                acta.score = min(100.0, acta.score + 20.0)
                if acta.tier == Tier.LIMPIA:
                    acta.tier = Tier.REVISAR
    return resultados


def analisis_cross_mesa(actas: list[ActaE14], cfg: Config) -> list[dict]:
    from collections import defaultdict
    por_puesto: dict[str, list[ActaE14]] = defaultdict(list)
    for acta in actas:
        por_puesto[acta.id_puesto].append(acta)
    alertas: list[dict] = []
    for puesto, mesas in por_puesto.items():
        if len(mesas) < 4:
            continue
        for cand in cfg.candidatos:
            pares = [(a, a.votos[cand]) for a in mesas if cand in a.votos]
            if len(pares) < 4:
                continue
            vals = [float(v) for _, v in pares]
            mu  = sum(vals) / len(vals)
            std = math.sqrt(sum((x - mu)**2 for x in vals) / len(vals))
            if std < 1.0:
                continue
            for acta, v in pares:
                z = abs(v - mu) / std
                if z > cfg.z_cross_mesa:
                    alertas.append({
                        "puesto": puesto, "id_mesa": acta.id_mesa,
                        "candidato": cand, "votos": v,
                        "media_puesto": round(mu, 1), "std_puesto": round(std, 1),
                        "z": round(z, 2),
                    })
                    msg = (f"Cross-mesa '{cand}': {v} votos vs media del puesto "
                           f"{mu:.0f}±{std:.0f} (z={z:.1f}σ en {len(pares)} mesas)")
                    aporte = min(40.0, 10.0 + (z - cfg.z_cross_mesa) * 5.0)
                    acta.hallazgos.append(Hallazgo("X", cand, msg, aporte))
                    acta.score = min(100.0, acta.score + aporte)
                    if acta.score >= cfg.score_umbral_urgente and acta.tier != Tier.URGENTE:
                        acta.tier = Tier.REVISAR
    return sorted(alertas, key=lambda x: -x["z"])


def pasada3_analisis_lote(actas: list[ActaE14], cfg: Config, out: Path) -> dict:
    benford = analisis_benford_batch(actas, cfg)
    cross   = analisis_cross_mesa(actas, cfg)
    resumen = {"benford": benford, "cross_mesa": cross[:50]}
    with (out / "analisis_lote.json").open("w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    return resumen


# ── Reporte ────────────────────────────────────────────────────────────────
def generar_reporte(actas: list[ActaE14], out: Path, cfg: Config,
                    resumen_lote: Optional[dict] = None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out / f"revision_priorizada_{ts}.csv"
    n_filas = 0
    orden_tier = {Tier.URGENTE: 0, Tier.REVISAR: 1, Tier.MANUAL: 2, Tier.LIMPIA: 3}
    actas_ord = sorted(actas, key=lambda a: (orden_tier[a.tier], -a.score))
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "PRIORIDAD", "SCORE", "TIER",
            "departamento", "municipio", "zona", "puesto", "mesa", "id_mesa",
            "FAMILIA_PRINCIPAL", "HALLAZGOS_PARA_REVISOR",
            "cepeda_leido", "espriella_leido", "urna_leida", "votantes_leidos",
            "firmas_jurados", "pdf_software", "evidencia_img", "archivo", "sha256_16"
        ])
        for acta in actas_ord:
            prio = acta.tier.value if acta.hallazgos else ""
            familias = sorted({h.familia for h in acta.hallazgos})
            fam_ppal = "|".join(familias)
            partes = [f"[{h.familia}/{h.campo}] {h.mensaje}"
                      for h in sorted(acta.hallazgos, key=lambda x: -x.score_aporte)]
            hallazgos_str = " || ".join(partes) if partes else "Sin hallazgos"
            imgs = [h.evidencia_img for h in acta.hallazgos if h.evidencia_img]
            firmas_col = (
                f"{sum(1 for f in acta.firmas_jurados if f)}/6"
                if acta.firmas_jurados is not None else "?")
            w.writerow([
                prio, f"{acta.score:.0f}", acta.tier.value,
                acta.departamento or "", acta.municipio or "",
                acta.zona or "", acta.puesto or "", acta.mesa or "", acta.id_mesa,
                fam_ppal, hallazgos_str,
                acta.votos.get("cepeda", "?"),
                acta.votos.get("de_la_espriella", "?"),
                acta.total_votos_urna or "?", acta.total_votantes or "?",
                firmas_col,
                acta.pdf_software or "",
                imgs[0] if imgs else "",
                Path(acta.archivo).name,
                (acta.hash_sha256 or "")[:16]
            ])
            n_filas += 1
    with (out / f"actas_{ts}.json").open("w", encoding="utf-8") as f:
        data = [{
            **{k: v for k, v in acta.__dict__.items()
               if k not in ("señales_raw", "hallazgos") and not k.startswith("_")},
            "señales_raw": [asdict(s) for s in acta.señales_raw],
            "hallazgos": [asdict(h) for h in acta.hallazgos],
            "id_mesa": acta.id_mesa, "tier": acta.tier.value,
        } for acta in actas]
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    html_path = out / f"reporte_{ts}.html"
    _generar_html(actas_ord, html_path, ts, resumen_lote)
    (out / f"manifiesto_{ts}.json").write_text(json.dumps({
        "version": VERSION, "fecha": ts,
        "n_actas": len(actas),
        "urgentes": sum(1 for a in actas if a.tier == Tier.URGENTE),
        "revisar":  sum(1 for a in actas if a.tier == Tier.REVISAR),
        "manual":   sum(1 for a in actas if a.tier == Tier.MANUAL),
        "limpias":  sum(1 for a in actas if a.tier == Tier.LIMPIA),
        "config": {k: v for k, v in asdict(cfg).items()
                   if k not in ("huecos_esperados", "software_sospechoso")},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, html_path, n_filas


def _generar_html(actas: list[ActaE14], out: Path, ts: str,
                  resumen_lote: Optional[dict] = None) -> None:
    COLORES = {
        Tier.URGENTE: "#cc0000", Tier.REVISAR: "#d06000",
        Tier.MANUAL:  "#7700cc", Tier.LIMPIA:  "#007700",
    }
    def _img(ruta: Optional[str]) -> str:
        if not ruta: return ""
        p = Path(ruta)
        if not p.exists(): return ""
        data = base64.b64encode(p.read_bytes()).decode()
        return (f'<img src="data:image/png;base64,{data}" title="{p.name}" '
                f'style="max-height:52px;border:1px solid #bbb;margin:1px">')
    filas = []
    for acta in actas:
        color = COLORES.get(acta.tier, "#555")
        votos_str = " / ".join(str(acta.votos.get(c, "?")) for c in ["cepeda", "de_la_espriella"])
        sw = f' <small style="color:#c00">({acta.pdf_software})</small>' if acta.pdf_software else ""
        if acta.firmas_jurados is not None:
            n_ok = sum(1 for f in acta.firmas_jurados if f)
            firmas_str = f"{n_ok}/6"
            firmas_color = "#c00" if n_ok <= 3 else "#d06000" if n_ok < 6 else "#007700"
        else:
            firmas_str, firmas_color = "—", "#888"
        hs_li = "".join(
            f'<li style="color:{"#c00" if h.familia in ("D","E","F","H","J") else "#333"}">'
            f'[{h.familia}] {h.mensaje} {_img(h.evidencia_img)}</li>'
            for h in sorted(acta.hallazgos, key=lambda x: -x.score_aporte))
        filas.append(
            f"<tr>"
            f'<td style="color:{color};font-weight:bold">{acta.tier.value}</td>'
            f"<td><b>{acta.score:.0f}</b></td>"
            f"<td><small>{acta.id_mesa}</small>{sw}</td>"
            f'<td style="color:{firmas_color};font-weight:bold">{firmas_str}</td>'
            f"<td>{acta.total_votos_urna or '?'}</td>"
            f"<td>{votos_str}</td>"
            f'<td><ul style="margin:0;padding-left:14px;font-size:.83em">'
            f"{hs_li}</ul></td></tr>")
    resumen_str = " &nbsp;|&nbsp; ".join(
        f'<span style="color:{COLORES[t]}">{t.value}: {sum(1 for a in actas if a.tier==t)}</span>'
        for t in Tier)
    lote_html = ""
    if resumen_lote:
        bfd = resumen_lote.get("benford", [])
        if bfd:
            filas_b = "".join(
                f'<tr style="{"background:#ffe0e0" if b["sospechoso"] else ""}">'
                f'<td>{b["candidato"]}</td><td>{b["n"]}</td><td><b>{b["chi2"]}</b></td>'
                f'<td>{"⚠️ SOSPECHOSO" if b["sospechoso"] else "normal"}</td></tr>'
                for b in bfd)
            lote_html += (
                "<h2>Análisis de Benford (distribución de primeros dígitos)</h2>"
                "<p>chi² crítico (8 gl, p=1%) = 20.09.</p>"
                '<table border="1" cellpadding="4"><tr>'
                "<th>Candidato</th><th>Mesas</th><th>Chi²</th><th>Estado</th></tr>"
                f"{filas_b}</table>")
        cross = resumen_lote.get("cross_mesa", [])
        if cross:
            filas_c = "".join(
                f'<tr><td>{a["id_mesa"]}</td><td>{a["candidato"]}</td>'
                f'<td>{a["votos"]}</td><td>{a["media_puesto"]}±{a["std_puesto"]}</td>'
                f'<td><b>{a["z"]}σ</b></td></tr>'
                for a in cross[:20])
            lote_html += (
                "<h2>Alertas cross-mesa (outliers dentro del puesto)</h2>"
                '<table border="1" cellpadding="4"><tr>'
                "<th>Mesa</th><th>Candidato</th><th>Votos</th><th>Media±Std puesto</th>"
                f"<th>Z-score</th></tr>{filas_c}</table>")
    html = (
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
        f"<title>Auditoría E-14 {ts}</title>"
        "<style>body{font-family:sans-serif;font-size:13px;margin:20px}"
        "h1,h2{color:#222}table{border-collapse:collapse;width:100%;margin-bottom:20px}"
        "th{background:#222;color:#fff;padding:5px 8px;text-align:left}"
        "td{padding:4px 8px;vertical-align:top;border-bottom:1px solid #e0e0e0}"
        "tr:hover{background:#f7f7f7}</style></head><body>"
        f"<h1>Auditoría Actas E-14 &mdash; {ts}</h1>"
        f"<p>Total: {len(actas)} actas &nbsp;&nbsp; {resumen_str}</p>"
        "<p style='color:#c00;font-weight:bold'>PRINCIPIO: este reporte produce "
        "INDICIOS para reclamación en el escrutinio. La confirmación es siempre humana.</p>"
        "<h2>Actas por prioridad</h2>"
        "<table><thead><tr>"
        "<th>Tier</th><th>Score</th><th>Mesa</th>"
        "<th>Firmas</th><th>Urna</th><th>Cepeda / De la Espriella</th><th>Hallazgos</th>"
        f"</tr></thead><tbody>{''.join(filas)}</tbody></table>"
        f"{lote_html}"
        f"<p style='color:#888;font-size:.8em;margin-top:20px'>"
        f"pipeline_e14.py v{VERSION}</p></body></html>"
    )
    out.write_text(html, encoding="utf-8")


def imprimir_resumen(actas, csv_path, html_path, n_filas, resumen_lote=None):
    urg = sum(1 for a in actas if a.tier == Tier.URGENTE)
    rev = sum(1 for a in actas if a.tier == Tier.REVISAR)
    man = sum(1 for a in actas if a.tier == Tier.MANUAL)
    lim = sum(1 for a in actas if a.tier == Tier.LIMPIA)
    print(f"\n{'='*60}")
    print(f"  ACTAS PROCESADAS: {len(actas)}")
    print(f"  {'URGENTE (revisar primero)':35}: {urg:4d}")
    print(f"  {'REVISAR (señal visual/lote)':35}: {rev:4d}")
    print(f"  {'MANUAL (OCR falló)':35}: {man:4d}")
    print(f"  {'LIMPIA (pasa todos los checks)':35}: {lim:4d}")
    print(f"{'='*60}")
    print(f"  CSV:  {csv_path.resolve()}")
    print(f"  HTML: {html_path.resolve()}")
    if resumen_lote:
        for b in resumen_lote.get("benford", []):
            if b["sospechoso"]:
                print(f"\n  ⚠️  Benford SOSPECHOSO '{b['candidato']}': chi²={b['chi2']} (n={b['n']})")
        n_cross = len(resumen_lote.get("cross_mesa", []))
        if n_cross > 0:
            print(f"\n  ⚠️  {n_cross} alerta(s) cross-mesa — ver analisis_lote.json")
    print(f"\n  PRINCIPIO: este reporte produce INDICIOS para reclamación")
    print(f"  en el escrutinio. La confirmación es siempre humana.")


# ── Motor principal de auditoría ───────────────────────────────────────────
def auditar(carpeta, salida, oficiales_path, ocr_motor, google_key):
    if not (HAY_CV and HAY_FITZ):
        print("[ERROR] Instala: pip install pymupdf opencv-python numpy")
        return
    cfg = Config()
    out = Path(salida)
    out.mkdir(parents=True, exist_ok=True)
    dir_evi = out / "evidencia"

    if ocr_motor == "google":
        if not google_key:
            print("[ERROR] --ocr google requiere --google-key")
            return
        reco: Reconocedor = ReconocedorGoogleVision(google_key)
    else:
        if not HAY_TESS:
            print("[AVISO] Tesseract no disponible; cifras no se leerán.")
        reco = ReconocedorTesseract()
        print("[AVISO] Tesseract no lee manuscrito confiablemente.")
        print("        Checks visuales y aritméticos SÍ corren.")
        print("        Para cifras: --ocr google --google-key clave.json")

    oficiales: dict = {}
    if oficiales_path:
        oficiales = json.loads(Path(oficiales_path).read_text(encoding="utf-8"))

    pdfs = sorted({p for p in Path(carpeta).rglob("*") if p.suffix.lower() == ".pdf"})
    print(f"[OK] {len(pdfs)} PDFs encontrados en {carpeta}")
    if not pdfs:
        print("[AVISO] No hay PDFs. Verifica la ruta.")
        return

    print("\n── PASADA 1: extrayendo señales...")
    actas: list[ActaE14] = []
    interrumpido = False
    try:
        for i, pdf in enumerate(pdfs, 1):
            print(f"  [{i:4d}/{len(pdfs)}] {pdf.name[:60]}")
            try:
                acta = procesar_pdf_pasada1(pdf, reco, cfg, dir_evi)
            except Exception as e:
                acta = ActaE14(archivo=str(pdf))
                identidad_desde_nombre(acta, pdf)
                acta.fallo_extraccion = str(e)
            actas.append(acta)
    except KeyboardInterrupt:
        interrumpido = True
        print("\n[CTRL+C] Calibrando con lo procesado...")

    print(f"\n── PASADA 2: calibrando batch ({len(actas)} actas)...")
    eb = calcular_estadisticas_batch(actas)
    for acta in actas:
        if acta.fallo_extraccion:
            acta.tier = Tier.MANUAL
            acta.hallazgos = [Hallazgo("FALLO", "extraccion", acta.fallo_extraccion, 0.0)]
            continue
        scoring_acta(acta, eb, cfg, oficiales)

    print("\n── PASADA 3: análisis de lote (Benford + cross-mesa)...")
    resumen_lote = pasada3_analisis_lote(actas, cfg, out)

    csv_path, html_path, n_filas = generar_reporte(actas, out, cfg, resumen_lote)
    imprimir_resumen(actas, csv_path, html_path, n_filas, resumen_lote)
    if interrumpido and len(actas) < len(pdfs):
        print(f"\n[AVISO] Procesados {len(actas)} de {len(pdfs)} PDFs.")


# ===========================================================================
# SECCIÓN 3 — AUTOTEST
# ===========================================================================
def _autotest():
    print(f"AUTOTEST pipeline_e14 v{VERSION}\n" + "="*55)
    cfg = Config()
    out = Path("salida_autotest_pipeline")
    out.mkdir(exist_ok=True)
    fallos = 0

    def ok(nombre, cond):
        nonlocal fallos
        print(f"  [{'OK  ' if cond else 'FALLO'}] {nombre}")
        if not cond: fallos += 1

    def acta_sim(nombre, votos_c, votos_e, urna, votantes,
                 inc=0, blanco=0, nulos=0, no_marc=0):
        a = ActaE14(archivo=nombre)
        identidad_desde_nombre(a, Path(nombre))
        a.votos = {"cepeda": votos_c, "de_la_espriella": votos_e}
        a.total_votos_urna = urna
        a.total_votantes = votantes
        a.votos_incinerados = inc
        a.voto_en_blanco = blanco
        a.votos_nulos = nulos
        a.no_marcados = no_marc
        a.suma_total = votos_c + votos_e + blanco + nulos + no_marc
        a.confianza = {k: 0.95 for k in ["cepeda","de_la_espriella",
                       "voto_en_blanco","votos_nulos","no_marcados","total_votos_urna"]}
        a.dir_evidencia = str(out)
        return a

    actas = [
        acta_sim("Dep15-Mun100-Zona000-Puesto01-Mesa001.pdf", 117, 137, 260, 260, blanco=5, nulos=1),
        acta_sim("Dep15-Mun100-Zona000-Puesto01-Mesa002.pdf", 147, 137, 260, 260, blanco=5, nulos=1),
        acta_sim("Dep03-Mun037-Zona099-Puesto05-Mesa010.pdf", 98, 58, 192, 360, inc=198),
        acta_sim("Dep03-Mun037-Zona099-Puesto05-Mesa011.pdf", 95, 60, 185, 185, blanco=20, nulos=10),
    ]
    oficiales = {"15-100-000-01-002": {"cepeda": 107}}
    eb_vacia = EstadisticasBatch()
    for acta in actas:
        scoring_acta(acta, eb_vacia, cfg, oficiales)

    mesa001 = next(a for a in actas if "Mesa001" in a.archivo)
    mesa002 = next(a for a in actas if "Mesa002" in a.archivo)
    mesa010 = next(a for a in actas if "Mesa010" in a.archivo)

    ok("Mesa001 LIMPIA",          mesa001.tier == Tier.LIMPIA)
    ok("Mesa002 URGENTE",         mesa002.tier == Tier.URGENTE)
    ok("Mesa002 score≥50",        mesa002.score >= 50.0)
    ok("Mesa002 familia D+F",     {"D","F"} <= {h.familia for h in mesa002.hallazgos})
    ok("Mesa010 URGENTE/REVISAR", mesa010.tier in (Tier.URGENTE, Tier.REVISAR))

    import random as _rnd
    actas_benford: list[ActaE14] = []
    _rnd.seed(0)
    for i in range(50):
        a = ActaE14(archivo=f"Dep01-Mun01-Zona01-Puesto01-Mesa{i:03d}.pdf")
        identidad_desde_nombre(a, Path(a.archivo))
        a.votos["cepeda"] = int(_rnd.expovariate(1/100)) + 10
        a.votos["de_la_espriella"] = int(_rnd.expovariate(1/80)) + 10
        actas_benford.append(a)
    bfd = analisis_benford_batch(actas_benford, cfg)
    ok("Benford devuelve resultado para ≥30 mesas", len(bfd) > 0)
    ok("Benford tiene campos esperados", all("chi2" in b for b in bfd))

    actas_cross = []
    for i in range(20):
        a = ActaE14(archivo=f"Dep01-Mun01-Zona01-Puesto02-Mesa{i:03d}.pdf")
        identidad_desde_nombre(a, Path(a.archivo))
        a.votos["cepeda"] = 100 + i
        a.votos["de_la_espriella"] = 80
        actas_cross.append(a)
    actas_cross[-1].votos["cepeda"] = 500
    alertas = analisis_cross_mesa(actas_cross, cfg)
    ok("Cross-mesa detecta outlier extremo", len(alertas) >= 1)
    ok("Cross-mesa identifica la mesa correcta",
       any(a["id_mesa"] == actas_cross[-1].id_mesa for a in alertas))

    # Familia J: firmas de jurados
    acta_j = acta_sim("Dep01-Mun001-Zona001-Puesto01-Mesa099.pdf", 80, 70, 150, 150)
    acta_j._firma_hallazgos = [Hallazgo(
        "J", "firmas_jurados",
        "Faltan 4/6 firma(s) de jurado(s) #[1, 2, 3, 4] — acta posiblemente no firmada.",
        48.0)]
    scoring_acta(acta_j, eb_vacia, cfg, {})
    ok("Familia J: 4 firmas ausentes → URGENTE", acta_j.tier == Tier.URGENTE)
    ok("Familia J: score ≥ 48",                  acta_j.score >= 48.0)

    acta_j2 = acta_sim("Dep01-Mun001-Zona001-Puesto01-Mesa098.pdf", 80, 70, 150, 150)
    acta_j2._firma_hallazgos = [Hallazgo(
        "J", "firmas_jurados",
        "Faltan 2/6 firma(s) de jurado(s) #[1, 2] — acta posiblemente no firmada.",
        24.0)]
    scoring_acta(acta_j2, eb_vacia, cfg, {})
    ok("Familia J: 2 firmas ausentes → REVISAR", acta_j2.tier == Tier.REVISAR)

    generar_reporte(actas, out, cfg)

    print(f"\n{'Mesa':33} {'Tier':10} {'Score':6} {'Hallazgos'}")
    for a in sorted(actas, key=lambda x: -x.score):
        print(f"  {a.id_mesa:31} {a.tier.value:10} {a.score:6.0f}  "
              + "; ".join(h.mensaje[:55] for h in a.hallazgos[:2]))

    if fallos == 0:
        print(f"\nTodos los tests pasaron.")
    else:
        print(f"\n{fallos} test(s) FALLARON.")
        sys.exit(1)


# ===========================================================================
# SECCIÓN 4 — CLI UNIFICADO
# ===========================================================================
if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=f"pipeline_e14.py v{VERSION} — Descarga + Auditoría de Actas E-14",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EJEMPLOS:
  # Descarga y audita
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/

  # Con preconteo oficial y OCR de Google
  python3 pipeline_e14.py --lista mesas.csv --salida resultados/ \\
      --oficiales preconteo.json --ocr google --google-key clave.json

  # Ya tengo los PDFs descargados, solo auditar
  python3 pipeline_e14.py --solo-auditar actas/ --salida resultados/

  # Verificar integridad de PDFs
  python3 pipeline_e14.py --verificar actas/

  # Test interno sin PDFs
  python3 pipeline_e14.py --autotest

FORMATO CSV (--lista):
  dep,mun,zona,puesto,mesa
  15,001,000,001,001
        """)
    p.add_argument("--lista",        help="CSV con columnas: dep,mun,zona,puesto,mesa")
    p.add_argument("--salida",       default="resultados_e14",
                                     help="Carpeta de salida (default: resultados_e14/)")
    p.add_argument("--solo-auditar", metavar="CARPETA_PDFS",
                                     help="Saltar descarga, auditar PDFs en esta carpeta")
    p.add_argument("--verificar",    metavar="CARPETA_PDFS",
                                     help="Solo verificar integridad de los PDFs")
    p.add_argument("--oficiales",    default=None,
                                     help="JSON con preconteo oficial por mesa")
    p.add_argument("--ocr",          default="tesseract", choices=["tesseract", "google"])
    p.add_argument("--google-key",   default=None,
                                     help="Credenciales Google Cloud Vision (.json)")
    p.add_argument("--autotest",     action="store_true",
                                     help="Test interno sin PDFs reales")
    args = p.parse_args()

    if args.autotest:
        _autotest()

    elif args.verificar:
        verificar_pdfs(Path(args.verificar))

    elif args.solo_auditar:
        carpeta = Path(args.solo_auditar)
        if not carpeta.exists():
            print(f"[ERROR] Carpeta no existe: {carpeta}", file=sys.stderr)
            sys.exit(1)
        print(f"\n{'='*60}")
        print(f"  AUDITORÍA — {carpeta}/")
        print(f"  Salida:  {args.salida}/")
        print(f"{'='*60}\n")
        auditar(str(carpeta), args.salida, args.oficiales, args.ocr, args.google_key)

    elif args.lista:
        try:
            construir_url("15", "001", "000", "001", "001")
        except NotImplementedError as e:
            print(f"\n[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

        mesas = _leer_csv(args.lista)
        print(f"[OK] {len(mesas)} mesas leídas de {args.lista}")

        salida      = Path(args.salida)
        carpeta_pdfs = salida / "actas"

        n_pdfs = paso_descarga(mesas, carpeta_pdfs)
        if n_pdfs == 0:
            print("[ERROR] No hay PDFs para auditar. Revisa errores de descarga.", file=sys.stderr)
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  PASO 2/2 — AUDITORÍA FORENSE")
        print(f"  PDFs: {carpeta_pdfs}/")
        print(f"  Salida: {salida / 'auditoria'}/")
        print(f"{'='*60}\n")
        auditar(str(carpeta_pdfs), str(salida / "auditoria"),
                args.oficiales, args.ocr, args.google_key)

        print(f"\n{'='*60}")
        print(f"  PIPELINE COMPLETO")
        print(f"  PDFs:    {carpeta_pdfs}/")
        print(f"  Reporte: {salida / 'auditoria'}/")
        print(f"{'='*60}")

    else:
        p.print_help()
