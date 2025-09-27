# Amadeus AI 🤖: Your Personal Voice Assistant



**Amadeus** is an intelligent, voice-powered personal assistant built with Python. Designed to be a singular, cohesive AI companion, it integrates with your system, productivity tools, and online services to streamline daily tasks. It understands natural language, manages your schedule, and provides real-time information, all through a seamless conversational interface.

<div align="center">

[![Python Version](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Contributions Welcome](https://img.shields.io/badge/Contributions-welcome-brightgreen.svg?style=flat)](./CONTRIBUTING.md)

</div>

---

## 🌟 Key Features

Amadeus is packed with features to make you more productive and keep you informed.

| Category              | Features                                                                                                                                              |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **🧠 Conversational AI** | Powered by **Google's Gemini Pro** for context-aware, human-like responses.                                                                             |
| **🗣️ Voice Interaction** | Hands-free control with real-time speech recognition and a natural-sounding text-to-speech voice.                                                     |
| **✅ Productivity Suite** | Manage **tasks**, take **notes**, and set active **reminders** with natural language.                                                                 |
| **📧 Email Integration** | Read, summarize, and send emails directly from your **Gmail** account.                                                                                |
| **🖥️ System Control** | Open applications, search for files, manage system resources (CPU, GPU, RAM), and more.                                                               |
| **🌐 Information Hub** | Fetch **news** headlines, get real-time **weather** forecasts, and search **Wikipedia** for concise summaries.                                         |

---

## 🚀 Getting Started

Follow these steps to get Amadeus running on your local machine.

### 1. Prerequisites

* **Python 3.9+**
* **Git** for cloning the repository.
* A working microphone and speakers for voice interaction.

### 2. Installation & Setup

1.  **Clone the Repository**
    ```bash
    git clone (https://github.com/your-username/Amadeus-AI.git)
    cd Amadeus-AI
    ```

2.  **Create and Activate a Virtual Environment**
    A virtual environment keeps your project dependencies isolated.
    ```bash
    # Create the environment
    python -m venv venv

    # Activate it
    # On Windows:
    venv\Scripts\activate
    # On macOS/Linux:
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

### 3. API & Credentials Configuration

Amadeus requires several API keys to function.

1.  **Create a `.env` file** in the root directory of the project. Copy the contents of `.env.example` (if provided) or create it from scratch with the following content:
    ```env
    GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
    NEWS_API_KEY="YOUR_NEWSAPI_ORG_KEY"
    WEATHER_API_KEY="YOUR_OPENWEATHERMAP_API_KEY"
    ```

2.  **Set up Google API Credentials (for Gmail)**
    This is required for the email and calendar functionalities.

    <details>
    <summary><b>Click here for a step-by-step guide</b></summary>

    1.  Go to the [Google Cloud Console](https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com) and enable the **Gmail API**.
    2.  Create a new project if you don't have one already.
    3.  Go to "Credentials" on the left-hand menu.
    4.  Click "+ CREATE CREDENTIALS" and select "OAuth client ID".
    5.  Choose **"Desktop app"** as the application type and give it a name.
    6.  Click "CREATE", then "DOWNLOAD JSON" to download your `credentials.json` file.
    7.  Place the downloaded `credentials.json` file in the root directory of this project.
    8.  The first time you run a command that uses the Gmail API, a browser window will open asking you to authorize access. After you approve, a `token.json` file will be created automatically. **Do not share this file.**

    </details>

---

## 🏃‍♀️ Usage

To start the assistant, run `main.py` from your terminal.

* **For voice-based interaction:**
    ```bash
    python main.py
    ```
* **For text-based interaction (no microphone needed):**
    ```bash
    python main.py --debug
    ```

### Example Commands

Try saying "Hey Amadeus," followed by one of these commands:

* *"What's the latest news on technology?"*
* *"Summarize my last 5 unread emails."*
* *"Set a reminder to call the bank tomorrow at 4 pm."*
* *"Add 'buy groceries' to my to-do list."*
* *"What's the weather like in New Delhi?"*
* *"Open Google Chrome and search for the Eiffel Tower."*
* *"Tell me about the Roman Empire."*
* *"What's my current CPU usage?"*

---

## 🏛️ Project Architecture

Amadeus is built on a modular architecture to make it easy to extend and maintain. The core AI dynamically selects the appropriate "tool" based on your command.
```bash
Amadeus-AI/
│
├── main.py             # Main entry point to run the assistant
├── amadeus.py          # Core Amadeus class, manages state and the main interaction loop
├── requirements.txt    # Project dependencies
├── .env                # API keys and environment variables (you create this)
├── credentials.json    # Google API credentials (you add this)
│
└── tools/              # Directory for all functional modules
├── init.py
├── email_handler.py
├── task_manager.py
├── system_control.py
├── web_search.py
└── ... (etc.)
```
---

## 🤝 Contributing

Contributions are what make the open-source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

Please refer to the `CONTRIBUTING.md` file for detailed guidelines on how to get started.

1.  **Fork the Project**
2.  **Create your Feature Branch** (`git checkout -b feature/AmazingFeature`)
3.  **Commit your Changes** (`git commit -m 'Add some AmazingFeature'`)
4.  **Push to the Branch** (`git push origin feature/AmazingFeature`)
5.  **Open a Pull Request**

---

## 📜 License

Distributed under the Apache License. See `LICENSE` for more information.
