from aiogram.fsm.state import StatesGroup, State


class UserSettingsStates(StatesGroup):
    awaiting_chat_id = State()
    awaiting_period = State()
    awaiting_question = State()
    # Improvement #2: мульти-чат
    awaiting_new_monitored_chat = State()
