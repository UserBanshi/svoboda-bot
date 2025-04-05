import asyncio
import os
import logging
import re
import string
from telethon import TelegramClient, errors, functions
from telethon.tl.types import Dialog, Channel, Chat, User

# --- НАСТРОЙКИ ---
API_ID = 24498155# Замени на свой API ID
API_HASH = 'bc6e31f84a075cec12c0dbf661833d0'  # Замени на свой API Hash
SESSION_NAME = 'svoboda' # Имя файла сессии

TERMS_FILE = 'terms.txt'
WHITELIST_FILE = 'white_list.txt'
REPORT_FILE = 'svoboda_report.html' # Имя файла отчета
DELETION_THRESHOLD = 3 # Удалять, если найдено БОЛЬШЕ стольки триггеров
FETCH_MESSAGE_LIMIT = 5000 # Лимит сообщений для сканирования в каждом чате (None для всех - ОЧЕНЬ ДОЛГО)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def load_list_from_file(filename):
    """Загружает список строк из файла, убирая пустые строки и пробелы."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # Приводим к нижнему регистру сразу при загрузке
            items = [line.strip().lower() for line in f if line.strip()]
        logger.info(f"Загружено {len(items)} элементов из {filename}")
        return items
    except FileNotFoundError:
        logger.warning(f"Файл {filename} не найден. Список будет пустым.")
        return []

async def get_entity_title(entity):
    """Получает читаемое имя для диалога (чат, канал, пользователь)."""
    if hasattr(entity, 'title'):
        return entity.title
    elif hasattr(entity, 'first_name'):
        name = entity.first_name
        if entity.last_name:
            name += f" {entity.last_name}"
        if not name and entity.username:
             name = f"@{entity.username}"
        if not name:
            name = f"User ID: {entity.id}"
        return name
    return "Unknown Title"

async def get_user_display_name(user: User):
    """Получает имя пользователя, как оно записано в контактах, если возможно."""
    name = ""
    if user.first_name:
        name = user.first_name
        if user.last_name:
            name += f" {user.last_name}"
    # Возвращаем в нижнем регистре для сравнения с whitelist_names
    return name.lower().strip()

def clean_text_for_matching(text):
    """Приводит текст к нижнему регистру и удаляет основную пунктуацию."""
    if not text:
        return ""
    text_lower = text.lower()
    # Удаляем знаки препинания, которые могут прилипнуть к словам
    # Можно расширить список знаков при необходимости
    translator = str.maketrans('', '', string.punctuation.replace('-', '')) # Оставляем дефис в словах
    return text_lower.translate(translator)

def generate_html_report(analysis_results, permanent_whitelist_ids, permanent_whitelist_names, candidates_for_deletion, final_deleted_ids, terms_list):
    """Генерирует HTML-отчет по результатам анализа."""
    html = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Отчет SVOBODA Bot</title>
    <style>
        body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; background-color: #f4f4f4; color: #333; }}
        h1, h2, h3 {{ color: #555; border-bottom: 1px solid #ddd; padding-bottom: 5px;}}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; background-color: #fff; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background-color: #e9e9e9; }}
        .danger-high {{ color: red; font-weight: bold; }}
        .danger-medium {{ color: orange; }}
        .danger-low {{ color: green; }}
        .neutral {{ color: grey; }}
        .whitelist {{ background-color: #e6f7ff; }} /* Голубоватый фон для белого списка */
        .deleted {{ background-color: #ffe6e6; text-decoration: line-through; }} /* Розовый фон для удаленных */
        .kept {{ background-color: #e6ffe6; }} /* Зеленый фон для оставленных */
        .trigger-list {{ font-size: 0.9em; color: #777; max-width: 400px; word-wrap: break-word;}}
        .summary p {{ margin: 5px 0; }}
        .section {{ margin-bottom: 30px; padding: 15px; border: 1px solid #ccc; border-radius: 5px; background-color: #fff;}}
    </style>
</head>
<body>
    <h1>Отчет анализатора чатов SVOBODA</h1>

    <div class="section summary">
        <h2>Сводка</h2>
        <p>Всего проанализировано чатов: {len(analysis_results)}</p>
        <p>Загружено триггер-слов: {len(terms_list)}</p>
        <p>Порог для удаления: > {DELETION_THRESHOLD} триггеров</p>
        <p>Имен в постоянном белом списке: {len(permanent_whitelist_names)}</p>
        <p>ID в постоянном белом списке: {len(permanent_whitelist_ids)}</p>
        <p>Чатов удалено (или помечено к удалению): {len(final_deleted_ids)}</p>
    </div>

    <div class="section">
        <h2>Постоянный белый список (Не удаляются)</h2>
        <p>Имена/Названия из {WHITELIST_FILE}:</p>
        <ul>{''.join(f'<li>{name}</li>' for name in permanent_whitelist_names) if permanent_whitelist_names else '<li>Список пуст</li>'}</ul>
        <p>Разрешенные ID пользователей: {permanent_whitelist_ids if permanent_whitelist_ids else 'Нет'}</p>
    </div>

    <div class="section">
        <h2>Анализ чатов</h2>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Название чата</th>
                    <th>ID чата</th>
                    <th>Кол-во триггеров</th>
                    <th>Найденные триггеры</th>
                    <th>Статус</th>
                </tr>
            </thead>
            <tbody>
    """

    # Сортируем для отчета: сначала кандидаты на удаление, потом остальные по убыванию триггеров
    analysis_results.sort(key=lambda x: (
        -(x['count'] > DELETION_THRESHOLD and x['id'] not in permanent_whitelist_ids), # Сначала кандидаты на удаление
        -x['count'] # Потом по убыванию кол-ва триггеров
    ))

    for i, chat_info in enumerate(analysis_results):
        chat_id = chat_info['id']
        title = chat_info['title']
        count = chat_info['count']
        found_triggers = chat_info.get('found_triggers', set()) # Получаем найденные триггеры
        msg_count = chat_info['message_count']
        is_permanent_whitelist = chat_id in permanent_whitelist_ids
        is_candidate = count > DELETION_THRESHOLD and not is_permanent_whitelist
        is_deleted = chat_id in final_deleted_ids # Проверяем, был ли он в итоге удален

        status_text = ""
        status_class = ""

        if is_deleted:
            status_text = "УДАЛЕН"
            status_class = "deleted danger-high"
        elif is_permanent_whitelist:
            status_text = "Белый список (сохранен)"
            status_class = "whitelist"
        elif is_candidate: # Был кандидатом, но пользователь решил сохранить
            status_text = f"Кандидат на удаление (сохранен)"
            status_class = "kept danger-high" # Подсвечиваем, что был опасен
        elif count > 0 :
             status_text = f"Найдены триггеры (сохранен)"
             status_class = "kept danger-medium" if 1 <= count <= DELETION_THRESHOLD else "kept danger-low"
        else:
             status_text = "Триггеры не найдены (сохранен)"
             status_class = "kept neutral"

        # Определение уровня опасности для цвета
        danger_class = "neutral"
        if count > DELETION_THRESHOLD:
            danger_class = "danger-high"
        elif 1 <= count <= DELETION_THRESHOLD:
            danger_class = "danger-medium"
        elif count == 0 and msg_count > 0:
             danger_class = "danger-low"


        triggers_str = ', '.join(sorted(list(found_triggers))) if found_triggers else 'Нет'

        html += f"""
                <tr class="{status_class}">
                    <td>{i+1}</td>
                    <td>{title}</td>
                    <td>{chat_id}</td>
                    <td class="{danger_class}">{count}</td>
                    <td class="trigger-list">{triggers_str}</td>
                    <td>{status_text}</td>
                </tr>
        """

    html += """
            </tbody>
        </table>
    </div>

</body>
</html>
    """
    try:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"HTML-отчет успешно сохранен в файл: {REPORT_FILE}")
        print(f"\n[i] HTML-отчет сохранен в файл: {REPORT_FILE}")
    except Exception as e:
        logger.error(f"Не удалось сохранить HTML-отчет: {e}")
        print(f"\n[!] Ошибка сохранения HTML-отчета: {e}")

# --- ОСНОВНАЯ ЛОГИКА ---

async def main():
    # --- 1. Авторизация --- (Без изменений)
    # ... (код авторизации как в предыдущей версии) ...
    if os.path.exists(f"{SESSION_NAME}.session"):
        logger.info("Обнаружен файл сессии. Попытка входа...")
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("Сессия есть, но авторизация не удалась.")
            print("Не удалось автоматически войти. Удалите .session и запустите снова.")
            await client.disconnect()
            return
        logger.info("Авторизация по сессии прошла успешно.")
        me = await client.get_me()
        print(f"Авторизован как: {me.first_name} (@{me.username})")
    else:
        logger.info("Файл сессии не найден. Требуется авторизация.")
        print("--- Авторизация SVOBODA Bot ---")
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        await client.start()
        logger.info("Авторизация прошла успешно.")
        me = await client.get_me()
        print(f"Авторизован как: {me.first_name} (@{me.username})")


    async with client:
        # --- 2. Загрузка списков ---
        terms = load_list_from_file(TERMS_FILE)
        # Загружаем имена из белого списка также в нижнем регистре
        whitelist_names = load_list_from_file(WHITELIST_FILE)

        if not terms:
            logger.warning("Список триггер-слов (terms.txt) пуст. Анализ опасности не будет работать.")
            print("[!] ВНИМАНИЕ: Файл terms.txt пуст. Анализ и удаление по триггерам невозможны.")
            # Можно либо прервать выполнение, либо продолжить без анализа
            # return
        if not whitelist_names:
            logger.warning("Белый список (white_list.txt) пуст.")

        # --- 3. Поиск ID контактов из белого списка ---
        whitelisted_user_ids = set()
        logger.info("Поиск контактов из постоянного белого списка...")
        try:
            contacts = await client(functions.contacts.GetContactsRequest(hash=0))
            # contacts = await client.get_contacts() # Старый метод, если новый не сработает

            if hasattr(contacts, 'users'):
                for user in contacts.users:
                    if isinstance(user, User):
                        display_name = await get_user_display_name(user) # Уже в lower case
                        username = f"@{user.username.lower()}" if user.username else ""

                        # Проверяем совпадение с display_name или username
                        if display_name in whitelist_names or (username and username in whitelist_names):
                            whitelisted_user_ids.add(user.id)
                            name_found = display_name if display_name in whitelist_names else username
                            logger.info(f"Найден контакт в белом списке: {name_found} (ID: {user.id})")

            logger.info(f"Найдено {len(whitelisted_user_ids)} ID пользователей в постоянном белом списке.")
            print(f"[i] Найдено ID в постоянном белом списке: {len(whitelisted_user_ids)}")

        except Exception as e:
            logger.error(f"Ошибка при получении контактов: {e}")

        # --- 4. Парсинг чатов и ТОЧНЫЙ подсчет триггеров ---
        print("\n--- Анализ чатов (поиск точных совпадений триггеров) ---")
        logger.info("Начинаю парсинг диалогов и сообщений...")

        chat_analysis = [] # Список для хранения результатов анализа
        dialog_count = 0
        skipped_dialogs = 0

        try:
            async for dialog in client.iter_dialogs(limit=None): # limit=None для всех диалогов
                dialog_count += 1
                entity = dialog.entity
                title = await get_entity_title(entity)
                chat_id = dialog.id

                # Пропускаем "Saved Messages" (чат с собой)
                if isinstance(entity, User) and entity.is_self:
                    logger.info(f"Пропускаю 'Saved Messages': {title}")
                    skipped_dialogs +=1
                    continue

                # Проверяем, не находится ли пользователь из личного чата в постоянном белом списке ID
                if isinstance(entity, User) and entity.id in whitelisted_user_ids:
                     logger.info(f"Чат с '{title}' (ID: {chat_id}) в постоянном белом списке. Сообщения не сканируются.")
                     chat_analysis.append({
                         "id": chat_id, "title": title, "count": 0,
                         "message_count": 0, "entity": entity,
                         "found_triggers": set(), "is_whitelisted": True
                     })
                     skipped_dialogs += 1
                     continue

                # Можно добавить проверку на имя чата/канала в whitelist_names
                # if title.lower() in whitelist_names:
                #    logger.info(f"Чат/Канал '{title}' (ID: {chat_id}) в постоянном белом списке имен. Сообщения не сканируются.")
                #    chat_analysis.append({
                #         "id": chat_id, "title": title, "count": 0,
                #         "message_count": 0, "entity": entity,
                #         "found_triggers": set(), "is_whitelisted": True
                #    })
                #    skipped_dialogs += 1
                #    continue


                logger.info(f"Анализирую чат ({dialog_count}): {title} (ID: {chat_id})")

                term_count = 0
                message_count = 0
                found_triggers_in_chat = set() # Сет для найденных слов в ЭТОМ чате

                try:
                    async for message in client.iter_messages(chat_id, limit=FETCH_MESSAGE_LIMIT):
                        message_count += 1
                        text_to_check = ""
                        if message.text:
                            text_to_check += message.text + " " # Добавляем пробел для разделения с caption
                        if message.caption:
                             text_to_check += message.caption

                        if text_to_check and terms:
                            cleaned_text = clean_text_for_matching(text_to_check)
                            words_in_message = set(cleaned_text.split()) # Используем set для быстрой проверки

                            for term in terms: # terms уже в lower case
                                if term in words_in_message: # Точное совпадение слова
                                    term_count += 1
                                    found_triggers_in_chat.add(term) # Добавляем найденное слово

                        if message_count % 500 == 0:
                           logger.debug(f"Обработано {message_count} сообщений в '{title}'...")
                           await asyncio.sleep(0.05) # Небольшая пауза

                    chat_analysis.append({
                        "id": chat_id,
                        "title": title,
                        "count": term_count, # Общее кол-во совпадений
                        "entity": entity,
                        "message_count": message_count,
                        "found_triggers": found_triggers_in_chat, # Конкретные слова
                        "is_whitelisted": False # Не из постоянного БС (иначе бы пропустили)
                    })
                    logger.info(f"Чат '{title}': Найдено {term_count} триггеров (уникальных: {len(found_triggers_in_chat)}) в {message_count} сообщениях.")

                except errors.FloodWaitError as e:
                     logger.warning(f"FloodWaitError для чата '{title}'. Ждем {e.seconds} сек. Анализ чата может быть неполным.")
                     print(f"!!! FloodWaitError на чате '{title}'. Ждем {e.seconds} сек...")
                     await asyncio.sleep(e.seconds + 1)
                     # Добавляем то, что успели посчитать
                     chat_analysis.append({
                         "id": chat_id, "title": title, "count": term_count,
                         "entity": entity, "message_count": message_count,
                         "found_triggers": found_triggers_in_chat, "is_whitelisted": False
                     })
                     logger.info(f"Чат '{title}' (частично): Найдено {term_count} триггеров в {message_count} сообщениях.")
                except (errors.ChannelPrivateError, errors.ChatForbiddenError) as e:
                     logger.warning(f"Нет доступа к сообщениям в '{title}' (ID: {chat_id}): {e}. Пропускаю.")
                     skipped_dialogs += 1
                except Exception as e:
                    logger.error(f"Не удалось прочитать сообщения в чате '{title}' (ID: {chat_id}): {e}. Пропускаю.")
                    chat_analysis.append({ # Добавляем в анализ, но с 0 счетчиками
                         "id": chat_id, "title": title, "count": 0,
                         "entity": entity, "message_count": 0,
                         "found_triggers": set(), "is_whitelisted": False
                     })
                    skipped_dialogs += 1

                await asyncio.sleep(0.2) # Пауза между обработкой диалогов

        except errors.FloodWaitError as e:
            logger.error(f"FloodWaitError при получении списка диалогов. Ждем {e.seconds} сек...")
            print(f"!!! FloodWaitError при получении списка чатов. Ждем {e.seconds} сек...")
            await asyncio.sleep(e.seconds + 1)
            print("!!! Возможно, не все чаты были обработаны.")
        except Exception as e:
            logger.error(f"Критическая ошибка при парсинге диалогов: {e}", exc_info=True)
            print(f"!!! Произошла ошибка, анализ чатов прерван: {e}")

        logger.info(f"Завершен анализ. Всего диалогов обработано/пропущено: {len(chat_analysis)}/{skipped_dialogs}.")
        print(f"\n[i] Анализ завершен. Результаты для {len(chat_analysis)} чатов.")

        # --- 5. Выход из чатов/каналов по названию --- (Без существенных изменений)
        print("\n--- Выход из чатов/каналов по триггер-словам в названии ---")
        # ... (код выхода по названию как в предыдущей версии,
        #      но УБЕДИСЬ, что он использует проверку
        #      `if isinstance(entity, User) and entity.is_self:` вместо `dialog.is_self`
        #      и пропускает `whitelisted_user_ids` и, возможно, `whitelist_names`) ...
        # Примерная логика пропуска:
        # async for dialog ...:
        #   entity = dialog.entity
        #   if isinstance(entity, User) and entity.is_self: continue
        #   title = await get_entity_title(entity)
        #   title_lower = title.lower()
        #   chat_id = dialog.id
        #   if isinstance(entity, User) and entity.id in whitelisted_user_ids: continue
        #   # if title_lower in whitelist_names: continue # Если нужно пропускать и по имени
        #   for term in terms:
        #      if term in title_lower:
        #          # ... добавить в список на выход ...
        #          break
        # ... (остальной код подтверждения и выхода) ...
        # ----- КОД ВЫХОДА ПО НАЗВАНИЮ ЗДЕСЬ -----
        # ----- (Как в предыдущей версии, с исправленной проверкой is_self) ----
        dialogs_to_leave = []
        logger.info("Получение актуального списка диалогов для проверки названий...")
        try:
            async for dialog in client.iter_dialogs(limit=None):
                entity = dialog.entity
                # Пропускаем 'Saved Messages'
                if isinstance(entity, User) and entity.is_self:
                    continue

                title = await get_entity_title(entity)
                title_lower = title.lower()
                chat_id = dialog.id

                # Пропускаем чаты с пользователями из БС по ID
                if isinstance(entity, User) and entity.id in whitelisted_user_ids:
                    logger.info(f"Пропуск выхода из чата с '{title}' (в белом списке ID).")
                    continue
                 # Пропускаем чаты/каналы из БС по имени
                # if title_lower in whitelist_names:
                #    logger.info(f"Пропуск выхода из '{title}' (в белом списке имен).")
                #    continue

                if terms: # Проверяем только если есть триггеры
                    for term in terms:
                        if term in title_lower: # Ищем вхождение в названии
                            dialogs_to_leave.append({"id": chat_id, "title": title})
                            logger.warning(f"Найден триггер '{term}' в названии чата/канала '{title}'. Планирую выход.")
                            break # Достаточно одного триггера
        except Exception as e:
             logger.error(f"Ошибка при получении диалогов для проверки названий: {e}")

        if dialogs_to_leave:
            print(f"\n[!] Обнаружено {len(dialogs_to_leave)} чатов/каналов с триггерами в названии:")
            for item in dialogs_to_leave:
                print(f" - {item['title']} (ID: {item['id']})")

            confirm_leave = input("!!! ВНИМАНИЕ !!! Выйти из этих чатов/каналов? (yes/no): ").lower()
            if confirm_leave == 'yes':
                logger.info("Начинаю выход из чатов/каналов по названию...")
                left_count = 0
                for item in dialogs_to_leave:
                    try:
                        await client.delete_dialog(item['id']) # delete_dialog часто работает и для выхода
                        # await client.leave_dialog(item['id']) # Альтернатива, если delete не работает для каналов
                        logger.info(f"Успешно покинут/удален диалог: {item['title']}")
                        print(f" -> Покинут чат/канал: {item['title']}")
                        left_count += 1
                        await asyncio.sleep(1) # Пауза
                    except Exception as e:
                        logger.error(f"Ошибка при выходе из диалога {item['title']} (ID: {item['id']}): {e}")
                        print(f" ! Ошибка при выходе из: {item['title']} - {e}")
                print(f"[i] Завершено. Покинуто {left_count} чатов/каналов.")
            else:
                print("[i] Выход из чатов/каналов отменен.")
                logger.info("Выход из чатов/каналов по названию отменен.")
        else:
            print("[i] Чатов/каналов с триггер-словами в названии для выхода не найдено.")


        # --- 6. Интерактивное удаление чатов (только > N триггеров) ---
        print(f"\n--- Удаление чатов (только если триггеров > {DELETION_THRESHOLD}) ---")

        candidates_for_deletion = []
        id_to_chat_map = {chat['id']: chat for chat in chat_analysis} # Для быстрого доступа по ID

        for chat_info in chat_analysis:
            # Кандидат = больше порога И НЕ в постоянном белом списке
            if chat_info['count'] > DELETION_THRESHOLD and chat_info['id'] not in whitelisted_user_ids:
                candidates_for_deletion.append(chat_info)

        final_chats_to_delete_ids = set() # ID чатов, которые точно будут удалены

        if not candidates_for_deletion:
            print("[i] Чатов с количеством триггеров >", DELETION_THRESHOLD, "не найдено. Удаление не требуется.")
            logger.info("Нет кандидатов на удаление по порогу триггеров.")
        else:
            print(f"\n[!] Найдено {len(candidates_for_deletion)} чатов с количеством триггеров > {DELETION_THRESHOLD}:")
            print("-" * 40)
            for idx, chat_info in enumerate(candidates_for_deletion):
                triggers_str = ', '.join(sorted(list(chat_info['found_triggers'])))
                print(f"{idx + 1}. {chat_info['title']} (ID: {chat_info['id']})")
                print(f"   Триггеров: {chat_info['count']}")
                print(f"   Найденные слова: {triggers_str if triggers_str else 'Нет'}")
                print("-" * 10)

            print("\n--- Постоянный белый список (НЕ удаляются): ---")
            if whitelist_names:
                 print("Имена/Названия:", ', '.join(whitelist_names))
            if whitelisted_user_ids:
                 print("ID пользователей:", ', '.join(map(str, whitelisted_user_ids)))
            if not whitelist_names and not whitelisted_user_ids:
                 print("Постоянный белый список пуст.")
            print("-" * 40)

            # --- Интерактивное добавление во временный белый список ---
            temp_whitelist_ids = set()
            while True:
                save_input = input(f"\nВведите НОМЕРА (из списка выше, через запятую) чатов, которые НЕ НУЖНО удалять (или Enter, чтобы продолжить): ").strip()
                if not save_input:
                    break

                try:
                    indices_to_save = [int(i.strip()) - 1 for i in save_input.split(',') if i.strip()]
                    valid_indices = True
                    current_saved = set()
                    for index in indices_to_save:
                        if 0 <= index < len(candidates_for_deletion):
                            chat_to_save = candidates_for_deletion[index]
                            current_saved.add(chat_to_save['id'])
                            print(f"   -> Добавлен во временный белый список: {chat_to_save['title']} (ID: {chat_to_save['id']})")
                        else:
                            print(f"   [!] Неверный номер: {index + 1}")
                            valid_indices = False
                            break
                    if valid_indices:
                         temp_whitelist_ids.update(current_saved)
                         print(f"   [i] Текущий временный белый список ID: {temp_whitelist_ids if temp_whitelist_ids else 'пусто'}")
                         break # Выходим из while после успешного ввода
                    else:
                         print("   Попробуйте ввести номера еще раз.")

                except ValueError:
                    print("[!] Ошибка: Вводите только числа (номера из списка) через запятую.")
                except Exception as e:
                     print(f"[!] Произошла ошибка: {e}")

            # --- Финальное подтверждение ---
            final_chats_to_delete_list = []
            for chat_info in candidates_for_deletion:
                if chat_info['id'] not in temp_whitelist_ids:
                    final_chats_to_delete_list.append(chat_info)
                    final_chats_to_delete_ids.add(chat_info['id']) # Сохраняем ID для отчета

            if not final_chats_to_delete_list:
                print("\n[i] Все кандидаты были добавлены во временный белый список. Удаление отменено.")
                logger.info("Все кандидаты на удаление добавлены во временный белый список.")
            else:
                print(f"\n--- ИТОГО К УДАЛЕНИЮ ({len(final_chats_to_delete_list)} чатов): ---")
                for chat_info in final_chats_to_delete_list:
                     print(f" - {chat_info['title']} (ID: {chat_info['id']}, Триггеров: {chat_info['count']})")

                confirm_delete = input(f"\n!!! ВНИМАНИЕ !!! Подтвердите удаление этих {len(final_chats_to_delete_list)} чатов? Это НЕОБРАТИМО! (yes/no): ").lower()

                if confirm_delete == 'yes':
                    logger.info(f"Начинаю удаление {len(final_chats_to_delete_list)} чатов...")
                    deleted_count = 0
                    for chat_info in final_chats_to_delete_list:
                        try:
                            await client.delete_dialog(chat_info['id'])
                            logger.info(f"Успешно удален диалог: {chat_info['title']} (ID: {chat_info['id']})")
                            print(f" -> Удален чат: {chat_info['title']}")
                            deleted_count += 1
                            await asyncio.sleep(1) # Пауза
                        except Exception as e:
                            logger.error(f"Ошибка при удалении диалога {chat_info['title']} (ID: {chat_info['id']}): {e}")
                            print(f" ! Ошибка при удалении: {chat_info['title']} - {e}")
                            final_chats_to_delete_ids.remove(chat_info['id']) # Убираем из списка удаленных для отчета, если не вышло
                    print(f"[i] Завершено. Удалено {deleted_count} чатов.")
                else:
                    print("[i] Удаление чатов отменено пользователем.")
                    logger.info("Удаление чатов отменено пользователем.")
                    final_chats_to_delete_ids.clear() # Очищаем, так как удаление отменено

        # --- 7. Генерация HTML отчета ---
        print("\n--- Генерация HTML отчета ---")
        generate_html_report(
            analysis_results=chat_analysis,
            permanent_whitelist_ids=whitelisted_user_ids,
            permanent_whitelist_names=whitelist_names,
            candidates_for_deletion=candidates_for_deletion, # Передаем кандидатов (для информации)
            final_deleted_ids=final_chats_to_delete_ids, # Передаем ID тех, что реально удалили (или собирались)
            terms_list=terms
        )

        print("\n--- Работа SVOBODA Bot завершена ---")

if __name__ == "__main__":
    # Проверка наличия файлов перед запуском
    for f in [TERMS_FILE, WHITELIST_FILE]:
         if not os.path.exists(f):
              print(f"[!] Файл {f} не найден. Создайте его.")
              # Можно создать пустые файлы
              # try: open(f, 'a').close()
              # except OSError: pass

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Работа бота прервана пользователем.")
        print("\nВыход...")
    # ... (остальная обработка исключений как в предыдущей версии) ...
    except errors.AuthKeyError:
         logger.error("Ключ авторизации недействителен.")
         print("\n!!! Ошибка авторизации. Ключ недействителен.")
         print("!!! Удалите .session файл и запустите заново.")
         if os.path.exists(f"{SESSION_NAME}.session"):
             try: os.remove(f"{SESSION_NAME}.session"); logger.info("Удален недействительный .session")
             except OSError as e: logger.error(f"Не удалось удалить .session: {e}")
    except Exception as e:
         logger.exception("Произошла непредвиденная ошибка:")
         print(f"\n!!! Произошла критическая ошибка: {e}")