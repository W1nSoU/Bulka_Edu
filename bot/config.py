"""Runtime configuration for the Bulka bot."""

import os
import sys
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# ==================== Core settings ====================
API_TOKEN = os.getenv("BOT_API_TOKEN", "")
DAYS_TOTAL = int(os.getenv("DAYS_TOTAL", "5"))
TIMEZONE = "Europe/Kyiv"
MAIN_DEVELOPER_ID = int(os.getenv("MAIN_DEVELOPER_ID", "0"))

# ==================== AI settings ====================
# Groq AI API (optional, for smart search)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ==================== Token settings ====================
TOKEN_EXPIRY_HOURS = int(os.getenv("TOKEN_EXPIRY_HOURS", "24"))
TOKEN_CLEANUP_INTERVAL_HOURS = int(os.getenv("TOKEN_CLEANUP_INTERVAL_HOURS", "6"))

# ==================== Reminder settings ====================
INACTIVE_DAYS_THRESHOLD = int(os.getenv("INACTIVE_DAYS_THRESHOLD", "3"))
AUTO_REMINDER_INTERVAL_HOURS = int(os.getenv("AUTO_REMINDER_INTERVAL_HOURS", "24"))

# ==================== Logging settings ====================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() == "true"
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/bot.log")
DEV_CHAT_ID = os.getenv("DEV_CHAT_ID", "")

# ==================== Startup validation ====================
def validate_config():
    """Перевіряє критичні змінні конфігурації при старті."""
    errors = []
    
    if not API_TOKEN:
        errors.append("BOT_API_TOKEN is required")
    
    if DAYS_TOTAL < 1 or DAYS_TOTAL > 30:
        errors.append(f"DAYS_TOTAL must be 1-30, got {DAYS_TOTAL}")
    
    if MAIN_DEVELOPER_ID <= 0:
        errors.append("MAIN_DEVELOPER_ID must be a positive integer")
    
    if errors:
        print("❌ Configuration errors:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    
    return True


__all__ = [
    "API_TOKEN", "DAYS_TOTAL", "TIMEZONE", "MAIN_DEVELOPER_ID", "GROQ_API_KEY",
    "TOKEN_EXPIRY_HOURS", "TOKEN_CLEANUP_INTERVAL_HOURS",
    "INACTIVE_DAYS_THRESHOLD", "AUTO_REMINDER_INTERVAL_HOURS",
    "DEBUG", "LOG_TO_FILE", "LOG_FILE_PATH", "DEV_CHAT_ID",
    "validate_config",
]
