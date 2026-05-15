# OSCAR — Orientador de Saberes Curriculares, Académicos y de Recursos

Agente docente especializado en educación colombiana. Apoya a docentes con planeaciones, mallas curriculares, guías, rúbricas, evaluaciones, proyectos STEM/maker, investigación escolar y toda la documentación académica requerida según los lineamientos del MEN.

## Características

- **Chat persistente** con historial completo por sesión (SQLite).
- **Carga de documentos** PDF o TXT para análisis e integración en el contexto.
- **Generación de documentos** descargables: planeaciones, guías, mallas, rúbricas, evaluaciones, actas, informes, etc.
- **Alineación normativa** con MEN, DBA, estándares básicos, Decreto 1290 y lineamientos curriculares.
- **Múltiples sesiones** de conversación con gestión desde el panel lateral.

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env y agrega tu ANTHROPIC_API_KEY
```

## Uso

```bash
streamlit run app.py
```

Abre el navegador en `http://localhost:8501`.

## Configuración

| Variable | Descripción | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Clave API de Anthropic (requerida) | — |
| `OSCAR_MODEL` | Modelo Claude a usar | `claude-opus-4-7` |

## Estructura

```
Oscar/
├── app.py              # Interfaz Streamlit
├── agent/
│   ├── oscar.py        # Agente principal (Claude API)
│   ├── memory.py       # Historial persistente (SQLite)
│   ├── tools.py        # Herramientas del agente
│   └── prompts.py      # System prompt de OSCAR
├── data/               # Base de datos y documentos generados (gitignored)
└── requirements.txt
```
