import os
import logging
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


async def auto_fetch_job(bot, user_client):
    """
    Периодическая фоновая задача: сбор и суммаризация.
    Improvement #2: обрабатывает все отслеживаемые чаты (мульти-чат).
    """
    logger.info("Запуск фоновой задачи сбора сообщений...")
    from bot.handlers import process_and_send_summary
    import config
    from database.connection import SessionLocal
    from database.models import get_user_settings, get_monitored_chats

    try:
        admin_id = config.ADMIN_ID

        # 1) Основной чат
        await process_and_send_summary(
            bot=bot,
            chat_id=admin_id,
            user_client=user_client,
            since_last=True,
        )

        # 2) Все мониторинговые чаты (#2)
        with SessionLocal() as db:
            chats = get_monitored_chats(db, admin_id)

        for chat in chats:
            try:
                await process_and_send_summary(
                    bot=bot,
                    chat_id=admin_id,
                    user_client=user_client,
                    since_last=True,
                    target_chat_peer=chat.chat_peer,
                    target_last_msg_id=chat.last_message_id,
                    target_last_run=chat.last_run_timestamp,
                    monitored_chat_db_id=chat.id,
                )
            except Exception as e:
                logger.error(f"Ошибка при обработке чата {chat.chat_peer}: {e}")

    except Exception as e:
        logger.error(f"Ошибка фоновой задачи суммаризации: {e}")


# ─── Improvement #5: Умные уведомления (сторожевая задача) ───

async def smart_alert_job(bot, user_client):
    """
    Сторожевая задача: каждые 15 мин проверяет свежие сообщения
    на наличие срочных ключевых слов и отправляет push-алерт.
    """
    import config
    from database.connection import SessionLocal
    from database.models import get_user_settings, get_monitored_chats, get_recent_alert, add_alert_log
    from client.telegram_client import fetch_messages_for_period, detect_urgent_keywords

    admin_id = config.ADMIN_ID

    with SessionLocal() as db:
        settings = get_user_settings(db, admin_id)
        if not settings.smart_alerts:
            return  # Уведомления выключены

    chats_to_check = []

    # Основной чат
    if settings.target_chat:
        chats_to_check.append(("main", settings.target_chat))

    # Мониторинговые чаты
    with SessionLocal() as db:
        monitored = get_monitored_chats(db, admin_id)
    for m in monitored:
        chats_to_check.append(("monitored", m.chat_peer))

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    check_since = now_utc - datetime.timedelta(minutes=20)  # Проверяем последние 20 мин

    for chat_type, chat_peer in chats_to_check:
        try:
            # Проверяем кулдаун
            with SessionLocal() as db:
                recent_alert = get_recent_alert(db, chat_peer, config.ALERT_COOLDOWN_MINUTES)
            if recent_alert:
                continue  # Кулдаун ещё не истёк

            msgs, _ = await fetch_messages_for_period(
                client=user_client,
                chat_peer=chat_peer,
                start_time=check_since,
                end_time=now_utc,
            )

            if not msgs:
                continue

            keywords_found = detect_urgent_keywords(msgs)

            if len(keywords_found) >= 2:
                # Нашли ≥2 ключевых слова — отправляем алерт
                keywords_str = ", ".join(keywords_found[:5])
                alert_text = (
                    f"🚨 **СРОЧНОЕ УВЕДОМЛЕНИЕ**\n\n"
                    f"В чате `{chat_peer}` обнаружены важные ключевые слова:\n"
                    f"**{keywords_str}**\n\n"
                    f"Рекомендуется запросить саммари для деталей."
                )

                await bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="Markdown")

                with SessionLocal() as db:
                    add_alert_log(db, chat_peer, alert_text, keywords_str)

                logger.info(f"Алерт отправлен для {chat_peer}: {keywords_str}")

        except Exception as e:
            logger.error(f"Ошибка smart_alert для {chat_peer}: {e}")


# ─── Improvement #9: Автоматическая очистка данных ───

async def data_cleanup_job():
    """
    Фоновая задача: ротация дампов и старых записей в БД.
    Запускается раз в сутки.
    """
    import config
    from database.connection import SessionLocal
    from database.models import SummaryLog, AlertLog

    logger.info("Запуск задачи очистки данных...")

    # 1) Удаляем старые файлы дампов
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=config.DUMP_RETENTION_DAYS)
    deleted_files = 0

    if config.DUMPS_DIR.exists():
        for f in config.DUMPS_DIR.iterdir():
            if f.is_file() and f.suffix == ".txt":
                try:
                    file_mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
                    if file_mtime < cutoff_date:
                        f.unlink()
                        deleted_files += 1
                except Exception as e:
                    logger.warning(f"Не удалось удалить {f}: {e}")

    logger.info(f"Удалено старых дампов: {deleted_files}")

    # 2) Удаляем старые записи SummaryLog
    log_cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=config.LOG_RETENTION_DAYS)
    deleted_logs = 0

    with SessionLocal() as db:
        old_logs = db.query(SummaryLog).filter(SummaryLog.timestamp < log_cutoff).all()
        for log in old_logs:
            # Удаляем связанный файл дампа, если он ещё существует
            if log.dump_file_path and os.path.exists(log.dump_file_path):
                try:
                    os.remove(log.dump_file_path)
                except Exception:
                    pass
            db.delete(log)
            deleted_logs += 1
        db.commit()

    logger.info(f"Удалено старых записей SummaryLog: {deleted_logs}")

    # 3) Удаляем старые AlertLog (старше 30 дней)
    with SessionLocal() as db:
        old_alerts = db.query(AlertLog).filter(AlertLog.timestamp < log_cutoff).all()
        alert_count = len(old_alerts)
        for alert in old_alerts:
            db.delete(alert)
        db.commit()

    logger.info(f"Удалено старых AlertLog: {alert_count}")


# ─── Инициализация планировщика ───

def init_scheduler(bot, user_client, period_hours: int) -> AsyncIOScheduler:
    """Инициализирует и возвращает планировщик со всеми задачами."""
    scheduler = AsyncIOScheduler()

    # Основная задача суммаризации
    scheduler.add_job(
        auto_fetch_job,
        "interval",
        hours=period_hours,
        id="auto_fetch_messages",
        args=[bot, user_client],
    )

    # Improvement #5: Сторожевая задача (каждые 15 мин)
    scheduler.add_job(
        smart_alert_job,
        "interval",
        minutes=15,
        id="smart_alert_check",
        args=[bot, user_client],
    )

    # Improvement #9: Очистка данных (раз в сутки, в 04:00)
    scheduler.add_job(
        data_cleanup_job,
        "cron",
        hour=4,
        minute=0,
        id="data_cleanup",
    )

    return scheduler


def reschedule_summary_job(scheduler: AsyncIOScheduler, new_period_hours: int):
    """Динамически перенастраивает интервал суммаризации."""
    logger.info(f"Перенастройка планировщика на {new_period_hours} ч.")
    scheduler.reschedule_job(
        "auto_fetch_messages",
        trigger="interval",
        hours=new_period_hours,
    )
