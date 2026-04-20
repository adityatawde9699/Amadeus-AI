
import sys
import os
from pathlib import Path

# Add root to sys.path
sys.path.append(str(Path("c:/Users/ASUS/Downloads/Amadeus-AI").resolve()))
os.environ["BASE_DIR"] = "c:/Users/ASUS/Downloads/Amadeus-AI"

try:
    from src.core.config import get_settings
    from src.infra.llm.router import LLMRouter
    from src.infra.llm.groq_adapter import GroqAdapter
    from src.infra.llm.gemini_adapter import GeminiAdapter
    
    settings = get_settings()
    
    print("--- DIAGNOSTIC ---")
    print(f"GROQ_API_KEY present: {bool(settings.GROQ_API_KEY)}")
    print(f"GEMINI_API_KEY present: {bool(settings.GEMINI_API_KEY)}")
    
    groq = None
    if settings.GROQ_API_KEY:
        try:
            groq = GroqAdapter(api_key=settings.GROQ_API_KEY)
            print("GroqAdapter initialized successfully.")
        except Exception as e:
            print(f"GroqAdapter failed to init: {e}")
            
    gemini = None
    if settings.GEMINI_API_KEY:
        try:
            gemini = GeminiAdapter(api_key=settings.GEMINI_API_KEY)
            print("GeminiAdapter initialized successfully.")
        except Exception as e:
            print(f"GeminiAdapter failed to init: {e}")

    router = LLMRouter(groq=groq, gemini=gemini)
    print(f"Router providers: {list(router._providers.keys())}")
    
    prompt = "write a code for RAG"
    level, score = router._scorer.score(prompt)
    print(f"Prompt complexity: {level} ({score})")
    
    # Simulate building providers list (this is what I fixed earlier)
    providers_order = ["groq", "gemini", "openai", "llama_cpp", "ollama"]
    print(f"Effective priority: {[p for p in providers_order if p in router._providers]}")

except Exception as e:
    print(f"Diagnostic Error: {e}")
    import traceback
    traceback.print_exc()
