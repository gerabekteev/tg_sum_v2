import datetime
import logging
from telethon import TelegramClient
from telethon.tl.types import User, PeerChannel
import config

logger = logging.getLogger(__name__)


async def _resolve_chat_entity(client: TelegramClient, chat_peer: str):
    """
    Пытается найти чат-сущность в Telegram по ID или юзернейму.
    Автоматически обрабатывает различные форматы ID супергрупп.
    """
    if chat_peer.startswith("@"):
        return await client.get_input_entity(chat_peer)

    try:
        chat_id = int(chat_peer)
    except ValueError:
        return await client.get_input_entity(chat_peer)

    # Стратегия 1: пробуем ID как есть
    try:
        return await client.get_input_entity(chat_id)
    except (ValueError, TypeError):
        pass

    # Стратегия 2: если ID отрицательный без префикса -100
    if chat_id < 0:
        chat_id_str = str(chat_id)
        if not chat_id_str.startswith("-100"):
            raw_id = abs(chat_id)
            full_id = int(f"-100{raw_id}")
            try:
                return await client.get_input_entity(full_id)
            except (ValueError, TypeError):
                pass
            try:
                return await client.get_input_entity(PeerChannel(raw_id))
            except (ValueError, TypeError):
                pass

    # Стратегия 3: для положительных чисел
    if chat_id > 0:
        try:
            return await client.get_input_entity(PeerChannel(chat_id))
        except (ValueError, TypeError):
            pass
        try:
            return await client.get_input_entity(int(f"-100{chat_id}"))
        except (ValueError, TypeError):
            pass

    raise ValueError(
        f"Не удалось найти чат '{chat_peer}'.\n"
        f"Убедитесь, что юзербот состоит в этом чате, и формат ID верен (например, -100XXXXXXXXXX или @username)."
    )


async def fetch_messages_for_period(
    client: TelegramClient,
    chat_peer: str,
    start_time: datetime.datetime = None,
    end_time: datetime.datetime = None,
    min_id: int = None,
    include_media: bool = False,
):
    """
    Получает сообщения из чата за указанный период.
    include_media=True добавляет мета-информацию о медиа-вложениях (#6).
    Возвращает (список_словарей, форматированный_текст).
    """
    logger.info(
        f"Сбор сообщений из '{chat_peer}' (min_id={min_id}, start={start_time}, end={end_time or 'сейчас'}, media={include_media})"
    )

    # Приводим к UTC для Telethon
    if start_time:
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=datetime.timezone.utc)
        else:
            start_time = start_time.astimezone(datetime.timezone.utc)

    if end_time:
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=datetime.timezone.utc)
        else:
            end_time = end_time.astimezone(datetime.timezone.utc)
    else:
        end_time = datetime.datetime.now(datetime.timezone.utc)

    collected_messages = []

    try:
        entity = await _resolve_chat_entity(client, chat_peer)
    except Exception as e:
        logger.error(f"Не удалось получить сущность чата {chat_peer}: {e}")
        raise ValueError(str(e))

    iter_args = {"limit": None}
    if min_id is not None and min_id > 0:
        iter_args["min_id"] = int(min_id)

    async for message in client.iter_messages(entity, **iter_args):
        # Если сообщение старше начала периода — останавливаем сбор
        if start_time and message.date < start_time:
            break

        # Если сообщение новее конца периода — пропускаем
        if message.date > end_time:
            continue

        # Определяем текст сообщения
        msg_text = message.text or ""

        # Improvement #6: медиа-контент
        if include_media and message.media and not msg_text:
            from telethon.tl.types import (
                MessageMediaPhoto,
                MessageMediaDocument,
                MessageMediaWebPage,
            )

            if isinstance(message.media, MessageMediaPhoto):
                caption = message.text or ""
                msg_text = f"[📷 Фото{': ' + caption if caption else ''}]"
            elif isinstance(message.media, MessageMediaDocument):
                doc = message.media.document
                filename = ""
                if doc and doc.attributes:
                    for attr in doc.attributes:
                        if hasattr(attr, "file_name"):
                            filename = attr.file_name
                            break
                        if hasattr(attr, "duration"):
                            duration = attr.duration
                            # Голосовое или видеосообщение
                            if hasattr(attr, "voice") and attr.voice:
                                msg_text = f"[🎤 Голосовое, {duration} сек]"
                            elif hasattr(attr, "round_message") and attr.round_message:
                                msg_text = f"[🎥 Видеосообщение, {duration} сек]"
                            else:
                                msg_text = f"[🎵 Аудио/Видео, {duration} сек]"
                            break
                if not msg_text and filename:
                    msg_text = f"[📄 Документ: {filename}]"
                elif not msg_text:
                    msg_text = "[📎 Вложение]"
            elif isinstance(message.media, MessageMediaWebPage):
                msg_text = message.text or "[🔗 Ссылка]"

        # Мета-информация о пересланных сообщениях
        forward_prefix = ""
        if message.forward:
            fwd = message.forward
            fwd_name = ""
            if fwd.sender_id:
                try:
                    fwd_entity = await client.get_entity(fwd.sender_id)
                    if isinstance(fwd_entity, User):
                        fwd_name = f"{fwd_entity.first_name or ''} {fwd_entity.last_name or ''}".strip()
                    else:
                        fwd_name = getattr(fwd_entity, "title", str(fwd.sender_id))
                except Exception:
                    fwd_name = str(fwd.sender_id)
            elif fwd.from_name:
                fwd_name = fwd.from_name
            if fwd_name:
                forward_prefix = f"[🔀 Переслано от: {fwd_name}] "

        # Пропускаем, если текста нет (и медиа не включены)
        if not msg_text:
            continue

        sender = message.sender
        if sender:
            if isinstance(sender, User):
                first = sender.first_name or ""
                last = sender.last_name or ""
                sender_name = f"{first} {last}".strip() or sender.username or f"ID {sender.id}"
            else:
                sender_name = getattr(sender, "title", f"ID {sender.id}")
        else:
            sender_name = f"ID {message.sender_id or 'Unknown'}"

        collected_messages.append({
            "id": message.id,
            "date": message.date,
            "sender": sender_name,
            "text": f"{forward_prefix}{msg_text}",
        })

    # Переворачиваем в хронологический порядок
    collected_messages.reverse()

    # Формируем текст
    formatted_text_lines = []
    for msg in collected_messages:
        local_date = msg["date"].astimezone(config.TIMEZONE)
        date_str = local_date.strftime("%Y-%m-%d %H:%M:%S")
        formatted_text_lines.append(f"[{date_str}] [{msg['sender']}]: {msg['text']}\n")

    formatted_text = "".join(formatted_text_lines)

    logger.info(f"Собрано сообщений из '{chat_peer}': {len(collected_messages)}")
    return collected_messages, formatted_text


def detect_urgent_keywords(messages: list[dict]) -> list[str]:
    """
    Improvement #5: Проверяет сообщения на наличие срочных ключевых слов.
    Возвращает список найденных ключевых слов (пустой список = ничего срочного).
    """
    found = set()
    for msg in messages:
        text_lower = msg.get("text", "").lower()
        for keyword in config.URGENT_KEYWORDS:
            if keyword.lower() in text_lower:
                found.add(keyword)
    return list(found)
