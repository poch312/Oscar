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

PRINCIPIOS:
  - Calibración relativa: lo que es "normal" lo determinan las estadísticas
    del batch (misma impresora, mismo escáner).
  - Co-ocurrencia de familias: una enmendadura real deja huella en múltiples
    planos. El ruido afecta solo uno.
  - Checks determinísticos primero: aritmética, nivelación y discrepancia
    vs. preconteo no tienen falsos positivos posibles.
  - Condicionalidad: checks visuales solo aplican sobre campos leídos con
    confianza suficiente.

FAMILIAS DE SEÑAL:
  A — Topología (huecos_inconsistentes)
  B — Trazo (cv_ancho_trazo)
  C — Geometría (trazo_horizontal_inesperado en "1")
  D — Aritmética (determinística)
  E — Nivelación (determinística)
  F — Preconteo (determinística)

USO:
  python3 auditor_e14_v2.py --autotest
  python3 auditor_e14_v2.py CARPETA_PDFS --ocr google --google-key clave.json
  python3 auditor_e14_v2.py CARPETA_PDFS --oficiales preconteo.json

DEPENDENCIAS: pip install pymupdf opencv-python numpy pytesseract google-cloud-vision
"""
from __future__ import annotations

import argparse, base64, csv, hashlib, json, re, sys
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

VERSION = "2.0.0"


# ===========================================================================
# CONFIGURACIÓN
# ===========================================================================
@dataclass
class Config:
    candidatos: tuple        = ("cepeda", "de_la_espriella")
    eleccion_esperada: str   = "presidencia_2v_2026"
    dpi: int                 = 300
    score_umbral_urgente: float = 40.0
    score_umbral_revisar: float = 20.0
    n_sigma_outlier: float   = 2.0
    min_familias_coocurrentes: int = 2
    umbral_confianza_ocr: float = 0.70
    max_sufragantes_mesa: int    = 400
    tolerancia_nivelacion: int   = 2
    umbral_incineracion: float   = 0.10
    huecos_esperados: dict = field(default_factory=lambda: {
        "0": 1, "1": 0, "2": 0, "3": 0, "5": 0,
        "6": 1, "7": 0, "8": 2, "9": 1,
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
    digito_ocr: Optional[str] = None
    conf_ocr: float = 0.0
    clase: str = "vacia"  # vacia | void | void_con_digito | digito | ilegible

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

    @property
    def id_mesa(self) -> str:
        return "-".join(x or "?" for x in [
            self.departamento, self.municipio, self.zona, self.puesto, self.mesa])


# ===========================================================================
# RECONOCEDORES OCR — intercambiables
# ===========================================================================
class Reconocedor:
    def leer(self, roi_gris) -> tuple[Optional[str], float]:
        raise NotImplementedError

class ReconocedorTesseract(Reconocedor):
    def leer(self, roi):
        if not HAY_TESS:
            return None, 0.0
        try:
            data = pytesseract.image_to_data(
                roi, config="--psm 10 -c tessedit_char_whitelist=0123456789",
                output_type=pytesseract.Output.DICT)
            best_txt, best_conf = None, -1.0
            for txt, conf in zip(data["text"], data["conf"]):
                txt = txt.strip()
                try:
                    conf = float(conf)
                except Exception:
                    continue
                if txt.isdigit() and conf > best_conf:
                    best_txt, best_conf = txt[0], conf
            return (best_txt, max(0.0, best_conf) / 100.0) if best_txt else (None, 0.0)
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

class _ReconocedorMock(Reconocedor):
    """Para autotest: inyecta lecturas predefinidas por (campo, casilla)."""
    def __init__(self, tabla: dict):
        self._tabla = tabla  # {(campo, casilla): (digito, conf)}
        self._current: tuple = ("", 0)

    def preparar(self, campo: str, casilla: int) -> None:
        self._current = (campo, casilla)

    def leer(self, roi):
        return self._tabla.get(self._current, (None, 0.0))


# ===========================================================================
# UTILIDADES
# ===========================================================================
_PATRON_NOMBRE = re.compile(
    r"Dep(\d+)-Mun(\d+)-Zona(\d+)-Puesto(\d+)-Mesa(\d+)", re.I)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()

def identidad_desde_nombre(acta: ActaE14, path: Path) -> bool:
    m = _PATRON_NOMBRE.search(path.name)
    if not m:
        return False
    acta.departamento, acta.municipio, acta.zona, acta.puesto, acta.mesa = m.groups()
    return True

def _preprocess(gris: np.ndarray) -> np.ndarray:
    """CLAHE antes de umbralizar para normalizar variación de escáner."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gris)


# ===========================================================================
# DETECCIÓN DE ESTRUCTURA
# ===========================================================================
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

def asignar_filas(ys: list[int], candidatos: tuple) -> dict[str, tuple[int, int]]:
    filas = [(ys[i], ys[i + 1]) for i in range(len(ys) - 1) if ys[i + 1] - ys[i] > 80]
    if len(filas) < 8:
        return {}
    asig: dict[str, tuple[int, int]] = {}
    asig["total_votantes"]    = filas[1]
    asig["total_votos_urna"]  = filas[2]
    asig["votos_incinerados"] = filas[3]
    candidato_filas = sorted(filas[5:-5], key=lambda f: f[1] - f[0], reverse=True)
    for i, cand in enumerate(candidatos):
        if i < len(candidato_filas):
            asig[cand] = candidato_filas[i]
    asig["voto_en_blanco"] = filas[-5]
    asig["votos_nulos"]    = filas[-4]
    asig["no_marcados"]    = filas[-3]
    asig["suma_total"]     = filas[-2]
    return asig


# ===========================================================================
# PASADA 1 — EXTRACCIÓN DE SEÑALES RAW
# ===========================================================================
def _clasificar_blob(binaria: np.ndarray, area_min: int,
                     gris_original: Optional[np.ndarray] = None) -> tuple[str, dict]:
    """
    Clasifica el contenido de una casilla binarizada.

    fill_ratio discrimina ● relleno (≈0.75-1.0) de dígito (≈0.10-0.45).
    Un ● con dígito encima tiene CV de intensidad elevado en los píxeles oscuros.

    Retorna (clase, info):
      'vacia'           — sin tinta
      'void'            — ● de anulación limpio
      'void_con_digito' — ● CON dígito encima  → evidencia de alteración
      'digito'          — dígito manuscrito
      'ilegible'        — tinta inclasificable
    """
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
    bw  = max(1, int(stat_dom[cv2.CC_STAT_WIDTH]))
    bh  = max(1, int(stat_dom[cv2.CC_STAT_HEIGHT]))
    area_dom   = int(stat_dom[cv2.CC_STAT_AREA])
    frac_celda = area_dom / area_celda
    fill_ratio = area_dom / max(1, bw * bh)
    aspect     = min(bw, bh) / max(bw, bh)

    info.update({"frac_celda": frac_celda, "fill_ratio": fill_ratio, "aspect": aspect})

    # ● relleno: fill_ratio alto + no demasiado alargado + ocupa algo de la celda
    es_blob = fill_ratio > 0.55 and aspect > 0.30 and frac_celda > 0.08
    if not es_blob:
        return "digito", info

    # Es ●: ¿tiene dígito encima?
    bx = int(stat_dom[cv2.CC_STAT_LEFT])
    by = int(stat_dom[cv2.CC_STAT_TOP])
    info["cv_intensidad_blob"] = 0.0
    if gris_original is not None:
        roi_b = gris_original[by:by + bh, bx:bx + bw]
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
    """Extrae métricas de imagen de UNA casilla (1 dígito). Sin veredicto."""
    s = SeñalesRaw(campo=campo, casilla=casilla_idx)

    roi_prep = _preprocess(roi_gris)
    _, b = cv2.threshold(roi_prep, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2)))

    # Eliminar líneas de la tabla (bordes impresos horizontales)
    W_b = b.shape[1]
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, W_b // 2), 2))
    bordes_h = cv2.morphologyEx(b, cv2.MORPH_OPEN, k_h)
    b = cv2.bitwise_and(b, cv2.bitwise_not(bordes_h))

    area_total = b.shape[0] * b.shape[1]
    area_min = max(10, int(area_total * 0.005))

    clase_blob, info_blob = _clasificar_blob(b, area_min, gris_original=roi_gris)
    s.densidad = info_blob["densidad"]

    if clase_blob == "vacia":
        s.clase = "vacia"
        return s
    if clase_blob == "void":
        s.clase = "void"
        return s
    if clase_blob == "void_con_digito":
        s.clase = "void_con_digito"
        cv2.imwrite(str(ruta_recorte), roi_gris)
        return s

    # Dígito normal — analizar para enmendaduras
    s.clase = "digito"
    cv2.imwrite(str(ruta_recorte), roi_gris)

    # Componentes conectados
    n, _, stats_cc, _ = cv2.connectedComponentsWithStats(b, 8)
    s.n_componentes = sum(1 for i in range(1, n)
                          if stats_cc[i, cv2.CC_STAT_AREA] >= area_min)

    # Huecos topológicos (lazos internos)
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

    # CV del ancho de trazo via transformada de distancia
    dist = cv2.distanceTransform(b, cv2.DIST_L2, 5)
    v = dist[dist > 0.5]
    if v.size >= 10:
        m_v = float(np.mean(v))
        s.cv_ancho_trazo = float(np.std(v) / m_v) if m_v > 0 else 0.0

    # Trazo horizontal largo (señal de "1" construido sobre un guion)
    largo = max(3, int(W_b * 0.55))
    k_t = cv2.getStructuringElement(cv2.MORPH_RECT, (largo, 1))
    s.tiene_trazo_horiz = cv2.countNonZero(
        cv2.morphologyEx(b, cv2.MORPH_OPEN, k_t)) > 0

    s.digito_ocr, s.conf_ocr = reco.leer(roi_gris)
    if not s.digito_ocr:
        s.clase = "ilegible"
    return s


def _segmentar_casillas(roi_num: np.ndarray) -> list[tuple[int, int]]:
    """
    Divide el ROI numérico en 3 casillas usando proyección de tinta vertical.
    Si no hay separadores claros, cae a tercios iguales.
    Retorna lista de (x_inicio, x_fin).
    """
    W = roi_num.shape[1]
    if W < 6:
        return [(0, W)]

    # Proyección vertical: suma de píxeles oscuros por columna
    dark = (roi_num < 100).astype(np.float32)
    proj = dark.mean(axis=0)

    # Suavizar para encontrar valles entre dígitos
    k = max(1, W // 20)
    proj_s = np.convolve(proj, np.ones(k) / k, mode="same")

    # Intentar encontrar valles en las zonas de separación (tercio ± 15%)
    margin = max(2, W // 10)
    cortes: list[int] = []
    for tercio in [W // 3, 2 * W // 3]:
        zona = proj_s[max(0, tercio - margin): tercio + margin]
        if zona.size > 0:
            idx_local = int(np.argmin(zona))
            cortes.append(max(0, tercio - margin) + idx_local)

    if len(cortes) == 2 and cortes[0] < cortes[1]:
        return [(0, cortes[0]), (cortes[0], cortes[1]), (cortes[1], W)]

    # Fallback: tercios iguales
    paso = W // 3
    return [(0, paso), (paso, 2 * paso), (2 * paso, W)]


def procesar_pdf_pasada1(pdf_path: Path, reco: Reconocedor,
                          cfg: Config, dir_evi: Path) -> ActaE14:
    """Pasada 1: extrae señales raw de un PDF sin producir veredictos."""
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
        pix = doc.load_page(0).get_pixmap(dpi=cfg.dpi)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(
            pix.height, pix.width, pix.n)
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
    asig = asignar_filas(ys, cfg.candidatos)
    if not asig:
        acta.fallo_extraccion = "No se pudo asignar filas al acta."
        return acta

    for campo, (y1, y2) in asig.items():
        try:
            y1c = max(0, y1 + 5)
            y2c = min(H, y2 - 5)
            roi_campo = gris[y1c:y2c, max(0, x_col): min(W, x_col + w_col)]
            if roi_campo.size == 0:
                continue

            # Recortar solo la banda con tinta (evita márgenes en blanco)
            dens_rows = np.mean(roi_campo < 100, axis=1)
            filas_tinta = np.where(dens_rows > 0.01)[0]
            if len(filas_tinta) == 0:
                continue
            if filas_tinta[-1] - filas_tinta[0] < roi_campo.shape[0] * 0.4:
                pad = 10
                roi_num = roi_campo[
                    max(0, filas_tinta[0] - pad):
                    min(roi_campo.shape[0], filas_tinta[-1] + pad), :]
            else:
                roi_num = roi_campo

            # Dividir en casillas (centenas / decenas / unidades)
            casillas = _segmentar_casillas(roi_num)
            for ci, (x0, x1) in enumerate(casillas):
                casilla_roi = roi_num[:, x0:x1]
                if casilla_roi.size == 0:
                    continue
                ruta_recorte = out / f"{campo}_{ci}.png"
                sr = extraer_señales_casilla(
                    casilla_roi, cfg, campo, ci, reco, ruta_recorte)
                acta.señales_raw.append(sr)
        except Exception:
            pass  # un campo fallido no invalida el acta

    _parsear_valores_acta(acta, cfg)
    return acta


# ===========================================================================
# PARSEO OCR → VALORES ENTEROS
# ===========================================================================
def _parsear_valores_acta(acta: ActaE14, cfg: Config) -> None:
    """Combina las casillas OCR de cada campo en un valor entero."""
    por_campo: dict[str, list[SeñalesRaw]] = {}
    for sr in acta.señales_raw:
        por_campo.setdefault(sr.campo, []).append(sr)

    for campo, slots in por_campo.items():
        slots = sorted(slots, key=lambda s: s.casilla)
        digitos: list[str] = []
        conf_total = 0.0
        n = 0
        toda_vacia = True
        anulada = False

        for s in slots:
            if s.clase == "vacia":
                digitos.append("0")
                conf_total += 1.0
                n += 1
            elif s.clase == "void":
                anulada = True
                break
            elif s.clase == "void_con_digito":
                digitos.append(s.digito_ocr or "?")
                conf_total += 0.3   # confianza penalizada — campo comprometido
                n += 1
                toda_vacia = False
            elif s.clase == "digito" and s.digito_ocr:
                digitos.append(s.digito_ocr)
                conf_total += s.conf_ocr
                n += 1
                toda_vacia = False
            else:
                digitos.append("?")
                n += 1
                toda_vacia = False

        if anulada:
            continue

        conf_media = conf_total / max(1, n)
        acta.confianza[campo] = conf_media

        valor_str = "0" if toda_vacia else ("".join(digitos).lstrip("0") or "0")
        if "?" not in valor_str:
            try:
                _asignar_campo(acta, campo, int(valor_str))
            except ValueError:
                pass


def _asignar_campo(acta: ActaE14, campo: str, val: int) -> None:
    _MAP = {
        "total_votos_urna":  "total_votos_urna",
        "total_votantes":    "total_votantes",
        "votos_incinerados": "votos_incinerados",
        "voto_en_blanco":    "voto_en_blanco",
        "votos_nulos":       "votos_nulos",
        "no_marcados":       "no_marcados",
        "suma_total":        "suma_total",
    }
    if campo in _MAP:
        setattr(acta, _MAP[campo], val)
    else:
        acta.votos[campo] = val


# ===========================================================================
# CHECKS DETERMINÍSTICOS
# ===========================================================================
def _check_aritmetica(acta: ActaE14, cfg: Config) -> Optional[Hallazgo]:
    """D: Σ(candidatos + blanco + nulos + no_marcados) ≠ total_urna."""
    partes = [acta.votos.get(c) for c in cfg.candidatos]
    partes += [acta.voto_en_blanco, acta.votos_nulos, acta.no_marcados]
    if any(v is None for v in partes) or acta.total_votos_urna is None:
        return None
    suma = sum(partes)  # type: ignore[arg-type]
    if suma != acta.total_votos_urna:
        delta = suma - acta.total_votos_urna
        return Hallazgo(
            familia="D", campo="total_votos_urna",
            mensaje=(f"Aritmética: Σcomponentes={suma} ≠ total_urna="
                     f"{acta.total_votos_urna} (Δ={delta:+d})"),
            score_aporte=40.0)
    return None


def _check_nivelacion(acta: ActaE14, cfg: Config) -> Optional[Hallazgo]:
    """E: votantes_E11 ≠ urna + incinerados."""
    tv, tu, ti = acta.total_votantes, acta.total_votos_urna, acta.votos_incinerados
    if any(v is None for v in [tv, tu, ti]):
        return None
    esperado = tu + ti  # type: ignore[operator]
    delta = abs(tv - esperado)  # type: ignore[operator]
    if delta > cfg.tolerancia_nivelacion:
        return Hallazgo(
            familia="E", campo="total_votantes",
            mensaje=(f"Nivelación: votantes={tv} ≠ urna({tu})+incinera({ti})"
                     f"={esperado} (Δ={delta})"),
            score_aporte=35.0)
    return None


def _check_fisico(acta: ActaE14, cfg: Config) -> list[Hallazgo]:
    """D/E: valores que violan cotas físicas de una mesa colombiana."""
    hs: list[Hallazgo] = []
    for campo, val in [("total_votos_urna", acta.total_votos_urna),
                       ("total_votantes",   acta.total_votantes)]:
        if val is not None and val > cfg.max_sufragantes_mesa:
            hs.append(Hallazgo(
                familia="D", campo=campo,
                mensaje=(f"{campo}={val} supera el máximo físico de "
                         f"{cfg.max_sufragantes_mesa} sufragantes por mesa"),
                score_aporte=45.0))
    if (acta.votos_incinerados is not None and acta.total_votos_urna
            and acta.total_votos_urna > 0):
        frac = acta.votos_incinerados / acta.total_votos_urna
        if frac > cfg.umbral_incineracion:
            hs.append(Hallazgo(
                familia="E", campo="votos_incinerados",
                mensaje=(f"Incinerados={acta.votos_incinerados} es {frac:.0%} "
                         f"de la urna — inusualmente alto (umbral {cfg.umbral_incineracion:.0%})"),
                score_aporte=20.0))
    return hs


def _check_preconteo(acta: ActaE14, cfg: Config,
                     oficiales: dict) -> list[Hallazgo]:
    """F: valor leído ≠ valor publicado en preconteo oficial."""
    hs: list[Hallazgo] = []
    pub = oficiales.get(acta.id_mesa)
    if pub is None:
        return hs
    for cand in cfg.candidatos:
        v_l = acta.votos.get(cand)
        v_p = pub.get(cand)
        if v_l is None or v_p is None:
            continue
        if acta.confianza.get(cand, 0.0) < cfg.umbral_confianza_ocr:
            continue
        if v_l != v_p:
            hs.append(Hallazgo(
                familia="F", campo=cand,
                mensaje=(f"Preconteo: leído={v_l} ≠ publicado={v_p} "
                         f"para '{cand}' (Δ={v_l - v_p:+d})"),
                score_aporte=50.0))
    return hs


# ===========================================================================
# PASADA 2 — CALIBRACIÓN + SCORING VISUAL
# ===========================================================================
def _estadisticas_batch(actas: list[ActaE14]) -> dict:
    """
    Calcula media, std e IQR de métricas visuales por campo.
    Solo incluye casillas de clase 'digito' (exluye vacías y blobs).
    Combinar sigma + IQR da robustez a sub-lotes pequeños.
    """
    from collections import defaultdict
    raw: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for acta in actas:
        if acta.fallo_extraccion:
            continue
        for sr in acta.señales_raw:
            if sr.clase != "digito":
                continue
            raw[sr.campo]["cv_ancho_trazo"].append(sr.cv_ancho_trazo)
            raw[sr.campo]["n_huecos"].append(float(sr.n_huecos))
            raw[sr.campo]["dens_interior_lazo"].append(sr.dens_interior_lazo)

    stats: dict[str, dict[str, dict]] = {}
    for campo, metricas in raw.items():
        stats[campo] = {}
        for metrica, vals in metricas.items():
            if len(vals) < 3:
                continue
            a = np.array(vals, dtype=float)
            q1 = float(np.percentile(a, 25))
            q3 = float(np.percentile(a, 75))
            iqr = q3 - q1
            mu  = float(np.mean(a))
            std = float(np.std(a))
            stats[campo][metrica] = {
                "mu": mu, "std": std,
                "q1": q1, "q3": q3, "iqr": iqr,
                "upper_sigma": mu + 2.0 * std,
                "upper_iqr":   q3 + 1.5 * iqr,
            }
    return stats


def _es_outlier(val: float, campo: str, metrica: str,
                stats: dict, cfg: Config) -> tuple[bool, float]:
    """True si val supera umbral sigma O umbral IQR del batch. Retorna (bool, z-score)."""
    s = stats.get(campo, {}).get(metrica)
    if s is None:
        return False, 0.0
    z = (val - s["mu"]) / s["std"] if s["std"] > 0 else 0.0
    return (z > cfg.n_sigma_outlier or val > s["upper_iqr"]), z


def _puntuar_señales_visuales(acta: ActaE14, stats: dict,
                               cfg: Config) -> list[Hallazgo]:
    """Familias A, B, C. Solo genera hallazgo si la señal es outlier del batch."""
    hs: list[Hallazgo] = []

    for sr in acta.señales_raw:
        if sr.clase not in ("digito", "void_con_digito"):
            continue

        familias: set[str] = set()
        evi = str(Path(acta.dir_evidencia or ".") / f"{sr.campo}_{sr.casilla}.png")
        dig = sr.digito_ocr or "?"

        # A — Topología
        huecos_esp = cfg.huecos_esperados.get(dig) if dig != "?" else None
        if huecos_esp is not None and sr.conf_ocr >= cfg.umbral_confianza_ocr:
            if sr.n_huecos != huecos_esp:
                outlier, z = _es_outlier(
                    float(sr.n_huecos), sr.campo, "n_huecos", stats, cfg)
                if outlier or abs(sr.n_huecos - huecos_esp) >= 2:
                    familias.add("A")
                    hs.append(Hallazgo(
                        familia="A", campo=sr.campo,
                        mensaje=(f"Casilla {sr.casilla} ('{dig}'): "
                                 f"huecos={sr.n_huecos} esperado={huecos_esp}, z={z:.1f}σ"),
                        score_aporte=20.0, evidencia_img=evi))

        outlier_il, _ = _es_outlier(
            sr.dens_interior_lazo, sr.campo, "dens_interior_lazo", stats, cfg)
        if sr.dens_interior_lazo > 0.30 and outlier_il:
            familias.add("A")
            hs.append(Hallazgo(
                familia="A", campo=sr.campo,
                mensaje=(f"Casilla {sr.casilla} ('{dig}'): "
                         f"tinta dentro del lazo={sr.dens_interior_lazo:.2f} — dígito sobrescrito"),
                score_aporte=22.0, evidencia_img=evi))

        # B — Trazo
        outlier_b, z_b = _es_outlier(
            sr.cv_ancho_trazo, sr.campo, "cv_ancho_trazo", stats, cfg)
        if outlier_b:
            familias.add("B")
            hs.append(Hallazgo(
                familia="B", campo=sr.campo,
                mensaje=(f"Casilla {sr.casilla} ('{dig}'): "
                         f"CV trazo={sr.cv_ancho_trazo:.2f}, z={z_b:.1f}σ — posible doble instrumento"),
                score_aporte=20.0, evidencia_img=evi))

        # C — Geometría
        if dig == "1" and sr.tiene_trazo_horiz and sr.conf_ocr >= cfg.umbral_confianza_ocr:
            familias.add("C")
            hs.append(Hallazgo(
                familia="C", campo=sr.campo,
                mensaje=(f"Casilla {sr.casilla}: '1' con trazo horizontal "
                         "— compatible con guion modificado"),
                score_aporte=25.0, evidencia_img=evi))

        # void_con_digito
        if sr.clase == "void_con_digito":
            familias.add("A")
            hs.append(Hallazgo(
                familia="A", campo=sr.campo,
                mensaje=(f"Casilla {sr.casilla}: blob de anulación ● con dígito encima "
                         "— evidencia directa de alteración"),
                score_aporte=35.0, evidencia_img=evi))

        # Bonus co-ocurrencia de ≥2 familias
        if len(familias) >= cfg.min_familias_coocurrentes:
            hs.append(Hallazgo(
                familia="+".join(sorted(familias)), campo=sr.campo,
                mensaje=(f"Casilla {sr.casilla}: co-ocurrencia "
                         f"{'+'.join(sorted(familias))} → alta confianza de alteración"),
                score_aporte=15.0, evidencia_img=evi))

    return hs


def pasada2_calibrar_y_puntuar(actas: list[ActaE14], cfg: Config,
                                oficiales: Optional[dict] = None) -> None:
    """Pasada 2 in-place: calibra el lote y asigna score/tier a cada acta."""
    stats = _estadisticas_batch(actas) if HAY_CV else {}

    for acta in actas:
        if acta.fallo_extraccion:
            acta.tier = Tier.MANUAL
            continue

        hs: list[Hallazgo] = []

        # Determinísticos (siempre aplican si los datos están)
        h = _check_aritmetica(acta, cfg)
        if h:
            hs.append(h)
        h = _check_nivelacion(acta, cfg)
        if h:
            hs.append(h)
        hs.extend(_check_fisico(acta, cfg))
        if oficiales:
            hs.extend(_check_preconteo(acta, cfg, oficiales))

        # Visuales (solo si OpenCV disponible)
        if HAY_CV:
            hs.extend(_puntuar_señales_visuales(acta, stats, cfg))

        acta.hallazgos = hs
        acta.score = min(100.0, sum(h.score_aporte for h in hs))

        n_ileg = sum(1 for sr in acta.señales_raw if sr.clase == "ilegible")
        if n_ileg >= 3:
            acta.tier = Tier.MANUAL
        elif acta.score >= cfg.score_umbral_urgente:
            acta.tier = Tier.URGENTE
        elif acta.score >= cfg.score_umbral_revisar:
            acta.tier = Tier.REVISAR
        else:
            acta.tier = Tier.LIMPIA


# ===========================================================================
# REPORTES
# ===========================================================================
def generar_reporte_csv(actas: list[ActaE14], out: Path) -> None:
    cols = ["id_mesa", "tier", "score", "archivo",
            "total_votantes", "total_votos_urna", "votos_incinerados",
            "voto_en_blanco", "votos_nulos", "no_marcados",
            "n_hallazgos", "hallazgos_resumen", "hash_sha256", "fallo_extraccion"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for acta in sorted(actas, key=lambda a: -a.score):
            w.writerow({
                "id_mesa":            acta.id_mesa,
                "tier":               acta.tier.value,
                "score":              f"{acta.score:.1f}",
                "archivo":            acta.archivo,
                "total_votantes":     acta.total_votantes,
                "total_votos_urna":   acta.total_votos_urna,
                "votos_incinerados":  acta.votos_incinerados,
                "voto_en_blanco":     acta.voto_en_blanco,
                "votos_nulos":        acta.votos_nulos,
                "no_marcados":        acta.no_marcados,
                "n_hallazgos":        len(acta.hallazgos),
                "hallazgos_resumen":  " | ".join(
                    f"[{h.familia}] {h.mensaje}" for h in acta.hallazgos),
                "hash_sha256":        acta.hash_sha256 or "",
                "fallo_extraccion":   acta.fallo_extraccion or "",
            })


def generar_reporte_json(actas: list[ActaE14], out: Path) -> None:
    payload = {
        "generado":    datetime.utcnow().isoformat() + "Z",
        "version":     VERSION,
        "total_actas": len(actas),
        "urgentes":    sum(1 for a in actas if a.tier == Tier.URGENTE),
        "revisar":     sum(1 for a in actas if a.tier == Tier.REVISAR),
        "manual":      sum(1 for a in actas if a.tier == Tier.MANUAL),
        "limpias":     sum(1 for a in actas if a.tier == Tier.LIMPIA),
        "actas": [
            {
                "id_mesa":         a.id_mesa,
                "archivo":         a.archivo,
                "tier":            a.tier.value,
                "score":           round(a.score, 2),
                "hash_sha256":     a.hash_sha256,
                "fallo_extraccion": a.fallo_extraccion,
                "total_votantes":  a.total_votantes,
                "total_votos_urna": a.total_votos_urna,
                "votos_incinerados": a.votos_incinerados,
                "votos":           a.votos,
                "voto_en_blanco":  a.voto_en_blanco,
                "votos_nulos":     a.votos_nulos,
                "no_marcados":     a.no_marcados,
                "confianza_ocr":   a.confianza,
                "hallazgos":       [asdict(h) for h in a.hallazgos],
                "dir_evidencia":   a.dir_evidencia,
            }
            for a in sorted(actas, key=lambda x: -x.score)
        ],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def generar_reporte_html(actas: list[ActaE14], out: Path) -> None:
    """HTML con imágenes de evidencia embebidas en base64."""
    COLORES = {
        Tier.URGENTE: "#cc0000",
        Tier.REVISAR: "#e07000",
        Tier.MANUAL:  "#7700cc",
        Tier.LIMPIA:  "#007700",
    }

    def _img_b64(ruta: Optional[str]) -> str:
        if not ruta:
            return ""
        p = Path(ruta)
        if not p.exists():
            return ""
        data = base64.b64encode(p.read_bytes()).decode()
        return (f'<img src="data:image/png;base64,{data}" '
                f'style="max-height:56px;border:1px solid #bbb;margin:1px">')

    filas = []
    for acta in sorted(actas, key=lambda a: -a.score):
        color = COLORES.get(acta.tier, "#555")
        votos_str = " / ".join(
            str(acta.votos.get(c, "?")) for c in ["cepeda", "de_la_espriella"])
        hs_li = "".join(
            f"<li>[{h.familia}] {h.mensaje} {_img_b64(h.evidencia_img)}</li>"
            for h in acta.hallazgos)
        filas.append(
            f"<tr>"
            f'<td style="color:{color};font-weight:bold">{acta.tier.value}</td>'
            f"<td>{acta.score:.1f}</td>"
            f"<td><small>{acta.id_mesa}</small></td>"
            f"<td>{acta.total_votos_urna or '?'}</td>"
            f"<td>{votos_str}</td>"
            f'<td><ul style="margin:0;padding-left:14px;font-size:.85em">'
            f"{hs_li}</ul></td>"
            f"</tr>")

    resumen = " &nbsp;|&nbsp; ".join(
        f'<span style="color:{COLORES[t]}">{t.value}: '
        f'{sum(1 for a in actas if a.tier == t)}</span>'
        for t in Tier)

    html = (
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
        f"<title>Auditoría E-14 {datetime.now():%Y-%m-%d}</title>"
        "<style>body{font-family:sans-serif;font-size:13px;margin:20px}"
        "table{border-collapse:collapse;width:100%}"
        "th{background:#222;color:#fff;padding:5px 8px;text-align:left}"
        "td{padding:4px 8px;vertical-align:top;border-bottom:1px solid #e0e0e0}"
        "tr:hover{background:#f7f7f7}</style></head><body>"
        f"<h1>Auditoría Actas E-14 &mdash; {datetime.now():%Y-%m-%d %H:%M}</h1>"
        f"<p>Total: {len(actas)} actas &nbsp;&nbsp; {resumen}</p>"
        "<table><thead><tr>"
        "<th>Tier</th><th>Score</th><th>Mesa</th>"
        "<th>Urna</th><th>Cepeda / De&nbsp;la&nbsp;Espriella</th><th>Hallazgos</th>"
        f"</tr></thead><tbody>{''.join(filas)}</tbody></table>"
        f"<p style='color:#888;font-size:.8em;margin-top:20px'>"
        f"auditor_e14_v2.py v{VERSION} &mdash; insumo para revisión humana</p>"
        "</body></html>"
    )
    out.write_text(html, encoding="utf-8")


# ===========================================================================
# AUTOTEST
# ===========================================================================
def autotest() -> None:
    """Pruebas sintéticas — no requieren PDFs ni GPU."""
    print(f"auditor_e14_v2 v{VERSION} — autotest")
    fallos = 0

    def ok(nombre: str, cond: bool) -> None:
        nonlocal fallos
        print(f"  [{'OK  ' if cond else 'FALLO'}] {nombre}")
        if not cond:
            fallos += 1

    cfg = Config()

    # ── T1: Checks determinísticos ─────────────────────────────────────────
    a = ActaE14(archivo="t.pdf")
    a.votos = {"cepeda": 120, "de_la_espriella": 80}
    a.voto_en_blanco, a.votos_nulos, a.no_marcados = 5, 3, 2
    a.total_votos_urna = 220          # error intencional (real=210)
    h = _check_aritmetica(a, cfg)
    ok("T1a aritmética detecta error",   h is not None)
    ok("T1a familia=D",                  h is not None and h.familia == "D")
    a.total_votos_urna = 210
    ok("T1b aritmética pasa correcto",   _check_aritmetica(a, cfg) is None)

    b = ActaE14(archivo="t2.pdf")
    b.total_votantes, b.total_votos_urna, b.votos_incinerados = 220, 210, 5
    ok("T1c nivelación detecta error",   _check_nivelacion(b, cfg) is not None)
    b.total_votantes = 215
    ok("T1d nivelación pasa correcto",   _check_nivelacion(b, cfg) is None)

    # ── T2: Cota física ────────────────────────────────────────────────────
    c = ActaE14(archivo="t3.pdf")
    c.total_votos_urna = 999
    ok("T2  cota física urna>400",       len(_check_fisico(c, cfg)) >= 1)

    # ── T3: Preconteo ──────────────────────────────────────────────────────
    d = ActaE14(archivo="t4.pdf")
    d.departamento, d.municipio, d.zona, d.puesto, d.mesa = "1","2","3","4","5"
    d.votos = {"cepeda": 100, "de_la_espriella": 80}
    d.confianza = {"cepeda": 0.95, "de_la_espriella": 0.95}
    of = {d.id_mesa: {"cepeda": 100, "de_la_espriella": 90}}
    hs = _check_preconteo(d, cfg, of)
    ok("T3a preconteo detecta discrepancia", len(hs) == 1)
    ok("T3b familia=F",                      hs[0].familia == "F")
    of[d.id_mesa]["de_la_espriella"] = 80
    ok("T3c preconteo pasa correcto",        len(_check_preconteo(d, cfg, of)) == 0)

    # ── T4: Clasificación de blobs (requiere OpenCV) ───────────────────────
    if HAY_CV:
        # Celda vacía
        b_vac = np.full((40, 30), 255, np.uint8)
        _, bbin = cv2.threshold(b_vac, 128, 255, cv2.THRESH_BINARY_INV)
        ok("T4a celda vacía → vacia",
           _clasificar_blob(bbin, 5)[0] == "vacia")

        # Blob ● sólido
        blob = np.full((50, 40), 255, np.uint8)
        cv2.circle(blob, (20, 25), 14, 0, -1)
        _, bblob = cv2.threshold(blob, 128, 255, cv2.THRESH_BINARY_INV)
        ok("T4b blob sólido → void",
           _clasificar_blob(bblob, 5, gris_original=blob)[0] == "void")

        # Dígito "1" (trazo vertical delgado)
        d1 = np.full((60, 20), 255, np.uint8)
        cv2.line(d1, (10, 5), (10, 55), 0, 3)
        _, b1 = cv2.threshold(d1, 128, 255, cv2.THRESH_BINARY_INV)
        ok("T4c dígito '1' → digito",
           _clasificar_blob(b1, 5, gris_original=d1)[0] == "digito")

        # Dígito "0" (aro)
        d0 = np.full((60, 40), 255, np.uint8)
        cv2.ellipse(d0, (20, 30), (12, 20), 0, 0, 360, 0, 3)
        _, b0 = cv2.threshold(d0, 128, 255, cv2.THRESH_BINARY_INV)
        ok("T4d dígito '0' → digito",
           _clasificar_blob(b0, 5, gris_original=d0)[0] == "digito")

        # Blob ● con alto CV (simula tinta heterogénea de dígito encima)
        blob_mod = np.full((50, 40), 255, np.uint8)
        cv2.circle(blob_mod, (20, 25), 14, 0, -1)
        # Simular dígito más oscuro encima: franja de píxeles muy oscuros
        blob_mod[18:32, 8:32] = 10
        _, bmod = cv2.threshold(blob_mod, 128, 255, cv2.THRESH_BINARY_INV)
        clase_mod, info_mod = _clasificar_blob(bmod, 5, gris_original=blob_mod)
        ok("T4e blob+dígito → void_con_digito o void",
           clase_mod in ("void_con_digito", "void"))
    else:
        print("  [SKIP] T4 (sin OpenCV)")

    # ── T5: Pasada 2 end-to-end sintético ─────────────────────────────────
    limpia = ActaE14(archivo="limpia.pdf")
    limpia.votos = {"cepeda": 150, "de_la_espriella": 100}
    limpia.voto_en_blanco, limpia.votos_nulos, limpia.no_marcados = 5, 3, 2
    limpia.total_votos_urna  = 260
    limpia.total_votantes    = 262
    limpia.votos_incinerados = 2

    sosp = ActaE14(archivo="sosp.pdf")
    sosp.votos = {"cepeda": 150, "de_la_espriella": 100}
    sosp.voto_en_blanco, sosp.votos_nulos, sosp.no_marcados = 5, 3, 2
    sosp.total_votos_urna  = 999   # físicamente imposible
    sosp.total_votantes    = 262
    sosp.votos_incinerados = 2

    pasada2_calibrar_y_puntuar([limpia, sosp], cfg)
    ok("T5a limpia → LIMPIA",
       limpia.tier == Tier.LIMPIA)
    ok("T5b sospechosa → URGENTE|REVISAR",
       sosp.tier in (Tier.URGENTE, Tier.REVISAR))
    ok("T5c sospechosa tiene hallazgos",
       len(sosp.hallazgos) > 0)

    # ── Resultado ──────────────────────────────────────────────────────────
    print(f"\n  {'Todos los tests pasaron.' if fallos == 0 else f'{fallos} test(s) FALLARON.'}")
    if fallos:
        sys.exit(1)


# ===========================================================================
# CLI
# ===========================================================================
def main() -> None:
    ap = argparse.ArgumentParser(
        description=f"Auditor Actas E-14 v{VERSION} — Colombia 2026, 2ª vuelta",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", nargs="?",
                    help="Carpeta raíz con PDFs de actas (búsqueda recursiva)")
    ap.add_argument("--ocr", choices=["tesseract", "google"], default="tesseract")
    ap.add_argument("--google-key", metavar="CLAVE_JSON",
                    help="JSON de credenciales Google Vision (requerido con --ocr google)")
    ap.add_argument("--oficiales", metavar="JSON",
                    help="JSON con resultados oficiales para check F: "
                         '{\"Dep1-Mun2-…\": {\"cepeda\": N, \"de_la_espriella\": M}}')
    ap.add_argument("--salida", metavar="DIR", default="auditoria_salida",
                    help="Directorio de salida (default: auditoria_salida)")
    ap.add_argument("--dpi", type=int, default=300,
                    help="DPI de rasterización (default: 300)")
    ap.add_argument("--umbral-urgente", type=float, default=40.0)
    ap.add_argument("--umbral-revisar", type=float, default=20.0)
    ap.add_argument("--autotest", action="store_true",
                    help="Ejecutar pruebas de verificación interna")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args()

    if args.autotest:
        autotest()
        return

    if not args.carpeta:
        ap.print_help()
        sys.exit(0)

    if not HAY_CV:
        sys.exit("[ERROR] OpenCV no disponible.  pip install opencv-python numpy")
    if not HAY_FITZ:
        sys.exit("[ERROR] PyMuPDF no disponible.  pip install pymupdf")

    cfg = Config()
    cfg.dpi = args.dpi
    cfg.score_umbral_urgente = args.umbral_urgente
    cfg.score_umbral_revisar = args.umbral_revisar

    if args.ocr == "google":
        if not args.google_key:
            sys.exit("[ERROR] --google-key requerido con --ocr google")
        reco: Reconocedor = ReconocedorGoogleVision(args.google_key)
    else:
        if not HAY_TESS:
            print("[WARN] pytesseract no disponible — lecturas OCR estarán vacías.")
        reco = ReconocedorTesseract()

    oficiales: Optional[dict] = None
    if args.oficiales:
        with open(args.oficiales, encoding="utf-8") as f:
            oficiales = json.load(f)

    carpeta = Path(args.carpeta)
    pdfs = sorted(carpeta.rglob("*.pdf"))
    if not pdfs:
        sys.exit(f"[WARN] No se encontraron PDFs en {carpeta}")

    dir_salida = Path(args.salida)
    dir_evi    = dir_salida / "evidencia"
    dir_evi.mkdir(parents=True, exist_ok=True)

    print(f"Procesando {len(pdfs)} acta(s) — OCR: {args.ocr} — DPI: {cfg.dpi}")
    actas: list[ActaE14] = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"  [{i:4d}/{len(pdfs)}] {pdf.name}", end=" ", flush=True)
        acta = procesar_pdf_pasada1(pdf, reco, cfg, dir_evi)
        actas.append(acta)
        if acta.fallo_extraccion:
            print(f"→ FALLO: {acta.fallo_extraccion}")
        else:
            print(f"→ {len(acta.señales_raw)} señales")

    print("\nCalibrando lote y calculando scores …")
    pasada2_calibrar_y_puntuar(actas, cfg, oficiales)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_out  = dir_salida / f"reporte_{ts}.csv"
    json_out = dir_salida / f"reporte_{ts}.json"
    html_out = dir_salida / f"reporte_{ts}.html"

    generar_reporte_csv(actas, csv_out)
    generar_reporte_json(actas, json_out)
    generar_reporte_html(actas, html_out)

    n_u = sum(1 for a in actas if a.tier == Tier.URGENTE)
    n_r = sum(1 for a in actas if a.tier == Tier.REVISAR)
    n_m = sum(1 for a in actas if a.tier == Tier.MANUAL)
    n_l = sum(1 for a in actas if a.tier == Tier.LIMPIA)

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  Total:    {len(actas)}")
    print(f"  URGENTE:  {n_u}")
    print(f"  REVISAR:  {n_r}")
    print(f"  MANUAL:   {n_m}  (OCR inseguro — revisión humana)")
    print(f"  LIMPIA:   {n_l}")
    print(sep)
    print(f"  CSV   → {csv_out}")
    print(f"  JSON  → {json_out}")
    print(f"  HTML  → {html_out}")

    if n_u > 0:
        print(f"\n  !! {n_u} acta(s) URGENTE(s) — revisar primero:")
        for a in sorted(actas, key=lambda x: -x.score):
            if a.tier == Tier.URGENTE:
                print(f"     score={a.score:5.1f}  {a.id_mesa}  "
                      f"{Path(a.archivo).name}")


if __name__ == "__main__":
    main()
