# calendar_utils.py
"""
Calendar event management utilities for Amadeus AI Assistant.
Provides CRUD operations for calendar events with natural language time parsing.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.sql import func

from db import get_async_session
import models
import config
import dateparser
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_datetime(time_str: str) -> Optional[datetime]:
    """
    Parse natural language time string into datetime.
    
    Args:
        time_str: Natural language time like "tomorrow at 2pm", "next Monday 10am"
    
    Returns:
        Parsed datetime or None if parsing fails
    """
    try:
        parsed = dateparser.parse(
            time_str,
            settings={
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': datetime.now(),
                'RETURN_AS_TIMEZONE_AWARE': True,
            }
        )
        if parsed and parsed.tzinfo is None:
            # Make timezone-aware using local timezone
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception as e:
        logger.warning(f"Failed to parse datetime '{time_str}': {e}")
        return None


def format_event_time(event: models.CalendarEvent) -> str:
    """Format event time for display."""
    if event.all_day:
        return event.start_time.strftime("%A, %B %d")
    
    start_str = event.start_time.strftime("%I:%M %p")
    end_str = event.end_time.strftime("%I:%M %p")
    date_str = event.start_time.strftime("%A, %B %d")
    
    return f"{date_str} from {start_str} to {end_str}"


def format_event_display(event: models.CalendarEvent, include_date: bool = True) -> str:
    """Format event for voice/text display."""
    if include_date:
        time_str = format_event_time(event)
    else:
        if event.all_day:
            time_str = "All day"
        else:
            time_str = f"{event.start_time.strftime('%I:%M %p')} - {event.end_time.strftime('%I:%M %p')}"
    
    result = f"{event.title}: {time_str}"
    if event.location:
        result += f" at {event.location}"
    return result


# ============================================================================
# CRUD OPERATIONS
# ============================================================================

async def add_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: str = "",
    location: str = "",
    all_day: bool = False,
    recurrence: str = ""
) -> Dict[str, Any]:
    """
    Add a new calendar event.
    
    Args:
        title: Event title
        start_time: Start time (natural language or ISO format)
        end_time: End time (optional, defaults to 1 hour after start)
        description: Event description
        location: Event location
        all_day: Whether this is an all-day event
        recurrence: Recurrence pattern (daily, weekly, monthly, yearly)
    
    Returns:
        Dict with event details or error message
    """
    # Parse start time
    start_dt = parse_datetime(start_time)
    if not start_dt:
        return {"error": f"Could not understand the time '{start_time}'. Try something like 'tomorrow at 2pm'."}
    
    # Parse or calculate end time
    if end_time:
        end_dt = parse_datetime(end_time)
        if not end_dt:
            return {"error": f"Could not understand the end time '{end_time}'."}
    else:
        # Default to configured duration (default 1 hour)
        duration = getattr(config, 'CALENDAR_DEFAULT_EVENT_DURATION', 60)
        end_dt = start_dt + timedelta(minutes=duration)
    
    # Validate time order
    if end_dt <= start_dt:
        return {"error": "End time must be after start time."}
    
    # Check for conflicts
    conflicts = await check_conflicts(start_dt, end_dt)
    if conflicts:
        conflict_titles = ", ".join([c['title'] for c in conflicts[:3]])
        logger.info(f"Event conflicts with: {conflict_titles}")
        # We still create the event but warn the user
    
    async with get_async_session() as db:
        event = models.CalendarEvent(
            title=title,
            description=description,
            start_time=start_dt,
            end_time=end_dt,
            location=location,
            all_day=all_day,
            recurrence=recurrence,
            status='active'
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        
        result = {
            "id": event.id,
            "title": event.title,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "message": f"Event '{title}' scheduled for {format_event_time(event)}."
        }
        
        if conflicts:
            result["warning"] = f"Note: This overlaps with {len(conflicts)} other event(s)."
            result["message"] += f" Warning: overlaps with {conflict_titles}."
        
        return result


async def list_events(
    date: Optional[str] = None,
    days_ahead: int = 7,
    include_past: bool = False,
    limit: Optional[int] = None
) -> str:
    """
    List calendar events.
    
    Args:
        date: Specific date to list (natural language)
        days_ahead: Number of days to look ahead
        include_past: Include past events
        limit: Maximum events to return
    
    Returns:
        Formatted list of events
    """
    max_events = limit or getattr(config, 'CALENDAR_MAX_EVENTS_DISPLAY', 10)
    
    async with get_async_session() as db:
        stmt = select(models.CalendarEvent).where(
            models.CalendarEvent.status == 'active'
        )
        
        if date:
            # Parse specific date
            target_date = parse_datetime(date)
            if target_date:
                # Get events for that day
                day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                stmt = stmt.where(
                    and_(
                        models.CalendarEvent.start_time >= day_start,
                        models.CalendarEvent.start_time < day_end
                    )
                )
        else:
            # Get upcoming events
            now = datetime.now(timezone.utc)
            if not include_past:
                stmt = stmt.where(models.CalendarEvent.end_time >= now)
            
            future_limit = now + timedelta(days=days_ahead)
            stmt = stmt.where(models.CalendarEvent.start_time <= future_limit)
        
        stmt = stmt.order_by(models.CalendarEvent.start_time).limit(max_events)
        
        result = await db.execute(stmt)
        events = result.scalars().all()
        
        if not events:
            if date:
                return f"No events scheduled for {date}."
            return "No upcoming events scheduled."
        
        # Format output
        lines = []
        current_date = None
        
        for event in events:
            event_date = event.start_time.strftime("%A, %B %d")
            if event_date != current_date:
                current_date = event_date
                lines.append(f"\n{event_date}:")
            
            lines.append(f"  • {format_event_display(event, include_date=False)}")
        
        header = f"Upcoming events ({len(events)}):" if not date else f"Events for {date}:"
        return header + "".join(lines)


async def get_event(event_id: int) -> Dict[str, Any]:
    """Get a single event by ID."""
    async with get_async_session() as db:
        stmt = select(models.CalendarEvent).where(models.CalendarEvent.id == event_id)
        result = await db.execute(stmt)
        event = result.scalars().first()
        
        if not event:
            return {"error": f"Event with ID {event_id} not found."}
        
        return {
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "location": event.location,
            "all_day": event.all_day,
            "recurrence": event.recurrence,
            "status": event.status,
            "display": format_event_display(event)
        }


async def update_event(
    event_id: int,
    title: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None
) -> str:
    """Update an existing event."""
    async with get_async_session() as db:
        stmt = select(models.CalendarEvent).where(models.CalendarEvent.id == event_id)
        result = await db.execute(stmt)
        event = result.scalars().first()
        
        if not event:
            return f"Event with ID {event_id} not found."
        
        updates = {}
        if title:
            updates['title'] = title
        if description is not None:
            updates['description'] = description
        if location is not None:
            updates['location'] = location
        if start_time:
            parsed = parse_datetime(start_time)
            if parsed:
                updates['start_time'] = parsed
            else:
                return f"Could not understand the time '{start_time}'."
        if end_time:
            parsed = parse_datetime(end_time)
            if parsed:
                updates['end_time'] = parsed
            else:
                return f"Could not understand the time '{end_time}'."
        
        if updates:
            await db.execute(
                update(models.CalendarEvent)
                .where(models.CalendarEvent.id == event_id)
                .values(**updates)
            )
            await db.commit()
        
        return f"Event '{event.title}' updated successfully."


async def delete_event(identifier: str) -> str:
    """
    Delete a calendar event by ID or title search.
    
    Args:
        identifier: Event ID (numeric) or title to search
    
    Returns:
        Status message
    """
    async with get_async_session() as db:
        event = None
        
        # Try to find by ID first
        if identifier.isdigit():
            stmt = select(models.CalendarEvent).where(models.CalendarEvent.id == int(identifier))
            result = await db.execute(stmt)
            event = result.scalars().first()
        
        # If not found, search by title
        if not event:
            stmt = select(models.CalendarEvent).where(
                and_(
                    models.CalendarEvent.title.ilike(f"%{identifier}%"),
                    models.CalendarEvent.status == 'active'
                )
            )
            result = await db.execute(stmt)
            event = result.scalars().first()
        
        if not event:
            return f"No event found matching '{identifier}'."
        
        # Soft delete by updating status
        await db.execute(
            update(models.CalendarEvent)
            .where(models.CalendarEvent.id == event.id)
            .values(status='cancelled')
        )
        await db.commit()
        
        return f"Event '{event.title}' has been cancelled."


# ============================================================================
# AGENDA & SCHEDULING HELPERS
# ============================================================================

async def get_today_agenda() -> str:
    """Get today's schedule with all events."""
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    return await list_events(date="today", limit=20)


async def get_upcoming_events(hours: int = 24) -> str:
    """Get events in the next N hours."""
    async with get_async_session() as db:
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=hours)
        
        stmt = select(models.CalendarEvent).where(
            and_(
                models.CalendarEvent.status == 'active',
                models.CalendarEvent.start_time >= now,
                models.CalendarEvent.start_time <= future
            )
        ).order_by(models.CalendarEvent.start_time)
        
        result = await db.execute(stmt)
        events = result.scalars().all()
        
        if not events:
            return f"No events in the next {hours} hours."
        
        lines = [f"Events in the next {hours} hours:"]
        for event in events:
            time_str = event.start_time.strftime("%I:%M %p")
            lines.append(f"  • {time_str}: {event.title}")
        
        return "\n".join(lines)


async def check_conflicts(start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
    """
    Check for scheduling conflicts with existing events.
    
    Args:
        start_time: Proposed start time
        end_time: Proposed end time
    
    Returns:
        List of conflicting events
    """
    async with get_async_session() as db:
        # Find events that overlap with the proposed time range
        # Overlap condition: existing.start < proposed.end AND existing.end > proposed.start
        stmt = select(models.CalendarEvent).where(
            and_(
                models.CalendarEvent.status == 'active',
                models.CalendarEvent.start_time < end_time,
                models.CalendarEvent.end_time > start_time
            )
        )
        
        result = await db.execute(stmt)
        events = result.scalars().all()
        
        return [
            {
                "id": e.id,
                "title": e.title,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat()
            }
            for e in events
        ]


async def get_calendar_summary() -> str:
    """Get a summary of calendar events for the daily briefing."""
    async with get_async_session() as db:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        week_end = today_start + timedelta(days=7)
        
        # Count today's events
        today_stmt = select(func.count(models.CalendarEvent.id)).where(
            and_(
                models.CalendarEvent.status == 'active',
                models.CalendarEvent.start_time >= today_start,
                models.CalendarEvent.start_time < today_end
            )
        )
        today_result = await db.execute(today_stmt)
        today_count = today_result.scalar() or 0
        
        # Count this week's events
        week_stmt = select(func.count(models.CalendarEvent.id)).where(
            and_(
                models.CalendarEvent.status == 'active',
                models.CalendarEvent.start_time >= today_start,
                models.CalendarEvent.start_time < week_end
            )
        )
        week_result = await db.execute(week_stmt)
        week_count = week_result.scalar() or 0
        
        if today_count == 0 and week_count == 0:
            return "Your calendar is clear this week."
        
        parts = []
        if today_count > 0:
            parts.append(f"{today_count} event{'s' if today_count != 1 else ''} today")
        if week_count > today_count:
            remaining = week_count - today_count
            parts.append(f"{remaining} more this week")
        
        return "Calendar: " + ", ".join(parts) + "."
