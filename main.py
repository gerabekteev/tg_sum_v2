import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from telethon import TelegramClient
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database.connection import init_db, SessionLocal
from database.models import get_user_settings
from bot.handlers import router
from scheduler import init_scheduler

# ─── Improvement #9: RotatingFileHandler ───
log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)

rotating_handler = RotatingFileHandler(
    config.BASE_DIR / "app.log",
    maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT,
    encoding="utf-8",
)
rotating_handler.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[stream_handler, rotating_handler],
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Запуск Telegram-Саммаризатора V2...")

    # 1. Валидация конфигурации
    errors = config.validate_config()
    if errors:
        logger.error("Ошибки конфигурации .env:")
        for err in errors:
            print(f"❌ {err}")
        sys.exit(1)

    # 2. Инициализация БД (создаёт новые таблицы автоматически)
    logger.info("Инициализация базы данных SQLite...")
    init_db()

    # Получаем период из БД
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        period_hours = settings.period_hours

    # 3. Telethon-юзербот
    logger.info("Инициализация Telethon юзербота...")
    user_client = TelegramClient(
        config.USER_SESSION_PATH,
        config.API_ID,
        config.API_HASH,
    )

    # 4. aiogram-бот
    logger.info("Инициализация aiogram бота...")
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # 5. Планировщик
    logger.info("Настройка планировщика APScheduler...")
    scheduler = init_scheduler(bot, user_client, period_hours)

    try:
        # 6. Авторизация юзербота
        logger.info("Авторизация юзербота...")
        await user_client.start(phone=lambda: config.TELEGRAM_PHONE)
        logger.info("Юзербот авторизован!")

        # 7. Старт планировщика
        scheduler.start()
        logger.info(f"Планировщик запущен: суммаризация каждые {period_hours} ч., алерты каждые 15 мин., очистка в 04:00")

        # 8. Запуск
        logger.info("Приложение готово. Запуск polling...")
        await asyncio.gather(
            dp.start_polling(
                bot,
                user_client=user_client,
                scheduler=scheduler,
                close_bot_session=True,
            ),
            user_client.run_until_disconnected(),
        )

    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал завершения...")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Планировщик остановлен.")
        if user_client.is_connected():
            await user_client.disconnect()
            logger.info("Юзербот отключен.")
        logger.info("Приложение завершено.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Приложение остановлено.")
