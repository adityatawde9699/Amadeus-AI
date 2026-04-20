import asyncio
import logging
from unittest.mock import MagicMock, AsyncMock

# Minimal mocks to avoid importing the whole app
class MockTool:
    def __init__(self, name, description):
        self.name = name
        self.description = description
        self.category = MagicMock()
        self.category.value = "test"

async def test_isolated_routing():
    print("\n" + "="*60)
    print("      ISOLATED AMADEUS ROUTING VERIFICATION")
    print("="*60 + "\n")

    # 1. Setup a clean ToolRegistry
    print("[1/3] Initializing isolated ToolRegistry...")
    from src.app.services.tool_registry import ToolRegistry
    registry = ToolRegistry()
    
    # Register some key tools manually to simulate a real environment
    registry.register(MockTool("send_email", "Send an email message to a recipient."))
    registry.register(MockTool("read_unread_emails", "Check and read unread emails from the inbox."))
    registry.register(MockTool("get_weather", "Get current weather for a city."))
    
    menu = registry.get_tools_menu()
    print(f"  - Generated Tool Menu:\n{menu}")
    
    if "send_email" in menu and "read_unread_emails" in menu:
        print("  [PASS] Tool Menu Generation")
    else:
        print("  [FAIL] Tool Menu Generation")

    # 2. Test the Triage Parsing Logic (Isolated)
    print("\n[2/3] Verifying Triage Parsing Logic...")
    
    # We'll simulate the _predict_intent_llm logic but without the full service
    async def simulate_triage(query, mock_response):
        # This is the same logic I added to AmadeusService
        clean_res = mock_response.strip().upper()
        if "ACTION: CLOUD_ESCALATION" in clean_res:
            return "cloud_escalation", None
        if "ACTION: CONVERSATIONAL" in clean_res:
            return "conversational", None
        
        # Check for tool name
        for t_name in registry.list_names():
            if t_name.upper() in clean_res:
                return "tool", t_name
        return "conversational", None

    # Test cases
    scenarios = [
        ("Send email to John", "ACTION: send_email", ("tool", "send_email")),
        ("Hey Amadeus", "ACTION: conversational", ("conversational", None)),
        ("Write a PhD thesis", "ACTION: cloud_escalation", ("cloud_escalation", None)),
        ("Ambiguous input", "I think you should use send_email", ("tool", "send_email"))
    ]

    for query, response, expected in scenarios:
        result = await simulate_triage(query, response)
        if result == expected:
            print(f"  - Query: '{query}' -> {result} [PASS]")
        else:
            print(f"  - Query: '{query}' -> {result} [FAIL] (Expected {expected})")

    # 3. Prompt Construction Check
    print("\n[3/3] Prompt Construction Check...")
    triage_prompt = f"""### Instructions
You are the semantic router for Amadeus AI.

### Available Tools
{menu}

### User Input
Check for emails
"""
    print(f"  - Triage Prompt size: {len(triage_prompt)} characters")
    if len(triage_prompt) < 1000:
        print("  [PASS] Prompt Efficiency (Fits well in local context)")
    else:
        print("  [WARNING] Prompt Efficiency: Large list might slow down local model.")

    print("\n" + "="*60)
    print("      ISOLATED VERIFICATION COMPLETE")
    print("="*60 + "\n")

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.getcwd())
    asyncio.run(test_isolated_routing())
