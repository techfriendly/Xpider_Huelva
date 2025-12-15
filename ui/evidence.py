"""Construcción de markdown y panel lateral de evidencias (Chainlit) sin JSX.

Este módulo evita CustomElement (JSX) y usa cl.Text para mostrar evidencias
directamente en el sidebar (ElementSidebar).
"""
import json
import textwrap
from typing import Any, Dict, List, Optional

import chainlit as cl


# -----------------------------
# Helpers
# -----------------------------
def _escape_fence(text: str) -> str:
    """Evita romper bloques ``` en markdown si el contenido incluye ```."""
    if not text:
        return ""
    return text.replace("```", "``\u200b`")


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n\n…(truncado)…"


def _json_dumps(obj: Any, max_chars: int = 12000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = str(obj)
    return _truncate(s, max_chars)


def _build_meta_markdown(props_extra: Optional[Dict[str, Any]]) -> str:
    """Convierte props_extra (mode/filters/counts/tokens) en un bloque markdown."""
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
            if isinstance(v, list):
                v_str = ", ".join([str(x) for x in v])
            else:
                v_str = str(v)
            f_parts.append(f"{k}={v_str}")
        if f_parts:
            lines.append(f"**Filtros:** {', '.join(f_parts)}")

    counts = props_extra.get("counts")
    if isinstance(counts, dict) and counts:
        c_parts = []
        for k, v in counts.items():
            if v is None:
                continue
            c_parts.append(f"{k}={v}")
        if c_parts:
            lines.append(f"**Conteos:** {', '.join(c_parts)}")

    tokens = props_extra.get("tokens")
    if isinstance(tokens, dict) and tokens:
        sent = tokens.get("sent_approx")
        budget = tokens.get("budget")
        if sent is not None or budget is not None:
            lines.append(f"**Tokens (aprox):** enviados={sent}, presupuesto={budget}")

    return "\n".join(lines).strip()


# -----------------------------
# Evidencias RAG
# -----------------------------
def build_evidence_markdown(contratos, capitulos, extractos) -> str:
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


# -----------------------------
# Evidencias Cypher / Neo4j
# -----------------------------
def build_cypher_evidence_markdown(
    question: str,
    cypher: str,
    rows: Any,
    params: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    max_rows: int = 25,
    max_json_chars: int = 12000,
) -> str:
    if rows is None:
        rows_list: List[Any] = []
    elif isinstance(rows, list):
        rows_list = rows
    else:
        rows_list = [rows]

    lines: List[str] = []
    lines.append("### Evidencias (Neo4j / Cypher)")

    if question:
        lines.append("")
        lines.append("**Pregunta**")
        lines.append(_escape_fence(question.strip()))

    if error:
        lines.append("")
        lines.append("**Error**")
        lines.append(_escape_fence(str(error)))

    lines.append("")
    lines.append("**Cypher ejecutado**")
    lines.append("```cypher")
    lines.append(_escape_fence((cypher or "").strip()))
    lines.append("```")

    if params:
        lines.append("")
        lines.append("**Parámetros**")
        lines.append("```json")
        lines.append(_escape_fence(_json_dumps(params, max_chars=max_json_chars)))
        lines.append("```")

    n_total = len(rows_list)
    n_show = min(max_rows, n_total)
    preview = rows_list[:max_rows]

    lines.append("")
    lines.append(f"**Resultado** (preview: {n_show} filas de {n_total})")
    lines.append("```json")
    lines.append(_escape_fence(_json_dumps(preview, max_chars=max_json_chars)))
    lines.append("```")

    return "\n".join(lines)


# -----------------------------
# Sidebar (sin JSX)
# -----------------------------
async def set_evidence_sidebar(
    title: str,
    markdown: str,
    props_extra: Optional[Dict[str, Any]] = None,
    context_text: Optional[str] = None,
):
    """Abre/actualiza el sidebar derecho con cl.Text (sin CustomElement).

    - Primer elemento: meta (mode/filters/counts/tokens) si existe
    - Segundo: evidencias (markdown)
    - Tercero (opcional): contexto enviado al LLM (como bloque ```text)
    """
    meta_md = _build_meta_markdown(props_extra)

    elements: List[Any] = []

    if meta_md:
        elements.append(cl.Text(name="evidence_meta", content=meta_md))

    elements.append(cl.Text(name="evidence_markdown", content=markdown or "No hay evidencias para mostrar."))

    if context_text:
        ctx = _escape_fence(_truncate(context_text, 20000))
        ctx_md = "### Contexto enviado al modelo\n\n```text\n" + ctx + "\n```"
        elements.append(cl.Text(name="evidence_context", content=ctx_md))

    try:
        # Nota: según docs, set_elements abre el sidebar; set_title actualiza el título.
        await cl.ElementSidebar.set_elements(elements)
        await cl.ElementSidebar.set_title(title)
    except Exception as exc:
        # Fallback: si el sidebar no está disponible, mostramos en chat (sin romper UX).
        print(f"[WARN] No se pudo abrir el sidebar de evidencias: {exc}")
        try:
            await cl.Message(content=title or "Evidencias", elements=elements).send()
        except Exception as exc_inline:
            print(f"[ERROR] Tampoco pude adjuntar evidencias en el mensaje: {exc_inline}")


async def clear_evidence_sidebar():
    try:
        await cl.ElementSidebar.set_elements([])
    except Exception:
        pass
