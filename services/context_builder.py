"""Construcción del contexto RAG a partir de contratos, capítulos y extractos."""
from typing import List

import config
from chat_utils.text_utils import clip, enforce_budget


def build_context(question: str, contratos, capitulos, extractos) -> str:
    parts: List[str] = []
    parts.append("=== PREGUNTA DEL USUARIO ===")
    parts.append(question.strip())

    if contratos:
        parts.append("\n=== CONTRATOS RELEVANTES ===")
        for c in contratos:
            snippet = clip(c.get("abstract", "") or "", 1000)
            link = (c.get("link_contrato") or "").strip()
            link_line = f"  Enlace: {link}\n" if link else ""
            parts.append(
                f"- Expediente: {c.get('expediente') or 'N/D'} | Estado: {c.get('estado') or 'N/D'}\n"
                f"  Título: {c.get('titulo') or 'N/D'}\n"
                f"{link_line}"
                f"  CPV principal: {c.get('cpv_principal') or 'N/D'}\n"
                f"  Adjudicataria: {c.get('adjudicataria_nombre') or 'N/D'} "
                f"(NIF: {c.get('adjudicataria_nif') or 'N/D'})\n"
                f"  Presupuesto s/IVA: {c.get('presupuesto_sin_iva') or 'N/D'} | "
                f"Importe adjudicado: {c.get('importe_adjudicado') or 'N/D'}\n"
                f"  Resumen: {snippet}"
            )

    if capitulos:
        parts.append("\n=== CAPÍTULOS RELEVANTES ===")
        for cap in capitulos:
            snippet = clip(cap.get("texto", "") or "", 900)
            parts.append(
                f"- Contrato {cap.get('expediente') or 'N/D'} | Capítulo {cap.get('heading') or 'N/D'} "
                f"({cap.get('fuente_doc') or ''})\n"
                f"  Texto: {snippet}"
            )

    if extractos:
        parts.append("\n=== EXTRACTOS RELEVANTES ===")
        for ex in extractos:
            snippet = clip(ex.get("texto", "") or "", 700)
            parts.append(
                f"- Contrato {ex.get('expediente') or 'N/D'} | Tipo: {ex.get('tipo') or 'N/D'} "
                f"({ex.get('fuente_doc') or ''})\n"
                f"  Texto: {snippet}"
            )

    parts.append(
        "\n=== INSTRUCCIONES PARA EL MODELO ===\n"
        "Responde basándote EXCLUSIVAMENTE en el contexto anterior.\n"
        "Si no hay información suficiente, dilo.\n"
        "Si un contrato incluye una línea 'Enlace:', inclúyela al citar ese contrato, pero sin enseñar todo el link.\n"
        "Si lo crees conveniente, genera tablas para ofrecer resultados.\n"
        "No inventes datos.\n"
        "Respuesta en castellano, clara, breve y concisa."
    )

    ctx = "\n".join(parts)
    return enforce_budget(ctx, config.RAG_CONTEXT_MAX_CHARS)
