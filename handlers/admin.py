"""Команды учителя и главного администратора."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from config import ADMIN_IDS, MAIN_ADMIN_ID

router = Router()


def _teacher_only(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS or db.is_teacher(tg_id)


def _main_admin_only(tg_id: int) -> bool:
    return tg_id == MAIN_ADMIN_ID


# ── /invite — инвайт для ученика ──────────────────────────────────────────────

@router.message(Command("invite"))
async def cmd_invite(message: Message, bot: Bot) -> None:
    if not _teacher_only(message.from_user.id):
        await message.answer("❌ Команда доступна только учителям.")
        return

    if not db.get_user(message.from_user.id):
        db.register_teacher(
            message.from_user.id,
            message.from_user.full_name,
            message.from_user.username,
        )

    token = db.create_invite(message.from_user.id, role="student")
    me    = await bot.get_me()
    link  = f"https://t.me/{me.username}?start=inv_{token}"

    await message.answer(
        "🔗 <b>Инвайт-ссылка для ученика:</b>\n\n"
        f"<code>{link}</code>\n\n"
        "Перешли эту ссылку ученику. После перехода он будет привязан к тебе.",
        parse_mode="HTML",
    )


# ── /invite_teacher — инвайт для учителя (только главный админ) ───────────────

@router.message(Command("invite_teacher"))
async def cmd_invite_teacher(message: Message, bot: Bot) -> None:
    if not _main_admin_only(message.from_user.id):
        await message.answer("❌ Команда доступна только главному администратору.")
        return

    token = db.create_invite(message.from_user.id, role="teacher")
    me    = await bot.get_me()
    link  = f"https://t.me/{me.username}?start=inv_{token}"

    await message.answer(
        "🔗 <b>Инвайт-ссылка для учителя:</b>\n\n"
        f"<code>{link}</code>\n\n"
        "Перешли эту ссылку будущему учителю. После перехода по ссылке "
        "он получит роль <b>учителя</b>.",
        parse_mode="HTML",
    )


# ── /students — список учеников учителя ───────────────────────────────────────

@router.message(Command("students"))
async def cmd_students(message: Message) -> None:
    if not _teacher_only(message.from_user.id):
        await message.answer("❌ Команда доступна только учителям.")
        return

    students = db.get_teacher_students(message.from_user.id)
    if not students:
        await message.answer("У тебя пока нет учеников.")
        return

    lines = [f"👥 <b>Ученики ({len(students)}):</b>"]
    for i, s in enumerate(students, 1):
        uname = f" (@{s['username']})" if s.get("username") else ""
        lines.append(f"{i}. {s['full_name']}{uname} — <code>{s['tg_id']}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /teachers — список учителей с кнопкой удаления (только главный админ) ────

@router.message(Command("teachers"))
async def cmd_teachers(message: Message) -> None:
    if not _main_admin_only(message.from_user.id):
        await message.answer("❌ Команда доступна только главному администратору.")
        return

    teachers = db.get_all_teachers()
    # Не показываем самого главного админа в списке на удаление
    teachers = [t for t in teachers if t["tg_id"] != MAIN_ADMIN_ID]

    if not teachers:
        await message.answer("Учителей пока нет.")
        return

    builder = InlineKeyboardBuilder()
    for t in teachers:
        uname = f" (@{t['username']})" if t.get("username") else ""
        label = f"🗑 {t['full_name']}{uname}"
        builder.button(
            text=label,
            callback_data=f"admin:removeteacher:{t['tg_id']}",
        )
    builder.adjust(1)

    lines = [f"👩‍🏫 <b>Учителя ({len(teachers)}):</b>"]
    for i, t in enumerate(teachers, 1):
        uname = f" (@{t['username']})" if t.get("username") else ""
        lines.append(f"{i}. {t['full_name']}{uname} — <code>{t['tg_id']}</code>")

    await message.answer(
        "\n".join(lines) + "\n\nНажми кнопку чтобы снять роль учителя:",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


# ── Callback: снять учителя ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:removeteacher:"))
async def cb_remove_teacher(call: CallbackQuery) -> None:
    if not _main_admin_only(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    target_id = int(call.data.split(":")[2])

    if target_id == MAIN_ADMIN_ID:
        await call.answer("Нельзя снять самого себя.", show_alert=True)
        return

    target = db.get_user(target_id)
    name   = target["full_name"] if target else str(target_id)

    removed = db.remove_teacher(target_id)
    if removed:
        await call.message.edit_text(
            f"✅ Пользователь <b>{name}</b> (<code>{target_id}</code>) "
            "снят с роли учителя.",
            parse_mode="HTML",
        )
    else:
        await call.answer("Пользователь не найден или уже не учитель.", show_alert=True)
