
import sys
import os
from pathlib import Path

# Add root to sys.path
sys.path.append(str(Path("c:/Users/ASUS/Downloads/Amadeus-AI").resolve()))
os.environ["BASE_DIR"] = "c:/Users/ASUS/Downloads/Amadeus-AI"

try:
    from src.infra.llm.router import ComplexityScorer, LLMRouter
    from src.core.config import get_settings
    
    scorer = ComplexityScorer()
    settings = get_settings()
    
    print(f"--- VERIFICATION ---")
    print(f"SLM_CTX_SIZE: {settings.SLM_CTX_SIZE}")
    
    prompt = "write a code for RAG"
    level, score = scorer.score(prompt)
    print(f"Prompt: '{prompt}'")
    print(f"  Level: {level}, Score: {score}")
    
    # Check if a long prompt would still be within the new limit
    long_prompt = "A" * 8000 # ~2000 tokens
    level_long, score_long = scorer.score(long_prompt)
    print(f"Long Prompt (~2000 tokens): Level={level_long}, Score={score_long}")
    
    # Verify the router Constants
    print(f"Router _LLAMA_CTX_LIMIT: {LLMRouter._LLAMA_CTX_LIMIT}")
    
    if level == "high":
        print("SUCCESS: RAG identified as high complexity.")
    else:
        print("FAILURE: RAG NOT identified as high complexity.")

    if LLMRouter._LLAMA_CTX_LIMIT == 4096:
        print("SUCCESS: Router CTX limit increased to 4096.")
    else:
        print("FAILURE: Router CTX limit is still", LLMRouter._LLAMA_CTX_LIMIT)

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
