# telethon_client/utils.py
import logging
import string
import os
import datetime
from telethon.tl.types import User
import config # Импорт config для доступа к константам

logger = logging.getLogger(__name__)

# --- Вспомогательные функции ---

def load_list_from_file(filename):
    # загружает список строк из файла
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            items = [line.strip().lower() for line in f if line.strip()]
        return items
    except FileNotFoundError:
        logger.warning(f"файл {filename} не найден.")
        return []

async def get_entity_title(entity):
    # получает читаемое имя для диалога
    if hasattr(entity, 'title'):
        return entity.title
    elif hasattr(entity, 'first_name'):
        name = entity.first_name
        if entity.last_name: name += f" {entity.last_name}"
        if not name and entity.username: name = f"@{entity.username}"
        if not name: name = f"User ID: {entity.id}"
        return name
    return "Unknown Title"

async def get_user_display_name(user: User):
    # получает имя пользователя как в контактах (в нижнем регистре)
    name = ""
    if user.first_name:
        name = user.first_name
        if user.last_name: name += f" {user.last_name}"
    return name.lower().strip()

def clean_text_for_matching(text):
    # приводит текст к нижнему регистру и удаляет пунктуацию
    if not text: return ""
    text_lower = text.lower()
    translator = str.maketrans('', '', string.punctuation.replace('-', ''))
    return text_lower.translate(translator)

# --- Генерация HTML отчета ---

def generate_html_report(analysis_results, permanent_whitelist_ids, permanent_whitelist_names, candidates_for_deletion, final_deleted_ids, terms_list):
    # генерирует html-отчет и возвращает путь к файлу
    # (стили и структура HTML остаются прежними, они уже используют HTML)
    html = f"""
<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><title>Отчет SVOBODA Bot</title><style>
body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;line-height:1.6;padding:25px;background-color:#282c34;color:#abb2bf;margin:0}}
h1,h2,h3{{color:#61afef;border-bottom:1px solid #4b5263;padding-bottom:8px;margin-top:30px;margin-bottom:15px}}h1{{text-align:center;border-bottom:2px solid #61afef;margin-bottom:30px}}
table{{width:100%;border-collapse:collapse;margin-bottom:25px;background-color:#3b4048;box-shadow:0 2px 5px rgba(0,0,0,0.2);border-radius:5px;overflow:hidden}}
th,td{{border:1px solid #4b5263;padding:12px 15px;text-align:left;vertical-align:top}}th{{background-color:#4f5660;color:#fff;font-weight:600}}
.whitelist{{background-color:rgba(97,175,239,.2)}}.deleted{{background-color:rgba(224,108,117,.2);text-decoration:line-through}}.kept{{background-color:rgba(152,195,121,.15)}}
.danger-high{{color:#e06c75;font-weight:700}}.danger-medium{{color:#d19a66}}.danger-low{{color:#98c379}}.neutral{{color:#abb2bf}}
.trigger-list{{font-size:.85em;color:#e5c07b;max-width:350px;word-wrap:break-word;line-height:1.4}}
.summary p,.section ul{{margin:8px 0}}.section{{margin-bottom:30px;padding:20px;border:1px solid #4b5263;border-radius:8px;background-color:#323842}}
.section ul{{padding-left:20px}}.section li{{margin-bottom:5px}}
td:nth-child(3){{font-family:'Courier New',Courier,monospace;font-size:.9em;color:#56b6c2}}td:last-child{{font-weight:500}}
</style></head><body><h1>Отчет анализатора чатов SVOBODA</h1><div class="section summary"><h2>Сводка</h2>
<p>Всего проанализировано чатов: {len(analysis_results)}</p><p>Загружено триггер-слов: {len(terms_list)}</p><p>Порог для удаления: > {config.DELETION_THRESHOLD} триггеров</p>
<p>Имен в постоянном белом списке: {len(permanent_whitelist_names)}</p><p>ID в постоянном белом списке: {len(permanent_whitelist_ids)}</p><p>Чатов удалено: {len(final_deleted_ids)}</p></div>
<div class="section"><h2>Постоянный белый список (Не удаляются)</h2><p>Имена/Названия из {config.WHITELIST_FILE}:</p><ul>{''.join(f'<li>{name}</li>' for name in permanent_whitelist_names) if permanent_whitelist_names else '<li>Список пуст</li>'}</ul>
<p>Разрешенные ID пользователей: {permanent_whitelist_ids if permanent_whitelist_ids else 'Нет'}</p></div><div class="section"><h2>Анализ чатов</h2><table>
<thead><tr><th>#</th><th>Название чата</th><th>ID чата</th><th>Кол-во триггеров</th><th>Найденные триггеры</th><th>Статус</th></tr></thead><tbody>
    """
    analysis_results.sort(key=lambda x: (-(x['count'] > config.DELETION_THRESHOLD and not x.get('is_whitelisted', False)), -x['count']))
    for i, chat_info in enumerate(analysis_results):
        chat_id, title, count = chat_info['id'], chat_info['title'], chat_info['count']
        found_triggers = chat_info.get('found_triggers', set()) # Это уже list в analysis_cache
        is_permanent_whitelist = chat_info.get('is_whitelisted', False)
        is_deleted = chat_id in final_deleted_ids
        status_text, status_class = "", ""
        if is_deleted: status_text, status_class = "УДАЛЕН", "deleted danger-high"
        elif is_permanent_whitelist: status_text, status_class = "Белый список", "whitelist"
        elif count > config.DELETION_THRESHOLD: status_text, status_class = f"Кандидат >{config.DELETION_THRESHOLD}", "kept danger-high"
        elif count > 0: status_text, status_class = f"Триггеры <= {config.DELETION_THRESHOLD}", "kept danger-medium"
        else: status_text, status_class = "Нет триггеров", "kept neutral"
        danger_class = "neutral"
        if count > config.DELETION_THRESHOLD: danger_class = "danger-high"
        elif count > 0: danger_class = "danger-medium"
        triggers_str = ', '.join(sorted(list(found_triggers))) if found_triggers else 'Нет' # На случай если пришел set
        html += f'<tr class="{status_class}"><td>{i+1}</td><td>{title}</td><td>{chat_id}</td><td class="{danger_class}">{count}</td><td class="trigger-list">{triggers_str}</td><td>{status_text}</td></tr>'
    html += """</tbody></table></div></body></html>"""

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filepath = config.REPORT_FILENAME_TEMPLATE.format(timestamp=timestamp)
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

    try:
        with open(report_filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"html-отчет сохранен: {report_filepath}")
        return report_filepath
    except Exception as e:
        logger.error(f"не удалось сохранить html-отчет: {e}")
        return None