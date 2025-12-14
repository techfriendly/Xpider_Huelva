"""Construcción de markdown y panel lateral de evidencias Chainlit."""
import textwrap
from typing import Any, Dict, List, Optional

import chainlit as cl


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


async def set_evidence_sidebar(title: str, markdown: str, props_extra: Optional[Dict[str, Any]] = None):
    """
    Abre/actualiza el sidebar derecho con un CustomElement EvidencePanel.
    Chainlit permite controlar el sidebar desde Python con ElementSidebar.
    El CustomElement se implementa en public/elements/EvidencePanel.jsx.
    """
    if props_extra is None:
        props_extra = {}

    props = {
        "title": title,
        "markdown": markdown,
        **props_extra,
    }

    el = cl.CustomElement(name="EvidencePanel", props=props)

    try:
        await cl.ElementSidebar.set_title(title)
        await cl.ElementSidebar.set_elements([el])
    except Exception as exc:
        # Fallback: si ElementSidebar no está disponible (versiones antiguas de Chainlit),
        # adjuntamos el panel como un elemento inline para que el usuario siga viendo
        # las evidencias en el chat.
        print(f"[WARN] No se pudo abrir el sidebar de evidencias: {exc}")
        try:
            await cl.Message(
                content="(Aviso) Muestro las evidencias en el chat porque no puedo abrir el panel lateral.",
                elements=[el],
            ).send()
        except Exception as exc_inline:
            print(f"[ERROR] Tampoco pude adjuntar evidencias en el mensaje: {exc_inline}")


async def clear_evidence_sidebar():
    try:
        await cl.ElementSidebar.set_elements([])
    except Exception:
        pass
