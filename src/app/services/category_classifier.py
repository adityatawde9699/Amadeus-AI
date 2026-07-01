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

import itertools
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
        "which applications are active",
    ],
    "monitoring": [
        # cpu / memory
        "cpu usage", "how much cpu is being used", "check cpu load",
        "memory usage", "ram usage", "how much memory is free",
        "is my ram full", "running processes", "top processes by memory",
        # disk
        "disk space", "how much disk space is left", "is my disk full",
        "storage usage",
        # battery / power
        "battery level", "battery status", "how much battery is left",
        "is the laptop charging",
        # network health
        "is my internet working", "network info", "check my connection",
        "am i online", "what is my local ip",
        # temps / uptime / overall
        "system temperature", "is the cpu overheating",
        "how long has the pc been on", "system uptime",
        "system status", "system health report", "full system report",
        "any system alerts", "is the system healthy",
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
        # web page reading
        "read this webpage", "fetch content from this URL",
        "get text from this website", "scrape this page",
    ],
    "news": [
        "latest tech news", "headlines today", "news about cricket",
        "top news in india", "current events", "show me todays news",
        "tech headlines", "sports news today", "business news",
        "breaking news", "world news", "news update",
        "what's happening in the world", "today's top stories",
        "entertainment news", "science news", "health news",
        "political news today", "any news about the election",
        "show me the latest headlines",
    ],
    "finance": [
        "stock price of apple", "how is tesla stock doing",
        "share price of reliance", "what is the nifty at",
        "check microsoft stock", "price of google shares",
        "stock market today", "is the market up or down",
        "bitcoin price", "how much is ethereum",
        "btc to usd", "crypto prices", "what is dogecoin worth",
        "solana price today", "check crypto market",
        "ethereum in inr", "current value of bitcoin",
        "how are my stocks doing", "tsla quote", "aapl stock",
    ],
    "developer": [
        "write and run a python script", "execute this code",
        "run python code", "execute a script", "run this program",
        "write code to compute fibonacci", "code this up and run it",
        "calculate using code", "run a python script for primes",
        "execute python", "test this code snippet",
        "run command ping google.com", "run a terminal command",
        "what is my ip address", "run ifconfig", "nslookup this domain",
        "show network info via command", "run hostname command",
        "search my codebase for the router", "where is this function defined",
        "find the class that handles auth", "search the workspace for config",
        "look in my projects for the docker port", "grep my code for TODO",
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
    "content_generation": [
        "write an essay about computers", "compose an article on AI",
        "draft a letter to my boss", "create a story for kids",
        "write a poem about nature", "generate a report summary",
        "compose a blog post", "write a professional email",
        "draft a proposal", "create a detailed explanation",
        "write a script for a video", "compose a formal invitation",
    ],
}


# ---------------------------------------------------------------------------
# CategoryClassifier
# ---------------------------------------------------------------------------


class CategoryClassifier:
    """
    TF-IDF + linear-SVM classifier for coarse tool category prediction.

    Training uses scikit-learn ONCE (first run), then the fitted model is
    persisted as plain numpy arrays. Inference re-implements the TF-IDF
    transform and the SVM decision function in numpy, so the runtime daemon
    never imports sklearn/scipy (~70MB RSS saved — CLAUDE.md §6).

    Usage
    -----
    clf = CategoryClassifier(model_dir=Path("Model"))
    clf.train()
    category, confidence = clf.predict("take a screenshot")
    # -> ("os_control", 1.23)
    """

    CACHE_FILENAME = "category_classifier.npz"
    # Must mirror TfidfVectorizer defaults used in train()
    _TOKEN_PATTERN = r"(?u)\b\w\w+\b"

    def __init__(self, model_dir: Path | str = Path("Model")) -> None:
        self._model_dir = Path(model_dir)
        self._vocab: dict[str, int] = {}
        self._idf: Any = None        # np.ndarray (n_features,)
        self._coef: Any = None       # np.ndarray (n_classes, n_features)
        self._intercept: Any = None  # np.ndarray (n_classes,)
        self._classes: list[str] = []
        self._token_re: Any = None
        self._ready = False

    # ------------------------------------------------------------------
    # Training (build-time only — the single place sklearn is imported)
    # ------------------------------------------------------------------

    def train(self) -> None:
        """Fit TF-IDF + LinearSVC on TRAINING_DATA and persist numpy arrays."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.svm import LinearSVC
        except ImportError:
            logger.exception(
                "CategoryClassifier requires scikit-learn for training. "
                "Install with: pip install scikit-learn"
            )
            return

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

        vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),   # unigrams + bigrams
            sublinear_tf=True,     # log-frequency scaling
            min_df=1,
        )
        X = vectorizer.fit_transform(texts)

        classifier = LinearSVC(
            C=1.0,
            max_iter=2000,
            class_weight="balanced",  # handles category size imbalance
        )
        classifier.fit(X, labels)

        import numpy as np

        self._vocab = {t: int(i) for t, i in vectorizer.vocabulary_.items()}
        self._idf = np.asarray(vectorizer.idf_, dtype=np.float32)
        self._coef = np.asarray(classifier.coef_, dtype=np.float32)
        self._intercept = np.asarray(classifier.intercept_, dtype=np.float32)
        self._classes = [str(c) for c in classifier.classes_]
        self._compile_tokenizer()
        self._ready = True

        self._persist()
        logger.info("CategoryClassifier: trained and saved. Classes: %s", self._classes)

    def _persist(self) -> None:
        try:
            import numpy as np

            self._model_dir.mkdir(parents=True, exist_ok=True)
            cache_path = self._model_dir / self.CACHE_FILENAME
            tokens = np.array(list(self._vocab.keys()))
            indices = np.array(list(self._vocab.values()), dtype=np.int64)
            np.savez(
                cache_path,
                tokens=tokens,
                indices=indices,
                idf=self._idf,
                coef=self._coef,
                intercept=self._intercept,
                classes=np.array(self._classes),
            )
        except Exception as exc:
            logger.warning("CategoryClassifier: could not persist model: %s", exc)

    def load(self) -> bool:
        """Load persisted numpy arrays. Returns True on success."""
        cache_path = self._model_dir / self.CACHE_FILENAME
        if not cache_path.exists():
            return False
        try:
            import numpy as np

            data = np.load(cache_path, allow_pickle=False)
            classes = [str(c) for c in data["classes"]]

            # Invalidate stale caches: if the trained classes no longer match
            # TRAINING_DATA (categories added/removed), force a retrain.
            if set(classes) != set(TRAINING_DATA.keys()):
                logger.info(
                    "CategoryClassifier: cached classes differ from TRAINING_DATA — retraining."
                )
                return False

            self._vocab = {
                str(t): int(i) for t, i in zip(data["tokens"], data["indices"], strict=True)
            }
            self._idf = data["idf"]
            self._coef = data["coef"]
            self._intercept = data["intercept"]
            self._classes = classes
            self._compile_tokenizer()
            self._ready = True
            logger.info(
                "CategoryClassifier: loaded from cache. Classes: %s", self._classes
            )
            return True
        except Exception as exc:
            logger.warning("CategoryClassifier: cache load failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Inference (numpy only)
    # ------------------------------------------------------------------

    def _compile_tokenizer(self) -> None:
        import re

        self._token_re = re.compile(self._TOKEN_PATTERN)

    def _transform(self, query: str) -> Any:
        """Numpy re-implementation of the fitted TfidfVectorizer transform."""
        import numpy as np

        tokens = self._token_re.findall(query.lower())
        # unigrams + bigrams, mirroring ngram_range=(1, 2)
        grams = tokens + [" ".join(pair) for pair in itertools.pairwise(tokens)]

        counts: dict[int, int] = {}
        for gram in grams:
            idx = self._vocab.get(gram)
            if idx is not None:
                counts[idx] = counts.get(idx, 0) + 1

        x = np.zeros(self._idf.shape[0], dtype=np.float32)
        for idx, count in counts.items():
            # sublinear_tf: 1 + ln(tf), then multiply idf
            x[idx] = (1.0 + np.log(count)) * self._idf[idx]

        norm = np.linalg.norm(x)
        if norm > 0:
            x /= norm
        return x

    def _decision_scores(self, query: str) -> Any:
        """SVM decision function: X @ coef.T + intercept."""
        x = self._transform(query)
        return self._coef @ x + self._intercept

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
        if not self._ready or self._coef is None:
            return "unknown", 0.0

        try:
            import numpy as np

            scores = self._decision_scores(query)
            best_idx = int(np.argmax(scores))
            return self._classes[best_idx], float(scores[best_idx])
        except Exception as exc:
            logger.exception("CategoryClassifier: prediction error: %s", exc)
            return "unknown", 0.0

    def predict_top2(self, query: str) -> list[str]:
        """
        Return the top-2 most likely category names (for wider candidate pools).
        Returns empty list if not ready.
        """
        if not self._ready or self._coef is None:
            return []

        try:
            import numpy as np

            scores = self._decision_scores(query)
            if len(self._classes) <= 1:
                return list(self._classes)
            top2_idx = np.argsort(scores)[::-1][:2]
            return [self._classes[i] for i in top2_idx]
        except Exception as exc:
            logger.exception("CategoryClassifier: top2 prediction error: %s", exc)
            return []

    @property
    def is_ready(self) -> bool:
        return self._ready
