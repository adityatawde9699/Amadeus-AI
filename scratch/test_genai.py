import traceback
from google import genai
from google.genai import types

client = genai.Client(api_key='fake')
config = types.GenerateContentConfig(
    temperature=0.7, 
    max_output_tokens=4096, 
    system_instruction='test'
)
try:
    client.models.generate_content(
        model='gemini-2.5-flash', 
        contents='hi', 
        config=config
    )
except Exception as e:
    print(traceback.format_exc())
