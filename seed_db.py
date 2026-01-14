import asyncio
import os
import uuid
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def seed_db():
    db_path = os.path.join(os.getcwd(), "chat_history.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    print(f"Seeding DB at: {url}")
    
    engine = create_async_engine(url)
    
    # IDs
    user_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    step_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat() + "Z"
    
    queries = [
        # Insert User ('admin') - Note: Chainlit uses identifier to match
        f"""
        INSERT INTO users ("id", "identifier", "createdAt", "metadata")
        VALUES ('{user_id}', 'admin', '{timestamp}', '{{}}');
        """,
        # Insert Thread
        f"""
        INSERT INTO threads ("id", "createdAt", "name", "userId", "userIdentifier", "tags", "metadata")
        VALUES ('{thread_id}', '{timestamp}', 'Test Conversation Manual', '{user_id}', 'admin', '[]', '{{}}');
        """,
        # Insert Step (Message)
        f"""
        INSERT INTO steps ("id", "name", "type", "threadId", "parentId", "streaming", "waitForAnswer", "isError", "metadata", "tags", "input", "output", "createdAt", "start", "end", "generation", "showInput", "language")
        VALUES ('{step_id}', 'User', 'user_message', '{thread_id}', NULL, 0, 0, 0, '{{}}', '[]', 'Hola seeded', 'Hola seeded', '{timestamp}', '{timestamp}', '{timestamp}', NULL, NULL, 'en');
        """
    ]

    async with engine.begin() as conn:
        for q in queries:
            try:
                print(f"Executing seed query...")
                await conn.execute(text(q))
            except Exception as e:
                print(f"Error seeding: {e}")
    
    print("Database seeded with test thread.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_db())
