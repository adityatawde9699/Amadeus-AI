<div align="center">

# 🎭 Amadeus AI

### *Your Intelligent Voice-Powered Personal Assistant*

<br/>

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
<img src="https://img.shields.io/badge/Gemini-AI_Powered-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="Gemini"/>
<img src="https://img.shields.io/badge/SQLite-Database-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite"/>
<img src="https://img.shields.io/badge/License-Apache_2.0-D22128?style=for-the-badge&logo=apache&logoColor=white" alt="License"/>

<br/><br/>

*Amadeus is an advanced, modular AI assistant combining natural language understanding with powerful system integration. Designed for developers and productivity enthusiasts, it seamlessly bridges voice commands and actionable tasks.*

<br/>

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [Architecture](#architecture) • [API](#api-reference) • [Contributing](#contributing)

<br/>

---

</div>

## 📋 Overview

**Amadeus** is a comprehensive Python-based AI assistant leveraging Google's Gemini for intelligent conversation and task execution. Unlike traditional voice assistants, Amadeus maintains conversational context, learns from interactions, and provides a unified interface for digital productivity.

<table>
<tr>
<td width="50%">

### ✨ Why Choose Amadeus?

- **Context-Aware Conversations** — Multi-turn dialogue with full history retention
- **Modular Architecture** — Easily extensible tool system for custom capabilities
- **Cross-Platform** — Seamless support for Windows, macOS, and Linux
- **Privacy-Centric** — All data persisted locally using SQLite
- **Dual Input** — Voice and text modes for flexible interaction

</td>
<td width="50%">

### 🎯 Perfect For

- Developers building customizable AI solutions
- Productivity enthusiasts managing complex workflows
- Voice-first users seeking hands-free control
- Teams requiring self-hosted assistant infrastructure
- Researchers exploring modular AI architectures

</td>
</tr>
</table>

---

## 🚀 Features

<table>
<tr>
<td align="center" width="33%">
<h3>🧠 Conversational AI</h3>
<p>Powered by <strong>Google Gemini 2.0</strong> for context-aware responses with advanced natural language understanding</p>
</td>
<td align="center" width="33%">
<h3>🎤 Voice Interface</h3>
<p>Real-time speech recognition via <strong>Faster-Whisper</strong> with natural text-to-speech synthesis</p>
</td>
<td align="center" width="33%">
<h3>📊 System Monitor</h3>
<p>Comprehensive monitoring for CPU, RAM, GPU, disk usage, and thermal sensors</p>
</td>
</tr>
<tr>
<td align="center" width="33%">
<h3>✅ Task Management</h3>
<p>Full-featured task system with creation, tracking, filtering, and intelligent summaries</p>
</td>
<td align="center" width="33%">
<h3>📝 Notes & Reminders</h3>
<p>Persistent note-taking with tag support and intelligent time-based reminder parsing</p>
</td>
<td align="center" width="33%">
<h3>🌐 Information Hub</h3>
<p>Real-time weather, news aggregation, Wikipedia summaries, and web search integration</p>
</td>
</tr>
</table>

### Complete Feature List

<details>
<summary><strong>🖥️ System Control</strong></summary>

| Feature | Description |
|---------|-------------|
| Application Launcher | Open installed applications via voice command |
| File Search & Management | Recursive search, copy, move, delete operations |
| Directory Operations | Create folders and browse directory structures |
| Process Management | Monitor and terminate running processes |
| System Analytics | Real-time CPU, memory, disk, and GPU metrics |

</details>

<details>
<summary><strong>📋 Productivity Tools</strong></summary>

| Feature | Description |
|---------|-------------|
| Smart Task Creation | Add tasks using natural language |
| Task Filtering | View pending or completed items |
| Completion Tracking | Mark tasks done by ID or content matching |
| Note Management | Create, tag, and organize notes |
| Smart Reminders | Natural language time-based reminders |
| Daily Briefing | Automated summary of tasks, reminders, weather |

</details>

<details>
<summary><strong>🌍 Information Services</strong></summary>

| Feature | Description |
|---------|-------------|
| Weather Integration | Real-time conditions via OpenWeatherMap API |
| News Aggregation | Top headlines filtered by category |
| Knowledge Retrieval | Article summaries via Wikipedia |
| Web Search | Integrated Google search functionality |
| Entertainment | Programming humor and general jokes |

</details>

---

## 💻 Installation

### Prerequisites

| **Essential** | **Recommended** |
|---|---|
| Python 3.9+ | Virtual environment (venv) |
| pip package manager | 4GB+ RAM |
| Working microphone | SSD storage |
| Internet connection | NVIDIA GPU (for faster inference) |

### Quick Start

**1. Clone Repository**
```bash
git clone https://github.com/adityatawde9699/Amadeus-AI.git
cd Amadeus-AI
```

**2. Set Up Environment**
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows
```

**3. Install Dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure API Keys**

Create `.env` in project root:
```env
GEMINI_API_KEY=your_key_here
NEWS_API_KEY=your_key_here
WEATHER_API_KEY=your_key_here
VOICE_ENABLED=true
```

<details>
<summary><strong>📌 Obtaining API Keys</strong></summary>

| Service | Link | Free Tier |
|---------|------|-----------|
| Google Gemini | [ai.google.dev](https://ai.google.dev/) | ✅ Available |
| OpenWeatherMap | [openweathermap.org/api](https://openweathermap.org/api) | 1,000 calls/day |
| NewsAPI | [newsapi.org](https://newsapi.org/) | 100 requests/day |

</details>

---

## 🎮 Usage

### Running Amadeus

| Mode | Command | Description |
|------|---------|-------------|
| **Voice** | `python Amadeus/main.py` | Full voice interaction |
| **Debug** | `python Amadeus/main.py --debug` | Text-only mode |
| **Briefing** | `python Amadeus/main.py --brief` | Daily summary only |

### Command Examples

| Category | Examples |
|----------|----------|
| **Time & Date** | "What time is it?" • "Today's date?" |
| **Tasks** | "Add task: buy groceries" • "Show pending tasks" |
| **Notes** | "Create note: Meeting Notes" • "List my notes" |
| **Reminders** | "Remind me to call at 5pm" • "Show reminders" |
| **System** | "Open Chrome" • "System status?" • "Find document.pdf" |
| **Information** | "Weather in Mumbai?" • "Latest tech news" • "Quantum computing" |

---

## 🏗️ Architecture

### Project Layout

```
Amadeus-AI/
├── Amadeus/
│   ├── main.py                # Entry point
│   ├── amadeus.py             # Core assistant logic
│   ├── api.py                 # FastAPI REST server
│   ├── speech_utils.py        # Voice I/O handling
│   ├── task_utils.py          # Task operations
│   ├── system_controls.py     # OS integration
│   └── general_utils.py       # External APIs
├── requirements.txt
├── .env
└── README.md
```

### System Architecture

```
User Input (Voice/Text)
  ↓
   Amadeus Core
   ├→ Conversation Manager
   ├→ Tool Selector (Gemini AI)
   └→ Tool Executor
  ↓
   ┌────┬────┬────────┐
   ↓    ↓    ↓        ↓
 Tasks Notes System Info Services
   ↓
 SQLite Database
```

### Database Schema

```sql
CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY,
    content      TEXT NOT NULL,
    status       VARCHAR(32) DEFAULT 'pending',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notes (
    id           INTEGER PRIMARY KEY,
    title        VARCHAR(256) NOT NULL,
    content      TEXT NOT NULL,
    tags         VARCHAR(512),
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reminders (
    id           INTEGER PRIMARY KEY,
    title        VARCHAR(256) NOT NULL,
    time         VARCHAR(64) NOT NULL,
    status       VARCHAR(32) DEFAULT 'active'
);
```

---

## 🔌 API Reference

Start the REST API server:
```bash
uvicorn Amadeus.api:app --reload --port 8000
```

<details>
<summary><strong>Tasks Endpoints</strong></summary>

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/tasks` | Create task |
| GET | `/tasks` | List all tasks |
| POST | `/tasks/{id}/complete` | Complete task |
| DELETE | `/tasks/{id}` | Delete task |

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"content": "Review PRs"}'
```

</details>

<details>
<summary><strong>Notes Endpoints</strong></summary>

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/notes` | Create note |
| GET | `/notes` | List notes |
| GET | `/notes/{id}` | Get note |
| PUT | `/notes/{id}` | Update note |
| DELETE | `/notes/{id}` | Delete note |

</details>

<details>
<summary><strong>Reminders Endpoints</strong></summary>

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/reminders` | Create reminder |
| GET | `/reminders` | List active |
| DELETE | `/reminders/{id}` | Delete reminder |

</details>

---

## 🛠️ Configuration

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GEMINI_API_KEY` | ✅ | — | Gemini API authentication |
| `NEWS_API_KEY` | ❌ | — | News aggregation service |
| `WEATHER_API_KEY` | ❌ | — | Weather data provider |
| `VOICE_ENABLED` | ❌ | `true` | Toggle voice features |
| `AMADEUS_DB_FILE` | ❌ | `amadeus.db` | Database location |

---

## 🤝 Contributing

### Getting Started

```bash
git clone https://github.com/adityatawde9699/Amadeus-AI.git
git checkout -b feature/your-feature
pip install -r requirements.txt
pytest tests/
```

### Guidelines

1. Fork the repository
2. Create feature branch (`feature/amazing-feature`)
3. Commit with clear messages
4. Test thoroughly
5. Submit pull request

### Code Standards

- Follow PEP 8 guidelines
- Include type hints
- Add docstrings for public methods
- Write unit tests for features

---

## 📜 License

Licensed under **Apache License 2.0** — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

| Project | Role |
|---------|------|
| [Google Gemini](https://ai.google.dev/) | AI Language Model |
| [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) | Speech Recognition |
| [SQLAlchemy](https://www.sqlalchemy.org/) | Database ORM |
| [FastAPI](https://fastapi.tiangolo.com/) | REST API Framework |

---

<div align="center">

**Crafted with ❤️ by Aditya S. Tawde**

[⬆️ Back to Top](#-amadeus-ai)

</div>
