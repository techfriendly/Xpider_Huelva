import json
import re
from typing import Any, Dict, List, Optional, Tuple

import chainlit as cl

import config
from clients import llm_client
from services.context_builder import build_context
from services.cypher import cypher_qa
from services.embeddings import embed_text
from services.followups import (
    generate_follow_up_questions,
    should_generate_followups,
    summarize_for_memory,
)
from services.intent_router import detect_intent
from services.neo4j_queries import (
    search_capitulos,
    search_contratos,
    search_contratos_by_empresa,
    search_empresas,
    search_extractos,
)
from services.ppt_generation import (
    HAS_DOCX,
    build_ppt_generation_prompt_one_by_one,
    find_reference_ppt_contract,
    get_ppt_reference_data,
    plan_ppt_clarifications,
    ppt_to_docx_bytes,
    slug_filename,
)
from ui.evidence import build_evidence_markdown, clear_evidence_sidebar, set_evidence_sidebar
from chat_utils.text_utils import context_token_report, estimate_tokens, trim_history_to_fit


# -----------------------------
# Helpers
# -----------------------------
def _json_preview(obj: Any, max_chars: int = 12000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = str(obj)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n\n…(truncado)…"


def _escape_fence(text: str) -> str:
    if not text:
        return ""
    return text.replace("```", "``\u200b`")


def _normalize_contratos_for_context(contratos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normaliza claves para compatibilidad:
    - build_context usa c["abstract"] (pero algunas versiones devuelven "resumen").
    """
    out: List[Dict[str, Any]] = []
    for c in contratos or []:
        if not isinstance(c, dict):
            continue
        c2 = dict(c)
        if "abstract" not in c2 and "resumen" in c2:
            c2["abstract"] = c2.get("resumen")
        out.append(c2)
    return out


def _empresa_lookup_from_intent(intent: Dict[str, Any], question: str) -> Optional[str]:
    q = (intent.get("empresa_nif") or intent.get("empresa_query") or "").strip()
    if q:
        return q
    # Fallback mínimo (no depende del router): intenta detectar CIF
    m = re.search(r"\b([A-Z]\d{8})\b", (question or "").upper())
    if m:
        return m.group(1)
    return None


def _build_empresa_block_for_context(
    empresa_lookup: str,
    empresas: List[Dict[str, Any]],
    contratos: List[Dict[str, Any]],
) -> str:
    """
    Bloque adicional para meter en el contexto cuando el focus es EMPRESA.
    """
    lines: List[str] = []
    lines.append("=== EMPRESA / ADJUDICACIONES ===")
    lines.append(f"Búsqueda: {empresa_lookup}")

    if empresas:
        # Mostramos 1-3 candidatos
        lines.append("")
        lines.append("Empresas candidatas (top):")
        for e in empresas[:3]:
            nombre = e.get("nombre") or "N/D"
            nif = e.get("nif") or "N/D"
            cnt = e.get("adjudicaciones_count")
            total = e.get("adjudicaciones_total")
            lines.append(f"- {nombre} (NIF: {nif}) | adjudicaciones: {cnt} | total: {total}")
    else:
        lines.append("")
        lines.append("No se ha podido resolver la empresa por nombre/NIF (se intenta con adjudicaciones encontradas).")

    # Resumen rápido derivado de la lista de contratos (por si no hay métricas)
    if contratos:
        lines.append("")
        lines.append(f"Adjudicaciones recuperadas: {len(contratos)} (lista de contratos abajo).")

    return "\n".join(lines)


def _build_empresa_evidence_markdown(
    empresa_lookup: str,
    empresas: List[Dict[str, Any]],
) -> str:
    lines: List[str] = []
    lines.append("### Evidencias (Empresa)")
    lines.append(f"**Búsqueda:** {empresa_lookup}")

    if not empresas:
        lines.append("")
        lines.append("No hay coincidencias directas en (EmpresaRAG) para esta búsqueda.")
        return "\n".join(lines)

    lines.append("")
    lines.append("**Coincidencias (top):**")
    for e in empresas[:5]:
        nombre = e.get("nombre") or "N/D"
        nif = e.get("nif") or "N/D"
        cnt = e.get("adjudicaciones_count")
        total = e.get("adjudicaciones_total")
        lines.append(f"- {nombre} (NIF: {nif}) | adjudicaciones: {cnt} | total: {total}")

        adjud = e.get("adjudicaciones") or []
        if adjud:
            lines.append("  - Top adjudicaciones:")
            for a in adjud[:5]:
                lines.append(
                    f"    - {a.get('expediente') or a.get('contract_id') or 'N/D'} · "
                    f"{(a.get('titulo') or 'N/D')}"
                )

    return "\n".join(lines)


def _build_cypher_evidence_markdown(question: str, out: Dict[str, Any]) -> str:
    cypher = out.get("cypher") or ""
    plan = out.get("plan") or {}
    params = plan.get("params") if isinstance(plan, dict) else None
    rows = out.get("rows") or []
    err = out.get("error")

    lines: List[str] = []
    lines.append("### Evidencias (Neo4j / Cypher)")
    lines.append("")
    lines.append("**Pregunta**")
    lines.append(_escape_fence(question.strip()))

    if err:
        lines.append("")
        lines.append("**Error**")
        lines.append(_escape_fence(str(err)))

    lines.append("")
    lines.append("**Cypher ejecutado**")
    lines.append("```cypher")
    lines.append(_escape_fence(cypher.strip()))
    lines.append("```")

    if isinstance(params, dict) and params:
        lines.append("")
        lines.append("**Parámetros**")
        lines.append("```json")
        lines.append(_escape_fence(_json_preview(params)))
        lines.append("```")

    lines.append("")
    lines.append("**Resultado (preview)**")
    lines.append("```json")
    lines.append(_escape_fence(_json_preview(rows[:25])))
    lines.append("```")

    return "\n".join(lines)


# -----------------------------
# PPT flow
# -----------------------------
async def handle_generate_ppt(question: str):
    plan = await cl.make_async(plan_ppt_clarifications)(question)
    if plan["need_clarification"] and plan["questions"]:
        cl.user_session.set("ppt_pending", True)
        cl.user_session.set("ppt_request_base", plan["normalized_request"])
        cl.user_session.set("ppt_questions", plan["questions"])

        qtxt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(plan["questions"])])
        await cl.Message(
            content=(
                "Antes de redactar el PPT necesito aclarar algunas cosas:\n\n"
                f"{qtxt}\n\n"
                "Respóndeme en un solo mensaje (puedes numerar tus respuestas)."
            )
        ).send()
        return

    await cl.Message(content="Generando PPT basado en un pliego de referencia del grafo…").send()

    emb = await cl.make_async(embed_text)(question)
    if not emb:
        await cl.Message("No he podido calcular el embedding de la petición.").send()
        return

    ref_contrato = await cl.make_async(find_reference_ppt_contract)(emb, top_k=10)
    if not ref_contrato:
        await cl.Message("No he encontrado un PPT de referencia adecuado.").send()
        return

    contract_id = ref_contrato["contract_id"]
    ref_data = await cl.make_async(get_ppt_reference_data)(contract_id)
    if ref_data is None:
        await cl.Message(f"El contrato {contract_id} no tiene PPT con capítulos en el grafo.").send()
        return

    extra_caps = await cl.make_async(search_capitulos)(emb, k=min(12, config.K_CAPITULOS), doc_tipo="PPT")
    extra_extractos = await cl.make_async(search_extractos)(emb, k=min(20, config.K_EXTRACTOS), tipos=None, doc_tipo="PPT")

    evidence_md = build_evidence_markdown(
        contratos=[
            {
                "expediente": ref_data.get("expediente"),
                "titulo": ref_data.get("contrato_titulo"),
                "adjudicataria_nombre": ref_contrato.get("adjudicataria_nombre"),
                "adjudicataria_nif": ref_contrato.get("adjudicataria_nif"),
                "importe_adjudicado": ref_contrato.get("importe_adjudicado"),
                "presupuesto_sin_iva": ref_contrato.get("presupuesto_sin_iva"),
                "cpv_principal": ref_data.get("cpv_principal"),
                "estado": ref_data.get("estado"),
                "abstract": ref_data.get("abstract") or "",
            }
        ],
        capitulos=[
            {
                "heading": c.get("heading"),
                "expediente": ref_data.get("expediente"),
                "fuente_doc": "PPT",
                "texto": c.get("texto", ""),
            }
            for c in ref_data.get("capitulos", [])[:12]
        ],
        extractos=[
            {
                "tipo": ex.get("tipo"),
                "expediente": ex.get("expediente"),
                "fuente_doc": ex.get("fuente_doc"),
                "texto": ex.get("texto", ""),
            }
            for ex in extra_extractos[:12]
        ],
    )

    await clear_evidence_sidebar()
    await set_evidence_sidebar(
        title="Evidencias RAG usadas (PPT)",
        markdown=evidence_md,
        props_extra={
            "mode": "PPT",
            "filters": {"doc_tipo": "PPT"},
            "counts": {
                "contratos": 1,
                "capitulos": len(ref_data.get("capitulos", [])[:12]),
                "extractos": len(extra_extractos[:12]),
            },
        },
    )

    system_msg, user_msg = build_ppt_generation_prompt_one_by_one(question, ref_data)

    msg = cl.Message(content="")
    await msg.send()

    stream = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        max_tokens=6000,
        temperature=0.3,
        stream=True,
    )

    pliego_chunks: List[str] = []
    for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            pliego_chunks.append(token)
            await msg.stream_token(token)

    await msg.update()
    pliego_text = "".join(pliego_chunks).strip()

    ppt_title = "Pliego de Prescripciones Técnicas"
    m = re.search(r"^#\s*(.+)$", pliego_text, flags=re.MULTILINE)
    if m:
        ppt_title = m.group(1).strip()

    if HAS_DOCX:
        docx_bytes = ppt_to_docx_bytes(pliego_text, title=ppt_title)
        file = cl.File(
            name=f"{slug_filename(ppt_title)}.docx",
            content=docx_bytes,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        await cl.Message(content=f"Documento Word generado: **{ppt_title}**", elements=[file]).send()
    else:
        await cl.Message(content="(Aviso) No puedo generar Word porque python-docx no está disponible.").send()

    ppt_summary = await cl.make_async(summarize_for_memory)(pliego_text, config.MEMORY_SUMMARY_TOKENS)
    await cl.Message(content=f"Resumen del PPT (memoria corta):\n\n{ppt_summary}").send()


# -----------------------------
# Chainlit hooks
# -----------------------------
@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("history", [])
    cl.user_session.set("ppt_pending", False)
    cl.user_session.set("ppt_request_base", "")
    cl.user_session.set("ppt_questions", [])
    await clear_evidence_sidebar()

    await cl.Message(
        content=(
            "Hola. Soy el asistente RAG/Cypher de contratos.\n\n"
            "Puedo:\n"
            "- Responder preguntas (RAG) y mostrar evidencias a la derecha.\n"
            "- Contar/sumar/rankings (Cypher).\n"
            "- Generar un PPT (con referencia del grafo) y descargarlo en Word.\n"
        )
    ).send()


@cl.action_callback("follow_up_question")
async def on_follow_up_question(action: cl.Action):
    payload = action.payload or {}
    q = payload.get("question")
    if not q:
        return
    await cl.Message(content=q).send()
    await on_message(cl.Message(content=q))


@cl.on_message
async def on_message(message: cl.Message):
    question = (message.content or "").strip()
    if not question:
        await cl.Message(content="No he recibido ninguna pregunta.").send()
        return

    # Resolución de aclaraciones de PPT
    if cl.user_session.get("ppt_pending", False):
        base_req = cl.user_session.get("ppt_request_base", "")
        final_req = f"{base_req}\n\nAclaraciones del usuario:\n{question}"
        cl.user_session.set("ppt_pending", False)
        cl.user_session.set("ppt_request_base", "")
        cl.user_session.set("ppt_questions", [])
        await handle_generate_ppt(final_req)
        return

    history: List[Dict[str, str]] = cl.user_session.get("history", [])
    thinking_msg = await cl.Message(content="Detectando intención y consultando el grafo...").send()

    try:
        intent = await cl.make_async(detect_intent)(question)

        # 1) PPT
        if intent.get("intent") == "GENERATE_PPT":
            await thinking_msg.update()
            await handle_generate_ppt(question)

            history.append({"role": "user", "content": question})
            history.append(
                {"role": "assistant", "content": f"PPT generado (fecha {config.TODAY_STR}). Word entregado + resumen corto."}
            )
            cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])
            return

        # 2) CYPHER
        if intent.get("intent") == "CYPHER_QA":
            thinking_msg.content = "Generando y ejecutando consulta Cypher (solo lectura)..."
            await thinking_msg.update()

            out = await cl.make_async(cypher_qa)(question)

            # Evidencias Cypher siempre (incluido error) para depurar
            evidence_md = _build_cypher_evidence_markdown(question, out)
            await set_evidence_sidebar(
                title="Evidencias Neo4j (Cypher)",
                markdown=evidence_md,
                props_extra={"mode": "CYPHER"},
            )

            if out.get("error"):
                await cl.Message(content=f"No he podido ejecutar Cypher QA.\nDetalle: {out.get('error')}").send()
                return

            answer = out.get("answer") or "No hay respuesta."
            await cl.Message(content=answer).send()

            history.append({"role": "user", "content": question})
            answer_mem = (
                await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS)
                if len(answer) > 2000
                else answer
            )
            history.append({"role": "assistant", "content": answer_mem})
            cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])

            thinking_msg.content = (
                f"Respuesta generada (Cypher). Tokens aprox: enviados={estimate_tokens(question)}, generados={estimate_tokens(answer)}"
            )
            await thinking_msg.update()
            return

        # 3) RAG
        focus = (intent.get("focus") or "CONTRATO").upper()
        doc_tipo = intent.get("doc_tipo")
        tipos = intent.get("extracto_tipos")

        thinking_msg.content = f"Ejecutando RAG (focus={focus})..."
        await thinking_msg.update()

        embedding = await cl.make_async(embed_text)(question)

        contratos: List[Dict[str, Any]] = []
        empresas: List[Dict[str, Any]] = []

        # 3.A) Si es EMPRESA: buscamos adjudicaciones por nombre/NIF
        empresa_lookup = None
        if focus == "EMPRESA":
            empresa_lookup = _empresa_lookup_from_intent(intent, question)
            if empresa_lookup:
                empresas = await cl.make_async(search_empresas)(empresa_lookup, k_empresas=5, max_adjudicaciones=12)
                contratos = await cl.make_async(search_contratos_by_empresa)(
                    empresa_lookup, k_empresas=3, k_contratos=max(25, config.K_CONTRATOS)
                )
            else:
                # Sin lookup claro, seguimos como contrato (fallback)
                focus = "CONTRATO"

        # 3.B) Fallback contrato por embedding
        if not contratos:
            if not embedding:
                thinking_msg.content = "No he podido generar el embedding (y no hay adjudicaciones por empresa)."
                await thinking_msg.update()
                return
            contratos = await cl.make_async(search_contratos)(embedding, config.K_CONTRATOS)

        contratos = _normalize_contratos_for_context(contratos)

        # 3.C) Capítulos/extractos por embedding (y filtrado si focus=EMPRESA)
        capitulos: List[Dict[str, Any]] = []
        extractos: List[Dict[str, Any]] = []

        if embedding:
            # Si focus=EMPRESA, traemos más y luego filtramos por expedientes adjudicados
            k_caps = config.K_CAPITULOS if focus != "EMPRESA" else max(config.K_CAPITULOS * 6, 30)
            k_ext = config.K_EXTRACTOS if focus != "EMPRESA" else max(config.K_EXTRACTOS * 6, 50)

            capitulos = await cl.make_async(search_capitulos)(embedding, k_caps, doc_tipo)
            extractos = await cl.make_async(search_extractos)(embedding, k_ext, tipos, doc_tipo)

            if focus == "EMPRESA" and contratos:
                allowed = {c.get("expediente") for c in contratos if c.get("expediente")}
                capitulos = [c for c in capitulos if c.get("expediente") in allowed][: config.K_CAPITULOS]
                extractos = [e for e in extractos if e.get("expediente") in allowed][: config.K_EXTRACTOS]
            else:
                capitulos = capitulos[: config.K_CAPITULOS]
                extractos = extractos[: config.K_EXTRACTOS]

        # 3.D) Evidencias + contexto
        evidence_md = build_evidence_markdown(contratos, capitulos, extractos)

        if focus == "EMPRESA" and empresa_lookup:
            empresa_evd = _build_empresa_evidence_markdown(empresa_lookup, empresas)
            evidence_md = empresa_evd + "\n\n" + evidence_md

        context_core = build_context(question, contratos, capitulos, extractos)

        if focus == "EMPRESA" and empresa_lookup:
            empresa_block = _build_empresa_block_for_context(empresa_lookup, empresas, contratos)
            context = empresa_block + "\n\n" + context_core
        else:
            context = context_core

        system_msg = (
            "Eres un asistente experto en contratación pública. "
            "Respondes SOLO con la información del contexto. No inventas datos."
        )

        history_short = history[-config.MAX_HISTORY_TURNS:]
        history_trimmed = trim_history_to_fit(
            history=history_short,
            system_msg=system_msg,
            user_msg=context,
            max_context_tokens=config.MODEL_MAX_CONTEXT_TOKENS,
            reserve_for_answer=config.RESERVE_FOR_ANSWER_TOKENS,
        )

        rep = context_token_report(system_msg, history_trimmed, context)

        thinking_msg.content = (
            f"Redactando respuesta… Tokens aprox enviados={rep['total']} "
            f"(sys={rep['system']}, hist={rep['history']}, ctx={rep['user']}). "
            f"Filtros: focus={focus}, doc_tipo={doc_tipo}, extracto_tipos={tipos}"
        )
        await thinking_msg.update()

        props_extra: Dict[str, Any] = {
            "mode": "RAG",
            "filters": {"focus": focus, "doc_tipo": doc_tipo, "extracto_tipos": tipos},
            "tokens": {"sent_approx": rep["total"], "budget": config.MODEL_MAX_CONTEXT_TOKENS},
            "counts": {"contratos": len(contratos), "capitulos": len(capitulos), "extractos": len(extractos)},
        }
        if focus == "EMPRESA" and empresa_lookup:
            props_extra["filters"]["empresa"] = empresa_lookup

        await set_evidence_sidebar(
            title="Evidencias RAG usadas",
            markdown=evidence_md,
            props_extra=props_extra,
            context_text=context,
        )

        # 3.E) LLM respuesta
        messages_llm: List[Dict[str, str]] = [{"role": "system", "content": system_msg}]
        messages_llm.extend(history_trimmed)
        messages_llm.append({"role": "user", "content": context})

        reply = cl.Message(content="")
        await reply.send()

        stream = llm_client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages_llm,
            temperature=0.3,
            stream=True,
            max_tokens=900,
        )

        full_answer: List[str] = []
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                full_answer.append(token)
                await reply.stream_token(token)

        await reply.update()
        answer = "".join(full_answer).strip()

        # 3.F) Memoria + followups
        history.append({"role": "user", "content": question})
        answer_mem = (
            await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS)
            if len(answer) > 2000
            else answer
        )
        history.append({"role": "assistant", "content": answer_mem})
        cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])

        suggestions: List[str] = []
        if should_generate_followups(answer, contratos, capitulos, extractos):
            suggestions = await cl.make_async(generate_follow_up_questions)(question, answer, 3)

        actions: List[cl.Action] = []
        for s in suggestions:
            label = s if len(s) <= config.SUGGESTION_LABEL_MAX_CHARS else s[: config.SUGGESTION_LABEL_MAX_CHARS - 1] + "…"
            actions.append(
                cl.Action(
                    name="follow_up_question",
                    label=label,
                    tooltip=s,
                    payload={"question": s},
                    icon="sparkles",
                )
            )

        reply.actions = actions
        await reply.update()

        thinking_msg.content = (
            f"Respuesta generada (RAG). Tokens aprox: enviados={rep['total']}, generados={estimate_tokens(answer)}"
        )
        await thinking_msg.update()

    except Exception as e:
        print(f"[ERROR] {e}")
        thinking_msg.content = "Ha ocurrido un error. Revisa logs."
        await thinking_msg.update()
