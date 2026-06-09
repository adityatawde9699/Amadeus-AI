import asyncio
import os
import sys

from src.container import global_container

async def main():
    # Setup simple environment
    os.environ["ENV"] = "development"
    os.environ["LOCAL_ONLY_MODE"] = "True"
    os.environ["LLM_PROVIDER"] = "llama"
    
    amadeus = global_container.amadeus_service()
    
    # We'll just test the graph execution directly
    from src.core.domain.context import RequestContext
    from src.core.domain.models import PermissionProfile
    
    ctx = RequestContext(
        request_id="test-1",
        session_id="test-session",
        user_id="test-user",
        permissions=PermissionProfile.SYSTEM_FULL
    )
    
    print("Executing query via LangGraph...")
    result = await amadeus.graph.ainvoke(
        task="What time is it?",
        context=ctx,
    )
    print("Success:", result.success)
    print("Final answer:", result.final_answer)

if __name__ == "__main__":
    asyncio.run(main())
