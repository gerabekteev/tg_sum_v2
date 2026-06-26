import asyncio
import sys
import logging

# Настройка простого логгера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Verifier")

async def test_all():
    logger.info("=== Начинаем проверку проекта V2 ===")
    
    # 1. Проверка импорта модулей
    try:
        import config
        from database.connection import init_db, SessionLocal
        from database.models import get_user_settings, add_summary_log
        from client.telegram_client import fetch_messages_for_period
        from ai.gemini import summarize_messages
        from scheduler import init_scheduler
        logger.info("✅ Все модули успешно импортированы!")
    except Exception as e:
        logger.error(f"❌ Ошибка импорта: {e}")
        sys.exit(1)

    # 2. Проверка валидации конфигурации
    errors = config.validate_config()
    if errors:
        logger.warning("⚠️ Есть предупреждения по конфигурации:")
        for err in errors:
            logger.warning(f"  - {err}")
    else:
        logger.info("✅ Конфигурация .env полностью валидна!")

    # 3. Тест базы данных SQLite
    try:
        logger.info("Инициализация базы данных...")
        init_db()
        logger.info("✅ База данных успешно инициализирована!")
        
        with SessionLocal() as db:
            logger.info("Проверка создания настроек администратора...")
            settings = get_user_settings(db, config.ADMIN_ID)
            logger.info(f"✅ Настройки получены/созданы. Целевой чат: {settings.target_chat}, Модель: {settings.preferred_model}")
    except Exception as e:
        logger.error(f"❌ Ошибка при работе с базой данных: {e}")
        sys.exit(1)

    # 4. Тест OpenRouter API с переключением (failover)
    try:
        logger.info("Тестирование суммаризации через OpenRouter...")
        test_text = "[2026-06-26 05:00:00] [Иван Иванов]: Всем привет! Надо доделать лабораторную работу №3 по физике до понедельника. PDF с описанием лежит в общем облаке."
        
        # Пробуем вызвать суммаризатор
        summary, model = await summarize_messages(test_text, settings.preferred_model)
        logger.info(f"✅ Саммаризация успешно выполнена моделью: {model}")
        logger.info("Полученный результат:")
        print(f"\n{summary}\n")
        
        # Логируем тестовую запись
        with SessionLocal() as db:
            add_summary_log(db, "TEST_CHAT", 1, summary, model)
            logger.info("✅ Запись успешно добавлена в лог базы данных!")

        # Тестируем Q&A
        from ai.gemini import ask_llm_about_chat
        logger.info("Тестирование Q&A режима...")
        question = "До какого дня нужно сдать лабораторную?"
        answer, qa_model = await ask_llm_about_chat(test_text, question, settings.preferred_model)
        logger.info(f"✅ Q&A успешно выполнено моделью: {qa_model}")
        logger.info(f"Вопрос: {question}")
        logger.info(f"Ответ: {answer}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при вызове OpenRouter: {e}")
        sys.exit(1)

    logger.info("=== Все автономные тесты успешно пройдены! ===")

if __name__ == "__main__":
    asyncio.run(test_all())
