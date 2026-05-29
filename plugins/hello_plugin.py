from src.infra.tools.base import tool, ToolCategory

@tool(
    name="say_hello",
    description="Say hello to a user with a custom message",
    category=ToolCategory.COMMUNICATION,
    parameters={
        "name": {"type": "string", "description": "Name of the person to greet"},
        "greeting": {"type": "string", "description": "The greeting message", "default": "Hello"}
    }
)
async def say_hello(name: str, greeting: str = "Hello") -> str:
    """A simple tool to say hello."""
    return f"{greeting}, {name}! I am Amadeus, your local agentic AI."

def register_tools(registry):
    """Explicit registration hook (optional if using @tool)."""
    # This is called by ToolRegistry.discover_plugins
    pass
