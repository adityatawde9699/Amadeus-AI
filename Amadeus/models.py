from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Index
from sqlalchemy.sql import func
from db import Base


class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    status = Column(String(32), default='pending', index=True)  # Indexed for filtering
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Indexed for sorting
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_task_status_created', 'status', 'created_at'),  # For filtering by status and sorting
        Index('idx_task_status_completed', 'status', 'completed_at'),  # For completed tasks queries
    )


class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False, index=True)  # Indexed for search
    content = Column(Text, nullable=False)
    tags = Column(String(512), default='', index=True)  # Indexed for tag filtering
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Indexed for sorting
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_note_tags_created', 'tags', 'created_at'),  # For tag filtering and sorting
        Index('idx_note_created_desc', 'created_at'),  # For recent notes queries
    )


class Reminder(Base):
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    time = Column(String(64), nullable=False, index=True)  # Indexed for time-based queries
    description = Column(Text, default='')
    status = Column(String(32), default='active', index=True)  # Indexed for filtering active reminders
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_reminder_status_created', 'status', 'created_at'),  # For active reminders queries
        Index('idx_reminder_status_time', 'status', 'time'),  # For due reminders check
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
    recurrence = Column(String(64), default='')  # none, daily, weekly, monthly, yearly
    status = Column(String(32), default='active', index=True)  # active, cancelled, completed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_event_start_status', 'start_time', 'status'),  # For active events by time
        Index('idx_event_date_range', 'start_time', 'end_time'),  # For conflict detection
        Index('idx_event_status_created', 'status', 'created_at'),  # For listing events
    )