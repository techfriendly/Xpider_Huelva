"""
CHATBOT HUELVA V2: app.py
Punto de entrada Chainlit con arquitectura limpia.
"""
import chainlit as cl
from services.orchestrator import orchestrate_message


@cl.on_chat_start
async def on_chat_start():
    """Inicializa la sesión de chat."""
    cl.user_session.set("history", [])
    cl.user_session.set("session_state", {})
    
    # Mensaje de bienvenida
    welcome = """**Hola.** Soy el asistente virtual del área de contratación de la Diputación Provincial de Huelva.

Puedo:
- 🔍 Buscar contratos y licitaciones
- 🏢 Consultar datos de empresas adjudicatarias
- 📊 Hacer análisis de la base de datos
- 📄 Generar borradores de pliegos técnicos

**(Selecciona un ejemplo para empezar):**
"""
    
    examples = [
        "Busca contratos de suministro de vehículos",
        "¿Qué contratos ha ganado Techfriendly?",
        "Top 10 empresas por importe adjudicado",
        "Hazme un pliego para material informático"
    ]
    
    actions = [
        cl.Action(name="example_prompt", label=ex, payload={"text": ex})
        for ex in examples
    ]
    
    await cl.Message(content=welcome, actions=actions).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Procesa cada mensaje del usuario."""
    await orchestrate_message(message.content)


@cl.action_callback("example_prompt")
async def on_example_click(action: cl.Action):
    """Maneja clicks en los ejemplos iniciales."""
    text = action.payload.get("text", "")
    if text:
        # Simulamos que el usuario lo escribió
        await cl.Message(content=text, author="User").send()
        await orchestrate_message(text)


@cl.action_callback("follow_up")
async def on_follow_up(action: cl.Action):
    """Maneja clicks en sugerencias."""
    question = action.payload.get("question", "")
    if question:
        await cl.Message(content=question, author="User").send()
        await orchestrate_message(question)
