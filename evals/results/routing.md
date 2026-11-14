# Routing eval - LLM-free intent router

## Category head

| Split | n | Accuracy | Macro-F1 | Top-2 acc | Profile acc |
|---|---|---|---|---|---|
| Held-out | 70 | 95.7% | 0.950 | 98.6% | 95.7% |
| 5-fold CV (training phrases) | 936 | 85.7% | 0.836 | - | 89.4% |

## End to end (route + rule-based arguments, no LLM)

75 held-out requests, 61 of them answerable by one tool.

| Metric | Value |
|---|---|
| Handled correctly overall | 96.0% |
| Tool requests finished with **no LLM call** | 83.6% (51/61) |
| Direct dispatches that were right | 98.1% |
| Wrong direct dispatches | 1 |
| Sent to the right expert / chat intent | 21 |
| Sent to the wrong expert / intent | 2 |
| Routing latency p50 / p95 | 1.07 ms / 1.65 ms |

### Failures

- `can you reach wikipedia.org` - direct_bad: tool:wikipedia_search {"query": "reach wikipedia.org"}
- `where is the database session created in the repo` - llm_bad: expert:filesystem_expert
- `keep in mind that I'm vegetarian` - llm_bad: conversational:None

### Correctly deferred to the LLM (tool requests)

- `what's NVDA trading at` - finance_expert (tool unsure)
- `how long has this machine been running` - monitor_expert (tool unsure)
- `kill the zoom app` - os_expert (category unsure)
- `new task: book the dentist` - task_expert (direct)
- `remind me to call the vet in 45 minutes` - task_expert (tool unsure)
- `look up how to descale a kettle` - research_expert (category unsure)
- `tell me about the Mughal empire` - research_expert (tool unsure)
- `check the weather in Goa and then add a task to pack an umbrella` - research_expert (multi-step)
- `write a python script that sorts a csv and run it` - developer_expert (category unsure)
- `move the report into the archive folder and then email it to Sam` - filesystem_expert (multi-step)

## Held-out recall by category

| Category | Recall | Precision | Support |
|---|---|---|---|
| productivity | 50% | 67% | 4 |
| os_control | 75% | 100% | 4 |
| app_control | 100% | 100% | 4 |
| calculation | 100% | 100% | 4 |
| communication | 100% | 100% | 4 |
| content_generation | 100% | 80% | 4 |
| conversational | 100% | 100% | 8 |
| datetime | 100% | 100% | 4 |
| developer | 100% | 100% | 4 |
| file_system | 100% | 80% | 4 |
| finance | 100% | 100% | 4 |
| monitoring | 100% | 100% | 4 |
| news | 100% | 100% | 4 |
| task_manager | 100% | 100% | 6 |
| weather | 100% | 100% | 4 |
| web_research | 100% | 100% | 4 |

## Held-out category errors

- `put the laptop to sleep` - gold **os_control**, predicted productivity
- `put together a word doc summarizing the quarterly results` - gold **productivity**, predicted content_generation
- `draft the meeting minutes as a docx file` - gold **productivity**, predicted file_system
