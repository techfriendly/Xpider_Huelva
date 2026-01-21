"""
FOLLOWUPS V2: followups.py
Generación de preguntas sugeridas.
"""
from typing import List
import config
from clients import llm_client
from chat_utils.text_utils import clip
from chat_utils.json_utils import safe_json_loads


def generate_follow_up_questions(question: str, answer: str, max_suggestions: int = 3) -> List[str]:
    """
    Genera preguntas de seguimiento basadas en la respuesta.
    """
    # Truncamos la respuesta para no explotar contexto
    answer_clipped = clip(answer, 1500)
    
    prompt = f"""Basándote en esta conversación, genera {max_suggestions} preguntas cortas que el usuario podría hacer a continuación.

PREGUNTA DEL USUARIO:
{question}

RESPUESTA DEL ASISTENTE:
{answer_clipped}

REGLAS PARA LAS SUGERENCIAS:
1. Las sugerencias DEBEN ser ACCIONES CONCRETAS que ejecuten una búsqueda o consulta.
2. Usa verbos de acción: "Buscar...", "Mostrar...", "Listar...", "Consultar...", "Generar PPT de..."
3. NO sugieras preguntas abstractas o que requieran interpretación.
4. NO sugieras acciones imposibles como "mostrar más filas" si hay limitación de contexto.
5. NO sugieras "Mostrar detalles del contrato [NOMBRE EMPRESA]". Para empresas usa "Buscar contratos de [EMPRESA]".
6. Ejemplos BUENOS: "Buscar contratos de esta empresa", "Mostrar detalles del contrato 21seA24", "Listar empresas similares", "Ver normativas asociadas"
7. Ejemplos MALOS: "¿Qué opinas?", "Mostrar detalles del contrato PROINSO" (incorrecto, es empresa), "¿Cuáles son los criterios?"

Responde SOLO con un JSON array de strings. Ejemplo:
["Buscar más contratos de esta empresa", "Mostrar detalles del expediente 21seA34", "Listar empresas del sector construcción"]
"""
    
    try:
        resp = llm_client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": "Genera preguntas de seguimiento. Responde SOLO JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=200
        )
        
        content = resp.choices[0].message.content or "[]"
        questions = safe_json_loads(content)
        
        if isinstance(questions, list):
            return [str(q) for q in questions[:max_suggestions]]
        return []
        
    except Exception as e:
        print(f"[WARN] Error en followups: {e}")
        return []
