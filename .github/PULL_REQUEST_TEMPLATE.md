## Description
<!-- What does this PR do? Link the related issue with "Closes #<number>" -->

Closes #

## Type of Change
- [ ] 🐛 Bug fix
- [ ] ✨ New feature
- [ ] ♻️ Refactor (no behaviour change)
- [ ] 📝 Documentation
- [ ] 🔒 Security fix
- [ ] ⚡ Performance improvement
- [ ] 🧪 Tests only

## Changes Made
<!-- Bullet-point summary of what changed and why -->
- 

## Testing
- [ ] Unit tests added / updated for all changed code
- [ ] `uv run pytest tests/unit/ -v` passes locally
- [ ] Coverage stays at or above **80%**

## Code Quality
- [ ] `uv run ruff check src/ tests/` — no new lint errors
- [ ] `uv run mypy src/` — no new type errors
- [ ] No bare `except Exception: pass` added
- [ ] All new public functions/classes have docstrings
- [ ] Exception types match semantics (no raising `LLMRateLimitError` for non-rate-limit situations)

## For LLM Adapter PRs
- [ ] New adapter inherits from `src.core.interfaces.llm.LLMAdapter`
- [ ] `is_available()` and `generate_response()` implemented
- [ ] `context` parameter used to inject conversation history
- [ ] Adapter registered in `src/container.py` `_build_llm_router()`
- [ ] `DAILY_LIMITS` entry added in `LLMRouter`

## Breaking Changes
<!-- List any breaking changes or migration steps required -->
None / see below:

## Screenshots / Logs
<!-- For UI or behaviour changes, paste relevant output or screenshots -->
