"""
AMADEUS AI v3.0 - Next-Generation JARVIS Interface
Complete redesign with holographic effects, 3D animations, and premium UX
Key Improvements:
- Holographic gradient animations on title
- 3D glassmorphism cards with animated borders
- Quantum-style progress indicators
- Neural network scanning effects
- Enhanced micro-interactions
- Optimized performance
"""

import streamlit as st
import time, asyncio, logging
from typing import Dict, Any, Optional
from datetime import datetime
from functools import lru_cache
import threading, sys, os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from amadeus import Amadeus
from task_utils import list_tasks
from note_utils import list_notes
from reminder_utils import ReminderManager
from system_monitor import get_cpu_usage, get_memory_usage, get_battery_info, get_disk_usage
from general_utils import get_weather_async
from db import init_db_async

st.set_page_config(page_title="AMADEUS v3.0", page_icon="🔮", layout="wide")

# COMPRESSED CSS - All essential styles
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@500;700&family=Audiowide&display=swap');
:root{--cyan:#00f0ff;--blue:#0080ff;--purple:#a855f7;--pink:#ff006e}
#MainMenu,footer,header,.stDeployButton{display:none!important}
.stApp{background:radial-gradient(circle at 20% 20%,rgba(0,240,255,0.15),transparent 40%),radial-gradient(circle at 80% 80%,rgba(168,85,247,0.15),transparent 40%),linear-gradient(180deg,#000,#0a0e17 40%,#111827);background-attachment:fixed}
.stApp::before{content:"";position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,240,255,0.03) 2px,rgba(0,240,255,0.03) 4px);pointer-events:none;z-index:1;animation:scan 20s linear infinite}
@keyframes scan{100%{transform:translateY(100px)}}
.stApp::after{content:"";position:fixed;inset:0;background-image:linear-gradient(rgba(0,240,255,0.05) 1px,transparent 1px),linear-gradient(90deg,rgba(0,240,255,0.05) 1px,transparent 1px);background-size:60px 60px;pointer-events:none;z-index:1;animation:grid 4s ease-in-out infinite}
@keyframes grid{0%,100%{opacity:0.3}50%{opacity:0.6}}
.holo-title{font-family:Audiowide,cursive!important;font-size:5rem;font-weight:900;text-align:center;background:linear-gradient(135deg,#00f0ff,#0080ff 20%,#a855f7 40%,#ff006e 60%,#00f0ff 80%);background-size:400% 400%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:holo-grad 6s ease infinite,float 3s ease-in-out infinite;padding:2rem 0 1rem;text-shadow:0 0 40px rgba(0,240,255,0.5);letter-spacing:18px;position:relative;z-index:10}
@keyframes holo-grad{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
@keyframes float{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-5px) scale(1.02)}}
.holo-sub{font-family:Rajdhani,sans-serif!important;text-align:center;background:linear-gradient(90deg,transparent,var(--cyan),transparent);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.1rem;letter-spacing:8px;margin-bottom:2rem;text-transform:uppercase;animation:sub-glow 2s ease-in-out infinite alternate}
@keyframes sub-glow{to{filter:brightness(1.5)}}
.nexus{background:linear-gradient(135deg,rgba(15,23,42,0.95),rgba(30,41,59,0.85) 50%,rgba(15,23,42,0.95));backdrop-filter:blur(30px);border:2px solid transparent;border-radius:20px;padding:2rem;position:relative;overflow:hidden;transition:all 0.5s;box-shadow:0 10px 40px rgba(0,0,0,0.6),0 0 0 1px rgba(0,240,255,0.15)}
.nexus::before{content:"";position:absolute;inset:-2px;background:linear-gradient(45deg,var(--cyan),var(--blue),var(--purple),var(--cyan));background-size:400%;border-radius:20px;z-index:-1;opacity:0;animation:border-flow 3s ease infinite;transition:opacity 0.5s}
.nexus:hover::before{opacity:1}
@keyframes border-flow{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
.nexus::after{content:"";position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:linear-gradient(45deg,transparent 30%,rgba(0,240,255,0.1) 50%,transparent 70%);transform:rotate(45deg);animation:shine 3s ease infinite}
@keyframes shine{100%{transform:translateX(100%) rotate(45deg)}}
.nexus:hover{transform:translateY(-8px) scale(1.02);box-shadow:0 20px 60px rgba(0,240,255,0.3),0 0 40px rgba(0,240,255,0.2)}
.q-stat{background:radial-gradient(circle at top,rgba(0,240,255,0.15),transparent 70%),linear-gradient(145deg,rgba(15,23,42,0.98),rgba(30,41,59,0.95));backdrop-filter:blur(20px);border:2px solid rgba(0,240,255,0.2);border-radius:24px;padding:1.75rem;text-align:center;position:relative;overflow:hidden;transition:all 0.4s}
.q-stat::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--cyan),transparent);animation:q-scan 2s linear infinite}
@keyframes q-scan{100%{transform:translateX(100%)}}
.q-stat:hover{border-color:var(--cyan);box-shadow:0 0 30px rgba(0,240,255,0.4);transform:translateY(-4px)}
.q-icon{font-size:3rem;margin-bottom:1rem;filter:drop-shadow(0 0 10px rgba(0,240,255,0.5));animation:icon 2s ease-in-out infinite}
@keyframes icon{0%,100%{transform:scale(1)}50%{transform:scale(1.1)}}
.q-label{font-family:Orbitron,sans-serif!important;color:var(--cyan);font-size:0.75rem;text-transform:uppercase;letter-spacing:4px;margin-bottom:0.75rem;font-weight:700;text-shadow:0 0 10px rgba(0,240,255,0.6)}
.q-val{font-family:Rajdhani,sans-serif!important;color:#fff;font-size:1.6rem;font-weight:800;text-shadow:0 0 15px rgba(255,255,255,0.5)}
.badge{display:inline-flex;align-items:center;gap:0.6rem;padding:0.6rem 1.4rem;border-radius:50px;font-family:monospace!important;font-size:0.8rem;font-weight:600;letter-spacing:2px;text-transform:uppercase;position:relative;overflow:hidden}
.badge::before{content:"";position:absolute;top:0;left:-100%;width:100%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.2),transparent);animation:shimmer 2s infinite}
@keyframes shimmer{100%{left:200%}}
.online{background:rgba(0,255,136,0.2);color:#00ff88;border:2px solid rgba(0,255,136,0.4);box-shadow:0 0 20px rgba(0,255,136,0.3);animation:pulse 1.5s infinite}
@keyframes pulse{50%{box-shadow:0 0 30px rgba(0,255,136,0.6)}}
.prog{width:100px;height:100px;position:relative;margin:0 auto 1rem}
.prog svg{transform:rotate(-90deg);filter:drop-shadow(0 0 10px rgba(0,240,255,0.6))}
.prog-txt{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-family:Orbitron!important;font-size:1.3rem;font-weight:800;color:#fff;text-shadow:0 0 20px rgba(0,240,255,0.8)}
[data-testid="stSidebar"]{background:linear-gradient(180deg,rgba(0,0,0,0.98),rgba(10,14,23,0.98) 50%,rgba(17,24,39,0.95));border-right:2px solid rgba(0,240,255,0.2);backdrop-filter:blur(30px);box-shadow:5px 0 30px rgba(0,240,255,0.1)}
.stChatMessage{background:rgba(15,23,42,0.9)!important;border:2px solid rgba(0,240,255,0.2)!important;border-radius:20px!important;backdrop-filter:blur(15px)!important;margin-bottom:1.5rem!important;box-shadow:0 5px 25px rgba(0,0,0,0.4)!important;transition:all 0.3s!important}
.stChatMessage:hover{border-color:rgba(0,240,255,0.4)!important;box-shadow:0 0 25px rgba(0,240,255,0.2)!important}
.stChatInput>div{background:rgba(15,23,42,0.95)!important;border:2px solid rgba(0,240,255,0.3)!important;border-radius:20px!important;backdrop-filter:blur(20px)!important}
.stChatInput input{background:transparent!important;color:#fff!important;font-family:Rajdhani!important;font-size:1.05rem!important}
.stButton>button{background:linear-gradient(135deg,rgba(0,240,255,0.25),rgba(0,128,255,0.25))!important;border:2px solid rgba(0,240,255,0.5)!important;border-radius:16px!important;color:var(--cyan)!important;font-family:Orbitron!important;font-weight:700!important;letter-spacing:2px!important;padding:0.7rem 1.8rem!important;transition:all 0.4s!important;text-transform:uppercase!important;box-shadow:0 0 20px rgba(0,240,255,0.2)!important}
.stButton>button:hover{background:linear-gradient(135deg,rgba(0,240,255,0.5),rgba(0,128,255,0.4))!important;border-color:var(--cyan)!important;box-shadow:0 0 35px rgba(0,240,255,0.5)!important;transform:translateY(-3px) scale(1.05)!important;color:#fff!important}
.streamlit-expanderHeader{background:rgba(15,23,42,0.8)!important;border:2px solid rgba(0,240,255,0.25)!important;border-radius:16px!important;color:#fff!important;font-family:Orbitron!important}
hr{border:none;height:2px;background:linear-gradient(90deg,transparent,var(--cyan) 20%,var(--purple) 50%,var(--cyan) 80%,transparent);margin:2rem 0;box-shadow:0 0 10px rgba(0,240,255,0.5)}
::-webkit-scrollbar{width:10px}
::-webkit-scrollbar-track{background:rgba(10,14,23,0.8);border-radius:5px}
::-webkit-scrollbar-thumb{background:linear-gradient(180deg,var(--cyan),var(--blue));border-radius:5px;box-shadow:0 0 10px rgba(0,240,255,0.5)}
.bar{display:flex;justify-content:center;align-items:center;gap:2.5rem;padding:1rem 2.5rem;background:linear-gradient(135deg,rgba(10,14,23,0.9),rgba(15,23,42,0.85));border:2px solid rgba(0,240,255,0.2);border-radius:50px;margin:0 auto 2rem;width:fit-content;box-shadow:0 5px 25px rgba(0,0,0,0.3);backdrop-filter:blur(20px)}
.bar-item{display:flex;align-items:center;gap:0.7rem;font-family:monospace!important;color:rgba(255,255,255,0.8);font-size:0.9rem}
.bar-icon{color:var(--cyan);font-size:1.2rem;filter:drop-shadow(0 0 5px currentColor)}
.typing{display:flex;align-items:center;gap:0.7rem;padding:1.2rem;background:rgba(15,23,42,0.8);border-radius:16px;border:1px solid rgba(0,240,255,0.2)}
.dot{width:10px;height:10px;background:var(--cyan);border-radius:50%;box-shadow:0 0 10px currentColor;animation:bounce 1.4s infinite ease-in-out both}
.dot:nth-child(1){animation-delay:-0.32s}
.dot:nth-child(2){animation-delay:-0.16s}
@keyframes bounce{0%,80%,100%{transform:scale(0.5);opacity:0.3}40%{transform:scale(1.2);opacity:1}}
.welcome{text-align:center;padding:3.5rem}
.welcome h3{font-family:Audiowide!important;background:linear-gradient(135deg,var(--cyan),var(--purple));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:1rem}
.w-icon{font-size:4.5rem;margin-bottom:1.5rem;animation:float2 3s ease-in-out infinite;filter:drop-shadow(0 0 20px rgba(0,240,255,0.6))}
@keyframes float2{0%,100%{transform:translateY(0)}50%{transform:translateY(-15px)}}
</style>""", unsafe_allow_html=True)

def run_async(coro):
    try:
        return asyncio.run(coro)
    except:
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(coro)
        except Exception as e:
            logger.error(f"Async error: {e}")
            return None

def create_progress(pct, lbl, col="#00f0ff"):
    c = 2 * 3.14159 * 42
    o = c - (pct / 100) * c
    return f'<div class="prog"><svg width="100" height="100"><defs><linearGradient id="g-{lbl}"><stop offset="0%" stop-color="{col}"/><stop offset="100%" stop-color="#a855f7"/></linearGradient></defs><circle cx="50" cy="50" r="42" fill="none" stroke="rgba(0,240,255,0.15)" stroke-width="8"/><circle cx="50" cy="50" r="42" fill="none" stroke="url(#g-{lbl})" stroke-width="8" stroke-linecap="round" stroke-dasharray="{c}" stroke-dashoffset="{o}"/></svg><div class="prog-txt">{pct:.0f}%</div></div><div class="q-label">{lbl}</div>'

@st.cache_resource
def init_db():
    try:
        run_async(init_db_async())
        return True
    except:
        return False

@st.cache_resource
def get_amadeus():
    try:
        return Amadeus(debug_mode=True, voice_enabled=False)
    except:
        return None

@st.cache_resource
def get_reminders():
    try:
        return ReminderManager()
    except:
        return None

async def fetch_data():
    async def safe(coro, default):
        try:
            return await coro
        except:
            return default
    t, n, r, w = await asyncio.gather(
        safe(list_tasks("pending"), []),
        safe(list_notes(), []),
        safe(asyncio.to_thread(lambda: get_reminders().list_reminders() if get_reminders() else []), []),
        safe(get_weather_async("India"), "Weather unavailable")
    )
    return {"tasks":t[:5],"task_count":len(t),"notes":n[:3],"note_count":len(n),"reminders":r[:3],"reminder_count":len(r),"weather":w,"timestamp":datetime.now()}

def get_data(refresh=False):
    t = time.time()
    if refresh or "dash_data" not in st.session_state or "dash_time" not in st.session_state or (t - st.session_state.dash_time) > 30:
        try:
            d = run_async(fetch_data())
            st.session_state.dash_data = d
            st.session_state.dash_time = t
            return d
        except:
            return st.session_state.get("dash_data", {"tasks":[],"task_count":0,"notes":[],"note_count":0,"reminders":[],"reminder_count":0,"weather":"N/A","timestamp":datetime.now()})
    return st.session_state.dash_data

if "messages" not in st.session_state:
    st.session_state.messages = []
if "state" not in st.session_state:
    st.session_state.state = "IDLE"
if "init" not in st.session_state:
    with st.spinner("🔮 Initializing AMADEUS v3.0..."):
        if not init_db() or not get_amadeus():
            st.error("❌ Init failed. Refresh page.")
            st.stop()
        st.session_state.init = True
        st.session_state.amadeus = get_amadeus()

with st.sidebar:
    st.markdown('<div style="text-align:center;padding:1rem 0"><div style="font-size:3.5rem;filter:drop-shadow(0 0 15px rgba(0,240,255,0.6))">🔮</div><div style="font-family:Audiowide;font-size:1.4rem;background:linear-gradient(135deg,#00f0ff,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:6px">AMADEUS</div><div style="font-size:0.7rem;color:rgba(0,240,255,0.6);letter-spacing:3px;margin-top:0.3rem">v3.0 NEURAL</div></div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown('<div style="font-family:Orbitron;font-size:0.8rem;color:#00f0ff;letter-spacing:2px;margin-bottom:1rem">◈ SYSTEM</div>', unsafe_allow_html=True)
    
    try:
        cpu = get_cpu_usage() or 0
        mem = (get_memory_usage() or {}).get("percent", 0)
        c1, c2 = st.columns(2)
        with c1:
            cc = "#00ff88" if cpu < 70 else "#ffc107" if cpu < 85 else "#ff5252"
            st.markdown(create_progress(cpu, "CPU", cc), unsafe_allow_html=True)
        with c2:
            mc = "#00ff88" if mem < 70 else "#ffc107" if mem < 85 else "#ff5252"
            st.markdown(create_progress(mem, "RAM", mc), unsafe_allow_html=True)
        
        bat = get_battery_info()
        if isinstance(bat, dict) and "percent" in bat:
            st.progress(bat["percent"]/100)
            st.caption(f"{'⚡' if 'charging' in bat.get('status','').lower() else '🔋'} {bat['percent']}%")
    except:
        st.error("⚠️ Monitor error")
    
    st.markdown("---")
    st.markdown('<div style="font-family:Orbitron;font-size:0.8rem;color:#00f0ff;letter-spacing:2px;margin-bottom:1rem">◈ CONTROLS</div>', unsafe_allow_html=True)
    ca, cb = st.columns(2)
    with ca:
        if st.button("🧹 CLEAR", use_container_width=True):
            st.session_state.messages = []
            st.toast("✅ Cleared")
            time.sleep(0.2)
            st.rerun()
    with cb:
        if st.button("🔄 SYNC", use_container_width=True):
            get_data(True)
            st.toast("✅ Synced")
            time.sleep(0.2)
            st.rerun()
    
    st.markdown("---")
    st.markdown(f'<div style="text-align:center"><span class="badge online"><span style="width:8px;height:8px;background:currentColor;border-radius:50%"></span>{"ONLINE" if st.session_state.get("init") else "OFFLINE"}</span></div>', unsafe_allow_html=True)

st.markdown('<h1 class="holo-title">AMADEUS</h1>', unsafe_allow_html=True)
st.markdown('<p class="holo-sub">Neural Intelligence System</p>', unsafe_allow_html=True)

now = datetime.now()
st.markdown(f'<div class="bar"><div class="bar-item"><span class="bar-icon">🕐</span><span>{now.strftime("%H:%M")}</span></div><div class="bar-item"><span class="bar-icon">📅</span><span>{now.strftime("%A, %b %d")}</span></div><div class="bar-item"><span class="bar-icon">⚡</span><span>{"Processing" if st.session_state.state == "PROCESSING" else "Ready"}</span></div></div>', unsafe_allow_html=True)

try:
    data = get_data()
    cols = st.columns(4)
    with cols[0]:
        st.markdown(f'<div class="q-stat"><span class="q-icon">📋</span><div class="q-label">Tasks</div><div class="q-val">{data["task_count"]} pending</div></div>', unsafe_allow_html=True)
        if data["tasks"]:
            with st.expander("View"):
                for i, t in enumerate(data["tasks"][:3], 1):
                    st.markdown(f"**{i}.** {t.get('content','')[:40]}...")
    with cols[1]:
        st.markdown(f'<div class="q-stat"><span class="q-icon">📝</span><div class="q-label">Notes</div><div class="q-val">{data["note_count"]} saved</div></div>', unsafe_allow_html=True)
        if data["notes"]:
            with st.expander("View"):
                for i, n in enumerate(data["notes"][:3], 1):
                    st.markdown(f"**{i}.** {n.get('title','')[:40]}")
    with cols[2]:
        st.markdown(f'<div class="q-stat"><span class="q-icon">⏰</span><div class="q-label">Reminders</div><div class="q-val">{data["reminder_count"]} active</div></div>', unsafe_allow_html=True)
        if data["reminders"]:
            with st.expander("View"):
                for i, r in enumerate(data["reminders"][:3], 1):
                    st.markdown(f"**{i}.** {r.get('title','')[:40]}")
    with cols[3]:
        w = data["weather"]
        ws = w[:30]+"..." if len(w) > 30 else w
        st.markdown(f'<div class="q-stat"><span class="q-icon">🌤️</span><div class="q-label">Weather</div><div class="q-val" style="font-size:1rem">{ws}</div></div>', unsafe_allow_html=True)
except Exception as e:
    st.error(f"⚠️ Data error")

st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div style="font-family:Orbitron;font-size:1rem;color:#00f0ff;letter-spacing:3px;margin-bottom:1rem">◈ COMMUNICATION INTERFACE</div>', unsafe_allow_html=True)

chat = st.container(height=420)
with chat:
    if not st.session_state.messages:
        st.markdown('<div class="welcome"><div class="w-icon">🔮</div><h3>Welcome to AMADEUS</h3><p style="color:rgba(255,255,255,0.5)">Your neural AI assistant is ready.<br>Type a command or ask a question to begin.</p></div>', unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"]=="user" else "🔮"):
                st.markdown(msg["content"])

if st.session_state.state == "PROCESSING":
    st.markdown('<div class="typing"><div class="dot"></div><div class="dot"></div><div class="dot"></div><span style="margin-left:0.5rem;color:rgba(255,255,255,0.6)">AMADEUS thinking...</span></div>', unsafe_allow_html=True)

prompt = st.chat_input("Enter command...")

if prompt and len(prompt.strip()) > 0 and len(prompt) <= 500:
    st.session_state.messages.append({"role":"user","content":prompt,"timestamp":datetime.now()})
    st.session_state.state = "PROCESSING"
    
    try:
        async def process():
            try:
                return await asyncio.wait_for(st.session_state.amadeus.process_command(prompt), timeout=30)
            except asyncio.TimeoutError:
                return "⏱️ Timeout. Try simpler command."
        
        with st.spinner(""):
            response = run_async(process())
        
        st.session_state.messages.append({"role":"assistant","content":response,"timestamp":datetime.now()})
        st.toast("✅ Complete", icon="✨")
    except Exception as e:
        err = f"❌ Error: {str(e)[:100]}"
        st.session_state.messages.append({"role":"assistant","content":err,"timestamp":datetime.now()})
        st.error(err)
    finally:
        st.session_state.state = "IDLE"
        get_data(True)
        st.rerun()

st.markdown('<div style="text-align:center;margin-top:3rem;padding:1rem;border-top:2px solid rgba(0,240,255,0.1)"><div style="font-family:Audiowide;font-size:0.9rem;background:linear-gradient(90deg,#00f0ff,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent">◈ AMADEUS AI v3.0 • NEURAL EDITION ◈</div><div style="margin-top:0.5rem;font-size:0.7rem;color:rgba(255,255,255,0.3)">Powered by Gemini AI • Built with Streamlit</div></div>', unsafe_allow_html=True)