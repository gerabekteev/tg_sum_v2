import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Корневой путь проекта
BASE_DIR = Path(__file__).resolve().parent

# Папки для дампов и сессий Telegram
DUMPS_DIR = BASE_DIR / "dumps"
SESSIONS_DIR = BASE_DIR / "sessions"

# Создаем папки, если их нет
DUMPS_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)

# Чтение и валидация конфигурации из .env
try:
    API_ID_RAW = os.getenv("TELEGRAM_API_ID")
    API_ID = int(API_ID_RAW) if API_ID_RAW else 0
except ValueError:
    API_ID = 0

API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

try:
    ADMIN_ID_RAW = os.getenv("ADMIN_ID")
    ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW else 0
except ValueError:
    ADMIN_ID = 0

# Значения по умолчанию из .env
DEFAULT_TARGET_CHAT = os.getenv("TARGET_CHAT", "")
try:
    DEFAULT_PERIOD_HOURS = int(os.getenv("DEFAULT_PERIOD_HOURS", "4"))
except ValueError:
    DEFAULT_PERIOD_HOURS = 4

# Путь к SQLite БД
DATABASE_URL = f"sqlite:///{BASE_DIR}/tg_sum.db"

# Пути к сессиям
USER_SESSION_PATH = str(SESSIONS_DIR / "user_session")

# OpenRouter API Credentials
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Часовой пояс
TIMEZONE_STR = os.getenv("TIMEZONE", "Europe/Moscow")
try:
    TIMEZONE = ZoneInfo(TIMEZONE_STR)
except Exception:
    import datetime
    TIMEZONE = datetime.timezone.utc

# ─── Ротация данных (Improvement #9) ───
try:
    DUMP_RETENTION_DAYS = int(os.getenv("DUMP_RETENTION_DAYS", "7"))
except ValueError:
    DUMP_RETENTION_DAYS = 7

try:
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
except ValueError:
    LOG_RETENTION_DAYS = 30

LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB по умолчанию
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# ─── Умные уведомления (Improvement #5) ───
try:
    ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "60"))
except ValueError:
    ALERT_COOLDOWN_MINUTES = 60

URGENT_KEYWORDS = [
    "дедлайн", "сдать", "экзамен", "зачёт", "зачет", "тест",
    "срочно", "важно", "перенос", "отмена", "обязательно",
    "контрольная", "лабораторная", "курсовая", "диплом",
    "завтра сдача", "последний день", "не забудьте",
]


def validate_config():
    """Простая проверка конфигурации на наличие заполненных значений."""
    errors = []
    if not API_ID:
        errors.append("TELEGRAM_API_ID не задан или некорректен.")
    if not API_HASH:
        errors.append("TELEGRAM_API_HASH не задан.")
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не задан.")
    if not ADMIN_ID:
        errors.append("ADMIN_ID не задан.")
    if not OPENROUTER_API_KEY:
        errors.append("OPENROUTER_API_KEY не задан.")
    return errors
