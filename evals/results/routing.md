# Routing eval — Stage-1 category classifier

| Split | n | Accuracy | Macro-F1 | Top-2 acc | Profile acc |
|---|---|---|---|---|---|
| Held-out | 62 | 88.7% | 0.877 | 91.9% | 88.7% |
| 5-fold CV (train set) | 387 | 67.4% | 0.643 | – | 71.3% |

## Held-out recall by category

| Category | Recall | Precision | Support |
|---|---|---|---|
| news | 50% | 100% | 4 |
| productivity | 50% | 100% | 4 |
| app_control | 75% | 60% | 4 |
| calculation | 75% | 100% | 4 |
| os_control | 75% | 100% | 4 |
| communication | 100% | 100% | 4 |
| content_generation | 100% | 100% | 4 |
| datetime | 100% | 100% | 4 |
| developer | 100% | 80% | 4 |
| file_system | 100% | 80% | 4 |
| finance | 100% | 100% | 4 |
| monitoring | 100% | 80% | 4 |
| task_manager | 100% | 100% | 6 |
| weather | 100% | 80% | 4 |
| web_research | 100% | 80% | 4 |

## Held-out errors

- `could you bring up visual studio code` — gold **app_control**, predicted developer
- `put the laptop to sleep` — gold **os_control**, predicted monitoring
- `what's new in technology this week` — gold **news**, predicted weather
- `latest updates on the elections` — gold **news**, predicted web_research
- `divide 9000 between 4 people` — gold **calculation**, predicted app_control
- `open the budget xlsx and read the totals` — gold **productivity**, predicted app_control
- `draft the meeting minutes as a docx file` — gold **productivity**, predicted file_system
