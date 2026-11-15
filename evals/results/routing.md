# Routing eval - LLM-free intent router

## Category head

| Split | n | Accuracy | Macro-F1 | Top-2 acc | Profile acc |
|---|---|---|---|---|---|
| Held-out | 70 | 94.3% | 0.929 | 97.1% | 94.3% |
| 5-fold CV (training phrases) | 958 | 84.9% | 0.837 | - | 87.9% |

## End to end (route + rule-based arguments, no LLM)

75 held-out requests, 61 of them answerable by one tool.

| Metric | Value |
|---|---|
| Handled correctly overall | 96.0% |
| Tool requests finished with **no LLM call** | 82.0% (50/61) |
| Direct dispatches that were right | 98.0% |
| Wrong direct dispatches | 1 |
| Sent to the right expert / chat intent | 22 |
| Sent to the wrong expert / intent | 2 |
| Routing latency p50 / p95 | 0.82 ms / 1.21 ms |

### Failures

- `can you reach wikipedia.org` - direct_bad: tool:wikipedia_search {"query": "reach wikipedia.org"}
- `where is the database session created in the repo` - llm_bad: expert:filesystem_expert
- `keep in mind that I'm vegetarian` - llm_bad: conversational:None

### Correctly deferred to the LLM (tool requests)

- `what's NVDA trading at` - finance_expert (tool unsure)
- `how long has this machine been running` - monitor_expert (tool unsure)
- `show the processes eating the most memory` - monitor_expert (tool unsure)
- `could you open slack` - os_expert (tool unsure)
- `kill the zoom app` - os_expert (category unsure)
- `new task: book the dentist` - task_expert (tool unsure)
- `look up how to descale a kettle` - research_expert (category unsure)
- `tell me about the Mughal empire` - research_expert (tool unsure)
- `check the weather in Goa and then add a task to pack an umbrella` - research_expert (multi-step)
- `write a python script that sorts a csv and run it` - developer_expert (category unsure)
- `move the report into the archive folder and then email it to Sam` - filesystem_expert (multi-step)

## Held-out recall by category

| Category | Recall | Precision | Support |
|---|---|---|---|
| productivity | 25% | 50% | 4 |
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
| monitoring | 100% | 80% | 4 |
| news | 100% | 100% | 4 |
| task_manager | 100% | 100% | 6 |
| weather | 100% | 100% | 4 |
| web_research | 100% | 100% | 4 |

## Held-out category errors

- `put the laptop to sleep` - gold **os_control**, predicted productivity
- `put together a word doc summarizing the quarterly results` - gold **productivity**, predicted content_generation
- `open the budget xlsx and read the totals` - gold **productivity**, predicted monitoring
- `draft the meeting minutes as a docx file` - gold **productivity**, predicted file_system
