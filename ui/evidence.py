"""
GESTOR DE EVIDENCIAS (SIDEBAR): ui/evidence.py
DESCRIPCIÓN:
Controla la barra lateral derecha de la interfaz (Chainlit).
Muestra las "Pruébas" o documentos que el bot ha usado para responder (Contratos, Capítulos, etc.).
No usa React/JSX complejo, solo componentes nativos de Chainlit (cl.Text, cl.ElementSidebar).
"""

import json
import textwrap
from typing import Any, Dict, List, Optional
import chainlit as cl

# --- HELPERS ---

def _escape_fence(text: str) -> str:
    """Evita que un texto rompa el formato Markdown si contiene bloques de código."""
    if not text:
        return ""
    return text.replace("```", "``\u200b`")


def _truncate(text: str, max_chars: int) -> str:
    """Recorta textos largos para que no ocupen toda la pantalla."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n\n…(truncado)…"


def _json_dumps(obj: Any, max_chars: int = 12000) -> str:
    """Convierte objeto a JSON string con límite de tamaño."""
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = str(obj)
    return _truncate(s, max_chars)


def _build_meta_markdown(props_extra: Optional[Dict[str, Any]]) -> str:
    """
    Crea un bloque de texto resumen con metadatos (ej: cuántos contratos se han encontrado, modo de búsqueda...).
    """
    if not props_extra or not isinstance(props_extra, dict):
        return ""

    lines: List[str] = []

    mode = props_extra.get("mode")
    if mode:
        lines.append(f"**Modo:** {mode}")

    filters = props_extra.get("filters")
    if isinstance(filters, dict) and filters:
        f_parts = []
        for k, v in filters.items():
            if v is None or v == "" or v == []:
                continue
            v_str = ", ".join([str(x) for x in v]) if isinstance(v, list) else str(v)
            f_parts.append(f"{k}={v_str}")
        if f_parts:
            lines.append(f"**Filtros:** {', '.join(f_parts)}")

    counts = props_extra.get("counts")
    if isinstance(counts, dict) and counts:
        c_parts = [f"{k}={v}" for k, v in counts.items() if v is not None]
        if c_parts:
            lines.append(f"**Conteos:** {', '.join(c_parts)}")

    tokens = props_extra.get("tokens")
    if isinstance(tokens, dict) and tokens:
        sent = tokens.get("sent_approx")
        budget = tokens.get("budget")
        if sent is not None or budget is not None:
            lines.append(f"**Tokens (aprox):** enviados={sent}, presupuesto={budget}")

    return "\n".join(lines).strip()


# --- CONSTRUCTORES DE MARKDOWN ---

def build_evidence_markdown(contratos, capitulos, extractos) -> str:
    """Genera el texto Markdown principal con la lista de documentos encontrados (RAG)."""
    lines: List[str] = []
    lines.append("### Evidencias utilizadas")

    if contratos:
        lines.append("")
        lines.append("**Contratos relevantes**")
        for c in contratos:
            lines.append(
                f"- Expediente **{c.get('expediente') or 'N/D'}** · "
                f"Título: {c.get('titulo') or 'N/D'} · "
                f"Adjudicataria: {c.get('adjudicataria_nombre') or 'N/D'} "
                f"(importe adjudicado: {c.get('importe_adjudicado') or 'N/D'})"
            )

    if capitulos:
        lines.append("")
        lines.append("**Capítulos relevantes**")
        for cap in capitulos:
            snippet = textwrap.shorten(cap.get("texto", "") or "", width=220, placeholder=" […]")
            lines.append(
                f"- Contrato **{cap.get('expediente') or 'N/D'}**, capítulo _{cap.get('heading') or 'N/D'}_ "
                f"({cap.get('fuente_doc') or ''}): {snippet}"
            )

    if extractos:
        lines.append("")
        lines.append("**Extractos relevantes**")
        for ex in extractos:
            snippet = textwrap.shorten(ex.get("texto", "") or "", width=220, placeholder=" […]")
            lines.append(
                f"- Contrato **{ex.get('expediente') or 'N/D'}**, tipo _{ex.get('tipo') or 'N/D'}_ "
                f"({ex.get('fuente_doc') or ''}): {snippet}"
            )

    return "\n".join(lines)


def build_cypher_evidence_markdown(
    question: str,
    cypher: str,
    rows: Any,
    params: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    max_rows: int = 25,
    max_json_chars: int = 12000,
) -> str:
    """Genera el texto Markdown para cuando hacemos una consulta a Base de Datos (Cypher)."""
    if rows is None:
        rows_list: List[Any] = []
    elif isinstance(rows, list):
        rows_list = rows
    else:
        rows_list = [rows]

    lines: List[str] = []
    lines.append("### Evidencias (Neo4j / Cypher)")

    if question:
        lines.append(f"\n**Pregunta**\n{_escape_fence(question.strip())}")

    if error:
        lines.append(f"\n**Error**\n{_escape_fence(str(error))}")

    lines.append(f"\n**Cypher ejecutado**\n```cypher\n{_escape_fence((cypher or '').strip())}\n```")

    if params:
        lines.append(f"\n**Parámetros**\n```json\n{_escape_fence(_json_dumps(params, max_chars=max_json_chars))}\n```")

    n_total = len(rows_list)
    n_show = min(max_rows, n_total)
    preview = rows_list[:max_rows]

    lines.append(f"\n**Resultado** (preview: {n_show} filas de {n_total})\n```json\n{_escape_fence(_json_dumps(preview, max_chars=max_json_chars))}\n```")

    return "\n".join(lines)


# --- FUNCIÓN PRINCIPAL DE CONTROL DEL SIDEBAR ---

async def set_evidence_sidebar(
    title: str,
    markdown: str,
    props_extra: Optional[Dict[str, Any]] = None,
    context_text: Optional[str] = None,
):
    """
    Despliega la barra lateral derecha con la información proporcionada.
    
    Args:
        title: Título de la barra (ej: "Evidencias RAG").
        markdown: Contenido principal formateado.
        props_extra: Datos técnicos extra (tokens, filtros).
        context_text: El texto completo crudo que se envió al LLM (para depurar).
    """
    meta_md = _build_meta_markdown(props_extra)

    elements: List[Any] = []

    # 1. Metadatos (arriba del todo)
    if meta_md:
        elements.append(cl.Text(name="evidence_meta", content=meta_md))

    # 2. Contenido Principal
    elements.append(cl.Text(name="evidence_markdown", content=markdown or "No hay evidencias para mostrar."))

    # 3. Contexto RAW (Opcional, útil para depuración)
    if context_text:
        ctx = _escape_fence(_truncate(context_text, 20000))
        ctx_md = "### Contexto enviado al modelo\n\n```text\n" + ctx + "\n```"
        elements.append(cl.Text(name="evidence_context", content=ctx_md))

    # Intentamos abrir el sidebar
    try:
        await cl.ElementSidebar.set_elements(elements)
        await cl.ElementSidebar.set_title(title)
        
    # Fallback: Si falla (versiones nuevas/viejas de Chainlit a veces cambian API), lo enviamos al chat.
    except Exception as exc:
        print(f"[WARN] No se pudo abrir el sidebar de evidencias: {exc}")
        try:
            await cl.Message(content=title or "Evidencias", elements=elements).send()
        except Exception as exc_inline:
             print(f"[ERROR] Tampoco pude adjuntar evidencias en el mensaje: {exc_inline}")


async def clear_evidence_sidebar():
    """Cierra/limpia la barra lateral."""
    try:
        await cl.ElementSidebar.set_elements([])
    except Exception:
        pass
