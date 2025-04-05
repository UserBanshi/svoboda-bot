# config.py
import os

# --- aiogram bot ---
BOT_TOKEN = "" # <<<=== ТОКЕН БОТА
ADMIN_ID = # <<<=== ВАШ USER ID

# --- telethon user client ---
API_ID =   # ваш api id
API_HASH = ''  # ваш api hash
SESSION_NAME = 'svoboda'

# --- файлы и папки ---
TERMS_FILE = 'terms.txt'
WHITELIST_FILE = 'white_list.txt'
REPORTS_DIR = 'reports'
REPORT_FILENAME_TEMPLATE = os.path.join(REPORTS_DIR, 'svoboda_report_{timestamp}.html')

# --- настройки анализа (telethon) ---
DELETION_THRESHOLD = 3
FETCH_MESSAGE_LIMIT = 500 # None = все

# --- фразы подтверждения (aiogram) ---
CHAT_DELETION_CONFIRMATION_PHRASE = "ДА ПОДТВЕРЖДАЮ УДАЛЕНИЕ ЧАТОВ"
CONTACT_DELETION_CONFIRMATION_PHRASE = "ПОЛНОЕ УДАЛЕНИЕ КОНТАКТОВ ПОДТВЕРЖДАЮ"