from src.infra.tools.base import Tool, ToolCategory

async def my_custom_logic(a: int, b: int) -> str:
    return f"The sum of {a} and {b} is {a + b}, calculated by a dynamic plugin!"

def register_tools(registry):
    """Explicitly register tools using the registry object."""
    tool = Tool(
        name="sum_plugin",
        function=my_custom_logic,
        description="Calculate sum of two numbers using a custom plugin",
        category=ToolCategory.CALCULATION,
        parameters={
            "a": {"type": "integer", "description": "First number"},
            "b": {"type": "integer", "description": "Second number"}
        }
    )
    registry.register(tool)
