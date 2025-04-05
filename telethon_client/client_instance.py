# telethon_client/client_instance.py
import logging
from telethon import TelegramClient
import config

logger = logging.getLogger(__name__)

# глобальный экземпляр клиента telethon
telethon_client: TelegramClient | None = None

async def init_telethon_client():
    # инициализирует и запускает клиент telethon
    global telethon_client
    if telethon_client and telethon_client.is_connected():
        logger.info("клиент telethon уже инициализирован.")
        return telethon_client

    logger.info("инициализация клиента telethon...")
    telethon_client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)

    try:
        logger.info("подключение клиента telethon...")
        await telethon_client.start(
            phone=lambda: input("telethon: введите номер телефона: "),
            code_callback=lambda: input("telethon: введите код из telegram: ")
        )
        me = await telethon_client.get_me()
        logger.info(f"клиент telethon авторизован как: {me.first_name} (@{me.username})")
        return telethon_client
    except Exception as e:
        logger.exception("не удалось запустить клиент telethon!")
        telethon_client = None
        raise

async def stop_telethon_client():
    # отключает клиент telethon
    global telethon_client
    if telethon_client and telethon_client.is_connected():
        logger.info("отключение клиента telethon...")
        await telethon_client.disconnect()
        logger.info("клиент telethon отключен.")
    telethon_client = None

def get_telethon_client() -> TelegramClient:
    # возвращает активный экземпляр клиента telethon
    if not telethon_client or not telethon_client.is_connected():
        logger.error("попытка получить неактивный клиент telethon!")
        raise ConnectionError("Клиент Telethon не активен.")
    return telethon_client