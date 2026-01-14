"""
HERRAMIENTA EXTRA: force_db_init.py
DESCRIPCIÓN:
Script alternativo para forzar la creación de tablas usando directamente la definición de modelos de Chainlit.
Normalmente usamos 'create_tables.py', pero este script es útil para depurar si falla la estructura de Usuarios.
"""

import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from chainlit.data.sql_alchemy import User  # Modelo de Usuario interno de Chainlit
from sqlalchemy.schema import CreateTable

async def init_db():
    db_path = os.path.join(os.getcwd(), "chat_history.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    print(f"--- [SISTEMA] Inicializando BD (Modo Forzado) en: {url} ---")
    
    engine = create_async_engine(url)
    
    # Comprobación de seguridad
    if not hasattr(User, "metadata"):
        print("--- [ERROR] La clase User no tiene metadatos. Algo va mal con Chainlit. ---")
        return

    print("--- [SISTEMA] Creando tablas desde modelos SQLAlchemy... ---")
    async with engine.begin() as conn:
        # Crea todas las tablas definidas en los modelos importados
        await conn.run_sync(User.metadata.create_all)
    
    print("--- [SISTEMA] Proceso completado. ---")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_db())
