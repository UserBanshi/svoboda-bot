# telethon_client/actions.py
import asyncio
import logging
from telethon import errors, functions
from telethon.tl.types import User, InputUser, InputPeerUser

from .client_instance import get_telethon_client
from .utils import get_user_display_name, get_entity_title

logger = logging.getLogger(__name__)


async def delete_chats_job(chat_ids_to_delete: list[int], status_callback=None):

    client = get_telethon_client()
    deleted_count = 0
    failed_count = 0
    deleted_ids = set()
    total = len(chat_ids_to_delete)
    logger.warning(f"telethon: начинаю удаление {total} чатов...")
    for i, chat_id in enumerate(chat_ids_to_delete):
        title = f"ID {chat_id}"
        try:
            try:
                 entity = await client.get_entity(chat_id)
                 title = await get_entity_title(entity)
            except Exception as title_err: logger.debug(f"не удалось получить title для {chat_id}: {title_err}")
            await client.delete_dialog(chat_id)
            logger.info(f"telethon: удален диалог: {title} (id: {chat_id})")
            deleted_count += 1; deleted_ids.add(chat_id)
            if status_callback: await status_callback(f"Удален ({i+1}/{total}): {title}")
            await asyncio.sleep(1.2)
        except errors.FloodWaitError as e:
            logger.error(f"telethon: floodwait при удалении {title}. жду {e.seconds}с.")
            if status_callback: await status_callback(f"FloodWait! Жду {e.seconds} сек...")
            await asyncio.sleep(e.seconds + 1)
            try: # Повтор
                await client.delete_dialog(chat_id)
                logger.info(f"telethon: удален (повторно): {title} (id: {chat_id})")
                deleted_count += 1; deleted_ids.add(chat_id)
                if status_callback: await status_callback(f"Удален ({i+1}/{total}) (повторно): {title}")
                await asyncio.sleep(1.2)
            except Exception as e_retry:
                logger.error(f"telethon: ошибка повторного удаления {title}: {e_retry}")
                failed_count += 1
                if status_callback: await status_callback(f"Ошибка повторного удаления: {title}")
        except Exception as e:
            logger.error(f"telethon: ошибка удаления {title}: {e}")
            failed_count += 1
            if status_callback: await status_callback(f"Ошибка удаления: {title} - {type(e).__name__}")
            await asyncio.sleep(0.5)
    logger.warning(f"telethon: удаление чатов завершено. удалено: {deleted_count}, ошибок: {failed_count}")
    return {"deleted": deleted_count, "failed": failed_count, "deleted_ids": deleted_ids}



async def delete_messages_job(messages_to_delete: dict[int, list[int]], status_callback=None):
    """
    Удаляет указанные сообщения.
    messages_to_delete: Словарь {chat_id: [msg_id1, msg_id2, ...]}
    """
    client = get_telethon_client()
    deleted_count = 0
    failed_count = 0
    total_messages = sum(len(ids) for ids in messages_to_delete.values())
    processed_messages = 0
    logger.warning(f"telethon: начинаю удаление {total_messages} сообщений в {len(messages_to_delete)} чатах...")

    for chat_id, message_ids in messages_to_delete.items():
        if not message_ids: continue
        chat_title = f"ID {chat_id}"
        try: # Пытаемся получить название чата для лога
            entity = await client.get_entity(chat_id)
            chat_title = await get_entity_title(entity)
        except Exception as title_err:
            logger.debug(f"не удалось получить title для {chat_id} при удалении сообщений: {title_err}")

        logger.info(f"telethon: удаляю {len(message_ids)} сообщений в чате '{chat_title}' (id: {chat_id})...")
        # Удаляем сообщения пачками по 100 (лимит Telegram)
        chunk_size = 100
        chat_deleted_count = 0
        chat_failed_count = 0
        for i in range(0, len(message_ids), chunk_size):
            chunk_ids = message_ids[i:i + chunk_size]
            processed_messages += len(chunk_ids)
            progress = f"({processed_messages}/{total_messages})"
            try:
                # revoke=True удаляет для всех, если есть права (например, в своих сообщениях или как админ)
                # Если прав нет, удалит только у себя.
                await client.delete_messages(chat_id, chunk_ids, revoke=True)
                logger.debug(f"telethon: удалена пачка {len(chunk_ids)} сообщений в {chat_title} {progress}")
                deleted_count += len(chunk_ids)
                chat_deleted_count += len(chunk_ids)
                if status_callback:
                    # Не спамим на каждую пачку, сообщим итог по чату
                    pass
                await asyncio.sleep(0.8) # Небольшая пауза между пачками

            except errors.FloodWaitError as e:
                logger.error(f"telethon: floodwait при удалении сообщений в {chat_title}. жду {e.seconds}с.")
                if status_callback: await status_callback(f"FloodWait в '{chat_title}'! Жду {e.seconds} сек...")
                await asyncio.sleep(e.seconds + 1)
                # Повтор пачки
                try:
                    await client.delete_messages(chat_id, chunk_ids, revoke=True)
                    logger.debug(f"telethon: удалена пачка (повторно) {len(chunk_ids)} в {chat_title} {progress}")
                    deleted_count += len(chunk_ids)
                    chat_deleted_count += len(chunk_ids)
                    await asyncio.sleep(0.8)
                except Exception as e_retry:
                    logger.error(f"telethon: ошибка повторного удаления сообщений в {chat_title}: {e_retry}")
                    failed_count += len(chunk_ids) # Считаем всю пачку ошибкой
                    chat_failed_count += len(chunk_ids)
                    if status_callback: await status_callback(f"Ошибка повторного удаления в '{chat_title}'!")

            except errors.MessageDeleteForbiddenError:
                # Частая ошибка: нет прав удалять чужие сообщения или сообщение слишком старое
                logger.warning(f"telethon: нет прав на удаление сообщений (или старые) в '{chat_title}'. Пропускаю пачку.")
                failed_count += len(chunk_ids)
                chat_failed_count += len(chunk_ids)
                if status_callback:
                    await status_callback(f"Нет прав/старые сообщения в '{chat_title}' ({len(chunk_ids)} шт).")
                await asyncio.sleep(0.2) # Пауза после ошибки прав
            except Exception as e:
                logger.error(f"telethon: ошибка удаления сообщений в {chat_title}: {e}")
                failed_count += len(chunk_ids)
                chat_failed_count += len(chunk_ids)
                if status_callback:
                    await status_callback(f"Ошибка удаления в '{chat_title}': {type(e).__name__}")
                await asyncio.sleep(0.5)

        # Сообщаем итог по чату
        if status_callback:
            await status_callback(f"Чат '{chat_title}': удалено {chat_deleted_count}, ошибок {chat_failed_count}")

    logger.warning(f"telethon: удаление сообщений завершено. удалено: {deleted_count}, ошибок: {failed_count}")
    # Возвращаем статистику, ID удаленных сообщений не храним детально
    return {"deleted": deleted_count, "failed": failed_count}

# --- Функция delete_contacts_job БЕЗ ИЗМЕНЕНИЙ ---
async def delete_contacts_job(contacts_to_delete: list[User], status_callback=None):

    client = get_telethon_client()
    deleted_count = 0
    failed_count = 0
    total = len(contacts_to_delete)
    logger.warning(f"telethon: !!! Начинаю НЕОБРАТИМОЕ удаление {total} контактов !!!")
    input_users_to_delete = []
    skipped_input_users = 0
    logger.info("telethon: преобразую User в InputUser/InputPeerUser...")
    for user in contacts_to_delete:
        display_name = await get_user_display_name(user)
        try:
            input_entity = await client.get_input_entity(user.id)
            if isinstance(input_entity, (InputUser, InputPeerUser)):
                 input_users_to_delete.append(input_entity)
            else:
                 logger.warning(f"telethon: не получить InputUser/InputPeerUser для {display_name} ({user.id}). Тип: {type(input_entity)}")
                 skipped_input_users += 1
        except ValueError as e: logger.warning(f"telethon: ValueError get_input_entity {display_name} ({user.id}): {e}"); skipped_input_users += 1
        except Exception as e: logger.error(f"telethon: ошибка get_input_entity {display_name} ({user.id}): {type(e).__name__} - {e}"); skipped_input_users += 1
    failed_count += skipped_input_users
    total_to_request = len(input_users_to_delete)
    logger.info(f"telethon: готово к удалению (запрос): {total_to_request} контактов.")
    if status_callback: await status_callback(f"Подготовлено: {total_to_request} (пропущено: {skipped_input_users}). Начинаю...")
    if not input_users_to_delete:
         logger.warning("telethon: нет контактов для запроса на удаление.")
         return {"deleted": 0, "failed": failed_count}
    chunk_size = 100
    for i in range(0, total_to_request, chunk_size):
        chunk = input_users_to_delete[i:i + chunk_size]; current_chunk_num = (i // chunk_size) + 1; total_chunks = (total_to_request + chunk_size - 1) // chunk_size
        logger.info(f"telethon: удаляю пачку {current_chunk_num}/{total_chunks} ({len(chunk)} шт.)...")
        if status_callback: await status_callback(f"Удаляю пачку {current_chunk_num}/{total_chunks} ({len(chunk)} шт)...")
        try:
            await client(functions.contacts.DeleteContactsRequest(id=chunk)); logger.info(f"telethon: пачка {current_chunk_num} удалена.")
            deleted_count += len(chunk); await asyncio.sleep(1.5)
        except errors.FloodWaitError as e:
            logger.error(f"telethon: floodwait пачка {current_chunk_num}. жду {e.seconds}с."); await asyncio.sleep(e.seconds + 1)
            if status_callback: await status_callback(f"FloodWait пачка {current_chunk_num}! Жду {e.seconds} сек...")
            try: # Повтор
                await client(functions.contacts.DeleteContactsRequest(id=chunk)); logger.info(f"telethon: пачка {current_chunk_num} удалена (повторно).")
                deleted_count += len(chunk); await asyncio.sleep(1.5)
            except Exception as e_retry: logger.error(f"telethon: ошибка повтора пачки {current_chunk_num}: {e_retry}"); failed_count += len(chunk); await status_callback(f"Ошибка повтора пачки {current_chunk_num}!")
        except Exception as e: logger.error(f"telethon: ошибка пачки {current_chunk_num}: {e}"); failed_count += len(chunk); await status_callback(f"Ошибка пачки {current_chunk_num}: {type(e).__name__}"); await asyncio.sleep(0.5)
    logger.warning(f"telethon: удаление контактов завершено. удалено: {deleted_count}, ошибок/пропущено: {failed_count}")
    return {"deleted": deleted_count, "failed": failed_count}


# --- Функция get_contacts_for_deletion БЕЗ ИЗМЕНЕНИЙ ---
async def get_contacts_for_deletion(whitelist_ids: set):

    client = get_telethon_client()
    contacts_to_delete = []
    try:
        contacts = await client(functions.contacts.GetContactsRequest(hash=0))
        if hasattr(contacts, 'users'):
            for user in contacts.users:
                if isinstance(user, User) and not user.is_self and not user.bot and not user.deleted:
                    if user.id not in whitelist_ids:
                        contacts_to_delete.append(user)
        logger.info(f"telethon: найдено контактов для возможного удаления: {len(contacts_to_delete)}")
        return contacts_to_delete
    except Exception as e:
        logger.error(f"telethon: ошибка при получении контактов для удаления: {e}")
        return []