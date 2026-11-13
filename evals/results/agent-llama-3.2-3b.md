# Agent tool-selection eval — Llama-3.2-3B-Instruct-Q4_K_M.gguf

22 tasks; first tool call + argument checks. Tools are not executed.

| Config | Pass rate | Time |
|---|---|---|
| expert+grammar | 86% | 524.2s |
| generalist+grammar | 73% | 2609.7s |

## Failures — expert+grammar

- `convert 100 fahrenheit to celsius` — wrong tool calculate (`calculate` {"expression": "100 - 32"})
- `what time is it` — no tool call (FINISH or error)
- `remember that my favourite colour is teal` — wrong tool create_goal (`create_goal` {"title": "Favourite Colour", "description": "Remember the user's favourite colour, teal."})

## Failures — generalist+grammar

- `convert 100 fahrenheit to celsius` — wrong tool calculate (`calculate` {"expression": "100 F - 32 * 5/9"})
- `weather in Mumbai right now` — no tool call (FINISH or error)
- `give me the latest technology headlines` — wrong tool web_search (`web_search` {"query": "latest technology news"})
- `read the file notes/todo.md` — no tool call (FINISH or error)
- `what time is it` — no tool call (FINISH or error)
- `remember that my favourite colour is teal` — wrong tool add_task (`add_task` {"task_content": "Remember my favourite colour is teal", "content": ""})
