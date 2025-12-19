import re
from typing import Any, Dict, List, Optional

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
    empresa_awards_stats,
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


def _empresa_lookup(intent: Dict[str, Any], router_state: Dict[str, Any]) -> Optional[str]:
    lookup = (intent.get("empresa_query") or intent.get("empresa_nif") or "").strip()
    if lookup:
        return lookup
    if intent.get("is_followup") and router_state.get("last_empresa_query"):
        return str(router_state.get("last_empresa_query"))
    return None


def _normalize_contrato_keys(contratos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compatibilidad por si algún sitio devuelve 'resumen'."""
    out: List[Dict[str, Any]] = []
    for c in contratos or []:
        if not isinstance(c, dict):
            continue
        c2 = dict(c)
        if "abstract" not in c2 and "resumen" in c2:
            c2["abstract"] = c2.get("resumen") or ""
        out.append(c2)
    return out


def _empresa_context_header(empresa_lookup: str, empresas: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("=== RESOLUCIÓN DE EMPRESA ===")
    lines.append(f"Consulta empresa (input usuario): {empresa_lookup}")
    if empresas:
        top = empresas[0]
        lines.append(f"Empresa candidata top: {top.get('nombre')} (NIF: {top.get('nif')})")
        lines.append(f"Adjudicaciones (count): {top.get('adjudicaciones_count')} | Total: {top.get('adjudicaciones_total')}")
    else:
        lines.append("No se han encontrado coincidencias directas en EmpresaRAG (se intenta igualmente por contratos).")
    return "\n".join(lines)


async def handle_generate_ppt(question: str, allow_clarifications: bool = True):
    plan = await cl.make_async(plan_ppt_clarifications)(question)
    if (
        allow_clarifications
        and not cl.user_session.get("ppt_clarifications_sent", False)
        and plan["need_clarification"]
        and plan["questions"]
    ):
        cl.user_session.set("ppt_pending", True)
        cl.user_session.set("ppt_request_base", plan["normalized_request"])
        cl.user_session.set("ppt_questions", plan["questions"])
        cl.user_session.set("ppt_clarifications_sent", True)

        qtxt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(plan["questions"])])
        await cl.Message(
            content=(
                "Antes de redactar el PPT necesito aclarar algunas cosas:\n\n"
                f"{qtxt}\n\n"
                "Respóndeme en un solo mensaje (puedes numerar tus respuestas)."
            )
        ).send()
        return

    normalized_question = plan.get("normalized_request", question)

    await cl.Message(content="Generando PPT basado en un pliego de referencia del grafo…").send()

    emb = await cl.make_async(embed_text)(normalized_question)
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
                "importe_adjudicado": ref_contrato.get("importe_adjudicado"),
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

    system_msg, user_msg = build_ppt_generation_prompt_one_by_one(normalized_question, ref_data)

    msg = cl.Message(content="")
    await msg.send()

    stream = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        max_tokens=6000,
        temperature=0.2,
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

    cl.user_session.set("ppt_clarifications_sent", False)


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("history", [])
    cl.user_session.set("ppt_pending", False)
    cl.user_session.set("ppt_request_base", "")
    cl.user_session.set("ppt_questions", [])
    cl.user_session.set("ppt_clarifications_sent", False)
    cl.user_session.set(
        "router_state",
        {
            "last_focus": None,
            "last_empresa_query": None,
            "last_empresa_nif": None,
            "last_contratos": [],
            "last_capitulos": [],
            "last_extractos": [],
            "last_doc_tipo": None,
            "last_extracto_tipos": None,
        },
    )
    await clear_evidence_sidebar()

    await cl.Message(
        content=(
            "Hola. Soy el asistente RAG/Cypher de contratos (Huelva).\n\n"
            "Puedo:\n"
            "- Responder preguntas (RAG) y mostrar evidencias a la derecha.\n"
            "- Consultar adjudicaciones por empresa (por nombre, y CIF si aplica).\n"
            "- Contar/sumar/rankings (Cypher).\n"
            "- Generar un PPT (te preguntaré si falta contexto) y descargarlo en Word.\n"
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

    if cl.user_session.get("ppt_pending", False):
        base_req = cl.user_session.get("ppt_request_base", "")
        final_req = f"{base_req}\n\nAclaraciones del usuario:\n{question}"
        cl.user_session.set("ppt_pending", False)
        cl.user_session.set("ppt_request_base", "")
        cl.user_session.set("ppt_questions", [])
        history: List[Dict[str, str]] = cl.user_session.get("history", [])
        await handle_generate_ppt(final_req, allow_clarifications=False)
        history.append({"role": "user", "content": final_req})
        history.append({"role": "assistant", "content": f"PPT generado (fecha {config.TODAY_STR})."})
        cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])
        return

    history: List[Dict[str, str]] = cl.user_session.get("history", [])
    router_state: Dict[str, Any] = cl.user_session.get(
        "router_state",
        {
            "last_focus": None,
            "last_empresa_query": None,
            "last_empresa_nif": None,
            "last_contratos": [],
            "last_capitulos": [],
            "last_extractos": [],
            "last_doc_tipo": None,
            "last_extracto_tipos": None,
        },
    )

    thinking_msg = await cl.Message(content="Detectando intención...").send()

    try:
        intent = await cl.make_async(detect_intent)(question, history, router_state)

        # Saludo
        if intent.get("is_greeting"):
            await thinking_msg.update()
            await cl.Message(
                content=(
                    "Hola. Dime qué necesitas buscar.\n\n"
                    "Ejemplos:\n"
                    "- \"Qué contratos ha ganado Techfriendly\"\n"
                    "- \"Cuántos contratos ha ganado Vodafone\"\n"
                    "- \"Top 10 adjudicatarias por importe adjudicado\""
                )
            ).send()
            return

        # PPT
        if intent["intent"] == "GENERATE_PPT":
            await thinking_msg.update()
            await handle_generate_ppt(question)
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": f"PPT generado (fecha {config.TODAY_STR})."})
            cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])
            return

        focus = (intent.get("focus") or "CONTRATO").upper()

        # CYPHER (agregaciones)
        if intent["intent"] == "CYPHER_QA":
            # Caso especial: agregación por EMPRESA => determinístico (NO LLM Cypher)
            if focus == "EMPRESA":
                empresa_lookup = _empresa_lookup(intent, router_state)
                if empresa_lookup:
                    thinking_msg.content = f"Calculando agregados de adjudicaciones para empresa: {empresa_lookup} ..."
                    await thinking_msg.update()

                    stats = await cl.make_async(empresa_awards_stats)(empresa_lookup)
                    if not stats:
                        await cl.Message(content=f"No he encontrado la empresa '{empresa_lookup}' en el grafo.").send()
                        return

                    nombre = stats.get("nombre") or empresa_lookup
                    nif = stats.get("nif") or "N/D"
                    n_contratos = stats.get("contratos_ganados", 0)
                    importe_total = stats.get("importe_total", 0)

                    # Evidencias: resolvemos empresa + lista top contratos (opcional)
                    contratos = await cl.make_async(search_contratos_by_empresa)(empresa_lookup, k_empresas=3, k_contratos=12)
                    contratos = _normalize_contrato_keys(contratos)

                    ev_md = "### Evidencias (Empresa / Agregación)\n"
                    ev_md += f"**Input usuario:** {empresa_lookup}\n\n"
                    ev_md += f"**Empresa resuelta:** {nombre} (NIF: {nif})\n\n"
                    ev_md += f"**Contratos ganados (count):** {n_contratos}\n\n"
                    ev_md += f"**Importe total adjudicado (aprox):** {importe_total}\n\n"
                    if contratos:
                        ev_md += "**Top contratos (preview):**\n"
                        for c in contratos[:10]:
                            ev_md += f"- {c.get('expediente')} · {c.get('titulo')} · importe={c.get('importe_adjudicado')}\n"

                    await set_evidence_sidebar(
                        title="Evidencias Neo4j (Empresa)",
                        markdown=ev_md,
                        props_extra={"mode": "EMPRESA"},
                        context_text=None,
                    )

                    # Respuesta principal
                    content = f"{nombre} (NIF: {nif}) ha ganado **{n_contratos}** contratos."
                    # Si el usuario preguntaba "cuántos", con esto basta; si quieres, añadimos importe total como extra útil
                    content += f"\nImporte total adjudicado (según el grafo): **{importe_total}**."
                    if contratos:
                        content += "\n\nContratos (preview):"
                        for c in contratos[:10]:
                            content += f"\n- Expediente: {c.get('expediente')} · {c.get('titulo')}"

                    await cl.Message(content=content).send()

                    # Estado + memoria (guardamos también contratos para permitir follow-ups contextualizados)
                    router_state.update(
                        {
                            "last_focus": "EMPRESA",
                            "last_empresa_query": empresa_lookup,
                            "last_empresa_nif": nif if nif != "N/D" else intent.get("empresa_nif"),
                            "last_contratos": contratos,
                            "last_capitulos": [],
                            "last_extractos": [],
                            "last_doc_tipo": None,
                            "last_extracto_tipos": None,
                        }
                    )
                    cl.user_session.set("router_state", router_state)

                    history.append({"role": "user", "content": question})
                    history.append({"role": "assistant", "content": content})
                    cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])

                    thinking_msg.content = "Respuesta generada (Empresa/Aggregación)."
                    await thinking_msg.update()
                    return

            # Resto de agregaciones => tu cypher_qa actual
            thinking_msg.content = "Generando y ejecutando consulta Cypher (solo lectura)..."
            await thinking_msg.update()

            out = await cl.make_async(cypher_qa)(question)
            if out.get("error"):
                await cl.Message(content=f"No he podido ejecutar Cypher QA.\nDetalle: {out.get('error')}").send()
                return

            answer = out["answer"]
            await cl.Message(content=answer).send()

            history.append({"role": "user", "content": question})
            answer_mem = await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS) if len(answer) > 2000 else answer
            history.append({"role": "assistant", "content": answer_mem})
            cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])

            thinking_msg.content = f"Respuesta generada (Cypher). Tokens aprox: enviados={estimate_tokens(question)}, generados={estimate_tokens(answer)}"
            await thinking_msg.update()
            return

        # RAG
        # Caso EMPRESA: buscamos por nombre en el grafo (no dependemos del embedding para localizar la empresa)
        if focus == "EMPRESA":
            empresa_lookup = _empresa_lookup(intent, router_state)
            thinking_msg.content = f"Buscando adjudicaciones por empresa: {empresa_lookup or '(no resuelta)'} ..."
            await thinking_msg.update()

            empresas = []
            contratos = []
            if empresa_lookup:
                empresas = await cl.make_async(search_empresas)(empresa_lookup, 5, 12)
                contratos = await cl.make_async(search_contratos_by_empresa)(empresa_lookup, 3, max(25, config.K_CONTRATOS))

                router_state["last_focus"] = "EMPRESA"
                router_state["last_empresa_query"] = empresa_lookup
                router_state["last_empresa_nif"] = (empresas[0].get("nif") if empresas else intent.get("empresa_nif"))
                cl.user_session.set("router_state", router_state)

            contratos = _normalize_contrato_keys(contratos)

            # Si no encontramos contratos por empresa, caemos al RAG vector normal
            if not contratos:
                focus = "CONTRATO"
            else:
                # Embedding para enriquecer con extractos/capítulos relacionados, pero filtrados por expedientes adjudicados
                embedding = await cl.make_async(embed_text)(question)
                capitulos = []
                extractos = []
                if embedding:
                    doc_tipo = intent.get("doc_tipo")
                    tipos = intent.get("extracto_tipos")
                    allowed = {c.get("expediente") for c in contratos if c.get("expediente")}
                    cap_tmp = await cl.make_async(search_capitulos)(embedding, max(config.K_CAPITULOS * 6, 30), doc_tipo)
                    ex_tmp = await cl.make_async(search_extractos)(embedding, max(config.K_EXTRACTOS * 6, 50), tipos, doc_tipo)
                    capitulos = [c for c in cap_tmp if c.get("expediente") in allowed][: config.K_CAPITULOS]
                    extractos = [e for e in ex_tmp if e.get("expediente") in allowed][: config.K_EXTRACTOS]

                evidence_md = build_evidence_markdown(contratos, capitulos, extractos)
                context = build_context(question, contratos, capitulos, extractos)
                if empresa_lookup:
                    context = _empresa_context_header(empresa_lookup, empresas) + "\n\n" + context

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

                await set_evidence_sidebar(
                    title="Evidencias RAG usadas (Empresa)",
                    markdown=evidence_md,
                    props_extra={
                        "mode": "RAG_EMPRESA",
                        "filters": {"empresa": empresa_lookup},
                        "tokens": {"sent_approx": rep["total"], "budget": config.MODEL_MAX_CONTEXT_TOKENS},
                        "counts": {"contratos": len(contratos), "capitulos": len(capitulos), "extractos": len(extractos)},
                    },
                    context_text=context,
                )

                messages_llm: List[Dict[str, str]] = [{"role": "system", "content": system_msg}]
                messages_llm.extend(history_trimmed)
                messages_llm.append({"role": "user", "content": context})

                reply = cl.Message(content="")
                await reply.send()

                stream = llm_client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=messages_llm,
                    temperature=0.2,
                    stream=True,
                    max_tokens=1200,
                )

                full_answer: List[str] = []
                for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        full_answer.append(token)
                        await reply.stream_token(token)

                await reply.update()
                answer = "".join(full_answer).strip()

                history.append({"role": "user", "content": question})
                answer_mem = await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS) if len(answer) > 2000 else answer
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

                router_state.update(
                    {
                        "last_focus": "EMPRESA",
                        "last_contratos": contratos,
                        "last_capitulos": capitulos,
                        "last_extractos": extractos,
                        "last_doc_tipo": doc_tipo,
                        "last_extracto_tipos": tipos,
                    }
                )
                cl.user_session.set("router_state", router_state)

                thinking_msg.content = f"Respuesta generada (RAG Empresa). Tokens aprox: enviados={rep['total']}, generados={estimate_tokens(answer)}"
                await thinking_msg.update()
                return

        # RAG normal (CONTRATO)
        thinking_msg.content = "Ejecutando RAG (vector search) con filtros..."
        await thinking_msg.update()

        use_cached_context = bool(intent.get("is_followup") and router_state.get("last_contratos"))
        if use_cached_context:
            thinking_msg.content = "Reutilizando el contexto previo para el seguimiento..."
            await thinking_msg.update()

            contratos = router_state.get("last_contratos", [])
            capitulos = router_state.get("last_capitulos", [])
            extractos = router_state.get("last_extractos", [])
            doc_tipo = router_state.get("last_doc_tipo")
            tipos = router_state.get("last_extracto_tipos")
        else:
            embedding = await cl.make_async(embed_text)(question)
            if not embedding:
                thinking_msg.content = "No he podido generar el embedding."
                await thinking_msg.update()
                return

            doc_tipo = intent.get("doc_tipo")
            tipos = intent.get("extracto_tipos")

            contratos = await cl.make_async(search_contratos)(embedding, config.K_CONTRATOS)
            capitulos = await cl.make_async(search_capitulos)(embedding, config.K_CAPITULOS, doc_tipo)
            extractos = await cl.make_async(search_extractos)(embedding, config.K_EXTRACTOS, tipos, doc_tipo)

        contratos = _normalize_contrato_keys(contratos)

        evidence_md = build_evidence_markdown(contratos, capitulos, extractos)
        context = build_context(question, contratos, capitulos, extractos)

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
            f"Filtros: doc_tipo={doc_tipo}, extracto_tipos={tipos}"
        )
        await thinking_msg.update()

        await set_evidence_sidebar(
            title="Evidencias RAG usadas",
            markdown=evidence_md,
            props_extra={
                "mode": "RAG",
                "filters": {"doc_tipo": doc_tipo, "extracto_tipos": tipos},
                "tokens": {"sent_approx": rep["total"], "budget": config.MODEL_MAX_CONTEXT_TOKENS},
                "counts": {"contratos": len(contratos), "capitulos": len(capitulos), "extractos": len(extractos)},
            },
            context_text=context,
        )

        messages_llm: List[Dict[str, str]] = [{"role": "system", "content": system_msg}]
        messages_llm.extend(history_trimmed)
        messages_llm.append({"role": "user", "content": context})

        reply = cl.Message(content="")
        await reply.send()

        stream = llm_client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages_llm,
            temperature=0.2,
            stream=True,
            max_tokens=1200,
        )

        full_answer: List[str] = []
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                full_answer.append(token)
                await reply.stream_token(token)

        await reply.update()
        answer = "".join(full_answer).strip()

        history.append({"role": "user", "content": question})
        answer_mem = await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS) if len(answer) > 2000 else answer
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

        router_state.update(
            {
                "last_focus": "CONTRATO",
                "last_contratos": contratos,
                "last_capitulos": capitulos,
                "last_extractos": extractos,
                "last_doc_tipo": doc_tipo,
                "last_extracto_tipos": tipos,
            }
        )
        cl.user_session.set("router_state", router_state)

        thinking_msg.content = f"Respuesta generada (RAG). Tokens aprox: enviados={rep['total']}, generados={estimate_tokens(answer)}"
        await thinking_msg.update()

    except Exception as e:
        print(f"[ERROR] {e}")
        thinking_msg.content = "Ha ocurrido un error. Revisa logs."
        await thinking_msg.update()
