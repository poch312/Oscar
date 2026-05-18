"""
Intent detection for multi-agent routing.
Keyword-based — zero extra LLM calls, instant, token-free.
"""

_PATTERNS: dict[str, list[str]] = {
    "stem": [
        "maker", "steam", "stem", "arduino", "scratch", "prototipo",
        "robótica", "robotica", "impresión 3d", "impresion 3d", "sensor",
        "proyecto stem", "proyecto maker", "design thinking",
        "monitoreo acústico", "monitoreo acustico", "ods",
        "interdisciplinar", "electrónica", "electronica",
    ],
    "evaluacion": [
        "rúbrica", "rubrica", "evaluación", "evaluacion", "decreto 1290",
        "escala valorativa", "nivel de desempeño", "nivel de desempeno",
        "saber 9", "saber 11", "icfes", "autoevaluación", "autoevaluacion",
        "coevaluación", "coevaluacion", "superior alto básico bajo",
        "superior alto basico bajo", "instrumento de evaluación",
        "instrumento de evaluacion", "prueba escrita", "valoración",
        "valoracion",
    ],
    "planeacion": [
        "planeación", "planeacion", "planear", "plan de clase",
        "unidad didáctica", "unidad didactica", "secuencia didáctica",
        "secuencia didactica", "plan de aula", "diseña una clase",
        "diseña la clase", "planifica", "sesión de", "sesion de",
        "actividad para grado", "clase sobre", "enseñar",
    ],
    "curricular": [
        "dba", "estándar", "estandar", "malla curricular", "plan de área",
        "plan de area", "lineamiento", "currículo", "curriculo",
        "competencia matemática", "competencia matematica",
        "pensamiento numérico", "pensamiento espacial", "pensamiento métrico",
        "pensamiento estadístico", "pensamiento variacional",
        "núcleo temático", "nucleo tematico", "eje curricular",
        "alineación curricular", "alineacion curricular",
    ],
    "documental": [
        "acta", "acta de", "informe académico", "informe academico",
        "circular", "concepto pedagógico", "concepto pedagogico",
        "siee", "pei", "plan de mejoramiento", "evidencia docente",
        "comunicado", "documento institucional", "informe disciplinario",
        "piar", "ajuste razonable",
    ],
}

# Priority order: more specific intents first
_ORDER = ["stem", "evaluacion", "planeacion", "curricular", "documental"]


def detect_intent(message: str) -> str:
    """Returns the best matching agent intent, or 'general'."""
    text = message.lower()
    scores: dict[str, int] = {}
    for intent in _ORDER:
        count = sum(1 for kw in _PATTERNS[intent] if kw in text)
        if count:
            scores[intent] = count
    if not scores:
        return "general"
    return max(scores, key=lambda k: scores[k])
