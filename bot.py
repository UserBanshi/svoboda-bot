# bot.py
# основной файл бота

import asyncio
import logging
import os
from telethon import TelegramClient, events, errors, functions
from telethon.tl.types import User, InputUser

# импорт модулей проекта
import config
import utils
import analyzer
import html_generator

# настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('telethon').setLevel(logging.WARNING) # чтобы телетон не спамил в лог
logger = logging.getLogger(__name__)

# --- глобальное состояние бота ---
# (в реальном приложении лучше использовать базу данных или более надежное хранилище)
bot_state = {
    "analysis_results": None,         # результаты последнего анализа []
    "candidates_for_deletion": None,  # чаты, превысившие порог []
    "permanent_whitelist_ids": set(), # id из файла whitelist.txt
    "is_busy": False,                 # флаг, что бот занят анализом/удалением
    "pending_chat_deletion": None,    # список чатов, ожидающих подтверждения удаления
    "pending_contact_deletion": None, # список контактов, ожидающих подтверждения удаления
}

# --- инициализация клиента ---
client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)

# --- обработчики команд ---

@client.on(events.NewMessage(pattern='/start', from_users='me'))
async def start_handler(event):
    """обработчик команды /start"""
    await event.respond(
        "**SVOBODA Bot**\n\n"
        "Команды:\n"
        "`/analyze` - Запустить анализ чатов и создать отчет.\n"
        "`/delete` - Показать чаты для удаления (по результатам `/analyze`) и запросить подтверждение.\n"
        "`/deletecontacts` - Показать контакты для удаления (кроме белого списка) и запросить подтверждение.\n"
        "`/clearcache` - Очистить результаты последнего анализа.\n"
        "`/help` - Показать это сообщение.\n\n"
        "**ВНИМАНИЕ:** Команды `/delete` и `/deletecontacts` выполняют необратимые действия!"
    )

@client.on(events.NewMessage(pattern='/help', from_users='me'))
async def help_handler(event):
    """обработчик команды /help"""
    await start_handler(event) # просто вызываем /start

@client.on(events.NewMessage(pattern='/clearcache', from_users='me'))
async def clear_cache_handler(event):
    """очищает сохраненные результаты анализа."""
    if bot_state["is_busy"]:
        await event.respond("Бот занят, подождите завершения текущей операции.")
        return
    bot_state["analysis_results"] = None
    bot_state["candidates_for_deletion"] = None
    bot_state["pending_chat_deletion"] = None
    bot_state["pending_contact_deletion"] = None
    await event.respond("Кэш результатов анализа очищен.")
    logger.info("кэш анализа очищен по команде.")


@client.on(events.NewMessage(pattern='/analyze', from_users='me'))
async def analyze_handler(event):
    """запускает анализ чатов."""
    if bot_state["is_busy"]:
        await event.respond("Анализ уже запущен или выполняется другая операция.")
        return

    bot_state["is_busy"] = True
    await event.respond("Начинаю анализ... Это может занять много времени.\nЯ сообщу о завершении и пришлю отчет.")
    logger.info("запущен анализ по команде /analyze")

    try:
        # 1. загрузка списков
        terms = utils.load_list_from_file(config.TERMS_FILE)
        whitelist_names = utils.load_list_from_file(config.WHITELIST_FILE)

        # 2. поиск id из белого списка
        bot_state["permanent_whitelist_ids"] = await analyzer.find_whitelisted_ids(client, whitelist_names)

        # 3. анализ чатов
        analysis_results = await analyzer.analyze_chats(
            client,
            terms,
            bot_state["permanent_whitelist_ids"],
            config.FETCH_MESSAGE_LIMIT
        )
        bot_state["analysis_results"] = analysis_results

        # 4. определение кандидатов на удаление
        candidates = []
        if analysis_results:
            for chat_info in analysis_results:
                # кандидат = больше порога и не в постоянном белом списке
                is_whitelisted = chat_info.get("is_whitelisted", False) or \
                                 (isinstance(chat_info["entity"], User) and chat_info["entity"].id in bot_state["permanent_whitelist_ids"])

                if chat_info['count'] > config.DELETION_THRESHOLD and not is_whitelisted:
                    candidates.append(chat_info)
        bot_state["candidates_for_deletion"] = candidates
        logger.info(f"найдено кандидатов на удаление чатов: {len(candidates)}")

        # 5. генерация и отправка отчета
        report_filename = html_generator.generate_html_report(
            analysis_results=analysis_results if analysis_results else [],
            permanent_whitelist_ids=bot_state["permanent_whitelist_ids"],
            permanent_whitelist_names=whitelist_names,
            candidates_for_deletion=candidates,
            final_deleted_ids=set(), # пока ничего не удалено
            terms_list=terms
        )

        final_message = "Анализ завершен.\n"
        if candidates:
            final_message += f"Найдено **{len(candidates)}** чатов с числом триггеров > {config.DELETION_THRESHOLD}.\n"
            final_message += f"Используйте команду `/delete` для просмотра списка и возможного удаления.\n"
        else:
            final_message += f"Чатов с числом триггеров > {config.DELETION_THRESHOLD} не найдено.\n"

        if report_filename and os.path.exists(report_filename):
            try:
                await event.respond(final_message, file=report_filename)
                logger.info(f"отчет {report_filename} отправлен.")
                # os.remove(report_filename) # можно удалить файл после отправки
            except Exception as e:
                 logger.error(f"не удалось отправить файл отчета: {e}")
                 await event.respond(final_message + "\n\n*Не удалось отправить HTML-отчет.*")
        else:
             await event.respond(final_message + "\n\n*Не удалось создать или найти HTML-отчет.*")

    except Exception as e:
        logger.exception("ошибка во время выполнения /analyze")
        await event.respond(f"Произошла ошибка во время анализа: {e}")
    finally:
        bot_state["is_busy"] = False


@client.on(events.NewMessage(pattern='/delete', from_users='me'))
async def delete_handler(event):
    """показывает кандидатов на удаление и инициирует процесс."""
    if bot_state["is_busy"]:
        await event.respond("Бот занят, подождите завершения.")
        return
    if bot_state["analysis_results"] is None:
        await event.respond("Сначала нужно выполнить анализ. Используйте команду `/analyze`.")
        return
    if not bot_state["candidates_for_deletion"]:
        await event.respond(f"Кандидатов на удаление (триггеров > {config.DELETION_THRESHOLD}) по результатам последнего анализа нет.")
        return

    candidates = bot_state["candidates_for_deletion"]
    bot_state["pending_chat_deletion"] = candidates # сохраняем для подтверждения

    response = f"**Кандидаты на удаление ({len(candidates)} чатов):**\n\n"
    for idx, chat in enumerate(candidates):
        triggers_str = ', '.join(sorted(list(chat['found_triggers'])))[:100] # обрезаем для краткости
        response += f"{idx + 1}. **{chat['title']}** (ID: `{chat['id']}`)\n"
        response += f"   Триггеров: {chat['count']}, Найдено: _{triggers_str}_\n"

    response += f"\n**ВНИМАНИЕ!** Удаление чатов необратимо!\n"
    response += f"Для подтверждения удаления **всех** чатов из списка выше, отправьте ТОЧНО следующую фразу:\n\n`{config.CHAT_DELETION_CONFIRMATION_PHRASE}`\n\n"
    response += "Любое другое сообщение отменит операцию."

    await event.respond(response)
    logger.info(f"запрошено подтверждение на удаление {len(candidates)} чатов.")


@client.on(events.NewMessage(pattern=config.CHAT_DELETION_CONFIRMATION_PHRASE, from_users='me'))
async def delete_confirm_handler(event):
    """обрабатывает подтверждение удаления чатов."""
    if bot_state["is_busy"]:
        await event.respond("Бот занят, подождите.")
        return
    if not bot_state["pending_chat_deletion"]:
        # await event.respond("Нет чатов, ожидающих подтверждения удаления.") # можно раскомментировать для отладки
        return # игнорируем, если не было запроса

    chats_to_delete = bot_state["pending_chat_deletion"]
    bot_state["pending_chat_deletion"] = None # очищаем сразу
    bot_state["is_busy"] = True
    logger.warning(f"получено подтверждение на удаление {len(chats_to_delete)} чатов. Начинаю удаление...")
    await event.respond(f"Подтверждение получено. Начинаю удаление {len(chats_to_delete)} чатов...")

    deleted_count = 0
    failed_count = 0
    deleted_ids = set()

    for chat_info in chats_to_delete:
        chat_id = chat_info['id']
        title = chat_info['title']
        try:
            await client.delete_dialog(chat_id)
            logger.info(f"успешно удален диалог: {title} (id: {chat_id})")
            await event.respond(f"Удален: {title}", parse_mode=None) # parse_mode=None на случай спецсимволов в названии
            deleted_count += 1
            deleted_ids.add(chat_id)
            await asyncio.sleep(1.2) # пауза между удалениями
        except errors.FloodWaitError as e:
            logger.error(f"floodwait при удалении {title}. жду {e.seconds} сек.")
            await event.respond(f"Слишком часто! Жду {e.seconds} сек перед продолжением...")
            await asyncio.sleep(e.seconds + 1)
            # пробуем удалить еще раз после паузы (не обязательно)
            try:
                await client.delete_dialog(chat_id)
                logger.info(f"успешно удален диалог (повторно): {title} (id: {chat_id})")
                await event.respond(f"Удален (повторно): {title}", parse_mode=None)
                deleted_count += 1
                deleted_ids.add(chat_id)
                await asyncio.sleep(1.2)
            except Exception as e_retry:
                 logger.error(f"ошибка при повторном удалении {title} (id: {chat_id}): {e_retry}")
                 await event.respond(f"Ошибка при повторном удалении: {title} - {e_retry}")
                 failed_count += 1
        except Exception as e:
            logger.error(f"ошибка при удалении {title} (id: {chat_id}): {e}")
            await event.respond(f"Ошибка при удалении: {title} - {e}")
            failed_count += 1
            await asyncio.sleep(0.5) # небольшая пауза после ошибки

    # обновить отчет после удаления
    if bot_state["analysis_results"]:
        logger.info("обновление html-отчета после удаления чатов...")
        whitelist_names = utils.load_list_from_file(config.WHITELIST_FILE) # перезагружаем на всякий случай
        terms = utils.load_list_from_file(config.TERMS_FILE)
        report_filename = html_generator.generate_html_report(
             analysis_results=bot_state["analysis_results"],
             permanent_whitelist_ids=bot_state["permanent_whitelist_ids"],
             permanent_whitelist_names=whitelist_names,
             candidates_for_deletion=bot_state["candidates_for_deletion"] if bot_state["candidates_for_deletion"] else [],
             final_deleted_ids=deleted_ids, # передаем реально удаленные
             terms_list=terms
        )
        final_report_msg = f"Удаление чатов завершено.\nУдалено: {deleted_count}\nОшибок: {failed_count}\nОбновленный отчет:"
        if report_filename and os.path.exists(report_filename):
             try:
                 await event.respond(final_report_msg, file=report_filename)
             except Exception as e:
                 logger.error(f"не удалось отправить обновленный отчет: {e}")
                 await event.respond(final_report_msg + "\n*Не удалось отправить файл отчета.*")
        else:
             await event.respond(final_report_msg + "\n*Не удалось создать обновленный отчет.*")
    else:
         await event.respond(f"Удаление чатов завершено.\nУдалено: {deleted_count}\nОшибок: {failed_count}")

    bot_state["is_busy"] = False
    # очищаем кандидатов после попытки удаления
    bot_state["candidates_for_deletion"] = []
    logger.warning("удаление чатов завершено.")


@client.on(events.NewMessage(pattern='/deletecontacts', from_users='me'))
async def delete_contacts_handler(event):
    """инициирует удаление контактов (кроме белого списка)."""
    if bot_state["is_busy"]:
        await event.respond("Бот занят, подождите.")
        return

    bot_state["is_busy"] = True
    await event.respond("Получаю список контактов...")
    logger.info("запрошено удаление контактов (/deletecontacts)")

    try:
        # получаем id из белого списка, если его нет в кэше
        if not bot_state["permanent_whitelist_ids"]:
             whitelist_names = utils.load_list_from_file(config.WHITELIST_FILE)
             bot_state["permanent_whitelist_ids"] = await analyzer.find_whitelisted_ids(client, whitelist_names)

        contacts = await client(functions.contacts.GetContactsRequest(hash=0))
        if not hasattr(contacts, 'users'):
             await event.respond("Не удалось получить список контактов.")
             logger.warning("не удалось получить список контактов для удаления.")
             bot_state["is_busy"] = False
             return

        contacts_to_delete = []
        for user in contacts.users:
            # удаляем только реальных пользователей (не ботов, не удаленных), которые не в белом списке
            if isinstance(user, User) and not user.is_self and not user.bot and not user.deleted:
                if user.id not in bot_state["permanent_whitelist_ids"]:
                    contacts_to_delete.append(user)

        if not contacts_to_delete:
            await event.respond("Не найдено контактов для удаления (все контакты в белом списке или список контактов пуст).")
            logger.info("не найдено контактов для удаления.")
            bot_state["is_busy"] = False
            return

        bot_state["pending_contact_deletion"] = contacts_to_delete # сохраняем для подтверждения

        response = f"**Найдено {len(contacts_to_delete)} контактов для удаления (НЕ из белого списка):**\n\n"
        for idx, user in enumerate(contacts_to_delete[:20]): # показываем только первые 20 для краткости
            display_name = await utils.get_user_display_name(user)
            username = f"(@{user.username})" if user.username else ""
            response += f"{idx + 1}. **{display_name}** {username} (ID: `{user.id}`)\n"
        if len(contacts_to_delete) > 20:
            response += f"... и еще {len(contacts_to_delete) - 20}\n"

        response += f"\n**!!! ВНИМАНИЕ !!!** Удаление контактов **НЕОБРАТИМО**!\n"
        response += f"Вы потеряете их из своего списка контактов навсегда (если только не добавите снова вручную).\n"
        response += f"Для подтверждения удаления **всех** контактов из списка выше ({len(contacts_to_delete)} шт.), отправьте ТОЧНО следующую фразу:\n\n`{config.CONTACT_DELETION_CONFIRMATION_PHRASE}`\n\n"
        response += "Любое другое сообщение отменит операцию."

        await event.respond(response)
        logger.warning(f"запрошено подтверждение на удаление {len(contacts_to_delete)} контактов.")

    except Exception as e:
        logger.exception("ошибка при получении контактов для удаления")
        await event.respond(f"Произошла ошибка при получении контактов: {e}")
    finally:
         # освобождаем бота, даже если была ошибка, чтобы не завис
         if bot_state["pending_contact_deletion"] is None: # если не дошли до сохранения кандидатов
             bot_state["is_busy"] = False


@client.on(events.NewMessage(pattern=config.CONTACT_DELETION_CONFIRMATION_PHRASE, from_users='me'))
async def delete_contacts_confirm_handler(event):
    """обрабатывает подтверждение удаления контактов."""
    if bot_state["is_busy"] and bot_state["pending_contact_deletion"] is None: # проверяем, что бот не занят чем-то другим
        await event.respond("Бот занят другой операцией.")
        return
    if not bot_state["pending_contact_deletion"]:
        # await event.respond("Нет контактов, ожидающих подтверждения удаления.")
        return # игнорируем

    contacts_to_delete = bot_state["pending_contact_deletion"]
    bot_state["pending_contact_deletion"] = None # очищаем
    # is_busy уже должен быть True с предыдущего шага
    logger.warning(f"!!! ПОЛУЧЕНО ПОДТВЕРЖДЕНИЕ НА УДАЛЕНИЕ {len(contacts_to_delete)} КОНТАКТОВ !!! Начинаю...")
    await event.respond(f"Подтверждение получено. Начинаю **НЕОБРАТИМОЕ** удаление {len(contacts_to_delete)} контактов...")

    deleted_count = 0
    failed_count = 0

    # готовим список InputUser для запроса
    input_users_to_delete = []
    for user in contacts_to_delete:
        try:
            # получаем InputUser - это важно для DeleteContactsRequest
            input_user = await client.get_input_entity(user.id)
            if isinstance(input_user, InputUser):
                 input_users_to_delete.append(input_user)
            else:
                 logger.warning(f"не удалось получить inputuser для {user.id}, пропускаю.")
                 failed_count += 1
        except ValueError as e: # может возникнуть, если юзер уже не доступен
             logger.warning(f"не удалось получить inputuser для {user.id} (возможно, удален): {e}")
             failed_count += 1
        except Exception as e:
             logger.error(f"ошибка get_input_entity для {user.id}: {e}")
             failed_count += 1

    if not input_users_to_delete:
         await event.respond("Не удалось подготовить список контактов для удаления (возможно, все уже недоступны).")
         logger.warning("список input_users_to_delete пуст.")
         bot_state["is_busy"] = False
         return

    # удаляем пачками, если их много (telegram может иметь лимиты на размер запроса)
    chunk_size = 100
    for i in range(0, len(input_users_to_delete), chunk_size):
        chunk = input_users_to_delete[i:i + chunk_size]
        logger.info(f"удаляю пачку контактов: {len(chunk)} шт.")
        try:
            await client(functions.contacts.DeleteContactsRequest(id=chunk))
            logger.info(f"пачка контактов удалена.")
            deleted_count += len(chunk)
            await event.respond(f"Удалена пачка из {len(chunk)} контактов...")
            await asyncio.sleep(1.5) # пауза между пачками
        except errors.FloodWaitError as e:
            logger.error(f"floodwait при удалении пачки контактов. жду {e.seconds} сек.")
            await event.respond(f"Слишком часто! Жду {e.seconds} сек перед следующей пачкой...")
            await asyncio.sleep(e.seconds + 1)
             # повторная попытка для этой же пачки (не обязательно)
            try:
                await client(functions.contacts.DeleteContactsRequest(id=chunk))
                logger.info(f"пачка контактов удалена (повторно).")
                deleted_count += len(chunk)
                await event.respond(f"Удалена пачка из {len(chunk)} контактов (повторно)...")
                await asyncio.sleep(1.5)
            except Exception as e_retry:
                 logger.error(f"ошибка при повторном удалении пачки контактов: {e_retry}")
                 await event.respond(f"Ошибка при повторном удалении пачки: {e_retry}")
                 failed_count += len(chunk) # считаем всю пачку как неудавшуюся
        except Exception as e:
            logger.error(f"ошибка при удалении пачки контактов: {e}")
            await event.respond(f"Ошибка при удалении пачки контактов: {e}")
            failed_count += len(chunk) # считаем всю пачку как неудавшуюся
            await asyncio.sleep(0.5)

    await event.respond(f"Удаление контактов завершено.\nУспешно удалено: {deleted_count}\nНе удалось удалить (ошибки/пропущено): {failed_count}")
    bot_state["is_busy"] = False
    logger.warning("удаление контактов завершено.")


# --- обработчик любых других сообщений от себя (для отмены операций) ---
@client.on(events.NewMessage(from_users='me'))
async def cancel_handler(event):
    """отменяет ожидание подтверждения, если пришло не то сообщение."""
    # проверяем, было ли ожидание и не является ли сообщение командой или фразой подтверждения
    is_command = event.text.startswith('/')
    is_chat_confirm = event.text == config.CHAT_DELETION_CONFIRMATION_PHRASE
    is_contact_confirm = event.text == config.CONTACT_DELETION_CONFIRMATION_PHRASE

    if bot_state["pending_chat_deletion"] and not is_command and not is_chat_confirm:
        bot_state["pending_chat_deletion"] = None
        if bot_state["is_busy"]: bot_state["is_busy"] = False # освобождаем, если ждали подтверждения
        await event.respond("Подтверждение не получено. Операция удаления чатов отменена.")
        logger.info("удаление чатов отменено из-за другого сообщения.")

    if bot_state["pending_contact_deletion"] and not is_command and not is_contact_confirm:
        bot_state["pending_contact_deletion"] = None
        if bot_state["is_busy"]: bot_state["is_busy"] = False # освобождаем
        await event.respond("Подтверждение не получено. Операция удаления контактов отменена.")
        logger.info("удаление контактов отменено из-за другого сообщения.")


# --- запуск бота ---
async def run_bot():
    """основная функция запуска."""
    logger.info("запуск бота...")
    # проверка наличия файлов
    for f in [config.TERMS_FILE, config.WHITELIST_FILE]:
        if not os.path.exists(f):
            logger.warning(f"файл {f} не найден. создаю пустой.")
            try: open(f, 'a', encoding='utf-8').close()
            except OSError as e: logger.error(f"не удалось создать {f}: {e}")

    # подключаемся и авторизуемся
    try:
        await client.start(phone=lambda: input("введите номер телефона: "),
                           code_callback=lambda: input("введите код из telegram: "))
        me = await client.get_me()
        logger.info(f"бот запущен и авторизован как: {me.first_name} (@{me.username}) id: {me.id}")
        await client.send_message('me', "**SVOBODA Bot запущен.**\nОтправьте `/help` для списка команд.")
    except errors.AuthKeyError:
         logger.error("ключ авторизации недействителен. удалите .session файл и перезапустите.")
         print("\n!!! Ошибка авторизации. Ключ недействителен.")
         print("!!! Удалите файл .session и запустите скрипт заново.")
         if os.path.exists(config.SESSION_NAME + ".session"):
             try: os.remove(config.SESSION_NAME + ".session"); logger.info("удален недействительный .session")
             except OSError as e: logger.error(f"не удалось удалить .session: {e}")
         return # выходим, если авторизация не удалась
    except Exception as e:
        logger.exception("непредвиденная ошибка при запуске:")
        print(f"критическая ошибка при запуске: {e}")
        return

    # запускаем цикл обработки событий
    logger.info("бот готов к приему команд от вас.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run_bot())