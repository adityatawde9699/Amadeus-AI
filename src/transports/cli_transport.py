import asyncio
import sys
import uuid
import logging
from src.core.config import get_settings
from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.runtime.core import AmadeusRuntime

# Configure logging for CLI
logging.basicConfig(level=logging.INFO, format="%(message)s")

async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.transports.cli_transport <message>")
        sys.exit(1)
        
    input_text = " ".join(sys.argv[1:])
    settings = get_settings()
    
    runtime = AmadeusRuntime(settings)
    await runtime.start()
    
    context = RequestContext(
        request_id=str(uuid.uuid4()),
        session_id="cli_session",
        user_id="cli_user",
        permissions=PermissionProfile.SYSTEM_FULL,
        memory_scope="global",
        trace_id=str(uuid.uuid4()),
        cancellation_token=asyncio.Event()
    )
    
    print(f"\n[User]: {input_text}")
    print("[Amadeus]: ", end="", flush=True)
    
    try:
        response = await runtime.process_task(context, input_text)
        print(response)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await runtime.stop()

if __name__ == "__main__":
    asyncio.run(main())
