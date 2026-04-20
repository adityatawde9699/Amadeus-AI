import asyncio
import logging
import sys
import os

# Set up logging to avoid spam but see errors
logging.basicConfig(level=logging.ERROR)

# Add current dir to path
sys.path.append(os.getcwd())

from src.app.services.amadeus_service import AmadeusService
from src.infra.llm.router import ComplexityScorer

async def test_routing():
    print("--- AMADEUS ROUTING & COMPLEXITY TEST ---")
    
    # Initialize service without full DI container startup to avoid missing dependency errors
    service = AmadeusService(session_id='test_sess', auto_start_orchestrator=False)
    
    # Debug paths
    vectorizer_path = str(service.settings.BASE_DIR / "Model" / "tfidf_vectorizer.joblib")
    print(f"DEBUG: Vectorizer expected at: {os.path.abspath(vectorizer_path)}")
    print(f"DEBUG: File exists? {os.path.exists(vectorizer_path)}")
    
    # Manually load the classifier specifically for this test
    service._load_tool_classifier()
    print(f"DEBUG: Loaded classes: {list(service.classifier.classes_)}")
    print(f"DEBUG: Number of classes: {len(service.classifier.classes_)}")
    
    scorer = ComplexityScorer()
    
    queries = [
        "check my inbox and read unread emails please",
        "send an email to adityatawde9699@gmail.com with subject 'test mail' and body 'this is a test'",
        "search the web for news about technology",
        "calculate 50 plus 100",
        "write a 500 word essay about the future of AI ethics and global policy"
    ]
    
    for q in queries:
        print(f"\nQUERY: '{q}'")
        
        # 1. Test Complexity
        level, score = scorer.score(q)
        print(f"  [Complexity] Score: {score}, Level: {level}")
        
        # 2. Test SVM
        if level == "high":
            print("  [SVM] Bypass: Triggered (High Complexity)")
        else:
            prediction = service._predict_relevant_tools(q)
            print(f"  [SVM] Prediction: {prediction[0]}")

if __name__ == "__main__":
    asyncio.run(test_routing())
