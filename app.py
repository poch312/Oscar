import io
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent import memory
from agent.oscar import OscarAgent

memory.init_db()

st.set_page_config(
    page_title="OSCAR – Agente Docente",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _extract_pdf_text(file_bytes: bytes, filename: str) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = [page.get_text() for page in doc]
        doc.close()
        text = "\n\n".join(p for p in pages if p.strip())
        return text[:80_000]  # ~80 k chars to stay within context limits
    except Exception as e:
        return f"[No se pudo extraer el texto de '{filename}': {e}]"


def _get_or_create_session() -> str:
    if "session_id" not in st.session_state:
        sessions = memory.get_sessions()
        if sessions:
            st.session_state.session_id = sessions[0]["id"]
        else:
            st.session_state.session_id = memory.create_session()
    return st.session_state.session_id


def _switch_session(session_id: str) -> None:
    st.session_state.session_id = session_id
    st.session_state.pop("agent", None)
    st.session_state.pop("saved_files", None)


def _get_agent(session_id: str) -> OscarAgent | None:
    if "agent" not in st.session_state or st.session_state.get("_agent_session") != session_id:
        try:
            st.session_state.agent = OscarAgent(session_id)
            st.session_state._agent_session = session_id
        except ValueError as e:
            st.error(str(e))
            return None
    return st.session_state.agent


def _display_messages(messages: list[dict]) -> None:
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role not in ("user", "assistant"):
            continue
        if isinstance(content, list):
            text_parts = [
                b["text"] for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            display_text = "\n".join(text_parts).strip()
            if not display_text:
                continue
        else:
            display_text = str(content)
            if not display_text.strip():
                continue
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(display_text)


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📚 OSCAR")
    st.caption("Orientador de Saberes Curriculares, Académicos y de Recursos")
    st.divider()

    if st.button("＋ Nueva conversación", use_container_width=True):
        new_id = memory.create_session()
        _switch_session(new_id)
        st.rerun()

    sessions = memory.get_sessions()
    current_session_id = _get_or_create_session()

    st.markdown("### Conversaciones")
    for s in sessions:
        cols = st.columns([5, 1])
        label = s["name"][:35] + ("…" if len(s["name"]) > 35 else "")
        btn_type = "primary" if s["id"] == current_session_id else "secondary"
        if cols[0].button(label, key=f"sess_{s['id']}", use_container_width=True, type=btn_type):
            _switch_session(s["id"])
            st.rerun()
        if cols[1].button("🗑", key=f"del_{s['id']}", help="Eliminar conversación"):
            memory.delete_session(s["id"])
            if s["id"] == current_session_id:
                remaining = [x for x in sessions if x["id"] != s["id"]]
                new_id = remaining[0]["id"] if remaining else memory.create_session()
                _switch_session(new_id)
            st.rerun()

    st.divider()
    st.markdown("### Cargar documento")
    uploaded = st.file_uploader(
        "PDF o TXT",
        type=["pdf", "txt"],
        key="file_uploader",
        label_visibility="collapsed",
    )
    if uploaded and not memory.document_exists(current_session_id, uploaded.name):
        file_bytes = uploaded.read()
        if uploaded.name.lower().endswith(".pdf"):
            doc_text = _extract_pdf_text(file_bytes, uploaded.name)
        else:
            doc_text = file_bytes.decode("utf-8", errors="replace")[:80_000]

        memory.add_document(current_session_id, uploaded.name, doc_text)
        context_msg = (
            f"El docente ha cargado el documento **'{uploaded.name}'**.\n\n"
            f"Contenido del documento:\n\n{doc_text}\n\n"
            "Analiza este documento y confirma que lo has procesado."
        )
        agent = _get_agent(current_session_id)
        if agent:
            with st.spinner(f"Analizando '{uploaded.name}'…"):
                try:
                    agent.chat(context_msg)
                except Exception as e:
                    st.error(f"Error al procesar documento: {e}")
        st.rerun()

    docs = memory.get_documents(current_session_id)
    if docs:
        st.markdown("**Documentos cargados:**")
        for d in docs:
            st.caption(f"📄 {d['filename']}")

    st.divider()
    st.caption("Powered by Claude · Anthropic")


# ── main chat ─────────────────────────────────────────────────────────────────

session_id = _get_or_create_session()
agent = _get_agent(session_id)

st.markdown("# 📚 OSCAR — Agente Docente")
st.caption("Especialista en educación colombiana · Matemáticas · STEM · Investigación escolar")

if not os.getenv("ANTHROPIC_API_KEY"):
    st.warning(
        "Configura tu `ANTHROPIC_API_KEY` en el archivo `.env` para comenzar. "
        "Copia `.env.example` a `.env` y agrega tu clave.",
        icon="⚠️",
    )
    st.stop()

messages = memory.get_messages(session_id)
_display_messages(messages)

if "saved_files" not in st.session_state:
    st.session_state.saved_files = []

for saved in st.session_state.saved_files:
    filepath = Path(saved["filepath"])
    if filepath.exists():
        with st.expander(f"📥 Documento generado: {saved['filename']}", expanded=True):
            content = filepath.read_text(encoding="utf-8")
            st.download_button(
                label="Descargar documento",
                data=content,
                file_name=saved["filename"],
                mime="text/plain",
                key=f"dl_{saved['filename']}",
            )

if not messages:
    st.info(
        "Hola, soy OSCAR. Estoy aquí para ayudarte con planeaciones, mallas curriculares, "
        "guías, rúbricas, evaluaciones, proyectos STEM y toda la documentación docente que necesites. "
        "¿Con qué empezamos?"
    )

if prompt := st.chat_input("Escribe tu consulta aquí…"):
    with st.chat_message("user"):
        st.markdown(prompt)

    if agent is None:
        st.error("No hay un agente activo. Verifica la configuración de ANTHROPIC_API_KEY.")
        st.stop()

    # Auto-name session from first real user message
    if len([m for m in messages if m["role"] == "user"]) == 0:
        short_name = prompt[:50].strip()
        memory.update_session_name(session_id, short_name)

    with st.chat_message("assistant"):
        with st.spinner("OSCAR está pensando…"):
            try:
                response_text, new_files = agent.chat(prompt)
                st.session_state.saved_files = new_files
            except Exception as e:
                st.error(f"Error: {e}")
                st.stop()

        st.markdown(response_text)

        for saved in new_files:
            filepath = Path(saved["filepath"])
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                st.download_button(
                    label=f"📥 Descargar: {saved['filename']}",
                    data=content,
                    file_name=saved["filename"],
                    mime="text/plain",
                    key=f"dl_new_{saved['filename']}",
                )

    st.rerun()
