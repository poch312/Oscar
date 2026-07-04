# Arquitectura

Ver el plan completo de diseño en la conversación original; este documento
resume lo esencial para quien continúe el proyecto.

## Principio central

Cada capa de evidencia detecta un mecanismo de fraude distinto, a una unidad
de análisis distinta, y ninguna reemplaza a las otras:

| Capa | Unidad de análisis | Qué detecta | Qué NO detecta |
|---|---|---|---|
| Metadatos/hash | archivo individual | archivo reeditado tras el escaneo, imágenes duplicadas entre "mesas distintas" | ediciones que preservan contenido, fraude físico |
| Consistencia aritmética/OCR | acta individual | contradicciones internas (suma ≠ total, dígitos ≠ letras) | una falsificación autoconsistente |
| ELA + CNN two-stream | acta/página individual | edición digital de píxeles de la imagen escaneada | fraude cometido antes del escaneo (trashteo, coacción) sobre imagen limpia |
| Cruce con fuente oficial (fase 2+) | mesa, requiere datos externos | fraude de transcripción/digitación entre acta física y sistema | fraude anterior a la firma del acta |
| Benford/último dígito + Mebane/eforensics | lote completo de mesas | firmas estadísticas de manipulación sistemática | atribución certera a una mesa/imagen específica |

## Hoja de ruta

- **Fase 0 (implementada)**: ingesta PDF, detección automática de tabla,
  OCR ensemble, chequeo aritmético, chequeo de metadatos, puntaje de
  manipulación experimental (requiere entrenar sobre CASIA + calibrar).
- **Fase 1**: `oscar analyze-batch` (Benford/último dígito) en producción real;
  recolectar actas genuinas reales y cualquier caso confirmado de alteración;
  esqueleto de `official_crosscheck.py` a la espera de un dump estructurado
  del preconteo/escrutinio oficial.
- **Fase 2**: fine-tuning del CNN con datos reales de actas (aumentación
  sintética como sustituto interino ante la escasez de casos reales
  confirmados); integración completa de `mebane_bridge.py`/`eforensics`
  (requiere especificación de fórmula con criterio de ciencia
  política/estadística electoral); robustecer el cruce oficial.
- **Fase 3**: API (FastAPI) sobre `pipeline.py`, dashboard, procesamiento
  distribuido a escala nacional, reentrenamiento continuo.

## Riesgos y limitaciones conocidas

- **Transferencia de dominio ELA/CNN sin verificar**: CASIA son fotos
  naturales con artefactos JPEG; los PDF de la Registraduría pueden usar
  `/CCITTFaxDecode` u otros filtros sin pérdida, donde ELA puede no aplicar.
  `oscar ingest` reporta el filtro de cada página para verificar esto
  empíricamente antes de confiar en el puntaje.
- **La calibración con actas de referencia solo mueve un umbral**, no corrige
  el modelo subyacente. Tratar el puntaje de manipulación como orientativo,
  nunca como determinación de fraude.
- **La detección de tabla es un problema de visión abierto**: ante fallos de
  confianza, el pipeline marca `needs_review` en vez de forzar una lectura
  de baja confianza.
- **Errores de OCR en escritura a mano son inherentes**; el chequeo
  aritmético es necesario pero no suficiente.
- **Casi ausencia de casos reales confirmados de alteración** es el riesgo
  central del proyecto: ninguna afirmación de precisión/recall es verificable
  todavía. El framing en todo el sistema es "señalización para revisión
  humana", nunca "determinación de fraude".
- **Cadena de custodia**: la ingesta nunca sobrescribe los PDFs originales;
  se hashea cada entrada (`oscar.io.file_discovery`) para trazabilidad.
