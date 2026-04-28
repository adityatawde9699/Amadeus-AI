# Development Guide

How to extend Amadeus: adding LLM providers, tools, writing tests, and coding standards.

---

## Adding an LLM Provider

### Step 1 — Create the Adapter

Create `src/infra/llm/<name>_adapter.py` and inherit from `src.core.interfaces.llm.LLMAdapter`:

```python
from src.core.interfaces.llm import LLMAdapter

class MyAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def is_available(self) -> bool:
        # Return True if the provider can accept requests right now
        return bool(self.api_key)

    async def generate_response(
        self,
        prompt: str,
        context: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        # Call provider API and return the response string
        ...
```

### Step 2 — Register in the Container

In `src/container.py` → `_build_llm_router()`:

```python
my_adapter = MyAdapter(api_key=settings.MY_API_KEY)
return LLMRouter(..., my_adapter=my_adapter)
```

### Step 3 — Add Quota Tracking

In `LLMRouter`:
```python
DAILY_LIMITS = {
    ...,
    "my_provider": 5000,
}
COST_PER_REQUEST = {
    ...,
    "my_provider": 0.0001,
}
```

### Step 4 — Write Tests

Create `tests/unit/test_<name>_adapter.py` with mocked HTTP calls.

---

## Adding a Tool

Tools live in `src/infra/tools/`. Use the `@tool` decorator:

```python
from src.infra.tools.base import tool, ToolCategory

@tool(
    name="my_tool",
    description="Does something useful. Trigger: 'do X', 'run Y'",
    category=ToolCategory.INFORMATION,
    parameters={
        "query": {"type": "string", "description": "The thing to process"},
    },
    requires_confirmation=False,  # Set True for destructive operations
)
async def my_tool(query: str) -> str:
    return f"Processed: {query}"
```

### Register the Tool

In `AmadeusService._register_all_tools()`:

```python
from src.infra.tools.my_tools import get_my_tools

for tool in get_my_tools():
    self.tool_registry.register(tool)
```

The `SemanticToolRouter` picks it up automatically on the next startup — **no retraining needed**.

> **Tip:** Write a compelling `description` with example trigger phrases. The semantic router uses this text to embed the tool, so richer descriptions lead to better routing accuracy.

---

## Testing

### Unit Tests *(fast, no I/O)*

```bash
uv run pytest tests/unit/ -v
```

### Full Suite with Coverage

```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
```

**Coverage gate: 80%** — enforced in CI and via `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-fail-under=80"
```

### Integration Tests *(spins up PostgreSQL via testcontainers)*

```bash
uv run pytest tests/ -m integration
```

### Skip Slow Tests

```bash
uv run pytest tests/ -m "not slow"
```

### Load Testing

```bash
locust -f locustfile.py --host http://localhost:8000
```

---

## Coding Standards

| Tool | Purpose | Command |
|---|---|---|
| `ruff` | Lint + format (100 char line length) | `uv run ruff check src/ tests/` |
| `mypy` | Strict type checking | `uv run mypy src/` |
| `bandit` | Security scan (0 HIGH gate) | `uv run bandit -r src/ -ll` |
| `pip-audit` | CVE dependency audit | `uv run pip-audit` |

### Key Conventions

- **Type hints everywhere** — `disallow_untyped_defs = true` in `mypy` config.
- Use domain exceptions from `src.core.exceptions` — never raise `LLMRateLimitError` for non-rate-limit errors.
- **No bare `except Exception: pass`** — always log at minimum `logger.warning(...)`.
- Use lazy `%s` logging: `logger.info("Processing %s", value)` not f-strings in log calls.
- Docstrings on all public classes and methods.
- Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat(llm):`, `fix(tools):`, `docs:`, `test:`, etc.

### Pre-Commit Hooks

```bash
pre-commit install
```

Runs `ruff`, `mypy`, and GitGuardian secret scanning on every commit.

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `scripts/index_workspace.py` | Build / update the hybrid workspace search index |
| `scripts/calibrate_semantic_threshold.py` | Find the optimal routing threshold for your tool set |
| `scripts/initialize_amadeus_identity.py` | Seed identity memories into Qdrant |
| `scripts/verify_identity_storage.py` | Verify identity memories are correctly stored |
| `scripts/build_backend_binary.py` | Build a Windows executable via PyInstaller |
| `scripts/install_windows_service.ps1` | Install Amadeus as a Windows NSSM service |

---

*← [[Deployment]] | [[Observability]] →*
