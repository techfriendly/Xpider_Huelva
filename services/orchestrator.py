"""
ORQUESTADOR V2: orchestrator.py
Loop controlado con OpenAI function calling y streaming.
"""
import chainlit as cl
from typing import Dict, Any, List
import json
import re

import config
from clients import llm_client
from services.tools import TOOLS_SCHEMA, execute_tool, continue_ppt_generation
from services.ppt_generation import ppt_to_docx_bytes, slug_filename, HAS_DOCX
from ui.evidence import set_evidence_sidebar


SYSTEM_PROMPT = """Eres un asistente experto en licitaciones y contratación pública de la Diputación de Huelva.

Tienes acceso a herramientas para:
- Buscar contratos y licitaciones (search_contracts)
- Obtener datos de empresas (search_company)  
- Consultar detalles de un contrato específico (get_contract_details) -> Incluye normativas, solvencia y extractos del pliego.
- Hacer consultas avanzadas (query_database)
- Generar documentos técnicos (generate_document)

REGLAS:
1. Usa las herramientas cuando sea apropiado.
2. Si el usuario pide generar un documento (pliego, PPT), USA LA HERRAMIENTA generate_document. NO preguntes detalles al usuario tú mismo; la herramienta lo hará si es necesario.
3. Responde siempre en español.
5. SOLO puedes generar documentos tipo "Pliego de Prescripciones Técnicas" (PPT). Si el usuario pide generar Excel, PDF, informes o cartas, responde que no tienes esa función, pero que puedes mostrarle los datos en pantalla.

REGLAS DE INTERACCIÓN:
6. NO preguntes constantemente "¿Deseas que genere un PPT?". Solo ofrécelo si el usuario muestra una intención clara de querer documentar la información o si la respuesta es muy técnica y extensa.
7. Sé directo en tus respuestas. Evita muletillas repetitivas al final.

REGLAS ANTI-ALUCINACIÓN (MUY IMPORTANTE):
6. NUNCA inventes datos que no hayas recibido de las herramientas. Si no sabes algo, di "No tengo esa información en el contexto actual" y ofrece hacer una nueva consulta.
7. Si te muestran una tabla con 10 filas, NO RELLENES las filas restantes. Solo comenta sobre los datos que tienes.
8. Los importes, expedientes, títulos y adjudicatarios DEBEN venir literalmente de los datos de la herramienta. NUNCA los inventes.
9. Si el usuario pregunta por un dato específico que no está en tu contexto, usa la herramienta apropiada para buscarlo. NO lo adivines.
10. PROACTIVIDAD: Si el usuario te pide información que no tienes, BUSCA AUTOMÁTICAMENTE usando las herramientas disponibles. NO preguntes "¿Desea que realice una consulta?" - simplemente hazla.
11. NUNCA inventes listados de leyes o normativas con años futuros (ej: "Ley 1/2030"). Si no conoces la normativa específica, di "No dispongo de la normativa específica en este momento" y ofrece buscar en el pliego usando get_contract_details.
"""


async def orchestrate_message(question: str):
    """
    Procesa un mensaje con loop controlado de herramientas.
    """
    # 1. Recuperar estado
    history = cl.user_session.get("history", [])
    session_state = cl.user_session.get("session_state", {})
    
    # 2. Verificar si hay PPT pendiente
    if session_state.get("ppt_pending"):
        await handle_ppt_followup(question, session_state)
        return
    
    # 3. Construir mensajes
    messages = build_messages(history, question)
    
    # 4. Loop de pensamiento (hasta 3 interacciones)
    MAX_LOOPS = 3
    for _ in range(MAX_LOOPS):
        # STREAMING EXECUTION
        msg = cl.Message(content="")
        
        # Necesitamos la clase para reconstruir el objeto (o un mock compatible)
        from openai.types.chat.chat_completion_message import ChatCompletionMessage
        from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function
        
        stream = await cl.make_async(llm_client.chat.completions.create)(
            model=config.LLM_MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.2,
            frequency_penalty=0.5,
            stream=True
        )
        
        full_content = ""
        tool_calls_data = [] # Lista de dicts para ir construyendo
        
        for chunk in stream:
            delta = chunk.choices[0].delta
            
            # 1. Streaming de texto normal
            if delta.content:
                if not msg.id:
                    await msg.send()
                full_content += delta.content
                await msg.stream_token(delta.content)
            
            # 2. Reconstrucción de Tool Calls
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    index = tc_chunk.index
                    
                    # Asegurar tamaño de la lista
                    while len(tool_calls_data) <= index:
                        tool_calls_data.append({
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        })
                    
                    tc = tool_calls_data[index]
                    
                    if tc_chunk.id:
                        tc["id"] += tc_chunk.id
                    
                    if tc_chunk.function:
                        if tc_chunk.function.name:
                            tc["function"]["name"] += tc_chunk.function.name
                        if tc_chunk.function.arguments:
                            tc["function"]["arguments"] += tc_chunk.function.arguments
        
        if msg.id:
            await msg.update()
        
        # Reconstruir el objeto assistant_msg para compatibilidad con el resto del código
        tool_calls_objects = []
        for tc in tool_calls_data:
            tool_calls_objects.append(
                ChatCompletionMessageToolCall(
                    id=tc["id"],
                    type="function",
                    function=Function(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                )
            )
            
        assistant_msg = ChatCompletionMessage(
            role="assistant",
            content=full_content if full_content else None,
            tool_calls=tool_calls_objects if tool_calls_objects else None
        )
        
        # SI NO HAY HERRAMIENTAS -> Respuesta final (ya se streameó)
        if not assistant_msg.tool_calls:
            # Ya se hizo stream arriba, solo actualizar historial
            update_history(history, question, full_content)
            await generate_suggestions(question, full_content, {})
            return

        # SI HAY HERRAMIENTAS -> Ejecutar y seguir
        messages.append(assistant_msg) # Añadimos la intención de llamar a la history
        
        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except:
                tool_args = {}
            
            print(f"--- [ORCHESTRATOR] Loop Tool: {tool_name} Args: {tool_args} ---")
            
            # Ejecutar herramienta con feedback visual (Step)
            async with cl.Step(name=tool_name, type="tool") as step:
                step.input = json.dumps(tool_args, indent=2, ensure_ascii=False)
                
                tool_result = await cl.make_async(execute_tool)(tool_name, tool_args, session_state)
                
                # Mostrar output truncado en el paso
                step.output = tool_result["content"][:800] + "..." if len(tool_result["content"]) > 800 else tool_result["content"]
                
                # Mostrar sidebar si hay
                if tool_result.get("sidebar"):
                    sb = tool_result["sidebar"]
                    # Forzamos sidebar update
                    await set_evidence_sidebar(sb["title"], sb["md"])
            
            # Visualizar Dataframe (Tablas)
            if tool_result.get("dataframe"):
                await cl.Message(
                    content="📊 **Datos extraídos:**", 
                    elements=[tool_result["dataframe"]]
                ).send()
            
            # Guardar estado por si acaso
            cl.user_session.set("session_state", session_state)
            
            # Casos especiales de interrupción (PPT)
            if tool_result.get("needs_clarification"):
                await handle_ppt_clarification(tool_result)
                return
            
            if tool_result.get("ppt_prompts"):
                sb = tool_result.get("sidebar")
                await generate_ppt_streaming(tool_result, question, history, sidebar_data=sb)
                return

            # Añadir resultado para la siguiente vuelta del LLM
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result["content"]
            })
            
    # Si salimos del loop por límite (despues de 3 vueltas sin respuesta final)
    # Forzamos una respuesta con lo que tengamos
    await stream_final_response(messages, question, history, {})


def build_messages(history: List[Dict], question: str) -> List[Dict]:
    """Construye lista de mensajes para el LLM."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Añadir historial (últimos turnos)
    for turn in history[-10:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    
    messages.append({"role": "user", "content": question})
    return messages


async def stream_final_response(messages: List[Dict], question: str, history: List, tool_result: Dict):
    """Genera respuesta final con streaming."""
    msg = cl.Message(content="")
    await msg.send()
    
    stream = await cl.make_async(llm_client.chat.completions.create)(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=0.2,
        stream=True,
        max_tokens=1500
    )
    
    chunks = []
    for chunk in stream:
        token = getattr(chunk.choices[0].delta, 'content', '') or ""
        if token:
            chunks.append(token)
            await msg.stream_token(token)
    
    await msg.update()
    answer = "".join(chunks)
    
    update_history(history, question, answer)
    
    # Sugerencias
    await generate_suggestions(question, answer, tool_result)


async def handle_ppt_clarification(tool_result: Dict):
    """Muestra preguntas de clarificación para PPT."""
    questions = tool_result.get("questions", [])
    q_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)])
    
    msg_content = f"Para generar el documento necesito algunos detalles:\n\n{q_text}\n\nResponde en un solo mensaje."
    await cl.Message(content=msg_content).send()


async def handle_ppt_followup(user_response: str, session_state: Dict):
    """Continúa generación de PPT después de clarificaciones."""
    tool_result = await cl.make_async(continue_ppt_generation)(user_response, session_state)
    
    cl.user_session.set("session_state", session_state)
    
    if tool_result.get("ppt_prompts"):
        history = cl.user_session.get("history", [])
        # Pasamos sidebar para que se adjunte al mensaje de generación
        sb = tool_result.get("sidebar")
        await generate_ppt_streaming(tool_result, user_response, history, sidebar_data=sb)
    else:
        await cl.Message(content=tool_result.get("content", "Error generando PPT")).send()


async def generate_ppt_streaming(tool_result: Dict, question: str, history: List, sidebar_data: Dict = None):
    """Genera PPT con streaming y archivo DOCX."""
    prompts = tool_result["ppt_prompts"]
    
    # 1. Enviar evidencia en un mensaje separado primero para asegurar visibilidad
    if sidebar_data:
        ref_element = cl.Text(name=sidebar_data["title"], content=sidebar_data["md"], display="side")
        await cl.Message(
            content=f"📄 **Referencia detectada:** Se utilizará la estructura del contrato **{sidebar_data['title']}**.",
            elements=[ref_element]
        ).send()

    # 2. Iniciar generación
    msg = cl.Message(content="⏳ **Redactando documento...**")
    await msg.send()
    
    stream = await cl.make_async(llm_client.chat.completions.create)(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]}
        ],
        temperature=0.2,
        frequency_penalty=0.1,
        stream=True,
        max_tokens=5000
    )
    
    chunks = []
    for chunk in stream:
        token = getattr(chunk.choices[0].delta, 'content', '') or ""
        if token:
            chunks.append(token)
            await msg.stream_token(token)
    
    await msg.update()
    ppt_text = "".join(chunks)
    
    # Generar DOCX
    ppt_title = "Pliego de Prescripciones Técnicas"
    m = re.search(r"^#\s*(.+)$", ppt_text, flags=re.MULTILINE)
    if m:
        ppt_title = m.group(1).strip()
    
    if HAS_DOCX:
        docx_bytes = ppt_to_docx_bytes(ppt_text, title=ppt_title)
        file = cl.File(
            name=f"{slug_filename(ppt_title)}.docx",
            content=docx_bytes,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        await cl.Message(content=f"📄 Documento generado: **{ppt_title}**", elements=[file]).send()
    
    update_history(history, question, f"[Documento generado: {ppt_title}]")


async def generate_suggestions(question: str, answer: str, tool_result: Dict):
    """Genera sugerencias de follow-up."""
    if len(answer) < 100:
        return
    
    # Importamos aquí para evitar circular
    from services.followups import generate_follow_up_questions
    
    try:
        suggestions = await cl.make_async(generate_follow_up_questions)(question, answer, 3)
        if suggestions:
            actions = []
            for s in suggestions:
                label = s if len(s) <= config.SUGGESTION_LABEL_MAX_CHARS else s[:config.SUGGESTION_LABEL_MAX_CHARS-1] + "…"
                actions.append(cl.Action(
                    name="follow_up",
                    label=label,
                    tooltip=s,
                    payload={"question": s}
                ))
            await cl.Message(content="💡 Sugerencias:", actions=actions).send()
    except Exception as e:
        print(f"[WARN] Error generando sugerencias: {e}")


def update_history(history: List, question: str, answer: str):
    """Actualiza historial de conversación."""
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    cl.user_session.set("history", history[-config.MAX_HISTORY_TURNS:])
