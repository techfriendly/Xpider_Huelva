"""
NODOS DEL GRAFO: graph_nodes.py
DESCRIPCIÓN:
Este archivo contiene la lógica de cada "caja" (nodo) del diagrama de flujo.
Cada función aquí recibe el estado actual de la conversación, hace algo (buscar, pensar, generar),
y devuelve un nuevo estado actualizado.
"""

import chainlit as cl
from typing import Dict, Any, List, Optional
import config
from services.graph_state import AgentState
from services.intent_router import detect_intent
from services.cypher import cypher_qa
from services.embeddings import embed_text
from services.followups import (
    generate_follow_up_questions,
    should_generate_followups,
    summarize_for_memory,
)
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
from chat_utils.prompt_loader import load_prompt
from clients import llm_client
import json
import re

# --- NODO 1: ROUTER (CLASIFICADOR) ---
async def router_node(state: AgentState) -> AgentState:
    """
    Decide qué intención tiene el usuario (Consulta, Saludo, PPT, etc.)
    Analiza la pregunta y el historial reciente.
    """
    print(f"--- [GRAFO] EJECUTANDO: router_node. Pregunta: {state['question'][:50]}... ---")
    question = state["question"]
    history = state["history"]
    router_state = state["router_state"]
    
    # 1. Detectar intención usando LLM
    intent = await cl.make_async(detect_intent)(question, history, router_state)
    
    # Si el detector reescribe la pregunta (ej: "búscalo" -> "buscar X"), actualizamos el estado
    if intent.get("rewritten_query"):
        question = intent["rewritten_query"]
        state = {**state, "question": question}
        # CRÍTICO: Si reescribimos, es una búsqueda nueva, no usar caché anterior.
        intent["is_followup"] = False
    
    # HEURÍSTICA DE SEGURIDAD PARA PPT:
    # Si estábamos pendientes de un PPT y el usuario da una respuesta técnica (lista numerada, texto largo),
    # forzamos que sea PPT aunque el clasificador se confunda y diga "RAG".
    lines = [l for l in question.splitlines() if l.strip()]
    is_technical_answer = (
        bool(re.search(r"^\s*(\d+\.|-|•|\*)\s+.+", question, re.MULTILINE)) 
        or len(question.split()) > 30
        or len(lines) >= 3
    )
    
    if router_state.get("ppt_pending") and is_technical_answer:
        intent["intent"] = "GENERATE_PPT"
    
    # Si estábamos pendientes de PPT pero el usuario cambia de tema (y no es respuesta técnica), limpiamos estado PPT.
    if router_state.get("ppt_pending") and intent.get("intent") != "GENERATE_PPT":
        router_state = {**router_state, "ppt_pending": False, "ppt_request_base": ""}

    return {**state, "intent": intent, "router_state": router_state}

# --- NODO 2: SALUDO ---
async def greeting_node(state: AgentState) -> AgentState:
    """Responde a saludos simples sin gastar recursos de búsqueda."""
    print(f"--- [GRAFO] EJECUTANDO: greeting_node ---")
    answer = (
        "Hola. Dime qué necesitas buscar.\n\n"
        "Ejemplos:\n"
        "- \"¿Qué contratos ha ganado Techfriendly?\"\n"
        "- \"¿Me haces un pliego de prescripciones técnicas para el Suministro de un vehículo 4x4 para el servicio forestal?\"\n"
        "- \"Top 10 adjudicatarias por importe adjudicado\""
    )
    return {**state, "answer": answer}

# --- NODO 3: CYPHER (CONSULTA EXACTA A GRAFO) ---
async def cypher_node(state: AgentState) -> AgentState:
    """
    Ejecuta consultas técnicas (SQL/Cypher) contra la base de datos de conocimiento.
    Ideal para preguntas exactas como "¿Cuánto dinero ha ganado X?" o estadísticas.
    """
    print(f"--- [GRAFO] EJECUTANDO: cypher_node. Intención: {state['intent'].get('intent')} ---")
    question = state["question"]
    intent = state["intent"]
    router_state = state["router_state"]
    focus = (intent.get("focus") or "CONTRATO").upper()
    
    # Caso especial: Ficha de Empresa
    if focus == "EMPRESA":
        from services.orchestrator import _empresa_lookup, _normalize_contrato_keys
        empresa_lookup = _empresa_lookup(intent, router_state)
        
        if empresa_lookup:
            # Buscamos estadísticas de la empresa
            stats = await cl.make_async(empresa_awards_stats)(empresa_lookup)
            if not stats:
                return {**state, "answer": f"No he encontrado la empresa '{empresa_lookup}' en el grafo."}
            
            nombre = stats.get("nombre") or empresa_lookup
            nif = stats.get("nif") or "N/D"
            n_contratos = stats.get("contratos_ganados", 0)
            importe_total = stats.get("importe_total", 0)
            
            # Buscamos sus contratos recientes
            contratos = await cl.make_async(search_contratos_by_empresa)(empresa_lookup, k_empresas=3, k_contratos=12)
            contratos = _normalize_contrato_keys(contratos)
            
            # Preparamos la evidencia para el sidebar
            ev_md = "### Evidencias (Empresa / Agregación)\n"
            ev_md += f"**Input usuario:** {empresa_lookup}\n\n"
            ev_md += f"**Empresa resuelta:** {nombre} (NIF: {nif})\n\n"
            
            # Texto de respuesta
            content = f"{nombre} (NIF: {nif}) ha ganado **{n_contratos}** contratos."
            content += f"\nImporte total adjudicado (según el grafo): **{importe_total}**."
            
            # Actualizamos memoria de navegación
            new_router_state = {
                **router_state,
                "last_intent": "CYPHER_QA",
                "last_focus": "EMPRESA",
                "last_empresa_query": empresa_lookup,
                "last_empresa_nif": nif if nif != "N/D" else intent.get("empresa_nif"),
                "last_contratos": contratos,
            }
            
            return {
                **state, 
                "answer": content, 
                "router_state": new_router_state,
                "sidebar_title": "Evidencias Neo4j (Empresa)",
                "sidebar_md": ev_md,
                "sidebar_props": {"mode": "EMPRESA"}
            }
            
    # Caso General: Generar consulta Cypher con LLM
    out = await cl.make_async(cypher_qa)(question)
    if out.get("error"):
        return {**state, "error": f"No he podido ejecutar consulta QA.\nDetalle: {out.get('error')}"}
    
    new_router_state = {
        **router_state,
        "last_intent": "CYPHER_QA",
        "last_focus": "CONTRATO",
    }
    return {
        **state, 
        "answer": out["answer"],
        "router_state": new_router_state,
        "sidebar_title": "Evidencias Neo4j (Grafo)",
        "sidebar_md": out.get("sidebar_md"),
        "sidebar_props": {"mode": "CYPHER"}
    }

# --- NODO 4: RAG (BÚSQUEDA SEMÁNTICA) ---
async def rag_node(state: AgentState) -> AgentState:
    """
    Busca documentos (pliegos, contratos, PDF) similares a la pregunta.
    Construye un contexto y pide al LLM que responda basándose en ellos.
    """
    print(f"--- [GRAFO] EJECUTANDO: rag_node. Foco: {state['intent'].get('focus')} ---")
    from services.orchestrator import _empresa_lookup, _normalize_contrato_keys, _empresa_context_header
    from services.context_builder import build_context
    
    question = state["question"]
    intent = state["intent"]
    router_state = state["router_state"]
    history = state["history"]
    focus = (intent.get("focus") or "CONTRATO").upper()
    
    # Lógica de Caché para seguimiento de preguntas (Follow-up)
    current_empresa = intent.get("empresa_query")
    last_empresa = router_state.get("last_empresa_query")
    # ¿Hemos cambiado de empresa?
    entity_switch = bool(current_empresa and last_empresa and current_empresa.lower() != last_empresa.lower())
    
    # Usamos caché si es seguimiento Y es la misma empresa
    use_cached_context = bool(intent.get("is_followup") and router_state.get("last_contratos") and not entity_switch)

    # SUB-LOGICA A: RAG ENFOCADO EN EMPRESA
    if focus == "EMPRESA":
        if not use_cached_context or entity_switch:
            # Búsqueda fresca de contratos de la empresa
            empresa_lookup = _empresa_lookup(intent, router_state)
            empresas = []
            contratos = []
            if empresa_lookup:
                empresas = await cl.make_async(search_empresas)(empresa_lookup, 5, 12)
                contratos = await cl.make_async(search_contratos_by_empresa)(empresa_lookup, 3, max(25, config.K_CONTRATOS))

                router_state["last_focus"] = "EMPRESA"
                router_state["last_empresa_query"] = empresa_lookup
                router_state["last_empresa_nif"] = (empresas[0].get("nif") if empresas else intent.get("empresa_nif"))
                
                if entity_switch: # Limpiar caché si cambia la empresa
                    router_state["last_contratos"] = []
                    router_state["last_capitulos"] = []
                    router_state["last_extractos"] = []

                if contratos:
                    router_state["last_contratos"] = contratos

            contratos = _normalize_contrato_keys(contratos)
            embedding = await cl.make_async(embed_text)(question)
            capitulos = []
            extractos = []
            
            # Búsqueda profunda en los documentos de esos contratos
            if contratos and embedding:
                doc_tipo = intent.get("doc_tipo")
                tipos = intent.get("extracto_tipos")
                allowed = [c.get("expediente") for c in contratos if c.get("expediente")]
                # Deduplicar expedientes
                seen = set()
                allowed = [x for x in allowed if x and not (x in seen or seen.add(x))]

                capitulos = await cl.make_async(search_capitulos)(embedding, k=config.K_CAPITULOS, doc_tipo=doc_tipo, expedientes=allowed)
                extractos = await cl.make_async(search_extractos)(embedding, k=config.K_EXTRACTOS, tipos=tipos, doc_tipo=doc_tipo, expedientes=allowed)

                router_state["last_capitulos"] = capitulos
                router_state["last_extractos"] = extractos

            # Construir Markdown de evidencias
            evidence_md = build_evidence_markdown(contratos, capitulos, extractos)
            context = build_context(question, contratos, capitulos, extractos)
            if empresa_lookup:
                context = _empresa_context_header(empresa_lookup, empresas) + "\n\n" + context

            # Preparar Prompt para el LLM
            system_msg = "Eres un asistente experto en contratación pública. Respondes SOLO con la información del contexto. No inventas datos."
            history_short = history[-config.MAX_HISTORY_TURNS:]
            # Recortar historial para que quepa en memoria
            history_trimmed = trim_history_to_fit(history_short, system_msg, context, config.MODEL_MAX_CONTEXT_TOKENS, config.RESERVE_FOR_ANSWER_TOKENS)
            rep = context_token_report(system_msg, history_trimmed, context)

            new_router_state = {
                **router_state,
                "last_intent": "RAG_QA",
                "last_focus": "EMPRESA",
                "last_empresa_query": empresa_lookup,
                "last_empresa_nif": (empresas[0].get("nif") if empresas else intent.get("empresa_nif")),
                "last_contratos": contratos,
                "last_capitulos": capitulos,
                "last_extractos": extractos
            }

            return {
                **state,
                "answer_prompt": {"system": system_msg, "history": history_trimmed, "user": context},
                "sidebar_title": "Evidencias RAG usadas (Empresa)",
                "sidebar_md": evidence_md,
                "sidebar_props": {
                    "mode": "RAG_EMPRESA",
                    "filters": {"empresa": empresa_lookup},
                    "tokens": {"sent_approx": rep["total"]},
                    "counts": {"contratos": len(contratos), "capitulos": len(capitulos), "extractos": len(extractos)},
                },
                "router_state": new_router_state,
                "contratos": contratos,
                "capitulos": capitulos,
                "extractos": extractos
            }
        else:
            # Caso caché (Follow-up)
            new_router_state = {**router_state, "last_intent": "RAG_QA", "last_focus": "EMPRESA"}
            
            # DETECCIÓN DE ERROR DE ESTRATEGIA:
            # Si estamos en modo "una sola empresa" pero el usuario pide un "ranking" o "top",
            # el RAG va a fallar (solo tiene info de una empresa).
            # Mandamos a CYPHER.
            is_aggregation = any(x in question.lower() for x in ["ranking", "top 10", "top 5", "quién ganó más", "mayor importe"])
            
            if is_aggregation:
                 print(f"--- [GRAFO] FALLBACK: RAG -> CYPHER (Detectada Agregación) ---")
                 intent["intent"] = "CYPHER_QA" 
                 intent["focus"] = "EMPRESA"
                 intent["needs_aggregation"] = True
                 
                 return {
                    **state,
                    "intent": {**state["intent"], "needs_cypher_fallback": True},
                    "answer": None,
                    "router_state": {**router_state, "last_intent": "RAG_QA"}
                 }

            # Si no es agregación, respuesta normal RAG Followup (código omitido por brevedad, usa caché similar arriba)
            # Nota: Para simplificar, reutilizamos la lógica de construcción de prompt de arriba,
            # pero usando 'contratos', 'capitulos' de `router_state`.
            contratos = router_state.get("last_contratos", [])
            capitulos = router_state.get("last_capitulos", [])
            extractos = router_state.get("last_extractos", [])
            
            evidence_md = build_evidence_markdown(contratos, capitulos, extractos)
            context = build_context(question, contratos, capitulos, extractos)
            
            system_msg = "Eres un asistente experto en contratación pública. Respondes SOLO con la información del contexto. No inventas datos."
            history_trimmed = trim_history_to_fit(history[-config.MAX_HISTORY_TURNS:], system_msg, context, config.MODEL_MAX_CONTEXT_TOKENS, config.RESERVE_FOR_ANSWER_TOKENS)
            
            return {
                **state,
                "answer_prompt": {"system": system_msg, "history": history_trimmed, "user": context},
                "sidebar_title": "Evidencias RAG (Contexto previo)",
                "sidebar_md": evidence_md,
                "sidebar_props": {"mode": "RAG_FOLLOWUP"},
                "router_state": new_router_state,
                "contratos": contratos,
                "capitulos": capitulos,
                "extractos": extractos
            }

    # SUB-LOGICA B: RAG ENFOCADO EN CONTRATOS/TEMAS (Standard)
    if focus == "CONTRATO" and use_cached_context:
        # Reutilizamos documentos encontrados anteriormente
        contratos = router_state.get("last_contratos", [])
        contratos = _normalize_contrato_keys(contratos)
        doc_tipo = intent.get("doc_tipo") or router_state.get("last_doc_tipo")
        tipos = intent.get("extracto_tipos") or router_state.get("last_extracto_tipos")

        embedding = await cl.make_async(embed_text)(question)
        if not embedding: return {**state, "error": "No he podido generar el embedding"}

        # Filtramos búsqueda vectorial solo a los expedientes ya encontrados
        allowed = [c.get("expediente") for c in contratos if c.get("expediente")]
        seen = set()
        allowed = [x for x in allowed if x and not (x in seen or seen.add(x))]

        capitulos = await cl.make_async(search_capitulos)(embedding, config.K_CAPITULOS, doc_tipo, allowed)
        extractos = await cl.make_async(search_extractos)(embedding, config.K_EXTRACTOS, tipos, doc_tipo, allowed)
    else:
        # Búsqueda nueva abierta
        embedding = await cl.make_async(embed_text)(question)
        if not embedding: return {**state, "error": "No he podido generar el embedding"}

        doc_tipo = intent.get("doc_tipo")
        tipos = intent.get("extracto_tipos")

        contratos = await cl.make_async(search_contratos)(embedding, config.K_CONTRATOS)
        capitulos = await cl.make_async(search_capitulos)(embedding, config.K_CAPITULOS, doc_tipo)
        extractos = await cl.make_async(search_extractos)(embedding, config.K_EXTRACTOS, tipos, doc_tipo)

    contratos = _normalize_contrato_keys(contratos)
    evidence_md = build_evidence_markdown(contratos, capitulos, extractos)
    context = build_context(question, contratos, capitulos, extractos)

    system_msg = "Eres un asistente experto en contratación pública. Respondes SOLO con la información del contexto. No inventas datos."
    history_trimmed = trim_history_to_fit(history[-config.MAX_HISTORY_TURNS:], system_msg, context, config.MODEL_MAX_CONTEXT_TOKENS, config.RESERVE_FOR_ANSWER_TOKENS)
    rep = context_token_report(system_msg, history_trimmed, context)

    new_router_state = {
        **router_state,
        "last_intent": "RAG_QA",
        "last_focus": "CONTRATO",
        "last_contratos": contratos,
        "last_capitulos": capitulos,
        "last_extractos": extractos,
        "last_doc_tipo": doc_tipo,
        "last_extracto_tipos": tipos,
    }

    return {
        **state,
        "answer_prompt": {"system": system_msg, "history": history_trimmed, "user": context},
        "sidebar_title": "Evidencias RAG usadas",
        "sidebar_md": evidence_md,
        "sidebar_props": {
            "mode": "RAG",
            "filters": {"doc_tipo": doc_tipo, "extracto_tipos": tipos},
            "tokens": {"sent_approx": rep["total"]},
            "counts": {"contratos": len(contratos), "capitulos": len(capitulos), "extractos": len(extractos)},
        },
        "router_state": new_router_state,
        "contratos": contratos,
        "capitulos": capitulos,
        "extractos": extractos
    }

# --- NODO 5: PLANIFICADOR PPT ---
async def ppt_plan_node(state: AgentState) -> AgentState:
    """Detecta si falta información para crear el PPT y genera preguntas al usuario."""
    print(f"--- [GRAFO] EJECUTANDO: ppt_plan_node ---")
    question = state["question"]
    router_state = state["router_state"]
    
    is_pending = router_state.get("ppt_pending", False)
    base_req = router_state.get("ppt_request_base", "")
    ppt_rounds = router_state.get("ppt_rounds", 0)
    
    # Contexto acumulado (petición original + respuesta nueva del usuario)
    full_context = question
    if is_pending and base_req:
        full_context = f"{base_req}\n\nNuevos detalles/petición: {question}"
    
    # El LLM analiza si necesita más datos
    plan = await cl.make_async(plan_ppt_clarifications)(full_context)
    
    # Regla: Si llevamos 2 rondas de preguntas, paramos y generamos con lo que haya.
    force_clarification = not is_pending
    if ppt_rounds >= 2 and plan.get("need_clarification"):
        plan["need_clarification"] = False

    if force_clarification or plan.get("need_clarification"):
        # Preguntas por defecto si el LLM no generó ninguna
        if not plan.get("questions"):
            plan["questions"] = [
                "¿Podrías especificar para qué se va a usar exactamente?",
                "¿Qué características técnicas mínimas debe cumplir?",
                "¿Cuál es el presupuesto máximo estimado?"
            ]
        
        return {
            **state,
            "intent": {**state["intent"], "ppt_clarifications_needed": True, "ppt_plan": plan},
            "answer": "Necesito aclaraciones antes de generar el PPT.",
            "router_state": {
                **router_state, 
                "ppt_pending": True, 
                "ppt_request_base": plan.get("normalized_request"),
                "ppt_rounds": ppt_rounds + 1
            }
        }

    # Si todo ok, pasamos a generar
    return {
        **state,
        "intent": {**state["intent"], "ppt_clarifications_needed": False, "ppt_plan": plan},
        "router_state": {**router_state, "ppt_pending": False, "ppt_request_base": "", "ppt_rounds": 0}
    }

# --- NODO 6: GENERADOR PPT ---
async def ppt_generate_node(state: AgentState) -> AgentState:
    """Crea el contenido del PPT usando un contrato de referencia y el LLM."""
    print(f"--- [GRAFO] EJECUTANDO: ppt_generate_node ---")
    plan = state["intent"].get("ppt_plan", {})
    question = plan.get("normalized_request") or state["question"]
    
    # 1. Buscar contrato de referencia similar (para copiar estructura)
    emb = await cl.make_async(embed_text)(question)
    if not emb: return {**state, "error": "Error de embedding en PPT"}

    ref_contrato = await cl.make_async(find_reference_ppt_contract)(emb, top_k=10)
    if not ref_contrato: return {**state, "error": "No he encontrado un PPT de referencia"}

    contract_id = ref_contrato["contract_id"]
    ref_data = await cl.make_async(get_ppt_reference_data)(contract_id)
    if ref_data is None: return {**state, "error": f"El contrato {contract_id} no tiene PPT con capítulos"}

    # 2. Buscar bloques de texto extra
    extra_extractos = await cl.make_async(search_extractos)(emb, k=min(20, config.K_EXTRACTOS), tipos=None, doc_tipo="PPT")
    
    # Evidencias visuales
    evidence_md = build_evidence_markdown(
        contratos=[{"expediente": ref_data.get("expediente"), "titulo": ref_data.get("contrato_titulo"), "adjudicataria_nombre": "REF PPT", "importe_adjudicado": "N/A"}],
        capitulos=[{"heading": c.get("heading"), "texto": c.get("texto", ""), "expediente": ref_data.get("expediente")} for c in ref_data.get("capitulos", [])[:12]],
        extractos=[{"tipo": ex.get("tipo"), "texto": ex.get("texto", ""), "expediente": ref_data.get("expediente")} for ex in extra_extractos[:12]],
    )

    # Construir prompt de generación
    system_msg, user_msg = build_ppt_generation_prompt_one_by_one(question, ref_data)

    return {
        **state,
        "ppt_generation_input": {"system": system_msg, "user": user_msg, "ref_data": ref_data},
        "sidebar_title": "Evidencias RAG usadas (PPT)",
        "sidebar_md": evidence_md,
        "sidebar_props": {"mode": "PPT"},
        "router_state": {**state["router_state"], "last_intent": "GENERATE_PPT"}
    }

# --- NODO 7: POST-PROCESO ---
async def post_process_node(state: AgentState) -> AgentState:
    """Limpia el historial, genera preguntas sugeridas y finaliza."""
    print(f"--- [GRAFO] EJECUTANDO: post_process_node ---")
    answer = state.get("answer", "")
    answer_mem = ""
    
    # Resumir respuesta para memoria si es muy larga
    if answer:
        is_table = "---" in answer and "|" in answer
        if len(answer) > 3000 and not is_table:
            answer_mem = await cl.make_async(summarize_for_memory)(answer, config.MEMORY_SUMMARY_TOKENS)
        else:
            answer_mem = answer
            
    new_history = list(state["history"])
    if answer:
        new_history.append({"role": "user", "content": state["question"]})
        new_history.append({"role": "assistant", "content": answer_mem})
    
    # Generar sugerencias (Follow-ups)
    follow_ups = []
    if answer:
        contratos = state.get("contratos") or []
        capitulos = state.get("capitulos") or []
        extractos = state.get("extractos") or []
        
        is_simple_chat = (state["router_state"].get("last_intent") == "SIMPLE_CHAT")
        should_gen = should_generate_followups(answer, contratos, capitulos, extractos)
        
        if should_gen or (is_simple_chat and len(answer) > 100):
            follow_ups = await cl.make_async(generate_follow_up_questions)(state["question"], answer, 3)
         
    return {
        **state, 
        "history": new_history[-config.MAX_HISTORY_TURNS:], 
        "follow_ups": follow_ups
    }

# --- NODO 8: CHAT SIMPLE ---
async def simple_chat_node(state: AgentState) -> AgentState:
    """
    Chat básico usando solo el historial y conocimientos generales del LLM.
    Se usa para preguntas de razonamiento, matemáticas o charla casual sobre
    lo que ya se ha discutido.
    """
    print(f"--- [GRAFO] EJECUTANDO: simple_chat_node ---")
    question = state["question"]
    history = state["history"] or []
    
    # Formatear historial (últimos 5 turnos)
    history_ctx = ""
    for turn in history[-5:]:
        role = "Usuario" if turn["role"] == "user" else "Asistente"
        content = turn["content"]
        if len(content) > 8000:
             content = content[:8000] + "... (contenido truncado)"
        history_ctx += f"{role}: {content}\n"

    system_msg = load_prompt("simple_chat_system")
    
    resp = await cl.make_async(llm_client.chat.completions.create)(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Historial:\n{history_ctx}\n\nPregunta actual: {question}"}
        ],
        temperature=0.3,
        max_tokens=1000,
    )
    
    answer = resp.choices[0].message.content or "No he podido procesar tu solicitud."
    
    # AUTO-CORRECCIÓN: si el LLM dice "no lo sé, mira en los datos", mandamos a RAG.
    missing_info_keywords = [
        "no se dispone de información", "no aparece en el historial",
        "no tengo datos sobre", "no he encontrado", "desconozco"
    ]
    needs_fallback = any(k in answer.lower() for k in missing_info_keywords)
    
    if needs_fallback:
        await cl.Message(content="ℹ️ No encuentro esta información en lo hablado hasta ahora. Consultando la base de datos...").send()
        
        # Forzar búsqueda explícita
        forced_question = f"busca en base de datos: {question}"
        
        return {
            **state,
            "question": forced_question,
            "intent": {**state["intent"], "needs_rag_fallback": True},
            "answer": None, 
            "router_state": {**state["router_state"], "last_intent": "SIMPLE_CHAT"}
        }

    new_router_state = {**state["router_state"], "last_intent": "SIMPLE_CHAT"}
    
    return {
        **state,
        "answer": answer,
        "router_state": new_router_state,
        "sidebar_title": state.get("sidebar_title"), 
        "sidebar_md": state.get("sidebar_md"),
        "sidebar_props": state.get("sidebar_props")
    }
