from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура главного меню."""
    kb = [
        [
            KeyboardButton(text="📥 За 1 час"),
            KeyboardButton(text="📥 За 4 часа"),
            KeyboardButton(text="📥 За 24 часа"),
        ],
        [
            KeyboardButton(text="🔄 Собрать новые"),
            KeyboardButton(text="📈 Статистика"),
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_settings_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура меню настроек."""
    kb = [
        [
            KeyboardButton(text="📝 Изменить чат"),
            KeyboardButton(text="⏱ Изменить период"),
        ],
        [
            KeyboardButton(text="🤖 Выбрать модель ИИ"),
            KeyboardButton(text="📋 Текущие настройки"),
        ],
        [
            KeyboardButton(text="📡 Мульти-чат"),
            KeyboardButton(text="🔔 Уведомления"),
        ],
        [
            KeyboardButton(text="🖼 Медиа-контент"),
            KeyboardButton(text="🔙 Назад в меню"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_model_selection_keyboard(current_model: str) -> InlineKeyboardMarkup:
    """Inline-клавиатура для выбора ИИ-модели."""
    models = {
        "google/gemma-4-31b-it:free": "Gemma 4 31B",
        "meta-llama/llama-3.3-70b-instruct:free": "Llama 3.3 70B",
        "qwen/qwen3-coder:free": "Qwen3 Coder",
        "nousresearch/hermes-3-llama-3.1-405b:free": "Hermes 3 405B",
        "qwen/qwen3-next-80b-a3b-instruct:free": "Qwen3 Next 80B",
        "meta-llama/llama-3.2-3b-instruct:free": "Llama 3.2 3B",
    }

    buttons = []
    for model_id, name in models.items():
        prefix = "✅ " if model_id == current_model else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{name}",
                callback_data=f"set_model:{model_id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_qa_exit_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура для выхода из режима вопросов."""
    kb = [[KeyboardButton(text="❌ Выйти из режима вопросов")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# ─── Improvement #2: Мульти-чат ───

def get_multichat_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура подменю мульти-чат."""
    kb = [
        [
            KeyboardButton(text="➕ Добавить чат"),
            KeyboardButton(text="➖ Убрать чат"),
        ],
        [
            KeyboardButton(text="📋 Список чатов"),
            KeyboardButton(text="🔙 Назад в настройки"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_chat_remove_keyboard(chats: list) -> InlineKeyboardMarkup:
    """Inline-клавиатура для удаления отслеживаемого чата."""
    buttons = []
    for chat in chats:
        name = chat.display_name or chat.chat_peer
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ {name}",
                callback_data=f"rm_chat:{chat.id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chat_select_keyboard(chats: list) -> InlineKeyboardMarkup:
    """Inline-клавиатура для выбора чата для ручного запроса."""
    buttons = []
    for chat in chats:
        name = chat.display_name or chat.chat_peer
        buttons.append([
            InlineKeyboardButton(
                text=f"📨 {name}",
                callback_data=f"sel_chat:{chat.id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
