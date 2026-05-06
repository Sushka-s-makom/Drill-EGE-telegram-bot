import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "database" / "tasks1.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    UPDATE tasks
    SET type = 'written'
    WHERE type = 'test'
      AND (
            answer IS NULL
            OR TRIM(CAST(answer AS TEXT)) = ''
          )
""")

conn.commit()

print("Изменено строк:", cursor.rowcount)

conn.close()