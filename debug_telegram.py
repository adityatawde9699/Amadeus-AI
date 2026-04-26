import asyncio
import logging

from src.container import global_container
from src.infra.messaging.telegram_adapter import TelegramAdapter

logging.basicConfig(level=logging.DEBUG)

async def main():
    # Initialize container manually
    try:
        from src.infra.persistence.database import init_db
        await init_db()
    except Exception as e:
        print("DB init error:", e)

    adapter = TelegramAdapter()
    
    chat_id = 123456789
    text = "hey I am Aditya S. Tawde"
    
    print("Running background task...")
    await adapter._process_and_reply_background(chat_id, text)
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
