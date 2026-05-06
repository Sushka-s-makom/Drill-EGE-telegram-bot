"""
Одноразовая миграция: копирует video_link из tasks1.db в physics.db.
Запуск: python migrate_video_links.py
"""

import sqlite3
from pathlib import Path

BASE = Path(__file__).parent / "database"


def main() -> None:
    conn_tasks = sqlite3.connect(BASE / "tasks1.db")
    conn_phys  = sqlite3.connect(BASE / "physics.db")

    links = conn_tasks.execute(
        "SELECT id, video_link FROM tasks WHERE video_link IS NOT NULL AND TRIM(video_link) != ''"
    ).fetchall()

    updated = skipped = 0
    for qid, url in links:
        url = url.strip()
        cur = conn_phys.execute(
            "UPDATE questions SET video_url = ? WHERE id = ?",
            (url, qid),
        )
        if cur.rowcount:
            updated += 1
        else:
            skipped += 1

    conn_phys.commit()
    conn_tasks.close()
    conn_phys.close()

    print(f"Обновлено: {updated}  |  Не найдено в physics.db: {skipped}")


if __name__ == "__main__":
    main()
