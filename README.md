# OSCAR — Orientador de Saberes Curriculares, Académicos y de Recursos

Agente docente especializado en educación colombiana. Apoya a docentes con planeaciones, mallas curriculares, guías, rúbricas, evaluaciones, proyectos STEM/maker, investigación escolar y toda la documentación académica requerida según los lineamientos del MEN.

## Características

- **Chat persistente** con historial completo por sesión (SQLite).
- **Carga de documentos** PDF o TXT para análisis e integración en el contexto.
- **Generación de documentos** descargables: planeaciones, guías, mallas, rúbricas, evaluaciones, actas, informes, etc.
- **Alineación normativa** con MEN, DBA, estándares básicos, Decreto 1290 y lineamientos curriculares.
- **Múltiples sesiones** de conversación con gestión desde el panel lateral.
- **Interfaz web móvil** accesible desde el navegador del celular.

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env y agrega tu GROQ_API_KEY
```

## Uso

```bash
python app.py
```

Abre el navegador en `http://localhost:5000`.

## Configuración

| Variable | Descripción | Default |
|---|---|---|
| `GROQ_API_KEY` | Clave API de Groq (requerida) — consíguela gratis en console.groq.com | — |
| `OSCAR_MODEL` | Modelo a usar | `llama-3.3-70b-versatile` |

## Estructura

```
Oscar/
├── app.py              # Servidor Flask + interfaz web embebida
├── agent/
│   ├── oscar.py        # Agente principal (Groq API)
│   ├── memory.py       # Historial persistente (SQLite)
│   ├── tools.py        # Herramientas del agente (guardar_documento)
│   └── prompts.py      # System prompt de OSCAR
├── data/               # Base de datos y documentos generados (gitignored)
└── requirements.txt
```
