import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ADMIN_IDS: list[int] = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
MAIN_ADMIN_ID: int | None = ADMIN_IDS[0] if ADMIN_IDS else None

BASE_DIR    = Path(__file__).parent
DB_PHYSICS  = BASE_DIR / "database" / "physics.db"
DB_BOT      = BASE_DIR / "database" / "bot.db"
CARDS_DIR   = BASE_DIR / "cards"
CARDS_SOL   = BASE_DIR / "cards_solution"
