"""Обработка /start и инвайт-ссылок."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import db
from .. import keyboards as kb
from ..config import ADMIN_IDS
from ..states import StudentFSM

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg_id    = message.from_user.id
    name     = message.from_user.full_name
    username = message.from_user.username
    args     = message.text.split(maxsplit=1)[1] if " " in message.text else ""

    # ── Учитель / администратор ───────────────────────────────────────────────
    if tg_id in ADMIN_IDS:
        if not db.get_user(tg_id):
            db.register_teacher(tg_id, name, username)
        else:
            db.upsert_user(tg_id, name, username)
        await message.answer(
            f"👋 Привет, {name}!\n"
            "Ты зарегистрирован как <b>учитель</b>.\n\n"
            "Команды:\n"
            "• /invite — создать инвайт для ученика\n"
            "• /students — список учеников\n"
            "• /invite_teacher — создать инвайт для учителя\n"
            "• /teachers — список учителей\n"
            "• /stats — статистика учеников",
            parse_mode="HTML",
        )
        return

    # ── Обработка инвайт-ссылки ───────────────────────────────────────────────
    if args.startswith("inv_"):
        token  = args[4:]
        invite = db.get_invite(token)

        if not invite:
            await message.answer("❌ Инвайт-ссылка недействительна.")
            return
        if invite["used_by"] and invite["used_by"] != tg_id:
            await message.answer("❌ Эта ссылка уже использована.")
            return

        invite_role = invite.get("role") or "student"

        if invite_role == "teacher":
            db.register_teacher(tg_id, name, username)
            db.use_invite(token, tg_id)
            await message.answer(
                f"✅ Привет, {name}! Ты зарегистрирован как <b>учитель</b>.\n\n"
                "Команды:\n"
                "• /invite — создать инвайт для ученика\n"
                "• /students — список учеников\n"
                "• /stats — статистика учеников",
                parse_mode="HTML",
            )
        else:
            db.register_student(tg_id, name, username, invite["teacher_id"])
            db.use_invite(token, tg_id)
            await state.set_state(StudentFSM.choosing_subject)
            await message.answer(
                f"✅ Привет, {name}! Ты успешно подключён к учителю.\n\n"
                "Выбери предмет:",
                reply_markup=kb.kb_main_menu(tg_id),
            )
        return

    # ── Уже зарегистрированный пользователь ──────────────────────────────────
    user = db.get_user(tg_id)
    if user:
        db.upsert_user(tg_id, name, username)

        if user["role"] == "student":
            await state.set_state(StudentFSM.choosing_subject)
            await message.answer(
                f"👋 С возвращением, {name}!\nВыбери предмет:",
                reply_markup=kb.kb_main_menu(tg_id),
            )
            return

        if user["role"] in ("teacher", "admin"):
            await message.answer(
                f"👋 С возвращением, {name}!\n\n"
                "Команды:\n"
                "• /invite — создать инвайт для ученика\n"
                "• /students — список учеников\n"
                "• /stats — статистика учеников",
                parse_mode="HTML",
            )
            return

    # ── Незарегистрированный пользователь ─────────────────────────────────────
    await message.answer(
        "👋 Привет!\n\n"
        "Для доступа к боту тебе нужна инвайт-ссылка от учителя.\n"
        "Попроси учителя создать её командой /invite и отправь её мне."
    )
