# Contributing to Amadeus-AI

Thank you for your interest in contributing! Amadeus-AI is an open-source, local-first AI assistant built with Clean Architecture principles. We welcome contributions of all sizes — from typo fixes to new LLM adapters.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Issues](#reporting-issues)

---

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold these standards.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/Amadeus-AI.git
   cd Amadeus-AI
   ```
3. Set the upstream remote:
   ```bash
   git remote add upstream https://github.com/adityatawde9699/Amadeus-AI.git
   ```

---

## Development Setup

Amadeus-AI uses [`uv`](https://github.com/astral-sh/uv) for fast, reproducible dependency management.

```bash
# Install uv (if not already installed)
pip install uv

# Install all dependencies (including dev/test extras)
uv sync --all-extras --dev

# Copy the example environment file
cp .env.example .env
# Edit .env and fill in at least one LLM provider key, OR set SLM_MODEL_PATH
# for a fully offline setup with a local GGUF model.

# Run database migrations
uv run alembic upgrade head

# Start the API server
uv run uvicorn src.api.server:app --reload --port 8765
```

### Optional: Local Model (Offline Mode)

To run completely offline with `llama-cpp-python`:

```bash
# Install llama-cpp-python (CPU-only)
pip install llama-cpp-python

# Download a GGUF model (e.g. Mistral 7B Q4)
# Place it in the Model/ directory, then set in .env:
# SLM_MODEL_PATH=./Model/your-model.gguf
```

---

## Project Structure

```
src/
├── api/          # FastAPI routes, middleware, auth
├── app/          # Use-cases, services, agent loop
│   └── services/
│       ├── agent_loop.py         ← LangGraph cognitive core state machine
│       ├── amadeus_service.py    ← main AI service + SemanticToolRouter integration
│       └── semantic_router.py   ← zero-training tool router (all-mpnet-base-v2)
├── core/         # Domain models, exceptions, interfaces (no external deps)
│   ├── domain/
│   ├── interfaces/
│   │   └── llm.py               ← LLMAdapter ABC (all adapters must implement this)
│   └── exceptions.py
└── infra/        # Infrastructure implementations
    ├── llm/      ← LLM adapters (add new providers here)
    ├── cache/
    ├── persistence/
    ├── search/
    ├── speech/
    ├── turbovec_memory.py       ← FlashMemoryCache (L1) + Turbovec Deep RAG (L2)
    ├── workspace_indexer.py     ← Hybrid BM25+dense workspace RAG
    └── tools/    ← All Amadeus tools (add new tools here)
        └── workspace_tools.py   ← search_workspace tool
scripts/
    └── index_workspace.py       ← CLI to build/update the workspace RAG index
tests/
├── unit/         # Fast, isolated unit tests (no I/O)
└── integration/  # Tests that need DB / external services
```

---

## How to Contribute

### Adding a New LLM Provider

1. Create `src/infra/llm/<name>_adapter.py`
2. Inherit from `src.core.interfaces.llm.LLMAdapter`
3. Implement `is_available()` and `generate_response()` at minimum
4. Register the adapter in `src/container.py` → `_build_llm_router()`
5. Add `PROVIDER_DAILY_LIMITS` entry in `LLMRouter.DAILY_LIMITS`
6. Write unit tests in `tests/unit/test_<name>_adapter.py`

### Adding a New Tool

Tools live in `src/infra/tools/`. Each tool is a `ToolDefinition` registered via the `ToolRegistry`. See `src/infra/tools/info_tools.py` for a minimal example.

### Bug Fixes

- Open an issue first (unless it's a trivial fix) to discuss the approach.
- Branch naming: `fix/<short-description>` (e.g. `fix/llama-context-injection`)

### New Features

- Open a **Feature Request** issue first so we can discuss design before you invest time coding.
- Branch naming: `feat/<short-description>` (e.g. `feat/openai-vision-adapter`)

---

## Coding Standards

We enforce these automatically on every PR:

| Tool | Purpose | Command |
|------|---------|---------|
| **ruff** | Lint + format | `uv run ruff check src/ tests/` |
| **mypy** | Type checking | `uv run mypy src/` |
| **bandit** | Security scan | `uv run bandit -r src/ -ll` |

Key conventions:
- **Type hints everywhere** — `disallow_untyped_defs = true` is enforced
- **Exceptions**: use domain exceptions from `src.core.exceptions` — never raise `LLMRateLimitError` for non-rate-limit situations
- **No bare `except Exception: pass`** — always log at minimum `logger.warning(...)`
- **Docstrings** on all public classes and methods
- Line length: **100 characters**

---

## Testing

```bash
# Run unit tests only (fast, no external services)
uv run pytest tests/unit/ -v

# Run all tests with coverage
uv run pytest tests/ --cov=src --cov-report=term-missing

# Run a specific test file
uv run pytest tests/unit/test_llm_router.py -v
```

Coverage gate: **80%** minimum. New code must be accompanied by tests.

---

## Submitting a Pull Request

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes and write tests.
3. Run quality checks locally:
   ```bash
   uv run ruff check src/ tests/
   uv run mypy src/
   uv run pytest tests/ --cov=src --cov-fail-under=80
   ```
4. Commit with a descriptive message (we follow [Conventional Commits](https://www.conventionalcommits.org/)):
   ```
   feat(llm): add Anthropic Claude adapter
   fix(llama): use correct exception types for model load failures
   docs: update CONTRIBUTING with new tool guide
   ```
5. Push and open a PR against `main`.
6. Fill in the PR template and link any related issues.

---

## Reporting Issues

Use the [issue templates](.github/ISSUE_TEMPLATE/) — either **Bug Report** or **Feature Request**. Include as much detail as possible: OS, Python version, error tracebacks, and steps to reproduce.

For **security vulnerabilities**, please follow the [Security Policy](SECURITY.md) and do **not** open a public issue.
