import asyncio
import logging
from imap_tools import MailBox
import aiosmtplib
from src.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_email():
    settings = get_settings()
    email = settings.EMAIL_ADDRESS
    password = settings.EMAIL_APP_PASSWORD
    imap_server = settings.EMAIL_IMAP_SERVER
    smtp_server = settings.EMAIL_SMTP_SERVER
    smtp_port = settings.EMAIL_SMTP_PORT

    print(f"\n--- Testing Email Configuration for {email} ---")

    # 1. Test IMAP (Reading)
    print(f"Testing IMAP login ({imap_server})...")
    try:
        with MailBox(imap_server).login(email, password) as mailbox:
            count = mailbox.folder.status('INBOX')['MESSAGES']
            print(f"SUCCESS: IMAP Success! Found {count} messages in INBOX.")
    except Exception as e:
        print(f"FAILED: IMAP Failed: {e}")

    # 2. Test SMTP (Sending)
    print(f"Testing SMTP login ({smtp_server}:{smtp_port})...")
    try:
        smtp = aiosmtplib.SMTP(
            hostname=smtp_server,
            port=smtp_port,
            start_tls=True
        )
        await smtp.connect()
        await smtp.login(email, password)
        await smtp.quit()
        print("SUCCESS: SMTP Success! Login authenticated.")
    except Exception as e:
        print(f"FAILED: SMTP Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_email())
