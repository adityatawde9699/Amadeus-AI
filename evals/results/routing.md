# Routing eval - LLM-free intent router

## Category head

| Split | n | Accuracy | Macro-F1 | Top-2 acc | Profile acc |
|---|---|---|---|---|---|
| Held-out | 70 | 94.3% | 0.929 | 97.1% | 94.3% |
| 5-fold CV (training phrases) | 969 | 85.7% | 0.840 | - | 88.6% |

## End to end (route + rule-based arguments, no LLM)

75 held-out requests, 61 of them answerable by one tool.

| Metric | Value |
|---|---|
| Handled correctly overall | 100.0% |
| Tool requests finished with **no LLM call** | 86.9% (53/61) |
| Direct dispatches that were right | 100.0% |
| Wrong direct dispatches | 0 |
| Sent to the right expert / chat intent | 22 |
| Sent to the wrong expert / intent | 0 |
| Routing latency p50 / p95 | 0.83 ms / 1.17 ms |

### Failures

- none

### Correctly deferred to the LLM (tool requests)

- `what's NVDA trading at` - finance_expert (tool unsure)
- `how long has this machine been running` - monitor_expert (tool unsure)
- `could you open slack` - os_expert (category unsure)
- `new task: book the dentist` - task_expert (tool unsure)
- `remind me to call the vet in 45 minutes` - task_expert (tool unsure)
- `remember that my car is parked on level 3` - memory_expert (category unsure)
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
