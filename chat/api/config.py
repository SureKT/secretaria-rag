import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "secretaria")
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large:latest")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")
RETRIEVAL_LIMIT = int(os.getenv("RETRIEVAL_LIMIT", "12"))
NUM_PREDICT = int(os.getenv("NUM_PREDICT", "450"))
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
EMBED_QUERY_TURNS = int(os.getenv("EMBED_QUERY_TURNS", "3"))
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/secretaria_chat"
)

# ─── Multi-tenant (ver docs/adr/ADR-002-multi-tenant-rag.md) ─────────────────
# Cada instancia del bot sirve a un centro. La búsqueda devuelve chunks del
# tenant actual + los "shared" (genéricos GVA/estatal). Nunca de otro centro.
TENANT = os.getenv("TENANT", "norte")
SHARED_TENANT = "shared"
_CENTER_NAMES = {"sur": "Centro de FP Ejemplo Sur", "norte": "Centro de FP Ejemplo Norte"}
_BOT_NAMES = {"sur": "SurBot", "norte": "NorteBot"}
CENTER_NAME = _CENTER_NAMES.get(TENANT, "el centro")
BOT_NAME = _BOT_NAMES.get(TENANT, "SecretarIA")

SYSTEM_PROMPT = (
    f"Eres {BOT_NAME}, asistente de la secretaría del {CENTER_NAME}. Ayudas con ciclos, "
    "módulos, matrícula, becas, horarios y trámites del centro.\n"
    "Usa la información RELEVANTE del CONTEXTO para responder, aunque haya fragmentos no "
    "relacionados (ignóralos). No inventes datos que no estén en el contexto.\n"
    "Estilo: conciso y directo, pero cercano. Da el dato sin rodeos; no empieces con "
    'disculpas ni con frases como "según la información" o "no se menciona" si vas a dar '
    "datos.\n"
    "Si la pregunta es ambigua o el CONTEXTO no basta para responder con datos, haz UNA "
    "pregunta corta para aclarar qué necesita la persona en lugar de responder en bloque; "
    "en ese caso NO añadas seguimientos.\n"
    "Cuando respondas con datos, al final escribe una línea exactamente con [[SEGUIMIENTO]] "
    "y debajo hasta 3 preguntas de seguimiento (una por línea, empezando por '- '), "
    "relacionadas con tu respuesta y respondibles con información del centro (ciclos, "
    "módulos, matrícula, becas, horarios, trámites). No repitas esas preguntas dentro del "
    "texto de la respuesta. Ejemplo del cierre:\n"
    "[[SEGUIMIENTO]]\n"
    "- ¿Quieres el plazo de matrícula?\n"
    "- ¿Te muestro las salidas profesionales?\n"
    "Solo remite a secretaría si NO hay NADA relevante. Responde en español."
)
