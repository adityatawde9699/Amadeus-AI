"""
Train the TF-IDF + SVM tool classifier.
Loads training_data.json and saves models to the Model/ directory.
"""
import json
import os
import sys
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score
import numpy as np

def main():
    # Setup paths
    project_root = Path(__file__).parent.parent
    data_path = project_root / "data" / "training_data.json"
    model_dir = project_root / "Model"
    
    if not data_path.exists():
        print(f"Error: {data_path} not found. Run generate_training_data.py first.")
        sys.exit(1)
        
    print(f"Loading training data from {data_path}...")
    with open(data_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    texts = [item["text"] for item in dataset]
    labels = [item["label"] for item in dataset]
    
    print(f"Loaded {len(texts)} examples across {len(set(labels))} classes: {set(labels)}")
    
    # Create the pipeline
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2)
    classifier = LinearSVC(C=1.0, dual=False, max_iter=2000)
    
    pipeline = Pipeline([
        ('vectorizer', vectorizer),
        ('classifier', classifier)
    ])
    
    # Evaluate with 5-fold cross-validation
    print("Evaluating model with 5-fold cross-validation...")
    scores = cross_val_score(pipeline, texts, labels, cv=5)
    mean_accuracy = np.mean(scores)
    
    print(f"Cross-validation accuracy: {mean_accuracy:.4f} (+/- {np.std(scores) * 2:.4f})")
    
    if mean_accuracy < 0.85:
        print("Error: Model accuracy below 85% threshold. Training failed.")
        sys.exit(1)
        
    print("Training final model on all data...")
    # Train separate vectorizer and classifier to save as separate joblib files
    # to match AmadeusService expectations
    vectorizer.fit(texts)
    X = vectorizer.transform(texts)
    classifier.fit(X, labels)
    
    # Ensure Model directory exists
    model_dir.mkdir(exist_ok=True)
    
    # Save the models
    vectorizer_path = model_dir / "tfidf_vectorizer.joblib"
    classifier_path = model_dir / "svm_classifier.joblib"
    
    joblib.dump(vectorizer, vectorizer_path)
    joblib.dump(classifier, classifier_path)
    
    print(f"Successfully saved models to:")
    print(f"- {vectorizer_path}")
    print(f"- {classifier_path}")

if __name__ == "__main__":
    main()
