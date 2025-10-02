from fastapi import FastAPI, HTTPException
from typing import List, Optional
import task_utils
import note_utils
import reminder_utils

app = FastAPI(title="Amadeus API", version="0.1")


@app.post('/tasks', tags=['tasks'])
def create_task(payload: dict):
    content = payload.get('content')
    if not content:
        raise HTTPException(status_code=400, detail='content is required')
    return task_utils.add_task(content)


@app.get('/tasks', tags=['tasks'])
def read_tasks(status: Optional[str] = None):
    return task_utils.list_tasks(status)


@app.post('/tasks/{task_id}/complete', tags=['tasks'])
def complete_task(task_id: str):
    return {"result": task_utils.complete_task(task_id)}


@app.delete('/tasks/{task_id}', tags=['tasks'])
def delete_task(task_id: str):
    return {"result": task_utils.delete_task(task_id)}


@app.post('/notes', tags=['notes'])
def create_note(payload: dict):
    title = payload.get('title')
    content = payload.get('content')
    if not title or not content:
        raise HTTPException(status_code=400, detail='title and content are required')
    tags = payload.get('tags', [])
    return note_utils.create_note(title, content, tags)

@app.get('/notes', tags=['notes'])
def list_notes(tag: Optional[str] = None):
    return note_utils.list_notes(tag)


@app.get('/notes/{note_id}', tags=['notes'])
def get_note(note_id: int):
    return note_utils.get_note(note_id)


@app.put('/notes/{note_id}', tags=['notes'])
def update_note(note_id: int, payload: dict):
    return note_utils.update_note(note_id, payload.get('title'), payload.get('content'), payload.get('tags'))


@app.delete('/notes/{note_id}', tags=['notes'])
def delete_note(note_id: int):
    return note_utils.delete_note(note_id)

def create_reminder(payload: dict):
    title = payload.get('title')
    time = payload.get('time')
    if not title or not time:
        raise HTTPException(status_code=400, detail='title and time are required')
    description = payload.get('description', '')
    return reminder_utils.add_reminder(title, time, description)
    description = payload.get('description', '')
    return reminder_utils.add_reminder(title, time, description)


@app.get('/reminders', tags=['reminders'])
def list_reminders():
    return reminder_utils.list_reminders()


@app.delete('/reminders/{reminder_id}', tags=['reminders'])
def delete_reminder(reminder_id: int):
    return reminder_utils.delete_reminder(reminder_id)
