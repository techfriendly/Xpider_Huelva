"""
HERRAMIENTA: create_tables.py
DESCRIPCIÓN:
Script para INICIALIZAR LA BASE DE DATOS (SQLite).
Crea las tablas necesarias para guardar la información del chat si no existen.
TABLAS:
1. users: Usuarios registrados.
2. threads: Hilos de conversación.
3. steps: Pasos (mensajes) dentro de una conversación.
4. feedbacks: Votos o comentarios (like/dislike) de los usuarios.
5. elements: Archivos adjuntos o imágenes.
"""

import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def create_tables():
    # Ruta de la base de datos (chat_history.db en la carpeta actual)
    db_path = os.path.join(os.getcwd(), "chat_history.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    print(f"--- [SISTEMA] Creando tablas en: {url} ---")
    
    # Motor de conexión asíncrono
    engine = create_async_engine(url)
    
    # Sentencias SQL para definir la estructura de las tablas
    queries = [
        # TABLA DE USUARIOS
        """
        CREATE TABLE IF NOT EXISTS users (
            "id" TEXT PRIMARY KEY,          -- Identificador único interno
            "identifier" TEXT NOT NULL UNIQUE, -- Nombre de usuario (ej: admin)
            "createdAt" TEXT NOT NULL,      -- Fecha de creación
            "metadata" TEXT                 -- Datos extra (JSON)
        );
        """,
        # TABLA DE HILOS (CONVERSACIONES)
        """
        CREATE TABLE IF NOT EXISTS threads (
            "id" TEXT PRIMARY KEY,
            "createdAt" TEXT,
            "name" TEXT,                    -- Título del chat
            "userId" TEXT,                  -- Dueño del chat
            "userIdentifier" TEXT,
            "tags" TEXT,                    -- Etiquetas
            "metadata" TEXT
        );
        """,
        # TABLA DE PASOS (MENSAJES)
        """
        CREATE TABLE IF NOT EXISTS steps (
            "id" TEXT PRIMARY KEY,
            "name" TEXT NOT NULL,           -- Quien habla (User, Assistant)
            "type" TEXT NOT NULL,           -- Tipo (user_message, assistant_message, run, tool)
            "threadId" TEXT NOT NULL,       -- A qué hilo pertenece
            "parentId" TEXT,                -- Si es hijo de otro paso (ej: pensamiento dentro de un paso)
            "streaming" BOOLEAN,
            "waitForAnswer" BOOLEAN,
            "isError" BOOLEAN,
            "metadata" TEXT,
            "tags" TEXT,
            "input" TEXT,                   -- Entrada (lo que entra al paso)
            "output" TEXT,                  -- Salida (el mensaje de texto final)
            "createdAt" TEXT,
            "start" TEXT,
            "end" TEXT,
            "generation" TEXT,
            "showInput" TEXT,
            "language" TEXT,
            FOREIGN KEY("threadId") REFERENCES threads("id") ON DELETE CASCADE
        );
        """,
        # TABLA DE FEEDBACK (LIKES)
        """
        CREATE TABLE IF NOT EXISTS feedbacks (
            "id" TEXT PRIMARY KEY,
            "forId" TEXT NOT NULL,
            "value" INTEGER NOT NULL,       -- +1 (Like), -1 (Dislike)
            "comment" TEXT
        );
        """,
        # TABLA DE ELEMENTOS (ARCHIVOS/IMÁGENES)
        """
        CREATE TABLE IF NOT EXISTS elements (
            "id" TEXT PRIMARY KEY,
            "threadId" TEXT,
            "type" TEXT,
            "url" TEXT,
            "chainlitKey" TEXT,
            "objectKey" TEXT,
            "name" TEXT,
            "display" TEXT,
            "size" TEXT,
            "language" TEXT,
            "page" INTEGER,
            "forId" TEXT,
            "mime" TEXT,
            "props" TEXT,
            "autoPlay" BOOLEAN,
            "playerConfig" TEXT
        );
        """
    ]

    # Ejecutamos las consultas una por una
    async with engine.begin() as conn:
        for q in queries:
            # Imprimimos qué está haciendo (solo la primera línea para no ensuciar)
            print(f"Ejecutando SQL: {q.strip().splitlines()[0]}...")
            await conn.execute(text(q))
    
    print("--- [SISTEMA] Tablas creadas/verificadas correctamente. ---")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(create_tables())
