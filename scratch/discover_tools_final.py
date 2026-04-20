import os
import sys
import asyncio
from typing import Any
from unittest.mock import MagicMock

# Add current directory to sys.path
sys.path.append(os.getcwd())

# Mock settings completely
import src.core.config
src.core.config.get_settings = MagicMock()

def discover_all_tool_metadata():
    tool_data = []
    
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
                        "name": str(t.name),
                        "description": str(t.description),
                        "category": mod_path.split('.')[-1],
                        "parameters": t.parameters
                    })
            
            # Pattern 2: build_*_tools() (Dictionaries)
            builder = getattr(mod, f"build_{func_name}_tools", None)
            if builder:
                try:
                    # Mock repositories if needed
                    tools = builder(MagicMock()) if "productivity" in mod_path or "filesystem" in mod_path else builder()
                    for t in tools:
                        if isinstance(t, dict):
                            tool_data.append({
                                "name": str(t.get("name")),
                                "description": str(t.get("description")),
                                "category": mod_path.split('.')[-1],
                                "parameters": t.get("parameters", {})
                            })
                        else:
                            tool_data.append({
                                "name": str(t.name),
                                "description": str(t.description),
                                "category": mod_path.split('.')[-1],
                                "parameters": t.parameters
                            })
                except Exception:
                    pass
        except Exception:
            pass

    # Special handling for email and web research
    try:
        from src.infra.tools.email_tools import build_email_tools
        from src.infra.tools.web_research_tools import build_web_research_tools
        
        for t in build_email_tools():
            tool_data.append({"name": str(t["name"]), "description": str(t["description"]), "category": "email_tools", "parameters": t.get("parameters", {})})
        for t in build_web_research_tools():
            tool_data.append({"name": str(t["name"]), "description": str(t["description"]), "category": "web_research_tools", "parameters": t.get("parameters", {})})
    except Exception:
        pass

    return tool_data

if __name__ == "__main__":
    tools = discover_all_tool_metadata()
    # Remove duplicates by name
    unique_tools = {}
    for t in tools:
        if t['name'] and t['name'] != 'None':
            unique_tools[t['name']] = t
    
    final_list = sorted(unique_tools.values(), key=lambda x: x['name'])
    print(f"TOTAL_UNIQUE_TOOLS: {len(final_list)}")
    for t in final_list:
        print(f"|{t['name']}|{t['category']}|{t['description']}|")
