import os
import json
import textwrap
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

import chainlit as cl
from neo4j import GraphDatabase
from openai import OpenAI

# ============================================================
#  Opcional: LangChain + Neo4jGraph para más flexibilidad
# ============================================================

try:
    from langchain_community.graphs import Neo4jGraph
    HAS_LANGCHAIN = True
except ImportError:
    Neo4jGraph = None
    HAS_LANGCHAIN = False


# ============================================================
#  CONFIGURACIÓN
# ============================================================

# Neo4j (grafo RAG)
NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://49.13.151.49:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "root_tech_2019")
NEO4J_DB       = os.getenv("NEO4J_DB", "huelva")

# LLM (chat) – servidor OpenAI-compatible en 8002
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.71.46.94:8002/v1")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "dummy-key")
LLM_MODEL    = os.getenv("LLM_MODEL", "llm")

# Embeddings – servidor OpenAI-compatible en 8003
EMB_BASE_URL = os.getenv("EMB_BASE_URL", "http://100.71.46.94:8003/v1")
EMB_API_KEY  = os.getenv("EMB_API_KEY", "dummy-key")
EMB_MODEL    = os.getenv("EMB_MODEL", "embedding")
EMB_DIM      = int(os.getenv("EMB_DIM", "1024"))

# Top-K resultados por tipo
K_CONTRATOS = 5
K_CAPITULOS = 10
K_EXTRACTOS = 30

# Cuántos mensajes de historial mantener (user+assistant)
MAX_HISTORY_TURNS = 6  # 3 turnos completos

# Longitud máxima del label de los botones de sugerencias
SUGGESTION_LABEL_MAX_CHARS = 100


# ============================================================
#  CLIENTES GLOBALES
# ============================================================

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

llm_client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
emb_client = OpenAI(base_url=EMB_BASE_URL, api_key=EMB_API_KEY)

graph: Optional["Neo4jGraph"] = None
if HAS_LANGCHAIN:
    try:
        graph = Neo4jGraph(
            url=NEO4J_URI,
            username=NEO4J_USER,
            password=NEO4J_PASSWORD,
            database=NEO4J_DB,
        )
        print("[INFO] Neo4jGraph (LangChain) inicializado correctamente.")
    except Exception as e:
        print(f"[WARN] No se pudo inicializar Neo4jGraph de LangChain: {e}")
        graph = None
else:
    print("[INFO] LangChain no instalado; se usará solo el driver oficial de Neo4j.")


# ============================================================
#  HELPERS: NEO4J / LANGCHAIN
# ============================================================

def neo4j_query(cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if params is None:
        params = {}

    if graph is not None:
        return graph.query(cypher, params)

    with driver.session(database=NEO4J_DB) as session:
        result = session.run(cypher, **params)
        return [record.data() for record in result]


# ============================================================
#  HELPERS: EMBEDDINGS
# ============================================================

def embed_text(text: str, max_chars: int = 4000) -> List[float]:
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


# ============================================================
#  VECTOR SEARCH EN NEO4J
# ============================================================

def search_contratos(embedding: List[float], k: int = K_CONTRATOS) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('contrato_rag_embedding', $k, $embedding)
    YIELD node, score
    OPTIONAL MATCH (e:EmpresaRAG)-[:ADJUDICATARIA_RAG]->(node)
    RETURN
      node.contract_id               AS contract_id,
      coalesce(node.expediente,'')   AS expediente,
      coalesce(node.titulo,'')       AS titulo,
      coalesce(node.abstract,'')     AS abstract,
      coalesce(node.estado,'')       AS estado,
      coalesce(node.cpv_principal,'') AS cpv_principal,
      e.nif                          AS adjudicataria_nif,
      e.nombre                       AS adjudicataria_nombre,
      node.presupuesto_sin_iva       AS presupuesto_sin_iva,
      node.valor_estimado            AS valor_estimado,
      node.importe_adjudicado        AS importe_adjudicado,
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
      node.cap_id               AS cap_id,
      coalesce(node.heading,'') AS heading,
      coalesce(node.texto,'')   AS texto,
      coalesce(node.fuente_doc,'') AS fuente_doc,
      c.contract_id             AS contract_id,
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
      node.extracto_id          AS extracto_id,
      coalesce(node.tipo,'')    AS tipo,
      coalesce(node.texto,'')   AS texto,
      coalesce(node.fuente_doc,'') AS fuente_doc,
      c.contract_id             AS contract_id,
      coalesce(c.expediente,'') AS expediente,
      coalesce(c.titulo,'')     AS contrato_titulo,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding})


# ============================================================
#  BÚSQUEDA DE PLIEGO DE REFERENCIA (PPT)
# ============================================================

def find_reference_ppt_contract(question_embedding: List[float],
                                top_k: int = 10) -> Optional[Dict[str, Any]]:
    candidatos = search_contratos(question_embedding, top_k)
    if not candidatos:
        return None

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
            return c

    return None


def get_ppt_reference_data(contract_id: str) -> Optional[Dict[str, Any]]:
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
            "texto":   row["texto"],
        }
        for row in caps_rows
        if row["heading"] is not None
    ]

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

    ext_por_tipo: Dict[str, List[str]] = defaultdict(list)
    for e in extractos:
        ext_por_tipo[e["tipo"]].append(e["texto"])

    for t in ext_por_tipo:
        ext_por_tipo[t] = ext_por_tipo[t][:5]

    return {
        "contract_id": contract_id,
        "expediente": expediente,
        "contrato_titulo": contrato_titulo,
        "doc_id": doc_id,
        "capitulos": capitulos,
        "extractos": extractos,
        "extractos_por_tipo": ext_por_tipo,
    }


# ============================================================
#  PROMPT PARA GENERAR UN PPT
# ============================================================

def build_ppt_generation_prompt(
    user_request: str,
    ref_data: Dict[str, Any],
    extra_caps: Optional[List[Dict[str, Any]]] = None,
    extra_extractos: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    contrato_titulo = ref_data["contrato_titulo"]
    expediente      = ref_data["expediente"]
    caps_ref        = ref_data["capitulos"]
    ext_por_tipo    = ref_data["extractos_por_tipo"]

    caps_lines = []
    for c in caps_ref:
        if not c["heading"]:
            continue
        snippet = textwrap.shorten(c.get("texto") or "", width=200, placeholder=" […]")
        caps_lines.append(f"- {c.get('orden', '')}. {c['heading']}\n  {snippet}")
    caps_text_ref = "\n".join(caps_lines[:15])

    ext_lines_ref = []
    for t, textos in ext_por_tipo.items():
        ext_lines_ref.append(f"**{t}**:")
        for txt in textos:
            sn = textwrap.shorten(txt, width=220, placeholder=" […]")
            ext_lines_ref.append(f"  - {sn}")
    ext_text_ref = "\n".join(ext_lines_ref) if ext_lines_ref else "No se han detectado extractos específicos."

    extra_caps_text = ""
    if extra_caps:
        caps_by_exp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for cap in extra_caps:
            exp = cap.get("expediente") or "N/D"
            caps_by_exp[exp].append(cap)

        lines = []
        lines.append("Se han encontrado también capítulos relevantes en otros contratos:")
        total_caps = 0
        for exp, caps in caps_by_exp.items():
            lines.append(f"- Expediente {exp}:")
            for c in caps[:3]:
                snippet = textwrap.shorten(c.get("texto") or "", width=160, placeholder=" […]")
                heading = c.get("heading") or "N/D"
                fuente  = c.get("fuente_doc") or ""
                lines.append(f"    · {heading} ({fuente}): {snippet}")
                total_caps += 1
                if total_caps >= 15:
                    break
            if total_caps >= 15:
                break
        extra_caps_text = "\n".join(lines)

    extra_ext_text = ""
    if extra_extractos:
        ext_by_tipo_global: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for ex in extra_extractos:
            t = ex.get("tipo") or "OTRO"
            ext_by_tipo_global[t].append(ex)

        lines = []
        lines.append(
            "Además, se han encontrado extractos relevantes (normativa, solvencia, criterios, garantías, etc.) "
            "en otros contratos distintos al de referencia:"
        )
        for t, lst in ext_by_tipo_global.items():
            lines.append(f"- Tipo **{t}**:")
            for ex in lst[:3]:
                exp = ex.get("expediente") or "N/D"
                fuente = ex.get("fuente_doc") or ""
                snippet = textwrap.shorten(ex.get("texto") or "", width=180, placeholder=" […]")
                lines.append(f"    · Expediente {exp} ({fuente}): {snippet}")
        extra_ext_text = "\n".join(lines)

    system_msg = (
        "Eres un redactor experto en Pliegos de Prescripciones Técnicas (PPT) de contratos públicos "
        "de servicios, obras y suministros. Conoces la normativa española de contratación pública, "
        "pero no eres abogado: tu objetivo es redactar un pliego técnicamente sólido, claro y orientado "
        "a la buena ejecución del contrato, tomando como referencia pliegos existentes pero SIN copiar "
        "texto literal.\n"
        "Debes usar la información de referencia como inspiración estructural y de contenido, "
        "adaptándola al nuevo objeto indicado por el usuario."
    )

    user_msg = f"""
Se te pide redactar un **nuevo Pliego de Prescripciones Técnicas (PPT)**.

1. **Encargo del usuario (objeto y contexto)**  
{user_request}

2. **Pliego de referencia principal en el que debes inspirarte**  
- Expediente de referencia: {expediente}  
- Título del contrato de referencia: {contrato_titulo}

3. **Estructura de capítulos y contenido resumido del pliego de referencia**  
(No debes copiar literal, úsalo como guía de estructura y contenido técnico):

{caps_text_ref}

4. **Extractos relevantes del pliego de referencia**  
(Pueden aportarte normativa, solvencia, criterios, garantías, etc.):

{ext_text_ref}

5. **Capítulos relevantes de OTROS contratos (contexto global)**

{extra_caps_text or 'No se han encontrado capítulos adicionales relevantes.'}

6. **Extractos relevantes de OTROS contratos (contexto global)**

{extra_ext_text or 'No se han encontrado extractos adicionales relevantes.'}

### Instrucciones para redactar el nuevo PPT

- Elabora un Pliego de Prescripciones Técnicas completo y coherente con el encargo del usuario.
- Sólo el pliego, no hagas referencia a adjudicaciones de los contratos de referencia.
- Utiliza una estructura de capítulos de primer nivel numerados (1., 2., 3., …, y Anexos si procede).
- Debes reutilizar la estructura de capítulos del pliego de referencia, adaptando títulos y contenidos al nuevo objeto.
- Integra la normativa, solvencia, criterios de adjudicación, garantías, etc. usando los extractos como inspiración, pero SIN copiar frases textuales.
- Explica con suficiente detalle el objeto, alcance, condiciones técnicas, niveles de servicio, controles de calidad, responsabilidades del contratista, etc.
- Usa bullets si con eso se comprende mejor el texto.
- El texto debe estar en castellano, en tono profesional, claro y orientado a técnicos de contratación.
- Después de cada capítulo, has de indicar entre paréntesis y en cursiva, recomendaciones para mejorar el capítulo.
- Devuelve SOLO el texto del nuevo pliego en formato Markdown, usando encabezados de nivel 2 para los capítulos
  (por ejemplo: `## 1. Objeto del contrato`, `## 2. Alcance de los trabajos`, etc.), sin comentarios adicionales.
"""
    
    return system_msg.strip(), user_msg.strip()


# ============================================================
#  GENERACIÓN DE PPT USANDO EL GRAFO
# ============================================================

def generate_ppt_from_graph(user_request: str) -> Dict[str, Any]:
    emb = embed_text(user_request)
    if not emb:
        return {"error": "No se pudo calcular el embedding de la petición."}

    ref_contrato = find_reference_ppt_contract(emb, top_k=10)
    if not ref_contrato:
        return {"error": "No se ha encontrado ningún PPT de referencia adecuado."}

    contract_id = ref_contrato["contract_id"]
    ref_data = get_ppt_reference_data(contract_id)
    if ref_data is None:
        return {"error": f"El contrato {contract_id} no tiene PPT con capítulos en el grafo."}

    extra_caps      = search_capitulos(emb, k=K_CAPITULOS * 2)
    extra_extractos = search_extractos(emb, k=K_EXTRACTOS * 2)

    system_msg, user_msg = build_ppt_generation_prompt(
        user_request=user_request,
        ref_data=ref_data,
        extra_caps=extra_caps,
        extra_extractos=extra_extractos,
    )

    resp = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=6000,
        temperature=0.4,
    )
    pliego_text = resp.choices[0].message.content.strip()

    return {
        "pliego_text": pliego_text,
        "referencia_contrato": ref_data,
        "contrato_embedding_source": ref_contrato,
    }


async def handle_generate_ppt(question: str):
    await cl.Message(
        "He detectado que quieres **generar un Pliego de Prescripciones Técnicas**.\n"
        "Buscando pliegos de referencia y contexto relevante en el grafo..."
    ).send()

    emb = await cl.make_async(embed_text)(question)
    if not emb:
        await cl.Message(
            "No he podido calcular el embedding de tu petición. "
            "Intenta describir mejor el objeto del contrato."
        ).send()
        return

    ref_contrato = await cl.make_async(find_reference_ppt_contract)(emb, top_k=10)
    if not ref_contrato:
        await cl.Message(
            "No he encontrado ningún pliego de prescripciones técnicas similar en el grafo."
        ).send()
        return

    contract_id = ref_contrato["contract_id"]
    ref_data = await cl.make_async(get_ppt_reference_data)(contract_id)
    if ref_data is None:
        await cl.Message(
            f"He encontrado el contrato {contract_id}, pero no he podido recuperar su PPT de referencia."
        ).send()
        return

    extra_caps      = await cl.make_async(search_capitulos)(emb, k=K_CAPITULOS * 2)
    extra_extractos = await cl.make_async(search_extractos)(emb, k=K_EXTRACTOS * 2)

    system_msg, user_msg = build_ppt_generation_prompt(
        user_request=question,
        ref_data=ref_data,
        extra_caps=extra_caps,
        extra_extractos=extra_extractos,
    )

    msg = cl.Message(content="")
    await msg.send()

    stream = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=3000,
        temperature=0.1,
        stream=True,
    )

    pliego_chunks: List[str] = []

    for chunk in stream:
        delta = chunk.choices[0].delta
        token = delta.content or ""
        if token:
            pliego_chunks.append(token)
            await msg.stream_token(token)

    await msg.update()
    pliego_text = "".join(pliego_chunks).strip()

    evidencia_md = build_evidence_markdown(
        contratos=[{
            "expediente": ref_data["expediente"],
            "titulo":     ref_data["contrato_titulo"],
            "adjudicataria_nombre": ref_contrato.get("adjudicataria_nombre"),
            "importe_adjudicado":   ref_contrato.get("importe_adjudicado"),
        }],
        capitulos=[{
            "heading":    c["heading"],
            "expediente": ref_data["expediente"],
            "fuente_doc": "PPT",
            "texto":      c["texto"],
        } for c in ref_data["capitulos"]],
        extractos=[
            {
                "tipo":       t,
                "expediente": ref_data["expediente"],
                "fuente_doc": "PPT",
                "texto":      txt,
            }
            for t, lista in ref_data["extractos_por_tipo"].items()
            for txt in lista
        ]
    )

    with cl.Step(name="PPT - Contexto de referencia") as step:
        step.input = question
        step.output = {
            "contrato_referencia": ref_contrato,
            "ref_data": ref_data,
            "extra_caps": extra_caps,
            "extra_extractos": extra_extractos,
            "evidence_md": evidencia_md,
        }

    msg.metadata = {
        "evidence": {
            "markdown": evidencia_md,
            "referencia_contrato": ref_data,
            "contrato_embedding_source": ref_contrato,
            "extra_caps": extra_caps,
            "extra_extractos": extra_extractos,
        }
    }
    await msg.update()


# ============================================================
#  CONSTRUCCIÓN DE CONTEXTO RAG (Q&A)
# ============================================================

def build_context(question: str,
                  contratos: List[Dict[str, Any]],
                  capitulos: List[Dict[str, Any]],
                  extractos: List[Dict[str, Any]]) -> str:
    parts: List[str] = []

    parts.append("=== PREGUNTA DEL USUARIO ===")
    parts.append(question.strip())

    if contratos:
        parts.append("\n=== CONTRATOS RELEVANTES ===")
        for c in contratos:
            snippet = textwrap.shorten(c.get("abstract", "") or "", width=450, placeholder=" […]")
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
            snippet = textwrap.shorten(cap.get("texto", "") or "", width=600, placeholder=" […]")
            parts.append(
                f"- Contrato {cap.get('expediente') or 'N/D'} | Capítulo {cap.get('heading') or 'N/D'} "
                f"({cap.get('fuente_doc') or ''})\n"
                f"  Texto: {snippet}"
            )

    if extractos:
        parts.append("\n=== EXTRACTOS RELEVANTES (normativa, solvencia, garantías, criterios, etc.) ===")
        for ex in extractos:
            snippet = textwrap.shorten(ex.get("texto", "") or "", width=450, placeholder=" […]")
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
        "- Responde en castellano, con un tono claro, directo y orientado a ayudar a técnicos de contratación.\n"
        "- Responde de manera concisa, para ahorrar tokens."
    )

    return "\n".join(parts)


def build_evidence_markdown(contratos, capitulos, extractos) -> str:
    lines: List[str] = []
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
            snippet = textwrap.shorten(cap.get("texto", "") or "", width=200, placeholder=" […]")
            lines.append(
                f"- Contrato **{expediente}**, capítulo _{heading}_ ({fuente}): {snippet}"
            )

    if extractos:
        lines.append("\n**Extractos relevantes**")
        for ex in extractos:
            tipo = ex.get("tipo") or "N/D"
            expediente = ex.get("expediente") or "N/D"
            fuente = ex.get("fuente_doc") or ""
            snippet = textwrap.shorten(ex.get("texto", "") or "", width=200, placeholder=" […]")
            lines.append(
                f"- Contrato **{expediente}**, tipo _{tipo}_ ({fuente}): {snippet}"
            )

    return "\n".join(lines)


# ============================================================
#  SUGERENCIAS DE PREGUNTAS DE SEGUIMIENTO
# ============================================================

def generate_follow_up_questions(
    question: str,
    answer: str,
    max_suggestions: int = 3,
) -> List[str]:
    """
    Usa el LLM para proponer preguntas de seguimiento.
    Devuelve una lista de strings.
    """
    prompt = f"""
Has respondido a una pregunta sobre contratación pública.

Pregunta del usuario:
\"\"\"{question}\"\"\"

Tu respuesta:
\"\"\"{answer}\"\"\"

Genera entre 1 y {max_suggestions} PREGUNTAS DE SEGUIMIENTO útiles que el usuario
podría hacer a continuación para profundizar o concretar más la información
(relacionadas con contratos, normativa, criterios, adjudicatarios, etc.).

Devuelve EXCLUSIVAMENTE un JSON con esta forma:

{{
  "suggestions": [
    "Pregunta de seguimiento 1",
    "Pregunta de seguimiento 2"
  ]
}}
"""

    resp = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un asistente que propone preguntas de seguimiento breves y útiles "
                    "a partir de una respuesta previa sobre contratación pública."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=256,
    )

    text = resp.choices[0].message.content.strip()
    suggestions: List[str] = []

    try:
        data = json.loads(text)
        raw = data.get("suggestions", [])
        if isinstance(raw, list):
            suggestions = [s for s in raw if isinstance(s, str)]
    except Exception:
        # Fallback: líneas de texto
        lines = [ln.strip("-• ").strip() for ln in text.splitlines() if ln.strip()]
        suggestions = lines

    # Normalizar: quitar duplicados, evitar repetir exactamente la pregunta original
    uniq: List[str] = []
    seen = set()
    for s in suggestions:
        s_clean = " ".join(s.split())
        if not s_clean:
            continue
        if s_clean.lower() == question.strip().lower():
            continue
        if s_clean.lower() in seen:
            continue
        seen.add(s_clean.lower())
        uniq.append(s_clean)
        if len(uniq) >= max_suggestions:
            break

    return uniq


# ============================================================
#  CHAINLIT HANDLERS
# ============================================================

@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("history", [])
    await cl.Message(
        content=(
            "Hola, soy el asistente RAG de contratos de la Diputación Provincial de Huelva.\n\n"
            "Puedes preguntarme, por ejemplo:\n"
            "- Qué normativa se cita más en los pliegos de la DPH.\n"
            "- Cómo se regula la solvencia técnica en los contratos de mantenimiento.\n"
            "- Qué cláusulas sociales o ambientales aparecen en determinados expedientes.\n"
            "- Qué adjudicatarios han ganado determinados contratos y por qué importe.\n\n"
            "También puedo ayudarte a **generar un borrador de Pliego de Prescripciones Técnicas (PPT)** "
            "a partir de pliegos existentes."
        )
    ).send()


@cl.action_callback("follow_up_question")
async def on_follow_up_question(action: cl.Action):
    """
    Cuando el usuario pulsa uno de los botones de sugerencia,
    se envía automáticamente esa pregunta y se reutiliza on_message.
    """
    payload = action.payload or {}
    follow_up = payload.get("question")
    if not follow_up:
        return

    # Mostramos la pregunta seleccionada como nuevo mensaje del usuario
    await cl.Message(content=follow_up).send()
    # Reutilizamos la lógica principal
    await on_message(cl.Message(content=follow_up))


@cl.on_message
async def on_message(message: cl.Message):
    # Texto de la pregunta
    question = (message.content or "").strip()
    lower_q = question.lower()

    # 1) Detección de intención: generación de PPT
    if (
        "pliego de prescripciones técnicas" in lower_q
        or "pliego técnico" in lower_q
        or "ppt" in lower_q
    ) and any(
        kw in lower_q
        for kw in ["genera", "generar", "redacta", "redáctame", "elabora", "borrador", "elaborar", "redactar", "genérame", "elabórame"]
    ):
        await handle_generate_ppt(question)
        return

    # Si no hay pregunta, avisamos
    if not question:
        await cl.Message(
            content="No he recibido ninguna pregunta. Prueba a escribir algo."
        ).send()
        return

    # 2) Recuperar historial de la sesión
    history: List[Dict[str, str]] = cl.user_session.get("history", [])

    # 3) Mensaje de "pensando..."
    thinking_msg = await cl.Message(
        content="Pensando sobre tu pregunta, consultando el grafo y los pliegos..."
    ).send()

    try:
        # 4) Embedding de la pregunta
        embedding = await cl.make_async(embed_text)(question)
        if not embedding:
            thinking_msg.content = "No he podido generar el embedding de la pregunta."
            await thinking_msg.update()
            return

        # 5) Búsquedas en el grafo (vector search)
        contratos = await cl.make_async(search_contratos)(embedding, K_CONTRATOS)
        capitulos = await cl.make_async(search_capitulos)(embedding, K_CAPITULOS)
        extractos = await cl.make_async(search_extractos)(embedding, K_EXTRACTOS)

        # 6) Evidencias en markdown (NO visibles al usuario, solo para debug/metadata)
        evidence_md = build_evidence_markdown(contratos, capitulos, extractos)

        # 7) Step para ver el contexto RAG en el panel de debug (no se muestra en el chat)
        with cl.Step(name="RAG - Recuperación de contexto") as step:
            step.input = question
            step.output = {
                "contratos": contratos,
                "capitulos": capitulos,
                "extractos": extractos,
                "evidence_md": evidence_md,
            }

        # 8) Construir contexto RAG que se pasa al LLM
        context = build_context(question, contratos, capitulos, extractos)

        # 9) Construir mensajes para el LLM con historial
        messages_llm: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Eres un asistente experto en contratación pública para la Diputación Provincial de Huelva. "
                    "Usas un grafo RAG de contratos y pliegos para responder. No inventas datos y solo respondes "
                    "con la información proporcionada en el contexto o inferencias razonables directamente "
                    "relacionadas con él."
                ),
            }
        ]

        if history:
            history_trimmed = history[-MAX_HISTORY_TURNS:]
            messages_llm.extend(history_trimmed)

        messages_llm.append({"role": "user", "content": context})

        # 10) Preparar mensaje de respuesta en streaming
        reply_msg = cl.Message(content="")
        await reply_msg.send()

        # 11) Llamada al LLM con streaming
        stream = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages_llm,
            temperature=0.3,
            stream=True,
        )

        full_answer: List[str] = []

        thinking_msg.content = "Generando respuesta..."
        await thinking_msg.update()

        for chunk in stream:
            delta = chunk.choices[0].delta
            token = delta.content or ""
            if token:
                full_answer.append(token)
                await reply_msg.stream_token(token)

        # Finalizar el mensaje de respuesta (contenido completo ya en pantalla)
        await reply_msg.update()
        answer = "".join(full_answer).strip()

        # 12) Actualizar historial (pregunta + respuesta)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        if len(history) > MAX_HISTORY_TURNS:
            history = history[-MAX_HISTORY_TURNS:]
        cl.user_session.set("history", history)

        # 13) Generar sugerencias de seguimiento (botones pequeños)
        suggestions = await cl.make_async(generate_follow_up_questions)(
            question, answer, max_suggestions=3
        )

        actions: List[cl.Action] = []
        for s in suggestions:
            label = (
                s
                if len(s) <= SUGGESTION_LABEL_MAX_CHARS
                else s[: SUGGESTION_LABEL_MAX_CHARS - 1] + "…"
            )
            actions.append(
                cl.Action(
                    name="follow_up_question",
                    label=label,           # etiqueta corta → botón pequeño
                    tooltip=s,             # texto completo en tooltip
                    payload={"question": s},
                    icon="help-circle",
                )
            )

        # 14) Adjuntar evidencias y acciones como metadata / botones
        reply_msg.metadata = {
            "evidence": {
                "markdown": evidence_md,
                "contratos": contratos,
                "capitulos": capitulos,
                "extractos": extractos,
            }
        }
        reply_msg.actions = actions      # se asignan aquí
        await reply_msg.update()         # sin argumentos

        thinking_msg.content = "Respuesta generada (RAG)."
        await thinking_msg.update()

    except Exception as e:
        print(f"[ERROR] {e}")
        thinking_msg.content = (
            "Ha ocurrido un error al procesar la consulta. Revisa los logs del servidor."
        )
        await thinking_msg.update()
