import os
import textwrap
from typing import List, Dict, Any
from collections import defaultdict


import chainlit as cl
from neo4j import GraphDatabase
from openai import OpenAI

# ==========================
# CONFIGURACIÓN
# ==========================

# Neo4j
NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://49.13.151.49:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "root_tech_2019")
NEO4J_DB       = os.getenv("NEO4J_DB", "huelva")

# LLM (chat) – servidor OpenAI-compatible en 8002
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.71.46.94:8002/v1")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "dummy-key")  # da igual si tu servidor no valida
LLM_MODEL    = os.getenv("LLM_MODEL", "llm")

# Embeddings – servidor OpenAI-compatible en 8003
EMB_BASE_URL = os.getenv("EMB_BASE_URL", "http://100.71.46.94:8003/v1")
EMB_API_KEY  = os.getenv("EMB_API_KEY", "dummy-key")
EMB_MODEL    = os.getenv("EMB_MODEL", "embedding")
EMB_DIM      = int(os.getenv("EMB_DIM", "1024"))

# Top-K resultados por tipo
K_CONTRATOS = 10
K_CAPITULOS = 10
K_EXTRACTOS = 30

# Cuántos turnos de historial mantener (user+assistant)
MAX_HISTORY_TURNS = 6  # es decir, hasta 6 mensajes en total (3 preguntas + 3 respuestas)


# ==========================
# CLIENTES GLOBALes
# ==========================

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

llm_client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
emb_client = OpenAI(base_url=EMB_BASE_URL, api_key=EMB_API_KEY)


# ==========================
# HELPERS: EMBEDDING & NEO4J
# ==========================

def embed_text(text: str, max_chars: int = 4000) -> List[float]:
    """Llama a tu modelo de embeddings y devuelve un vector de floats."""
    if not text:
        return []
    text = text[:max_chars]
    resp = emb_client.embeddings.create(
        model=EMB_MODEL,
        input=text,
    )
    emb = resp.data[0].embedding
    if len(emb) != EMB_DIM:
        print(f"[WARN] Embedding dimension {len(emb)} != {EMB_DIM}")
    return emb


def neo4j_query(cypher: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Ejecuta una query Cypher en la BD NEO4J_DB y devuelve lista de dicts."""
    if params is None:
        params = {}
    with driver.session(database=NEO4J_DB) as session:
        result = session.run(cypher, **params)
        return [record.data() for record in result]


# ==========================
# VECTOR SEARCH EN NEO4J
# ==========================

def search_contratos(embedding: List[float], k: int = K_CONTRATOS) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('contrato_rag_embedding', $k, $embedding)
    YIELD node, score
    OPTIONAL MATCH (e:EmpresaRAG)-[:ADJUDICATARIA_RAG]->(node)
    RETURN
      node.contract_id         AS contract_id,
      coalesce(node.expediente,'')    AS expediente,
      coalesce(node.titulo,'')        AS titulo,
      coalesce(node.abstract,'')      AS abstract,
      coalesce(node.estado,'')        AS estado,
      coalesce(node.cpv_principal,'') AS cpv_principal,
      e.nif                            AS adjudicataria_nif,
      e.nombre                         AS adjudicataria_nombre,
      node.presupuesto_sin_iva         AS presupuesto_sin_iva,
      node.valor_estimado              AS valor_estimado,
      node.importe_adjudicado          AS importe_adjudicado,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding})



def search_capitulos(embedding: List[float], k: int = K_CAPITULOS) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('capitulo_embedding', $k, $embedding)
    YIELD node, score
    MATCH (c:ContratoRAG)-[:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_CAPITULO]->(node)
    RETURN
      node.cap_id         AS cap_id,
      coalesce(node.heading,'') AS heading,
      coalesce(node.texto,'')   AS texto,
      coalesce(node.fuente_doc,'') AS fuente_doc,
      c.contract_id       AS contract_id,
      coalesce(c.expediente,'') AS expediente,
      coalesce(c.titulo,'')     AS contrato_titulo,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding})


def search_extractos(embedding: List[float], k: int = K_EXTRACTOS) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('extracto_embedding', $k, $embedding)
    YIELD node, score
    MATCH (c:ContratoRAG)-[:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_EXTRACTO]->(node)
    RETURN
      node.extracto_id    AS extracto_id,
      coalesce(node.tipo,'')       AS tipo,
      coalesce(node.texto,'')      AS texto,
      coalesce(node.fuente_doc,'') AS fuente_doc,
      c.contract_id       AS contract_id,
      coalesce(c.expediente,'') AS expediente,
      coalesce(c.titulo,'')     AS contrato_titulo,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding})

def find_reference_ppt_contract(question_embedding,
                                top_k: int = 10):
    """
    Usa el embedding de la pregunta para buscar contratos base con PPT.
    Devuelve el mejor candidato o None si no encuentra nada útil.
    """
    # Reutilizamos search_contratos, pero nos aseguramos de que el contrato tenga un DocumentoRAG PPT
    candidatos = search_contratos(question_embedding, top_k)
    if not candidatos:
        return None
    
    # Filtrar a aquellos que tengan PPT asociado
    # (usamos una consulta rápida para verificar si existe :DocumentoRAG tipo_doc='PPT')
    for c in candidatos:
        contract_id = c.get("contract_id")
        if not contract_id:
            continue
        rows = neo4j_query(
            """
            MATCH (c:ContratoRAG {contract_id: $cid})-[:TIENE_DOC {tipo_doc:'PPT'}]->(d:DocumentoRAG)
            RETURN d.doc_id AS doc_id
            LIMIT 1
            """,
            {"cid": contract_id}
        )
        if rows:
            c["doc_id"] = rows[0]["doc_id"]
            return c  # devolvemos el primer candidato válido
    
    return None

def get_ppt_reference_data(contract_id: str):
    """
    Devuelve datos de referencia para el PPT de un contrato:
    - contrato: título, expediente
    - capítulos: lista de dicts con heading, orden, texto
    - extractos: lista de dicts con tipo, texto
    Agrupa también extractos por tipo.
    """
    # Capítulos ordenados
    caps_rows = neo4j_query(
        """
        MATCH (c:ContratoRAG {contract_id: $cid})-[:TIENE_DOC {tipo_doc:'PPT'}]->(d:DocumentoRAG)
        OPTIONAL MATCH (d)-[:TIENE_CAPITULO]->(cap:Capitulo)
        RETURN
          c.titulo     AS contrato_titulo,
          c.expediente AS expediente,
          d.doc_id     AS doc_id,
          cap.heading  AS heading,
          cap.orden    AS orden,
          cap.texto    AS texto
        ORDER BY cap.orden ASC
        """,
        {"cid": contract_id}
    )
    
    if not caps_rows:
        return None
    
    contrato_titulo = caps_rows[0]["contrato_titulo"]
    expediente      = caps_rows[0]["expediente"]
    doc_id          = caps_rows[0]["doc_id"]
    
    capitulos = [
        {
            "heading": row["heading"],
            "orden":   row["orden"],
            "texto":   row["texto"]
        }
        for row in caps_rows
        if row["heading"] is not None
    ]
    
    # Extractos
    ext_rows = neo4j_query(
        """
        MATCH (c:ContratoRAG {contract_id: $cid})-[:TIENE_DOC {tipo_doc:'PPT'}]->(d:DocumentoRAG)
        OPTIONAL MATCH (d)-[:TIENE_EXTRACTO]->(e:Extracto)
        RETURN e.tipo AS tipo, e.texto AS texto
        """,
        {"cid": contract_id}
    )
    
    extractos = [
        {"tipo": row["tipo"], "texto": row["texto"]}
        for row in ext_rows
        if row["tipo"] is not None and row["texto"]
    ]
    
    # Agrupamos extractos por tipo
    ext_por_tipo = defaultdict(list)
    for e in extractos:
        ext_por_tipo[e["tipo"]].append(e["texto"])
    
    # limitamos un poco cada tipo para no reventar el prompt
    for t in ext_por_tipo:
        ext_por_tipo[t] = ext_por_tipo[t][:5]
    
    return {
        "contract_id": contract_id,
        "expediente": expediente,
        "contrato_titulo": contrato_titulo,
        "doc_id": doc_id,
        "capitulos": capitulos,
        "extractos": extractos,
        "extractos_por_tipo": ext_por_tipo
    }

def build_ppt_generation_prompt(user_request: str,
                                ref_data: dict) -> tuple[str, str]:
    """
    Devuelve (system_msg, user_msg) para pedir al LLM que redacte un nuevo PPT
    usando un pliego de referencia (ref_data) y la petición del usuario.
    """
    # Cabecera con datos del pliego base
    contrato_titulo = ref_data["contrato_titulo"]
    expediente      = ref_data["expediente"]
    caps            = ref_data["capitulos"]
    ext_por_tipo    = ref_data["extractos_por_tipo"]
    
    # Sección de capítulos de referencia (solo headings + pequeño snippet)
    caps_lines = []
    for c in caps:
        if not c["heading"]:
            continue
        snippet = textwrap.shorten(c.get("texto") or "", width=200, placeholder=" […]")
        caps_lines.append(f"- {c['orden']}. {c['heading']}\n  {snippet}")
    caps_text = "\n".join(caps_lines[:15])  # por si el pliego es enorme
    
    # Sección de extractos por tipo
    ext_lines = []
    for t, textos in ext_por_tipo.items():
        ext_lines.append(f"**{t}**:")
        for txt in textos:
            sn = textwrap.shorten(txt, width=220, placeholder=" […]")
            ext_lines.append(f"  - {sn}")
    ext_text = "\n".join(ext_lines) if ext_lines else "No se han detectado extractos específicos."
    
    system_msg = (
        "Eres un redactor experto en Pliegos de Prescripciones Técnicas (PPT) de contratos públicos "
        "de servicios, obras y suministros. Conoces la normativa española de contratación pública, "
        "pero no eres abogado: tu objetivo es redactar un pliego técnicamente sólido, claro y orientado "
        "a la buena ejecución del contrato, tomando como referencia pliegos existentes pero sin copiar "
        "texto literal.\n"
    )
    
    user_msg = f"""
Se te pide redactar un **nuevo Pliego de Prescripciones Técnicas (PPT)**.

1. **Encargo del usuario (objeto y contexto)**  
{user_request}

2. **Pliego de referencia en el que debes inspirarte**  
- Expediente de referencia: {expediente}  
- Título del contrato de referencia: {contrato_titulo}

3. **Estructura de capítulos del pliego de referencia (no la copies literal, úsala como guía):**
{caps_text}

4. **Extractos relevantes del pliego de referencia** (puedes usarlos para diseñar el nuevo PPT):
{ext_text}

### Instrucciones para redactar el nuevo PPT

- Elabora un Pliego de Prescripciones Técnicas completo y coherente con el encargo del usuario.
- Utiliza una estructura de capítulos de primer nivel numerados (1., 2., 3., …, y Anexos si procede).
- Puedes reutilizar la estructura de capítulos del pliego de referencia, manteniendo títulos y adaptando contenidos.
- Integra la normativa y los requisitos de solvencia, criterios de adjudicación, etc., tomando como base los extractos, pero sin copiar texto literal.
- Explica con suficiente detalle el objeto, alcance, condiciones técnicas, niveles de servicio, controles de calidad, responsabilidades del contratista, etc.
- El texto debe estar en castellano, en tono profesional y claro.
- Devuelve SOLO el texto del nuevo pliego en formato Markdown, usando encabezados de nivel 2 para los capítulos (por ejemplo: `## 1. Objeto del contrato`, `## 2. Alcance de los trabajos`, etc.), sin comentarios adicionales.
"""
    return system_msg.strip(), user_msg.strip()

def generate_ppt_from_graph(user_request: str):
  """
  Genera un nuevo Pliego de Prescripciones Técnicas a partir de:
  - la petición del usuario (user_request),
  - el contrato y PPT de referencia más parecido en el grafo,
  - sus capítulos y extractos.

  Devuelve un dict con:
    - 'pliego_text'
    - 'referencia_contrato'
    - 'capitulos'
    - 'extractos'
  """
  # 1) Embedding de la petición
  emb = embed_text(user_request)
  if emb is None or not emb:
      return {"error": "No se pudo calcular el embedding de la petición."}
  
  # 2) Buscar contrato de referencia con PPT
  ref_contrato = find_reference_ppt_contract(emb, top_k=10)
  if not ref_contrato:
      return {"error": "No se ha encontrado ningún pliego de prescripciones técnicas de referencia adecuado."}
  
  contract_id = ref_contrato["contract_id"]
  
  # 3) Obtener datos de referencia (capítulos + extractos)
  ref_data = get_ppt_reference_data(contract_id)
  if ref_data is None:
      return {"error": f"El contrato {contract_id} no tiene un PPT con capítulos en el grafo."}
  
  # 4) Construir prompt
  system_msg, user_msg = build_ppt_generation_prompt(user_request, ref_data)
  
  # 5) Llamar al LLM (sin streaming aquí; se puede adaptar si quieres)
  resp = llm_client.chat.completions.create(
      model = LLM_MODEL,
      messages = [
          {"role": "system", "content": system_msg},
          {"role": "user",   "content": user_msg}
      ],
      max_tokens = 3000,
      temperature = 0.4,
  )
  pliego_text = resp.choices[0].message.content.strip()
  
  return {
      "pliego_text": pliego_text,
      "referencia_contrato": ref_data,
      "contrato_embedding_source": ref_contrato,
  }

async def handle_generate_ppt(question: str):
    # Mostrar que estamos en modo generación
    await cl.Message("He detectado que quieres **generar un Pliego de Prescripciones Técnicas**. Buscando pliegos de referencia…").send()
    
    emb = await cl.make_async(embed_text)(question)
    if not emb:
        await cl.Message("No he podido calcular el embedding de tu petición. Inténtalo de nuevo reformulando el objeto.").send()
        return
    
    ref_contrato = find_reference_ppt_contract(emb, top_k=10)
    if not ref_contrato:
        await cl.Message("No he encontrado ningún pliego de prescripciones técnicas similar en el grafo.").send()
        return
    
    contract_id = ref_contrato["contract_id"]
    ref_data = get_ppt_reference_data(contract_id)
    if ref_data is None:
        await cl.Message(f"He encontrado el contrato {contract_id}, pero no he podido recuperar su PPT de referencia.").send()
        return
    
    system_msg, user_msg = build_ppt_generation_prompt(question, ref_data)
    
    # Preparamos streaming del pliego
    msg = cl.Message(content="")
    await msg.send()
    
    # Streaming del LLM
    resp = llm_client.chat.completions.create(
        model = LLM_MODEL,
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg}
        ],
        max_tokens = 3000,
        temperature = 0.4,
        stream = True
    )
    
    pliego_chunks = []
    for chunk in resp:
        delta = chunk.choices[0].message.get("content") or ""
        if delta:
            pliego_chunks.append(delta)
            await msg.stream_token(delta)
    
    pliego_text = "".join(pliego_chunks).strip()
    
    # Enviar evidencias específicas del pliego base
    evidencia_md = build_evidence_markdown(
        contratos=[{
            "expediente": ref_data["expediente"],
            "titulo":     ref_data["contrato_titulo"],
            "adjudicataria_nombre": ref_contrato.get("nombre"),
            "importe_adjudicado":   ref_contrato.get("importe_adjudicado")
        }],
        capitulos=[{
            "heading":   c["heading"],
            "expediente": ref_data["expediente"],
            "fuente_doc": "PPT",
            "texto":     c["texto"]
        } for c in ref_data["capitulos"]],
        extractos=[{"tipo": t, "expediente": ref_data["expediente"], "fuente_doc": "PPT", "texto": txt}
                   for t, lista in ref_data["extractos_por_tipo"].items()
                   for txt in lista]
    )
    await cl.Message(content=evidencia_md).send()

# ==========================
# CONSTRUCCIÓN DE CONTEXTO
# ==========================

def build_context(question: str,
                  contratos: List[Dict[str, Any]],
                  capitulos: List[Dict[str, Any]],
                  extractos: List[Dict[str, Any]]) -> str:
    parts = []

    parts.append("=== PREGUNTA DEL USUARIO ===")
    parts.append(question.strip())

    if contratos:
        parts.append("\n=== CONTRATOS RELEVANTES ===")
        for c in contratos:
            snippet = textwrap.shorten(c.get("abstract", "") or "", width=450, placeholder=" [...]")
            parts.append(
                f"- Expediente: {c.get('expediente') or 'N/D'} | Estado: {c.get('estado') or 'N/D'}\n"
                f"  Título: {c.get('titulo') or 'N/D'}\n"
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
            snippet = textwrap.shorten(cap.get("texto", "") or "", width=600, placeholder=" [...]")
            parts.append(
                f"- Contrato {cap.get('expediente') or 'N/D'} | Capítulo {cap.get('heading') or 'N/D'} "
                f"({cap.get('fuente_doc') or ''})\n"
                f"  Texto: {snippet}"
            )

    if extractos:
        parts.append("\n=== EXTRACTOS RELEVANTES (normativa, solvencia, garantías, criterios, etc.) ===")
        for ex in extractos:
            snippet = textwrap.shorten(ex.get("texto", "") or "", width=450, placeholder=" [...]")
            parts.append(
                f"- Contrato {ex.get('expediente') or 'N/D'} | Tipo: {ex.get('tipo') or 'N/D'} "
                f"({ex.get('fuente_doc') or ''})\n"
                f"  Texto: {snippet}"
            )

    parts.append(
        "\n=== INSTRUCCIONES PARA EL MODELO ===\n"
        "Responde a la pregunta del usuario basándote EXCLUSIVAMENTE en la información anterior "
        "(contratos, capítulos y extractos relevantes).\n"
        "- Si necesitas citar un contrato, menciona su expediente y una breve descripción.\n"
        "- Puedes mencionar la adjudicataria y los importes adjudicados cuando sea relevante.\n"
        "- Si no hay información suficiente, dilo explícitamente.\n"
        "- No inventes datos que no aparezcan en el contexto.\n"
        "- Responde en castellano, con un tono claro, directo y orientado a ayudar a técnicos de contratación."
    )

    return "\n".join(parts)

def build_evidence_markdown(contratos, capitulos, extractos) -> str:
    lines = []
    lines.append("### Evidencias utilizadas")

    if contratos:
        lines.append("\n**Contratos relevantes**")
        for c in contratos:
            lines.append(
                f"- Expediente **{c.get('expediente') or 'N/D'}** · "
                f"Título: {c.get('titulo') or 'N/D'} · "
                f"Adjudicataria: {c.get('adjudicataria_nombre') or 'N/D'} "
                f"(importe adjudicado: {c.get('importe_adjudicado') or 'N/D'})"
            )

    if capitulos:
        lines.append("\n**Capítulos relevantes**")
        for cap in capitulos:
            heading = cap.get("heading") or "N/D"
            expediente = cap.get("expediente") or "N/D"
            fuente = cap.get("fuente_doc") or ""
            snippet = textwrap.shorten(cap.get("texto", "") or "", width=200, placeholder=" [...]")
            lines.append(
                f"- Contrato **{expediente}**, capítulo _{heading}_ ({fuente}): {snippet}"
            )

    if extractos:
        lines.append("\n**Extractos relevantes**")
        for ex in extractos:
            tipo = ex.get("tipo") or "N/D"
            expediente = ex.get("expediente") or "N/D"
            fuente = ex.get("fuente_doc") or ""
            snippet = textwrap.shorten(ex.get("texto", "") or "", width=200, placeholder=" [...]")
            lines.append(
                f"- Contrato **{expediente}**, tipo _{tipo}_ ({fuente}): {snippet}"
            )

    return "\n".join(lines)


# ==========================
# LLM CHAT CON HISTORIAL
# ==========================

def chat_with_llm(context: str, history: List[Dict[str, str]]) -> str:
    """
    history: lista de dicts {"role": "user"/"assistant", "content": "..."}
    """
    messages: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Eres un asistente experto en contratación pública para la Diputación Provincial de Huelva. "
                "Usas un grafo RAG de contratos y pliegos para responder. No inventas datos y solo respondes "
                "con la información proporcionada en el contexto o inferencias directamente relacionadas con él."
            ),
        }
    ]

    # Añadimos los últimos turnos de historial (recortado)
    if history:
        # nos quedamos con los últimos MAX_HISTORY_TURNS mensajes
        history_trimmed = history[-MAX_HISTORY_TURNS:]
        messages.extend(history_trimmed)

    # Contexto actual como último mensaje del usuario
    messages.append({"role": "user", "content": context})

    resp = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ==========================
# CHAINLIT HANDLERS
# ==========================

@cl.on_chat_start
async def on_chat_start():
    # Inicializamos historial por sesión
    cl.user_session.set("history", [])
    await cl.Message(
        content=(
            "Hola, soy el asistente RAG de contratos de la Diputación Provincial de Huelva.\n\n"
            "Puedes preguntarme, por ejemplo:\n"
            "- Qué normativa se cita más en los pliegos de la DPH.\n"
            "- Cómo se regula la solvencia técnica en los contratos de mantenimiento.\n"
            "- Qué cláusulas sociales o ambientales aparecen en determinados expedientes.\n"
            "Intentaré combinar el grafo y los embeddings para darte una respuesta útil."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    question = message.content.strip()

    lower_q = question.lower()
    
    # Detección muy simple: generar PPT
    if ("pliego de prescripciones técnicas" in lower_q or "pliego tecnico" in lower_q or "ppt" in lower_q) and any(
        kw in lower_q for kw in ["genera", "generar", "redacta", "redáctame", "elabora", "borrador"]
    ):
        await handle_generate_ppt(question)
        return

    if not question:
        await cl.Message(content="No he recibido ninguna pregunta. Prueba a escribir algo.").send()
        return

    # Recuperar historial de la sesión
    history = cl.user_session.get("history", [])

    # Mensaje de "pensando..."
    thinking_msg = await cl.Message(
        content="Pensando sobre tu pregunta, consultando el grafo y los pliegos..."
    ).send()

    try:
        # 1) Embedding de la pregunta
        embedding = await cl.make_async(embed_text)(question)
        if not embedding:
            thinking_msg.content = "No he podido generar el embedding de la pregunta."
            await thinking_msg.update()
            return

        # 2) Búsquedas en el grafo
        contratos = await cl.make_async(search_contratos)(embedding, K_CONTRATOS)
        capitulos = await cl.make_async(search_capitulos)(embedding, K_CAPITULOS)
        extractos = await cl.make_async(search_extractos)(embedding, K_EXTRACTOS)

        # 3) Construir contexto RAG
        context = build_context(question, contratos, capitulos, extractos)

        # 4) Construir mensajes para el LLM con historial
        messages_llm = [
            {
                "role": "system",
                "content": (
                    "Eres un asistente experto en contratación pública para la Diputación Provincial de Huelva. "
                    "Usas un grafo RAG de contratos y pliegos para responder. No inventas datos y solo respondes "
                    "con la información proporcionada en el contexto o inferencias razonables a partir de él."
                ),
            }
        ]

        # Añadimos historial recortado
        if history:
            history_trimmed = history[-MAX_HISTORY_TURNS:]
            messages_llm.extend(history_trimmed)

        # Añadimos el contexto actual como último mensaje del usuario
        messages_llm.append({"role": "user", "content": context})

        # 5) Preparar mensaje de respuesta en streaming
        reply_msg = cl.Message(content="")
        await reply_msg.send()

        # 6) Llamada al LLM con streaming
        stream = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages_llm,
            temperature=0.3,
            stream=True,
        )

        full_answer = []

        # Actualizamos el mensaje de "pensando..." antes de empezar a escribir
        thinking_msg.content = "Generando respuesta..."
        await thinking_msg.update()

        for chunk in stream:
            delta = chunk.choices[0].delta
            token = delta.content or ""
            if token:
                full_answer.append(token)
                await reply_msg.stream_token(token)

        await reply_msg.update()

        answer = "".join(full_answer).strip()

        # 7) Actualizar historial (pregunta + respuesta)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        if len(history) > MAX_HISTORY_TURNS:
            history = history[-MAX_HISTORY_TURNS:]
        cl.user_session.set("history", history)

        # Opcional: convertir mensaje de "pensando..." en marca discreta
        thinking_msg.content = "Respuesta generada (RAG)."
        await thinking_msg.update()

        # 8) Enviar evidencias como segundo mensaje
        #evidence_md = build_evidence_markdown(contratos, capitulos, extractos)
        #if evidence_md:
        #    await cl.Message(content=evidence_md).send()

    except Exception as e:
        print(f"[ERROR] {e}")
        thinking_msg.content = (
            "Ha ocurrido un error al procesar la consulta. Revisa los logs del servidor."
        )
        await thinking_msg.update()
