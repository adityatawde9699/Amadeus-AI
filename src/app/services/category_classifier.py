"""
Category Classifier for Amadeus AI — Stage 1 of the two-stage tool router.

Uses a TF-IDF vectorizer + LinearSVC to predict which ToolCategory a user
query belongs to. This collapses 50+ tools into a small candidate pool
(~5-12 tools) BEFORE the sentence-transformer similarity step runs.

Why TF-IDF + SVM instead of another transformer?
- Sub-millisecond inference — no GPU needed, no model load time
- Perfectly suited for short-text categorical classification
- Trivially re-trainable from code if categories change

Training data is embedded directly in this file as curated phrase lists,
one list per category. No separate dataset file is needed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Training Data — curated phrases per category
# Add more phrases to improve recall for under-performing categories.
# ---------------------------------------------------------------------------

TRAINING_DATA: dict[str, list[str]] = {
    "app_control": [
        # opening apps
        "open vlc", "launch chrome", "start word", "open notepad",
        "open calculator", "launch vs code", "start excel", "open file explorer",
        "launch discord", "open browser", "start photoshop", "open spotify",
        "run paint", "open task manager", "launch teams", "start powerpoint",
        "open whatsapp", "launch steam", "open zoom", "start obs",
        "open the music player", "run this application", "start this program",
        "open my default browser", "launch terminal", "open powershell",
        # closing apps
        "close spotify", "kill process", "terminate chrome", "quit app",
        "stop application", "end task", "force quit", "kill chrome",
        "close notepad", "terminate app", "exit this program", "shut down vlc",
        # scanning
        "scan apps", "find new apps", "discover installed programs",
        "refresh application list", "update app registry",
    ],
    "file_system": [
        # searching
        "find file report.pdf", "search for notes.txt", "where is my file",
        "locate resume.docx", "find all jpg files", "search file by name",
        "look for document", "where did I save the file",
        "find my homework file", "search for spreadsheet",
        # copying / moving
        "copy file to desktop", "move document to downloads", "duplicate file",
        "copy this to another folder", "move report to projects",
        "transfer this file to the other folder",
        # deleting
        "delete old file", "remove file", "trash this document",
        "delete this pdf", "remove the backup file",
        # creating folders
        "create folder projects", "make directory", "new folder",
        "make a new folder called work", "create a subdirectory",
        # reading/writing workspace files
        "list workspace files", "read this file", "write to a file",
        "show agent directory contents", "create a text file",
    ],
    "os_control": [
        # volume
        "set volume to 50", "increase volume", "mute audio", "unmute",
        "turn up the sound", "lower the volume", "volume 70 percent",
        "max volume", "silent mode", "what is the current volume",
        "make it louder", "turn down the music",
        # brightness
        "decrease brightness", "dim the screen", "set brightness 70",
        "increase brightness", "make screen brighter", "brightness 50 percent",
        "the screen is too bright", "lower screen brightness",
        # screenshot
        "take a screenshot", "capture screen", "screenshot", "print screen",
        "capture the current screen", "take screen capture",
        "snap a picture of my screen", "screengrab",
        # apps list
        "what programs are running", "list open windows", "show running apps",
        "what is currently open", "show open apps",
        "which applications are active", "running processes",
    ],
    "web_research": [
        # web search
        "search for python tutorials", "google this topic", "search online",
        "find information about machine learning", "look up history of india",
        "search the web for", "browse reddit", "open youtube",
        "search for latest python 3.13 features", "look up current news",
        "what happened in the world today", "find info about climate change",
        "search about this topic online", "look it up on the internet",
        "google who won the election", "search for best restaurants nearby",
        "find out about artificial intelligence", "research quantum physics",
        "what is trending right now", "look up this product online",
        "search for reviews of this movie", "find information on the web",
        "web search for", "internet search", "search the internet for",
        "look this up for me", "can you google this",
        # wikipedia
        "who is albert einstein", "what is quantum computing",
        "wikipedia machine learning", "tell me about black holes",
        "explain photosynthesis", "who invented the telephone",
        "what is the history of rome", "look up recursion definition",
        "who was gandhi", "what are neural networks",
        # news
        "latest tech news", "headlines today", "news about cricket",
        "top news in india", "current events", "show me todays news",
        "tech headlines", "sports news today", "business news",
        "breaking news", "what happened in the stock market",
        # web page reading
        "read this webpage", "fetch content from this URL",
        "get text from this website", "scrape this page",
    ],
    "weather": [
        "what is the weather in mumbai", "is it raining", "temperature today",
        "weather forecast", "how hot is it", "will it snow tomorrow",
        "humidity level", "weather report", "current weather",
        "check weather in delhi", "weather outside", "is it cloudy",
        "weather for the weekend", "UV index today",
        "do I need an umbrella today", "what is the temperature right now",
        "weather in new york", "forecast for this week",
    ],
    "calculation": [
        "calculate 15 percent of 5000", "what is 2 plus 2",
        "solve 500 divided by 4", "5 times 8", "square root of 144",
        "compute 100 minus 35", "what is 20% of 80",
        "multiply 6 by 7", "evaluate this math expression",
        "calculate tip 15%", "3 to the power 4",
        "math problem 12 times 12", "how much is 45 divided by 9",
        "convert 5 km to miles", "calculate area of circle with radius 5",
        "convert 100 celsius to fahrenheit", "how many inches in a foot",
        "convert meters to feet", "what is log of 100",
        "trigonometry sin 45", "cosine of 60 degrees",
    ],
    "datetime": [
        "what time is it", "current time", "what day is today",
        "todays date", "what is the date right now",
        "what month is it", "current year", "day of the week",
        "good morning", "what hour is it",
        "how many days left in the month", "is today a weekday",
        "hello", "hi there", "greet me", "good evening",
        "tell me a joke", "make me laugh", "something funny",
        "say something funny", "joke please",
    ],
    "task_manager": [
        # tasks
        "add task buy milk", "create a todo", "new task finish report",
        "list my tasks", "show pending tasks", "complete task 3",
        "mark done", "what are my todos", "show task list",
        "how many tasks do I have", "task summary",
        "add to my to do list", "finish this task",
        # notes
        "create a note", "take a note", "save this as a note",
        "show my notes", "list all notes", "read note meeting",
        "get note by id", "what notes do I have",
        # reminders
        "remind me at 5pm", "set a reminder for tomorrow",
        "list my reminders", "show upcoming reminders",
        "add reminder doctor appointment",
        # pomodoro
        "start pomodoro", "start focus session", "pomodoro timer",
        "stop pomodoro", "cancel focus timer", "pomodoro status",
        "how much time left in pomodoro",
        # timer
        "set timer for 5 minutes", "timer 30 seconds",
        "remind me in 1 hour", "countdown timer",
    ],
    "communication": [
        "send email to john", "check my inbox", "read unread emails",
        "how many emails do I have", "email summary",
        "send slack message", "slack to channel", "message team on slack",
        "notify team via slack", "post to slack general",
        "compose an email", "draft a reply", "email this person",
        "check my email", "any new messages",
        "send outlook email", "read outlook inbox",
    ],
    "productivity": [
        "create an excel spreadsheet", "make a word document",
        "generate a report in excel", "write a document",
        "create a new spreadsheet with data", "read this excel file",
        "open the spreadsheet", "make a presentation",
        "remember that my favorite color is blue",
        "always use dark mode", "forget that preference",
        "store this information for later", "memorize this fact",
        "my name is", "remember my city is mumbai",
        "schedule a task in 30 minutes", "run this in the background later",
    ],
}


# ---------------------------------------------------------------------------
# CategoryClassifier
# ---------------------------------------------------------------------------


class CategoryClassifier:
    """
    TF-IDF + LinearSVC classifier for coarse tool category prediction.

    Usage
    -----
    clf = CategoryClassifier(model_dir=Path("Model"))
    clf.train()
    category, confidence = clf.predict("set volume to 60")
    # -> ("os_control", 1.23)
    """

    CACHE_FILENAME = "category_classifier.joblib"

    def __init__(self, model_dir: Path | str = Path("Model")) -> None:
        self._model_dir = Path(model_dir)
        self._vectorizer: Any = None
        self._classifier: Any = None
        self._classes: list[str] = []
        self._ready = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self) -> None:
        """Fit TF-IDF + LinearSVC on TRAINING_DATA and persist to disk."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.svm import LinearSVC
        except ImportError:
            logger.error(
                "CategoryClassifier requires scikit-learn. "
                "Install with: pip install scikit-learn"
            )
            return

        # Flatten to parallel (text, label) lists
        texts: list[str] = []
        labels: list[str] = []
        for category, phrases in TRAINING_DATA.items():
            for phrase in phrases:
                texts.append(phrase)
                labels.append(category)

        logger.info(
            "CategoryClassifier: training on %d phrases across %d categories…",
            len(texts),
            len(TRAINING_DATA),
        )

        self._vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),   # unigrams + bigrams
            sublinear_tf=True,     # log-frequency scaling
            min_df=1,
        )
        X = self._vectorizer.fit_transform(texts)

        self._classifier = LinearSVC(
            C=1.0,
            max_iter=2000,
            class_weight="balanced",  # handles category size imbalance
        )
        self._classifier.fit(X, labels)
        self._classes = list(self._classifier.classes_)
        self._ready = True

        # Persist
        self._persist()
        logger.info("CategoryClassifier: trained and saved. Classes: %s", self._classes)

    def _persist(self) -> None:
        try:
            import joblib

            self._model_dir.mkdir(parents=True, exist_ok=True)
            cache_path = self._model_dir / self.CACHE_FILENAME
            joblib.dump(
                {
                    "vectorizer": self._vectorizer,
                    "classifier": self._classifier,
                    "classes": self._classes,
                },
                cache_path,
            )
        except Exception as exc:
            logger.warning("CategoryClassifier: could not persist model: %s", exc)

    def load(self) -> bool:
        """Load a previously persisted model. Returns True on success."""
        cache_path = self._model_dir / self.CACHE_FILENAME
        if not cache_path.exists():
            return False
        try:
            import joblib

            data = joblib.load(cache_path)
            self._vectorizer = data["vectorizer"]
            self._classifier = data["classifier"]
            self._classes = data["classes"]
            self._ready = True
            logger.info(
                "CategoryClassifier: loaded from cache. Classes: %s", self._classes
            )
            return True
        except Exception as exc:
            logger.warning("CategoryClassifier: cache load failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, query: str) -> tuple[str, float]:
        """
        Predict the most likely category for *query*.

        Returns
        -------
        (category_name, confidence_score)
            confidence_score is the raw SVM decision function value for
            the winning class — higher = more confident.
            Returns ("unknown", 0.0) if the classifier is not ready.
        """
        if not self._ready or self._vectorizer is None or self._classifier is None:
            return "unknown", 0.0

        try:
            import numpy as np

            x_vec = self._vectorizer.transform([query])
            scores = self._classifier.decision_function(x_vec)[0]

            if len(self._classes) == 1:
                return self._classes[0], float(scores)

            # Multi-class: decision_function returns shape (n_classes,)
            best_idx = int(np.argmax(scores))
            category = self._classes[best_idx]
            confidence = float(scores[best_idx])
            return category, confidence
        except Exception as exc:
            logger.error("CategoryClassifier: prediction error: %s", exc)
            return "unknown", 0.0

    def predict_top2(self, query: str) -> list[str]:
        """
        Return the top-2 most likely category names (for wider candidate pools).
        Returns empty list if not ready.
        """
        if not self._ready or self._vectorizer is None or self._classifier is None:
            return []

        try:
            import numpy as np

            x_vec = self._vectorizer.transform([query])
            scores = self._classifier.decision_function(x_vec)[0]

            if len(self._classes) <= 1:
                return list(self._classes)

            sorted_indices = np.argsort(scores)[::-1]
            top2_idx = sorted_indices[:2]
            return [self._classes[i] for i in top2_idx]
        except Exception as exc:
            logger.error("CategoryClassifier: top2 prediction error: %s", exc)
            return []

    @property
    def is_ready(self) -> bool:
        return self._ready
