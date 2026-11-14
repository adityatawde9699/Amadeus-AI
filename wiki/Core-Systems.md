# Core Systems

The core systems that power Amadeus's intelligence and safety.

---

## Agent Graph (cognitive core)

**File:** `src/app/services/agent_loop.py` (`AmadeusGraph`, LangGraph `StateGraph`)

All planning and execution happens in one explicit graph:

1. **orchestrate** — decides whether the request needs one expert or several sub-tasks.
2. **supervisor** — dispatches each sub-task to an expert agent profile.
3. **expert plan → tool → reflect** — the expert picks a tool, the `ToolExecutor`
   runs it through the policy engine (permission profile, HITL confirmation,
   taint gate), and reflection decides to continue, retry or `FINISH`.
4. **collect → synthesize** — expert results are merged into the final answer.

Risky tools pause the graph with `interrupt()`; `aresume()` continues it after
approval. State is checkpointed (SQLite saver when configured, in-memory
otherwise), so a paused run survives until it is approved or denied.

### Execution journal

**File:** `src/runtime/cognitive/core.py`

`AmadeusRuntime.process_task` wraps each request in a journal entry: one run
(`cognitive_plans`) with one step and one observation recording the outcome or
error, plus `plan.*` events on the runtime event bus. It does not plan or verify
by itself — that is the graph above. (Until 2026-11 this module emulated a
plan/verify/reflect state machine around a single hard-coded step.)

---

## Intent Router

**Files:** `src/app/services/intent_router.py`, `routing_data.py`, `slot_extractor.py`

Decides how each message is handled **without calling an LLM**, in about 1 ms:

1. **Hard rule:** a URL goes to `fetch_webpage_content`. Slash commands are handled earlier by the command router. There are no other keyword overrides.
2. **Category head:** a softmax classifier over MiniLM sentence embeddings picks a tool category or a chat intent (`conversational`, `content_generation`, `cloud_escalation`).
3. **Tool head:** a second classifier picks the tool inside the winning category. When the runner-up category is close, its tools compete too, and the winning tool decides the category.
4. **Arguments:** `slot_extractor.py` fills the tool's arguments with rules (numbers and units, tickers, paths, hostnames, times, "the rest of the sentence"). It returns nothing instead of guessing.

| Outcome | When | LLM calls |
|---|---|---|
| Direct tool dispatch | Category and tool are both confident, the request is a single step, and rules filled the arguments | 0, or 1 to phrase the reply (`TOOL_RESPONSE_MODE`) |
| Expert agent | Tool category is clear but the tool or its arguments are not, or the request has several steps | As before |
| Chat / content | A chat intent wins | 1 |

Both classifiers are trained in numpy at startup from the phrases in `routing_data.py` plus each registered tool's name and `Trigger:` phrases. Training takes under a second, and the phrase embeddings are cached in `Model/intent_router.npz`. There is no build-time artifact and no scikit-learn. Embeddings come from the quantized ONNX `all-MiniLM-L6-v2` (`scripts/export_embedding_onnx.py`); a fresh checkout falls back to sentence-transformers (`[ml-fallback]` extra).

**Fixing a misroute:** add a phrase to `TOOL_EXAMPLES` or `TRAINING_DATA` in `routing_data.py`, then run `uv run python -m evals.routing_eval`. Thresholds (`CATEGORY_GAP`, `TOOL_MARGIN`) are constants at the top of `intent_router.py`. Results are in `evals/results/routing.md`; CI fails if held-out accuracy, the LLM-free rate or wrong dispatches regress.

`TOOL_RESPONSE_MODE` controls the reply for a single tool result: `llm` rephrases it (one call), `direct` returns the tool's own output (no call), and `auto` (default) uses `llm` with a GPU or a cloud provider and `direct` on CPU-only local inference.

### Hot-Plugging Tools

Register a new `Tool` in the registry and restart. Tools are reached through their category's expert profile, so a new tool in an existing category needs no retraining; a new category needs `TRAINING_DATA` entries and a classifier rebuild.

```python
# Check router readiness
GET /api/v1/health/detailed
# {"classifier_enabled": true, ...}
```

---

## Omni-Workspace RAG

**File:** `src/infra/workspace_indexer.py`  
**CLI:** `scripts/index_workspace.py`

Builds a persistent **hybrid retrieval index** over a local file tree.

### Supported File Types

`.py` · `.md` · `.txt` · `.toml` · `.yaml` · `.yml` · `.env` · `.json` · `.cfg` · `.ini` · `.rst` · `.pdf`

### Dual-Retrieval Fusion

```
Query
  ├─▶  Dense search  (MiniLM-L6 ONNX · cosine sim)    ──▶  Top-N semantic matches
  └─▶  BM25 search   (BM25Okapi · code-aware tokeniser)──▶  Top-N lexical matches

RRF score = 1/(k + rank_semantic) + 1/(k + rank_bm25)   [k = 60]

Final results: sorted by RRF score, max 2 hits per file
```

The BM25 tokeniser preserves underscores, so `AUTH_UUID_7392` stays a single token — fixing the core failure mode of pure semantic search on code.

Dense embeddings use the int8 ONNX `all-MiniLM-L6-v2` export (the same model the router uses), falling back to sentence-transformers only if the export is missing. Before 2026-11 the indexer required sentence-transformers, which the default install and Docker image don't ship, so `build()` returned without indexing anything. On the wiki corpus, hybrid fusion scores recall@1 72% / MRR 0.81 vs 64% / 0.76 BM25-only and 60% / 0.75 dense-only (`evals/rag_eval.py`, `evals/results/rag.md`).

### Context-Augmented Chunking

Each chunk is enriched with a file-level metadata header before being passed to the embedding model:

```
[File: amadeus_service.py | Type: Python | Imports: asyncio, logging, genai | Globals: TOOL_TIMEOUTS]
class AmadeusService:
    ...
```

The display snippet and BM25 corpus always use raw chunk text. Only the encoder input is enriched.

### Incremental Builds

Only files with changed `mtime` or MD5 content hash are re-embedded. A 10,000-file workspace re-indexes in seconds after a single file change.

### RAM Budget

Default `max_chunks=15,000` → ~46 MB embedding matrix + ~20 MB BM25 corpus. Safe on 4 GB machines.

```bash
# Full rebuild
python scripts/index_workspace.py --root "~/Projects" --force

# Custom root and output directory
python scripts/index_workspace.py --root "~/Projects" --index-dir "data/my_index"
```

---

## Flash Memory Cache

**File:** `src/infra/turbovec_memory.py` — class `FlashMemoryCache`

A **Tier-1 L1 cache** that intercepts `TurbovecMemoryService.retrieve()` calls using in-process NumPy.

| Property | Value |
|---|---|
| Capacity | 100 entries (ring buffer — oldest overwritten) |
| Memory | 100 × 768 × 4 bytes ≈ **307 KB** |
| Threshold | `cosine_similarity >= 0.85` → cache hit |
| Latency | ~1 µs (single BLAS `@` multiply) vs ~1 ms Turbovec search |
| Invalidation | `clear_conversation()` → `FlashMemoryCache.invalidate()` |

When a new memory is stored via `TurbovecMemoryService.store()`, its embedding is simultaneously pushed to the ring buffer. The next retrieval call checks the L1 cache first and only falls through to Turbovec on a miss.

---

## LangGraph Agent Loop

**File:** `src/app/services/agent_loop.py`

Amadeus runs an **Agentic (Reason + Act)** agent implemented as a LangGraph state machine.

### State Machine

```
START → THINK → ACT → OBSERVE → THINK → ... → SYNTHESIZE → END
```

The state machine explicitly orchestrates tool execution and context updates, persisting its state via a SQLite checkpointer to support resumable episodic memory.

### Sub-Agents

| Agent | Max Iterations | Domain |
|---|---|---|
| `LangGraphAgent` | 4 | Multi-step reasoning and autonomous planning |

Routing to tools is handled purely by the `SemanticToolRouter` or direct explicit tool assignments.

---

## Human-in-the-Loop (HITL)

Tools decorated with `requires_confirmation=True` are **paused before execution**. The `ToolExecutor` calls `ConfirmationCallback.request_approval()` and blocks until approved, denied, or timed out (60 s → auto-deny).

### Confirmation Backends

| Class | Transport | Used In |
|---|---|---|
| `TerminalConfirmationCallback` | stdin `y/n` | CLI / tests |
| `APIConfirmationCallback` | HTTP — `POST /api/v1/confirm/{request_id}` | FastAPI server |
| `TelegramConfirmationCallback` | Inline keyboard buttons | Telegram long-polling |

### Destructive Tools Requiring Confirmation

`terminate_program` · `delete_file` · `execute_python_script` · `fs_write_file` · `send_outlook_email` · `send_email` · `send_slack_message`

### READ_ONLY Permission Profile

Hard-denies all `requires_confirmation=True` tools regardless of the callback — prevents guest-tier users from executing destructive operations.

---

*← [[Architecture]] | [[Tool-Registry]] →*
