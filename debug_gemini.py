import asyncio
import logging
import sys
import traceback

# Setup basic logging to see the output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_debug():
    print("--- Starting Debug Session ---")
    try:
        from src.app.services.amadeus_service import AmadeusService
        from src.core.config import Settings
        
        # Initialize service with minimal settings if needed, or let it load from env
        service = AmadeusService(debug_mode=True)
        await service.initialize()
        
        print("\n--- Service Initialized ---\n")
        
        # Test command that triggers tool usage (time)
        query = "What time is it?"
        print(f"Sending query: '{query}'")
        
        response = await service.handle_command(query)
        
        print(f"\nResponse: {response}")
        
    except Exception as e:
        print("\n!!! CRITICAL ERROR CAUGHT IN MAIN !!!")
        print(f"Type: {type(e)}")
        print(f"Repr: {repr(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    # Ensure src is in path
    import os
    sys.path.append(os.getcwd())
    
    asyncio.run(run_debug())
