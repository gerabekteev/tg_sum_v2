import datetime
import logging
import os
import time as _time
import asyncio

from aiogram import Router, F, BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

import config
from database.connection import SessionLocal
from database.models import (
    get_user_settings, update_user_settings, add_summary_log,
    get_monitored_chats, add_monitored_chat, remove_monitored_chat, update_monitored_chat,
    get_summary_stats, get_recent_summaries,
    add_alert_log, SummaryLog,
)
from bot.keyboards import (
    get_main_keyboard, get_settings_keyboard, get_model_selection_keyboard,
    get_qa_exit_keyboard, get_multichat_keyboard, get_chat_remove_keyboard,
)
from bot.states import UserSettingsStates
from client.telegram_client import fetch_messages_for_period
from ai.gemini import (
    summarize_messages, summarize_messages_stream, ask_llm_about_chat,
    get_cached_context, set_cached_context,
)

logger = logging.getLogger(__name__)
router = Router()


# ─── Middleware для ограничения доступа только для ADMIN_ID ───
class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and user.id == config.ADMIN_ID:
            return await handler(event, data)
        logger.warning(f"Попытка несанкционированного доступа от User ID: {user.id if user else 'Unknown'}")
        return

router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())


# ─── /start ───
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "👋 **Привет! Я бот управления Telegram-Саммаризатором V2.**\n\n"
        "Я помогу тебе собирать сообщения из выбранного чата и делать выжимки.\n"
        "Используй кнопки меню ниже для управления."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#  ОСНОВНАЯ ФУНКЦИЯ СБОРА И СУММАРИЗАЦИИ
# ═══════════════════════════════════════════════════════════════

async def process_and_send_summary(
    bot: Bot,
    chat_id: int,
    user_client,
    hours: int = None,
    since_last: bool = False,
    target_chat_peer: str = None,
    target_last_msg_id: int = None,
    target_last_run: datetime.datetime = None,
    monitored_chat_db_id: int = None,
    is_background: bool = False,
):
    """
    Основная логика: сбор → дамп → суммаризация → отправка.
    Поддерживает мульти-чат (#2) через параметры target_chat_peer и monitored_chat_db_id.
    Использует streaming (#8) для отображения прогресса.
    """
    admin_id = config.ADMIN_ID

    with SessionLocal() as db:
        settings = get_user_settings(db, admin_id)
        period_hours = settings.period_hours
        preferred_model = settings.preferred_model
        include_media = settings.include_media

    # Определяем целевой чат
    chat_target = target_chat_peer or settings.target_chat
    last_msg_id = target_last_msg_id if target_last_msg_id is not None else settings.last_message_id
    last_run = target_last_run if target_last_run is not None else settings.last_run_timestamp

    if not chat_target:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Целевой чат не указан.\n\nНажмите **⚙️ Настройки** → **📝 Изменить чат** для настройки.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown",
            disable_notification=True,
        )
        return

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    min_id = None
    start_time = None

    if since_last:
        min_id = last_msg_id if last_msg_id and last_msg_id > 0 else None
        if last_run:
            start_time = last_run.replace(tzinfo=datetime.timezone.utc) if last_run.tzinfo is None else last_run
        else:
            start_time = now_utc - datetime.timedelta(hours=period_hours)
        local_start = start_time.astimezone(config.TIMEZONE)
        period_str = f"с момента последнего запуска ({local_start.strftime('%d.%m %H:%M')})"
    else:
        start_time = now_utc - datetime.timedelta(hours=hours)
        period_str = f"за последние {hours} ч."

    # Контекст — последние 3 дня
    context_start_time = now_utc - datetime.timedelta(days=3)
    fetch_start = min(start_time, context_start_time)

    try:
        msgs, _ = await fetch_messages_for_period(
            client=user_client,
            chat_peer=chat_target,
            start_time=fetch_start,
            end_time=now_utc,
            min_id=None,
            include_media=include_media,
        )

        if not msgs:
            _update_last_run(admin_id, now_utc, monitored_chat_db_id)
            await bot.send_message(
                chat_id=chat_id,
                text=f"ℹ️ В чате `{chat_target}` не найдено сообщений {period_str}.",
                parse_mode="Markdown",
                disable_notification=True,
            )
            return

        # Разделяем на контекстные и целевые
        context_messages, target_messages = [], []
        for m in msgs:
            msg_date_utc = m["date"].astimezone(datetime.timezone.utc)
            is_target = (m["id"] > min_id) if min_id else (msg_date_utc >= start_time)
            (target_messages if is_target else context_messages).append(m)

        if not target_messages:
            _update_last_run(admin_id, now_utc, monitored_chat_db_id)
            await bot.send_message(
                chat_id=chat_id,
                text=f"ℹ️ В чате `{chat_target}` не найдено новых сообщений {period_str}.",
                parse_mode="Markdown",
                disable_notification=True,
            )
            return

        # Форматируем тексты
        target_text = _format_messages(target_messages)
        context_text = _format_messages(context_messages)

        combined_input = ""
        if context_text:
            combined_input += "ИСТОРИЯ ЧАТА ДЛЯ КОНТЕКСТА (ПОСЛЕДНИЕ 3 ДНЯ):\n"
            combined_input += context_text
            combined_input += "\n======== СВЕЖИЕ СООБЩЕНИЯ ДЛЯ СУММАРИЗАЦИИ ========\n"
            combined_input += target_text
            combined_input += "\n==================================================="
        else:
            combined_input = target_text

        # Сохраняем дамп
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_chat_name = "".join(c for c in str(chat_target) if c.isalnum() or c in ("@", "_", "-"))
        filename = f"messages_{safe_chat_name}_{timestamp_str}.txt"
        file_path = config.DUMPS_DIR / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(target_text)

        # Обновляем last_message_id
        max_id = max(m["id"] for m in target_messages)
        _update_last_run(admin_id, now_utc, monitored_chat_db_id, max_id)

        # ── Improvement #8: streaming суммаризации ──
        ai_status_msg = None
        if not is_background:
            ai_status_msg = await bot.send_message(
                chat_id=chat_id,
                text="⏳ **Генерирую ИИ-саммари (streaming)...**",
                parse_mode="Markdown",
                disable_notification=True,
            )

        try:
            t_start = _time.monotonic()
            summary = ""
            model_used = ""
            last_edit_time = 0

            async for accumulated_text, model in summarize_messages_stream(combined_input, preferred_model):
                summary = accumulated_text
                model_used = model
                # Обновляем сообщение не чаще 1 раза в 1.5 секунды (лимит Telegram)
                now = _time.monotonic()
                if now - last_edit_time >= 1.5 and ai_status_msg:
                    try:
                        display = accumulated_text[:3900] + "..." if len(accumulated_text) > 3900 else accumulated_text
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=ai_status_msg.message_id,
                            text=f"⏳ **Streaming от** `{model}`**...**\n\n{display}",
                        )
                    except Exception:
                        pass
                    last_edit_time = now

            t_elapsed = int((_time.monotonic() - t_start) * 1000)

            # Логируем в БД
            with SessionLocal() as db:
                log = add_summary_log(
                    db,
                    chat_target=chat_target,
                    messages_count=len(target_messages),
                    summary_text=summary,
                    used_model=model_used,
                    dump_file_path=str(file_path),
                    response_time_ms=t_elapsed,
                )
                log_id = log.id

            # Удаляем streaming-сообщение
            if ai_status_msg:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=ai_status_msg.message_id)
                except Exception:
                    pass

            # Финальное сообщение
            header = f"📊 **ИИ-Саммари переписки ({period_str}):**\n\n"
            stats = f"\n\n*(Проанализировано: {len(target_messages)} сообщ. за {t_elapsed}мс)*"
            footer = f"\n🤖 **Модель:** `{model_used}`"
            full_msg = f"{header}{summary}{stats}{footer}"

            is_important = not ("Нет важной информации" in summary or "🚫" in summary)

            qa_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Задать вопрос по чату", callback_data=f"ask_qa:{log_id}")]
            ])

            if len(full_msg) > 4096:
                parts = [full_msg[i:i + 4090] for i in range(0, len(full_msg), 4090)]
                for part in parts[:-1]:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        disable_notification=not is_important,
                    )
                await bot.send_message(
                    chat_id=chat_id,
                    text=parts[-1],
                    reply_markup=qa_keyboard,
                    disable_notification=not is_important,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=full_msg,
                    parse_mode="Markdown",
                    reply_markup=qa_keyboard,
                    disable_notification=not is_important,
                )

        except Exception as ai_err:
            logger.error(f"Streaming failed, fallback to non-stream: {ai_err}")
            # Fallback на обычную суммаризацию
            try:
                t_start = _time.monotonic()
                summary, model_used = await summarize_messages(combined_input, preferred_model)
                t_elapsed = int((_time.monotonic() - t_start) * 1000)

                with SessionLocal() as db:
                    log = add_summary_log(
                        db, chat_target=chat_target,
                        messages_count=len(target_messages),
                        summary_text=summary, used_model=model_used,
                        dump_file_path=str(file_path), response_time_ms=t_elapsed,
                    )
                    log_id = log.id

                if ai_status_msg:
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=ai_status_msg.message_id)
                    except Exception:
                        pass

                header = f"📊 **ИИ-Саммари переписки ({period_str}):**\n\n"
                stats = f"\n\n*(Проанализировано: {len(target_messages)} сообщ. за {t_elapsed}мс)*"
                footer = f"\n🤖 **Модель:** `{model_used}`"
                full_msg = f"{header}{summary}{stats}{footer}"

                is_important = not ("Нет важной информации" in summary or "🚫" in summary)

                qa_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Задать вопрос по чату", callback_data=f"ask_qa:{log_id}")]
                ])

                if len(full_msg) > 4096:
                    parts = [full_msg[i:i + 4090] for i in range(0, len(full_msg), 4090)]
                    for part in parts[:-1]:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=part,
                            disable_notification=not is_important,
                        )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=parts[-1],
                        reply_markup=qa_keyboard,
                        disable_notification=not is_important,
                    )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=full_msg,
                        parse_mode="Markdown",
                        reply_markup=qa_keyboard,
                        disable_notification=not is_important,
                    )

            except Exception as fallback_err:
                logger.error(f"Не удалось сгенерировать саммари: {fallback_err}")
                if ai_status_msg:
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=ai_status_msg.message_id)
                    except Exception:
                        pass
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ **Не удалось сгенерировать ИИ-саммари:**\n`{str(fallback_err)}`",
                    parse_mode="Markdown",
                    disable_notification=True,
                )

    except Exception as e:
        logger.exception("Ошибка во время сбора сообщений")
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Ошибка при сборе:\n`{str(e)}`",
            parse_mode="Markdown",
            disable_notification=True,
        )


def _format_messages(messages: list[dict]) -> str:
    """Форматирует список сообщений в текст для дампа/LLM."""
    lines = []
    for msg in messages:
        local_date = msg["date"].astimezone(config.TIMEZONE)
        date_str = local_date.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{date_str}] [{msg['sender']}]: {msg['text']}\n")
    return "".join(lines)


def _update_last_run(admin_id: int, now_utc, monitored_chat_db_id: int = None, max_id: int = None):
    """Обновляет last_run_timestamp (и опционально last_message_id) в БД."""
    with SessionLocal() as db:
        if monitored_chat_db_id:
            kwargs = {"last_run_timestamp": now_utc}
            if max_id is not None:
                kwargs["last_message_id"] = max_id
            update_monitored_chat(db, monitored_chat_db_id, **kwargs)
        else:
            kwargs = {"last_run_timestamp": now_utc}
            if max_id is not None:
                kwargs["last_message_id"] = max_id
            update_user_settings(db, admin_id, **kwargs)


# ═══════════════════════════════════════════════════════════════
#  ХЕНДЛЕРЫ ГЛАВНОГО МЕНЮ
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "📥 За 1 час")
async def process_1h(message: Message, user_client):
    await process_and_send_summary(message.bot, message.chat.id, user_client, hours=1)

@router.message(F.text == "📥 За 4 часа")
async def process_4h(message: Message, user_client):
    await process_and_send_summary(message.bot, message.chat.id, user_client, hours=4)

@router.message(F.text == "📥 За 24 часа")
async def process_24h(message: Message, user_client):
    await process_and_send_summary(message.bot, message.chat.id, user_client, hours=24)

@router.message(F.text == "🔄 Собрать новые")
async def process_since_last(message: Message, user_client):
    await process_and_send_summary(message.bot, message.chat.id, user_client, since_last=True)


# ═══════════════════════════════════════════════════════════════
#  Improvement #3: СТАТИСТИКА
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "📈 Статистика")
async def show_statistics(message: Message):
    with SessionLocal() as db:
        stats = get_summary_stats(db)
        recent = get_recent_summaries(db, limit=5)

    # Текстовая гистограмма активности
    daily = stats["daily_activity"]
    histogram = ""
    if daily:
        max_val = max(daily.values()) or 1
        for day, count in sorted(daily.items()):
            bar_len = int((count / max_val) * 10)
            bar = "█" * bar_len + "░" * (10 - bar_len)
            histogram += f"  `{day}` {bar} {count}\n"
    else:
        histogram = "  Нет данных за последние 7 дней\n"

    avg_resp = f"{stats['avg_response_ms']} мс" if stats["avg_response_ms"] else "—"

    text = (
        "📈 **Статистика системы:**\n\n"
        f"🔹 **Всего саммари:** {stats['total_summaries']}\n"
        f"🔹 **Сообщений обработано:** {stats['total_messages']}\n"
        f"🔹 **Ср. время ответа LLM:** {avg_resp}\n"
        f"🔹 **Топ модель:** `{stats['top_model']}`\n\n"
        f"📊 **Активность по дням (последние 7 дн.):**\n{histogram}\n"
    )

    # Последние саммари
    if recent:
        text += "📜 **Последние 5 саммари:**\n"
        for r in recent:
            ts = r.timestamp.strftime("%d.%m %H:%M") if r.timestamp else "?"
            text += f"  • `{ts}` — {r.chat_target} ({r.messages_count} сообщ.) `{r.used_model.split('/')[-1][:15]}`\n"

    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#  МЕНЮ НАСТРОЕК
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "⚙️ Настройки")
async def menu_settings(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "⚙️ **Меню настроек**\n\nВыберите, что хотите изменить:",
        reply_markup=get_settings_keyboard(),
        parse_mode="Markdown",
    )

@router.message(F.text == "🔙 Назад в меню")
async def menu_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 **Главное меню**", reply_markup=get_main_keyboard(), parse_mode="Markdown")

@router.message(F.text == "🔙 Назад в настройки")
async def menu_back_to_settings(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ **Настройки**", reply_markup=get_settings_keyboard(), parse_mode="Markdown")


# ─── Изменение чата (FSM) ───
@router.message(F.text == "📝 Изменить чат")
async def change_chat_start(message: Message, state: FSMContext):
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        current_chat = settings.target_chat

    await state.set_state(UserSettingsStates.awaiting_chat_id)
    await message.answer(
        f"📝 **Изменение основного чата**\n\n"
        f"Текущий: `{current_chat or 'не задан'}`\n\n"
        f"Отправьте новый ID группы или @username.\n"
        f"Или /start для отмены.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )

@router.message(UserSettingsStates.awaiting_chat_id)
async def change_chat_finish(message: Message, state: FSMContext):
    new_chat = message.text.strip()
    if not new_chat or new_chat.startswith("/"):
        await state.clear()
        await message.answer("❌ Изменение отменено.", reply_markup=get_main_keyboard())
        return

    with SessionLocal() as db:
        update_user_settings(db, config.ADMIN_ID, target_chat=new_chat, last_message_id=0)

    await state.clear()
    await message.answer(
        f"✅ **Целевой чат обновлен!**\n\nНовое значение: `{new_chat}`",
        reply_markup=get_settings_keyboard(),
        parse_mode="Markdown",
    )


# ─── Изменение периода (FSM) ───
@router.message(F.text == "⏱ Изменить период")
async def change_period_start(message: Message, state: FSMContext):
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        current_period = settings.period_hours

    await state.set_state(UserSettingsStates.awaiting_period)
    await message.answer(
        f"⏱ **Период автосбора**\n\nТекущий: **{current_period} ч.**\n\n"
        f"Отправьте число от 1 до 168.\nИли /start для отмены.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )

@router.message(UserSettingsStates.awaiting_period)
async def change_period_finish(message: Message, state: FSMContext, scheduler=None):
    text = message.text.strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    try:
        new_period = int(text)
        if new_period < 1 or new_period > 168:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Введите целое число от 1 до 168.")
        return

    with SessionLocal() as db:
        update_user_settings(db, config.ADMIN_ID, period_hours=new_period)

    reschedule_status = "⚠️ Вступит в силу при следующем перезапуске."
    if scheduler:
        try:
            from scheduler.task_scheduler import reschedule_summary_job
            reschedule_summary_job(scheduler, new_period)
            reschedule_status = "✅ Планировщик обновлён!"
        except Exception as e:
            logger.error(f"Не удалось обновить планировщик: {e}")

    await state.clear()
    await message.answer(
        f"✅ **Период обновлен: {new_period} ч.**\n{reschedule_status}",
        reply_markup=get_settings_keyboard(),
        parse_mode="Markdown",
    )


# ─── Выбор модели ───
@router.message(F.text == "🤖 Выбрать модель ИИ")
async def choose_model_start(message: Message):
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        current_model = settings.preferred_model

    await message.answer(
        "🤖 **Выбор приоритетной модели**\n\n"
        "Если модель недоступна — бот автоматически переключится на резервные.",
        reply_markup=get_model_selection_keyboard(current_model),
        parse_mode="Markdown",
    )

@router.callback_query(F.data.startswith("set_model:"))
async def choose_model_finish(callback: CallbackQuery):
    model_id = callback.data.split(":", 1)[1]
    with SessionLocal() as db:
        update_user_settings(db, config.ADMIN_ID, preferred_model=model_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_model_selection_keyboard(model_id))
    except Exception:
        pass
    await callback.answer(f"Модель: {model_id}")


# ─── Текущие настройки ───
@router.message(F.text == "📋 Текущие настройки")
async def view_current_settings(message: Message):
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        monitored = get_monitored_chats(db, config.ADMIN_ID)

    errors = config.validate_config()

    last_run_str = "Никогда"
    if settings.last_run_timestamp:
        last_run_str = settings.last_run_timestamp.astimezone(config.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    status_msg = (
        "📋 **Текущие настройки:**\n\n"
        f"🔹 **Основной чат:** `{settings.target_chat or 'не задан'}`\n"
        f"🔹 **Мониторинг чатов:** {len(monitored)} активных\n"
        f"🔹 **Приоритетная модель:** `{settings.preferred_model}`\n"
        f"🔹 **Период автосбора:** {settings.period_hours} ч.\n"
        f"🔹 **Медиа-контент:** {'✅ ВКЛ' if settings.include_media else '❌ ВЫКЛ'}\n"
        f"🔹 **Умные уведомления:** {'✅ ВКЛ' if settings.smart_alerts else '❌ ВЫКЛ'}\n"
        f"🔹 **Последний запуск:** {last_run_str}\n\n"
    )

    if errors:
        status_msg += "⚠️ **Ошибки .env:**\n"
        for err in errors:
            status_msg += f"• {err}\n"
    else:
        status_msg += "✅ Все настройки корректны."

    await message.answer(status_msg, reply_markup=get_settings_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#  Improvement #2: МУЛЬТИ-ЧАТ
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "📡 Мульти-чат")
async def multichat_menu(message: Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as db:
        chats = get_monitored_chats(db, config.ADMIN_ID)

    count_text = f"Активных чатов: **{len(chats)}**" if chats else "Нет отслеживаемых чатов."
    await message.answer(
        f"📡 **Управление мульти-чатом**\n\n{count_text}",
        reply_markup=get_multichat_keyboard(),
        parse_mode="Markdown",
    )

@router.message(F.text == "➕ Добавить чат")
async def add_chat_start(message: Message, state: FSMContext):
    await state.set_state(UserSettingsStates.awaiting_new_monitored_chat)
    await message.answer(
        "➕ **Добавление чата для мониторинга**\n\n"
        "Отправьте ID или @username группы.\n"
        "Формат: `Название чата | @username` или просто `@username`\n\n"
        "/start для отмены.",
        reply_markup=get_multichat_keyboard(),
        parse_mode="Markdown",
    )

@router.message(UserSettingsStates.awaiting_new_monitored_chat)
async def add_chat_finish(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_multichat_keyboard())
        return

    # Парсим формат "Название | @chat" или просто "@chat"
    if "|" in text:
        parts = text.split("|", 1)
        display_name = parts[0].strip()
        chat_peer = parts[1].strip()
    else:
        chat_peer = text
        display_name = text

    with SessionLocal() as db:
        chat = add_monitored_chat(db, config.ADMIN_ID, chat_peer, display_name)

    await state.clear()
    await message.answer(
        f"✅ **Чат добавлен!**\n\n"
        f"📌 **Название:** {chat.display_name}\n"
        f"🔗 **ID/Username:** `{chat.chat_peer}`",
        reply_markup=get_multichat_keyboard(),
        parse_mode="Markdown",
    )

@router.message(F.text == "➖ Убрать чат")
async def remove_chat_menu(message: Message):
    with SessionLocal() as db:
        chats = get_monitored_chats(db, config.ADMIN_ID)

    if not chats:
        await message.answer("ℹ️ Нет активных чатов для удаления.", reply_markup=get_multichat_keyboard())
        return

    await message.answer(
        "➖ **Выберите чат для удаления:**",
        reply_markup=get_chat_remove_keyboard(chats),
        parse_mode="Markdown",
    )

@router.callback_query(F.data.startswith("rm_chat:"))
async def remove_chat_callback(callback: CallbackQuery):
    chat_id = int(callback.data.split(":")[1])
    with SessionLocal() as db:
        success = remove_monitored_chat(db, chat_id)

    if success:
        await callback.answer("Чат удалён из мониторинга")
        # Обновляем список
        with SessionLocal() as db:
            chats = get_monitored_chats(db, config.ADMIN_ID)
        if chats:
            try:
                await callback.message.edit_reply_markup(reply_markup=get_chat_remove_keyboard(chats))
            except Exception:
                pass
        else:
            try:
                await callback.message.edit_text("✅ Все чаты удалены.")
            except Exception:
                pass
    else:
        await callback.answer("Ошибка при удалении")

@router.message(F.text == "📋 Список чатов")
async def list_chats(message: Message):
    with SessionLocal() as db:
        chats = get_monitored_chats(db, config.ADMIN_ID)

    if not chats:
        await message.answer("ℹ️ Нет отслеживаемых чатов.", reply_markup=get_multichat_keyboard())
        return

    text = "📋 **Отслеживаемые чаты:**\n\n"
    for i, chat in enumerate(chats, 1):
        last_run = "никогда"
        if chat.last_run_timestamp:
            last_run = chat.last_run_timestamp.strftime("%d.%m %H:%M")
        text += (
            f"**{i}.** {chat.display_name}\n"
            f"   🔗 `{chat.chat_peer}`\n"
            f"   📅 Последний сбор: {last_run}\n\n"
        )

    await message.answer(text, reply_markup=get_multichat_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#  Improvement #5: УМНЫЕ УВЕДОМЛЕНИЯ (toggle)
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "🔔 Уведомления")
async def toggle_alerts(message: Message):
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        new_val = not settings.smart_alerts
        update_user_settings(db, config.ADMIN_ID, smart_alerts=new_val)

    status = "✅ ВКЛ" if new_val else "❌ ВЫКЛ"
    text = (
        f"🔔 **Умные уведомления: {status}**\n\n"
    )
    if new_val:
        text += (
            "Бот будет каждые 15 минут проверять свежие сообщения на наличие "
            "ключевых слов (дедлайн, экзамен, срочно и т.д.) и присылать push-алерт.\n\n"
            f"⏳ Кулдаун: {config.ALERT_COOLDOWN_MINUTES} мин."
        )
    else:
        text += "Push-уведомления отключены."

    await message.answer(text, reply_markup=get_settings_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#  Improvement #6: МЕДИА-КОНТЕНТ (toggle)
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "🖼 Медиа-контент")
async def toggle_media(message: Message):
    with SessionLocal() as db:
        settings = get_user_settings(db, config.ADMIN_ID)
        new_val = not settings.include_media
        update_user_settings(db, config.ADMIN_ID, include_media=new_val)

    status = "✅ ВКЛ" if new_val else "❌ ВЫКЛ"
    text = (
        f"🖼 **Медиа-контент: {status}**\n\n"
    )
    if new_val:
        text += (
            "В саммари будут включены мета-данные о фото, документах, голосовых и пересланных сообщениях.\n\n"
            "⚠️ Это увеличивает объём контекста для LLM."
        )
    else:
        text += "Обрабатываются только текстовые сообщения."

    await message.answer(text, reply_markup=get_settings_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#  Q&A РЕЖИМ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ask_qa:"))
async def callback_ask_qa(callback: CallbackQuery, state: FSMContext):
    log_id = int(callback.data.split(":")[1])
    await state.set_state(UserSettingsStates.awaiting_question)
    await state.update_data(active_log_id=log_id)

    await callback.message.answer(
        "💬 **Режим вопросов активирован**\n\n"
        "Задайте любой вопрос по переписке.\n"
        "*Нажмите кнопку ниже для выхода.*",
        reply_markup=get_qa_exit_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()

@router.message(UserSettingsStates.awaiting_question)
async def process_qa_question(message: Message, state: FSMContext):
    text = message.text.strip()

    if text == "❌ Выйти из режима вопросов" or text.startswith("/"):
        await state.clear()
        await message.answer("🏠 **Режим вопросов отключен.**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        return

    data = await state.get_data()
    log_id = data.get("active_log_id")
    if not log_id:
        await state.clear()
        await message.answer("❌ Сессия устарела. Возврат в меню.", reply_markup=get_main_keyboard())
        return

    # Improvement #4: используем кеш контекста
    chat_text = get_cached_context(log_id)

    if not chat_text:
        with SessionLocal() as db:
            log = db.query(SummaryLog).filter(SummaryLog.id == log_id).first()
            settings = get_user_settings(db, config.ADMIN_ID)
            preferred_model = settings.preferred_model

        if not log or not log.dump_file_path or not os.path.exists(log.dump_file_path):
            await message.answer("❌ Файл переписки не найден.", reply_markup=get_main_keyboard())
            await state.clear()
            return

        with open(log.dump_file_path, "r", encoding="utf-8") as f:
            chat_text = f.read()

        set_cached_context(log_id, chat_text)
    else:
        with SessionLocal() as db:
            settings = get_user_settings(db, config.ADMIN_ID)
            preferred_model = settings.preferred_model

    status_msg = await message.answer("⏳ **Думаю над ответом...**")

    try:
        answer, model_used = await ask_llm_about_chat(chat_text, text, preferred_model)
        await status_msg.delete()
        response_msg = f"{answer}\n\n*(Модель: `{model_used}`)*"
        await message.answer(response_msg, reply_markup=get_qa_exit_keyboard())
    except Exception as e:
        logger.exception("Ошибка Q&A")
        try:
            await status_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"⚠️ **Не удалось получить ответ:**\n`{e}`\n\nПопробуйте ещё раз.",
            reply_markup=get_qa_exit_keyboard(),
        )
