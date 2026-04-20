import asyncio
import logging
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add current dir to path
sys.path.append(os.getcwd())

from src.app.services.amadeus_service import AmadeusService
from src.app.services.tool_registry import ToolRegistry
from src.core.config import Settings

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def test_semantic_routing():
    print("\n" + "="*60)
    print("      AMADEUS SEMANTIC ROUTING VERIFICATION")
    print("="*60 + "\n")

    # 1. Setup minimal mock environment
    settings = MagicMock(spec=Settings)
    settings.GEMINI_API_KEY = "mock_key"
    settings.GEMINI_MODEL = "gemini-1.5-flash"
    settings.BASE_DIR = os.getcwd()
    settings.CHROMA_ENABLED = False
    settings.LOCAL_ONLY_MODE = True
    
    # Mock LLMRouter
    mock_router = AsyncMock()
    
    # Initialize Service
    # We bypass full init to avoid DB/Redis/Qdrant issues
    with MagicMock() as mock_qdrant:
        service = AmadeusService(settings=settings, llm_router=mock_router, auto_start_orchestrator=False)
    
    # 2. Test Tools Menu Generation
    print("[STEP 1] Verifying Tool Menu Generation...")
    menu = service.tool_registry.get_tools_menu()
    tool_count = len(service.tool_registry)
    print(f"  - Tools found in registry: {tool_count}")
    print(f"  - Menu Sample (first 200 chars):\n{menu[:200]}...")
    if tool_count > 0 and len(menu) > 50:
        print("  ✅ Tool Menu looks valid.\n")
    else:
        print("  ❌ Tool Menu appears empty or too short!\n")

    # 3. Test Triage Logic with Mocks
    test_cases = [
        {
            "query": "Check my unread emails from John",
            "mock_llm_response": "ACTION: read_unread_emails",
            "expected_intent": "tool",
            "expected_tool": "read_unread_emails"
        },
        {
            "query": "Hi Amadeus, how are you today?",
            "mock_llm_response": "ACTION: conversational",
            "expected_intent": "conversational",
            "expected_tool": None
        },
        {
            "query": "Write a 2000-word deep dive into the impact of quantum computing on modern cryptography",
            "mock_llm_response": "ACTION: cloud_escalation",
            "expected_intent": "cloud_escalation",
            "expected_tool": None
        }
    ]

    print("[STEP 2] Verifying Triage Logic (Mocked LLM Outcomes)...")
    for case in test_cases:
        query = case["query"]
        mock_router.generate.return_value = (case["mock_llm_response"], "LlamaCpp")
        
        print(f"  - Query: '{query}'")
        intent, tool = await service._predict_intent_llm(query)
        print(f"    -> Intent: {intent}, Tool: {tool}")
        
        if intent == case["expected_intent"] and tool == case["expected_tool"]:
            print(f"    ✅ PASS")
        else:
            print(f"    ❌ FAIL (Expected {case['expected_intent']}, {case['expected_tool']})")

    # 4. Test Integration Flow (Bypassing actual execution)
    print("\n[STEP 3] Verifying Internal Path Branching...")
    
    # We mock _generate_conversational_response to avoid real LLM calls
    service._generate_conversational_response = AsyncMock(return_value="Mocked response")
    service._extract_args_for_tool = AsyncMock(return_value={})
    service.tool_executor.execute = AsyncMock()
    
    # Scenario: Cloud Escalation
    print("  - Testing Cloud Escalation flow...")
    mock_router.generate.return_value = ("ACTION: cloud_escalation", "LlamaCpp")
    await service._process_command_internal("Complex math proof")
    
    # Check if we forced high complexity
    service._generate_conversational_response.assert_called_with("Complex math proof", forced_complexity="high")
    print("    ✅ PASS: Correctly forced 'high' complexity for escalation.\n")

    print("="*60)
    print("      VERIFICATION COMPLETE")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(test_semantic_routing())
