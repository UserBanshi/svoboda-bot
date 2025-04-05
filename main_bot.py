# main_bot.py
import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('telethon').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


import config
from aiogram_bot.bot_instance import bot
from aiogram_bot.dispatcher import dp
from telethon_client.client_instance import init_telethon_client, stop_telethon_client

import shared_state


async def main():
    # основная функция запуска
    logger.info("запуск гибридного бота...")


    #  Убедитесь, что плейсхолдеры совпадают с вашим config.py
    placeholder_bot_token = "1234567890:ABCdEfGhIjKlMnOpQrStUvWxYz"
    placeholder_admin_id = 123456789
    placeholder_api_id = 1234567
    placeholder_api_hash = 'your_api_hash_here'

    errors_found = False
    if not config.BOT_TOKEN or config.BOT_TOKEN == placeholder_bot_token:
        logger.error(f"!!! Укажите действительный BOT_TOKEN в config.py")
        errors_found = True
    if not isinstance(config.ADMIN_ID, int) or config.ADMIN_ID == placeholder_admin_id:
         logger.error(f"!!! Укажите действительный ADMIN_ID (ваш User ID) в config.py")
         errors_found = True
    if not isinstance(config.API_ID, int) or config.API_ID == placeholder_api_id:
        logger.error(f"!!! Укажите действительный API_ID в config.py")
        errors_found = True
    if not config.API_HASH or config.API_HASH == placeholder_api_hash:
         logger.error(f"!!! Укажите действительный API_HASH в config.py")
         errors_found = True

    if errors_found:
        logger.critical("Ошибки конфигурации в config.py. Исправьте и перезапустите.")
        return

    for f in [config.TERMS_FILE, config.WHITELIST_FILE]:
        if not os.path.exists(f):
            logger.warning(f"Файл {f} не найден, создаю пустой.")
            try: # <--- try на новой строке
                open(f, 'a', encoding='utf-8').close()
            except OSError as e:
                logger.error(f"Не удалось создать файл {f}: {e}")
    try:
        os.makedirs(config.REPORTS_DIR, exist_ok=True)
    except OSError as e:
         logger.error(f"Не удалось создать папку {config.REPORTS_DIR}: {e}")


    # инициализация telethon
    try:
        await init_telethon_client()
    except Exception as e:
        logger.critical(f"не удалось инициализировать telethon: {e}")
        return

    # запуск aiogram polling
    logger.info("запуск aiogram polling...")
    polling_task = asyncio.create_task(dp.start_polling(bot, skip_updates=True))
    # Ждем сигнала на остановку
    await shared_state.shutdown_event.wait()
    logger.info("получен сигнал на остановку...")

    # корректное завершение
    logger.info("остановка polling...")
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        logger.info("polling task отменен.")

    logger.info("остановка бота...")
    await stop_telethon_client()
    await bot.session.close()
    logger.info("бот остановлен.")


if __name__ == "__main__":
    # установка политики цикла для windows(сделал для себя, никак не мешает работе на любом устройстве, просто у меня ошибка конченная)
    if sys.platform == "win32":
        logger.info("установка политики цикла событий для windows (selector)...")
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("бот остановлен вручную.")