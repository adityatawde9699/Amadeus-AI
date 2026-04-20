import os
import re

def extract_tools(directory):
    tools = []
    # Pattern to match @tool(name="...", description="...")
    # Note: Handles optional whitespace and single/double quotes
    tool_regex = re.compile(
        r'@tool\s*\(\s*name\s*=\s*["\']([^"\']+)["\']\s*,\s*description\s*=\s*["\']([^"\']+)["\']',
        re.DOTALL
    )

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py') and file != 'base.py':
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    matches = tool_regex.findall(content)
                    for name, desc in matches:
                        tools.append({"name": name, "description": desc})
    return tools

if __name__ == "__main__":
    tools = extract_tools('src/infra/tools')
    print(f"Total Tools Found: {len(tools)}")
    for t in sorted(tools, key=lambda x: x['name']):
        print(f"{t['name']}|{t['description']}")
