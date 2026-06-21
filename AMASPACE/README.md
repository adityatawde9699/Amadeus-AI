# AMASPACE

This is Amadeus AI's personal workspace and the **single source of truth for all
generated artifacts**. Every work product Amadeus produces — research reports,
generated code, exports, execution logs, datasets — is written here, never
streamed back over Telegram. Nothing in this directory is source code; it is
runtime output only.

Persistence is centralised in `src/infra/workspace/` (`WorkspaceManager`,
`ArtifactRegistry`, `StorageService`). Output handlers do **not** write here
directly — they build a `src.core.domain.artifacts.Artifact` and call
`StorageService.persist()`, which guarantees correct placement, collision-safe
naming, metadata, and indexing for free.

## Directory layout

```
AMASPACE/
├── research/        # Deep-research runs: report.md, sources.json, research_manifest.json
├── documents/       # Generated documents (essays, letters, reports)
├── code/            # Generated code files / scripts
├── executions/      # Captured execution results / sandbox transcripts
├── logs/            # Execution + task logs
├── exports/         # One-off exports and any large reply persisted from chat
├── memory/          # Exported memory / knowledge snapshots
├── datasets/        # Generated or collected datasets
├── temp/            # Scratch space (safe to clear)
├── summaries/       # Distilled summaries (legacy)
├── notes/           # Freeform notes (legacy)
├── tasks/           # Exported task lists (legacy)
├── conversations/   # Archived conversation threads (legacy)
└── .index/          # Append-only artifact index (artifacts.jsonl) — do not edit
```

## Traceability

Every artifact carries:

- a **timestamp** (creation time, ISO-8601),
- **metadata** — a sidecar `<file>.meta.json` plus an entry in `.index/artifacts.jsonl`,
- a **traceable origin** — the subsystem/tool and the originating `request_id` / `session_id`.

Text/markdown artifacts also begin with a YAML front-matter block:

```yaml
---
id: <artifact-id>
created: YYYY-MM-DDTHH:MM:SS+00:00
type: research | documents | code | exports | ...
title: <title>
origin: <subsystem>
tags: [...]
---
```

## Rules

1. Amadeus **always** writes into a typed sub-directory — never directly to `AMASPACE/`.
2. No generated file is written outside `AMASPACE` unless explicitly configured
   (`WORKSPACE_ENFORCE_CONTAINMENT=true` enforces this).
3. Old files are never deleted automatically — archiving is a manual decision.
</content>
