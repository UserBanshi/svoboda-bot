# aiogram_bot/dispatcher.py
from aiogram import Dispatcher
from .routers import common, analysis, deletion

# главный диспетчер aiogram
dp = Dispatcher()
dp.include_router(common.router)
dp.include_router(analysis.router)
dp.include_router(deletion.router)

