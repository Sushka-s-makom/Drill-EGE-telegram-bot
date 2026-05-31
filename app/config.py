import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ADMIN_IDS: list[int] = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
MAIN_ADMIN_ID: int | None = ADMIN_IDS[0] if ADMIN_IDS else None

DB_PHYSICS  = BASE_DIR / "database" / "physics.db"
DB_BOT      = BASE_DIR / "database" / "bot.db"
CARDS_DIR   = BASE_DIR / "cards"
CARDS_SOL   = BASE_DIR / "cards_solution"
