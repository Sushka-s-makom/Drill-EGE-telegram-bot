"""Все клавиатуры бота."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db


def kb_main_menu(user_id: int) -> InlineKeyboardMarkup:
    count = db.mistakes_count(user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Физика",      callback_data="subject:physics")
    builder.button(text="📐 Математика",  callback_data="subject:math")
    builder.adjust(2)
    if count:
        builder.row(InlineKeyboardButton(
            text=f"❌ Работа над ошибками ({count})",
            callback_data="mistakes:list",
        ))
    builder.row(InlineKeyboardButton(
        text="📊 Моя статистика",
        callback_data="stats:me",
    ))
    return builder.as_markup()


def kb_mode() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔢 По номеру задания", callback_data="mode:number")
    builder.button(text="📂 По теме",           callback_data="mode:topic")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="back:main"))
    return builder.as_markup()


def kb_numbers(numbers: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in numbers:
        builder.button(text=str(n), callback_data=f"number:{n}")
    builder.adjust(5)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="back:mode"))
    return builder.as_markup()


def kb_topics(topics: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in topics:
        short = t.split("/")[-1].strip()
        builder.button(text=short, callback_data=f"topic:{t}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data="back:mode"))
    return builder.as_markup()


def kb_written_question(question_id: int, has_video: bool) -> InlineKeyboardMarkup:
    """Кнопки под заданием письменного типа."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Посмотреть решение", callback_data=f"solution:{question_id}")
    if has_video:
        builder.button(text="🎥 Видеорешение", callback_data=f"video:{question_id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="➡️ Следующее задание", callback_data="next"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню",      callback_data="back:main"))
    return builder.as_markup()


def kb_after_answer(question_id: int, has_video: bool) -> InlineKeyboardMarkup:
    """Кнопки после ответа на тестовое задание."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Посмотреть решение", callback_data=f"solution:{question_id}")
    if has_video:
        builder.button(text="🎥 Видеорешение", callback_data=f"video:{question_id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="➡️ Следующее задание", callback_data="next"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню",      callback_data="back:main"))
    return builder.as_markup()


def kb_after_solution(has_video: bool, question_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_video:
        builder.button(text="🎥 Видеорешение", callback_data=f"video:{question_id}")
        builder.adjust(1)
    builder.row(InlineKeyboardButton(text="➡️ Следующее задание", callback_data="next"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню",      callback_data="back:main"))
    return builder.as_markup()


def kb_stats_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Статистика по заданиям", callback_data="stats:numbers")
    builder.button(text="📚 Статистика по темам",    callback_data="stats:topics")
    builder.button(text="📊 Общая статистика",       callback_data="stats:general")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="← Главное меню", callback_data="back:main"))
    return builder.as_markup()


def kb_mistakes_list(questions: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for q in questions:
        label = f"№{q['exam_number']} — {(q['exam_topic'] or '').split('/')[-1].strip()}"
        builder.button(text=label, callback_data=f"mistakes:solve:{q['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="← Главное меню", callback_data="back:main"))
    return builder.as_markup()
