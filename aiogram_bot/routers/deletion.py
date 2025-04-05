# aiogram_bot/routers/deletion.py
import asyncio
import logging
import os
from aiogram import Router, F, Bot, Dispatcher
from aiogram.filters import Command, StateFilter, CallbackQueryFilter
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.utils.text_decorations import html_decoration
from aiogram.exceptions import TelegramBadRequest

import config
from ..bot_instance import bot
from ..states import DeletionStates
from .analysis import analysis_cache
from telethon_client import actions, utils, analyzer
from telethon_client.client_instance import get_telethon_client

import shared_state


logger = logging.getLogger(__name__)
router = Router()
router.message.filter(F.from_user.id == config.ADMIN_ID)
# Фильтр для колбеков от админа
router.callback_query.filter(F.from_user.id == config.ADMIN_ID)


async def deletion_status_callback(chat_id: int, status_message: str):
    # отправка статуса удаления (без изменений)
    try:
        await bot.send_message(chat_id, f"<code>{html_decoration.quote(status_message)}</code>")
    except Exception as e:
        logger.warning(f"не удалось отправить статус удаления в чат {chat_id}: {e}")

# --- Хелпер для отправки промпта очистки/остановки ---
async def offer_cleanup_and_stop(dp: Dispatcher, chat_id: int, user_id: int, final_status_message: Message | None = None):
    """Отправляет сообщение с предложением очистки и остановки."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, очистить и остановить", callback_data="confirm_cleanup_stop")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_cleanup")]
    ])
    try:
        prompt_msg = await bot.send_message(
            chat_id,
            "Операция завершена.\nОчистить историю этого чата (последние сообщения) и остановить бота?",
            reply_markup=keyboard
        )
        # Устанавливаем состояние и сохраняем ID сообщения с кнопками
        user_key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=user_id)
        # Передаем ID сообщения с кнопками и ID предыдущего сообщения (статуса) для удаления
        data_to_store = {"cleanup_prompt_msg_id": prompt_msg.message_id}
        if final_status_message:
             data_to_store["final_status_msg_id"] = final_status_message.message_id
        await dp.storage.set_state(key=user_key, state=DeletionStates.confirm_cleanup_stop)
        await dp.storage.set_data(key=user_key, data=data_to_store)
        logger.info(f"Предложена очистка/остановка пользователю {user_id} в чате {chat_id}")
    except Exception as e:
        logger.error(f"Не удалось предложить очистку/остановку в чате {chat_id}: {e}")


async def run_chat_deletion_background(dp: Dispatcher, chat_id_to_notify: int, user_id: int, chats_list: list[dict]):
    # фоновое удаление ЧАТОВ
    global analysis_cache
    analysis_cache["is_busy"] = True
    final_status_msg = None
    success = False
    try:
        get_telethon_client()
        chat_ids = [chat['id'] for chat in chats_list]
        results = await actions.delete_chats_job(
            chat_ids, lambda status: deletion_status_callback(chat_id_to_notify, status)
        )
        deleted_ids = results.get("deleted_ids", set())
        deleted_count = results.get('deleted', 0)
        failed_count = results.get('failed', 0)
        success = failed_count == 0 # Считаем успехом, если не было ошибок

        if analysis_cache.get("analysis_results") is not None:
            report_filepath = utils.generate_html_report(
                 analysis_results=analysis_cache["analysis_results"],
                 permanent_whitelist_ids=analysis_cache["permanent_whitelist_ids"],
                 permanent_whitelist_names=analysis_cache["whitelist_names"],
                 candidates_for_deletion=[], final_deleted_ids=deleted_ids,
                 terms_list=analysis_cache.get("terms", [])
            )
            final_report_msg_text = f"Удаление ЧАТОВ завершено.\nУдалено: {deleted_count}\nОшибок: {failed_count}\nОбновленный отчет:"
            if report_filepath and os.path.exists(report_filepath):
                 final_status_msg = await bot.send_document(chat_id_to_notify, FSInputFile(report_filepath), caption=final_report_msg_text)
            else:
                 final_status_msg = await bot.send_message(chat_id_to_notify, final_report_msg_text + "\n<i>Не удалось создать/отправить отчет.</i>")
        else:
             final_status_msg = await bot.send_message(chat_id_to_notify, f"Удаление ЧАТОВ завершено.\nУдалено: {deleted_count}\nОшибок: {failed_count}")

        # Предлагаем очистку после завершения
        await offer_cleanup_and_stop(dp, chat_id_to_notify, user_id, final_status_msg)

    except ConnectionError as e:
        logger.error(f"ошибка telethon при удалении чатов: {e}")
        await bot.send_message(chat_id_to_notify, f"<b>Ошибка:</b> Клиент Telethon не активен.\n{html_decoration.quote(str(e))}")
    except Exception as e:
        logger.exception("aiogram: ошибка фонового удаления чатов")
        await bot.send_message(chat_id_to_notify, f"<b>Ошибка удаления чатов:</b>\n{html_decoration.quote(str(e))}")
    finally:
        analysis_cache["candidates_for_chat_deletion"] = []
        # Не сбрасываем is_busy здесь, ждем реакции пользователя на cleanup
        # analysis_cache["is_busy"] = False

async def run_message_deletion_background(dp: Dispatcher, chat_id_to_notify: int, user_id: int, messages_dict: dict[int, list[int]]):
    # фоновое удаление СООБЩЕНИЙ
    global analysis_cache
    analysis_cache["is_busy"] = True
    final_status_msg = None
    success = False
    try:
        get_telethon_client()
        results = await actions.delete_messages_job(
             messages_dict, lambda status: deletion_status_callback(chat_id_to_notify, status)
        )
        deleted_count = results.get('deleted', 0)
        failed_count = results.get('failed', 0)
        success = failed_count == 0
        final_status_msg = await bot.send_message(chat_id_to_notify, f"Удаление СООБЩЕНИЙ завершено.\nУдалено: {deleted_count}\nОшибок: {failed_count}")
        # Предлагаем очистку
        await offer_cleanup_and_stop(dp, chat_id_to_notify, user_id, final_status_msg)
    except ConnectionError as e:
        logger.error(f"ошибка telethon при удалении сообщений: {e}")
        await bot.send_message(chat_id_to_notify, f"<b>Ошибка:</b> Клиент Telethon не активен.\n{html_decoration.quote(str(e))}")
    except Exception as e:
        logger.exception("aiogram: ошибка фонового удаления сообщений")
        await bot.send_message(chat_id_to_notify, f"<b>Ошибка удаления сообщений:</b>\n{html_decoration.quote(str(e))}")
    finally:
        analysis_cache["candidates_for_msg_deletion"] = {}
        # Не сбрасываем is_busy
        # analysis_cache["is_busy"] = False

async def run_contact_deletion_background(dp: Dispatcher, chat_id_to_notify: int, user_id: int, contacts_list: list):
    # фоновое удаление КОНТАКТОВ
    global analysis_cache
    analysis_cache["is_busy"] = True
    final_status_msg = None
    success = False
    try:
        get_telethon_client()
        results = await actions.delete_contacts_job(
             contacts_list, lambda status: deletion_status_callback(chat_id_to_notify, status)
        )
        deleted_count = results.get('deleted', 0)
        failed_count = results.get('failed', 0)
        success = failed_count == 0
        final_status_msg = await bot.send_message(chat_id_to_notify, f"Удаление КОНТАКТОВ завершено.\nУспешно удалено: {deleted_count}\nОшибок/пропущено: {failed_count}")
        # Предлагаем очистку
        await offer_cleanup_and_stop(dp, chat_id_to_notify, user_id, final_status_msg)
    except ConnectionError as e:
        logger.error(f"ошибка telethon при удалении контактов: {e}")
        await bot.send_message(chat_id_to_notify, f"<b>Ошибка:</b> Клиент Telethon не активен.\n{html_decoration.quote(str(e))}")
    except Exception as e:
        logger.exception("aiogram: ошибка фонового удаления контактов")
        await bot.send_message(chat_id_to_notify, f"<b>Ошибка удаления контактов:</b>\n{html_decoration.quote(str(e))}")
    finally:
        # Не сбрасываем is_busy
        # analysis_cache["is_busy"] = False

# --- Обработчик команды /delete (без изменений в логике показа) ---
@router.message(Command("delete"), StateFilter(None))
async def cmd_delete(message: Message, state: FSMContext):
    # показать кандидатов на удаление чатов и сообщений
    global analysis_cache
    if analysis_cache["is_busy"]: await message.answer("Бот занят."); return
    if analysis_cache["analysis_results"] is None: await message.answer("Сначала запустите <code>/analyze</code>."); return

    candidates_chat = analysis_cache.get("candidates_for_chat_deletion", [])
    candidates_msg = analysis_cache.get("candidates_for_msg_deletion", {})
    messages_with_triggers = analysis_cache.get("messages_with_triggers", {})

    if not candidates_chat and not candidates_msg:
        await message.answer("Нет объектов для удаления."); return

    response = "<b>Объекты для удаления:</b>\n"
    action_planned = False; chats_to_delete_full = []; msgs_to_delete_dict = {}

    if candidates_chat:
        action_planned = True; response += "\n<b>--- ЧАТЫ НА ПОЛНОЕ УДАЛЕНИЕ ---</b>\n"
        for idx, chat_info in enumerate(candidates_chat):
            safe_title = html_decoration.quote(chat_info.get('title', 'N/A')); chat_id_str = f"<code>{chat_info.get('id', 'N/A')}</code>"; count_str = chat_info.get('count', 0)
            response += f"{idx + 1}. <b>{safe_title}</b> (ID: {chat_id_str}) - Триггеров: {count_str}\n"
            chats_to_delete_full.append(chat_info)

    if candidates_msg:
        action_planned = True; response += "\n<b>--- ЧАТЫ С УДАЛЕНИЕМ СООБЩЕНИЙ ---</b>\n"
        chat_titles = {res['id']: res['title'] for res in analysis_cache.get("analysis_results", [])}
        idx = 0
        for chat_id, expected_msg_count in candidates_msg.items():
            actual_message_ids = messages_with_triggers.get(chat_id)
            if not actual_message_ids: continue # Пропускаем, если нет ID
            idx += 1; safe_title = html_decoration.quote(chat_titles.get(chat_id, f'ID {chat_id}')); chat_id_str = f"<code>{chat_id}</code>"; actual_msg_count = len(actual_message_ids)
            response += f"{idx}. <b>{safe_title}</b> (ID: {chat_id_str}) - Сообщений: {actual_msg_count}\n"
            msgs_to_delete_dict[chat_id] = actual_message_ids

    if not action_planned: await message.answer("Нет действий для выполнения."); return

    response += f"\n<b>ВНИМАНИЕ!</b> Действия необратимы!\nДля подтверждения отправьте:\n<code>{config.CHAT_DELETION_CONFIRMATION_PHRASE}</code>\nИли <code>/cancel</code> для отмены."
    await state.update_data(chats_to_delete_full=chats_to_delete_full, msgs_to_delete_dict=msgs_to_delete_dict)
    await state.set_state(DeletionStates.pending_chat_deletion)
    await message.answer(response); logger.info(f"aiogram: запрошено подтверждение удаления {len(chats_to_delete_full)} чатов и сообщений в {len(msgs_to_delete_dict)} чатах.")


# --- Обработчик подтверждения удаления (/delete) ---
@router.message(StateFilter(DeletionStates.pending_chat_deletion), F.text == config.CHAT_DELETION_CONFIRMATION_PHRASE)
async def confirm_delete_actions(message: Message, state: FSMContext):
    # подтверждение удаления чатов и/или сообщений
    global analysis_cache
    # Получаем dp из контекста (или глобально, если так настроено)
    try:
        dp = Dispatcher.get_current() # Пытаемся получить текущий диспетчер
        if not dp: raise RuntimeError("Не удалось получить диспетчер")
    except Exception as e: # Если не получилось, например, вне контекста события
        logger.error(f"Критическая ошибка: не удалось получить диспетчер для FSM: {e}")
        await message.answer("Внутренняя ошибка: не удалось получить доступ к хранилищу состояний.")
        await state.clear()
        analysis_cache["is_busy"] = False # Освобождаем на всякий случай
        return

    if analysis_cache["is_busy"]: await message.answer("Бот занят."); return

    user_data = await state.get_data()
    chats_to_delete_full = user_data.get("chats_to_delete_full", [])
    msgs_to_delete_dict = user_data.get("msgs_to_delete_dict", {})
    await state.clear()

    if not chats_to_delete_full and not msgs_to_delete_dict:
        await message.answer("Ошибка: не найдены объекты для удаления."); logger.warning("aiogram: нет объектов в FSM.")
        return

    tasks_to_run = []
    if chats_to_delete_full:
        logger.warning(f"aiogram: подтверждено удаление {len(chats_to_delete_full)} чатов.")
        # Передаем dp в фоновую задачу
        tasks_to_run.append(run_chat_deletion_background(dp, message.chat.id, message.from_user.id, chats_to_delete_full))

    if msgs_to_delete_dict:
        total_msgs = sum(len(ids) for ids in msgs_to_delete_dict.values())
        logger.warning(f"aiogram: подтверждено удаление {total_msgs} сообщений в {len(msgs_to_delete_dict)} чатах.")
        # Передаем dp в фоновую задачу
        tasks_to_run.append(run_message_deletion_background(dp, message.chat.id, message.from_user.id, msgs_to_delete_dict))

    if tasks_to_run:
        await message.answer(f"Подтверждено. Запускаю {len(tasks_to_run)} фоновых задач удаления...")
        # Запускаем задачи. is_busy будет установлен внутри них.
        for task in tasks_to_run:
            asyncio.create_task(task)
    else: await message.answer("Нет действий для выполнения.")


# --- Команда /deletecontacts и её подтверждение ---
@router.message(Command("deletecontacts"), StateFilter(None))
async def cmd_delete_contacts(message: Message, state: FSMContext):
    # показать кандидатов на удаление контактов (код как раньше)
    global analysis_cache
    if analysis_cache["is_busy"]: await message.answer("Бот занят."); return
    analysis_cache["is_busy"] = True
    await message.answer("Получаю контакты через Telethon...")
    logger.info("aiogram: запрошено /deletecontacts")
    try:
        get_telethon_client()
        if not analysis_cache.get("permanent_whitelist_ids"): # Проверка наличия ключа
             analysis_cache["whitelist_names"] = utils.load_list_from_file(config.WHITELIST_FILE)
             analysis_cache["permanent_whitelist_ids"] = await analyzer.find_whitelisted_ids(analysis_cache["whitelist_names"])
        contacts_to_delete = await actions.get_contacts_for_deletion(analysis_cache.get("permanent_whitelist_ids", set()))
        if not contacts_to_delete:
            await message.answer("Контактов для удаления нет."); logger.info("aiogram: нет контактов для удаления.")
            analysis_cache["is_busy"] = False; return
        response = f"<b>Найдено {len(contacts_to_delete)} контактов для удаления:</b>\n\n"
        for idx, user in enumerate(contacts_to_delete[:20]):
            display_name = await utils.get_user_display_name(user); username = f"(@{user.username})" if user.username else ""
            safe_name = html_decoration.quote(display_name); safe_username = html_decoration.quote(username); user_id_str = f"<code>{user.id}</code>"
            response += f"{idx + 1}. <b>{safe_name}</b> {safe_username} (ID: {user_id_str})\n"
        if len(contacts_to_delete) > 20: response += f"... и еще {len(contacts_to_delete) - 20}\n"
        response += f"\n<b>!!! ВНИМАНИЕ !!!</b> Удаление контактов <b>НЕОБРАТИМО</b>!\nДля подтверждения отправьте:\n<code>{config.CONTACT_DELETION_CONFIRMATION_PHRASE}</code>\nИли <code>/cancel</code> для отмены."
        await state.update_data(contacts_to_delete=contacts_to_delete); await state.set_state(DeletionStates.pending_contact_deletion)
        await message.answer(response); logger.warning(f"aiogram: запрошено подтверждение удаления {len(contacts_to_delete)} контактов.")
    except ConnectionError as e: logger.error(f"ошибка telethon при получении контактов: {e}"); await message.answer(f"<b>Ошибка:</b> Клиент Telethon не активен.\n{html_decoration.quote(str(e))}"); analysis_cache["is_busy"] = False
    except Exception as e: logger.exception("aiogram: ошибка при получении контактов"); await message.answer(f"<b>Ошибка получения контактов:</b>\n{html_decoration.quote(str(e))}"); analysis_cache["is_busy"] = False

@router.message(StateFilter(DeletionStates.pending_contact_deletion), F.text == config.CONTACT_DELETION_CONFIRMATION_PHRASE)
async def confirm_delete_contacts(message: Message, state: FSMContext):
    # подтверждение удаления контактов
    global analysis_cache
    try: # Получаем dp
        dp = Dispatcher.get_current()
        if not dp: raise RuntimeError("Не удалось получить диспетчер")
    except Exception as e:
        logger.error(f"Критическая ошибка: не удалось получить диспетчер для FSM: {e}")
        await message.answer("Внутренняя ошибка: не удалось получить доступ к хранилищу состояний.")
        await state.clear(); analysis_cache["is_busy"] = False; return

    # is_busy уже True
    user_data = await state.get_data(); contacts_to_delete = user_data.get("contacts_to_delete"); await state.clear()
    if not contacts_to_delete:
        await message.answer("Ошибка: не найден список контактов."); logger.warning("aiogram: нет contacts_to_delete в FSM.")
        analysis_cache["is_busy"] = False; return
    await message.answer(f"Подтверждено. Запускаю <b>НЕОБРАТИМОЕ</b> удаление {len(contacts_to_delete)} контактов...")
    logger.warning(f"!!! aiogram: ПОДТВЕРЖДЕНО УДАЛЕНИЕ {len(contacts_to_delete)} КОНТАКТОВ !!!")
    # Передаем dp в фоновую задачу
    asyncio.create_task(run_contact_deletion_background(dp, message.chat.id, message.from_user.id, contacts_to_delete))




@router.callback_query(StateFilter(DeletionStates.confirm_cleanup_stop), F.data == "confirm_cleanup_stop")
async def handle_confirm_cleanup_stop(callback_query: CallbackQuery, state: FSMContext):
    """Обрабатывает подтверждение очистки и остановки."""
    global analysis_cache
    user_data = await state.get_data()
    prompt_msg_id = user_data.get("cleanup_prompt_msg_id")
    final_status_msg_id = user_data.get("final_status_msg_id")
    await state.clear()
    analysis_cache["is_busy"] = False # Считаем операцию завершенной

    await callback_query.answer("Остановка бота...") # Ответ на колбек
    logger.warning(f"Пользователь {callback_query.from_user.id} подтвердил очистку и остановку.")

    # Пытаемся удалить сообщения с кнопками и предыдущее статусное сообщение
    msgs_to_del = [mid for mid in [prompt_msg_id, final_status_msg_id] if mid]
    if msgs_to_del:
        try:
            await bot.delete_messages(chat_id=callback_query.message.chat.id, message_ids=msgs_to_del)
            logger.info(f"Удалены сообщения {msgs_to_del} перед остановкой.")
        except TelegramBadRequest as e:
            logger.warning(f"Не удалось удалить сообщения {msgs_to_del} перед остановкой: {e}")
        except Exception as e:
             logger.error(f"Непредвиденная ошибка при удалении сообщений перед остановкой: {e}")

    # Отправляем финальное сообщение
    await bot.send_message(callback_query.message.chat.id, "Остановка бота...")

    # Устанавливаем событие для остановки главного цикла
    shared_state.shutdown_event.set()


@router.callback_query(StateFilter(DeletionStates.confirm_cleanup_stop), F.data == "cancel_cleanup")
async def handle_cancel_cleanup(callback_query: CallbackQuery, state: FSMContext):
    """Обрабатывает отмену очистки и остановки."""
    global analysis_cache
    user_data = await state.get_data()
    prompt_msg_id = user_data.get("cleanup_prompt_msg_id")
    await state.clear()
    analysis_cache["is_busy"] = False # Считаем операцию завершенной

    await callback_query.answer("Отменено") # Ответ на колбек
    logger.info(f"Пользователь {callback_query.from_user.id} отменил очистку и остановку.")

    # Удаляем сообщение с кнопками
    if prompt_msg_id:
        try:
            await bot.delete_message(chat_id=callback_query.message.chat.id, message_id=prompt_msg_id)
        except Exception as e:
             logger.warning(f"Не удалось удалить сообщение с кнопками ({prompt_msg_id}) после отмены: {e}")

    await bot.send_message(callback_query.message.chat.id, "Очистка и остановка отменены.")

@router.message(StateFilter(DeletionStates.confirm_cleanup_stop))
async def handle_text_while_confirming_cleanup(message: Message, state: FSMContext):
    """Ловит текстовые сообщения в состоянии ожидания подтверждения очистки."""
    global analysis_cache
    await state.clear()
    analysis_cache["is_busy"] = False
    await message.answer("Ожидалось нажатие кнопки. Операция очистки и остановки отменена.")
    logger.info("Операция очистки/остановки отменена из-за текстового сообщения.")


# --- Обработчик отмены/неверного ввода в ДРУГИХ состояниях ожидания ---
@router.message(StateFilter(DeletionStates.pending_chat_deletion, DeletionStates.pending_contact_deletion))
async def incorrect_confirmation(message: Message, state: FSMContext):
    # ловит неверное сообщение при ожидании подтверждения УДАЛЕНИЯ
    global analysis_cache
    current_state = await state.get_state()
    await state.clear()

    op_type = "удаления объектов" if current_state == DeletionStates.pending_chat_deletion else "удаления контактов"
    await message.answer(f"Неверная фраза. Операция {op_type} отменена.")
    logger.info(f"aiogram: операция {op_type} отменена.")