import joblib
import sys

try:
    vectorizer = joblib.load("Model/tfidf_vectorizer.joblib")
    classifier = joblib.load("Model/svm_classifier.joblib")
    text = "open vlc"
    x = vectorizer.transform([text])
    pred = classifier.predict(x)
    print(f"Prediction for '{text}': {pred[0]}")
except Exception as e:
    print(f"Error: {e}")
