# Local model comparison: agent tool selection

Run with `python -m evals.agent_eval --model Model/<file> --configs expert+grammar,generalist+grammar`.
The dataset has 22 tasks, and the score checks the first tool call plus its arguments. Tools are not executed.
The run used grammar-constrained decoding, `n_ctx=4096`, 16 threads, on CPU (2026-11-13).

| Model (Q4_K_M) | File | Model RSS¹ | 1 call² | Expert + grammar | Generalist + grammar | Licence |
|---|---|---|---|---|---|---|
| **Qwen3-4B-Instruct-2507** (default) | 2.4 GB | 4.8 GB | 16.8 s | **100%** (912 s) | **100%** (3899 s) | Apache-2.0 |
| Llama-3.2-3B-Instruct | 1.9 GB | 3.9 GB | 13.5 s | 86% (524 s³) | 73% (2610 s³) | Llama 3.2 |
| Llama-3.2-1B-Instruct | 0.8 GB | 1.5 GB | 4.5 s | 68% (236 s) | 27% (1138 s) | Llama 3.2 |

¹ Peak RSS of llama.cpp alone after one generation, which is what the daemon adds. The eval harness peaked at 5.2 GB for 4B and 4.3 GB for 3B.
² One chat completion with about 1k prompt tokens (a 70-tool menu) and 64 output tokens, on 4 threads.
³ The 3B run shared the CPU with a Docker build, so its times are inflated.

- "Expert" routes each task to its specialist's tool subset first. "Generalist" offers all 70 tools.
- The 1B and 3B failures are wrong-tool picks (`calculate` for unit conversion, `create_goal`/`add_task` for "remember…") and no-call answers. Per-task details are in `agent.md` (1B, all four configs), `agent-llama-3.2-3b.md` and `agent-qwen3-4b.md`.
- 22 tasks is a small set, so treat 100% as "saturates this eval", not as perfect. Add harder cases before comparing larger models.
- The default is Qwen3-4B. On hosts with 4 GB of RAM or less, use Llama-3.2-1B, or run cloud planning with Groq or Gemini and `LOCAL_ONLY_MODE=false`.
