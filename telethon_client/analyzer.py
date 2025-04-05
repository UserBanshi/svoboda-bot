# telethon_client/analyzer.py
import asyncio
import logging
from telethon import errors, functions
from telethon.tl.types import User, Message as TelethonMessage

from .client_instance import get_telethon_client
from .utils import get_entity_title, clean_text_for_matching, get_user_display_name


logger = logging.getLogger(__name__)

async def find_whitelisted_ids(whitelist_names):
    # ищет id пользователей из белого списка имен (без изменений)
    client = get_telethon_client()
    whitelisted_user_ids = set()
    if not whitelist_names: return whitelisted_user_ids
    try:
        contacts = await client(functions.contacts.GetContactsRequest(hash=0))
        if hasattr(contacts, 'users'):
            for user in contacts.users:
                if isinstance(user, User):
                    display_name = await get_user_display_name(user)
                    username = f"@{user.username.lower()}" if user.username else ""
                    if display_name in whitelist_names or (username and username in whitelist_names):
                        whitelisted_user_ids.add(user.id)
                        name_found = display_name if display_name in whitelist_names else username
                        logger.info(f"telethon: найден контакт в белом списке: {name_found} (id: {user.id})")
        logger.info(f"telethon: найдено id в постоянном белом списке: {len(whitelisted_user_ids)}")
    except Exception as e:
        logger.error(f"telethon: ошибка при получении контактов: {e}")
    return whitelisted_user_ids


async def analyze_chats_job(terms, whitelist_ids, fetch_limit):
    # основная функция анализа чатов (возвращает упрощенный список + ID сообщений)
    client = get_telethon_client()
    chat_analysis = [] # список для результатов по чатам
    messages_with_triggers = {} # Словарь {chat_id: [msg_id1, msg_id2, ...]}
    dialog_count = 0
    skipped_dialogs = 0
    processed_chats = 0
    logger.info("telethon: начинаю парсинг диалогов и сообщений (с поиском ID сообщений)...")
    try:
        async for dialog in client.iter_dialogs(limit=None):
            dialog_count += 1
            entity = dialog.entity
            title = await get_entity_title(entity)
            chat_id = dialog.id

            is_self_chat = isinstance(entity, User) and entity.is_self
            if is_self_chat:
                skipped_dialogs += 1; continue

            is_whitelisted_by_id = isinstance(entity, User) and entity.id in whitelist_ids
            if is_whitelisted_by_id:
                 logger.info(f"telethon: чат с '{title}' (id: {chat_id}) в белом списке.")
                 chat_analysis.append({
                     "id": chat_id, "title": title, "count": 0, "message_count": 0,
                     "found_triggers": [], "is_whitelisted": True
                 })
                 skipped_dialogs += 1; continue

            logger.info(f"telethon: анализирую чат ({dialog_count}): {title} (id: {chat_id})")
            processed_chats += 1
            term_count, message_count = 0, 0
            found_triggers_in_chat = set()
            trigger_message_ids_in_chat = []

            try:
                async for message in client.iter_messages(chat_id, limit=fetch_limit):
                    message_count += 1
                    message_found_trigger = False #
                    text_to_check = ""
                    if isinstance(message, TelethonMessage):
                        if message.text: text_to_check += message.text + " "
                        if message.media and hasattr(message, 'caption') and message.caption: text_to_check += message.caption

                    if text_to_check and terms:
                        cleaned_text = clean_text_for_matching(text_to_check)
                        words_in_message = set(cleaned_text.split())
                        for term in terms:
                            if term in words_in_message:
                                term_count += 1
                                found_triggers_in_chat.add(term)
                                message_found_trigger = True # Помечаем сообщение


                    if message_found_trigger:
                        trigger_message_ids_in_chat.append(message.id)


                    if message_count % 500 == 0: await asyncio.sleep(0.05)

                chat_analysis.append({
                    "id": chat_id, "title": title, "count": term_count,
                    "message_count": message_count, "found_triggers": list(found_triggers_in_chat),
                    "is_whitelisted": False

                })

                if trigger_message_ids_in_chat:
                    messages_with_triggers[chat_id] = trigger_message_ids_in_chat

                logger.info(f"telethon: чат '{title}': найдено {term_count} триггеров в {len(trigger_message_ids_in_chat)} сообщениях (всего: {message_count}).")

            except errors.FloodWaitError as e:
                 logger.warning(f"telethon: floodwait для '{title}'. ждем {e.seconds}с.")
                 await asyncio.sleep(e.seconds + 1)
                 chat_analysis.append({"id": chat_id, "title": title, "count": term_count, "message_count": message_count, "found_triggers": list(found_triggers_in_chat), "is_whitelisted": False})
                 if trigger_message_ids_in_chat: messages_with_triggers[chat_id] = trigger_message_ids_in_chat # Сохраняем что успели
            except (errors.ChannelPrivateError, errors.ChatForbiddenError):
                 logger.warning(f"telethon: нет доступа к '{title}'.")
                 skipped_dialogs += 1; chat_analysis.append({"id": chat_id, "title": title, "count": 0, "message_count": 0, "found_triggers": [], "is_whitelisted": False})
            except Exception as e:
                logger.error(f"telethon: не удалось прочитать '{title}': {e}.")
                skipped_dialogs += 1; chat_analysis.append({"id": chat_id, "title": title, "count": 0, "message_count": 0, "found_triggers": [], "is_whitelisted": False})

            await asyncio.sleep(0.1)

    except errors.FloodWaitError as e:
        logger.error(f"telethon: floodwait при получении диалогов. ждем {e.seconds}с...")
        await asyncio.sleep(e.seconds + 1)
    except Exception as e:
        logger.error(f"telethon: критическая ошибка парсинга диалогов: {e}", exc_info=True)

    logger.info(f"telethon: анализ завершен. проанализировано: {processed_chats}. пропущено: {skipped_dialogs}.")
    # Возвращаем ОБА результата
    return chat_analysis, messages_with_triggers