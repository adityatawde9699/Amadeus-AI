"""
Office application tools for Amadeus AI Assistant.

Integrates with local Microsoft Office applications (Outlook, Word, Excel)
using the pywin32 (win32com.client) API on Windows.
"""

import logging
import os
from pathlib import Path
from typing import Any

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

# Declared as Any so the type checker permits win32com.client.* attribute access
# regardless of platform. Replaced with real modules on Windows; remain None elsewhere.
pythoncom: Any = None
win32com: Any = None

# Try to import win32com, but handle gracefully if not on Windows or not installed
try:
    import pythoncom as _pythoncom  # type: ignore[import-not-found]
    import win32com as _win32com  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]  # ensure submodule is loaded

    pythoncom = _pythoncom
    win32com = _win32com
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False
    logger.warning("pywin32 not installed. Office tools will be unavailable.")



from contextlib import contextmanager


@contextmanager
def _com_thread():
    """Ensure COM is initialised on the current thread.

    When office tools run inside ``run_in_executor`` (asyncio thread pool),
    the worker thread has no COM apartment. This context manager initialises
    COM on entry and uninitialises on exit so that ``win32com.client.Dispatch``
    works from any thread.
    """
    if pythoncom is not None:
        pythoncom.CoInitialize()
    try:
        yield
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def _check_windows_office() -> tuple[bool, str | None]:
    """Verify system is Windows and pywin32 is available."""
    if not HAS_PYWIN32:
        return False, "Error: pywin32 is not installed. Please run 'pip install pywin32'."
    if os.name != "nt":
        return False, "Error: Local Office integration is only supported on Windows."
    return True, None


@tool(
    name="create_excel_spreadsheet",
    description=(
        "Creates a new Excel spreadsheet (.xlsx) with specified column headers and row data using "
        "the local Microsoft Excel application (Windows only, requires pywin32). "
        "Saves to the agent workspace directory. "
        "Trigger: 'create excel', 'make spreadsheet', 'new excel file with data'"
    ),
    category=ToolCategory.PRODUCTIVITY,
    parameters={
        "file_name": {"type": "string", "description": "Name of the Excel file to create"},
        "columns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of column headers",
        },
        "data": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
            "description": "2D array of row data",
        },
    },
)
def create_excel_spreadsheet(
    file_name: str, columns: list[str], data: list[list[Any]], **kwargs: Any
) -> str:
    """Create a new Excel spreadsheet using local Excel app."""
    ok, err = _check_windows_office()
    if not ok:
        return err or "Office integration error"

    try:
        with _com_thread():
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = False
            wb = excel.Workbooks.Add()
            ws = wb.ActiveSheet

            # Add headers
            for i, col in enumerate(columns):
                ws.Cells(1, i + 1).Value = col

            # Add data
            for r_idx, row in enumerate(data):
                for c_idx, value in enumerate(row):
                    ws.Cells(r_idx + 2, c_idx + 1).Value = value

            # Save file in agent workspace
            from src.core.config import get_settings

            settings = get_settings()
            workspace = settings.AGENT_WORKSPACE
            workspace.mkdir(parents=True, exist_ok=True)

            save_path = workspace / file_name
            if not save_path.suffix:
                save_path = save_path.with_suffix(".xlsx")

            wb.SaveAs(str(save_path))
            wb.Close()
            excel.Quit()

            return f"Successfully created Excel spreadsheet at {save_path}"
    except Exception as e:
        logger.exception("Failed to create Excel spreadsheet: %s", e)
        return f"Error: Failed to create Excel spreadsheet: {e}"


def create_excel_preview(args: dict) -> str:
    """Generate a preview for Excel creation."""
    file_name = args.get("file_name", "untitled.xlsx")
    cols = args.get("columns", [])
    rows = len(args.get("data", []))
    return f"Create Excel file '{file_name}' with {len(cols)} columns and {rows} rows of data."


# Assign the preview function to the tool metadata
create_excel_spreadsheet._tool_metadata.get_preview = create_excel_preview  # type: ignore[attr-defined]


@tool(
    name="create_word_document",
    description=(
        "Creates a new Word document (.docx) with a title and content using "
        "the local Microsoft Word application (Windows only, requires pywin32). "
        "Saves to the agent workspace directory. "
        "Trigger: 'create word doc', 'make a document', 'write a report', 'new word file'"
    ),
    category=ToolCategory.PRODUCTIVITY,
    parameters={
        "file_name": {"type": "string", "description": "Name of the document"},
        "title": {"type": "string", "description": "Title of the document"},
        "content": {"type": "string", "description": "Full text content of the document"},
    },
)
def create_word_document(file_name: str, title: str, content: str, **kwargs: Any) -> str:
    """Create a new Word document using local Word app."""
    ok, err = _check_windows_office()
    if not ok:
        return err or "Office integration error"

    try:
        with _com_thread():
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Add()

            # Add Title
            title_range = doc.Range(0, 0)
            title_range.Text = title + "\n\n"
            title_range.Font.Bold = True
            title_range.Font.Size = 16

            # Add Content
            content_range = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
            content_range.Text = content
            content_range.Font.Bold = False
            content_range.Font.Size = 11

            from src.core.config import get_settings

            settings = get_settings()
            workspace = settings.AGENT_WORKSPACE
            workspace.mkdir(parents=True, exist_ok=True)

            save_path = workspace / file_name
            if not save_path.suffix:
                save_path = save_path.with_suffix(".docx")

            doc.SaveAs(str(save_path))
            doc.Close()
            word.Quit()

            return f"Successfully created Word document at {save_path}"
    except Exception as e:
        logger.exception("Failed to create Word document: %s", e)
        return f"Error: Failed to create Word document: {e}"


def create_word_preview(args: dict) -> str:
    file_name = args.get("file_name", "untitled.docx")
    title = args.get("title", "")
    return f"Create Word document '{file_name}' titled '{title}'."


create_word_document._tool_metadata.get_preview = create_word_preview  # type: ignore[attr-defined]


@tool(
    name="send_outlook_email",
    description=(
        "Sends an email using the locally installed Microsoft Outlook desktop application "
        "(Windows only, requires pywin32). Use this when the user specifically wants to send via Outlook. "
        "Trigger: 'send outlook email', 'email via outlook', 'use outlook to send mail'"
    ),
    category=ToolCategory.COMMUNICATION,
    parameters={
        "to": {"type": "string", "description": "Recipient email address"},
        "subject": {"type": "string", "description": "Email subject"},
        "body": {"type": "string", "description": "Email message body"},
    },
)
def send_outlook_email(to: str, subject: str, body: str, **kwargs: Any) -> str:
    """Send an email using the local Outlook app."""
    ok, err = _check_windows_office()
    if not ok:
        return err or "Office integration error"

    try:
        with _com_thread():
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)  # 0 = olMailItem
            mail.To = to
            mail.Subject = subject
            mail.Body = body
            mail.Send()
            return f"Successfully sent email to {to} via Outlook."
    except Exception as e:
        logger.exception("Failed to send Outlook email: %s", e)
        return f"Error: Failed to send Outlook email: {e}"


def send_email_preview(args: dict) -> str:
    to = args.get("to", "unknown recipient")
    subject = args.get("subject", "No subject")
    return f"Send email to '{to}' with subject '{subject}'."


send_outlook_email._tool_metadata.get_preview = send_email_preview  # type: ignore[attr-defined]


@tool(
    name="read_outlook_emails",
    description=(
        "Reads the most recent emails from the local Outlook desktop inbox (Windows only, requires pywin32). "
        "Returns sender, subject, date, and a 200-character body preview for each email. "
        "Trigger: 'read outlook emails', 'latest emails from outlook', 'check outlook inbox'"
    ),
    category=ToolCategory.COMMUNICATION,
    parameters={
        "count": {"type": "integer", "description": "Number of recent emails to read (default 5)"},
    },
)
def read_outlook_emails(count: int = 5, **kwargs: Any) -> str:
    """Read recent emails using the local Outlook app."""
    ok, err = _check_windows_office()
    if not ok:
        return err or "Office integration error"

    try:
        with _com_thread():
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)  # 6 = olFolderInbox

            # Get items, sort by received time descending
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)

            emails = []
            for i, item in enumerate(items):
                if i >= count:
                    break

                # Use getattr to safely access properties since items can be different types (e.g. meeting requests)
                sender = getattr(item, "SenderName", "Unknown Sender")
                subject = getattr(item, "Subject", "No Subject")
                received = getattr(item, "ReceivedTime", "Unknown Time")
                body = getattr(item, "Body", "")[:200]  # First 200 chars

                emails.append(
                    f"From: {sender}\nDate: {received}\nSubject: {subject}\nSnippet: {body}...\n"
                )

            if not emails:
                return "No recent emails found."

            return f"Found {len(emails)} recent emails:\n\n" + "\n---\n".join(emails)
    except Exception as e:
        logger.exception("Failed to read Outlook emails: %s", e)
        return f"Error: Failed to read Outlook emails: {e}"


def read_outlook_emails_preview(args: dict) -> str:
    count = args.get("count", 5)
    return f"Read the {count} most recent emails from your Outlook inbox."


read_outlook_emails._tool_metadata.get_preview = read_outlook_emails_preview  # type: ignore[attr-defined]


@tool(
    name="read_excel_spreadsheet",
    description=(
        "Reads data from an existing Excel spreadsheet (.xlsx) using the local Excel application "
        "(Windows only, requires pywin32). Returns up to 20 rows of data formatted as text. "
        "Supports specifying a sheet name and row limit. "
        "Trigger: 'read excel file', 'get data from spreadsheet', 'open and read this excel'"
    ),
    category=ToolCategory.PRODUCTIVITY,
    parameters={
        "file_path": {
            "type": "string",
            "description": "Absolute or relative path to the Excel file",
        },
        "sheet_name": {"type": "string", "description": "Optional sheet name to read"},
        "max_rows": {
            "type": "integer",
            "description": "Maximum number of rows to read (default 20)",
        },
    },
)
def read_excel_spreadsheet(
    file_path: str, sheet_name: str | None = None, max_rows: int = 20, **kwargs: Any
) -> str:
    """Read data from an Excel file."""
    ok, err = _check_windows_office()
    if not ok:
        return err or "Office integration error"

    try:
        from src.core.config import get_settings

        settings = get_settings()

        # Handle relative paths by anchoring to workspace
        path_obj = Path(file_path)
        if not path_obj.is_absolute():
            workspace = settings.AGENT_WORKSPACE
            path_obj = workspace / file_path

        # Add .xlsx if no extension
        if not path_obj.suffix:
            path_obj = path_obj.with_suffix(".xlsx")

        if not path_obj.exists():
            return f"Error: File not found at {path_obj}"

        with _com_thread():
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = False
            wb = excel.Workbooks.Open(str(path_obj.resolve()))

            try:
                ws = wb.Worksheets(sheet_name) if sheet_name else wb.ActiveSheet

                used_range = ws.UsedRange
                # Get values (returns tuple of tuples)
                values = used_range.Value

                if not values:
                    return f"No data found in sheet '{ws.Name}'."

                # Convert to string and limit rows
                rows = []
                for i, row in enumerate(values):
                    if i >= max_rows:
                        rows.append(f"... (truncated after {max_rows} rows)")
                        break
                    # Handle None values and filter out completely empty rows
                    str_row = [str(cell) if cell is not None else "" for cell in row]
                    if any(str_row):  # Only add if row has some data
                        rows.append(" | ".join(str_row))

                return f"Data from {path_obj.name} (Sheet: {ws.Name}):\n\n" + "\n".join(rows)
            finally:
                wb.Close(SaveChanges=False)
                excel.Quit()

    except Exception as e:
        logger.exception("Failed to read Excel spreadsheet: %s", e)
        return f"Error: Failed to read Excel spreadsheet: {e}"


def read_excel_preview(args: dict) -> str:
    file_path = args.get("file_path", "unknown")
    sheet = args.get("sheet_name", "active sheet")
    rows = args.get("max_rows", 20)
    return f"Read up to {rows} rows from '{sheet}' in Excel file '{file_path}'."


read_excel_spreadsheet._tool_metadata.get_preview = read_excel_preview  # type: ignore[attr-defined]


def get_office_tools() -> list[Tool]:
    """Get all office tools for registration.

    Returns an empty list when pywin32 is unavailable (non-Windows hosts) so
    these tools never appear in the LLM tool menu where they cannot work.
    """
    if not HAS_PYWIN32:
        return []
    return [
        create_excel_spreadsheet._tool_metadata,  # type: ignore[attr-defined]
        create_word_document._tool_metadata,  # type: ignore[attr-defined]
        send_outlook_email._tool_metadata,  # type: ignore[attr-defined]
        read_outlook_emails._tool_metadata,  # type: ignore[attr-defined]
        read_excel_spreadsheet._tool_metadata,  # type: ignore[attr-defined]
    ]
