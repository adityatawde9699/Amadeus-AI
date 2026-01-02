"""
Amadeus AI Visual Dashboard - JARVIS-style Futuristic Interface
A complete redesign with modern aesthetics, glassmorphism, and premium UX.

Features:
- Futuristic dark theme with neon accents
- Glassmorphism card design
- Animated elements and transitions
- Real-time system monitoring
- Voice input integration
- Responsive layout
"""

import streamlit as st
import time
import asyncio
import json
import requests
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from functools import lru_cache
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import Amadeus Backend
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from amadeus import Amadeus
from task_utils import list_tasks
from note_utils import list_notes
from reminder_utils import ReminderManager
from system_monitor import get_cpu_usage, get_memory_usage, get_battery_info, get_disk_usage
from general_utils import get_weather_async, get_datetime_info
from db import init_db_async

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="AMADEUS AI",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- JARVIS-INSPIRED CSS THEME ---
st.markdown("""
<style>
    /* === IMPORTS & VARIABLES === */
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;600;700;800;900&family=Rajdhani:wght@300;400;500;600;700&family=Share+Tech+Mono&display=swap');
    
    :root {
        --primary-cyan: #00d4ff;
        --primary-blue: #0066ff;
        --accent-purple: #7b2dff;
        --accent-pink: #ff2d95;
        --bg-deepest: #030508;
        --bg-deep: #0a0e17;
        --bg-medium: #111827;
        --bg-light: #1e293b;
        --glass-bg: rgba(15, 23, 42, 0.7);
        --glass-border: rgba(0, 212, 255, 0.2);
        --text-primary: #ffffff;
        --text-secondary: rgba(255, 255, 255, 0.7);
        --text-muted: rgba(255, 255, 255, 0.4);
        --glow-cyan: 0 0 20px rgba(0, 212, 255, 0.5);
        --glow-blue: 0 0 30px rgba(0, 102, 255, 0.3);
    }
    
    /* === MAIN BACKGROUND === */
    .stApp {
        background: 
            radial-gradient(ellipse at top left, rgba(0, 212, 255, 0.08) 0%, transparent 50%),
            radial-gradient(ellipse at bottom right, rgba(123, 45, 255, 0.08) 0%, transparent 50%),
            radial-gradient(ellipse at center, rgba(0, 102, 255, 0.05) 0%, transparent 70%),
            linear-gradient(180deg, var(--bg-deepest) 0%, var(--bg-deep) 50%, var(--bg-medium) 100%);
        background-attachment: fixed;
        min-height: 100vh;
    }
    
    /* Grid overlay effect */
    .stApp::before {
        content: "";
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-image: 
            linear-gradient(rgba(0, 212, 255, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0, 212, 255, 0.03) 1px, transparent 1px);
        background-size: 50px 50px;
        pointer-events: none;
        z-index: 0;
    }
    
    /* === HIDE STREAMLIT DEFAULTS === */
    #MainMenu, footer, header {visibility: hidden;}
    .stDeployButton {display: none;}
    
    /* === TYPOGRAPHY === */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Orbitron', sans-serif !important;
        color: var(--text-primary) !important;
        letter-spacing: 2px;
    }
    
    p, span, label, div {
        font-family: 'Rajdhani', sans-serif !important;
    }
    
    /* === ANIMATED MAIN TITLE === */
    .main-title {
        font-family: 'Orbitron', sans-serif !important;
        font-size: 4rem;
        font-weight: 900;
        text-align: center;
        background: linear-gradient(135deg, #00d4ff 0%, #0066ff 25%, #7b2dff 50%, #00d4ff 75%, #0066ff 100%);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: gradient-shift 8s ease infinite, title-glow 2s ease-in-out infinite alternate;
        margin: 0;
        padding: 1rem 0 0.5rem 0;
        text-shadow: var(--glow-cyan);
        letter-spacing: 12px;
    }
    
    @keyframes gradient-shift {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    
    @keyframes title-glow {
        from { filter: drop-shadow(0 0 20px rgba(0, 212, 255, 0.5)); }
        to { filter: drop-shadow(0 0 40px rgba(0, 212, 255, 0.8)); }
    }
    
    .subtitle {
        font-family: 'Share Tech Mono', monospace !important;
        text-align: center;
        color: var(--text-secondary);
        font-size: 1rem;
        letter-spacing: 4px;
        margin-bottom: 2rem;
        text-transform: uppercase;
    }
    
    /* === GLASSMORPHISM CARDS === */
    .glass-card {
        background: linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(30, 41, 59, 0.7) 100%);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid var(--glass-border);
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 
            0 8px 32px rgba(0, 0, 0, 0.4),
            inset 0 1px 0 rgba(255, 255, 255, 0.05),
            0 0 0 1px rgba(0, 212, 255, 0.1);
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }
    
    .glass-card::before {
        content: "";
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(0, 212, 255, 0.1), transparent);
        transition: left 0.5s;
    }
    
    .glass-card:hover::before {
        left: 100%;
    }
    
    .glass-card:hover {
        border-color: rgba(0, 212, 255, 0.5);
        transform: translateY(-4px);
        box-shadow: 
            0 16px 48px rgba(0, 0, 0, 0.5),
            0 0 30px rgba(0, 212, 255, 0.2);
    }
    
    /* === STAT CARDS === */
    .stat-card {
        background: linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.8));
        backdrop-filter: blur(15px);
        border: 1px solid rgba(0, 212, 255, 0.15);
        border-radius: 20px;
        padding: 1.25rem 1.5rem;
        text-align: center;
        transition: all 0.3s ease;
        position: relative;
    }
    
    .stat-card:hover {
        border-color: rgba(0, 212, 255, 0.4);
        box-shadow: 0 0 25px rgba(0, 212, 255, 0.15);
    }
    
    .stat-icon {
        font-size: 2.5rem;
        margin-bottom: 0.5rem;
        display: block;
    }
    
    .stat-label {
        font-family: 'Orbitron', sans-serif !important;
        color: var(--primary-cyan);
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 3px;
        margin-bottom: 0.5rem;
        font-weight: 600;
    }
    
    .stat-value {
        font-family: 'Rajdhani', sans-serif !important;
        color: var(--text-primary);
        font-size: 1.3rem;
        font-weight: 700;
        line-height: 1.3;
    }
    
    /* === STATUS INDICATORS === */
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.4rem 1rem;
        border-radius: 50px;
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.75rem;
        font-weight: 500;
        letter-spacing: 1px;
        text-transform: uppercase;
    }
    
    .status-online {
        background: rgba(0, 255, 136, 0.15);
        color: #00ff88;
        border: 1px solid rgba(0, 255, 136, 0.3);
        animation: pulse-green 2s infinite;
    }
    
    .status-processing {
        background: rgba(0, 212, 255, 0.15);
        color: var(--primary-cyan);
        border: 1px solid rgba(0, 212, 255, 0.3);
        animation: pulse-cyan 1s infinite;
    }
    
    .status-warning {
        background: rgba(255, 193, 7, 0.15);
        color: #ffc107;
        border: 1px solid rgba(255, 193, 7, 0.3);
    }
    
    .status-danger {
        background: rgba(255, 82, 82, 0.15);
        color: #ff5252;
        border: 1px solid rgba(255, 82, 82, 0.3);
    }
    
    @keyframes pulse-green {
        0%, 100% { box-shadow: 0 0 5px rgba(0, 255, 136, 0.3); }
        50% { box-shadow: 0 0 20px rgba(0, 255, 136, 0.6); }
    }
    
    @keyframes pulse-cyan {
        0%, 100% { box-shadow: 0 0 5px rgba(0, 212, 255, 0.3); }
        50% { box-shadow: 0 0 25px rgba(0, 212, 255, 0.8); }
    }
    
    /* === CIRCULAR PROGRESS === */
    .progress-ring {
        width: 80px;
        height: 80px;
        position: relative;
        margin: 0 auto 0.5rem auto;
    }
    
    .progress-ring svg {
        transform: rotate(-90deg);
    }
    
    .progress-ring-circle {
        fill: none;
        stroke: rgba(0, 212, 255, 0.2);
        stroke-width: 6;
    }
    
    .progress-ring-value {
        fill: none;
        stroke: var(--primary-cyan);
        stroke-width: 6;
        stroke-linecap: round;
        transition: stroke-dashoffset 0.5s ease;
        filter: drop-shadow(0 0 6px rgba(0, 212, 255, 0.8));
    }
    
    .progress-text {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        font-family: 'Orbitron', sans-serif !important;
        font-size: 1rem;
        font-weight: 700;
        color: var(--text-primary);
    }
    
    /* === SIDEBAR === */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(10, 14, 23, 0.98) 0%, rgba(17, 24, 39, 0.95) 100%);
        border-right: 1px solid rgba(0, 212, 255, 0.15);
        backdrop-filter: blur(20px);
    }
    
    [data-testid="stSidebar"] .stMarkdown {
        color: var(--text-secondary);
    }
    
    /* === CHAT INTERFACE === */
    .chat-container {
        background: linear-gradient(180deg, rgba(10, 14, 23, 0.6) 0%, rgba(17, 24, 39, 0.4) 100%);
        border: 1px solid rgba(0, 212, 255, 0.1);
        border-radius: 20px;
        padding: 1rem;
        min-height: 400px;
        max-height: 500px;
        overflow-y: auto;
    }
    
    .stChatMessage {
        background: rgba(15, 23, 42, 0.8) !important;
        border: 1px solid rgba(0, 212, 255, 0.15) !important;
        border-radius: 16px !important;
        backdrop-filter: blur(10px) !important;
        margin-bottom: 1rem !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3) !important;
    }
    
    .stChatMessage[data-testid="user-message"] {
        border-color: rgba(123, 45, 255, 0.3) !important;
        background: linear-gradient(135deg, rgba(123, 45, 255, 0.1), rgba(15, 23, 42, 0.8)) !important;
    }
    
    .stChatMessage[data-testid="assistant-message"] {
        border-color: rgba(0, 212, 255, 0.3) !important;
        background: linear-gradient(135deg, rgba(0, 212, 255, 0.1), rgba(15, 23, 42, 0.8)) !important;
    }
    
    /* === CHAT INPUT === */
    .stChatInput > div {
        background: rgba(15, 23, 42, 0.9) !important;
        border: 1px solid rgba(0, 212, 255, 0.3) !important;
        border-radius: 16px !important;
        backdrop-filter: blur(15px) !important;
    }
    
    .stChatInput input {
        background: transparent !important;
        color: var(--text-primary) !important;
        font-family: 'Rajdhani', sans-serif !important;
        font-size: 1rem !important;
    }
    
    .stChatInput input::placeholder {
        color: var(--text-muted) !important;
    }
    
    /* === BUTTONS === */
    .stButton > button {
        background: linear-gradient(135deg, rgba(0, 212, 255, 0.2), rgba(0, 102, 255, 0.2)) !important;
        border: 1px solid rgba(0, 212, 255, 0.4) !important;
        border-radius: 12px !important;
        color: var(--primary-cyan) !important;
        font-family: 'Orbitron', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 1px !important;
        padding: 0.5rem 1.5rem !important;
        transition: all 0.3s ease !important;
        text-transform: uppercase !important;
        font-size: 0.8rem !important;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, rgba(0, 212, 255, 0.4), rgba(0, 102, 255, 0.3)) !important;
        border-color: rgba(0, 212, 255, 0.8) !important;
        box-shadow: 0 0 25px rgba(0, 212, 255, 0.4) !important;
        transform: translateY(-2px) !important;
    }
    
    /* === EXPANDER === */
    .streamlit-expanderHeader {
        background: rgba(15, 23, 42, 0.6) !important;
        border: 1px solid rgba(0, 212, 255, 0.2) !important;
        border-radius: 12px !important;
        color: var(--text-primary) !important;
        font-family: 'Orbitron', sans-serif !important;
    }
    
    .streamlit-expanderContent {
        background: rgba(10, 14, 23, 0.8) !important;
        border: 1px solid rgba(0, 212, 255, 0.1) !important;
        border-top: none !important;
        border-radius: 0 0 12px 12px !important;
    }
    
    /* === DIVIDER === */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(0, 212, 255, 0.4), transparent);
        margin: 1.5rem 0;
    }
    
    /* === PROGRESS BAR === */
    .stProgress > div > div {
        background: linear-gradient(90deg, var(--primary-cyan), var(--primary-blue)) !important;
        border-radius: 10px !important;
    }
    
    /* === TOAST === */
    .stToast {
        background: rgba(15, 23, 42, 0.95) !important;
        border: 1px solid rgba(0, 212, 255, 0.3) !important;
        border-radius: 12px !important;
        backdrop-filter: blur(15px) !important;
    }
    
    /* === SPINNER === */
    .stSpinner > div {
        border-top-color: var(--primary-cyan) !important;
    }
    
    /* === SCROLLBAR === */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(10, 14, 23, 0.5);
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, var(--primary-cyan), var(--primary-blue));
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, #00e5ff, #0088ff);
    }
    
    /* === QUICK INFO BAR === */
    .info-bar {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 2rem;
        padding: 0.75rem 2rem;
        background: rgba(10, 14, 23, 0.8);
        border: 1px solid rgba(0, 212, 255, 0.15);
        border-radius: 50px;
        margin: 0 auto 2rem auto;
        width: fit-content;
    }
    
    .info-bar-item {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-family: 'Share Tech Mono', monospace !important;
        color: var(--text-secondary);
        font-size: 0.85rem;
    }
    
    .info-bar-icon {
        color: var(--primary-cyan);
        font-size: 1rem;
    }
    
    /* === TYPING INDICATOR === */
    .typing-indicator {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 1rem;
    }
    
    .typing-dot {
        width: 8px;
        height: 8px;
        background: var(--primary-cyan);
        border-radius: 50%;
        animation: typing-bounce 1.4s infinite ease-in-out both;
    }
    
    .typing-dot:nth-child(1) { animation-delay: -0.32s; }
    .typing-dot:nth-child(2) { animation-delay: -0.16s; }
    
    @keyframes typing-bounce {
        0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
        40% { transform: scale(1); opacity: 1; }
    }
    
    /* === FOOTER === */
    .footer {
        text-align: center;
        padding: 1rem;
        color: var(--text-muted);
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.75rem;
        letter-spacing: 2px;
        border-top: 1px solid rgba(0, 212, 255, 0.1);
        margin-top: 2rem;
    }
    
    .footer a {
        color: var(--primary-cyan);
        text-decoration: none;
    }
    
    /* === METRIC GAUGE === */
    .gauge-container {
        text-align: center;
        padding: 1rem;
    }
    
    .gauge-label {
        font-family: 'Orbitron', sans-serif !important;
        font-size: 0.7rem;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 0.5rem;
    }
    
    .gauge-value {
        font-family: 'Orbitron', sans-serif !important;
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--primary-cyan);
        text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
    }
    
    /* === WELCOME ANIMATION === */
    .welcome-text {
        text-align: center;
        padding: 3rem;
        color: var(--text-secondary);
    }
    
    .welcome-text h3 {
        font-family: 'Orbitron', sans-serif !important;
        color: var(--primary-cyan);
        margin-bottom: 1rem;
    }
    
    .welcome-icon {
        font-size: 4rem;
        margin-bottom: 1rem;
        animation: float 3s ease-in-out infinite;
    }
    
    @keyframes float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-10px); }
    }
    
    /* === VOICE BUTTON === */
    .voice-btn {
        background: linear-gradient(135deg, rgba(255, 45, 149, 0.2), rgba(123, 45, 255, 0.2)) !important;
        border: 1px solid rgba(255, 45, 149, 0.4) !important;
        animation: voice-pulse 2s infinite;
    }
    
    @keyframes voice-pulse {
        0%, 100% { box-shadow: 0 0 5px rgba(255, 45, 149, 0.3); }
        50% { box-shadow: 0 0 20px rgba(255, 45, 149, 0.6); }
    }
    
    /* === HEX BACKGROUND PATTERN === */
    .hex-bg {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        opacity: 0.03;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='49' viewBox='0 0 28 49'%3E%3Cg fill-rule='evenodd'%3E%3Cg id='hexagons' fill='%2300d4ff' fill-opacity='1' fill-rule='nonzero'%3E%3Cpath d='M13.99 9.25l13 7.5v15l-13 7.5L1 31.75v-15l12.99-7.5zM3 17.9v12.7l10.99 6.34 11-6.35V17.9l-11-6.34L3 17.9zM0 15l12.98-7.5V0h-2v6.35L0 12.69v2.3zm0 18.5L12.98 41v8h-2v-6.85L0 35.81v-2.3zM15 0v7.5L27.99 15H28v-2.31h-.01L17 6.35V0h-2zm0 49v-8l12.99-7.5H28v2.31h-.01L17 42.15V49h-2z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
    }
</style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---

_loop_lock = threading.Lock()
_shared_loop: Optional[asyncio.AbstractEventLoop] = None

def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get or create a shared event loop thread-safely."""
    global _shared_loop
    with _loop_lock:
        if _shared_loop is None or _shared_loop.is_closed():
            try:
                _shared_loop = asyncio.get_event_loop()
            except RuntimeError:
                _shared_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_shared_loop)
        return _shared_loop

def run_async(coro):
    """Run async coroutine safely in Streamlit context."""
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        try:
            return asyncio.run(coro)
        except Exception as e:
            logger.error(f"Error running async function: {e}")
            raise

@lru_cache(maxsize=1)
def load_lottie_url(url: str) -> Optional[Dict]:
    """Load Lottie animation with caching."""
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning(f"Failed to load Lottie animation: {e}")
    return None

def get_status_class(value: float, warning: float = 70, danger: float = 85) -> str:
    """Determine status badge class based on value."""
    if value >= danger:
        return "status-danger"
    elif value >= warning:
        return "status-warning"
    return "status-online"

def create_circular_progress(percent: float, label: str, color: str = "#00d4ff") -> str:
    """Create an SVG circular progress indicator."""
    circumference = 2 * 3.14159 * 36
    offset = circumference - (percent / 100) * circumference
    return f"""
    <div class="progress-ring">
        <svg width="80" height="80">
            <circle class="progress-ring-circle" cx="40" cy="40" r="36"/>
            <circle class="progress-ring-value" cx="40" cy="40" r="36"
                stroke="{color}"
                stroke-dasharray="{circumference}"
                stroke-dashoffset="{offset}"/>
        </svg>
        <div class="progress-text">{percent:.0f}%</div>
    </div>
    <div class="gauge-label">{label}</div>
    """

# --- GLOBAL RESOURCES ---

@st.cache_resource
def initialize_database():
    """Initialize database once globally."""
    try:
        run_async(init_db_async())
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False

@st.cache_resource
def get_amadeus_instance():
    """Get singleton Amadeus instance."""
    try:
        amadeus = Amadeus(debug_mode=True, voice_enabled=False)
        logger.info("Amadeus instance created")
        return amadeus
    except Exception as e:
        logger.error(f"Failed to create Amadeus instance: {e}")
        return None

@st.cache_resource
def get_reminder_manager():
    """Get singleton reminder manager."""
    try:
        manager = ReminderManager()
        return manager
    except Exception as e:
        logger.error(f"Failed to create reminder manager: {e}")
        return None

# --- DATA FETCHING ---

async def fetch_dashboard_data() -> Dict[str, Any]:
    """Fetch all dashboard data concurrently."""
    async def safe_fetch(coro, default):
        try:
            return await coro
        except Exception as e:
            logger.warning(f"Data fetch error: {e}")
            return default
    
    tasks_data, notes_data, reminders_data, weather_data = await asyncio.gather(
        safe_fetch(list_tasks("pending"), []),
        safe_fetch(list_notes(), []),
        safe_fetch(asyncio.to_thread(lambda: get_reminder_manager().list_reminders() if get_reminder_manager() else []), []),
        safe_fetch(get_weather_async("India"), "Weather unavailable"),
        return_exceptions=False
    )
    
    return {
        "tasks": tasks_data[:5] if tasks_data else [],
        "task_count": len(tasks_data) if tasks_data else 0,
        "notes": notes_data[:3] if notes_data else [],
        "note_count": len(notes_data) if notes_data else 0,
        "reminders": reminders_data[:3] if reminders_data else [],
        "reminder_count": len(reminders_data) if reminders_data else 0,
        "weather": weather_data,
        "timestamp": datetime.now()
    }

def get_dashboard_data(force_refresh: bool = False) -> Dict[str, Any]:
    """Get dashboard data with smart caching."""
    current_time = time.time()
    cache_ttl = 30
    
    needs_refresh = (
        force_refresh or
        "dashboard_data" not in st.session_state or
        "dashboard_data_timestamp" not in st.session_state or
        (current_time - st.session_state.dashboard_data_timestamp) > cache_ttl
    )
    
    if needs_refresh:
        try:
            data = run_async(fetch_dashboard_data())
            st.session_state.dashboard_data = data
            st.session_state.dashboard_data_timestamp = current_time
            return data
        except Exception as e:
            logger.error(f"Failed to refresh dashboard data: {e}")
            if "dashboard_data" in st.session_state:
                return st.session_state.dashboard_data
            return {
                "tasks": [], "task_count": 0,
                "notes": [], "note_count": 0,
                "reminders": [], "reminder_count": 0,
                "weather": "Weather unavailable",
                "timestamp": datetime.now()
            }
    
    return st.session_state.dashboard_data

# --- INITIALIZE SESSION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "state" not in st.session_state:
    st.session_state.state = "IDLE"

if "processing_start" not in st.session_state:
    st.session_state.processing_start = None

if "initialized" not in st.session_state:
    with st.spinner("🔮 Initializing AMADEUS..."):
        db_ok = initialize_database()
        amadeus = get_amadeus_instance()
        
        if not db_ok or not amadeus:
            st.error("❌ Failed to initialize Amadeus. Please refresh the page.")
            st.stop()
        
        st.session_state.initialized = True
        st.session_state.amadeus = amadeus

# --- SIDEBAR ---
with st.sidebar:
    # Logo/Brand
    st.markdown("""
    <div style="text-align: center; padding: 1rem 0;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🔮</div>
        <div style="font-family: 'Orbitron', sans-serif; font-size: 1.2rem; color: #00d4ff; letter-spacing: 4px;">AMADEUS</div>
        <div style="font-size: 0.7rem; color: rgba(255,255,255,0.4); letter-spacing: 2px; margin-top: 0.25rem;">AI ASSISTANT</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # System Status Header
    st.markdown("""
    <div style="font-family: 'Orbitron', sans-serif; font-size: 0.8rem; color: #00d4ff; letter-spacing: 2px; margin-bottom: 1rem;">
        ◈ SYSTEM STATUS
    </div>
    """, unsafe_allow_html=True)
    
    # System Metrics
    try:
        cpu = get_cpu_usage() or 0
        mem_data = get_memory_usage() or {"percent": 0}
        mem = mem_data.get("percent", 0) if isinstance(mem_data, dict) else 0
        
        col1, col2 = st.columns(2)
        
        with col1:
            cpu_color = "#00ff88" if cpu < 70 else ("#ffc107" if cpu < 85 else "#ff5252")
            st.markdown(create_circular_progress(cpu, "CPU", cpu_color), unsafe_allow_html=True)
        
        with col2:
            mem_color = "#00ff88" if mem < 70 else ("#ffc107" if mem < 85 else "#ff5252")
            st.markdown(create_circular_progress(mem, "MEMORY", mem_color), unsafe_allow_html=True)
        
        # Battery
        battery = get_battery_info()
        if isinstance(battery, dict) and "percent" in battery:
            battery_pct = battery["percent"]
            battery_status = battery.get("status", "Unknown")
            charging_icon = "⚡" if "charging" in battery_status.lower() else "🔋"
            st.progress(battery_pct / 100)
            st.markdown(f"""
            <div style="text-align: center; font-size: 0.8rem; color: rgba(255,255,255,0.6);">
                {charging_icon} {battery_pct}% • {battery_status}
            </div>
            """, unsafe_allow_html=True)
        
        # Disk Usage
        disk = get_disk_usage()
        if isinstance(disk, dict) and "percent" in disk:
            disk_pct = disk.get("percent", 0)
            st.markdown(f"""
            <div style="margin-top: 1rem;">
                <div style="font-size: 0.7rem; color: rgba(255,255,255,0.5); margin-bottom: 0.3rem;">💾 DISK USAGE</div>
            </div>
            """, unsafe_allow_html=True)
            st.progress(disk_pct / 100)
            st.caption(f"{disk_pct}% used")
    
    except Exception as e:
        st.error(f"⚠️ Monitoring error")
        logger.error(f"System monitoring error: {e}")
    
    st.markdown("---")
    
    # Quick Controls
    st.markdown("""
    <div style="font-family: 'Orbitron', sans-serif; font-size: 0.8rem; color: #00d4ff; letter-spacing: 2px; margin-bottom: 1rem;">
        ◈ CONTROLS
    </div>
    """, unsafe_allow_html=True)
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("🧹 CLEAR", use_container_width=True, help="Clear chat history"):
            st.session_state.messages = []
            if hasattr(st.session_state.amadeus, 'conversation'):
                st.session_state.amadeus.conversation.clear()
            st.toast("✅ Chat cleared!", icon="🧹")
            time.sleep(0.3)
            st.rerun()
    
    with col_b:
        if st.button("🔄 SYNC", use_container_width=True, help="Refresh data"):
            get_dashboard_data(force_refresh=True)
            st.toast("✅ Data refreshed!", icon="🔄")
            time.sleep(0.3)
            st.rerun()
    
    st.markdown("---")
    
    # Connection Status
    status_class = "status-online" if st.session_state.get('initialized', False) else "status-danger"
    status_text = "ONLINE" if st.session_state.get('initialized', False) else "OFFLINE"
    st.markdown(f"""
    <div style="text-align: center; padding: 0.5rem;">
        <span class="status-badge {status_class}">
            <span style="width: 8px; height: 8px; background: currentColor; border-radius: 50%; animation: pulse-green 2s infinite;"></span>
            {status_text}
        </span>
    </div>
    """, unsafe_allow_html=True)
    
    # Version Info
    st.markdown("""
    <div style="text-align: center; margin-top: 2rem; padding: 1rem; border-top: 1px solid rgba(0, 212, 255, 0.1);">
        <div style="font-family: 'Share Tech Mono', monospace; font-size: 0.7rem; color: rgba(255,255,255,0.3);">
            v2.0.0 • JARVIS EDITION
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- MAIN CONTENT ---

# Animated Header
st.markdown('<h1 class="main-title">AMADEUS</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Your Intelligent Digital Companion</p>', unsafe_allow_html=True)

# Quick Info Bar
current_time = datetime.now()
time_str = current_time.strftime("%H:%M")
date_str = current_time.strftime("%B %d, %Y")
day_str = current_time.strftime("%A")

st.markdown(f"""
<div class="info-bar">
    <div class="info-bar-item">
        <span class="info-bar-icon">🕐</span>
        <span>{time_str}</span>
    </div>
    <div class="info-bar-item">
        <span class="info-bar-icon">📅</span>
        <span>{day_str}, {date_str}</span>
    </div>
    <div class="info-bar-item">
        <span class="info-bar-icon">⚡</span>
        <span>{'Processing' if st.session_state.state == 'PROCESSING' else 'Ready'}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# --- DASHBOARD CARDS ---
try:
    dashboard_data = get_dashboard_data()
    
    card_cols = st.columns(4)
    
    # Tasks Card
    with card_cols[0]:
        st.markdown(f"""
        <div class="stat-card">
            <span class="stat-icon">📋</span>
            <div class="stat-label">Tasks</div>
            <div class="stat-value">{dashboard_data['task_count']} pending</div>
        </div>
        """, unsafe_allow_html=True)
        
        if dashboard_data["tasks"]:
            with st.expander("View Tasks", expanded=False):
                for i, task in enumerate(dashboard_data["tasks"][:3], 1):
                    content = task.get('content', 'No content')[:40]
                    st.markdown(f"**{i}.** {content}...")
    
    # Notes Card
    with card_cols[1]:
        st.markdown(f"""
        <div class="stat-card">
            <span class="stat-icon">📝</span>
            <div class="stat-label">Notes</div>
            <div class="stat-value">{dashboard_data['note_count']} saved</div>
        </div>
        """, unsafe_allow_html=True)
        
        if dashboard_data["notes"]:
            with st.expander("View Notes", expanded=False):
                for i, note in enumerate(dashboard_data["notes"][:3], 1):
                    title = note.get('title', 'Untitled')[:40]
                    st.markdown(f"**{i}.** {title}")
    
    # Reminders Card
    with card_cols[2]:
        st.markdown(f"""
        <div class="stat-card">
            <span class="stat-icon">⏰</span>
            <div class="stat-label">Reminders</div>
            <div class="stat-value">{dashboard_data['reminder_count']} active</div>
        </div>
        """, unsafe_allow_html=True)
        
        if dashboard_data["reminders"]:
            with st.expander("View Reminders", expanded=False):
                for i, rem in enumerate(dashboard_data["reminders"][:3], 1):
                    title = rem.get('title', 'No title')[:40]
                    st.markdown(f"**{i}.** {title}")
    
    # Weather Card
    with card_cols[3]:
        weather_text = dashboard_data["weather"]
        if isinstance(weather_text, str) and len(weather_text) > 30:
            weather_short = weather_text[:30] + "..."
        else:
            weather_short = weather_text if isinstance(weather_text, str) else "Loading..."
        
        st.markdown(f"""
        <div class="stat-card">
            <span class="stat-icon">🌤️</span>
            <div class="stat-label">Weather</div>
            <div class="stat-value" style="font-size: 1rem;">{weather_short}</div>
        </div>
        """, unsafe_allow_html=True)
        
        if isinstance(weather_text, str) and len(weather_text) > 30:
            with st.expander("Full Weather", expanded=False):
                st.info(weather_text)

except Exception as e:
    st.error(f"⚠️ Dashboard data error: {str(e)[:100]}")
    logger.error(f"Dashboard rendering error: {e}")

st.markdown("<br>", unsafe_allow_html=True)

# --- CHAT INTERFACE ---
st.markdown("""
<div style="font-family: 'Orbitron', sans-serif; font-size: 1rem; color: #00d4ff; letter-spacing: 3px; margin-bottom: 1rem;">
    ◈ COMMUNICATION INTERFACE
</div>
""", unsafe_allow_html=True)

# Chat container
chat_container = st.container(height=420)

with chat_container:
    if not st.session_state.messages:
        st.markdown("""
        <div class="welcome-text">
            <div class="welcome-icon">🔮</div>
            <h3>Welcome to AMADEUS</h3>
            <p style="color: rgba(255,255,255,0.5);">
                Your intelligent AI assistant is ready.<br>
                Type a command or ask a question to begin.
            </p>
            <div style="margin-top: 1.5rem; display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap;">
                <span style="background: rgba(0, 212, 255, 0.1); padding: 0.5rem 1rem; border-radius: 20px; font-size: 0.8rem; border: 1px solid rgba(0, 212, 255, 0.2);">💡 "What's the weather?"</span>
                <span style="background: rgba(0, 212, 255, 0.1); padding: 0.5rem 1rem; border-radius: 20px; font-size: 0.8rem; border: 1px solid rgba(0, 212, 255, 0.2);">📋 "Add a task"</span>
                <span style="background: rgba(0, 212, 255, 0.1); padding: 0.5rem 1rem; border-radius: 20px; font-size: 0.8rem; border: 1px solid rgba(0, 212, 255, 0.2);">⏰ "Set a reminder"</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for message in st.session_state.messages:
            avatar = "🧑‍💻" if message["role"] == "user" else "🔮"
            with st.chat_message(message["role"], avatar=avatar):
                st.markdown(message["content"])

# Processing indicator
if st.session_state.state == "PROCESSING":
    st.markdown("""
    <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <span style="margin-left: 0.5rem; color: rgba(255,255,255,0.6);">AMADEUS is thinking...</span>
    </div>
    """, unsafe_allow_html=True)

# Chat Input
prompt = st.chat_input("Enter command or ask a question...", key="chat_input")

# Voice input section (optional - try to import)
try:
    from streamlit_mic_recorder import speech_to_text
    
    with st.expander("🎙️ Voice Input", expanded=False):
        voice_text = speech_to_text(
            language='en',
            start_prompt="🎤 Start Recording",
            stop_prompt="⏹️ Stop Recording",
            just_once=True,
            key='STT'
        )
        if voice_text:
            st.success(f"**Heard:** {voice_text}")
            prompt = voice_text
except ImportError:
    voice_text = None
    logger.info("Voice input not available - streamlit_mic_recorder not installed")

# Process input
if prompt:
    if len(prompt.strip()) == 0:
        st.warning("⚠️ Please enter a valid command")
    elif len(prompt) > 500:
        st.error("❌ Command too long (max 500 characters)")
    else:
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now()
        })
        
        # Set processing state
        st.session_state.state = "PROCESSING"
        st.session_state.processing_start = time.time()
        
        # Process with Amadeus
        try:
            amadeus = st.session_state.amadeus
            
            async def process_with_timeout():
                try:
                    return await asyncio.wait_for(
                        amadeus.process_command(prompt),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    return "⏱️ Request timeout. Please try again with a simpler command."
            
            with st.spinner(""):
                response = run_async(process_with_timeout())
            
            # Add response
            st.session_state.messages.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now()
            })
            
            # Show success
            processing_time = time.time() - st.session_state.processing_start
            st.toast(f"✅ Completed in {processing_time:.1f}s", icon="✨")
            
        except Exception as e:
            error_msg = f"❌ Error: {str(e)[:100]}"
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg,
                "timestamp": datetime.now()
            })
            st.error(error_msg)
            logger.error(f"Command processing error: {e}")
        
        finally:
            st.session_state.state = "IDLE"
            st.session_state.processing_start = None
            get_dashboard_data(force_refresh=True)
            st.rerun()

# --- FOOTER ---
st.markdown("""
<div class="footer">
    <div style="margin-bottom: 0.5rem;">
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    </div>
    <div>
        ◈ AMADEUS AI v2.0 • JARVIS EDITION ◈
    </div>
    <div style="margin-top: 0.25rem; font-size: 0.65rem;">
        Powered by Gemini AI • Built with Streamlit
    </div>
</div>
""", unsafe_allow_html=True)