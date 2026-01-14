"""
ARCHIVO PRINCIPAL: app.py
DESCRIPCIÓN:
Este es el punto de entrada de la aplicación Chatbot. Aquí se configuran:
1. La conexión con Chainlit (la interfaz visual del chat).
2. La base de datos para guardar el historial de conversaciones.
3. El sistema de autenticación (login con usuario y contraseña).
4. Las funciones que reaccionan cuando el usuario entra, escribe o pulsa botones.
"""

import chainlit as cl
import config
from services.orchestrator import orchestrate_message
from ui.evidence import clear_evidence_sidebar
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
import json
import os
from typing import Union, Dict, Any
from chainlit.data.storage_clients.base import BaseStorageClient

# --- SECCIÓN 1: CONFIGURACIÓN DE PERSISTENCIA (GUARDADO DEL CHAT) ---
# Configuramos cómo y dónde se guarda el historial de las conversaciones.

# Cliente de almacenamiento "falso" (Dummy) porque guardamos el texto en base de datos local (SQLite),
# no archivos en la nube (S3, Azure, etc.).
class DummyStorageClient(BaseStorageClient):
    async def upload_file(self, object_key: str, data: Union[bytes, str], mime: str = "application/octet-stream", overwrite: bool = True) -> Dict[str, Any]:
        return {"object_key": object_key, "url": ""}
    async def get_read_url(self, object_key: str) -> str:
        return ""
    async def delete_file(self, object_key: str) -> bool:
        return True
    async def close(self):
        pass

# Clase extendida de la Capa de Datos para añadir diagnósticos (Logs).
# Esto nos permite ver en la terminal si algo falla al guardar o leer el historial.
class DebugSQLAlchemyDataLayer(SQLAlchemyDataLayer):
    # Función para crear un "paso" (mensaje) nuevo
    async def create_step(self, step_dict):
        # Descomentar para ver cada mensaje que se guarda:
        # print(f"--- [DEBUG] Guardando paso: {step_dict.get('name')} ({step_dict.get('type')}) ---")
        try:
            return await super().create_step(step_dict)
        except Exception as e:
            print(f"--- [ERROR DEBUG] Fallo al guardar paso: {e} ---")
            raise e

    # Función para recuperar todos los hilos (conversaciones) de un usuario
    async def get_all_user_threads(self, user_id: str):
        # Descomentar para ver cuándo se pide el historial:
        # print(f"--- [DEBUG] Recuperando hilos para usuario: {user_id} ---")
        threads = await super().get_all_user_threads(user_id)
        # if threads:
        #     print(f"--- [DEBUG] Encontrados {len(threads)} hilos ---")
        # else:
        #     print(f"--- [DEBUG] NO se encontraron hilos (historial vacío) ---")
        return threads

    # Función principal que llama el interfaz (frontend) para listar chats
    async def list_threads(self, pagination, filters):
        # print(f"--- [DEBUG] Listando hilos con filtros: {filters} ---")
        return await super().list_threads(pagination, filters)

    # Función para verificar si el usuario existe en la base de datos
    async def get_user(self, identifier: str):
        # print(f"--- [DEBUG] Buscando usuario: {identifier} ---")
        user = await super().get_user(identifier)
        # if user:
        #     print(f"--- [DEBUG] Usuario encontrado: {user.id} ({user.identifier}) ---")
        # else:
        #     print(f"--- [DEBUG] Usuario NO encontrado en BD ---")
        return user

# Inicialización de la Base de Datos
db_path = os.path.join(os.getcwd(), "chat_history.db")
print(f"--- [SISTEMA] Base de datos de historial en: {db_path} ---")

# Asignamos nuestra capa de datos personalizada a Chainlit
cl.data_layer = DebugSQLAlchemyDataLayer(
    conninfo=f"sqlite+aiosqlite:///{db_path}", 
    show_logger=False,
    storage_provider=DummyStorageClient()
)
if cl.data_layer:
    print("--- [SISTEMA] Persistencia activada correctamente ---")

# --- SECCIÓN 2: AUTENTICACIÓN (LOGIN) ---
# Sistema simple que lee usuarios y contraseñas desde 'users.json'.

def load_users():
    """Carga la lista de usuarios permitidos desde el archivo JSON."""
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

@cl.password_auth_callback
async def auth_callback(username, password):
    """
    Función que Chainlit llama cuando alguien intenta loguearse.
    Verifica si el usuario y contraseña coinciden con 'users.json'.
    """
    users = load_users()
    expected_pass = users.get(username)
    if expected_pass and expected_pass == password:
        # Si es correcto, devuelve un usuario autorizado
        return cl.User(identifier=username, metadata={"role": "user"})
    return None

# --- SECCIÓN 3: INICIO DE CHAT Y ESTADO ---

@cl.on_chat_start
async def on_chat_start():
    """
    Se ejecuta CADA VEZ que se inicia una nueva sesión o se refresca la página.
    Aquí inicializamos las variables de memoria ("session") para este usuario.
    """
    # Inicializamos variables vacías en la sesión del usuario
    cl.user_session.set("history", [])              # Historial de mensajes para el LLM
    cl.user_session.set("ppt_pending", False)       # ¿Estamos pendientes de generar un PPT?
    cl.user_session.set("ppt_request_base", "")     # Petición base del PPT
    cl.user_session.set("ppt_questions", [])        # Preguntas de clarificación pendientes
    cl.user_session.set("ppt_clarifications_sent", False) 

    # Estado del "Router" (cerebro decisor) para recordar contexto entre mensajes
    cl.user_session.set(
        "router_state",
        {
            "last_focus": None,
            "last_empresa_query": None,
            "last_empresa_nif": None,
            "last_contratos": [],
            "last_capitulos": [],
            "last_table_markdown": None, # Para recordar tablas y responder sobre ellas
            "last_extractos": [],
            "last_doc_tipo": None,
            "last_extracto_tipos": None,
        },
    )

    if cl.context.session.thread_id:
        print(f"--- [SISTEMA] Chat iniciado. ID de Hilo: {cl.context.session.thread_id} ---")

    # Enviamos el mensaje de bienvenida con "acciones" (botones de acceso rápido)
    await cl.Message(
        content=(
            "Hola. Soy el asistente virtual del área de contratación de la Diputación Provincial de Huelva.\n\n"
            "Puedo:\n"
            "- Responder preguntas y mostrar evidencias.\n"
            "- Consultar adjudicaciones por empresa (por nombre, y CIF si aplica).\n"
            "- Generar un PPT (te preguntaré si falta contexto) y descargarlo en Word.\n\n"
            "Pruébame:"
        ),
        actions=[
            cl.Action(
                name="quick_prompt",
                label="¿Qué contratos ha ganado Techfriendly?",
                payload={"text": "¿Qué contratos ha ganado Techfriendly?"},
            ),
            cl.Action(
                name="quick_prompt",
                label="Generar PPT vehículo 4x4",
                payload={"text": "¿Me haces un pliego de prescripciones técnicas para el suministro de un vehículo 4x4?"},
            ),
            cl.Action(
                name="quick_prompt",
                label="Top 10 empresas por importe adjudicado",
                payload={"text": "Top 10 adjudicatarias por importe adjudicado"},
            ),
        ],
    ).send()

    # Limpiamos la barra lateral de evidencias al empezar
    try:
        await clear_evidence_sidebar()
    except Exception:
        pass

@cl.on_chat_resume
async def on_chat_resume(thread):
    """
    CRÍTICO: Se ejecuta cuando un usuario pincha en una conversación antigua del historial.
    Sin esta función, Chainlit no muestra el historial porque no sabría cómo "reanudarlo".
    """
    print(f"--- [SISTEMA] Reanudando chat antiguo: {thread['id']} ---")
    # Aquí podríamos recuperar memoria específica si fuera necesario.
    # Por defecto, Chainlit ya carga los mensajes antiguos en la interfaz.
    cl.user_session.set("history", []) 
    # (El resto del estado se reinicia limpio, ya que es una nueva interacción sobre un chat viejo)

# --- SECCIÓN 4: GESTIÓN DE MENSAJES E INTERACCIONES ---

@cl.action_callback("quick_prompt")
async def quick_prompt(action: cl.Action):
    """
    Se ejecuta cuando el usuario pulsa un botón de acceso rápido (Action).
    Simula que el usuario ha escrito ese texto.
    """
    text = (action.payload or {}).get("text", "")
    if not text:
        return

    # Enviamos el mensaje a la interfaz como si fuera del usuario
    await cl.Message(content=text).send()
    # Y lo procesamos
    await on_message(cl.Message(content=text))

@cl.action_callback("follow_up_question")
async def on_follow_up_question(action: cl.Action):
    """
    Se ejecuta cuando el usuario pulsa una 'pregunta sugerida' (Follow-up).
    """
    payload = action.payload or {}
    q = payload.get("question")
    if not q:
        return
    await cl.Message(content=q).send()
    await on_message(cl.Message(content=q))

@cl.on_message
async def on_message(message: cl.Message):
    """
    FUNCIÓN PRINCIPAL: Se ejecuta cada vez que el usuario envía un mensaje de texto.
    """
    question = (message.content or "").strip()
    if not question:
        await cl.Message(content="No he recibido ninguna pregunta.").send()
        return

    # Usamos cl.Step para envolver el proceso.
    # Esto teóricamente ayuda a la persistencia automática, aunque usamos sincronización manual
    # en 'orchestrate_message' para asegurar que se guarda.
    async with cl.Step(name="Procesando", type="run") as step:
        step.input = question
        # Llamamos al Orquestador para que decida qué hacer con la pregunta
        await orchestrate_message(question)
