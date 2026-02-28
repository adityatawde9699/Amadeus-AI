import asyncio
import logging
import sys

from src.core.config import get_settings
from src.app.services.proactive_service import run_proactive_checks

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def test():
    settings = get_settings()
    # Mock settings to trigger the logic
    settings.MASTER_TELEGRAM_CHAT_ID = "123456789"
    # settings.MASTER_WHATSAPP_NUMBER = "9876543210"
    
    print("Running proactive checks test...")
    await run_proactive_checks()
    print("Test completed.")

if __name__ == "__main__":
    asyncio.run(test())
