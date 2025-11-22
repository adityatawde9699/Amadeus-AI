<div align="center">

# 🎭 Amadeus AI

### *Your Intelligent Voice-Powered Personal Assistant*

<br/>

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
<img src="https://img.shields.io/badge/Gemini-AI_Powered-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="Gemini"/>
<img src="https://img.shields.io/badge/SQLite-Database-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite"/>
<img src="https://img.shields.io/badge/License-Apache_2.0-D22128?style=for-the-badge&logo=apache&logoColor=white" alt="License"/>

<br/><br/>

*Amadeus is an advanced, modular AI assistant that combines natural language understanding with powerful system integration capabilities. Designed for productivity enthusiasts and developers alike, it seamlessly bridges the gap between voice commands and actionable tasks.*

<br/>

[Features](#-features) •
[Installation](#-installation) •
[Usage](#-usage) •
[Architecture](#-architecture) •
[API Reference](#-api-reference) •
[Contributing](#-contributing)

<br/>

---

</div>

## 📋 Overview

**Amadeus** is a comprehensive AI assistant built with Python, leveraging Google's Gemini AI for intelligent conversation and task execution. Unlike traditional voice assistants, Amadeus maintains conversational context, learns from interactions, and provides a unified interface for managing your digital life.

<table>
<tr>
<td width="50%">

### ✨ Why Amadeus?

- **Context-Aware Conversations** — Maintains dialogue history for coherent, multi-turn interactions
- **Modular Tool System** — Easily extensible architecture for adding new capabilities
- **Cross-Platform Support** — Works on Windows, macOS, and Linux
- **Privacy-First Design** — All data stored locally with SQLite
- **Dual Interface** — Voice and text input modes available

</td>
<td width="50%">

### 🎯 Ideal For

- Developers seeking a customizable AI assistant
- Productivity enthusiasts managing tasks and notes
- Users who prefer voice-driven workflows
- Anyone wanting hands-free system control
- Teams requiring a self-hosted assistant solution

</td>
</tr>
</table>

---

## 🚀 Features

<table>
<tr>
<td align="center" width="33%">
<br/>
<h3>🧠 Conversational AI</h3>
<p>Powered by <strong>Google Gemini 2.0</strong> for intelligent, context-aware responses with natural language understanding</p>
</td>
<td align="center" width="33%">
<br/>
<h3>🎤 Voice Interface</h3>
<p>Real-time speech recognition via <strong>Faster-Whisper</strong> with natural text-to-speech output using pyttsx3</p>
</td>
<td align="center" width="33%">
<br/>
<h3>📊 System Monitor</h3>
<p>Comprehensive system monitoring including CPU, RAM, GPU, disk usage, and temperature sensors</p>
</td>
</tr>
<tr>
<td align="center" width="33%">
<br/>
<h3>✅ Task Management</h3>
<p>Full-featured task system with creation, completion tracking, filtering, and intelligent summaries</p>
</td>
<td align="center" width="33%">
<br/>
<h3>📝 Notes & Reminders</h3>
<p>Persistent note-taking with tagging support and time-based reminders with natural language parsing</p>
</td>
<td align="center" width="33%">
<br/>
<h3>🌐 Information Hub</h3>
<p>Real-time weather forecasts, news headlines, Wikipedia summaries, and web search integration</p>
</td>
</tr>
</table>

### Complete Feature List

<details>
<summary><strong>🖥️ System Control</strong></summary>
<br/>

| Feature | Description |
|---------|-------------|
| Application Launcher | Open any installed application by name |
| File Search | Recursive file search across directories |
| File Operations | Copy, move, delete files with voice confirmation |
| Directory Management | Create folders and list directory contents |
| Process Manager | View and terminate running processes |
| System Status | Real-time CPU, memory, disk, and GPU monitoring |

</details>

<details>
<summary><strong>📋 Productivity Tools</strong></summary>
<br/>

| Feature | Description |
|---------|-------------|
| Task Creation | Add tasks with natural language |
| Task Filtering | View pending or completed tasks |
| Task Completion | Mark tasks done by ID or content match |
| Note Creation | Create notes with titles, content, and tags |
| Note Search | Filter notes by tags |
| Reminders | Set time-based reminders with natural language parsing |
| Daily Briefing | Automatic summary of tasks, reminders, and weather |

</details>

<details>
<summary><strong>🌍 Information Services</strong></summary>
<br/>

| Feature | Description |
|---------|-------------|
| Weather | Current conditions via OpenWeatherMap API |
| News | Top headlines from NewsAPI by category |
| Wikipedia | Article summaries and search |
| Web Search | Google search via browser |
| Jokes | Random programming and general humor |

</details>

---

## 💻 Installation

### Prerequisites

<table>
<tr>
<td>

**Required**
- Python 3.9 or higher
- pip (Python package manager)
- Working microphone (for voice mode)
- Internet connection

</td>
<td>

**Recommended**
- Virtual environment (venv)
- 4GB+ RAM
- SSD storage
- NVIDIA GPU (optional, for faster Whisper)

</td>
</tr>
</table>

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/Amadeus-AI.git
cd Amadeus-AI
```

### Step 2: Create Virtual Environment

```bash
# Create environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Create a `.env` file in the project root:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Optional (for extended features)
NEWS_API_KEY=your_newsapi_key_here
WEATHER_API_KEY=your_openweathermap_key_here

# Configuration
VOICE_ENABLED=true
AMADEUS_DB_FILE=amadeus.db
```

<details>
<summary><strong>📌 How to Obtain API Keys</strong></summary>
<br/>

| Service | URL | Free Tier |
|---------|-----|-----------|
| Google Gemini | [ai.google.dev](https://ai.google.dev/) | Yes |
| OpenWeatherMap | [openweathermap.org/api](https://openweathermap.org/api) | 1,000 calls/day |
| NewsAPI | [newsapi.org](https://newsapi.org/) | 100 requests/day |

</details>

---

## 🎮 Usage

### Starting Amadeus

<table>
<tr>
<td width="50%">

**Voice Mode** (Default)
```bash
python main.py
```
Speak naturally after the "Listening..." prompt.

</td>
<td width="50%">

**Debug/Text Mode**
```bash
python main.py --debug
```
Type commands directly in the terminal.

</td>
</tr>
</table>

### Command Line Options

```bash
python main.py [OPTIONS]

Options:
  --debug, -d       Run in text-only mode (no voice)
  --no-voice        Disable voice output but run normally
  --brief, -b       Show daily briefing and exit
  --log-level       Set logging level (DEBUG, INFO, WARNING, ERROR)
```

### Example Commands

<table>
<tr>
<th>Category</th>
<th>Example Commands</th>
</tr>
<tr>
<td><strong>Time & Date</strong></td>
<td>
<code>"What time is it?"</code><br/>
<code>"What's today's date?"</code><br/>
<code>"What day is it?"</code>
</td>
</tr>
<tr>
<td><strong>Tasks</strong></td>
<td>
<code>"Add task: buy groceries"</code><br/>
<code>"Show my pending tasks"</code><br/>
<code>"Complete the groceries task"</code>
</td>
</tr>
<tr>
<td><strong>Notes</strong></td>
<td>
<code>"Create a note titled Meeting Notes"</code><br/>
<code>"List all my notes"</code><br/>
<code>"Show notes tagged with work"</code>
</td>
</tr>
<tr>
<td><strong>Reminders</strong></td>
<td>
<code>"Remind me to call Mom tomorrow at 5pm"</code><br/>
<code>"Set a reminder for the meeting in 2 hours"</code><br/>
<code>"Show my reminders"</code>
</td>
</tr>
<tr>
<td><strong>System</strong></td>
<td>
<code>"Open Chrome"</code><br/>
<code>"What's my system status?"</code><br/>
<code>"Search for document.pdf"</code>
</td>
</tr>
<tr>
<td><strong>Information</strong></td>
<td>
<code>"What's the weather in Mumbai?"</code><br/>
<code>"Get the latest tech news"</code><br/>
<code>"Tell me about quantum computing"</code>
</td>
</tr>
</table>

---

## 🏗️ Architecture

### Project Structure

```
Amadeus-AI/
├── 📄 main.py                 # Application entry point
├── 📄 amadeus.py              # Core assistant class and main loop
├── 📄 config.py               # Configuration management
├── 📄 models.py               # SQLAlchemy database models
├── 📄 db.py                   # Async database engine and sessions
│
├── 📁 Utilities/
│   ├── 📄 general_utils.py    # DateTime, weather, news, web utilities
│   ├── 📄 speech_utils.py     # Voice recognition and TTS
│   ├── 📄 memory_utils.py     # Conversation memory persistence
│   ├── 📄 system_controls.py  # File and application management
│   ├── 📄 system_monitor.py   # Hardware monitoring
│   ├── 📄 task_utils.py       # Task CRUD operations
│   ├── 📄 note_utils.py       # Note CRUD operations
│   └── 📄 reminder_utils.py   # Reminder management
│
├── 📄 api.py                  # FastAPI REST endpoints
├── 📄 requirements.txt        # Python dependencies
├── 📄 .env                    # Environment variables (user-created)
└── 📄 amadeus.db              # SQLite database (auto-generated)
```

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                          │
│                   (Voice Input / Text Input)                    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Amadeus Core                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  Conversation   │  │  Tool Selection │  │    Tool        │  │
│  │    Manager      │◄─┤   (Gemini AI)   │─►│   Executor     │  │
│  └─────────────────┘  └─────────────────┘  └────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  System Tools    │  │ Productivity     │  │ Information      │
│  • App Launcher  │  │ • Tasks          │  │ • Weather API    │
│  • File Search   │  │ • Notes          │  │ • News API       │
│  • System Monitor│  │ • Reminders      │  │ • Wikipedia      │
└──────────────────┘  └────────┬─────────┘  └──────────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │  SQLite Database │
                    │   (Async I/O)    │
                    └──────────────────┘
```

### Database Schema

```sql
-- Tasks Table
CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY,
    content     TEXT NOT NULL,
    status      VARCHAR(32) DEFAULT 'pending',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

-- Notes Table
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY,
    title       VARCHAR(256) NOT NULL,
    content     TEXT NOT NULL,
    tags        VARCHAR(512) DEFAULT '',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Reminders Table
CREATE TABLE reminders (
    id          INTEGER PRIMARY KEY,
    title       VARCHAR(256) NOT NULL,
    time        VARCHAR(64) NOT NULL,
    description TEXT DEFAULT '',
    status      VARCHAR(32) DEFAULT 'active',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🔌 API Reference

Amadeus includes a REST API built with FastAPI for programmatic access.

### Starting the API Server

```bash
uvicorn api:app --reload --port 8000
```

### Endpoints

<details>
<summary><strong>Tasks API</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/tasks` | Create a new task |
| `GET` | `/tasks` | List all tasks |
| `POST` | `/tasks/{id}/complete` | Mark task complete |
| `DELETE` | `/tasks/{id}` | Delete a task |

**Example Request:**
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"content": "Review pull requests"}'
```

</details>

<details>
<summary><strong>Notes API</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/notes` | Create a new note |
| `GET` | `/notes` | List all notes |
| `GET` | `/notes/{id}` | Get note by ID |
| `PUT` | `/notes/{id}` | Update a note |
| `DELETE` | `/notes/{id}` | Delete a note |

</details>

<details>
<summary><strong>Reminders API</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/reminders` | Create a reminder |
| `GET` | `/reminders` | List active reminders |
| `DELETE` | `/reminders/{id}` | Delete a reminder |

</details>

---

## 🛠️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ | — | Google Gemini API key |
| `NEWS_API_KEY` | ❌ | — | NewsAPI.org key |
| `WEATHER_API_KEY` | ❌ | — | OpenWeatherMap key |
| `VOICE_ENABLED` | ❌ | `true` | Enable/disable voice |
| `AMADEUS_DB_FILE` | ❌ | `amadeus.db` | Database file path |
| `GEMINI_MODEL` | ❌ | `gemini-2.0-flash` | Gemini model version |

---

## 🤝 Contributing

Contributions are warmly welcomed! Please follow these guidelines to ensure a smooth collaboration process.

### Development Setup

```bash
# Clone your fork
git clone https://github.com/yourusername/Amadeus-AI.git

# Create feature branch
git checkout -b feature/your-feature-name

# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/
```

### Contribution Guidelines

1. **Fork** the repository
2. **Create** a feature branch (`feature/amazing-feature`)
3. **Commit** changes with clear messages
4. **Test** your changes thoroughly
5. **Submit** a pull request

### Code Standards

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write docstrings for public methods
- Include unit tests for new features

---

## 📜 License

This project is licensed under the **Apache License 2.0** — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

<table>
<tr>
<td align="center">
<a href="https://ai.google.dev/">
<strong>Google Gemini</strong>
</a>
<br/>AI Language Model
</td>
<td align="center">
<a href="https://github.com/guillaumekln/faster-whisper">
<strong>Faster-Whisper</strong>
</a>
<br/>Speech Recognition
</td>
<td align="center">
<a href="https://www.sqlalchemy.org/">
<strong>SQLAlchemy</strong>
</a>
<br/>Database ORM
</td>
<td align="center">
<a href="https://fastapi.tiangolo.com/">
<strong>FastAPI</strong>
</a>
<br/>REST API Framework
</td>
</tr>
</table>

---

<div align="center">

**Built with ❤️ by the Amadeus Team**

<br/>

<a href="#-amadeus-ai">⬆️ Back to Top</a>

</div>