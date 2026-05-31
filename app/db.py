"""Слой работы с базами данных."""

import re
import secrets
import sqlite3
from typing import Optional

from .config import DB_BOT, DB_PHYSICS


# ── Инициализация bot.db ──────────────────────────────────────────────────────

def init_bot_db() -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id      INTEGER PRIMARY KEY,
                role       TEXT    NOT NULL DEFAULT 'student',
                teacher_id INTEGER,
                full_name  TEXT,
                username   TEXT,
                joined_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS invites (
                token      TEXT    PRIMARY KEY,
                teacher_id INTEGER NOT NULL,
                role       TEXT    NOT NULL DEFAULT 'student',
                used_by    INTEGER,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS progress (
                user_id     INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                correct     INTEGER NOT NULL DEFAULT 0,
                attempts    INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT    DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, question_id)
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                answer_given TEXT,
                correct      INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mistakes (
                user_id     INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                added_at    TEXT    DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, question_id)
            );
        """)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Добавляет колонки в существующие таблицы при обновлении схемы."""
    user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "username" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")

    inv_cols = {r[1] for r in conn.execute("PRAGMA table_info(invites)")}
    if "role" not in inv_cols:
        conn.execute(
            "ALTER TABLE invites ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"
        )


# ── Пользователи ──────────────────────────────────────────────────────────────

def get_user(tg_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_BOT) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
        return dict(row) if row else None


def upsert_user(tg_id: int, full_name: str, username: Optional[str]) -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            "UPDATE users SET full_name = ?, username = ? WHERE tg_id = ?",
            (full_name, username, tg_id),
        )


def register_teacher(tg_id: int, full_name: str,
                     username: Optional[str] = None) -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO users (tg_id, role, full_name, username)
               VALUES (?, 'teacher', ?, ?)""",
            (tg_id, full_name, username),
        )


def register_admin(tg_id: int, full_name: str,
                   username: Optional[str] = None,
                   creator_id: Optional[int] = None) -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO users (tg_id, role, teacher_id, full_name, username)
               VALUES (?, 'admin', ?, ?, ?)""",
            (tg_id, creator_id, full_name, username),
        )


def register_student(tg_id: int, full_name: str,
                     username: Optional[str], teacher_id: int) -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO users (tg_id, role, teacher_id, full_name, username)
               VALUES (?, 'student', ?, ?, ?)""",
            (tg_id, teacher_id, full_name, username),
        )


def is_teacher(tg_id: int) -> bool:
    user = get_user(tg_id)
    return user is not None and user["role"] in ("teacher", "admin")


def remove_teacher(tg_id: int) -> bool:
    """Снимает роль учителя (переводит в student). Возвращает True если нашёл."""
    with sqlite3.connect(DB_BOT) as conn:
        cur = conn.execute(
            "UPDATE users SET role = 'student', teacher_id = NULL WHERE tg_id = ? AND role IN ('teacher','admin')",
            (tg_id,),
        )
        return cur.rowcount > 0


def get_teacher_students(teacher_id: int) -> list[dict]:
    with sqlite3.connect(DB_BOT) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM users WHERE teacher_id = ? AND role = 'student' ORDER BY joined_at",
            (teacher_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_teachers() -> list[dict]:
    with sqlite3.connect(DB_BOT) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM users WHERE role IN ('teacher','admin') ORDER BY joined_at"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Инвайты ───────────────────────────────────────────────────────────────────

def create_invite(teacher_id: int, role: str = "student") -> str:
    token = secrets.token_urlsafe(12)
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            "INSERT INTO invites (token, teacher_id, role) VALUES (?, ?, ?)",
            (token, teacher_id, role),
        )
    return token


def get_invite(token: str) -> Optional[dict]:
    with sqlite3.connect(DB_BOT) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM invites WHERE token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None


def use_invite(token: str, student_id: int) -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            "UPDATE invites SET used_by = ? WHERE token = ?",
            (student_id, token),
        )


# ── Задания (physics.db) ──────────────────────────────────────────────────────

def get_question(question_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PHYSICS) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        return dict(row) if row else None


def get_next_question(user_id: int, filter_type: str, filter_value) -> Optional[dict]:
    """Следующее нерешённое задание по номеру или теме."""
    correctly_solved = _get_correctly_solved(user_id)
    exclude = ",".join(str(i) for i in correctly_solved) if correctly_solved else "0"

    with sqlite3.connect(DB_PHYSICS) as conn:
        conn.row_factory = sqlite3.Row
        if filter_type == "number":
            row = conn.execute(
                f"""SELECT * FROM questions
                    WHERE exam_number = ? AND id NOT IN ({exclude})
                    ORDER BY RANDOM() LIMIT 1""",
                (filter_value,),
            ).fetchone()
        else:
            row = conn.execute(
                f"""SELECT * FROM questions
                    WHERE exam_topic = ? AND id NOT IN ({exclude})
                    ORDER BY RANDOM() LIMIT 1""",
                (filter_value,),
            ).fetchone()
        return dict(row) if row else None


def _get_correctly_solved(user_id: int) -> list[int]:
    with sqlite3.connect(DB_BOT) as conn:
        rows = conn.execute(
            "SELECT question_id FROM progress WHERE user_id = ? AND correct = 1",
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows]


def get_all_numbers() -> list[int]:
    with sqlite3.connect(DB_PHYSICS) as conn:
        rows = conn.execute(
            "SELECT DISTINCT exam_number FROM questions WHERE exam_number IS NOT NULL ORDER BY exam_number"
        ).fetchall()
        return [r[0] for r in rows]


def get_all_topics() -> list[str]:
    with sqlite3.connect(DB_PHYSICS) as conn:
        rows = conn.execute(
            "SELECT DISTINCT exam_topic FROM questions WHERE exam_topic IS NOT NULL ORDER BY exam_topic"
        ).fetchall()
        return [r[0] for r in rows]


def get_solution_text(question_id: int) -> Optional[str]:
    with sqlite3.connect(DB_PHYSICS) as conn:
        row = conn.execute(
            "SELECT text FROM solutions WHERE question_id = ?", (question_id,)
        ).fetchone()
        return row[0] if row else None


def get_video_info(question_id: int) -> Optional[str]:
    with sqlite3.connect(DB_PHYSICS) as conn:
        row = conn.execute(
            "SELECT video_url FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
    if row and row[0]:
        return row[0].strip()
    return None


def has_video(question_id: int) -> bool:
    return get_video_info(question_id) is not None


def save_tg_file_id(question_id: int, file_id: str) -> None:
    with sqlite3.connect(DB_PHYSICS) as conn:
        conn.execute(
            "UPDATE questions SET tg_file_id = ? WHERE id = ?",
            (file_id, question_id),
        )


# ── Нормализация ответа ───────────────────────────────────────────────────────

def normalize_answer(raw: str) -> str:
    return raw.strip().replace(",", ".").lower()


def check_answer(user_answer: str, correct_answer: str) -> bool:
    return normalize_answer(user_answer) == normalize_answer(correct_answer)


# ── Прогресс и попытки ────────────────────────────────────────────────────────

def log_attempt(user_id: int, question_id: int,
                answer_given: str, correct: bool) -> None:
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            """INSERT INTO attempts (user_id, question_id, answer_given, correct)
               VALUES (?, ?, ?, ?)""",
            (user_id, question_id, answer_given, int(correct)),
        )


def mark_correct(user_id: int, question_id: int, answer_given: str = "") -> None:
    log_attempt(user_id, question_id, answer_given, True)
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            """INSERT INTO progress (user_id, question_id, correct, attempts)
               VALUES (?, ?, 1, 1)
               ON CONFLICT(user_id, question_id) DO UPDATE SET
                   correct = 1,
                   attempts = attempts + 1,
                   updated_at = datetime('now')""",
            (user_id, question_id),
        )
        conn.execute(
            "DELETE FROM mistakes WHERE user_id = ? AND question_id = ?",
            (user_id, question_id),
        )


def mark_incorrect(user_id: int, question_id: int, answer_given: str = "") -> None:
    log_attempt(user_id, question_id, answer_given, False)
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(
            """INSERT INTO progress (user_id, question_id, correct, attempts)
               VALUES (?, ?, 0, 1)
               ON CONFLICT(user_id, question_id) DO UPDATE SET
                   attempts = attempts + 1,
                   updated_at = datetime('now')
               WHERE correct = 0""",
            (user_id, question_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO mistakes (user_id, question_id) VALUES (?, ?)",
            (user_id, question_id),
        )


def get_mistakes(user_id: int) -> list[dict]:
    with sqlite3.connect(DB_BOT) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT question_id FROM mistakes WHERE user_id = ? ORDER BY added_at",
            (user_id,),
        ).fetchall()
        ids = [r["question_id"] for r in rows]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with sqlite3.connect(DB_PHYSICS) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM questions WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [dict(r) for r in rows]


def mistakes_count(user_id: int) -> int:
    with sqlite3.connect(DB_BOT) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM mistakes WHERE user_id = ?", (user_id,)
        ).fetchone()[0]


# ── Статистика ────────────────────────────────────────────────────────────────

def get_student_stats(user_id: int) -> dict:
    with sqlite3.connect(DB_BOT) as conn:
        total_attempts = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

        correct_attempts = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE user_id = ? AND correct = 1", (user_id,)
        ).fetchone()[0]

        solved_questions = conn.execute(
            "SELECT COUNT(*) FROM progress WHERE user_id = ? AND correct = 1", (user_id,)
        ).fetchone()[0]

        mistakes = conn.execute(
            "SELECT COUNT(*) FROM mistakes WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

        last_attempts = conn.execute(
            """SELECT a.question_id, a.answer_given, a.correct, a.created_at
               FROM attempts a
               WHERE a.user_id = ?
               ORDER BY a.created_at DESC LIMIT 5""",
            (user_id,),
        ).fetchall()

    return {
        "total_attempts":   total_attempts,
        "correct_attempts": correct_attempts,
        "solved_questions": solved_questions,
        "mistakes":         mistakes,
        "last_attempts":    last_attempts,
    }


def get_student_stats_for_teacher(student_id: int) -> dict:
    return get_student_stats(student_id)


def get_detailed_stats(user_id: int) -> dict:
    """Детальная статистика: разбивка по темам и номерам заданий."""
    with sqlite3.connect(DB_BOT) as conn:
        conn.execute(f"ATTACH DATABASE '{DB_PHYSICS}' AS phys")

        by_number = conn.execute("""
            SELECT q.exam_number,
                   COUNT(*)       AS tried,
                   SUM(p.correct) AS solved
            FROM   progress p
            JOIN   phys.questions q ON q.id = p.question_id
            WHERE  p.user_id = ? AND q.exam_number IS NOT NULL
            GROUP  BY q.exam_number
            ORDER  BY q.exam_number
        """, (user_id,)).fetchall()

        by_topic = conn.execute("""
            SELECT q.exam_topic,
                   COUNT(*)       AS tried,
                   SUM(p.correct) AS solved
            FROM   progress p
            JOIN   phys.questions q ON q.id = p.question_id
            WHERE  p.user_id = ? AND q.exam_topic IS NOT NULL
            GROUP  BY q.exam_topic
            ORDER  BY q.exam_topic
        """, (user_id,)).fetchall()

    return {
        "by_number": [
            {"number": r[0], "tried": r[1], "solved": r[2] or 0}
            for r in by_number
        ],
        "by_topic": [
            {"topic": r[0], "tried": r[1], "solved": r[2] or 0}
            for r in by_topic
        ],
    }
