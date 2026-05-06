"""Работа над ошибками."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import db
import keyboards as kb
from states import StudentFSM
from handlers.study import _send_question_card

router = Router()


@router.callback_query(F.data == "mistakes:list")
async def cb_mistakes_list(call: CallbackQuery, state: FSMContext) -> None:
    questions = db.get_mistakes(call.from_user.id)
    if not questions:
        await call.answer("Ошибок нет — отличная работа! 🎉", show_alert=True)
        return
    await state.set_state(StudentFSM.mistakes_list)
    await call.message.edit_text(
        f"❌ <b>Работа над ошибками</b> — {len(questions)} задан.:",
        parse_mode="HTML",
        reply_markup=kb.kb_mistakes_list(questions),
    )


@router.callback_query(F.data.startswith("mistakes:solve:"))
async def cb_mistakes_solve(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    qid      = int(call.data.split(":")[2])
    question = db.get_question(qid)
    if not question:
        await call.answer("Задание не найдено.", show_alert=True)
        return

    # Используем filter_type=None чтобы после ответа не предлагать "следующее"
    await state.update_data(filter_type=None, filter_value=None)
    await call.message.delete()
    await _send_question_card(bot, call.message.chat.id, question, state)
    await call.answer()
