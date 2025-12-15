"""Generación y ejecución de consultas Cypher seguras (solo lectura).

Mejoras:
- El "redactor" del resultado NO debe devolver JSON.
- Fallback determinista: si el redactor devuelve JSON, se devuelve una tabla Markdown con los rows.
"""
import json
import re
from typing import Any, Dict, List, Optional, Union

import config
from clients import llm_client
from services.neo4j_queries import neo4j_query
from chat_utils.json_utils import safe_json_loads


WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|LOAD\s+CSV|CALL\s+apoc\.|CALL\s+dbms)\b",
    re.IGNORECASE,
)


def cypher_is_safe_readonly(cypher: str) -> bool:
    if not cypher or not isinstance(cypher, str):
        return False
    if WRITE_KEYWORDS.search(cypher):
        return False
    # Permitimos MATCH / CALL (p.ej. CALL db.index...); bloqueamos lo demás con WRITE_KEYWORDS
    if not re.search(r"\b(MATCH|CALL|WITH|RETURN)\b", cypher, re.IGNORECASE):
        return False
    return True


def cypher_ensure_limit(cypher: str, default_limit: int = 50) -> str:
    if re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        return cypher
    return cypher.rstrip() + f"\nLIMIT {default_limit}"


def cypher_needs_r_binding(cypher: str) -> bool:
    """Detecta si la query usa r.<prop> pero no declara [r:REL]."""
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


def _wants_raw_json(question: str) -> bool:
    q = (question or "").lower()
    # si el usuario pide explícitamente json, respetamos
    return any(tok in q for tok in [" json", "en json", "formato json", "devuélveme json", "devuelveme json", "raw json"])


def _format_number_es(x: Union[int, float], decimals: int = 2) -> str:
    # 5,036,383.02 -> 5.036.383,02
    s = f"{x:,.{decimals}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _format_value(key: str, v: Any) -> str:
    if v is None:
        return "—"

    # Boolean
    if isinstance(v, bool):
        return "sí" if v else "no"

    # Numéricos
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        k = (key or "").lower()
        is_money = any(t in k for t in ["importe", "total", "factur", "presupuesto", "valor", "eu", "€"])
        # Evita floats feos como 5036383.02000000005
        if isinstance(v, float):
            v = round(v, 2)
        if is_money:
            return f"{_format_number_es(float(v), 2)} €"
        # Enteros “bonitos” si aplica
        if float(v).is_integer():
            return _format_number_es(float(v), 0)
        return _format_number_es(float(v), 2)

    # Strings
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return "—"
        # compacta un poco
        s = re.sub(r"\s{2,}", " ", s)
        if len(s) > 140:
            s = s[:139].rstrip() + "…"
        return s.replace("|", r"\|")

    # Dict/list anidado
    try:
        s = json.dumps(v, ensure_ascii=False)
    except Exception:
        s = str(v)
    if len(s) > 160:
        s = s[:159].rstrip() + "…"
    return s.replace("|", r"\|")


def rows_to_markdown(rows: Any, max_rows: int = 25, max_cols: int = 8) -> str:
    """Convierte rows de Neo4j (list[dict]) a una tabla Markdown usable en chat."""
    if rows is None:
        return "No se han devuelto filas."

    if isinstance(rows, list):
        if not rows:
            return "No se han encontrado resultados."

        # list[dict] -> tabla
        if all(isinstance(r, dict) for r in rows):
            # Columnas: primero las de la primera fila, luego añadimos nuevas si aparecen
            cols: List[str] = list(rows[0].keys())
            for r in rows[1:]:
                for k in r.keys():
                    if k not in cols:
                        cols.append(k)

            cols = cols[:max_cols]

            header = "| " + " | ".join(cols) + " |"
            sep = "| " + " | ".join(["---"] * len(cols)) + " |"
            lines = [header, sep]

            for r in rows[:max_rows]:
                vals = [_format_value(c, r.get(c)) for c in cols]
                lines.append("| " + " | ".join(vals) + " |")

            if len(rows) > max_rows:
                lines.append(f"\n_Mostrando {max_rows} de {len(rows)} filas._")

            return "\n".join(lines)

        # list de escalares
        lines = ["Resultados:"]
        for x in rows[:max_rows]:
            lines.append(f"- {_format_value('', x)}")
        if len(rows) > max_rows:
            lines.append(f"\n_Mostrando {max_rows} de {len(rows)} elementos._")
        return "\n".join(lines)

    # dict -> pretty json
    if isinstance(rows, dict):
        return "```json\n" + json.dumps(rows, ensure_ascii=False, indent=2) + "\n```"

    return str(rows)


def generate_cypher_plan(question: str, schema_hint: str, error_hint: str = "") -> Dict[str, Any]:
    prompt = f"""
Fecha actual: {config.TODAY_STR}

Eres un experto en Neo4j y contratación pública.
Genera una consulta Cypher SOLO LECTURA para responder a la pregunta.

Esquema (puede estar truncado):
\"\"\"{schema_hint}\"\"\"

REGLAS IMPORTANTES:
- Evita APOC.
- Evita CREATE/MERGE/SET/DELETE/DROP.
- Limita resultados con LIMIT.
- Si usas propiedades de la relación de adjudicación (r.importe_adjudicado o r.importe),
  DEBES declarar la relación con variable r, por ejemplo:
  (emp:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)

- Usa aliases claros en el RETURN (ej: nombre, total_facturado, contratos_ganados, importe_total).

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

    # Ejecuta, con una reparación si falla
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
            plan3 = generate_cypher_plan(
                question,
                schema_hint,
                error_hint="Define la relación con variable r si usas r.<prop>.",
            )
            cypher2 = plan3["cypher"]
            params2 = plan3["params"]
            if not cypher_is_safe_readonly(cypher2):
                return {"error": "No se pudo generar Cypher seguro tras 2 reparaciones.", "cypher": cypher, "plan": plan3}

        cypher2 = cypher_ensure_limit(cypher2, 50)
        rows = neo4j_query(cypher2, params2)
        cypher = cypher2
        params = params2
        plan = plan2

    # Si el usuario quiere JSON explícito, se devuelve JSON directamente (sin LLM)
    if _wants_raw_json(question):
        answer = json.dumps(rows, ensure_ascii=False, indent=2)
        return {"answer": answer, "cypher": cypher, "rows": rows, "plan": plan}

    # Intentamos redacción en texto. Si “se cuela” JSON, fallback a tabla.
    table_md = rows_to_markdown(rows, max_rows=25)

    system_msg = (
        "Eres un asistente de contratación pública.\n"
        "Tu respuesta debe ser TEXTO en español (Markdown).\n"
        "NO devuelvas JSON, ni arrays/dicts literales, ni bloques ```json.\n"
        "Si hay varias filas, muestra una lista numerada o una tabla Markdown.\n"
        "Si no hay datos, dilo claramente."
    )

    user_msg = f"""
Pregunta:
\"\"\"{question}\"\"\"

Cypher ejecutado:
\"\"\"{cypher}\"\"\"

Filas devueltas (JSON, para tu análisis interno):
\"\"\"{json.dumps(rows, ensure_ascii=False)}\"\"\"
"""

    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=600,
    )

    answer = (resp.choices[0].message.content or "").strip()
    if not answer:
        answer = table_md

    # Fallback: si el LLM devuelve JSON o un bloque json, lo sustituimos por tabla.
    looks_like_json = False
    if answer.startswith("[") or answer.startswith("{"):
        parsed = safe_json_loads(answer)
        if isinstance(parsed, (list, dict)):
            looks_like_json = True
    if "```json" in answer.lower():
        looks_like_json = True

    if looks_like_json:
        answer = table_md

    return {"answer": answer, "cypher": cypher, "rows": rows, "plan": plan}
