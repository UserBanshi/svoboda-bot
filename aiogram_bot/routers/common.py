# aiogram_bot/routers/common.py
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import config

router = Router()
# фильтр на сообщения только от админа
router.message.filter(F.from_user.id == config.ADMIN_ID)

@router.message(Command("start"), StateFilter(None))
async def cmd_start(message: Message):
    # приветственное сообщение с командами в HTML
    await message.answer(
        "<b>SVOBODA Bot</b> (Aiogram + Telethon)\n\n"
        "Бот использует ваш аккаунт для анализа и действий.\n\n"
        "<b>Команды:</b>\n"
        "<code>/analyze</code> - Запустить анализ чатов (Telethon).\n"
        "<code>/delete</code> - Показать чаты для удаления и запросить подтверждение (Telethon).\n"
        "<code>/deletecontacts</code> - Показать контакты для удаления и запросить подтверждение (Telethon).\n"
        "<code>/clearcache</code> - Очистить результаты последнего анализа.\n"
        "<code>/help</code> - Показать это сообщение.\n\n"
        "<b>ВНИМАНИЕ:</b> Команды <code>/delete</code> и <code>/deletecontacts</code> выполняют необратимые действия!"
    )

@router.message(Command("help"), StateFilter(None))
async def cmd_help(message: Message):
    await cmd_start(message)

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    # отмена текущей операции (если есть состояние)
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активной операции для отмены.")
        return

    await state.clear()
    await message.answer("Операция отменена.")