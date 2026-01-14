"""
ORQUESTADOR PRINCIPAL: orchestrator.py
DESCRIPCIÓN:
Este archivo es el "Director de Orquesta".
Recibe el mensaje del usuario desde app.py y se encarga de:
1. Preparar el contexto (historial, estado).
2. Ejecutar el Grafo de LangGraph (la lógica de decisión).
3. Mostrar respuestas, errores o generadores en la interfaz visual (Chainlit).
4. Sincronizar manualmente el historial en la base de datos (Persistencia).
"""

import chainlit as cl
from typing import Dict, Any, List, Optional
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
import re
from services.graph import chatbot_graph

# Función auxiliar para resolver nombre/NIF de empresa
def _empresa_lookup(intent: Dict[str, Any], router_state: Dict[str, Any]) -> str:
    """Intenta obtener el mejor string de búsqueda para una empresa."""
    # 1. Prioridad: NIF explícito
    if intent.get("empresa_nif"):
        return intent["empresa_nif"]
    
    # 2. Prioridad: Nombre explícito en la query
    if intent.get("empresa_query"):
        return intent["empresa_query"]
        
    # 3. Contexto previo (estado del router)
    if router_state.get("last_empresa_nif"):
        return router_state["last_empresa_nif"]
    if router_state.get("last_empresa_query"):
        return router_state["last_empresa_query"]
        
    return ""

# Función auxiliar para generar cabecera de contexto de empresa
def _empresa_context_header(empresa_query: str, nif_found: str) -> str:
    """Genera una cabecera de texto para el contexto del LLM."""
    if nif_found:
        return f"Focus: EMPRESA (Query: '{empresa_query}', NIF: {nif_found})"
    return f"Focus: EMPRESA (Query: '{empresa_query}')"

# Función auxiliar para normalizar claves de contratos (por si vienen con nombres distintos)
def _normalize_contrato_keys(contratos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Asegura que todos los contratos tengan campo 'abstract'."""
    out: List[Dict[str, Any]] = []
    for c in contratos or []:
        if not isinstance(c, dict):
            continue
        c2 = dict(c)
        # Algunos resultados antiguos usan 'resumen' en lugar de 'abstract'
        if "abstract" not in c2 and "resumen" in c2:
            c2["abstract"] = c2.get("resumen") or ""
        out.append(c2)
    return out

# --- FUNCIÓN PRINCIPAL DEL PROCESO ---
async def orchestrate_message(question: str):
    """
    Gestiona el flujo completo de un mensaje de usuario.
    """
    # 1. RECUPERAR ESTADO DE LA SESIÓN
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

    # Añadimos estado del PPT al router para que el grafo sepa si estamos generando uno
    router_state["ppt_pending"] = cl.user_session.get("ppt_pending", False)
    router_state["ppt_request_base"] = cl.user_session.get("ppt_request_base", "")

    # Mensaje temporal de "Pensando..."
    thinking_msg = await cl.Message(content="Detectando intención...").send()

    # Estado Inicial para el Grafo
    initial_state = {
        "question": question,
        "history": history,
        "router_state": router_state,
        "thinking_message_id": thinking_msg.id,
        "intent": None,
        "answer": None,
        "error": None,
        "sidebar_title": None,
        "sidebar_md": None,
        "sidebar_props": None,
        "follow_ups": None,
        "element_to_send": None,
        "answer_prompt": None,
        "ppt_generation_input": None
    }

    try:
        # 2. EJECUTAR EL GRAFO (LÓGICA INTELIGENTE)
        # Aquí es donde LangGraph toma el control y decide qué nodos ejecutar.
        final_state = await chatbot_graph.ainvoke(initial_state)
        
        # Si el grafo reporta error, lo mostramos y paramos.
        if final_state.get("error"):
            thinking_msg.content = f"Error: {final_state['error']}"
            await thinking_msg.update()
            return

        # 3. ACTUALIZAR INTERFAZ (SIDEBAR)
        # Si el grafo generó evidencias (fuentes), las mostramos a la izquierda.
        if final_state.get("sidebar_md"):
            await set_evidence_sidebar(
                title=final_state["sidebar_title"] or "Evidencias",
                markdown=final_state["sidebar_md"],
                props_extra=final_state["sidebar_props"],
                context_text=final_state.get("answer_prompt", {}).get("user") if final_state.get("answer_prompt") else None
            )

        answer = ""
        # Actualizamos historial local (memoria a corto plazo)
        current_history = final_state.get("history", [])
        current_history.append({"role": "user", "content": question})

        # 4. GENERAR RESPUESTA AL USUARIO
        
        # CASO A: RESPUESTA GENERADA (RAG)
        if final_state.get("answer_prompt"):
            thinking_msg.content = "Redactando respuesta..."
            await thinking_msg.update()
            
            prompt = final_state["answer_prompt"]
            messages_llm = [{"role": "system", "content": prompt["system"]}]
            messages_llm.extend(prompt["history"])
            messages_llm.append({"role": "user", "content": prompt["user"]})

            reply = cl.Message(content="")
            await reply.send()

            # Streaming: enviamos la respuesta palabra por palabra
            stream = llm_client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages_llm,
                temperature=0.2,
                stream=True,
                max_tokens=1200,
            )

            full_answer: List[str] = []
            for chunk in stream:
                token = getattr(chunk.choices[0].delta, 'content', '') or ""
                if token:
                    full_answer.append(token)
                    await reply.stream_token(token)

            await reply.update()
            answer = "".join(full_answer).strip()
            
        # CASO B: GENERACIÓN DE PPT (Word)
        elif final_state.get("ppt_generation_input"):
            input_data = final_state["ppt_generation_input"]
            thinking_msg.content = "Generando documento..."
            await thinking_msg.update()
            
            msg = cl.Message(content="")
            await msg.send()

            stream = llm_client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": input_data["system"]},
                    {"role": "user", "content": input_data["user"]}
                ],
                max_tokens=8000,
                temperature=0.2,
                stream=True,
            )

            pliego_chunks: List[str] = []
            for chunk in stream:
                token = getattr(chunk.choices[0].delta, 'content', '') or ""
                if token:
                    pliego_chunks.append(token)
                    await msg.stream_token(token)

            await msg.update()
            pliego_text = "".join(pliego_chunks).strip()
            answer = pliego_text # Guardamos el texto generado en el historial
            
            # Exportar a archivo DOCX
            ppt_title = "Pliego de Prescripciones Técnicas"
            # Intentamos buscar un título en el Markdown (línea que empiece por #)
            m = re.search(r"^#\s*(.+)$", pliego_text, flags=re.MULTILINE)
            if m: ppt_title = m.group(1).strip()

            if HAS_DOCX:
                docx_bytes = ppt_to_docx_bytes(pliego_text, title=ppt_title)
                file = cl.File(
                    name=f"{slug_filename(ppt_title)}.docx",
                    content=docx_bytes,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                await cl.Message(content=f"Documento Word generado: **{ppt_title}**", elements=[file]).send()

        # CASO C: RESPUESTA ESTÁTICA O PREDEFINIDA (Saludo, Cypher simple)
        elif final_state.get("answer"):
            answer = final_state["answer"]
            # Si se necesita clarificar el PPT (el usuario no dio suficientes datos)
            if final_state["intent"] and final_state["intent"].get("ppt_clarifications_needed"):
                plan = final_state["intent"]["ppt_plan"]
                # Guardamos estado "pendiente de PPT"
                cl.user_session.set("ppt_pending", True)
                cl.user_session.set("ppt_request_base", plan["normalized_request"])
                cl.user_session.set("ppt_questions", plan["questions"])
                cl.user_session.set("ppt_clarifications_sent", True)

                qtxt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(plan["questions"])])
                msg_text = f"Antes de redactar el PPT necesito aclarar algunas cosas:\n\n{qtxt}\n\nRespóndeme en un solo mensaje."
                await cl.Message(content=msg_text).send()
                answer = msg_text
            else:
                await cl.Message(content=answer).send()

        # 5. ACTUALIZAR MEMORIA Y SUGERENCIAS
        
        # Guardar respuesta del asistente en memoria
        if answer:
            answer_to_store = answer
            # Si es muy larga, la resumimos para no llenar la memoria del contexto
            if len(answer) > 3000:
                 answer_to_store = await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS)

            current_history.append({"role": "assistant", "content": answer_to_store})
            cl.user_session.set("history", current_history[-config.MAX_HISTORY_TURNS:])

        # Generar sugerencias (Follow-ups) si procede
        intent_type = final_state["intent"].get("intent") if final_state.get("intent") else None
        if intent_type in ["RAG_QA", "CYPHER_QA"] and answer:
            contratos = final_state.get("contratos") or []
            capitulos = final_state.get("capitulos") or []
            extractos = final_state.get("extractos") or []
            
            if should_generate_followups(answer, contratos, capitulos, extractos) or intent_type == "CYPHER_QA":
                suggestions = await cl.make_async(generate_follow_up_questions)(question, answer, 3)
                if suggestions:
                    actions = []
                    for s in suggestions:
                        label = s if len(s) <= config.SUGGESTION_LABEL_MAX_CHARS else s[: config.SUGGESTION_LABEL_MAX_CHARS - 1] + "…"
                        actions.append(cl.Action(name="follow_up_question", label=label, tooltip=s, payload={"question": s}, icon="sparkles"))
                    await cl.Message(content="Sugerencias:", actions=actions).send()

        # Guardar nuevo estado del Router
        new_router_state = final_state["router_state"]
        cl.user_session.set("router_state", new_router_state)
        
        # Sincronizar variables individuales clave
        cl.user_session.set("ppt_pending", new_router_state.get("ppt_pending", False))
        cl.user_session.set("ppt_request_base", new_router_state.get("ppt_request_base", ""))
        
        thinking_msg.content = "Respuesta generada vía LangGraph."
        await thinking_msg.update()

        # 6. SINCRONIZACIÓN MANUAL DE PERSISTENCIA (Base de Datos)
        # Esto asegura que el historial se guarda en SQLite incluso si la integración automática falla.
        if cl.data_layer and cl.context.session.thread_id:
            try:
                user = cl.user_session.get("user")
                user_id = getattr(user, "id", None) if user else None
                
                # [FIX] Si el usuario en sesión no tiene ID, lo buscamos en BD
                if user and not user_id and getattr(user, "identifier", None):
                    persisted_user = await cl.data_layer.get_user(user.identifier)
                    if persisted_user:
                        user_id = persisted_user.id
                
                # Actualizamos el Hilo (Thread) con el nombre y usuario correctos
                await cl.data_layer.update_thread(
                    thread_id=cl.context.session.thread_id,
                    name=question[:50] if len(current_history) <= 2 else None,
                    user_id=user_id
                )
                print(f"--- [SYNC] Hilo {cl.context.session.thread_id} actualizado manualmente ---")

                # Guardamos el mensaje del USUARIO
                import uuid
                from datetime import datetime
                
                step_user = {
                    "id": str(uuid.uuid4()),
                    "threadId": cl.context.session.thread_id,
                    "name": "User",
                    "type": "user_message",
                    "output": question,
                    "createdAt": datetime.utcnow().isoformat() + "Z"
                }
                await cl.data_layer.create_step(step_user)
                # print(f"--- [SYNC] Mensaje usuario guardado ---")

                # Guardamos la respuesta del ASISTENTE
                if answer:
                    step_ai = {
                        "id": str(uuid.uuid4()),
                        "threadId": cl.context.session.thread_id,
                        "name": "Asistente",
                        "type": "assistant_message",
                        "output": answer,
                        "createdAt": datetime.utcnow().isoformat() + "Z"
                    }
                    await cl.data_layer.create_step(step_ai)
                    # print(f"--- [SYNC] Mensaje asistente guardado ---")

            except Exception as e:
                print(f"--- [ERROR SYNC] Fallo al guardar historial: {e} ---")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR LangGraph] {e}")
        thinking_msg.content = f"Error en el flujo del grafo: {e}"
        await thinking_msg.update()
