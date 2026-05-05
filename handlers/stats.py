"""Статистика ученика и учителя."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from config import ADMIN_IDS
from keyboards import kb_stats_menu

router = Router()

_CHUNK = 4000  # безопасный лимит Telegram (max 4096)


def _pct_icon(pct: int) -> str:
    if pct >= 70:
        return "✅"
    if pct >= 40:
        return "⚠️"
    return "❌"


def _format_stats(stats: dict, name: str = "Твоя") -> str:
    total    = stats["total_attempts"]
    correct  = stats["correct_attempts"]
    solved   = stats["solved_questions"]
    mistakes = stats["mistakes"]
    pct      = round(correct / total * 100) if total else 0

    lines = [
        f"📊 <b>{name} статистика</b>",
        "",
        f"✅ Решено верно:       <b>{solved}</b> заданий",
        f"❌ В работе над ошиб.: <b>{mistakes}</b> заданий",
        f"🔁 Всего попыток:      <b>{total}</b>",
        f"🎯 Из них верных:      <b>{correct}</b> ({pct}%)",
    ]

    last = stats["last_attempts"]
    if last:
        lines += ["", "📝 <b>Последние попытки:</b>"]
        for qid, answer, ok, ts in last:
            icon = "✅" if ok else "❌"
            date = ts[:10] if ts else ""
            lines.append(f"  {icon} Задание {qid} → <code>{answer}</code>  <i>{date}</i>")

    return "\n".join(lines)


def _format_detailed(detail: dict, name: str = "Твоя") -> list[str]:
    """Возвращает список сообщений (если длинное — разбивает на части)."""
    lines = [f"📈 <b>{name} подробная статистика</b>", ""]

    # По номерам заданий
    if detail["by_number"]:
        lines.append("📌 <b>По номерам заданий ЕГЭ:</b>")
        for row in detail["by_number"]:
            num    = row["number"]
            tried  = row["tried"]
            solved = row["solved"]
            pct    = round(solved / tried * 100) if tried else 0
            icon   = _pct_icon(pct)
            lines.append(f"  №{num} — {solved}/{tried} ({pct}%) {icon}")
        lines.append("")

    # По темам
    if detail["by_topic"]:
        lines.append("📚 <b>По темам:</b>")
        for row in detail["by_topic"]:
            topic  = row["topic"]
            tried  = row["tried"]
            solved = row["solved"]
            pct    = round(solved / tried * 100) if tried else 0
            icon   = _pct_icon(pct)
            short  = topic.split("/")[-1].strip() if "/" in topic else topic
            lines.append(f"  {icon} {short} — {solved}/{tried} ({pct}%)")

    if not detail["by_number"] and not detail["by_topic"]:
        lines.append("Пока нет решённых заданий.")

    # Разбиваем на части если нужно
    parts: list[str] = []
    current = ""
    for line in lines:
        candidate = (current + "\n" + line).strip()
        if len(candidate) > _CHUNK:
            if current:
                parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)

    return parts or ["Нет данных."]


def _stats_keyboard(user_id: int, student_id: int | None = None) -> object:
    """Кнопка 'Подробнее' под сообщением со статистикой."""
    builder = InlineKeyboardBuilder()
    if student_id:
        builder.button(
            text="📈 Подробная статистика",
            callback_data=f"stats:detail:{student_id}",
        )
    else:
        builder.button(text="📈 Подробная статистика", callback_data="stats:detail:me")
    builder.adjust(1)
    return builder.as_markup()


# ── Callback: меню статистики ─────────────────────────────────────────────────

@router.callback_query(F.data == "stats:me")
async def cb_stats_me(call: CallbackQuery) -> None:
    await call.message.answer(
        "📊 <b>Статистика</b>\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=kb_stats_menu(),
    )
    await call.answer()


# ── Callback: общая статистика ────────────────────────────────────────────────

@router.callback_query(F.data == "stats:general")
async def cb_stats_general(call: CallbackQuery) -> None:
    stats = db.get_student_stats(call.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="stats:me"))
    await call.message.answer(
        _format_stats(stats, "Твоя"),
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


# ── Callback: статистика по заданиям ──────────────────────────────────────────

@router.callback_query(F.data == "stats:numbers")
async def cb_stats_numbers(call: CallbackQuery) -> None:
    detail = db.get_detailed_stats(call.from_user.id)
    rows = detail["by_number"]

    if not rows:
        text = "📋 <b>Статистика по заданиям</b>\n\nПока нет решённых заданий."
    else:
        lines = ["📋 <b>Статистика по заданиям ЕГЭ:</b>", ""]
        for row in rows:
            correct   = row["solved"]
            incorrect = row["tried"] - row["solved"]
            pct       = round(correct / row["tried"] * 100) if row["tried"] else 0
            icon      = _pct_icon(pct)
            lines.append(
                f"  {icon} №{row['number']} — ✅ {correct} | ❌ {incorrect} | {pct}%"
            )
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="stats:me"))
    await call.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await call.answer()


# ── Callback: статистика по темам ─────────────────────────────────────────────

@router.callback_query(F.data == "stats:topics")
async def cb_stats_topics(call: CallbackQuery) -> None:
    detail = db.get_detailed_stats(call.from_user.id)
    rows = detail["by_topic"]

    if not rows:
        text = "📚 <b>Статистика по темам</b>\n\nПока нет решённых заданий."
    else:
        lines = ["📚 <b>Статистика по темам:</b>", ""]
        for row in rows:
            correct   = row["solved"]
            incorrect = row["tried"] - row["solved"]
            pct       = round(correct / row["tried"] * 100) if row["tried"] else 0
            icon      = _pct_icon(pct)
            short     = row["topic"].split("/")[-1].strip() if "/" in row["topic"] else row["topic"]
            lines.append(
                f"  {icon} {short} — ✅ {correct} | ❌ {incorrect} | {pct}%"
            )
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="stats:me"))

    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = (current + "\n" + line).strip()
        if len(candidate) > _CHUNK:
            if current:
                parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)

    for i, part in enumerate(parts):
        kb = builder.as_markup() if i == len(parts) - 1 else None
        await call.message.answer(part, parse_mode="HTML", reply_markup=kb)
    await call.answer()


# ── Callback: подробная статистика ────────────────────────────────────────────

@router.callback_query(F.data.startswith("stats:detail:"))
async def cb_stats_detail(call: CallbackQuery) -> None:
    raw = call.data.split(":")[2]

    if raw == "me":
        user_id = call.from_user.id
        label   = "Твоя"
    else:
        # Только учитель/админ может смотреть чужую статистику
        if call.from_user.id not in ADMIN_IDS and not db.is_teacher(call.from_user.id):
            await call.answer("Нет доступа.", show_alert=True)
            return
        user_id = int(raw)
        user    = db.get_user(user_id)
        label   = f"Статистика {user['full_name']}" if user else f"ID {user_id}"

    detail = db.get_detailed_stats(user_id)
    parts  = _format_detailed(detail, label)

    for part in parts:
        await call.message.answer(part, parse_mode="HTML")
    await call.answer()


# ── /stats — команда (учитель видит список учеников, ученик — себя) ───────────

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    tg_id = message.from_user.id
    if tg_id in ADMIN_IDS or db.is_teacher(tg_id):
        students = db.get_teacher_students(tg_id)
        if not students:
            await message.answer("У тебя пока нет учеников.")
            return
        builder = InlineKeyboardBuilder()
        for s in students:
            builder.button(
                text=s["full_name"],
                callback_data=f"stats:student:{s['tg_id']}",
            )
        builder.adjust(1)
        await message.answer(
            "👥 Выбери ученика для просмотра статистики:",
            reply_markup=builder.as_markup(),
        )
    else:
        stats = db.get_student_stats(tg_id)
        await message.answer(
            _format_stats(stats),
            parse_mode="HTML",
            reply_markup=_stats_keyboard(tg_id),
        )


# ── Callback: статистика конкретного ученика (краткая) ────────────────────────

@router.callback_query(F.data.startswith("stats:student:"))
async def cb_stats_student(call: CallbackQuery) -> None:
    if call.from_user.id not in ADMIN_IDS and not db.is_teacher(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    student_id = int(call.data.split(":")[2])
    user       = db.get_user(student_id)
    name       = user["full_name"] if user else str(student_id)
    stats      = db.get_student_stats_for_teacher(student_id)

    await call.message.answer(
        _format_stats(stats, f"Статистика {name}"),
        parse_mode="HTML",
        reply_markup=_stats_keyboard(call.from_user.id, student_id=student_id),
    )
    await call.answer()
