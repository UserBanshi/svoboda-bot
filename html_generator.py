# html_generator.py
# генерация html отчета

import logging
from config import REPORT_FILE, WHITELIST_FILE, DELETION_THRESHOLD

logger = logging.getLogger(__name__)

# (код функции generate_html_report из предыдущего ответа,
#  но с импортом констант из config и использованием logger)

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
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6; padding: 25px;
            background-color: #282c34; color: #abb2bf; margin: 0;
        }}
        h1, h2, h3 {{ color: #61afef; border-bottom: 1px solid #4b5263; padding-bottom: 8px; margin-top: 30px; margin-bottom: 15px; }}
        h1 {{ text-align: center; border-bottom: 2px solid #61afef; margin-bottom: 30px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 25px; background-color: #3b4048; box-shadow: 0 2px 5px rgba(0,0,0,0.2); border-radius: 5px; overflow: hidden; }}
        th, td {{ border: 1px solid #4b5263; padding: 12px 15px; text-align: left; vertical-align: top; }}
        th {{ background-color: #4f5660; color: #ffffff; font-weight: 600; }}
        .whitelist {{ background-color: rgba(97, 175, 239, 0.2); }}
        .deleted {{ background-color: rgba(224, 108, 117, 0.2); text-decoration: line-through; }}
        .kept {{ background-color: rgba(152, 195, 121, 0.15); }}
        .danger-high {{ color: #e06c75; font-weight: bold; }}
        .danger-medium {{ color: #d19a66; }}
        .danger-low {{ color: #98c379; }}
        .neutral {{ color: #abb2bf; }}
        .trigger-list {{ font-size: 0.85em; color: #e5c07b; max-width: 350px; word-wrap: break-word; line-height: 1.4; }}
        .summary p, .section ul {{ margin: 8px 0; }}
        .section {{ margin-bottom: 30px; padding: 20px; border: 1px solid #4b5263; border-radius: 8px; background-color: #323842; }}
        .section ul {{ padding-left: 20px; }}
        .section li {{ margin-bottom: 5px; }}
        td:nth-child(3) {{ font-family: 'Courier New', Courier, monospace; font-size: 0.9em; color: #56b6c2; }}
        td:last-child {{ font-weight: 500; }}
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
            <thead><tr><th>#</th><th>Название чата</th><th>ID чата</th><th>Кол-во триггеров</th><th>Найденные триггеры</th><th>Статус</th></tr></thead>
            <tbody>
    """
    # сортировка для отчета
    analysis_results.sort(key=lambda x: (
        -(x['count'] > DELETION_THRESHOLD and x['id'] not in permanent_whitelist_ids),
        -x['count']
    ))

    for i, chat_info in enumerate(analysis_results):
        chat_id = chat_info['id']
        title = chat_info['title']
        count = chat_info['count']
        found_triggers = chat_info.get('found_triggers', set())
        msg_count = chat_info['message_count']
        is_permanent_whitelist = chat_id in permanent_whitelist_ids
        is_candidate = count > DELETION_THRESHOLD and not is_permanent_whitelist
        is_deleted = chat_id in final_deleted_ids

        status_text = ""
        status_class = ""
        if is_deleted:
            status_text = "УДАЛЕН"
            status_class = "deleted danger-high"
        elif is_permanent_whitelist:
            status_text = "Белый список (сохранен)"
            status_class = "whitelist"
        elif is_candidate:
            status_text = f"Кандидат >{DELETION_THRESHOLD} (сохранен)"
            status_class = "kept danger-high"
        elif count > 0 :
             status_text = f"Триггеры <= {DELETION_THRESHOLD} (сохранен)"
             status_class = "kept danger-medium"
        else:
             status_text = "Нет триггеров (сохранен)"
             status_class = "kept neutral"

        danger_class = "neutral"
        if count > DELETION_THRESHOLD: danger_class = "danger-high"
        elif 1 <= count <= DELETION_THRESHOLD: danger_class = "danger-medium"
        elif count == 0 and msg_count > 0: danger_class = "danger-low"

        triggers_str = ', '.join(sorted(list(found_triggers))) if found_triggers else 'Нет'
        html += f"""<tr class="{status_class}"><td>{i+1}</td><td>{title}</td><td>{chat_id}</td><td class="{danger_class}">{count}</td><td class="trigger-list">{triggers_str}</td><td>{status_text}</td></tr>"""

    html += """</tbody></table></div></body></html>"""
    try:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"html-отчет сохранен: {REPORT_FILE}")
        return REPORT_FILE # возвращаем имя файла для отправки
    except Exception as e:
        logger.error(f"не удалось сохранить html-отчет: {e}")
        return None