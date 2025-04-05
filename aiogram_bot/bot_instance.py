# aiogram_bot/bot_instance.py
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import config

# создаем экземпляр бота aiogram с ParseMode.HTML по умолчанию
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))