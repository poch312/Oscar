# Oscar — Auditor Forense de Actas E14

Herramienta de auditoría forense para actas E14 (formulario de escrutinio de
mesa de Colombia), orientada a **señalar anomalías para revisión humana**, no
a emitir determinaciones de fraude.

Combina cinco capas de evidencia independientes — metadatos/hash del archivo,
consistencia aritmética interna, detección de manipulación de imagen (ELA +
CNN two-stream), cruce contra resultados oficiales (fase 2+), y estadística
poblacional (Benford / Mebane-eforensics) — porque cada una detecta un
mecanismo de fraude distinto y ninguna reemplaza a las otras. Ver
[`docs/architecture.md`](docs/architecture.md) para el diseño completo,
límites conocidos y la hoja de ruta por fases.

## Instalación

```bash
pip install -e ".[dev]"
```

Requiere además, en el sistema: `tesseract-ocr` (OCR fallback) y, opcionalmente,
`R` + `JAGS` para la integración futura con `eforensics` (fase 2+).

## Uso

```bash
# Ingesta de prueba: verifica que los PDFs se leen y muestra el tipo de
# compresión de cada página (determina si ELA será significativo).
oscar ingest actas/

# Calibrar el umbral de manipulación con actas genuinas de referencia
# (se requieren ~10 o más).
oscar calibrate --reference-genuine-dir actas_genuinas/

# Auditoría completa de una carpeta de actas
oscar audit actas/ -o reporte.json --csv reporte.csv

# Heurísticas estadísticas por lote (Benford, último dígito) sobre el
# acumulado de mesas procesadas
oscar analyze-batch --store mesa_results.csv
```

## Estado

Fase 0 (MVP): ingesta de PDF, detección automática de tabla, OCR ensemble,
chequeo aritmético y chequeo de metadatos están funcionales end-to-end. El
puntaje de manipulación (ELA + CNN two-stream) requiere entrenar un modelo
sobre CASIA 2.0 (`scripts/train_tamper_model.py`) antes de producir resultados;
sin checkpoint, se reporta explícitamente como no disponible en lugar de un
número engañoso.
