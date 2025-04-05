# aiogram_bot/routers/analysis.py
import asyncio
import logging
import os
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.text_decorations import html_decoration

import config
from ..bot_instance import bot
from telethon_client import analyzer, utils, actions
from telethon_client.client_instance import get_telethon_client

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(F.from_user.id == config.ADMIN_ID)

# кэш анализа (в памяти)
analysis_cache = {
    "analysis_results": None,
    "messages_with_triggers": None,
    "candidates_for_chat_deletion": None,
    "candidates_for_msg_deletion": None,
    "permanent_whitelist_ids": set(),
    "is_busy": False,
    "terms": [],
    "whitelist_names": []
}

@router.message(Command("clearcache"), StateFilter(None))
async def cmd_clear_cache(message: Message):
    # очистка кэша
    global analysis_cache
    if analysis_cache["is_busy"]:
        await message.answer("Бот занят, подождите.")
        return
    analysis_cache = { # сброс кэша
        "analysis_results": None, "messages_with_triggers": None,
        "candidates_for_chat_deletion": None, "candidates_for_msg_deletion": None,
        "permanent_whitelist_ids": set(), "is_busy": False,
        "terms": [], "whitelist_names": []
    }
    await message.answer("Кэш анализа очищен.")
    logger.info("aiogram: кэш анализа очищен.")

async def run_analysis_background(chat_id: int, bot_instance: Bot):
    # фоновая задача анализа
    global analysis_cache
    try:
        analysis_cache["terms"] = utils.load_list_from_file(config.TERMS_FILE)
        analysis_cache["whitelist_names"] = utils.load_list_from_file(config.WHITELIST_FILE)
        analysis_cache["permanent_whitelist_ids"] = await analyzer.find_whitelisted_ids(analysis_cache["whitelist_names"])

        # --- Получаем оба результата анализа ---
        analysis_results, messages_with_triggers = await analyzer.analyze_chats_job(
            analysis_cache["terms"],
            analysis_cache["permanent_whitelist_ids"],
            config.FETCH_MESSAGE_LIMIT
        )
        analysis_cache["analysis_results"] = analysis_results
        analysis_cache["messages_with_triggers"] = messages_with_triggers
        # --- ---

        # --- Определение кандидатов на разные действия ---
        candidates_chat_del = []
        candidates_msg_del = {} # {chat_id: msg_count}
        if analysis_results:
            for chat_info in analysis_results:
                 is_whitelisted_by_id = chat_info["id"] in analysis_cache["permanent_whitelist_ids"]
                 is_whitelisted_flag = chat_info.get("is_whitelisted", False)
                 if is_whitelisted_by_id or is_whitelisted_flag:
                     continue # Пропускаем белые списки

                 count = chat_info['count']
                 current_chat_id = chat_info['id']
                 trigger_msg_ids = messages_with_triggers.get(current_chat_id, [])

                 if count > config.DELETION_THRESHOLD:
                     candidates_chat_del.append(chat_info)
                 elif 1 <= count <= config.DELETION_THRESHOLD and trigger_msg_ids:
                     # Кандидат на удаление сообщений, только если есть ID сообщений
                     candidates_msg_del[current_chat_id] = len(trigger_msg_ids)

        analysis_cache["candidates_for_chat_deletion"] = candidates_chat_del
        analysis_cache["candidates_for_msg_deletion"] = candidates_msg_del
        logger.info(f"aiogram: кандидаты на удаление чатов: {len(candidates_chat_del)}")
        logger.info(f"aiogram: кандидаты на удаление сообщений: {len(candidates_msg_del)} чатов ({sum(candidates_msg_del.values())} сообщений)")
        # --- ---

        # --- Генерация отчета (используем candidates_chat_del для подсветки) ---
        report_filepath = utils.generate_html_report(
            analysis_results=analysis_results if analysis_results else [],
            permanent_whitelist_ids=analysis_cache["permanent_whitelist_ids"],
            permanent_whitelist_names=analysis_cache["whitelist_names"],
            candidates_for_deletion=candidates_chat_del, # Передаем только кандидатов на удаление чатов
            final_deleted_ids=set(),
            terms_list=analysis_cache["terms"]
        )

        # --- Формирование итогового сообщения ---
        final_message = "Анализ завершен.\n"
        if candidates_chat_del:
            final_message += f"Найдено <b>{len(candidates_chat_del)}</b> чатов для ПОЛНОГО удаления (>{config.DELETION_THRESHOLD} триггеров).\n"
        if candidates_msg_del:
             total_msgs = sum(candidates_msg_del.values())
             final_message += f"Найдено <b>{len(candidates_msg_del)}</b> чатов для удаления ОТДЕЛЬНЫХ сообщений ({total_msgs} шт.) (1-{config.DELETION_THRESHOLD} триггеров).\n"

        if not candidates_chat_del and not candidates_msg_del:
            final_message += "Чатов/сообщений для удаления по результатам анализа нет.\n"
        else:
             final_message += f"Используйте <code>/delete</code> для просмотра и подтверждения.\n"
        # --- ---

        # Отправка отчета и сообщения
        if report_filepath and os.path.exists(report_filepath):
            try:
                await bot_instance.send_document(chat_id, FSInputFile(report_filepath), caption=final_message)
                logger.info(f"aiogram: отчет {report_filepath} отправлен в чат {chat_id}.")
            except Exception as e:
                 logger.error(f"aiogram: не удалось отправить отчет: {e}")
                 await bot_instance.send_message(chat_id, final_message + "\n\n<i>Не удалось отправить HTML-отчет.</i>")
        else:
             await bot_instance.send_message(chat_id, final_message + "\n\n<i>Не удалось создать или найти HTML-отчет.</i>")

    except ConnectionError as e:
        logger.error(f"ошибка соединения telethon при анализе: {e}")
        await bot_instance.send_message(chat_id, f"<b>Ошибка:</b> Клиент Telethon не активен.\n{html_decoration.quote(str(e))}")
    except Exception as e:
        logger.exception("aiogram: ошибка фонового анализа")
        await bot_instance.send_message(chat_id, f"<b>Ошибка анализа:</b>\n{html_decoration.quote(str(e))}")
    finally:
        analysis_cache["is_busy"] = False

@router.message(Command("analyze"), StateFilter(None))
async def cmd_analyze(message: Message):
    # запуск анализа
    global analysis_cache
    if analysis_cache["is_busy"]:
        await message.answer("Анализ уже запущен.")
        return

    try: get_telethon_client()
    except ConnectionError as e:
        await message.answer(f"<b>Ошибка:</b> Клиент Telethon не активен.\n{html_decoration.quote(str(e))}")
        logger.error(f"запуск /analyze без активного telethon: {e}"); return
    except Exception as e:
         await message.answer(f"<b>Критическая ошибка Telethon:</b>\n{html_decoration.quote(str(e))}")
         logger.error(f"ошибка проверки telethon: {e}"); return

    analysis_cache["is_busy"] = True
    await message.answer("Начинаю анализ через Telethon... Это может занять много времени.\nОтчет придет по завершении.")
    logger.info("aiogram: запущен /analyze")
    asyncio.create_task(run_analysis_background(message.chat.id, bot))