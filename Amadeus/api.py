from fastapi import FastAPI, HTTPException
from typing import List, Optional
import task_utils
import note_utils
import reminder_utils
from db import init_db_async
import asyncio

app = FastAPI(title="Amadeus API", version="0.1")

# background task handle
_reminder_task: Optional[asyncio.Task] = None
_reminder_stop_event: Optional[asyncio.Event] = None


@app.on_event('startup')
async def startup_event():
    # Initialize DB and start reminder checker
    await init_db_async()
    global _reminder_task, _reminder_stop_event
    _reminder_stop_event = asyncio.Event()
    _reminder_task = asyncio.create_task(reminder_utils.check_due_reminders_loop(_reminder_stop_event))


@app.on_event('shutdown')
async def shutdown_event():
    global _reminder_task, _reminder_stop_event
    if _reminder_stop_event:
        _reminder_stop_event.set()
    if _reminder_task:
        await _reminder_task


@app.post('/tasks', tags=['tasks'])
async def create_task(payload: dict):
    content = payload.get('content')
    if not content:
        raise HTTPException(status_code=400, detail='content is required')
    return await task_utils.add_task(content)


@app.get('/tasks', tags=['tasks'])
async def read_tasks(status: Optional[str] = None):
    return await task_utils.list_tasks(status)


@app.post('/tasks/{task_id}/complete', tags=['tasks'])
async def complete_task(task_id: str):
    return {"result": await task_utils.complete_task(task_id)}


@app.delete('/tasks/{task_id}', tags=['tasks'])
async def delete_task(task_id: str):
    return {"result": await task_utils.delete_task(task_id)}


@app.post('/notes', tags=['notes'])
async def create_note(payload: dict):
    title = payload.get('title')
    content = payload.get('content')
    if not title or not content:
        raise HTTPException(status_code=400, detail='title and content are required')
    tags = payload.get('tags', [])
    return await note_utils.create_note(title, content, tags)


@app.get('/notes', tags=['notes'])
async def list_notes(tag: Optional[str] = None):
    return await note_utils.list_notes(tag)


@app.get('/notes/{note_id}', tags=['notes'])
async def get_note(note_id: int):
    return await note_utils.get_note(note_id)


@app.put('/notes/{note_id}', tags=['notes'])
async def update_note(note_id: int, payload: dict):
    return await note_utils.update_note(note_id, payload.get('title'), payload.get('content'), payload.get('tags'))


@app.delete('/notes/{note_id}', tags=['notes'])
async def delete_note(note_id: int):
    return await note_utils.delete_note(note_id)


@app.post('/reminders', tags=['reminders'])
async def create_reminder(payload: dict):
    title = payload.get('title')
    time = payload.get('time')
    if not title or not time:
        raise HTTPException(status_code=400, detail='title and time are required')
    description = payload.get('description', '')
    return await reminder_utils.add_reminder(title, time, description)


@app.get('/reminders', tags=['reminders'])
async def list_reminders():
    return await reminder_utils.list_reminders()


@app.delete('/reminders/{reminder_id}', tags=['reminders'])
async def delete_reminder(reminder_id: int):
    return await reminder_utils.delete_reminder(reminder_id)
