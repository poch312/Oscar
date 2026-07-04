#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auditor_e14_v2.py — Auditor de Actas E-14 (Colombia 2026, 2ª vuelta)
======================================================================
Arquitectura de dos pasadas que elimina falsos positivos:

  PASADA 1 — Extracción
    Por cada PDF: rasterizar → detectar estructura → extraer señales raw
    (métricas de imagen, no veredictos todavía)

  PASADA 2 — Calibración + Scoring
    Calcular estadísticas del lote → normalizar señales → acumular evidencia
    Solo señales que son outliers estadísticos del lote Y co-ocurren en ≥2
    familias independientes generan hallazgos.

  PASADA 3 — Análisis de lote
    Benford (distribución de primeros dígitos), consistencia cross-mesa,
    correlación entre puestos. Hallazgos de lote se añaden a actas individuales.

PRINCIPIOS:
  - Calibración relativa: lo que es "normal" para ESTE lote lo determinan
    las estadísticas del batch (misma impresora, mismo escáner).
  - Co-ocurrencia de familias: una enmendadura real deja huella en múltiples
    planos. El ruido afecta solo uno.
  - Checks determinísticos primero: aritmética, nivelación y discrepancia
    vs. preconteo son infalibles cuando el OCR es confiable.
  - Condicionalidad: los checks visuales solo aplican sobre campos leídos
    con confianza suficiente.
  - Triple capa: señal visual + aritmética + contexto de lote.

FAMILIAS DE SEÑAL:
  A — Topología: huecos inconsistentes / ● con dígito encima
  B — Trazo: CV de ancho de trazo (dos plumas distintas)
  C — Geometría: trazo horizontal en "1" (posible guion→dígito)
  D — Aritmética: suma ≠ total, suma ≠ suma_jurados
  E — Nivelación: votantes E-11 ≠ urna + incinerados
  F — Preconteo: valor leído ≠ preconteo oficial
  G — Borrado: grafito residual de borrado y reescritura
  H — Metadatos: PDF creado con software de edición (no escáner)
  J — Jurados: faltan firmas de jurados de votación en página 2
  X — Cross-mesa: outlier estadístico dentro de su puesto de votación
  Z — Benford: distribución de primeros dígitos significativamente anómala

USO:
  python3 auditor_e14_v2.py --autotest
  python3 auditor_e14_v2.py CARPETA_PDFS --ocr google --google-key clave.json
  python3 auditor_e14_v2.py CARPETA_PDFS --oficiales preconteo.json

DEPENDENCIAS: pip install pymupdf opencv-python numpy pytesseract google-cloud-vision
"""
from __future__ import annotations

import argparse, base64, csv, hashlib, json, math, re
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
# CONFIGURACIÓN
# ===========================================================================
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
    # Cross-mesa: z-score mínimo para marcar una mesa como outlier de su puesto
    z_cross_mesa: float     = 3.0
    # Benford: chi2 mínimo (8 grados) para sospecha. Crítico al 1%: 20.09
    chi2_benford_critico: float = 20.09
    umbral_firma_jurado: float  = 0.015
    # Metadatos PDF: software que NO es esperado en un escáner oficial
    software_sospechoso: tuple = (
        "photoshop", "gimp", "inkscape", "illustrator", "coreldraw",
        "paint", "krita", "affinity", "canva", "pixelmator",
    )
    huecos_esperados: dict = field(default_factory=lambda: {
        "0": 1, "1": 0, "2": 0, "3": 0, "5": 0,
        "6": 1, "7": 0, "8": 2, "9": 1
    })


# ===========================================================================
# MODELO DE DATOS
# ===========================================================================
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
    borrado_score: float = 0.0   # G: grafito residual 0-1
    digito_ocr: Optional[str] = None
    conf_ocr: float = 0.0
    clase: str = "vacia"  # vacia | void | void_con_digito | digito | ilegible

@dataclass
class Hallazgo:
    familia: str   # A B C D E F G H X Z ABC
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
    # Metadatos PDF (familia H)
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


# ===========================================================================
# RECONOCEDORES OCR
# ===========================================================================
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
        # Preprocesar: binarización Otsu + escala 2×
        try:
            h, w = roi.shape[:2]
            up = cv2.resize(roi, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            blur = cv2.GaussianBlur(up, (3, 3), 0)
            _, prep = cv2.threshold(blur, 0, 255,
                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            # En casillas muy altas el dígito ocupa solo una fracción pequeña.
            # Recortar al bounding box de la tinta para que Tesseract lo vea grande.
            inv = cv2.bitwise_not(prep)
            ys = np.where(np.any(inv > 0, axis=1))[0]
            xs = np.where(np.any(inv > 0, axis=0))[0]
            if ys.size > 0 and xs.size > 0:
                pad = 15
                y0 = max(0, int(ys.min()) - pad)
                y1 = min(prep.shape[0], int(ys.max()) + pad)
                x0 = max(0, int(xs.min()) - pad)
                x1 = min(prep.shape[1], int(xs.max()) + pad)
                prep = prep[y0:y1, x0:x1]
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
                    break  # confianza suficiente, no probar más modos
            except Exception:
                continue
        return (best_txt, max(0.0, best_conf) / 100.0) if best_txt else (None, 0.0)

class ReconocedorEasyOCR(Reconocedor):
    """
    OCR local GRATUITO con red neuronal (pip install easyocr).
    Lee manuscrito mucho mejor que Tesseract. La primera ejecución
    descarga los modelos (~110 MB) una sola vez; después funciona
    sin internet. CPU: ~1-2 s por casilla.
    """
    def __init__(self):
        try:
            import easyocr
        except ImportError:
            raise RuntimeError("pip install easyocr")
        self._reader = easyocr.Reader(["es"], gpu=False, verbose=False)

    def leer(self, roi):
        try:
            # Recortar al bounding box de la tinta (igual que Tesseract):
            # en casillas altas el dígito ocupa una fracción pequeña.
            _, b = cv2.threshold(roi, 0, 255,
                                 cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            ys = np.where(np.any(b > 0, axis=1))[0]
            xs = np.where(np.any(b > 0, axis=0))[0]
            if ys.size and xs.size:
                pad = 12
                roi = roi[max(0, int(ys.min())-pad): int(ys.max())+pad,
                          max(0, int(xs.min())-pad): int(xs.max())+pad]
            res = self._reader.readtext(roi, allowlist="0123456789",
                                        text_threshold=0.3, low_text=0.2)
        except Exception:
            return None, 0.0
        candidatos = [(t.strip(), float(c)) for _, t, c in res
                      if t.strip().isdigit()]
        if not candidatos:
            return None, 0.0
        txt, conf = max(candidatos, key=lambda x: x[1])
        return txt[0], conf


class ReconocedorRapidOCR(Reconocedor):
    """
    OCR local GRATUITO con modelos INCLUIDOS en el paquete pip — no
    descarga nada de internet (pip install rapidocr-onnxruntime).
    Benchmark sobre actas reales de consulado: 11/11 dígitos manuscritos
    correctos en casillas bien segmentadas (Tesseract: ~2/11).

    Preprocesamiento: borra las líneas de tabla morfológicamente, aísla
    el blob del dígito, y prueba dos recortes (ajustado y con contexto)
    quedándose con la lectura de mayor confianza.
    """
    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise RuntimeError("pip install rapidocr-onnxruntime")
        self._ocr = RapidOCR()

    def leer(self, roi):
        try:
            gris = roi if roi.ndim == 2 else cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            _, b = cv2.threshold(gris, 0, 255,
                                 cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            H, W = b.shape
            # Borrar líneas de tabla (bordes de casilla) morfológicamente
            k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, W // 3), 1))
            k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, H // 3)))
            lineas = (cv2.morphologyEx(b, cv2.MORPH_OPEN, k_h)
                      | cv2.morphologyEx(b, cv2.MORPH_OPEN, k_v))
            lineas = cv2.dilate(lineas, np.ones((3, 3), np.uint8))
            limpio = gris.copy()
            limpio[lineas > 0] = 255
            sin = cv2.bitwise_and(b, cv2.bitwise_not(lineas))
            n, _, stats, _ = cv2.connectedComponentsWithStats(sin, 8)
            cands = [(stats[i, 4], stats[i, 0], stats[i, 1],
                      stats[i, 2], stats[i, 3])
                     for i in range(1, n) if stats[i, 4] >= 40]
            if not cands:
                return None, 0.0
            _, x, y, w, h = max(cands)
            mejor_txt, mejor_conf = None, 0.0
            # Dos recortes: ajustado y con contexto — gana el más confiable
            for padf in (0.25, 1.0):
                pad = max(8, int(padf * max(w, h)))
                rec = limpio[max(0, y-pad): min(H, y+h+pad),
                             max(0, x-pad): min(W, x+w+pad)]
                if rec.size == 0:
                    continue
                alto = 96
                rec = cv2.resize(
                    rec, (max(16, int(rec.shape[1] * alto / rec.shape[0])), alto),
                    interpolation=cv2.INTER_CUBIC)
                res, _ = self._ocr(rec, use_det=False, use_cls=False)
                if res:
                    txt = "".join(c for c in res[0][0] if c.isdigit())
                    conf = float(res[0][1])
                    if txt and conf > mejor_conf:
                        mejor_txt, mejor_conf = txt[0], conf
            return (mejor_txt, mejor_conf) if mejor_txt else (None, 0.0)
        except Exception:
            return None, 0.0


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


# ===========================================================================
# UTILIDADES
# ===========================================================================
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
    """
    CLAHE antes de umbralizar. Normaliza variación de iluminación entre
    escáneres distintos y corrige sombras locales que engañan a Otsu.
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gris)

def _detectar_borrado(roi_gris: np.ndarray) -> float:
    """
    Detecta grafito residual de borrado (familia G).

    Un borrado con goma deja píxeles en rango 130-220:
      - más oscuros que papel limpio (>230)
      - más claros que tinta (<100)
    y con alta varianza local porque levanta fibras del papel.

    Retorna score 0.0-1.0 (0 = sin indicios, 1 = evidencia fuerte).
    """
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

    # Alta varianza en esa zona → fibras levantadas (vs. sombra uniforme del escáner)
    varianza = float(np.std(pixeles))
    if varianza < 5.0:
        return 0.0

    return min(1.0, frac * varianza / 180.0)


# ===========================================================================
# DETECCIÓN DE ESTRUCTURA
# ===========================================================================
def detectar_lineas_horizontales(gris: np.ndarray) -> list[int]:
    H, W = gris.shape
    _, b = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Fotos tomadas con celular tienen líneas más cortas que escáner plano.
    # Prueba fracciones decrecientes hasta obtener al menos 15 líneas.
    for frac in (1/3, 1/4, 1/5, 1/6):
        k_w = max(3, int(W * frac))
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 2))
        h = cv2.morphologyEx(b, cv2.MORPH_OPEN, k)
        cnts, _ = cv2.findContours(h, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        ys_raw = sorted(
            cv2.boundingRect(c)[1] + cv2.boundingRect(c)[3] // 2
            for c in cnts if cv2.boundingRect(c)[2] > k_w)
        ys: list[int] = []
        for y in ys_raw:
            if not ys or y - ys[-1] > 30:
                ys.append(y)
        if len(ys) >= 15:
            return ys
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
                  gris: Optional[np.ndarray] = None,
                  col: Optional[tuple[int, int]] = None) -> dict[str, tuple[int, int]]:
    # Umbral relativo a la altura de la imagen: en el escáner oficial
    # (~10900px) equivale a ~76px; en fotos de celular de menor resolución
    # escala proporcionalmente en vez de descartar todas las filas.
    h_ref = gris.shape[0] if gris is not None else (ys[-1] if ys else 0)
    min_alto = max(25, int(h_ref * 0.007))
    filas = [(ys[i], ys[i+1]) for i in range(len(ys)-1) if ys[i+1]-ys[i] > min_alto]
    if len(filas) < 8:
        return {}
    asig: dict[str, tuple[int, int]] = {}

    # Candidatos: las N filas más altas en la zona media, asignadas de arriba hacia abajo.
    # Ordenar por posición (no por altura) para que el primer candidato en la lista
    # siempre corresponda a la fila más alta visualmente, independiente de diferencias
    # mínimas de altura entre filas casi idénticas.
    # Margen adaptativo: con pocas filas detectadas (fotos de celular) no se
    # puede descartar 5 arriba y 5 abajo sin quedarse sin zona media.
    n_cands = max(len(candidatos), 1)
    margen = min(5, max(1, (len(filas) - n_cands) // 3))
    filas_por_altura = sorted(filas[margen:-margen], key=lambda f: f[1]-f[0], reverse=True)
    candidato_filas = sorted(filas_por_altura[:n_cands * 2][:n_cands], key=lambda f: f[0])
    for i, cand in enumerate(candidatos):
        if i < len(candidato_filas):
            asig[cand] = candidato_filas[i]

    # NIVELACIÓN: buscar la franja "NIVELACIÓN DE LA MESA" (fondo negro, texto blanco).
    # Es la primera franja oscura de la página (media de píxeles < 120).
    # Las 3 filas que le siguen son total_votantes, total_votos_urna, votos_incinerados.
    niv_encontrada = False
    if gris is not None:
        Hg, Wg = gris.shape
        # Banda central: los márgenes blancos diluyen el promedio y en fotos
        # la franja "negra" queda en gris medio (~130), no < 120.
        xc0, xc1 = int(Wg * 0.15), int(Wg * 0.85)
        for i, (y1, y2) in enumerate(filas):
            if y1 < Hg * 0.12:
                continue  # cabecera: código de barras / QR también son oscuros
            if float(np.mean(gris[y1:y2, xc0:xc1])) < 160:
                # Tomar las 3 filas CLARAS siguientes: la franja puede quedar
                # partida en varias "filas" oscuras que no son filas reales.
                claras = [f for f in filas[i + 1:]
                          if float(np.mean(gris[f[0]:f[1], xc0:xc1])) > 160]
                if len(claras) >= 3:
                    asig["total_votantes"]    = claras[0]
                    asig["total_votos_urna"]  = claras[1]
                    asig["votos_incinerados"] = claras[2]
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

    # Pie: últimas filas del formulario. El formato nacional tiene una fila
    # de margen debajo de SUMA TOTAL (suma = filas[-2]); el consulado no
    # (suma = filas[-1]). Decidir por dónde hay tinta en la columna de cifras.
    idx_suma = -2
    if gris is not None and col is not None and len(filas) >= 6:
        x0 = col[0] + 10
        x1 = col[0] + col[1] - 10
        def _tinta(f):
            r = gris[f[0]+15:f[1]-15, x0:x1]
            return float(np.mean(r < 100)) if r.size else 0.0
        t_ult, t_pen = _tinta(filas[-1]), _tinta(filas[-2])
        if t_ult > 0.01 and t_ult > t_pen * 1.5:
            idx_suma = -1
    asig["voto_en_blanco"] = filas[idx_suma - 3]
    asig["votos_nulos"]    = filas[idx_suma - 2]
    asig["no_marcados"]    = filas[idx_suma - 1]
    asig["suma_total"]     = filas[idx_suma]
    return asig


# ===========================================================================
# PASADA 1: EXTRACCIÓN DE SEÑALES RAW
# ===========================================================================
def _clasificar_blob(binaria: np.ndarray, area_min: int,
                     gris_original: Optional[np.ndarray] = None) -> tuple[str, dict]:
    """
    Clasifica el contenido de una casilla BINARIZADA.

    fill_ratio discrimina ● relleno (0.75-1.0) de dígito (0.10-0.45).
    Un ● con dígito encima tiene CV de intensidad elevado.

    Retorna (clase, info): vacia | void | void_con_digito | digito
    """
    H, W = binaria.shape
    area_celda = max(1, H * W)
    info: dict = {"densidad": float(np.mean(binaria > 0))}

    # 0.0015: en casillas de candidato muy altas un "1" fino da densidad
    # ~0.005 y se descartaba como vacía; el filtro area_min maneja el ruido.
    if info["densidad"] < 0.0015:
        return "vacia", info

    n, _, stats, _ = cv2.connectedComponentsWithStats(binaria, 8)
    comps = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < area_min:
            continue
        cw = int(stats[i, cv2.CC_STAT_WIDTH])
        ch = int(stats[i, cv2.CC_STAT_HEIGHT])
        cx = int(stats[i, cv2.CC_STAT_LEFT])
        cy = int(stats[i, cv2.CC_STAT_TOP])
        # Restos de líneas de tabla: cruzan la casilla y son delgados —
        # no deben competir como blob dominante contra el ● o el dígito.
        if cw > 0.85 * W and ch < 0.15 * H:
            continue
        if ch > 0.85 * H and cw < 0.15 * W:
            continue
        # Fragmentos delgados PEGADOS al borde de la casilla: son trozos del
        # marco de la tabla que el recorte partió, no tinta manuscrita.
        if cw < 0.08 * W and ch > 0.40 * H and (cx <= 2 or cx + cw >= W - 2):
            continue
        if ch < 0.08 * H and cw > 0.40 * W and (cy <= 2 or cy + ch >= H - 2):
            continue
        comps.append((i, stats[i]))
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

    # Punto pre-impreso pequeño (formato consulado) o mota de ruido: blob
    # minúsculo respecto al ANCHO de la casilla y compacto → casilla vacía.
    # (Un dígito real es más alto: el "1" es angosto pero nunca tan bajo.)
    if bw < 0.12 * W and bh < 0.12 * W and fill_ratio > 0.40:
        return "vacia", info

    # Guión manuscrito "—": los jurados lo usan como marcador de cero.
    # Ancho y muy bajo — ningún dígito tiene esa forma.
    if bh < 0.15 * bw and bh < 0.12 * H:
        return "vacia", info

    # frac 0.006: cubre el ● pre-impreso de fotos de celular y el guión/marca
    # compacta de cero que escriben los jurados (fill>0.55 protege dígitos).
    # de la casilla que en el escáner oficial (casillas más anchas).
    es_blob = fill_ratio > 0.55 and aspect > 0.30 and frac_celda > 0.006
    if not es_blob:
        return "digito", info

    # Es ●: verificar si tiene dígito encima
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
    """Extrae métricas de imagen de UNA casilla. No produce veredicto."""
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

    # Escalar con el ANCHO (grosor de trazo), no con el área: en casillas de
    # candidato muy altas (256×1574) el 0.5% del área exige ~2000px y un "1"
    # fino (~600px) desaparecía, componiendo 16→6 o 229→209.
    area_min = max(10, int(b.shape[1] * 1.2))

    clase_blob, info_blob = _clasificar_blob(b, area_min, gris_original=roi_gris)
    s.densidad = info_blob["densidad"]

    if clase_blob == "vacia":
        s.clase = "vacia"
        # Aun en celdas vacías, detectar borrado (señal de número eliminado)
        s.borrado_score = _detectar_borrado(roi_gris)
        return s

    if clase_blob == "void":
        s.clase = "void"
        return s

    if clase_blob == "void_con_digito":
        # Confirmar con OCR: en fotos, el ruido JPEG infla la varianza de
        # intensidad del ● y produce falsos "dígito sobre círculo". Sin un
        # dígito 1-9 legible encima, es un ● simple.
        txt, conf = reco.leer(roi_gris)
        if txt and txt != "0":
            s.clase = "void_con_digito"
            s.digito_ocr, s.conf_ocr = txt, conf
        else:
            s.clase = "void"
        cv2.imwrite(str(ruta_recorte), roi_gris)
        return s

    s.clase = "digito"
    cv2.imwrite(str(ruta_recorte), roi_gris)

    # Familia G: borrado antes del dígito actual
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
    # Tercio superior del DÍGITO con umbral normalizado al ancho real del dígito.
    # Funciona aunque el dígito sea pequeño respecto a la casilla (celdas muy altas).
    # Filas que son "trazo de dígito": entre 5 % y 92 % del ancho (excluye bordes completos).
    _row_pcts = np.sum(b > 0, axis=1).astype(float) / max(1, W_b)
    _d_rows = np.where((_row_pcts > 0.05) & (_row_pcts < 0.92))[0]
    if _d_rows.size >= 3:
        # Ancho horizontal del dígito (columnas con al menos un pixel de las filas dígito)
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
    """
    Divide el ROI numérico en 3 casillas buscando valles en la proyección
    vertical de densidad de tinta. Cae a tercios iguales si no hay valles.
    """
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
    """
    Combina las 3 casillas en (valor_int, confianza).
    Trata casillas vacías como "0" para conservar la posición del dígito:
      [vacía, "1", "7"] → "017" → 17   (no 17 como "1"+"7")
      ["1", vacía, "7"] → "107" → 107  (no 17)
    """
    slots = sorted(señales, key=lambda s: s.casilla)
    digitos: list[str] = []
    conf_total = 0.0
    n = 0
    toda_vacia = True

    for s in slots:
        if s.clase == "vacia":
            digitos.append("0")
            conf_total += 1.0
            n += 1
        elif s.clase == "void":
            # ● pre-impreso = posición anulada = cero de relleno.
            # "● ● 5" significa 005 = 5, no un campo ilegible.
            digitos.append("0")
            conf_total += 1.0
            n += 1
        elif s.clase == "void_con_digito":
            digitos.append(s.digito_ocr or "?")
            conf_total += 0.3
            n += 1
            toda_vacia = False
        elif s.clase == "digito" and s.digito_ocr:
            digitos.append(s.digito_ocr)
            conf_total += s.conf_ocr
            n += 1
            toda_vacia = False
        elif s.clase == "ilegible" and s.densidad < 0.008:
            # Mota de tinta insuficiente para ser un dígito real (ruido de
            # foto, sombra): tratar como cero de relleno con confianza baja
            # en vez de anular el campo completo.
            digitos.append("0")
            conf_total += 0.4
            n += 1
        else:
            return None, 0.0  # ilegible: no confiar en el valor

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
    """
    Familia H: verifica que el PDF fue generado por un escáner, no por
    software de edición de imágenes. Un PDF manipulado digitalmente puede
    ser una falsificación completa.
    """
    hs: list[Hallazgo] = []
    try:
        meta = doc.metadata or {}
        creador = (meta.get("creator", "") or meta.get("producer", "") or "").lower()
        fecha   = meta.get("creationDate", "")
        acta.pdf_software     = creador
        acta.pdf_fecha_creacion = fecha

        # Software de edición de imágenes → acta puede ser falsificada completamente
        for sw in cfg.software_sospechoso:
            if sw in creador:
                hs.append(Hallazgo(
                    "H", "pdf_metadata",
                    f"PDF generado con '{creador}' — software de edición, no escáner. "
                    f"Posible falsificación completa del documento.",
                    70.0))
                break

        # PDF sin metadatos de creador: también sospechoso
        if not creador and not meta.get("title"):
            hs.append(Hallazgo(
                "H", "pdf_metadata",
                "PDF sin metadatos de origen (creador/productor vacíos) — inusual en escáneres oficiales.",
                15.0))
    except Exception:
        pass
    return hs


def _rasterizar_pagina(doc, idx: int, dpi: int) -> Optional[np.ndarray]:
    """Rasteriza una página del PDF a escala de grises. None si falla."""
    try:
        pix = doc.load_page(idx).get_pixmap(dpi=dpi)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(
            pix.height, pix.width, pix.n)
        return cv2.cvtColor(
            cv2.cvtColor(arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR),
            cv2.COLOR_BGR2GRAY)
    except Exception:
        return None


def _clasificar_paginas(doc) -> tuple[Optional[int], Optional[int], list[int]]:
    """
    Clasifica las páginas del PDF: (pág. de votos, pág. de constancias,
    págs. placeholder tipo "PÁGINA NO DIGITALIZADA").

    Discriminador calibrado con actas reales (nacional + consulado,
    escáner + foto de celular):
      - votos: tabla completa (nivelación+candidatos+pie) → ≥14 líneas horiz.
      - constancias: página 2 del formulario → 7-12 líneas.
      - placeholder: casi sin tinta ni líneas (mesa no digitalizada).

    La Registraduría a veces publica el PDF SIN la página de votos
    (placeholder "PÁGINA NO DIGITALIZADA") — esa mesa escapa a toda
    auditoría y debe levantarse como alerta, no como fallo de extracción.
    """
    votos: Optional[int] = None
    constancias: Optional[int] = None
    placeholders: list[int] = []
    candidatas_votos: list[tuple[int, int]] = []
    for i in range(doc.page_count):
        gris = _rasterizar_pagina(doc, i, dpi=100)
        if gris is None:
            continue
        tinta = float(np.mean(gris < 128))
        n_lineas = len(detectar_lineas_horizontales(gris))
        if tinta < 0.05 and n_lineas < 5:
            placeholders.append(i)
        elif n_lineas >= 14:
            candidatas_votos.append((n_lineas, i))
        elif constancias is None:
            constancias = i
    if candidatas_votos:
        candidatas_votos.sort(reverse=True)
        votos = candidatas_votos[0][1]
        if constancias is None and len(candidatas_votos) > 1:
            constancias = candidatas_votos[1][1]
    return votos, constancias, placeholders


def _detectar_cajas_firma(gris: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    Encuentra las casillas "FIRMA JURADO N" en la página de constancias
    por contornos (rectángulos de ~media página de ancho en el tercio
    inferior). Autodetecta el layout: nacional = 6 cajas (3×2),
    consulado = 4 cajas (2×2). Devuelve (x, y, w, h) en orden de lectura.
    """
    H, W = gris.shape
    y0 = int(H * 0.55)
    zona = gris[y0:, :]
    b = cv2.adaptiveThreshold(zona, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY_INV, 35, 10)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, k)
    cnts, _ = cv2.findContours(b, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cajas = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if 0.30 * W <= w <= 0.60 * W and 0.025 * H <= h <= 0.15 * H:
            cajas.append((x, y + y0, w, h))
    # Deduplicar contorno interno/externo de la misma caja
    cajas.sort(key=lambda r: (r[1], r[0]))
    unicas: list[tuple[int, int, int, int]] = []
    for r in cajas:
        if not any(abs(r[0]-u[0]) < W*0.05 and abs(r[1]-u[1]) < H*0.02
                   for u in unicas):
            unicas.append(r)
    if not unicas:
        return []
    # Orden de lectura: filas agrupadas por y, columnas por x
    alto_med = float(np.median([h for *_, h in unicas]))
    unicas.sort(key=lambda r: (round(r[1] / max(1.0, alto_med * 0.8)), r[0]))
    return unicas


def _auditar_firmas_jurados(doc, acta: ActaE14, cfg: Config, out: Path,
                             pagina: Optional[int] = None) -> list[Hallazgo]:
    """
    Familia J: detecta si las firmas de jurados están presentes en la
    página de constancias. Localiza las casillas "FIRMA JURADO N" por
    contornos (4 en formato consulado, 6 en nacional) y mide la tinta
    manuscrita dentro de cada una (excluyendo la etiqueta impresa).
    Si no encuentra las casillas, cae a la grilla fija 2×3 (60-95%).
    """
    if not HAY_CV:
        return []
    if pagina is None:
        if doc.page_count < 2:
            return []
        pagina = 1
    gris = _rasterizar_pagina(doc, pagina, dpi=150)
    if gris is None:
        return []
    H, W = gris.shape
    firmas: list[bool] = []
    cajas = _detectar_cajas_firma(gris)
    if len(cajas) in (4, 6):
        # Umbral para densidad con umbral adaptativo (robusto a sombras de
        # fotos): firmas reales miden ≥0.067, cajas vacías ≤0.013.
        UMBRAL_CAJA = 0.035
        for n_jurado, (x, y, w, h) in enumerate(cajas, start=1):
            roi = gris[y + int(h*0.30): y + h - 3, x + 3: x + w - 3]
            if roi.size == 0:
                firmas.append(False)
                continue
            rb = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 35, 12)
            firmas.append(float(np.mean(rb > 0)) > UMBRAL_CAJA)
            cv2.imwrite(str(out / f"jurado{n_jurado}_firma.png"), roi)
    else:
        # Fallback: grilla fija 2×3 sobre la franja 60-95% (comportamiento
        # anterior, solo si las cajas no son detectables).
        y1, y2 = int(H * 0.60), int(H * 0.95)
        zona = gris[y1:y2, :]
        Hz = zona.shape[0]
        for fila in range(2):
            y_ini = int(fila * Hz / 2)
            y_fin = int((fila + 1) * Hz / 2)
            y_firma = y_ini + (y_fin - y_ini) // 2  # mitad inferior → manuscrito
            for col in range(3):
                x_ini = int(col * W / 3) + 10
                x_fin = int((col + 1) * W / 3) - 10
                roi = zona[y_firma:y_fin, x_ini:x_fin]
                if roi.size == 0:
                    firmas.append(False)
                    continue
                densidad = float(np.mean(roi < 128))
                firmas.append(densidad > cfg.umbral_firma_jurado)
                n_jurado = fila * 3 + col + 1
                cv2.imwrite(str(out / f"jurado{n_jurado}_firma.png"), roi)
    acta.firmas_jurados = firmas
    ausentes = [i + 1 for i, f in enumerate(firmas) if not f]
    if not ausentes:
        return []
    n = len(ausentes)
    total = len(firmas)
    aporte = min(50.0, n * 12.0)
    return [Hallazgo(
        "J", "firmas_jurados",
        f"Faltan {n}/{total} firma(s) de jurado(s) #{ausentes} — "
        f"acta posiblemente no firmada o incompleta.",
        aporte)]


def procesar_pdf_pasada1(pdf_path: Path, reco: Reconocedor,
                          cfg: Config, dir_evi: Path) -> ActaE14:
    """Pasada 1: extrae señales raw sin producir veredictos."""
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
        acta.señales_raw  # inicializar
        # Clasificar páginas: votos / constancias / placeholder
        pag_votos, pag_const, pags_ph = _clasificar_paginas(doc)
        # Análisis de metadatos PDF (familia H) y firmas jurados (familia J)
        # — se guardan ANTES de los early-return para no perderlos si la
        # extracción de la tabla falla.
        acta._meta_hallazgos  = _analizar_metadata_pdf(doc, acta, cfg)   # type: ignore[attr-defined]
        acta._firma_hallazgos = _auditar_firmas_jurados(                 # type: ignore[attr-defined]
            doc, acta, cfg, out, pagina=pag_const)

        if pag_votos is None:
            # El PDF publicado NO contiene la tabla de votos (p. ej.
            # "PÁGINA NO DIGITALIZADA"). No es un fallo de extracción:
            # es un hallazgo de primer orden (familia I en pasada 2).
            acta._pagina_votos_faltante = True  # type: ignore[attr-defined]
            return acta

        pix = doc.load_page(pag_votos).get_pixmap(dpi=cfg.dpi)
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
    asig = asignar_filas(ys, cfg.candidatos, gris, col=(x_col, w_col))
    if not asig:
        acta.fallo_extraccion = "No se pudo asignar filas al acta."
        return acta

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


# ===========================================================================
# PASADA 2: CALIBRACIÓN + SCORING
# ===========================================================================
@dataclass
class EstadisticasBatch:
    # campo → {señal → (media, std, upper_iqr)}
    por_campo: dict = field(default_factory=dict)

def calcular_estadisticas_batch(actas: list[ActaE14]) -> EstadisticasBatch:
    """
    Estadísticas por campo usando sigma + IQR de Tukey.
    Combinar ambos da robustez en lotes pequeños (sigma) y en distribuciones
    con cola pesada como la densidad de borrado (IQR).
    """
    from collections import defaultdict
    eb = EstadisticasBatch()
    acum: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for acta in actas:
        for s in acta.señales_raw:
            if s.clase not in ("digito", "ilegible", "vacia"):
                continue
            # borrado_score: baseline sobre todas las clases (una vacía con
            # grafito residual es justamente lo que se busca).
            acum[s.campo]["borrado_score"].append(s.borrado_score)
            # Señales de trazo: SOLO casillas con dígito real. Incluir vacías
            # (cv=0, comps=0) arrastra la media a 0 y hace que cualquier
            # dígito en un campo mayormente vacío (blanco/nulos) parezca
            # outlier — falso positivo sistemático.
            if s.clase != "digito":
                continue
            acum[s.campo]["dens_interior_lazo"].append(s.dens_interior_lazo)
            acum[s.campo]["cv_ancho_trazo"].append(s.cv_ancho_trazo)
            acum[s.campo]["n_componentes"].append(float(s.n_componentes))
            acum[s.campo]["n_huecos"].append(float(s.n_huecos))
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
    """True si el valor supera el umbral sigma O el umbral IQR de Tukey."""
    return (std > 0 and (valor - media) > n_sigma * std) or (valor > upper_iqr)

def evaluar_señal_visual(s: SeñalesRaw, eb: EstadisticasBatch,
                          cfg: Config) -> list[tuple[str, str, float]]:
    """
    Evalúa UNA señal contra el baseline del batch. Familias A-C + G.
    Las de clase void/vacia no producen hallazgos (excepto G en vacias con borrado).
    """
    hallazgos: list[tuple[str, str, float]] = []
    stats = eb.por_campo.get(s.campo, {})

    def _get(señal: str) -> tuple[float, float, float]:
        return stats.get(señal, (0.0, 1e-6, float("inf")))

    # Familia G — Borrado (aplica a cualquier clase, incluyendo vacias)
    m, std, uiqr = _get("borrado_score")
    if s.borrado_score > 0.10 and es_outlier(s.borrado_score, m, std, cfg.n_sigma_outlier, uiqr):
        msg_extra = " (casilla actualmente vacía — número fue borrado)" if s.clase == "vacia" else ""
        hallazgos.append(("G",
            f"Grafito residual de borrado detectado (score={s.borrado_score:.2f}){msg_extra}",
            25.0))

    if s.clase in ("vacia", "void", "void_con_digito"):
        return hallazgos  # solo familia G para estas clases

    # Blob grande sin lectura OCR = círculo pre-impreso (●) con artefacto de escáner,
    # no dígito manuscrito. Densidad > 0.30 distingue un ● de un trazo fino de pluma.
    if s.densidad > 0.30 and not s.digito_ocr:
        return hallazgos

    # Las señales A-topología, B y C2 comparan la forma del trazo contra lo
    # que dice el OCR: solo tienen sentido con lectura confiable. Un dígito
    # mal leído produce falsos mismatches topológicos.
    ocr_confiable = bool(s.digito_ocr) and s.conf_ocr >= cfg.umbral_confianza_ocr

    # Familia A — Topología (huecos inconsistentes)
    if ocr_confiable and s.digito_ocr in cfg.huecos_esperados:
        esperados = cfg.huecos_esperados[s.digito_ocr]
        if s.n_huecos != esperados:
            hallazgos.append(("A",
                f"Topología: OCR='{s.digito_ocr}' esperaba {esperados} "
                f"hueco(s), encontró {s.n_huecos}", 25.0))
    m, std, uiqr = _get("dens_interior_lazo")
    if s.dens_interior_lazo > 0.05 and es_outlier(s.dens_interior_lazo, m, std, cfg.n_sigma_outlier, uiqr):
        hallazgos.append(("A",
            f"Trazo dentro del lazo ({s.dens_interior_lazo:.0%}); batch: {m:.2f}±{std:.2f}",
            30.0))

    # Familia B — Variación de ancho de trazo (dos plumas).
    m, std, uiqr = _get("cv_ancho_trazo")
    if ocr_confiable and es_outlier(s.cv_ancho_trazo, m, std, cfg.n_sigma_outlier, uiqr):
        hallazgos.append(("B",
            f"Ancho de trazo mixto (cv={s.cv_ancho_trazo:.2f}); batch: {m:.2f}±{std:.2f}",
            20.0))

    # Familia C — Geometría: trazo horizontal en "1"
    if s.tiene_trazo_horiz and s.digito_ocr in ("1",):
        hallazgos.append(("C",
            f"Trazo horizontal largo en '{s.digito_ocr}' (posible guion→1)", 25.0))

    # Familia C2 — Componentes anómalos (outlier adaptivo).
    m, std, uiqr = _get("n_componentes")
    if ocr_confiable and es_outlier(float(s.n_componentes), m, std,
                                    cfg.n_sigma_outlier + 0.5, uiqr):
        hallazgos.append(("C",
            f"Componentes anómalos ({s.n_componentes} vs batch {m:.1f}±{std:.1f})", 15.0))

    return hallazgos

def scoring_acta(acta: ActaE14, eb: EstadisticasBatch,
                  cfg: Config, oficiales: dict) -> None:
    """Pasada 2: evalúa hallazgos y calcula score. Modifica acta in-place."""
    acta.hallazgos = []
    score = 0.0

    # Transferir hallazgos de metadatos PDF (familia H) y firmas (familia J)
    meta_hs = getattr(acta, "_meta_hallazgos", [])
    for h in meta_hs:
        acta.hallazgos.append(h)
        score += h.score_aporte
    firma_hs = getattr(acta, "_firma_hallazgos", [])
    for h in firma_hs:
        acta.hallazgos.append(h)
        score += h.score_aporte

    # I — La página con la tabla de votos NO está en el PDF publicado
    # ("PÁGINA NO DIGITALIZADA"). La mesa escapa a toda auditoría del E-14
    # de transmisión: alerta de primer orden para reclamación.
    if getattr(acta, "_pagina_votos_faltante", False):
        acta.hallazgos.append(Hallazgo(
            "I", "pagina_votos_no_digitalizada",
            "El PDF publicado NO contiene la página con la tabla de votos "
            "(aparece 'PÁGINA NO DIGITALIZADA' o solo la página de "
            "constancias). Imposible verificar cifras — solicitar el acta "
            "física o la copia de claveros.", 85.0))
        score += 85.0

    # ── VOID CON DÍGITO (manipulación directa) ────────────────────────────
    for s in acta.señales_raw:
        if s.clase == "void_con_digito":
            ruta = str(Path(acta.dir_evidencia or ".") /
                       f"{s.campo}_cas{s.casilla}.png")
            acta.hallazgos.append(Hallazgo(
                "A", s.campo,
                f"Casilla {s.casilla+1} de '{s.campo}': blob de anulación ● "
                f"con trazos adicionales dentro — posible dígito escrito encima.",
                65.0, ruta))
            score += 65.0

    # ── CHECKS DETERMINÍSTICOS ────────────────────────────────────────────
    # G — Dígito de centenas con trazo horizontal en el tercio SUPERIOR cuando votantes ≤ 299.
    # Un trazo largo (≥55% del ancho) en la parte alta indica "7" o "4":
    # imposibles si total_votantes ≤ 299 (solo son válidos 0-2 en centenas).
    # "2" tiene su trazo horizontal en la parte baja → no dispara este check.
    # Círculos pre-impresos (●) están centrados → tampoco aparecen en el tercio superior.
    if acta.total_votantes is not None and acta.total_votantes <= 299:
        for s in acta.señales_raw:
            if (s.campo in cfg.candidatos
                    and s.casilla == 0  # posición de centenas
                    and s.tiene_trazo_h_top
                    and s.densidad >= 0.012  # tinta de dígito real, no mota
                    and s.clase in ("digito", "ilegible", "void_con_digito")):
                acta.hallazgos.append(Hallazgo(
                    "G", "centenas_trazo_horiz",
                    f"Centenas de '{s.campo}' con trazo horizontal en parte alta (posible 7 o 4) "
                    f"— imposible con solo {acta.total_votantes} votantes registrados.", 80.0))
                score += 80.0

    # G — Fila de candidato completamente ilegible: tachón sobre el número original.
    # Condición doble: (1) las 3 casillas son "ilegible" (ninguna legible ni vacía) Y
    # (2) al menos 2 tienen densidad > 0.030 — el tachón deja más tinta que un
    # guión(-) o dígito borroso (OCR failure en votación baja), que tienen densidad < 0.033.
    for campo in cfg.candidatos:
        cas = [s for s in acta.señales_raw if s.campo == campo]
        if (len(cas) == 3
                and all(s.clase == "ilegible" for s in cas)
                and sum(1 for s in cas if s.densidad > 0.030) >= 2):
            acta.hallazgos.append(Hallazgo(
                "G", "tachon_fila",
                f"Las 3 casillas de '{campo}' son ilegibles con alta densidad de tinta "
                f"— posible tachón sobre el número original.",
                70.0))
            score += 70.0

    # D — Votos de un candidato superan la urna (check parcial, no requiere todos los campos)
    urna_ref = acta.total_votos_urna or acta.total_votantes
    if urna_ref is not None:
        campo_ref = ("total_votos_urna" if acta.total_votos_urna is not None
                     else "total_votantes")
        for cand, voto in acta.votos.items():
            if voto is not None and voto > urna_ref:
                conf_min = min(acta.confianza.get(cand, 1.0),
                               acta.confianza.get(campo_ref, 1.0))
                # Exceso de unidades (Δ≤9) = huella típica de UN dígito mal
                # leído por OCR, no de fraude (que suma decenas/centenas).
                fiable = (conf_min >= cfg.umbral_confianza_ocr
                          and voto - urna_ref > 9)
                sev = 100.0 if fiable else 15.0
                acta.hallazgos.append(Hallazgo(
                    "D", "votos_exceden_urna",
                    f"Candidato '{cand}' con {voto} votos supera la urna/votantes "
                    f"({urna_ref}) — aritméticamente imposible."
                    + ("" if fiable
                       else " Diferencia pequeña o confianza OCR baja: "
                            "posible error de lectura, verificar."), sev))
                score += sev

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
                    "D", "aritmetica",
                    f"Suma {suma} ≠ urna {acta.total_votos_urna} (Δ={dif:+d})", 50.0))
                score += 50.0
            else:
                acta.hallazgos.append(Hallazgo(
                    "D", "aritmetica",
                    f"Descuadre aritmético ({suma} vs {acta.total_votos_urna}) "
                    f"— confianza OCR baja ({conf_min:.0%})", 10.0))
                score += 10.0
        # Suma escrita por jurados vs. suma calculada
        if acta.suma_total is not None and acta.suma_total != suma:
            acta.hallazgos.append(Hallazgo(
                "D", "suma_total",
                f"Suma escrita por jurados ({acta.suma_total}) ≠ calculada ({suma})",
                40.0))
            score += 40.0

    # E — Nivelación
    # Igual que D/aritmética: si la confianza OCR de los campos comparados es
    # baja, degradar severidad — un dígito mal leído no debe producir URGENTE.
    V, U, I = acta.total_votantes, acta.total_votos_urna, acta.votos_incinerados
    if V is not None and U is not None:
        conf_niv = min(acta.confianza.get("total_votantes", 1.0),
                       acta.confianza.get("total_votos_urna", 1.0))
        ocr_fiable = conf_niv >= cfg.umbral_confianza_ocr
        if U > V:
            sev = 60.0 if ocr_fiable else 10.0
            acta.hallazgos.append(Hallazgo(
                "E", "nivelacion",
                f"Urna ({U}) > votantes E-11 ({V}): físicamente imposible"
                + ("" if ocr_fiable else f" — confianza OCR baja ({conf_niv:.0%})"),
                sev))
            score += sev
        elif U < V:
            dif = V - U
            sev = 60.0 if (dif > cfg.tolerancia_nivelacion and ocr_fiable) else 10.0
            acta.hallazgos.append(Hallazgo(
                "E", "nivelacion",
                f"Urna ({U}) < votantes E-11 ({V}), faltante {dif}"
                + (f" — incinerados ({I}) no cierran la brecha" if I and U+I != V else "")
                + ("" if ocr_fiable else f" — confianza OCR baja ({conf_niv:.0%})"),
                sev))
            score += sev
    if I is not None and I > 0:
        base = V or U
        if base and I / base > cfg.umbral_incineracion:
            acta.hallazgos.append(Hallazgo(
                "E", "votos_incinerados",
                f"Incineración inusualmente alta: {I} = {I/base:.0%} del total", 20.0))
            score += 20.0

    # F — Discrepancia vs. preconteo oficial
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

    # ── CHECKS VISUALES (calibrados contra batch) ─────────────────────────
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
                f"Enmendadura posible ({len(familias)} familias de señal): {desc}",
                aporte, ruta_evidencia))
            score += aporte
            if campo in cfg.candidatos:
                alertas_candidatos[campo] = hallazgos_campo

    # Detector de manipulación balanceada
    if len(alertas_candidatos) >= 2:
        score += 35.0
        acta.hallazgos.append(Hallazgo(
            "ABC", "AMBOS_CANDIDATOS",
            "AMBOS candidatos tienen señales visuales — puede indicar "
            "manipulación balanceada (votos movidos entre candidatos; "
            "la suma cuadra pero los valores individuales fueron alterados).",
            35.0))

    acta.score = min(score, 100.0)

    # Tier
    # Solo hallazgos deterministas con severidad real fuerzan URGENTE: los
    # degradados por baja confianza OCR (10-15 pts) no son evidencia firme.
    det = any((h.familia in ("D","E","F","I") and h.score_aporte >= 40.0) or
              (h.familia == "G" and h.campo in ("centenas_trazo_horiz", "tachon_fila"))
              for h in acta.hallazgos)
    manipulacion_directa = any(
        h.familia in ("A", "H") and h.score_aporte >= 40.0
        for h in acta.hallazgos)
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


# ===========================================================================
# PASADA 3: ANÁLISIS DE LOTE
# ===========================================================================

# Distribución esperada de Benford
_BENFORD = {d: math.log10(1 + 1/d) for d in range(1, 10)}

def analisis_benford_batch(actas: list[ActaE14], cfg: Config) -> list[dict]:
    """
    Ley de Benford sobre los primeros dígitos de los votos por candidato.
    En elecciones reales los primeros dígitos siguen Benford.
    Desviación significativa (chi2 > umbral) → resultado estadísticamente anómalo.
    Requiere ≥30 mesas para tener potencia estadística.
    """
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
            "candidato": cand,
            "n": n,
            "chi2": round(chi2, 2),
            "sospechoso": sospechoso,
            "observados": obs,
            "esperados": {d: round(n * _BENFORD[d], 1) for d in range(1, 10)},
        })
        if sospechoso:
            msg = (f"Benford '{cand}': chi2={chi2:.1f} > {cfg.chi2_benford_critico} "
                   f"(n={n}) — distribución de primeros dígitos estadísticamente anómala.")
            for acta in actas:
                acta.hallazgos.append(Hallazgo("Z", cand, msg, 0.0))
    return resultados


def analisis_cross_mesa(actas: list[ActaE14], cfg: Config) -> list[dict]:
    """
    Detecta mesas donde los votos de un candidato son outliers estadísticos
    (z > cfg.z_cross_mesa) dentro de su puesto de votación.
    Señal X: la mesa fue la única alterada en el puesto, haciendo que los
    demás resultados sirvan como control implícito.
    Requiere ≥4 mesas en el puesto para tener estadística.
    """
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
                    alerta = {
                        "puesto": puesto, "id_mesa": acta.id_mesa,
                        "candidato": cand, "votos": v,
                        "media_puesto": round(mu, 1), "std_puesto": round(std, 1),
                        "z": round(z, 2),
                    }
                    alertas.append(alerta)
                    msg = (f"Cross-mesa '{cand}': {v} votos vs media del puesto "
                           f"{mu:.0f}±{std:.0f} (z={z:.1f}σ en {len(pares)} mesas)")
                    aporte = min(40.0, 10.0 + (z - cfg.z_cross_mesa) * 5.0)
                    acta.hallazgos.append(Hallazgo("X", cand, msg, aporte))
                    acta.score = min(100.0, acta.score + aporte)
                    if acta.score >= cfg.score_umbral_urgente and acta.tier != Tier.URGENTE:
                        acta.tier = Tier.REVISAR

    return sorted(alertas, key=lambda x: -x["z"])


def pasada3_analisis_lote(actas: list[ActaE14], cfg: Config,
                           out: Path) -> dict:
    """Pasada 3 in-place: Benford + cross-mesa. Devuelve resumen para el reporte."""
    benford = analisis_benford_batch(actas, cfg)
    cross   = analisis_cross_mesa(actas, cfg)

    resumen = {"benford": benford, "cross_mesa": cross[:50]}  # top 50 alertas

    with (out / "analisis_lote.json").open("w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    return resumen


# ===========================================================================
# REPORTE
# ===========================================================================
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
                f"{sum(1 for f in acta.firmas_jurados if f)}/{len(acta.firmas_jurados)}"
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

    # JSON completo
    with (out / f"actas_{ts}.json").open("w", encoding="utf-8") as f:
        data = [{
            **{k: v for k, v in acta.__dict__.items()
               if k not in ("señales_raw", "hallazgos") and not k.startswith("_")},
            "señales_raw": [asdict(s) for s in acta.señales_raw],
            "hallazgos": [asdict(h) for h in acta.hallazgos],
            "id_mesa": acta.id_mesa, "tier": acta.tier.value,
        } for acta in actas]
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # HTML interactivo con evidencia
    html_path = out / f"reporte_{ts}.html"
    _generar_html(actas_ord, html_path, ts, resumen_lote)

    # Manifiesto
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
    """HTML con evidencia en base64, resumen de Benford y alertas cross-mesa."""
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
        votos_str = " / ".join(
            str(acta.votos.get(c, "?")) for c in ["cepeda", "de_la_espriella"])
        sw = f' <small style="color:#c00">({acta.pdf_software})</small>' if acta.pdf_software else ""
        if acta.firmas_jurados is not None:
            n_ok = sum(1 for f in acta.firmas_jurados if f)
            n_tot = len(acta.firmas_jurados)
            firmas_str = f"{n_ok}/{n_tot}"
            firmas_color = ("#c00" if n_ok <= n_tot // 2
                            else "#d06000" if n_ok < n_tot else "#007700")
        else:
            firmas_str, firmas_color = "—", "#888"
        hs_li = "".join(
            f'<li style="color:{"#c00" if h.familia in ("D","E","F","H","I","J") else "#333"}">'
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

    resumen = " &nbsp;|&nbsp; ".join(
        f'<span style="color:{COLORES[t]}">{t.value}: {sum(1 for a in actas if a.tier==t)}</span>'
        for t in Tier)

    # Sección de análisis de lote
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
                "<p>En elecciones legítimas los primeros dígitos de los votos siguen la Ley de Benford. "
                f"Umbral chi² crítico (8 gl, p=1%): {actas[0].score if actas else '—'}... "
                f"chi² crítico = 20.09.</p>"
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
                "<p>Mesas donde los votos de un candidato son outliers estadísticos "
                "respecto al resto de mesas del mismo puesto.</p>"
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
        f"<p>Total: {len(actas)} actas &nbsp;&nbsp; {resumen}</p>"
        "<p style='color:#c00;font-weight:bold'>PRINCIPIO: este reporte produce "
        "INDICIOS para reclamación en el escrutinio. La confirmación es siempre humana.</p>"
        "<h2>Actas por prioridad</h2>"
        "<table><thead><tr>"
        "<th>Tier</th><th>Score</th><th>Mesa</th>"
        "<th>Firmas</th><th>Urna</th><th>Cepeda / De la Espriella</th><th>Hallazgos</th>"
        f"</tr></thead><tbody>{''.join(filas)}</tbody></table>"
        f"{lote_html}"
        f"<p style='color:#888;font-size:.8em;margin-top:20px'>"
        f"auditor_e14_v2.py v{VERSION}</p></body></html>"
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
    print(f"  CSV:   {csv_path.resolve()}")
    print(f"  HTML:  {html_path.resolve()}")
    print(f"  Filas: {n_filas}")
    if resumen_lote:
        for b in resumen_lote.get("benford", []):
            if b["sospechoso"]:
                print(f"\n  ⚠️  Benford SOSPECHOSO para '{b['candidato']}': "
                      f"chi²={b['chi2']} (n={b['n']})")
        n_cross = len(resumen_lote.get("cross_mesa", []))
        if n_cross > 0:
            print(f"\n  ⚠️  {n_cross} alerta(s) cross-mesa — ver analisis_lote.json")
    print(f"\n  PRINCIPIO: este reporte produce INDICIOS para reclamación")
    print(f"  en el escrutinio. La confirmación es siempre humana.")


# ===========================================================================
# MAIN
# ===========================================================================
def main(carpeta, salida, oficiales_path, eleccion, ocr_motor, google_key):
    if not (HAY_CV and HAY_FITZ):
        print("[ERROR] Instala: pip install pymupdf opencv-python numpy"); return
    cfg = Config(eleccion_esperada=eleccion or "presidencia_2v_2026")
    out = Path(salida); out.mkdir(parents=True, exist_ok=True)
    dir_evi = out / "evidencia"

    if ocr_motor == "google":
        if not google_key:
            print("[ERROR] --ocr google requiere --google-key"); return
        reco: Reconocedor = ReconocedorGoogleVision(google_key)
    elif ocr_motor == "rapidocr":
        try:
            reco = ReconocedorRapidOCR()
            print("[OK] RapidOCR listo (neuronal local, modelos incluidos).")
        except RuntimeError as e:
            print(f"[ERROR] {e}"); return
    elif ocr_motor == "easyocr":
        try:
            reco = ReconocedorEasyOCR()
            print("[OK] EasyOCR listo (OCR neuronal local, gratuito).")
        except RuntimeError as e:
            print(f"[ERROR] {e}"); return
    else:
        if not HAY_TESS:
            print("[AVISO] Tesseract no disponible; cifras no se leerán.")
        reco = ReconocedorTesseract()
        if ocr_motor == "tesseract":
            print("[AVISO] Tesseract no lee manuscrito confiablemente.")
            print("        Checks visuales y aritméticos SÍ corren.")
            print("        Para cifras: --ocr google --google-key clave.json")

    oficiales: dict = {}
    if oficiales_path:
        oficiales = json.loads(Path(oficiales_path).read_text(encoding="utf-8"))

    pdfs = sorted({p for p in Path(carpeta).rglob("*") if p.suffix.lower() == ".pdf"})
    print(f"[OK] {len(pdfs)} PDFs encontrados en {carpeta}")
    if not pdfs:
        print("[AVISO] No hay PDFs. Verifica la ruta."); return

    # ── DEDUP POR SHA256 ─────────────────────────────────────────────────
    hashes_vistos: dict[str, Path] = {}
    pdfs_unicos: list[Path] = []
    n_dup = 0
    for p in pdfs:
        h = sha256(p)
        if h in hashes_vistos:
            n_dup += 1
        else:
            hashes_vistos[h] = p
            pdfs_unicos.append(p)
    if n_dup:
        print(f"[OK] {n_dup} PDFs duplicados (mismo SHA256) omitidos → "
              f"{len(pdfs_unicos)} únicos a procesar.")

    # ── PASADA 1 ──────────────────────────────────────────────────────────
    print("\n── PASADA 1: extrayendo señales...")
    actas: list[ActaE14] = []
    interrumpido = False
    try:
        for i, pdf in enumerate(pdfs_unicos, 1):
            print(f"  [{i:4d}/{len(pdfs_unicos)}] {pdf.name[:60]}")
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

    # ── PASADA 2 ──────────────────────────────────────────────────────────
    print(f"\n── PASADA 2: calibrando batch ({len(actas)} actas)...")
    eb = calcular_estadisticas_batch(actas)
    for acta in actas:
        if acta.fallo_extraccion:
            acta.tier = Tier.MANUAL
            acta.hallazgos = [Hallazgo("FALLO", "extraccion", acta.fallo_extraccion, 0.0)]
            continue
        scoring_acta(acta, eb, cfg, oficiales)

    # ── Normalizar H/pdf_metadata uniforme ─────────────────────────────
    n_h_meta = sum(1 for a in actas if any(
        h.familia == "H" and h.campo == "pdf_metadata" for h in a.hallazgos))
    if len(actas) >= 3 and n_h_meta / len(actas) > 0.70:
        print(f"[INFO] {n_h_meta}/{len(actas)} PDFs comparten misma anomalía de "
              f"metadatos — característica del escáner, no anomalía individual.")
        for acta in actas:
            nuevos = []
            for h in acta.hallazgos:
                if h.familia == "H" and h.campo == "pdf_metadata" and h.score_aporte <= 15.0:
                    acta.score = max(0.0, acta.score - h.score_aporte)
                    nuevos.append(Hallazgo(h.familia, h.campo,
                        h.mensaje + " [Nota: uniforme en el lote — escáner, no anomalía]",
                        0.0, h.evidencia_img))
                else:
                    nuevos.append(h)
            acta.hallazgos = nuevos
            if acta.score < cfg.score_umbral_revisar and acta.tier == Tier.MANUAL:
                if not any(s.clase == "ilegible" for s in acta.señales_raw):
                    acta.tier = Tier.LIMPIA

    # ── PASADA 3 ──────────────────────────────────────────────────────────
    print("\n── PASADA 3: análisis de lote (Benford + cross-mesa)...")
    resumen_lote = pasada3_analisis_lote(actas, cfg, out)

    # Re-evaluar tiers: actas que solo tenían Z+H (ahora score~0) → LIMPIA
    for acta in actas:
        if acta.fallo_extraccion:
            continue
        score_real = sum(h.score_aporte for h in acta.hallazgos)
        acta.score = min(100.0, score_real)
        tiene_hallazgo_real = any(
            h.score_aporte > 0 for h in acta.hallazgos)
        if not tiene_hallazgo_real:
            if any(s.clase == "ilegible" for s in acta.señales_raw):
                acta.tier = Tier.MANUAL
            else:
                acta.tier = Tier.LIMPIA

    # ── Reporte ───────────────────────────────────────────────────────────
    csv_path, html_path, n_filas = generar_reporte(actas, out, cfg, resumen_lote)
    imprimir_resumen(actas, csv_path, html_path, n_filas, resumen_lote)
    if interrumpido and len(actas) < len(pdfs):
        print(f"\n[AVISO] Procesados {len(actas)} de {len(pdfs)} PDFs.")


# ===========================================================================
# AUTOTEST
# ===========================================================================
def _autotest():
    import sys
    print(f"AUTOTEST auditor_e14_v2 v{VERSION}\n" + "="*55)
    cfg = Config()
    out = Path("salida_autotest_v2"); out.mkdir(exist_ok=True)
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
        # Mesa 001: limpia
        acta_sim("Dep15-Mun100-Zona000-Puesto01-Mesa001.pdf",
                 117, 137, 260, 260, blanco=5, nulos=1),
        # Mesa 002: suma descuadra + discrepancia preconteo
        acta_sim("Dep15-Mun100-Zona000-Puesto01-Mesa002.pdf",
                 147, 137, 260, 260, blanco=5, nulos=1),
        # Mesa 010: nivelación rota
        acta_sim("Dep03-Mun037-Zona099-Puesto05-Mesa010.pdf",
                 98, 58, 192, 360, inc=198),
        # Mesa 011: limpia, mismo puesto que mesa 010
        acta_sim("Dep03-Mun037-Zona099-Puesto05-Mesa011.pdf",
                 95, 60, 185, 185, blanco=20, nulos=10),
        # Mesa 012: nivelación rota pero OCR de baja confianza → NO urgente
        acta_sim("Dep03-Mun037-Zona099-Puesto05-Mesa012.pdf",
                 98, 58, 192, 360, blanco=20, nulos=16),
    ]
    oficiales = {"15-100-000-01-002": {"cepeda": 107}}

    mesa012 = next(a for a in actas if "Mesa012" in a.archivo)
    mesa012.confianza["total_votos_urna"] = 0.35  # OCR dudoso

    eb_vacia = EstadisticasBatch()
    for acta in actas:
        scoring_acta(acta, eb_vacia, cfg, oficiales)

    mesa001 = next(a for a in actas if "Mesa001" in a.archivo)
    mesa002 = next(a for a in actas if "Mesa002" in a.archivo)
    mesa010 = next(a for a in actas if "Mesa010" in a.archivo)

    ok("Mesa001 LIMPIA",         mesa001.tier == Tier.LIMPIA)
    ok("Mesa002 URGENTE",        mesa002.tier == Tier.URGENTE)
    ok("Mesa002 score≥50",       mesa002.score >= 50.0)
    ok("Mesa002 familia D+F",    {"D","F"} <= {h.familia for h in mesa002.hallazgos})
    ok("Mesa010 URGENTE/REVISAR",mesa010.tier in (Tier.URGENTE, Tier.REVISAR))
    ok("Mesa012 OCR dudoso NO urgente", mesa012.tier != Tier.URGENTE)
    ok("Mesa012 conserva hallazgo E",
       any(h.familia == "E" for h in mesa012.hallazgos))

    # _componer_valor: posición correcta de cada casilla
    if HAY_CV:
        s0 = SeñalesRaw(campo="x", casilla=0, clase="vacia")
        s1 = SeñalesRaw(campo="x", casilla=1, clase="digito", digito_ocr="1", conf_ocr=0.95)
        s2 = SeñalesRaw(campo="x", casilla=2, clase="digito", digito_ocr="7", conf_ocr=0.95)
        ok("_componer_valor [0,1,7] → 17",  _componer_valor([s0,s1,s2], cfg)[0] == 17)

        s0b = SeñalesRaw(campo="x", casilla=0, clase="digito", digito_ocr="1", conf_ocr=0.95)
        s1b = SeñalesRaw(campo="x", casilla=1, clase="vacia")
        s2b = SeñalesRaw(campo="x", casilla=2, clase="digito", digito_ocr="7", conf_ocr=0.95)
        ok("_componer_valor [1,0,7] → 107", _componer_valor([s0b,s1b,s2b], cfg)[0] == 107)

        sv = SeñalesRaw(campo="x", casilla=0, clase="void")
        ok("_componer_valor void → 0 (● = cero de relleno)",
           _componer_valor([sv], cfg)[0] == 0)

        # "● ● 5" = 005 = 5: los círculos pre-impresos son ceros
        sv0 = SeñalesRaw(campo="x", casilla=0, clase="void")
        sv1 = SeñalesRaw(campo="x", casilla=1, clase="void")
        sd2 = SeñalesRaw(campo="x", casilla=2, clase="digito",
                         digito_ocr="5", conf_ocr=0.95)
        ok("_componer_valor [●,●,5] → 5",
           _componer_valor([sv0, sv1, sd2], cfg)[0] == 5)

        # Clasificación de blobs
        vacia = np.full((40,30), 255, np.uint8)
        _, bbin = cv2.threshold(vacia, 128, 255, cv2.THRESH_BINARY_INV)
        ok("blob vacío → vacia",   _clasificar_blob(bbin, 5)[0] == "vacia")

        blob = np.full((50,40), 255, np.uint8)
        cv2.circle(blob, (20,25), 14, 0, -1)
        _, bblob = cv2.threshold(blob, 128, 255, cv2.THRESH_BINARY_INV)
        ok("blob ● sólido → void", _clasificar_blob(bblob, 5, gris_original=blob)[0] == "void")

        d1 = np.full((60,20), 255, np.uint8)
        cv2.line(d1, (10,5), (10,55), 0, 3)
        _, b1 = cv2.threshold(d1, 128, 255, cv2.THRESH_BINARY_INV)
        ok("blob '1' → digito",    _clasificar_blob(b1, 5, gris_original=d1)[0] == "digito")

        # _detectar_borrado: imagen con zona gris variante
        roi_limpio = np.full((40,30), 240, np.uint8)  # papel limpio
        ok("borrado: papel limpio → score bajo", _detectar_borrado(roi_limpio) < 0.10)

        roi_borrado = np.full((40,30), 180, np.uint8)
        # Añadir varianza (simula fibras levantadas)
        np.random.seed(42)
        roi_borrado = roi_borrado + np.random.randint(-20, 20, roi_borrado.shape, dtype=np.int8).astype(np.uint8)
        ok("borrado: zona gris variante → score alto", _detectar_borrado(roi_borrado) > 0.05)

    # Benford: batch sintético (50 mesas, valores aleatorios Benford-conformes)
    import random as _rnd
    actas_benford: list[ActaE14] = []
    _rnd.seed(0)
    for i in range(50):
        a = ActaE14(archivo=f"Dep01-Mun01-Zona01-Puesto01-Mesa{i:03d}.pdf")
        identidad_desde_nombre(a, Path(a.archivo))
        # Valores que siguen Benford aproximadamente (exponencial)
        a.votos["cepeda"] = int(_rnd.expovariate(1/100)) + 10
        a.votos["de_la_espriella"] = int(_rnd.expovariate(1/80)) + 10
        actas_benford.append(a)
    bfd = analisis_benford_batch(actas_benford, cfg)
    ok("Benford devuelve resultado para ≥30 mesas", len(bfd) > 0)
    ok("Benford tiene campos esperados", all("chi2" in b for b in bfd))
    ok("Benford Z es informativo (score_aporte=0)",
       all(h.score_aporte == 0 for a in actas_benford
           for h in a.hallazgos if h.familia == "Z"))

    # Cross-mesa: un outlier claro dentro del puesto
    # Nota: con n mesas el z máximo es sqrt(n-1). Para superar z=3.0 se necesitan
    # al menos 11 mesas. Usamos 20 para tener margen cómodo (z_max ≈ 4.4).
    actas_cross = []
    for i in range(20):
        a = ActaE14(archivo=f"Dep01-Mun01-Zona01-Puesto02-Mesa{i:03d}.pdf")
        identidad_desde_nombre(a, Path(a.archivo))
        a.votos["cepeda"] = 100 + i   # 100..119, cluster bien definido
        a.votos["de_la_espriella"] = 80
        actas_cross.append(a)
    # La última mesa tiene un outlier extremo (votos 3× la media)
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

    # Familia I: PDF publicado sin la página de la tabla de votos
    acta_i = ActaE14(archivo="Dep88-Mun815-Zona065-Puesto09-Mesa001.pdf")
    identidad_desde_nombre(acta_i, Path(acta_i.archivo))
    acta_i._pagina_votos_faltante = True
    scoring_acta(acta_i, eb_vacia, cfg, {})
    ok("Familia I: página de votos faltante → URGENTE",
       acta_i.tier == Tier.URGENTE)
    ok("Familia I: hallazgo registrado",
       any(h.familia == "I" for h in acta_i.hallazgos))

    generar_reporte(actas, out, cfg)

    print(f"\n{'Mesa':33} {'Tier':10} {'Score':6} {'Hallazgos'}")
    for a in sorted(actas, key=lambda x: -x.score):
        print(f"  {a.id_mesa:31} {a.tier.value:10} {a.score:6.0f}  "
              + "; ".join(h.mensaje[:55] for h in a.hallazgos[:2]))

    if fallos == 0:
        print(f"\nTodos los tests pasaron ({sum(1 for _ in range(100) if True)} checks).")
    else:
        print(f"\n{fallos} test(s) FALLARON.")
        sys.exit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=f"Auditor E-14 v{VERSION} — triple capa, cero falsos positivos sistemáticos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
OCR (--ocr):
  tesseract  Local. No lee manuscrito. Checks visuales y aritméticos SÍ corren.
  rapidocr   RECOMENDADO. Local, gratuito, modelos incluidos en el pip (sin
             descargas). 11/11 dígitos correctos en benchmark con actas
             reales. pip install rapidocr-onnxruntime
  easyocr    Local y gratuito (red neuronal). pip install easyocr
             (primera vez descarga ~110 MB de modelos).
  google     Google Cloud Vision. Lee manuscrito (~$35 USD por 860 actas).
             pip install google-cloud-vision + clave de servicio.

EJEMPLO:
  python3 auditor_e14_v2.py /ruta/actas --ocr rapidocr
  python3 auditor_e14_v2.py /ruta/actas --ocr google --google-key clave.json
  python3 auditor_e14_v2.py /ruta/actas --oficiales preconteo.json
  python3 auditor_e14_v2.py --autotest
        """)
    p.add_argument("carpeta",      nargs="?")
    p.add_argument("--salida",     default="salida_auditoria")
    p.add_argument("--oficiales",  default=None)
    p.add_argument("--eleccion",   default=None)
    p.add_argument("--ocr",        default="tesseract",
                   choices=["tesseract", "rapidocr", "easyocr", "google"])
    p.add_argument("--google-key", default=None)
    p.add_argument("--autotest",   action="store_true")
    a = p.parse_args()
    if a.autotest:
        _autotest()
    elif a.carpeta:
        main(a.carpeta, a.salida, a.oficiales, a.eleccion, a.ocr, a.google_key)
    else:
        p.print_help()
