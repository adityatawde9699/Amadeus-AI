import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env at import time so other modules can rely on environment vars
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# SQLite file path
DB_FILE = os.getenv('AMADEUS_DB_FILE', str(BASE_DIR / 'amadeus.db'))
DB_URL = f"sqlite:///{DB_FILE}"

# Application settings
VOICE_ENABLED = os.getenv('VOICE_ENABLED', 'true').lower() in ('1', 'true', 'yes')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
