import asyncio
import logging
import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter
from src.app.services.tool_registry import ToolRegistry
from src.container import _build_tool_registry
from src.core.config import get_settings

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def test_live_routing():
    print("\n" + "="*60)
    print("      LIVE AMADEUS SEMANTIC ROUTING TEST")
    print("      (Uses actual local model path)")
    print("="*60 + "\n")

    settings = get_settings()
    if not settings.SLM_MODEL_PATH or not os.path.exists(settings.SLM_MODEL_PATH):
        print(f"❌ ERROR: Local model not found at {settings.SLM_MODEL_PATH}")
        return

    # 1. Initialize Components
    print("[1/3] Initializing Tool Registry and Local Model...")
    registry = _build_tool_registry()
    tools_menu = registry.get_tools_menu()
    
    adapter = LlamaCppAdapter(
        model_path=settings.SLM_MODEL_PATH,
        threads=settings.SLM_THREADS,
        context_length=4096 # Allow for large tool menus
    )
    
    # 2. Test Cases
    test_queries = [
        "check my emails for any unread messages",
        "Hi Amadeus, what time is it?",
        "Explain the mathematical proof of the Riemann Hypothesis and its implications for cryptography."
    ]

    print("\n[2/3] Executing Triage Queries via Local LLM...")
    
    for query in test_queries:
        print(f"\nQUERY: '{query}'")
        
        # Construct the exact prompt AmadeusService uses
        triage_prompt = f"""### Instructions
You are the semantic router for Amadeus AI. Your job is to classify the user's request.

### Available Tools
{tools_menu}

### Decision Rules
1. If the request matches a tool description, output: ACTION: [tool_name]
2. If it is a greeting, simple question, or general chat, output: ACTION: conversational
3. If it is highly complex (advanced coding, math, philosophy, policy), output: ACTION: cloud_escalation

### User Input
{query}

### Decision
"""
        try:
            print("  Thinking...")
            response = await adapter.generate_response(
                prompt=triage_prompt,
                temperature=0.0,
                max_tokens=20
            )
            print(f"  RESPONSE: {response.strip()}")
            
            # Simple validation
            clean_res = response.strip().upper()
            if "ACTION:" in clean_res:
                print("  ✅ VALID TRIAGE FORMAT")
            else:
                print("  ⚠️ UNEXPECTED FORMAT (Model might need a better prompt)")
                
        except Exception as e:
            print(f"  ❌ FAILED: {e}")

    print("\n" + "="*60)
    print("      LIVE TEST COMPLETE")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(test_live_routing())
