import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = str(BASE_DIR / os.getenv("DB_PATH", "films.db").strip())

raw_admin_ids = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = {
    int(item.strip())
    for item in raw_admin_ids.split(",")
    if item.strip().isdigit()
}

BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip()

if not BOT_TOKEN:
    raise ValueError("Не заполнен BOT_TOKEN в файле .env")