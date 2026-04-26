"""
Slack tool integration for Amadeus AI Assistant.

Uses the Slack SDK for Python to interact with channels and messages.
Requires a Slack User/Bot token (SLACK_TOKEN).
"""

import logging
import os
from typing import Any

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

# Try to import slack_sdk, but handle gracefully if not installed
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    HAS_SLACK_SDK = True
except ImportError:
    HAS_SLACK_SDK = False
    logger.warning("slack-sdk not installed. Slack tools will be unavailable.")


def _get_slack_client() -> tuple["WebClient | None", str | None]:
    """Build Slack client from environment token."""
    if not HAS_SLACK_SDK:
        return None, "Error: slack-sdk is not installed. Please run 'pip install slack-sdk'."

    from src.core.config import get_settings

    token = getattr(get_settings(), "SLACK_TOKEN", os.environ.get("SLACK_TOKEN"))
    if not token:
        return None, "Error: SLACK_TOKEN environment variable not set."

    return WebClient(token=token), None


@tool(
    name="send_slack_message",
    description="Send a message to a Slack channel. Trigger: 'send slack message', 'slack ___'",
    category=ToolCategory.COMMUNICATION,
    parameters={
        "channel": {"type": "string", "description": "Channel name or ID (e.g. #general)"},
        "message": {"type": "string", "description": "Message text content"},
    },
)
def send_slack_message(channel: str, message: str, **kwargs: Any) -> str:
    """Send a message to Slack."""
    client, err = _get_slack_client()
    if err:
        return err

    try:
        response = client.chat_postMessage(channel=channel, text=message)  # type: ignore[union-attr]
        if response["ok"]:
            return f"Successfully sent Slack message to {channel}."
        return str(f"Error: Failed to send Slack message: {response['error']}")
    except SlackApiError as e:
        logger.exception("Slack API error: %s", e.response["error"])
        return str(f"Error: Slack API error: {e.response['error']}")
    except Exception as e:
        logger.exception("Failed to send Slack message: %s", e)
        return f"Error: Failed to send Slack message: {e}"


def send_slack_preview(args: dict) -> str:
    channel = args.get("channel", "unknown channel")
    msg = args.get("message", "empty message")
    return f"Post message to Slack channel '{channel}': '{msg[:50]}...'"


send_slack_message._tool_metadata.get_preview = send_slack_preview  # type: ignore[attr-defined]


@tool(
    name="list_slack_channels",
    description="List all public Slack channels in the workspace. Trigger: 'list slack channels'",
    category=ToolCategory.COMMUNICATION,
)
def list_slack_channels(**kwargs: Any) -> str:
    """List Slack channels."""
    client, err = _get_slack_client()
    if err:
        return err

    try:
        response = client.conversations_list(types="public_channel")  # type: ignore[union-attr]
        if response["ok"]:
            channels = [f"#{c['name']} ({c['id']})" for c in response["channels"]]
            return f"Found {len(channels)} Slack channels:\n" + "\n".join(channels)
        return str(f"Error: Failed to list Slack channels: {response['error']}")
    except SlackApiError as e:
        return str(f"Error: Slack API error: {e.response['error']}")
    except Exception as e:
        return f"Error: Failed to list Slack channels: {e}"


def list_slack_channels_preview(args: dict) -> str:
    return "List all public Slack channels in the workspace."


list_slack_channels._tool_metadata.get_preview = list_slack_channels_preview  # type: ignore[attr-defined]


@tool(
    name="read_slack_messages",
    description="Read the most recent messages from a Slack channel. Trigger: 'read slack', 'slack messages'",
    category=ToolCategory.COMMUNICATION,
    parameters={
        "channel": {"type": "string", "description": "Channel ID (e.g. C12345678)"},
        "count": {
            "type": "integer",
            "description": "Number of recent messages to read (default: 10)",
        },
    },
)
def read_slack_messages(channel: str, count: int = 10, **kwargs: Any) -> str:
    """Read recent messages from a Slack channel."""
    client, err = _get_slack_client()
    if err:
        return err

    try:
        response = client.conversations_history(channel=channel, limit=count)  # type: ignore[union-attr]
        if response["ok"]:
            messages = response.get("messages", [])
            if not messages:
                return f"No messages found in channel '{channel}'."

            formatted = []
            for msg in reversed(messages):  # Oldest to newest
                user = msg.get("user", "Unknown User")
                text = msg.get("text", "")
                ts = msg.get("ts", "Unknown Time")
                # Format timestamp
                try:
                    import datetime

                    time_str = datetime.datetime.fromtimestamp(float(ts)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except Exception:
                    time_str = str(ts)

                formatted.append(f"[{time_str}] User {user}: {text}")

            return f"Recent messages in {channel}:\\n\\n" + "\\n".join(formatted)
        return str(f"Error: Failed to read Slack messages: {response['error']}")
    except SlackApiError as e:
        return str(f"Error: Slack API error: {e.response['error']}")
    except Exception as e:
        return f"Error: Failed to read Slack messages: {e}"


def read_slack_preview(args: dict) -> str:
    channel = args.get("channel", "unknown channel")
    count = args.get("count", 10)
    return f"Read {count} most recent messages from Slack channel '{channel}'."


read_slack_messages._tool_metadata.get_preview = read_slack_preview  # type: ignore[attr-defined]


def get_slack_tools() -> list[Tool]:
    """Get all slack tools for registration."""
    return [
        send_slack_message._tool_metadata,  # type: ignore[attr-defined]
        list_slack_channels._tool_metadata,  # type: ignore[attr-defined]
        read_slack_messages._tool_metadata,  # type: ignore[attr-defined]
    ]
