
import sys
import os
from pathlib import Path

# Add root to sys.path
sys.path.append(str(Path("c:/Users/ASUS/Downloads/Amadeus-AI").resolve()))
os.environ["BASE_DIR"] = "c:/Users/ASUS/Downloads/Amadeus-AI"

try:
    from src.infra.llm.router import ComplexityScorer
    from src.app.services.amadeus_service import AmadeusService
    import joblib
    import numpy as np
    
    scorer = ComplexityScorer()
    
    prompts = [
        "write a code for RAG",
        "write a code for addition for three number",
        "addition for three number"
    ]
    
    print("--- COMPLEXITY SCORING ---")
    for p in prompts:
        level, score = scorer.score(p)
        print(f"Prompt: '{p}'")
        print(f"  Level: {level}, Score: {score}")
        
    print("\n--- SVM TOOL PREDICTION ---")
    # Try to load the model and predict
    model_dir = Path("c:/Users/ASUS/Downloads/Amadeus-AI/Model")
    v_path = model_dir / "tfidf_vectorizer.joblib"
    c_path = model_dir / "svm_classifier.joblib"
    
    if v_path.exists() and c_path.exists():
        vec = joblib.load(v_path)
        clf = joblib.load(c_path)
        
        for p in prompts:
            x_vec = vec.transform([p])
            scores = clf.decision_function(x_vec)[0]
            classes = clf.classes_
            top_idx = np.argsort(scores)[::-1]
            best_tool = classes[top_idx[0]]
            print(f"Prompt: '{p}' -> Best Tool: {best_tool} (Score: {scores[top_idx[0]]:.2f})")
    else:
        print("Models not found.")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
