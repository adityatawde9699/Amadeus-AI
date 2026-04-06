"""
Trains a lightweight Scikit-Learn SVM classifier for the AgentOrchestrator.

This script generates `router_vectorizer.joblib` and `router_classifier.joblib`
which are used to predict the correct sub-agent ("system", "research", "general")
based on the user's input text rapidly without using LLM quotas.
"""

import logging
import os

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Basic training dataset mapping queries to target agents
TRAINING_DATA = {
    # System Operations Agent
    "open chrome": "system",
    "close the calculator": "system",
    "turn up the volume": "system",
    "dim the screen": "system",
    "open my vscode": "system",
    "what is my battery level": "system",
    "check system memory": "system",
    "cpu usage": "system",
    "take a screenshot": "system",
    "lock the computer": "system",
    "open telegram": "system",
    "shut down the computer": "system",
    # Research & Data Agent
    "what is the weather like in london": "research",
    "check the news today": "research",
    "summarize this article": "research",
    "tell me about quantum physics": "research",
    "will it rain tomorrow": "research",
    "find information about the french revolution": "research",
    "read this document": "research",
    "is it hot outside": "research",
    "what are the latest headlines": "research",
    "translate this text": "research",
    # General / Conversational Agent (Fallback)
    "hello": "general",
    "how are you": "general",
    "tell me a joke": "general",
    "what is the meaning of life": "general",
    "help me plan my day": "general",
    "add milk to my shopping list": "general",
    "what time is it": "general",
    "set a timer for 5 minutes": "general",
    "remind me to call mom": "general",
    "what is your name": "general",
    "can you help me with a task": "general",
}


def train_router():
    """Trains the tf-idf vectorizer and linear SVC model."""
    logger.info("Initializing Agent Router training...")

    texts = list(TRAINING_DATA.keys())
    labels = list(TRAINING_DATA.values())

    logger.info(f"Loaded {len(texts)} training samples over {len(set(labels))} classes.")

    # Create TF-IDF Vectorizer
    # ngram_range=(1,2) ensures we capture combinations like "open chrome" as well as individual words
    vectorizer = TfidfVectorizer(lowercase=True, stop_words="english", ngram_range=(1, 2))

    try:
        X = vectorizer.fit_transform(texts)
    except Exception as e:
        logger.error(f"Failed to vectorize text: {e}")
        return

    # Create and train classifier
    classifier = LinearSVC(random_state=42, dual="auto")
    try:
        classifier.fit(X, labels)
        logger.info("Model successfully fitted.")
    except Exception as e:
        logger.error(f"Failed to train classifier: {e}")
        return

    # Ensure output directory exists
    os.makedirs("Model", exist_ok=True)

    # Save models
    vectorizer_path = "Model/router_vectorizer.joblib"
    classifier_path = "Model/router_classifier.joblib"

    try:
        joblib.dump(vectorizer, vectorizer_path)
        joblib.dump(classifier, classifier_path)
        logger.info(f"Models saved successfully to:\n- {vectorizer_path}\n- {classifier_path}")
    except Exception as e:
        logger.error(f"Failed to save models: {e}")


if __name__ == "__main__":
    train_router()
