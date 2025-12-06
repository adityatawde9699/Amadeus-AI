import pytest
from datetime import datetime
from general_utils import (
    get_greeting,
    get_datetime_info,
    calculate,
    convert_temperature,
    convert_length,
    parse_duration,
    set_timer_async
)

@pytest.mark.asyncio
async def test_get_greeting():
    """Test that get_greeting returns a valid string."""
    greeting = get_greeting()
    assert isinstance(greeting, str)
    assert len(greeting) > 0

@pytest.mark.asyncio
async def test_get_datetime_info():
    """Test various datetime query formats."""
    # We won't mock datetime, just check for expected substrings/formats
    time_info = get_datetime_info("time")
    assert "time is" in time_info
    
    date_info = get_datetime_info("date")
    assert "date is" in date_info
    
    full_info = get_datetime_info("full")
    assert "on" in full_info  # Usually "It is X on Y"

def test_calculate():
    """Test the safely evaluated calculator."""
    assert "4" in calculate("2+2")
    assert "10" in calculate("5 * 2")
    assert "Division by zero" in calculate("5/0")
    assert "Invalid characters" in calculate("import os")

def test_convert_temperature():
    """Test temperature conversions."""
    # C to F: 0 -> 32
    assert "32.00" in convert_temperature(0, "c", "f")
    # F to C: 32 -> 0
    assert "0.00" in convert_temperature(32, "f", "c")
    # C to K: 0 -> 273.15
    assert "273.15" in convert_temperature(0, "c", "k")

def test_convert_length():
    """Test length conversions."""
    # m to km: 1000m -> 1km
    assert "1.0000 km" in convert_length(1000, "m", "km")
    # in to cm: 1in -> 2.54cm
    # 1 inch = 0.0254 m
    # cm = 0.01 m
    # result = 0.0254 / 0.01 = 2.54
    assert "2.5400 cm" in convert_length(1, "in", "cm")

def test_parse_duration():
    """Test parsing natural language duration strings."""
    assert parse_duration("1 minute") == 60
    assert parse_duration("1 min") == 60
    assert parse_duration("2 hours") == 7200
    assert parse_duration("30 seconds") == 30
    assert parse_duration("1h 30m") == 5400 # 3600 + 1800

@pytest.mark.asyncio
async def test_set_timer_async():
    """Test timer logic (without actually waiting)."""
    # Test invalid inputs
    assert "must be positive" in await set_timer_async(-1)
    assert "cannot exceed 24 hours" in await set_timer_async(90000)
    
    # Test valid input output string
    result = await set_timer_async(60)
    assert "Timer set for" in result
    assert "1m 0s" in result
