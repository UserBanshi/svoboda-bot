# shared_state.py
import asyncio

# Событие для сигнализации о необходимости остановки бота
shutdown_event = asyncio.Event()