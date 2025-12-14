"""Generación y ejecución de consultas Cypher seguras."""
import json
import re
from typing import Any, Dict

import config
from clients import llm_client
from services.neo4j_queries import neo4j_query
from utils.json_utils import safe_json_loads


WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|LOAD\s+CSV|CALL\s+apoc\.|CALL\s+dbms)\b",
    re.IGNORECASE,
)


def cypher_is_safe_readonly(cypher: str) -> bool:
    if not cypher or not isinstance(cypher, str):
        return False
    if WRITE_KEYWORDS.search(cypher):
        return False
    if not re.search(r"\b(MATCH|CALL)\b", cypher, re.IGNORECASE):
        return False
    return True


def cypher_ensure_limit(cypher: str, default_limit: int = 50) -> str:
    if re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        return cypher
    return cypher.rstrip() + f"\nLIMIT {default_limit}"


def cypher_needs_r_binding(cypher: str) -> bool:
    if re.search(r"\br\.\w+", cypher):
        return not bool(re.search(r"\[\s*r\s*:", cypher))
    return False


def get_schema_hint(max_chars: int = 7000) -> str:
    try:
        rows = neo4j_query("CALL db.schema.visualization()")
        if rows:
            return json.dumps(rows[0], ensure_ascii=False)[:max_chars]
    except Exception:
        pass
    return "N/D"


def generate_cypher_plan(question: str, schema_hint: str, error_hint: str = "") -> Dict[str, Any]:
    prompt = f"""
Fecha actual: {config.TODAY_STR}

Eres un experto en Neo4j y contratación pública.
Genera una consulta Cypher SOLO LECTURA para responder a la pregunta.

Esquema (puede estar truncado):
\"\"\"{schema_hint}\"\"\"

REGLAS IMPORTANTES:
- Si usas propiedades de la relación de adjudicación (r.importe_adjudicado o r.importe),
  DEBES declarar la relación con variable r, por ejemplo:
  (emp:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)

- Evita APOC.
- Evita CREATE/MERGE/SET/DELETE/DROP.

{("Error previo a corregir: " + error_hint) if error_hint else ""}

Devuelve SOLO JSON:
{{
  "cypher": "...",
  "params": {{}}
}}

Pregunta:
\"\"\"{question}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON válido."}, {"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=650,
    )
    data = safe_json_loads(resp.choices[0].message.content or "") or {}
    cypher = (data.get("cypher") or "").strip()
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return {"cypher": cypher, "params": params, "raw": data}


def cypher_qa(question: str) -> Dict[str, Any]:
    schema_hint = get_schema_hint(7000)

    plan = generate_cypher_plan(question, schema_hint)
    cypher = plan["cypher"]
    params = plan["params"]

    if not cypher_is_safe_readonly(cypher):
        return {"error": "Cypher no seguro o inválido.", "cypher": cypher, "plan": plan}

    if cypher_needs_r_binding(cypher):
        plan = generate_cypher_plan(question, schema_hint, error_hint="La query usa r.<prop> pero no declara [r:REL].")
        cypher = plan["cypher"]
        params = plan["params"]
        if not cypher_is_safe_readonly(cypher):
            return {"error": "Cypher no seguro tras reparación.", "cypher": cypher, "plan": plan}

    cypher = cypher_ensure_limit(cypher, 50)

    try:
        rows = neo4j_query(cypher, params)
    except Exception as e:
        err = str(e)
        plan2 = generate_cypher_plan(question, schema_hint, error_hint=err)
        cypher2 = plan2["cypher"]
        params2 = plan2["params"]
        if not cypher_is_safe_readonly(cypher2):
            return {"error": f"Fallo Cypher y reparación insegura: {err}", "cypher": cypher, "plan": plan2}
        if cypher_needs_r_binding(cypher2):
            plan3 = generate_cypher_plan(question, schema_hint, error_hint="Define la relación con variable r si usas r.<prop>.")
            cypher2 = plan3["cypher"]
            params2 = plan3["params"]
            if not cypher_is_safe_readonly(cypher2):
                return {"error": "No se pudo generar Cypher seguro tras 2 reparaciones.", "cypher": cypher, "plan": plan3}
        cypher2 = cypher_ensure_limit(cypher2, 50)
        rows = neo4j_query(cypher2, params2)
        cypher = cypher2
        plan = plan2

    system_msg = (
        "Eres un asistente de contratación pública. Respondes SOLO con los datos devueltos por Neo4j. "
        "Si no hay datos suficientes, dilo."
    )
    user_msg = f"""
Pregunta:
\"\"\"{question}\"\"\"

Cypher ejecutado:
\"\"\"{cypher}\"\"\"

Resultado (JSON):
\"\"\"{json.dumps(rows, ensure_ascii=False)}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=600,
    )
    answer = resp.choices[0].message.content or "(sin respuesta)"
    return {"answer": answer, "cypher": cypher, "rows": rows, "plan": plan}
