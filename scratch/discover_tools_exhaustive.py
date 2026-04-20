import os
import sys
import asyncio
from typing import Any

# Add current directory to sys.path
sys.path.append(os.getcwd())

# Mock get_settings and other dependencies to prevent init failures
from unittest.mock import MagicMock
import src.core.config
src.core.config.get_settings = MagicMock()

def discover_all_tool_metadata():
    tool_data = []
    
    # List of modules to scan
    modules = [
        "src.infra.tools.info_tools",
        "src.infra.tools.system_tools",
        "src.infra.tools.monitor_tools",
        "src.infra.tools.productivity_tools",
        "src.infra.tools.filesystem_tools",
        "src.infra.tools.developer_tools",
        "src.infra.tools.office_tools",
        "src.infra.tools.slack_tools",
        "src.infra.tools.agent_tools"
    ]
    
    for mod_path in modules:
        try:
            import importlib
            mod = importlib.import_module(mod_path)
            
            # Pattern 1: get_*_tools()
            func_name = mod_path.split('.')[-1].replace('_tools', '')
            getter = getattr(mod, f"get_{func_name}_tools", None)
            if getter:
                for t in getter():
                    tool_data.append({
                        "name": t.name,
                        "description": t.description,
                        "category": t.category.value if hasattr(t.category, 'value') else str(t.category),
                        "parameters": t.parameters
                    })
            
            # Pattern 2: build_*_tools() (Dictionaries)
            builder = getattr(mod, f"build_{func_name}_tools", None)
            if builder:
                # Some builders need repos, we mock them
                try:
                    tools = builder(MagicMock()) if "productivity" in mod_path else builder()
                    for t in tools:
                        if isinstance(t, dict):
                            tool_data.append({
                                "name": t.get("name"),
                                "description": t.get("description"),
                                "category": "custom",
                                "parameters": t.get("parameters", {})
                            })
                        else:
                            tool_data.append({
                                "name": t.name,
                                "description": t.description,
                                "category": t.category.value if hasattr(t.category, 'value') else str(t.category),
                                "parameters": t.parameters
                            })
                except Exception:
                    pass
        except Exception as e:
            print(f"Error loading {mod_path}: {e}")

    # Special handling for email and web research (not in standard patterns)
    try:
        from src.infra.tools.email_tools import build_email_tools
        from src.infra.tools.web_research_tools import build_web_research_tools
        
        for t in build_email_tools():
            tool_data.append({"name": t["name"], "description": t["description"], "category": "communication", "parameters": t.get("parameters", {})})
        for t in build_web_research_tools():
            tool_data.append({"name": t["name"], "description": t["description"], "category": "information", "parameters": t.get("parameters", {})})
    except Exception:
        pass

    return tool_data

if __name__ == "__main__":
    tools = discover_all_tool_metadata()
    print(f"DEBUG_TOOL_COUNT: {len(tools)}")
    for t in sorted(tools, key=lambda x: x['name']):
        print(f"NAME: {t['name']}")
        print(f"DESC: {t['description']}")
        print(f"CAT: {t['category']}")
        print(f"PARAMS: {t['parameters']}")
        print("-" * 20)
