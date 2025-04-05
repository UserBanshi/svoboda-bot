# aiogram_bot/states.py
from aiogram.fsm.state import State, StatesGroup

class DeletionStates(StatesGroup):
    pending_chat_deletion = State()
    pending_contact_deletion = State()
    confirm_cleanup_stop = State()