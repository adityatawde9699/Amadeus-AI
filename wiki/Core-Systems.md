# Core Systems

The five core systems that power Amadeus's intelligence and safety.

---

## Semantic Tool Router

**File:** `src/app/services/semantic_router.py`

Replaces the legacy sklearn SVM classifier with a purely mathematical router — **no retraining ever needed**.

### How It Works

1. At startup, every tool's `name + description + category` string is embedded using `sentence-transformers/all-mpnet-base-v2` into a **768-dimensional L2-normalised float32 vector**.
2. The embedding matrix is cached to `Model/semantic_tool_embeddings.npz`. A fingerprint (MD5 of sorted tool names) detects registry changes and triggers automatic cache invalidation.
3. At query time: the user message is embedded and a **single NumPy matrix multiply** computes cosine similarity against all tool vectors — under **10 ms** on an Intel i3.
4. If `best_score >= 0.50`: the matched tool name is returned. Otherwise, `None` is returned and the LLM triage fallback takes over.

### Threshold Calibration

Use the bundled calibration script to find the optimal threshold for your tool set:

```bash
python scripts/calibrate_semantic_threshold.py
```

### Hot-Plugging Tools

Register a new `Tool` in the registry and restart. The router rebuilds its index automatically. No labels, no training data, no retraining.

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
  ├─▶  Dense search  (all-mpnet-base-v2 · cosine sim) ──▶  Top-N semantic matches
  └─▶  BM25 search   (BM25Okapi · code-aware tokeniser)──▶  Top-N lexical matches

RRF score = 1/(k + rank_semantic) + 1/(k + rank_bm25)   [k = 60]

Final results: sorted by RRF score, max 2 hits per file
```

The BM25 tokeniser preserves underscores, so `AUTH_UUID_7392` stays a single token — fixing the core failure mode of pure semantic search on code.

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

**File:** `src/infra/memory_service.py` — class `FlashMemoryCache`

A **Tier-1 L1 cache** that intercepts `QdrantMemoryService.retrieve()` calls using in-process NumPy.

| Property | Value |
|---|---|
| Capacity | 100 entries (ring buffer — oldest overwritten) |
| Memory | 100 × 768 × 4 bytes ≈ **307 KB** |
| Threshold | `cosine_similarity >= 0.85` → cache hit |
| Latency | ~1 µs (single BLAS `@` multiply) vs ~5 ms Qdrant round-trip |
| Invalidation | `clear_conversation()` → `FlashMemoryCache.invalidate()` |

When a new memory is stored via `QdrantMemoryService.store()`, its embedding is simultaneously pushed to the ring buffer. The next retrieval call checks the L1 cache first and only falls through to Qdrant on a miss.

---

## Agent Orchestrator

**File:** `src/app/services/agent_loop.py`

Amadeus runs a **ReAct (Reason + Act)** agent implemented as an async state machine over `asyncio.Queue`.

### State Machine

```
START → THINK → ACT → OBSERVE → THINK → ... → SYNTHESIZE → END
```

The `AgentOrchestrator` runs a **background worker loop** that pulls tasks off a bounded queue (`maxsize=50`). Requests exceeding queue capacity receive `QueueFullError`, surfaced as **HTTP 429**.

### Sub-Agents

| Agent | Max Iterations | Domain |
|---|---|---|
| `SystemAgent` | 3 | OS, volume, screenshots, process control |
| `ResearchAgent` | 5 | Web search, news, weather, documents |
| `ReActAgent` (general) | 4 | Everything else + multi-step reasoning |

Routing between sub-agents uses the legacy SVM classifier if `Model/router_classifier.joblib` exists, falling back to keyword heuristics.

### Cycle Detection

The orchestrator tracks recently executed `(action, frozenset(args))` tuples to detect and terminate repetitive tool-call loops — preventing runaway execution and performance degradation.

### Learning Step

After each agent run, entity/relationship triples are extracted from the interaction and stored in the Knowledge Graph.

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
