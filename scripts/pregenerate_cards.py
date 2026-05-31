"""
Предгенерация карточек заданий.

Запуск:
    python scripts/pregenerate_cards.py            # карточки с условием
    python scripts/pregenerate_cards.py --solutions
    python scripts/pregenerate_cards.py --workers 8
    python scripts/pregenerate_cards.py --retry
    python scripts/pregenerate_cards.py --force

Карточки-условия  → cards/{question_id}.png
Карточки-решения  → cards_solution/{question_id}.png
"""

import argparse
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from card_builder import build_question_card, build_solution_card, DB_PATH

# ─────────────────────────────────────────────
ROOT_DIR      = Path(__file__).resolve().parent.parent
CARDS_DIR     = ROOT_DIR / "cards"
CARDS_SOL_DIR = ROOT_DIR / "cards_solution"
FAILED_LOG    = ROOT_DIR / "cards_failed.txt"
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


def ensure_schema(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "tg_file_id" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN tg_file_id TEXT")
        conn.commit()
        print("  Колонка tg_file_id добавлена в таблицу questions.")
    conn.close()


def get_question_ids(db_path: Path, retry_only: bool = False) -> list[int]:
    conn = sqlite3.connect(db_path)
    if retry_only:
        if FAILED_LOG.exists():
            ids = [int(l.strip()) for l in FAILED_LOG.read_text().splitlines()
                   if l.strip().isdigit()]
        else:
            ids = []
    else:
        rows = conn.execute("SELECT id FROM questions ORDER BY id").fetchall()
        ids = [r[0] for r in rows]
    conn.close()
    return ids


def process_one(qid: int, out_dir: Path,
                mode: str, force: bool = False) -> tuple[int, str]:
    """
    mode: 'question' | 'solution'
    Возвращает (qid, 'ok' | 'skip' | 'error: ...')
    """
    out_path = out_dir / f"{qid}.png"
    if out_path.exists() and not force:
        return qid, "skip"
    try:
        if mode == "solution":
            card = build_solution_card(qid)
        else:
            card = build_question_card(qid)
        if card is None:
            return qid, "error: question not found"
        card.save(str(out_path), format="PNG", optimize=True)
        return qid, "ok"
    except Exception as e:
        return qid, f"error: {e}"


def run(question_ids: list[int], out_dir: Path,
        mode: str, workers: int, force: bool) -> None:
    out_dir.mkdir(exist_ok=True)

    total   = len(question_ids)
    already = sum(1 for qid in question_ids
                  if (out_dir / f"{qid}.png").exists()) if not force else 0
    todo    = total - already if not force else total

    label = "решений" if mode == "solution" else "условий"
    print(f"\nКарточки {label}:")
    print(f"  Заданий всего:     {total}")
    print(f"  Уже готово:        {already}")
    print(f"  Будет обработано:  {todo}")
    print(f"  Потоков:           {workers}")
    print(f"  Папка:             {out_dir}\n")

    if todo == 0:
        print("  Все карточки уже сгенерированы.")
        return

    t_start = time.time()
    results = {"ok": 0, "skip": 0, "error": 0}
    failed: list[int] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(process_one, qid, out_dir, mode, force): qid
            for qid in question_ids
        }
        with tqdm(total=total, unit="card", desc=f"Генерация ({label})") as bar:
            for future in as_completed(futures):
                qid, status = future.result()
                if status == "ok":
                    results["ok"] += 1
                elif status == "skip":
                    results["skip"] += 1
                else:
                    results["error"] += 1
                    failed.append(qid)
                    log.warning("  Задание %d: %s", qid, status)
                bar.update(1)
                bar.set_postfix(ok=results["ok"],
                                skip=results["skip"],
                                err=results["error"])

    elapsed = time.time() - t_start

    if failed:
        FAILED_LOG.write_text("\n".join(str(i) for i in failed))

    print(f"\n{'─'*40}")
    print(f"Готово за {elapsed:.0f} сек.")
    print(f"  Создано новых:  {results['ok']}")
    print(f"  Пропущено:      {results['skip']}")
    print(f"  Ошибок:         {results['error']}")
    if failed:
        print(f"\n  Упавшие → {FAILED_LOG}")
        print("  Повторить: python scripts/pregenerate_cards.py --retry --solutions")
    print(f"\nФайлов в папке: {len(list(out_dir.glob('*.png')))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Предгенерация карточек заданий")
    parser.add_argument("--solutions", action="store_true",
                        help="Генерировать карточки с решением (cards_solution/)")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retry",   action="store_true",
                        help="Повторить только упавшие задания")
    parser.add_argument("--force",   action="store_true",
                        help="Перегенерировать всё")
    args = parser.parse_args()

    ensure_schema()

    question_ids = get_question_ids(DB_PATH, retry_only=args.retry)
    if not question_ids:
        print("Нет заданий для обработки.")
        return

    if args.solutions:
        run(question_ids, CARDS_SOL_DIR, "solution", args.workers, args.force)
    else:
        run(question_ids, CARDS_DIR, "question", args.workers, args.force)


if __name__ == "__main__":
    main()
