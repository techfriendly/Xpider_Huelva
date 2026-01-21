"""
GENERADOR DE CONSULTAS CYPHER: cypher.py
DESCRIPCIÓN:
Convierte lenguaje natural ("¿Quién ganó más contratos?") en código Cypher (SQL para grafos)
usando el LLM.

SEGURIDAD:
- Comprueba que la consulta es SOLO LECTURA (prohíbe CREATE, DELETE, etc.).
- Comprueba errores comunes y reintenta repararlos automáticamente.
- Si falla, hace fallback a una tabla genérica.
"""

import json
import re
from typing import Any, Dict, List, Optional, Union

import config
from clients import llm_client
from services.neo4j_queries import neo4j_query
from chat_utils.json_utils import safe_json_loads
from chat_utils.prompt_loader import load_prompt


def clean_keys(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reemplaza puntos en las claves por guiones bajos para evitar problemas en UIs."""
    if not rows:
        return rows
    new_rows = []
    for r in rows:
        new_row = {}
        for k, v in r.items():
            new_key = k.replace(".", "_")
            new_row[new_key] = v
        new_rows.append(new_row)
    return new_rows


# Palabras prohibidas para evitar inyección de código que modifique la BD


# Palabras prohibidas para evitar inyección de código que modifique la BD
WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|LOAD\s+CSV|CALL\s+apoc\.|CALL\s+dbms)\b",
    re.IGNORECASE,
)


def cypher_is_safe_readonly(cypher: str) -> bool:
    """Valida si la consulta parece segura (solo lectura)."""
    if not cypher or not isinstance(cypher, str):
        return False
    if WRITE_KEYWORDS.search(cypher):
        return False
    # Debe contener al menos una cláusula de consulta básica
    if not re.search(r"\b(MATCH|CALL|WITH|RETURN)\b", cypher, re.IGNORECASE):
        return False
    return True


def cypher_ensure_limit(cypher: str, default_limit: int = 50) -> str:
    """Añade un LIMIT por seguridad si no existe, para no traerse toda la BD."""
    if re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        return cypher
    return cypher.rstrip() + f"\nLIMIT {default_limit}"


def cypher_needs_r_binding(cypher: str) -> bool:
    """Detecta un error común: usar propiedades de una relación (r.prop) sin declararla [r:REL]."""
    if re.search(r"\br\.\w+", cypher):
        return not bool(re.search(r"\[\s*r\s*:", cypher))
    return False


def get_schema_hint(max_chars: int = 7000) -> str:
    """Provee el esquema del grafo para el LLM."""
    # Retornamos un esquema curado y explícito para mejorar la precisión
    return """
    NODOS:
    - :ContratoRAG (Representa un contrato/licitación)
      Propiedades: expediente (str), titulo (str), valor_estimado (float), presupuesto_sin_iva (float), cpv_principal (str), contract_uri (str)
    
    - :EmpresaRAG (Representa una empresa adjudicataria)
      Propiedades: nombre (str), nif (str)
      
    RELACIONES:
    - (:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(:ContratoRAG)
      Propiedades de la relación 'r': 
        - importe_adjudicado (float): El importe real por el que se ganó el contrato.
        
    NOTA IMPORTANTE:
    - Para "importe adjudicado" o "importe contratado", USA SIEMPRE `r.importe_adjudicado` en la relación.
    - Para "facturación", suma `r.importe_adjudicado`.
    - Para "valor estimado" o presupuesto base, usa `c.valor_estimado` o `c.presupuesto_sin_iva` en el nodo ContratoRAG.
    
    ATENCIÓN DIRECCIÓN:
    La relación es UNIDIRECCIONAL: (:EmpresaRAG)-[:ADJUDICATARIA_RAG]->(:ContratoRAG).
    SIEMPRE usa (e:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG).
    NUNCA uses (c:ContratoRAG)-[:ADJUDICATARIA_RAG]->(e:EmpresaRAG) porque devolverá 0 resultados.
    
    DUPLICADOS:
    - Si buscas un LISTADO de contratos (top, búsqueda, etc.), usa SIEMPRE `DISTINCT c.expediente` (o `c.contract_id`) en el RETURN.
      Ej: `RETURN DISTINCT c.expediente, c.titulo, r.importe_adjudicado...`
      Esto evita que el contrato salga repetido si tiene múltiples empresas en UTE.
      
    FILTRADO POR TIPO (CPV):
    - IMPORTANTE: `cpv_principal` puede ser INT o STRING. Usa SIEMPRE `toString(c.cpv_principal)` para comparar.
    - OBRAS: `toString(c.cpv_principal) STARTS WITH '45'`
    - SUMINISTROS: `toString(c.cpv_principal) < '45'` (comparación lexicográfica funciona bien sobre strings)
    - SERVICIOS: `toString(c.cpv_principal) >= '50'`
    
    FILTRADO POR FECHA / AÑO:
    - NO EXISTE campo fecha.
    - El año suele estar al inicio del expediente.
    - Para "año 2024": `WHERE c.expediente STARTS WITH '24' OR c.expediente STARTS WITH '2024'`
    - Para "año 2023": `WHERE c.expediente STARTS WITH '23' OR c.expediente STARTS WITH '2023'`
    """


def _wants_raw_json(question: str) -> bool:
    """Detecta si el usuario 'experto' quiere ver el JSON crudo."""
    q = (question or "").lower()
    return any(tok in q for tok in [" json", "en json", "formato json", "devuélveme json", "devuelveme json", "raw json"])


def _format_number_es(x: Union[int, float], decimals: int = 2) -> str:
    """Formatea números al estilo español (1.000,00)."""
    # 5,036,383.02 -> 5.036.383,02
    s = f"{x:,.{decimals}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _format_value(key: str, v: Any) -> str:
    """Formatea valores individuales para mostrarlos bonitos en la tabla Markdown."""
    if v is None:
        return "—"

    if isinstance(v, bool):
        return "sí" if v else "no"

    if isinstance(v, (int, float)) and not isinstance(v, bool):
        k = (key or "").lower()
        # Detección heurística de campos monetarios
        is_money = any(t in k for t in ["importe", "total", "factur", "presupuesto", "valor", "eu", "€"])
        if isinstance(v, float):
            v = round(v, 2)
        if is_money:
            return f"{_format_number_es(float(v), 2)} €"
        if float(v).is_integer():
            return _format_number_es(float(v), 0)
        return _format_number_es(float(v), 2)

    if isinstance(v, str):
        s = v.strip()
        if not s:
            return "—"
        s = re.sub(r"\s{2,}", " ", s)
        # Recortar textos muy largos en celdas de tabla
        if len(s) > 140:
            s = s[:139].rstrip() + "…"
        return s.replace("|", r"\|") # Escapar pipes para Markdown

    # Objetos complejos -> JSON string
    try:
        s = json.dumps(v, ensure_ascii=False)
    except Exception:
        s = str(v)
    if len(s) > 160:
        s = s[:159].rstrip() + "…"
    return s.replace("|", r"\|")


def rows_to_markdown(rows: Any, max_rows: int = 100, max_cols: int = 8) -> str:
    """Convierte resultados de la BD (Lista de diccionarios) en una Tabla Markdown."""
    if rows is None:
        return "No se han devuelto filas."

    if isinstance(rows, list):
        if not rows:
            return "No se han encontrado resultados."

        if all(isinstance(r, dict) for r in rows):
            # Recopilar todas las columnas posibles
            cols: List[str] = list(rows[0].keys())
            for r in rows[1:]:
                for k in r.keys():
                    if k not in cols:
                        cols.append(k)

            cols = cols[:max_cols] # Limitar ancho

            header = "| " + " | ".join(cols) + " |"
            sep = "| " + " | ".join(["---"] * len(cols)) + " |"
            lines = [header, sep]

            for r in rows[:max_rows]:
                vals = [_format_value(c, r.get(c)) for c in cols]
                lines.append("| " + " | ".join(vals) + " |")

            if len(rows) > max_rows:
                lines.append(f"\n_Mostrando {max_rows} de {len(rows)} filas._")

            return "\n".join(lines)

        # Si es una lista simple (ej: lista de nombres)
        lines = ["Resultados:"]
        for x in rows[:max_rows]:
            lines.append(f"- {_format_value('', x)}")
        if len(rows) > max_rows:
            lines.append(f"\n_Mostrando {max_rows} de {len(rows)} elementos._")
        return "\n".join(lines)

    if isinstance(rows, dict):
        return "```json\n" + json.dumps(rows, ensure_ascii=False, indent=2) + "\n```"

    return str(rows)


def generate_cypher_plan(question: str, schema_hint: str, error_hint: str = "") -> Dict[str, Any]:
    """Genera el plan (Query + Parámetros) usando el LLM."""
    prompt = load_prompt(
        "cypher_generation",
        today=config.TODAY_STR,
        schema_hint=schema_hint,
        error_hint=("Error previo a corregir: " + error_hint) if error_hint else "",
        question=question
    )
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON válido."}, {"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=650,
    )

    content = resp.choices[0].message.content or ""
    print(f"--- [GEN CYPHER] Respuesta LLM: {content[:100]}... ---")

    data = safe_json_loads(content) or {}
    cypher = (data.get("cypher") or "").strip()
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    return {"cypher": cypher, "params": params, "raw": data}


def cypher_qa(question: str) -> Dict[str, Any]:
    """
    Función principal:
    1. Genera Cypher.
    2. Valida seguridad.
    3. Ejecuta.
    4. Si falla, intenta corregir (hasta 2 intentos).
    5. Formatea la respuesta (Tabla Markdown o Texto explicativo).
    """
    schema_hint = get_schema_hint(7000)
    
    plan = generate_cypher_plan(question, schema_hint)
    cypher = plan["cypher"]
    params = plan["params"]

    # Validación 1: Seguridad
    if not cypher_is_safe_readonly(cypher):
        print(f"--- [ERROR CYPHER] Cypher no seguro: {cypher!r} ---")
        return {"error": "Cypher no seguro o inválido.", "cypher": cypher, "plan": plan}

    # Validación 2: Sintaxis común incorrecta
    if cypher_needs_r_binding(cypher):
        plan = generate_cypher_plan(question, schema_hint, error_hint="La query usa r.<prop> pero no declara [r:REL].")
        cypher = plan["cypher"]
        params = plan["params"]

    cypher = cypher_ensure_limit(cypher, 50)

    # EJECUCIÓN CON REINTENTOS
    try:
        print(f"--- [EXEC CYPHER] Ejecutando: {cypher} | Params: {params} ---")
        rows = neo4j_query(cypher, params)
        rows = clean_keys(rows)  # Sanear claves para UI/DataFrame
        print(f"--- [EXEC CYPHER] Filas: {len(rows) if rows else 0} ---")
    except Exception as e:
        err = str(e)
        print(f"--- [ERROR CYPHER EXEC] {err} ---")
        # Reintento con pista del error
        plan2 = generate_cypher_plan(question, schema_hint, error_hint=err)
        cypher2 = plan2["cypher"]
        params2 = plan2["params"]

        if not cypher_is_safe_readonly(cypher2):
            return {"error": f"Fallo Cypher y reparación insegura: {err}", "cypher": cypher, "plan": plan2}

        cypher2 = cypher_ensure_limit(cypher2, 50)
        try:
            print(f"--- [REINTENTO CYPHER] Ejecutando: {cypher2} ---")
            rows = neo4j_query(cypher2, params2)
            rows = clean_keys(rows)  # Sanear claves para UI/DataFrame
            cypher = cypher2         # Actualizamos variables para devolver la query correcta
            params = params2
            plan = plan2
        except Exception as e2:
             return {"error": f"Fallo tras re-intento: {str(e2)}", "cypher": cypher2, "plan": plan2}

    # DEVOLUCIÓN DE RESPUESTA
    
    # Preparamos Sidebar Evidence (Query usada)
    sidebar_md = f"### Consulta Generada (Cypher)\n```cypher\n{cypher}\n```\n**Params:** `{json.dumps(params)}`\n"

    # Si piden JSON, devolvemos JSON
    if _wants_raw_json(question):
        answer = json.dumps(rows, ensure_ascii=False, indent=2)
        return {"answer": answer, "cypher": cypher, "rows": rows, "plan": plan, "sidebar_md": sidebar_md}

    # Generamos tabla Markdown para el contexto del LLM
    # LIMITACIÓN: Solo pasamos las 10 primeras filas al LLM para evitar alucinaciones
    rows_for_context = rows[:10] if len(rows) > 10 else rows
    table_md = rows_to_markdown(rows_for_context, max_rows=10)

    # OPTIMIZACIÓN: Si hay muchas filas (>15), no pedimos al LLM que las explique
    # Le damos un resumen estructurado con los datos reales (primeras 10 filas)
    if len(rows) > 15:
        answer = f"Se han encontrado **{len(rows)} resultados** en la base de datos.\n\n"
        answer += f"**DATOS EN CONTEXTO (primeras 10 filas):**\n\n{table_md}\n\n"
        answer += f"⚠️ **Solo las 10 primeras filas están en mi memoria/contexto.** "
        answer += f"El usuario puede ver las {len(rows)} filas completas en la tabla interactiva de arriba. "
        answer += f"Para preguntas sobre filas específicas fuera de estas 10, haré una nueva consulta."
    else:
        # Para pocas filas, que el LLM las explique
        system_msg = load_prompt("cypher_response_system")
        user_msg = load_prompt(
            "cypher_response_user",
            question=question,
            cypher=cypher,
            rows_json=json.dumps(rows, ensure_ascii=False)
        )

        resp = llm_client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            max_tokens=600,
        )

        answer = (resp.choices[0].message.content or "").strip()
        if not answer:
            answer = table_md

    # Fallback: Si el LLM devuelve JSON en vez de explicarlo, mostramos la tabla que se entiende mejor.
    looks_like_json = False
    if answer.startswith("[") or answer.startswith("{"):
        parsed = safe_json_loads(answer)
        if isinstance(parsed, (list, dict)):
            looks_like_json = True
    if "```json" in answer.lower():
        looks_like_json = True

    if looks_like_json:
        answer = table_md

    return {"answer": answer, "cypher": cypher, "rows": rows, "plan": plan, "sidebar_md": sidebar_md}
