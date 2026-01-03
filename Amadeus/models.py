from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Index, Enum as SAEnum
from sqlalchemy.sql import func
from db import Base
import enum

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"

class ReminderStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class EventStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    __table_args__ = (
        Index('idx_task_status_created', 'status', 'created_at'),
        Index('idx_task_status_completed', 'status', 'completed_at'),
    )


class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False, index=True)
    content = Column(Text, nullable=False)
    tags = Column(String(512), default='', index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    
    __table_args__ = (
        Index('idx_note_tags_created', 'tags', 'created_at'),
        Index('idx_note_created_desc', 'created_at'),
    )


class Reminder(Base):
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    # Changed from String to DateTime for proper scheduling
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    description = Column(Text, default='')
    status = Column(SAEnum(ReminderStatus), default=ReminderStatus.ACTIVE, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    __table_args__ = (
        Index('idx_reminder_status_created', 'status', 'created_at'),
        Index('idx_reminder_status_time', 'status', 'time'),
    )


class CalendarEvent(Base):
    """Calendar event model for scheduling and agenda management."""
    __tablename__ = 'calendar_events'
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, default='')
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False, index=True)
    location = Column(String(256), default='')
    all_day = Column(Boolean, default=False)
    recurrence = Column(String(64), default='')
    status = Column(SAEnum(EventStatus), default=EventStatus.ACTIVE, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_event_start_status', 'start_time', 'status'),
        Index('idx_event_date_range', 'start_time', 'end_time'),
        Index('idx_event_status_created', 'status', 'created_at'),
    )