"""
Amadeus AI Visual Dashboard - JARVIS-style Interactive Interface
Streamlit-based frontend for the Amadeus AI Assistant.

Improvements:
- Fixed async/event loop handling
- Better state management with singletons
- Improved error handling and graceful degradation
- Real-time updates with WebSocket-like behavior
- Performance optimizations
"""

import streamlit as st
import time
import asyncio
import json
import requests
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from streamlit_lottie import st_lottie
from streamlit_mic_recorder import speech_to_text
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
from system_monitor import get_cpu_usage, get_memory_usage, get_battery_info
from general_utils import get_weather_async
from db import init_db_async

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Amadeus AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM DARK THEME CSS ---
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #16213e 100%);
    }
    
    .header-cards {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    
    .info-card {
        background: linear-gradient(145deg, rgba(26, 26, 46, 0.9), rgba(22, 33, 62, 0.8));
        border: 1px solid rgba(79, 172, 254, 0.3);
        border-radius: 12px;
        padding: 1rem 1.25rem;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3), 
                    inset 0 1px 0 rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
    }
    
    .info-card:hover {
        border-color: rgba(79, 172, 254, 0.6);
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(79, 172, 254, 0.2);
    }
    
    .card-title {
        color: #4facfe;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-bottom: 0.5rem;
        font-weight: 600;
    }
    
    .card-value {
        color: #ffffff;
        font-size: 1.1rem;
        font-weight: 500;
        line-height: 1.4;
    }
    
    .card-icon {
        font-size: 1.5rem;
        margin-bottom: 0.5rem;
    }
    
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 500;
    }
    
    .status-good {
        background: rgba(0, 255, 136, 0.2);
        color: #00ff88;
        border: 1px solid rgba(0, 255, 136, 0.3);
    }
    
    .status-warning {
        background: rgba(255, 193, 7, 0.2);
        color: #ffc107;
        border: 1px solid rgba(255, 193, 7, 0.3);
    }
    
    .status-danger {
        background: rgba(255, 82, 82, 0.2);
        color: #ff5252;
        border: 1px solid rgba(255, 82, 82, 0.3);
    }
    
    .main-title {
        background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 2.5rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 0.5rem;
        text-shadow: 0 0 30px rgba(79, 172, 254, 0.5);
    }
    
    .subtitle {
        color: rgba(255, 255, 255, 0.6);
        text-align: center;
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a0a0f 0%, #1a1a2e 100%);
        border-right: 1px solid rgba(79, 172, 254, 0.2);
    }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    .stChatMessage {
        background: rgba(26, 26, 46, 0.6) !important;
        border: 1px solid rgba(79, 172, 254, 0.2) !important;
        border-radius: 12px !important;
    }
    
    /* Loading animation */
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    
    .loading {
        animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }
</style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---

# Thread-safe event loop management
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
    """
    Run async coroutine safely in Streamlit context.
    
    This handles the complexities of mixing Streamlit's execution model
    with asyncio properly.
    """
    try:
        # Check if we're already in an event loop
        loop = asyncio.get_running_loop()
        # We're in an async context - need to use thread executor
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        # No running loop - we can safely use asyncio.run()
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
    return "status-good"

# --- GLOBAL RESOURCES (SINGLETONS) ---

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
    """
    Fetch all dashboard data concurrently.
    
    Uses asyncio.gather for parallel execution with error isolation.
    """
    async def safe_fetch(coro, default):
        """Wrapper to catch errors and return defaults."""
        try:
            return await coro
        except Exception as e:
            logger.warning(f"Data fetch error: {e}")
            return default
    
    # Fetch all data concurrently
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
    """
    Get dashboard data with smart caching.
    
    Caches data in session state with 30-second TTL.
    """
    current_time = time.time()
    cache_ttl = 30  # seconds
    
    # Check if we need to refresh
    needs_refresh = (
        force_refresh or
        "dashboard_data" not in st.session_state or
        "dashboard_data_timestamp" not in st.session_state or
        (current_time - st.session_state.dashboard_data_timestamp) > cache_ttl
    )
    
    if needs_refresh:
        try:
            with st.spinner("🔄 Refreshing data..."):
                data = run_async(fetch_dashboard_data())
                st.session_state.dashboard_data = data
                st.session_state.dashboard_data_timestamp = current_time
                return data
        except Exception as e:
            logger.error(f"Failed to refresh dashboard data: {e}")
            # Return stale data if available
            if "dashboard_data" in st.session_state:
                st.warning("Using cached data (refresh failed)")
                return st.session_state.dashboard_data
            # Return empty defaults
            return {
                "tasks": [], "task_count": 0,
                "notes": [], "note_count": 0,
                "reminders": [], "reminder_count": 0,
                "weather": "Weather unavailable",
                "timestamp": datetime.now()
            }
    
    return st.session_state.dashboard_data

# --- LOTTIE ANIMATIONS ---
LOTTIE_IDLE_URL = "https://lottie.host/6c3c5886-0692-41a4-8451-d9a6c721c565/s8y951hJqj.json"
LOTTIE_ACTIVE_URL = "https://assets10.lottiefiles.com/packages/lf20_4kji20Y9.json"

# --- INITIALIZE SESSION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "state" not in st.session_state:
    st.session_state.state = "IDLE"

if "processing_start" not in st.session_state:
    st.session_state.processing_start = None

if "lottie_idle" not in st.session_state:
    st.session_state.lottie_idle = load_lottie_url(LOTTIE_IDLE_URL)

if "lottie_active" not in st.session_state:
    st.session_state.lottie_active = load_lottie_url(LOTTIE_ACTIVE_URL)

# Initialize global resources
if "initialized" not in st.session_state:
    with st.spinner("🚀 Initializing Amadeus..."):
        db_ok = initialize_database()
        amadeus = get_amadeus_instance()
        
        if not db_ok or not amadeus:
            st.error("❌ Failed to initialize Amadeus. Please refresh the page.")
            st.stop()
        
        st.session_state.initialized = True
        st.session_state.amadeus = amadeus

# --- SIDEBAR: SYSTEM STATUS ---
with st.sidebar:
    st.markdown("## 🖥️ System Status")
    
    # Real-time metrics with error handling
    try:
        cpu = get_cpu_usage() or 0
        mem_data = get_memory_usage() or {"percent": 0}
        mem = mem_data.get("percent", 0) if isinstance(mem_data, dict) else 0
        
        col1, col2 = st.columns(2)
        
        with col1:
            cpu_class = get_status_class(cpu)
            st.markdown(f'<div class="status-badge {cpu_class}">CPU: {cpu:.1f}%</div>', unsafe_allow_html=True)
        
        with col2:
            mem_class = get_status_class(mem)
            st.markdown(f'<div class="status-badge {mem_class}">RAM: {mem:.1f}%</div>', unsafe_allow_html=True)
        
        # Battery with visual indicator
        battery = get_battery_info()
        if isinstance(battery, dict) and "percent" in battery:
            battery_pct = battery["percent"]
            battery_status = battery.get("status", "Unknown")
            battery_emoji = "🔋" if battery_pct > 20 else "🪫"
            st.progress(battery_pct / 100, text=f"{battery_emoji} {battery_pct}% ({battery_status})")
    
    except Exception as e:
        st.error(f"⚠️ System monitoring unavailable: {str(e)[:50]}")
    
    st.divider()
    
    st.markdown("### 🛠️ Quick Controls")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("🧹 Clear Chat", use_container_width=True):
            st.session_state.messages = []
            if hasattr(st.session_state.amadeus, 'conversation'):
                st.session_state.amadeus.conversation.clear()
            st.success("✅ Cleared!")
            time.sleep(0.5)
            st.rerun()
    
    with col_b:
        if st.button("🔄 Refresh", use_container_width=True):
            get_dashboard_data(force_refresh=True)
            st.success("✅ Refreshed!")
            time.sleep(0.5)
            st.rerun()
    
    # Auto-refresh toggle
    auto_refresh = st.checkbox("🔁 Auto-refresh (30s)", value=False)
    
    if auto_refresh:
        # Auto-refresh every 30 seconds
        st_autorefresh = st.empty()
        with st_autorefresh:
            time.sleep(30)
            st.rerun()
    
    st.divider()
    
    # System info
    st.markdown("### ℹ️ About")
    st.caption("**Amadeus AI** v1.0")
    st.caption("Intelligent Assistant")
    st.caption(f"Session: {st.session_state.get('initialized', False)}")
    
    # Data freshness indicator
    if "dashboard_data_timestamp" in st.session_state:
        age = time.time() - st.session_state.dashboard_data_timestamp
        st.caption(f"Data age: {int(age)}s")

# --- MAIN CONTENT ---

# Title with animated effect
st.markdown('<h1 class="main-title">AMADEUS</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Intelligent AI Assistant • Ready to Help</p>', unsafe_allow_html=True)

# --- TOP HEADER CARDS ---
try:
    dashboard_data = get_dashboard_data()
    
    # Cards container
    st.markdown('<div class="header-cards">', unsafe_allow_html=True)
    
    card_cols = st.columns(4)
    
    # Tasks Card
    with card_cols[0]:
        st.markdown(f"""
        <div class="info-card">
            <div class="card-icon">📋</div>
            <div class="card-title">Tasks</div>
            <div class="card-value">{dashboard_data['task_count']} pending</div>
        </div>
        """, unsafe_allow_html=True)
        
        if dashboard_data["tasks"]:
            with st.expander("📋 View Tasks", expanded=False):
                for i, task in enumerate(dashboard_data["tasks"][:3], 1):
                    st.markdown(f"{i}. {task.get('content', 'No content')[:50]}...")
    
    # Notes Card
    with card_cols[1]:
        st.markdown(f"""
        <div class="info-card">
            <div class="card-icon">📝</div>
            <div class="card-title">Notes</div>
            <div class="card-value">{dashboard_data['note_count']} saved</div>
        </div>
        """, unsafe_allow_html=True)
        
        if dashboard_data["notes"]:
            with st.expander("📝 View Notes", expanded=False):
                for i, note in enumerate(dashboard_data["notes"][:3], 1):
                    st.markdown(f"{i}. {note.get('title', 'Untitled')[:50]}")
    
    # Reminders Card
    with card_cols[2]:
        st.markdown(f"""
        <div class="info-card">
            <div class="card-icon">⏰</div>
            <div class="card-title">Reminders</div>
            <div class="card-value">{dashboard_data['reminder_count']} active</div>
        </div>
        """, unsafe_allow_html=True)
        
        if dashboard_data["reminders"]:
            with st.expander("⏰ View Reminders", expanded=False):
                for i, rem in enumerate(dashboard_data["reminders"][:3], 1):
                    st.markdown(f"{i}. {rem.get('title', 'No title')[:50]}")
    
    # Weather Card
    with card_cols[3]:
        weather_text = dashboard_data["weather"]
        if isinstance(weather_text, str) and len(weather_text) > 50:
            weather_short = weather_text[:50] + "..."
        else:
            weather_short = weather_text
        
        st.markdown(f"""
        <div class="info-card">
            <div class="card-icon">🌤️</div>
            <div class="card-title">Weather</div>
            <div class="card-value" style="font-size: 0.85rem;">{weather_short}</div>
        </div>
        """, unsafe_allow_html=True)
        
        if isinstance(weather_text, str) and len(weather_text) > 50:
            with st.expander("🌤️ Full Weather", expanded=False):
                st.info(weather_text)
    
    st.markdown('</div>', unsafe_allow_html=True)

except Exception as e:
    st.error(f"⚠️ Dashboard data error: {str(e)[:100]}")
    logger.error(f"Dashboard rendering error: {e}")

st.markdown("<br>", unsafe_allow_html=True)

# --- MAIN INTERFACE: AVATAR + CHAT ---
anim_col, chat_col = st.columns([1, 3])

with anim_col:
    st.markdown("### 🤖 Status")
    
    # Display animation based on state
    if st.session_state.state == "PROCESSING":
        if st.session_state.lottie_active:
            st_lottie(st.session_state.lottie_active, height=150, key="anim_active")
        else:
            st.markdown('<div class="loading">🔄 Processing...</div>', unsafe_allow_html=True)
        
        # Show processing time
        if st.session_state.processing_start:
            elapsed = time.time() - st.session_state.processing_start
            st.caption(f"⏱️ {elapsed:.1f}s")
    else:
        if st.session_state.lottie_idle:
            st_lottie(st.session_state.lottie_idle, height=150, key="anim_idle")
        else:
            st.success("🟢 Ready")
    
    st.divider()
    
    # Voice input
    st.markdown("### 🎙️ Voice Input")
    voice_text = speech_to_text(
        language='en',
        start_prompt="🎤 Speak",
        stop_prompt="⏹️ Stop",
        just_once=True,
        key='STT'
    )
    
    if voice_text:
        st.success(f"Heard: {voice_text[:30]}...")

with chat_col:
    st.markdown("### 💬 Chat with Amadeus")
    
    # Chat history with auto-scroll
    chat_container = st.container(height=400)
    
    with chat_container:
        if not st.session_state.messages:
            st.info("👋 Say hello to Amadeus or type a command!")
        else:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
    
    st.divider()
    
    # Input controls
    input_col1, input_col2 = st.columns([4, 1])
    
    with input_col1:
        prompt = st.chat_input("Type your command here...", key="chat_input")
    
    with input_col2:
        clear_btn = st.button("🗑️", help="Clear this message", use_container_width=True)
    
    # Determine input source (voice takes priority)
    final_input = voice_text if voice_text else prompt
    
    # Process input
    if final_input:
        # Validate input
        if len(final_input.strip()) == 0:
            st.warning("⚠️ Please enter a valid command")
        elif len(final_input) > 500:
            st.error("❌ Command too long (max 500 characters)")
        else:
            # Add user message
            st.session_state.messages.append({
                "role": "user",
                "content": final_input,
                "timestamp": datetime.now()
            })
            
            # Set processing state
            st.session_state.state = "PROCESSING"
            st.session_state.processing_start = time.time()
            
            # Process with timeout
            try:
                with st.spinner("🤔 Amadeus is thinking..."):
                    amadeus = st.session_state.amadeus
                    
                    # Run with timeout protection
                    async def process_with_timeout():
                        try:
                            return await asyncio.wait_for(
                                amadeus.process_command(final_input),
                                timeout=30.0
                            )
                        except asyncio.TimeoutError:
                            return "⏱️ Request timeout. Please try again with a simpler command."
                    
                    response = run_async(process_with_timeout())
                
                # Add response
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": datetime.now()
                })
                
                # Show success toast
                processing_time = time.time() - st.session_state.processing_start
                st.toast(f"✅ Completed in {processing_time:.1f}s", icon="✅")
                
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
                # Reset state
                st.session_state.state = "IDLE"
                st.session_state.processing_start = None
                
                # Force data refresh after command
                get_dashboard_data(force_refresh=True)
                
                # Rerun to update UI
                st.rerun()

# --- FOOTER ---
st.markdown("---")

footer_cols = st.columns([2, 1, 1])

with footer_cols[0]:
    st.markdown(
        '<p style="color: rgba(255,255,255,0.4); font-size: 0.8rem;">'
        '✨ Amadeus AI Dashboard • Powered by Gemini AI'
        '</p>',
        unsafe_allow_html=True
    )

with footer_cols[1]:
    # Show connection status
    connection_status = "🟢 Connected" if st.session_state.get('initialized', False) else "🔴 Disconnected"
    st.markdown(
        f'<p style="color: rgba(255,255,255,0.4); font-size: 0.8rem; text-align: center;">{connection_status}</p>',
        unsafe_allow_html=True
    )

with footer_cols[2]:
    # Show message count
    msg_count = len(st.session_state.messages)
    st.markdown(
        f'<p style="color: rgba(255,255,255,0.4); font-size: 0.8rem; text-align: right;">Messages: {msg_count}</p>',
        unsafe_allow_html=True
    )

# --- PERFORMANCE MONITORING (OPTIONAL - COMMENTED OUT BY DEFAULT) ---
# Uncomment to see detailed performance metrics in sidebar

# with st.sidebar:
#     with st.expander("🔬 Performance Metrics", expanded=False):
#         if "dashboard_data_timestamp" in st.session_state:
#             fetch_time = time.time() - st.session_state.dashboard_data_timestamp
#             st.metric("Data Age", f"{int(fetch_time)}s")
#         
#         if "processing_start" in st.session_state and st.session_state.processing_start:
#             proc_time = time.time() - st.session_state.processing_start
#             st.metric("Processing Time", f"{proc_time:.2f}s")
#         
#         # Memory usage of session state
#         import sys
#         session_size = sys.getsizeof(st.session_state.messages)
#         st.metric("Session Size", f"{session_size / 1024:.1f} KB")