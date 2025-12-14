"""Flujo de preparación de Pliegos de Prescripciones Técnicas."""
import re
from typing import Any, Dict, List, Optional, Tuple

import config
from clients import llm_client
from services.embeddings import embed_text
from services.neo4j_queries import neo4j_query, search_capitulos, search_extractos
from chat_utils.json_utils import safe_json_loads
from chat_utils.text_utils import clip

try:
    from docx import Document

    HAS_DOCX = True
except Exception:
    HAS_DOCX = False


def plan_ppt_clarifications(user_request: str) -> Dict[str, Any]:
    prompt = f"""
Fecha: {config.TODAY_STR}

Eres un planificador para redactar un Pliego de Prescripciones Técnicas (PPT).
Tu tarea es decidir si necesitas aclaraciones antes de redactar.
Devuelve SOLO JSON válido:
{{
  "need_clarification": true|false,
  "normalized_request": "...",
  "questions": ["..."]
}}

Instrucciones:
- Resume y normaliza la petición.
- Si faltan datos clave (objeto, cantidades, plazos, lugar), pide 2-3 preguntas.
- Si ya hay suficiente contexto, need_clarification=false y questions=[].

Petición original:
\"\"\"{user_request}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON."}, {"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=500,
    )
    data = safe_json_loads(resp.choices[0].message.content or "") or {}
    need = bool(data.get("need_clarification"))
    normalized = data.get("normalized_request") or user_request
    questions = data.get("questions") if isinstance(data.get("questions"), list) else []
    return {
        "need_clarification": need,
        "normalized_request": normalized,
        "questions": questions,
    }


def find_reference_ppt_contract(question_embedding: List[float], top_k: int = 10) -> Optional[Dict[str, Any]]:
    candidatos = search_capitulos(question_embedding, k=top_k, doc_tipo="PPT")
    for c in candidatos:
        cid = c.get("contract_id")
        if not cid:
            continue
        rows = neo4j_query(
            """
            MATCH (c:ContratoRAG {contract_id: $cid})-[td:TIENE_DOC]->(d:DocumentoRAG)
            WHERE td.tipo_doc = 'PPT'
            RETURN d.doc_id AS doc_id
            LIMIT 1
            """,
            {"cid": cid},
        )
        if rows:
            c["doc_id"] = rows[0]["doc_id"]
            return c
    return None


def get_ppt_reference_data(contract_id: str) -> Optional[Dict[str, Any]]:
    rows = neo4j_query(
        """
        MATCH (c:ContratoRAG {contract_id: $cid})-[td:TIENE_DOC]->(d:DocumentoRAG)
        WHERE td.tipo_doc = 'PPT'
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
        {"cid": contract_id},
    )
    if not rows:
        return None

    cap_list = []
    for r in rows:
        if r.get("heading") is None:
            continue
        cap_list.append({
            "heading": r.get("heading"),
            "orden": r.get("orden"),
            "texto": r.get("texto") or "",
        })

    return {
        "contract_id": contract_id,
        "expediente": rows[0].get("expediente"),
        "contrato_titulo": rows[0].get("contrato_titulo"),
        "doc_id": rows[0].get("doc_id"),
        "capitulos": cap_list,
    }


def build_ppt_generation_prompt_one_by_one(user_request: str, ref_data: Dict[str, Any]) -> Tuple[str, str]:
    exp = ref_data.get("expediente") or "N/D"
    titulo_ref = ref_data.get("contrato_titulo") or "N/D"
    caps = ref_data.get("capitulos") or []

    cap_blocks = []
    for c in caps[:18]:
        heading = c.get("heading") or "N/D"
        orden = c.get("orden")
        texto = c.get("texto") or ""
        snippet = clip(texto, 1200)
        cap_blocks.append(
            f"### Capítulo {orden}. {heading}\n"
            f"Contenido de referencia (no copiar literal):\n"
            f"{snippet}\n"
        )
    caps_ref_text = "\n".join(cap_blocks) if cap_blocks else "N/D"

    system_msg = (
        "Eres un redactor experto en Pliegos de Prescripciones Técnicas (PPT). "
        "Redactas de forma original, técnica y clara. "
        "Sigues la estructura del pliego de referencia y te inspiras en su contenido capítulo a capítulo, "
        "pero SIN copiar literal."
    )

    user_msg = f"""
Fecha actual: {config.TODAY_STR}

Se te pide redactar un **Pliego de Prescripciones Técnicas (PPT)**.

0) TITULACIÓN
- Comienza el documento con un título en H1:
  "# Pliego de Prescripciones Técnicas: <TÍTULO CONCRETO Y DESCRIPTIVO>"
  (El título debe reflejar el objeto real del encargo del usuario).

1) Encargo del usuario (objeto y contexto)
{user_request}

2) Pliego de referencia principal
- Expediente: {exp}
- Título del contrato de referencia: {titulo_ref}

3) Estructura y contenido del pliego de referencia (capítulo a capítulo)
Debes seguir la MISMA estructura de capítulos (mismos niveles), adaptando títulos y contenido al nuevo objeto.
NO copies literal. Para cada capítulo, redacta el capítulo equivalente para el nuevo PPT.

{caps_ref_text}

INSTRUCCIONES MUY IMPORTANTES:
- Redacta capítulo a capítulo en el mismo orden y con encabezados `##`.
- Tras cada capítulo, añade SIEMPRE un bloque en cursiva con el encabezado:
  _Recomendaciones para mejorar el pliego:_
  _- ..._
  _- ..._
  _- ..._
- Las recomendaciones deben ser prácticas: qué faltaría para mejorar ese capítulo en una licitación real.
- No inventes normativa nueva; si mencionas normativa, hazlo prudente y coherente.
- Devuelve SOLO el PPT en Markdown (sin comentarios fuera del pliego).
"""
    return system_msg.strip(), user_msg.strip()


def slug_filename(title: str, max_len: int = 80) -> str:
    t = (title or "PPT").strip().lower()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    t = re.sub(r"\s+", "-", t).strip("-")
    if len(t) > max_len:
        t = t[:max_len].rstrip("-")
    return t or "ppt-generado"


def ppt_to_docx_bytes(md_text: str, title: str = "Pliego de Prescripciones Técnicas") -> bytes:
    if not HAS_DOCX:
        return b""
    doc = Document()
    doc.add_heading(title, level=1)
    for line in (md_text or "").splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            doc.add_heading(line.replace("## ", "").strip(), level=2)
        else:
            doc.add_paragraph(line)
    from io import BytesIO

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
