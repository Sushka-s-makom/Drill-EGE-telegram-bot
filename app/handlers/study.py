"""Основной учебный поток: выбор → задание → ответ → решение."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from .. import db
from .. import keyboards as kb
from ..config import CARDS_DIR, CARDS_SOL
from ..states import StudentFSM

router = Router()


# ── Хелперы ───────────────────────────────────────────────────────────────────

def _registered_student(tg_id: int) -> bool:
    user = db.get_user(tg_id)
    return user is not None and user["role"] == "student"


async def safe_edit(call: CallbackQuery, text: str,
                    reply_markup: InlineKeyboardMarkup | None = None,
                    parse_mode: str = "HTML") -> None:
    """
    edit_text падает на фото-сообщениях. Удаляем фото и шлём новое текстовое.
    """
    msg = call.message
    if msg.photo or msg.document or msg.video:
        await msg.delete()
        await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def _send_question_card(
    bot: Bot,
    chat_id: int,
    question: dict,
    state: FSMContext,
) -> None:
    """Отправляет карточку задания и устанавливает нужное состояние."""
    qid     = question["id"]
    is_test = question["type"] == "test"
    has_vid = db.has_video(qid)
    file_id = question.get("tg_file_id")
    caption = f"<b>Задание №{question['exam_number']}</b> — {question['exam_topic']}"

    if is_test:
        caption += "\n\n✏️ <i>Введи ответ в чат</i>"
    else:
        caption += "\n\n📝 <i>Задание с развёрнутым ответом</i>"

    markup = None if is_test else kb.kb_written_question(qid, has_vid)

    if file_id:
        msg = await bot.send_photo(
            chat_id, file_id,
            caption=caption, parse_mode="HTML", reply_markup=markup,
        )
    else:
        card_path = CARDS_DIR / f"{qid}.png"
        if not card_path.exists():
            await bot.send_message(chat_id, "⚠️ Карточка не найдена, попробуй следующее задание.")
            return
        msg = await bot.send_photo(
            chat_id, FSInputFile(card_path),
            caption=caption, parse_mode="HTML", reply_markup=markup,
        )
        if msg.photo:
            db.save_tg_file_id(qid, msg.photo[-1].file_id)

    await state.update_data(question_id=qid, is_test=is_test, has_video=has_vid)
    if is_test:
        await state.set_state(StudentFSM.solving)


# ── Выбор предмета ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "subject:physics")
async def cb_subject_physics(call: CallbackQuery, state: FSMContext) -> None:
    if not _registered_student(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.update_data(subject="physics")
    await state.set_state(StudentFSM.choosing_mode)
    await safe_edit(call, "📚 <b>Физика</b>\n\nВыбери способ:", kb.kb_mode())


@router.callback_query(F.data == "subject:math")
async def cb_subject_math(call: CallbackQuery) -> None:
    await call.answer("📐 Математика — скоро будет добавлена!", show_alert=True)


# ── Выбор режима ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "mode:number")
async def cb_mode_number(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(filter_type="number")
    await state.set_state(StudentFSM.choosing_number)
    numbers = db.get_all_numbers()
    await safe_edit(call, "🔢 Выбери номер задания:", kb.kb_numbers(numbers))


@router.callback_query(F.data == "mode:topic")
async def cb_mode_topic(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(filter_type="topic")
    await state.set_state(StudentFSM.choosing_topic)
    topics = db.get_all_topics()
    await safe_edit(call, "📂 Выбери тему:", kb.kb_topics(topics))


# ── Выбор номера / темы ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("number:"))
async def cb_choose_number(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    num = int(call.data.split(":")[1])
    await state.update_data(filter_type="number", filter_value=num)
    question = db.get_next_question(call.from_user.id, "number", num)
    if not question:
        await call.answer(f"✅ Все задания №{num} решены верно!", show_alert=True)
        return
    await call.message.delete()
    await _send_question_card(bot, call.message.chat.id, question, state)
    await call.answer()


@router.callback_query(F.data.startswith("topic:"))
async def cb_choose_topic(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    topic = call.data[len("topic:"):]
    await state.update_data(filter_type="topic", filter_value=topic)
    question = db.get_next_question(call.from_user.id, "topic", topic)
    if not question:
        await call.answer("✅ Все задания по этой теме решены верно!", show_alert=True)
        return
    await call.message.delete()
    await _send_question_card(bot, call.message.chat.id, question, state)
    await call.answer()


# ── Ответ на тестовое задание ─────────────────────────────────────────────────

@router.message(StudentFSM.solving)
async def handle_answer(message: Message, state: FSMContext) -> None:
    data        = await state.get_data()
    qid         = data["question_id"]
    has_vid     = data.get("has_video", False)
    question    = db.get_question(qid)
    user_answer = message.text.strip()
    correct_ans = str(question["answer"]).strip()

    if db.check_answer(user_answer, correct_ans):
        db.mark_correct(message.from_user.id, qid, user_answer)
        await message.answer(
            f"✅ <b>Верно!</b> Правильный ответ: <code>{correct_ans}</code>",
            reply_markup=kb.kb_after_answer(qid, has_vid),
        )
    else:
        db.mark_incorrect(message.from_user.id, qid, user_answer)
        await message.answer(
            f"❌ <b>Неверно.</b> Правильный ответ: <code>{correct_ans}</code>\n"
            "Задание добавлено в работу над ошибками.",
            reply_markup=kb.kb_after_answer(qid, has_vid),
        )

    await state.set_state(StudentFSM.choosing_subject)


# ── Следующее задание ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "next")
async def cb_next(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data         = await state.get_data()
    filter_type  = data.get("filter_type")
    filter_value = data.get("filter_value")

    if not filter_type or filter_value is None:
        await safe_edit(call, "🏠 Главное меню:", kb.kb_main_menu(call.from_user.id))
        await state.set_state(StudentFSM.choosing_subject)
        await call.answer()
        return

    question = db.get_next_question(call.from_user.id, filter_type, filter_value)
    if not question:
        label = f"№{filter_value}" if filter_type == "number" else filter_value
        await safe_edit(
            call,
            f"✅ Все задания по <b>{label}</b> решены верно!\n\nВыбери предмет:",
            kb.kb_main_menu(call.from_user.id),
        )
        await state.set_state(StudentFSM.choosing_subject)
        await call.answer()
        return

    await call.message.delete()
    await _send_question_card(bot, call.message.chat.id, question, state)
    await call.answer()


# ── Посмотреть решение ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("solution:"))
async def cb_solution(call: CallbackQuery, bot: Bot) -> None:
    qid      = int(call.data.split(":")[1])
    has_vid  = db.has_video(qid)
    question = db.get_question(qid)
    sol_path = CARDS_SOL / f"{qid}.png"
    caption  = f"📖 <b>Решение задания №{question['exam_number']}</b>"

    if sol_path.exists():
        await bot.send_photo(
            call.message.chat.id,
            FSInputFile(sol_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb.kb_after_solution(has_vid, qid),
        )
    else:
        sol_text = db.get_solution_text(qid) or "Решение недоступно."
        await bot.send_message(
            call.message.chat.id,
            caption + "\n\n" + sol_text,
            parse_mode="HTML",
            reply_markup=kb.kb_after_solution(has_vid, qid),
        )
    await call.answer()


# ── Видеорешение ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("video:"))
async def cb_video(call: CallbackQuery) -> None:
    qid  = int(call.data.split(":")[1])
    info = db.get_video_info(qid)
    if info and info.startswith("http"):
        await call.message.answer(f"🎥 Видеорешение: {info}")
    elif info:
        await call.message.answer(
            f"🎥 {info}\n\n<i>Ссылка на видео пока не добавлена.</i>",
            parse_mode="HTML",
        )
    else:
        await call.answer("Видеорешение пока недоступно.", show_alert=True)
        return
    await call.answer()


# ── Навигация назад ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "back:main")
async def cb_back_main(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StudentFSM.choosing_subject)
    await safe_edit(call, "🏠 Главное меню. Выбери предмет:", kb.kb_main_menu(call.from_user.id))
    await call.answer()


@router.callback_query(F.data == "back:mode")
async def cb_back_mode(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StudentFSM.choosing_mode)
    await safe_edit(call, "📚 <b>Физика</b>\n\nВыбери способ:", kb.kb_mode())
    await call.answer()
