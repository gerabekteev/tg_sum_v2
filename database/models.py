import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean
from database.connection import Base
import config


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id = Column(BigInteger, primary_key=True, index=True)
    target_chat = Column(String, nullable=True, default=config.DEFAULT_TARGET_CHAT)
    period_hours = Column(Integer, default=config.DEFAULT_PERIOD_HOURS)
    timezone = Column(String, default=config.TIMEZONE_STR)
    preferred_model = Column(String, default="google/gemma-4-31b-it:free")
    last_message_id = Column(Integer, default=0)
    last_run_timestamp = Column(DateTime, nullable=True)
    # Improvement #6: переключатель медиа-контента
    include_media = Column(Boolean, default=False)
    # Improvement #5: умные уведомления
    smart_alerts = Column(Boolean, default=False)


class MonitoredChat(Base):
    """Improvement #2: отслеживаемые чаты для мульти-чат режима."""
    __tablename__ = "monitored_chats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_peer = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_message_id = Column(Integer, default=0)
    last_run_timestamp = Column(DateTime, nullable=True)
    added_at = Column(DateTime, default=datetime.datetime.utcnow)


class SummaryLog(Base):
    __tablename__ = "summary_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_target = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    messages_count = Column(Integer, nullable=False)
    summary_text = Column(String, nullable=False)
    used_model = Column(String, nullable=False)
    dump_file_path = Column(String, nullable=True)
    # Improvement #3: время ответа модели в мс
    response_time_ms = Column(Integer, nullable=True)


class AlertLog(Base):
    """Improvement #5: лог отправленных алертов для кулдауна."""
    __tablename__ = "alert_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_target = Column(String, nullable=False)
    alert_text = Column(String, nullable=False)
    keywords_found = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    sent_to_user = Column(Boolean, default=True)


# ─── CRUD Хелперы ───

def get_user_settings(db, user_id: int) -> UserSettings:
    """Получает настройки для пользователя. Создает дефолтные, если их нет."""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings:
        settings = UserSettings(
            user_id=user_id,
            target_chat=config.DEFAULT_TARGET_CHAT,
            period_hours=config.DEFAULT_PERIOD_HOURS,
            timezone=config.TIMEZONE_STR,
            preferred_model="google/gemma-4-31b-it:free",
            last_message_id=0,
            last_run_timestamp=None,
            include_media=False,
            smart_alerts=False,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_user_settings(db, user_id: int, **kwargs) -> UserSettings:
    """Обновляет настройки пользователя."""
    settings = get_user_settings(db, user_id)
    for key, value in kwargs.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings


def add_summary_log(
    db,
    chat_target: str,
    messages_count: int,
    summary_text: str,
    used_model: str,
    dump_file_path: str = None,
    response_time_ms: int = None,
) -> SummaryLog:
    """Добавляет запись лога суммаризации."""
    log = SummaryLog(
        chat_target=chat_target,
        messages_count=messages_count,
        summary_text=summary_text,
        used_model=used_model,
        dump_file_path=dump_file_path,
        response_time_ms=response_time_ms,
        timestamp=datetime.datetime.utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ─── CRUD: MonitoredChat (Improvement #2) ───

def get_monitored_chats(db, user_id: int, active_only: bool = True) -> list[MonitoredChat]:
    """Возвращает список отслеживаемых чатов пользователя."""
    query = db.query(MonitoredChat).filter(MonitoredChat.user_id == user_id)
    if active_only:
        query = query.filter(MonitoredChat.is_active == True)
    return query.all()


def add_monitored_chat(db, user_id: int, chat_peer: str, display_name: str = None) -> MonitoredChat:
    """Добавляет чат в список отслеживаемых."""
    existing = db.query(MonitoredChat).filter(
        MonitoredChat.user_id == user_id,
        MonitoredChat.chat_peer == chat_peer,
    ).first()
    if existing:
        existing.is_active = True
        existing.display_name = display_name or existing.display_name
        db.commit()
        db.refresh(existing)
        return existing

    chat = MonitoredChat(
        user_id=user_id,
        chat_peer=chat_peer,
        display_name=display_name or chat_peer,
        is_active=True,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


def remove_monitored_chat(db, chat_id: int) -> bool:
    """Деактивирует чат из списка отслеживаемых."""
    chat = db.query(MonitoredChat).filter(MonitoredChat.id == chat_id).first()
    if chat:
        chat.is_active = False
        db.commit()
        return True
    return False


def update_monitored_chat(db, chat_id: int, **kwargs) -> MonitoredChat | None:
    """Обновляет параметры отслеживаемого чата."""
    chat = db.query(MonitoredChat).filter(MonitoredChat.id == chat_id).first()
    if not chat:
        return None
    for key, value in kwargs.items():
        if hasattr(chat, key):
            setattr(chat, key, value)
    db.commit()
    db.refresh(chat)
    return chat


# ─── CRUD: AlertLog (Improvement #5) ───

def add_alert_log(db, chat_target: str, alert_text: str, keywords_found: str = None) -> AlertLog:
    """Добавляет запись алерта."""
    alert = AlertLog(
        chat_target=chat_target,
        alert_text=alert_text,
        keywords_found=keywords_found,
        timestamp=datetime.datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def get_recent_alert(db, chat_target: str, minutes: int) -> AlertLog | None:
    """Проверяет, был ли алерт для этого чата за последние N минут (кулдаун)."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)
    return db.query(AlertLog).filter(
        AlertLog.chat_target == chat_target,
        AlertLog.timestamp >= cutoff,
    ).first()


# ─── Хелперы для статистики (Improvement #3) ───

def get_summary_stats(db) -> dict:
    """Возвращает сводную статистику по всем суммаризациям."""
    from sqlalchemy import func

    total = db.query(func.count(SummaryLog.id)).scalar() or 0
    total_messages = db.query(func.sum(SummaryLog.messages_count)).scalar() or 0
    avg_response = db.query(func.avg(SummaryLog.response_time_ms)).filter(
        SummaryLog.response_time_ms.isnot(None)
    ).scalar()

    # Самая используемая модель
    top_model_row = (
        db.query(SummaryLog.used_model, func.count(SummaryLog.id).label("cnt"))
        .group_by(SummaryLog.used_model)
        .order_by(func.count(SummaryLog.id).desc())
        .first()
    )
    top_model = top_model_row[0] if top_model_row else "—"

    # Активность по дням (последние 7 дней)
    week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    daily_counts = {}
    logs = db.query(SummaryLog).filter(SummaryLog.timestamp >= week_ago).all()
    for log in logs:
        day = log.timestamp.strftime("%d.%m")
        daily_counts[day] = daily_counts.get(day, 0) + log.messages_count

    return {
        "total_summaries": total,
        "total_messages": total_messages,
        "avg_response_ms": round(avg_response) if avg_response else None,
        "top_model": top_model,
        "daily_activity": daily_counts,
    }


def get_recent_summaries(db, limit: int = 5) -> list[SummaryLog]:
    """Последние N записей суммаризации."""
    return db.query(SummaryLog).order_by(SummaryLog.timestamp.desc()).limit(limit).all()
