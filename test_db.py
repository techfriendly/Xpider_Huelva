import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def test_connection():
    db_path = os.path.join(os.getcwd(), "chat_history.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    print(f"Testing URL: {url}")
    
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            # Check users
            print("--- Users ---")
            result = await conn.execute(text("SELECT * FROM users;"))
            for row in result.fetchall():
                print(row)
            
            # Check threads
            print("--- Threads ---")
            result = await conn.execute(text("SELECT * FROM threads;"))
            for row in result.fetchall():
                print(row)
        await engine.dispose()
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
