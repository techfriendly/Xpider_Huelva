"""
TOOLS V2: tools.py
Definición de herramientas en formato OpenAI y sus ejecutores.
"""
from typing import Any, Dict, List
import json
import config
from clients import llm_client
from services.embeddings import embed_text
from services.neo4j_queries import (
    search_contratos, search_capitulos, search_extractos,
    search_empresas, empresa_awards_stats, search_contratos_by_empresa
)
from services.context_builder import build_context
from services.cypher import cypher_qa
from services.ppt_generation import (
    plan_ppt_clarifications, find_reference_ppt_contract,
    get_ppt_reference_data, build_ppt_generation_prompt_one_by_one,
    ppt_to_docx_bytes, slug_filename, HAS_DOCX
)
from chat_utils.text_utils import clip

# ============================================================================
# SCHEMA DE HERRAMIENTAS (Formato OpenAI)
# ============================================================================

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_contracts",
            "description": "Busca contratos públicos, licitaciones o pliegos por tema. Usa para preguntas generales sobre contratación.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Tema a buscar, ej: 'vehículos 4x4', 'limpieza de edificios'"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_company",
            "description": "Busca datos de una empresa: NIF, contratos ganados, importes. Usa cuando pregunten por una empresa específica.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {
                        "type": "string",
                        "description": "Nombre o parte del nombre de la empresa"
                    }
                },
                "required": ["company_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_contract_details",
            "description": "Obtiene detalles de un contrato específico por su expediente/referencia. Usa cuando el usuario mencione un expediente concreto como '22sesuA53' o '2024/IGE_03/003219'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expediente": {
                        "type": "string",
                        "description": "El número de expediente o referencia del contrato, ej: '22sesuA53'"
                    }
                },
                "required": ["expediente"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Consulta avanzada a la base de datos. Usa para rankings, conteos o comparaciones globales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Pregunta en lenguaje natural, ej: 'Top 10 empresas con más contratos'"
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_document",
            "description": "Genera ÚNICAMENTE borradores de Pliegos de Prescripciones Técnicas (PPT). NO usar para informes, excels, pdfs, cartas o resúmenes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "Descripción del pliego técnico a generar"
                    }
                },
                "required": ["requirement"]
            }
        }
    }
]

# ============================================================================
# EJECUTORES DE HERRAMIENTAS
# ============================================================================

def execute_tool(tool_name: str, arguments: Dict[str, Any], session_state: Dict) -> Dict[str, Any]:
    """
    Ejecuta una herramienta y devuelve resultado + metadata para sidebar.
    """
    if tool_name == "search_contracts":
        return tool_search_contracts(arguments.get("topic", ""))
    elif tool_name == "search_company":
        return tool_search_company(arguments.get("company_name", ""))
    elif tool_name == "get_contract_details":
        return tool_get_contract_details(arguments.get("expediente", ""), session_state)
    elif tool_name == "query_database":
        return tool_query_database(arguments.get("question", ""))
    elif tool_name == "generate_document":
        return tool_generate_document(arguments.get("requirement", ""), session_state)
    else:
        return {"content": f"Herramienta desconocida: {tool_name}", "sidebar": None}


def tool_search_contracts(topic: str) -> Dict[str, Any]:
    """Búsqueda semántica RAG de contratos."""
    print(f"--- [TOOL] search_contracts: {topic} ---")
    
    # 1. Estrategia Híbrida: Intentar búsqueda exacta por ID/Expediente/NIF
    import re
    
    # Intentar extraer expediente del texto (ej: "22sesuA53", "2024/IGE_03/003219")
    expediente_pattern = re.search(r'\b(\d{2}[a-zA-Z]+\d+|\d{4}/[A-Z_]+/\d+)\b', topic)
    possible_nif = re.search(r'\b[A-Z]\d{8}\b', topic.upper())
    
    contratos = []
    use_rag_fallback = True
    
    # Generar embedding siempre, lo necesitamos para buscar capítulos/extractos relacionados
    embedding = embed_text(topic)
    if not embedding:
         return {"content": "Error generando embedding.", "sidebar": None}

    # Prioridad 1: Búsqueda exacta por expediente extraído
    if expediente_pattern:
        expediente_id = expediente_pattern.group(1)
        print(f"--- [TOOL] Expediente detectado: {expediente_id} ---")
        from services.neo4j_queries import search_contract_by_id
        exact_matches = search_contract_by_id(expediente_id)
        if exact_matches:
            print(f"--- [TOOL] Exact Match Found: {len(exact_matches)} ---")
            contratos = exact_matches
            use_rag_fallback = False

    # Prioridad 2: Búsqueda por NIF
    elif possible_nif:
        from services.neo4j_queries import search_contracts_by_nif
        exact_matches = search_contracts_by_nif(possible_nif.group(0))
        if exact_matches:
            print(f"--- [TOOL] Matches by NIF Found: {len(exact_matches)} ---")
            contratos = exact_matches
            use_rag_fallback = False
            
    # Si no hay match exacto, usar RAG puro
    if use_rag_fallback:
        contratos = search_contratos(embedding, k=5)

    # 3. [NUEVO] Búsqueda Específica de Extractos (Requisitos, Solvencia, Medioambiente...)
    # Buscamos extractos que coincidan semánticamente, para dar contexto del POR QUÉ
    from services.neo4j_queries import search_relevant_extracts_rag
    extractos_match = search_relevant_extracts_rag(embedding, k=5)

    if not contratos and not extractos_match:
         return {"content": "No se encontraron contratos relevantes.", "sidebar": None}
    
    # FORMATO DE RESPUESTA
    content = f"Resultados para: '{topic}'\n\n"
    
    # A) Contratos Generales (RAG o Exacto)
    if contratos:
        content += f"== Contratos Encontrados ({len(contratos)}) ==\n"
        for i, c in enumerate(contratos[:5]):
            content += f"{i+1}. [{c.get('contract_id', 'N/D')}] {c.get('titulo', 'N/D')}\n"
            content += f"   Adjudicataria: {c.get('adjudicataria_nombre', 'N/D')} | Importe: {c.get('importe_adjudicado', 0):,.2f} EUR\n"

    # B) Extractos Específicos (Evidencia del POR QUÉ)
    if extractos_match:
        content += "\n== Detalles Relevantes Encontrados (Claúsulas/Requisitos) ==\n"
        seen_extracts = set()
        for ext in extractos_match:
            texto = ext.get('extracto_texto', '').strip()
            if texto in seen_extracts: continue
            seen_extracts.add(texto)
            
            titulo = ext.get('titulo', 'Sin Título')
            exp = ext.get('expediente') or ext.get('contract_id') or 'N/D'
            tipo = ext.get('extracto_tipo', 'general').replace('_', ' ').upper()
            
            content += f"\n> Contrato [{exp}]: {titulo[:50]}...\n"
            content += f"  TIPO: {tipo}\n"
            content += f"  CONTENIDO: {texto[:400]}...\n"

    # Preparar DataFrame para UI
    import pandas as pd
    import chainlit as cl
    
    # Combinamos para la tabla todos los contratos vistos
    all_contracts_map = {}
    
    for c in contratos:
        all_contracts_map[c.get('contract_id')] = c
        
    for ext in extractos_match:
        cid = ext.get('contract_id')
        if cid and cid not in all_contracts_map:
             # Si encontramos un contrato solo por extracto, intentamos añadirlo a la tabla con datos minimos
             all_contracts_map[cid] = {
                 'contract_id': cid,
                 'titulo': ext.get('titulo'),
                 'expediente': ext.get('expediente'),
                 'adjudicataria_nombre': ext.get('adjudicataria')
             }

    df_data = list(all_contracts_map.values())
    
    if df_data:
        def clean_keys(d):
            new_d = {}
            for k, v in d.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    new_key = k.replace('c.', '').replace('e.', '').replace('r.', '')
                    new_d[new_key] = v
            return new_d

        clean_results = [clean_keys(r) for r in df_data]
        df_clean = pd.DataFrame(clean_results)
        
        # Eliminar 'abstract' si existe para que no ensucie la tabla
        if 'abstract' in df_clean.columns:
            df_clean = df_clean.drop(columns=['abstract'])
            
        dataframe_element = cl.Dataframe(name="Contratos", data=df_clean, size="medium")
    else:
        dataframe_element = None

    return {
        "content": content,
        "dataframe": dataframe_element,
        "sidebar": None
    }


def tool_get_contract_details(expediente: str, session_state: Dict = None) -> Dict[str, Any]:
    """Obtiene detalles de un contrato por expediente exacto."""
    print(f"--- [TOOL] get_contract_details: {expediente} ---")
    
    from services.neo4j_queries import search_contract_by_id, search_extractos_by_expediente
    
    # Limpiamos el expediente (quitar espacios extra)
    expediente = expediente.strip()
    
    if not expediente:
        return {"content": "No se proporcionó expediente.", "sidebar": None}
    
    contratos = search_contract_by_id(expediente)
    
    if not contratos:
        return {
            "content": f"No se encontró ningún contrato con expediente '{expediente}'.", 
            "sidebar": None
        }
    
    # Tomamos el primer resultado (debería ser único)
    c = contratos[0]
    
    # GUARDAR CONTEXTO PARA PPT
    if session_state is not None:
        session_state["last_contract_expediente"] = c.get("expediente")
        session_state["last_contract_title"] = c.get("titulo")
        print(f"--- [CTX] Saved context: {c.get('expediente')} ---")
    
    content = f"**Contrato encontrado:**\n\n"
    content += f"- **Expediente:** {c.get('expediente', 'N/D')}\n"
    content += f"- **Título:** {c.get('titulo', 'N/D')}\n"
    content += f"- **Estado:** {c.get('estado', 'N/D')}\n"
    content += f"- **Adjudicataria:** {c.get('adjudicataria_nombre', 'N/D')} (NIF: {c.get('adjudicataria_nif', 'N/D')})\n"
    content += f"- **Presupuesto sin IVA:** {c.get('presupuesto_sin_iva', 0):,.2f} EUR\n"
    content += f"- **Importe Adjudicado:** {c.get('importe_adjudicado', 0):,.2f} EUR\n"
    content += f"- **CPV Principal:** {c.get('cpv_principal', 'N/D')}\n"
    
    if c.get('abstract'):
        content += f"\n**Resumen:**\n{c.get('abstract')}\n"
    
    if c.get('link_contrato'):
        content += f"\n**Enlace:** [Ver en portal]({c.get('link_contrato')})\n"
    
    # Buscar extractos relacionados (normativas, garantías, etc.)
    try:
        extractos = search_extractos_by_expediente(expediente)
        if extractos:
            content += f"\n**Información adicional del pliego** (extractos detectados):\n"
            for ext in extractos:  # Quitamos límite estricto de 10 si son relevantes
                tipo = ext.get('tipo', 'general').replace('_', ' ').upper()
                texto = ext.get('texto', '')[:600]  # Aumentamos límite a 600 chars
                content += f"\n> **{tipo}**: {texto}{'...' if len(ext.get('texto', '')) > 600 else ''}\n"
    except Exception as e:
        print(f"[WARN] Error buscando extractos: {e}")
    
    sidebar_md = f"### Expediente: {expediente}\n"
    sidebar_md += f"Estado: {c.get('estado', 'N/D')}\n"
    
    return {
        "content": content,
        "sidebar": {"title": "Contrato", "md": sidebar_md}
    }


def tool_search_company(company_name: str) -> Dict[str, Any]:
    """Busca stats de una empresa."""
    print(f"--- [TOOL] search_company: {company_name} ---")
    
    empresas = search_empresas(company_name, k_empresas=1)
    if not empresas:
        return {"content": f"No encontré empresa '{company_name}'.", "sidebar": None}
    
    empresa = empresas[0]
    nombre = empresa.get("nombre")
    stats = empresa_awards_stats(nombre)
    contratos = search_contratos_by_empresa(nombre, k_empresas=1, k_contratos=5)
    
    content = f"**Empresa:** {nombre}\n"
    content += f"**NIF:** {stats.get('nif', 'N/D')}\n"
    content += f"**Contratos Ganados:** {stats.get('contratos_ganados', 0)}\n"
    content += f"**Importe Total:** {stats.get('importe_total', 0):,.2f} EUR\n\n"
    content += "**Contratos Recientes:**\n"
    for c in contratos[:5]:
        titulo = c.get('titulo', 'N/D')
        importe = c.get('importe_adjudicado', 0)
        abstract = c.get('abstract', '')[:200]
        cid = c.get('contract_id', '') or c.get('expediente', '')
        
        content += f"- [Ref: {cid}] {titulo[:60]}... ({importe:,.2f} EUR)\n  Resumen: {abstract}...\n"
    
    content += "\n(NOTA: Para ver plazos, pliegos o detalles, usa 'search_contracts' buscando por la REFERENCIA o TÍTULO)"
    
    sidebar_md = f"## {nombre}\n\n"
    sidebar_md += f"**NIF:** {stats.get('nif')}\n\n"
    sidebar_md += f"**Contratos:** {stats.get('contratos_ganados')}\n\n"
    sidebar_md += f"**Importe:** {stats.get('importe_total'):,.2f} EUR\n"
    
    return {
        "content": content,
        "sidebar": {"title": "Empresa", "md": sidebar_md}
    }


def tool_query_database(question: str) -> Dict[str, Any]:
    """Ejecuta consulta Cypher."""
    print(f"--- [TOOL] query_database: {question} ---")
    
    result = cypher_qa(question)
    
    if result.get("error"):
        return {"content": f"Error: {result['error']}", "sidebar": None}
    
    sidebar_md = result.get("sidebar_md", "")
    rows = result.get("rows", [])
    
    dataframe_element = None
    content = result.get("answer", "Sin resultado")
    
    # Si hay "datos tabulares", generamos Dataframe interactivo
    if rows and len(rows) > 0 and isinstance(rows, list):
        try:
            import pandas as pd
            import chainlit as cl
            
            df = pd.DataFrame(rows)
            # Limpiamos columnas raras si las hay
            df = df.fillna("")
            
            # Eliminar 'abstract' si existe
            if 'abstract' in df.columns:
                df = df.drop(columns=['abstract'])
            
            dataframe_element = cl.Dataframe(
                name="Tabla de Resultados",
                data=df,
                display="inline"
            )
            
            # IMPORTANTE: Mantenemos el contenido original (answer) que contiene
            # la tabla markdown o el resumen real de los datos.
            # Esto evita que el LLM "invente" datos en su respuesta final.
            # NO sustituimos content con un mensaje genérico.
        except Exception as e:
            print(f"[WARN] Error creando DataFrame: {e}")

    return {
        "content": clip(content, 8000),
        "sidebar": {"title": "Cypher", "md": sidebar_md} if sidebar_md else None,
        "dataframe": dataframe_element
    }


def tool_generate_document(requirement: str, session_state: Dict) -> Dict[str, Any]:
    """
    Genera documento PPT. Puede requerir clarificaciones.
    Retorna instrucciones para el orquestador.
    """
    print(f"--- [TOOL] generate_document: {requirement} ---")
    
    # 1. Verificar si necesita clarificaciones
    plan = plan_ppt_clarifications(requirement)
    
    if plan.get("need_clarification"):
        questions = plan.get("questions", [])
        session_state["ppt_pending"] = True
        session_state["ppt_requirement"] = plan.get("normalized_request") or requirement
        session_state["ppt_questions"] = questions
        
        q_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)])
        return {
            "content": f"CLARIFICACION_REQUERIDA\n\nPreguntas:\n{q_text}",
            "sidebar": None,
            "needs_clarification": True,
            "questions": questions
        }
    
    # 2. Buscar referencia y generar
    return _generate_ppt_content(plan.get("normalized_request") or requirement, session_state)


def continue_ppt_generation(user_response: str, session_state: Dict) -> Dict[str, Any]:
    """Continúa la generación después de que el usuario responda clarificaciones."""
    base_req = session_state.get("ppt_requirement", "")
    full_req = f"{base_req}\n\nDetalles adicionales del usuario:\n{user_response}"
    
    session_state["ppt_pending"] = False
    session_state["ppt_requirement"] = ""
    
    return _generate_ppt_content(full_req, session_state)


def _generate_ppt_content(requirement: str, session_state: Dict = None) -> Dict[str, Any]:
    """Genera el contenido del PPT (llamada interna)."""
    
    ref_contrato = None
    
    # 1. Intentar usar contexto previo si no hay expediente explícito en el requerimiento
    if session_state and session_state.get("last_contract_expediente"):
        from services.neo4j_queries import search_contract_by_id
        # Solo si el requerimiento parece genérico ("de este contrato", "del contrato")
        if "este contrato" in requirement.lower() or "del contrato" in requirement.lower() or len(requirement) < 50:
            print(f"--- [PPT] Usando contexto previo: {session_state['last_contract_expediente']} ---")
            possible = search_contract_by_id(session_state["last_contract_expediente"])
            if possible:
                ref_contrato = possible[0]

    # 2. Si no hay contexto o falló, buscar por embedding (RAG)
    if not ref_contrato:
        embedding = embed_text(requirement)
        ref_contrato = find_reference_ppt_contract(embedding, top_k=5)
    
    if not ref_contrato:
        return {"content": "No encontré contrato de referencia para generar el documento.", "sidebar": None}
    
    ref_data = get_ppt_reference_data(ref_contrato["contract_id"])
    system_msg, user_msg = build_ppt_generation_prompt_one_by_one(requirement, ref_data)
    
    # Sidebar con referencia
    link = ref_data.get("link_contrato") or "#"
    link_md = f"[🔗 Ver Contrato Original]({link})" if link != "#" else "(Sin enlace)"
    
    sidebar_md = f"## Referencia PPT\n\n"
    sidebar_md += f"**Expediente:** {ref_data.get('expediente')}\n\n"
    sidebar_md += f"**Título:** {ref_data.get('contrato_titulo')}\n\n"
    sidebar_md += f"{link_md}\n\n"
    sidebar_md += "### Capítulos:\n"
    for c in ref_data.get("capitulos", [])[:10]:
        heading = c.get('heading', 'N/D')
        texto = c.get('texto', '')
        snippet = clip(texto, 140)
        sidebar_md += f"- **{heading}**\n  _{snippet}_\n"
    
    return {
        "content": "GENERAR_PPT",
        "sidebar": {"title": "PPT Referencia", "md": sidebar_md},
        "ppt_prompts": {"system": system_msg, "user": user_msg},
        "ppt_title": ref_data.get("contrato_titulo", "Pliego")
    }
