import traceback
from google import genai
from google.genai import types

client = genai.Client(api_key='fake')
tools = [{'function_declarations': [{'name': 'test', 'description': 'desc', 'parameters': {'type': 'object', 'properties': {}}}]}]
config = types.GenerateContentConfig(tools=tools)

try:
    client.models.generate_content(model='gemini-2.5-flash', contents='hi', config=config)
except Exception as e:
    print(traceback.format_exc())
