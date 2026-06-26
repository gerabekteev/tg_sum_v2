# 🤖 Telegram Summarizer V2

**Telegram-бот для автоматической суммаризации чатов с помощью LLM через OpenRouter API.**

Бот собирает сообщения из целевого группового чата Telegram с помощью юзербота (Telethon), анализирует их через бесплатные LLM-модели (OpenRouter) и формирует краткую выжимку — саммари. Управление осуществляется через отдельного Telegram-бота на базе aiogram 3.

---

## ✨ Возможности

- 📥 **Сбор сообщений** — за 1 час, 4 часа, 24 часа или с момента последнего запуска
- 🤖 **Умная суммаризация** — ИИ анализирует переписку и выделяет только важное (дедлайны, задачи, объявления), отсеивая флуд
- 📊 **3-дневный контекст** — LLM получает контекст переписки за последние 3 дня для более точного анализа
- 💬 **Режим Q&A** — возможность задавать вопросы по содержимому чата после получения саммари
- ⚡ **Автоматический фоновый сбор** — настраиваемый периодический сбор сообщений через APScheduler
- 🔄 **Выбор модели ИИ** — переключение между бесплатными моделями OpenRouter (Gemma, Llama, Qwen и др.)
- 📁 **Дампы переписок** — сохранение собранных сообщений в текстовые файлы
- 📋 **Логирование саммари** — история всех суммаризаций сохраняется в SQLite БД
- 🔒 **Ограничение доступа** — управление ботом доступно только администратору (ADMIN_ID)
- ⚙️ **Гибкие настройки** — смена целевого чата, периода автосбора и модели ИИ прямо из бота

---

## 📋 Требования

- **Python 3.11+**
- **Telegram API credentials** — `API_ID` и `API_HASH` (получить на [my.telegram.org](https://my.telegram.org/))
- **Telegram Bot Token** — токен бота от [@BotFather](https://t.me/BotFather)
- **OpenRouter API Key** — ключ для доступа к LLM (получить на [openrouter.ai](https://openrouter.ai/))
- **Номер телефона** — для авторизации юзербота Telethon

---

## 🏗️ Архитектура проекта

```
Tg_sum_V2/
├── main.py                  # Точка входа — запуск бота и юзербота
├── config.py                # Конфигурация из .env
├── requirements.txt         # Зависимости Python
├── .env                     # Переменные окружения (не в Git!)
├── .env.example             # Шаблон переменных окружения
│
├── bot/                     # Модуль aiogram-бота
│   ├── __init__.py
│   ├── handlers.py          # Обработчики команд и кнопок
│   ├── keyboards.py         # Клавиатуры (ReplyKeyboard, InlineKeyboard)
│   └── states.py            # FSM-состояния (смена чата, периода, Q&A)
│
├── ai/                      # Модуль работы с LLM
│   ├── __init__.py
│   └── gemini.py            # Вызовы OpenRouter API (суммаризация, Q&A)
│
├── client/                  # Модуль Telethon-юзербота
│   ├── __init__.py
│   └── telegram_client.py   # Сбор сообщений из целевого чата
│
├── database/                # Модуль базы данных
│   ├── __init__.py
│   ├── connection.py        # Подключение SQLAlchemy + SessionLocal
│   └── models.py            # Модели (UserSettings, SummaryLog) + CRUD
│
├── scheduler/               # Модуль планировщика
│   ├── __init__.py
│   └── task_scheduler.py    # Инициализация и управление APScheduler
│
├── deploy/                  # Скрипты деплоя
│   ├── deploy.sh            # Скрипт развертывания на сервере
│   ├── setup.sh             # Скрипт первоначальной настройки
│   └── tg_summarizer.service # Systemd unit-файл
│
├── dumps/                   # Дампы собранных сообщений (не в Git)
├── sessions/                # Файлы сессий Telethon (не в Git)
└── tg_sum.db                # SQLite база данных (не в Git)
```

---

## 🚀 Установка и запуск

### 1. Клонирование репозитория

```bash
git clone https://github.com/your-username/Tg_sum_V2.git
cd Tg_sum_V2
```

### 2. Создание виртуального окружения

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка переменных окружения

```bash
cp .env.example .env
nano .env  # Отредактируйте файл, заполнив все значения
```

Подробное описание переменных см. в разделе [Конфигурация .env](#-конфигурация-env).

### 5. Первый запуск (авторизация юзербота)

При первом запуске Telethon попросит ввести код авторизации из Telegram:

```bash
python main.py
```

> **Важно:** файл сессии сохранится в папке `sessions/`. При переносе на сервер скопируйте этот файл вместе с проектом.

### 6. Последующие запуски

```bash
python main.py
```

---

## ⚙️ Конфигурация .env

| Переменная | Описание | Пример |
|---|---|---|
| `TELEGRAM_API_ID` | ID приложения Telegram API (число) | `12345678` |
| `TELEGRAM_API_HASH` | Хеш приложения Telegram API | `0123456789abcdef0123456789abcdef` |
| `TELEGRAM_PHONE` | Номер телефона аккаунта для юзербота | `+79001234567` |
| `BOT_TOKEN` | Токен управляющего бота от @BotFather | `123456789:ABCdefGhIjKlMnOpQrStUvWxYz` |
| `ADMIN_ID` | Ваш Telegram User ID (узнать у @userinfobot) | `123456789` |
| `TARGET_CHAT` | ID или @username целевого чата | `@my_group` или `-1001234567890` |
| `DEFAULT_PERIOD_HOURS` | Период автосбора по умолчанию (в часах) | `4` |
| `TIMEZONE` | Часовой пояс для отчетов | `Europe/Moscow` |
| `OPENROUTER_API_KEY` | API-ключ OpenRouter для доступа к LLM | `sk-or-v1-...` |

---

## 🐧 Деплой на Linux-сервер (systemd)

### Быстрый деплой

```bash
# 1. Первоначальная настройка
chmod +x deploy/setup.sh deploy/deploy.sh
./deploy/setup.sh

# 2. Заполните .env файл
nano .env

# 3. Выполните авторизацию юзербота (первый раз — интерактивно)
source .venv/bin/activate
python main.py
# После успешной авторизации остановите (Ctrl+C)

# 4. Разверните как systemd-сервис
sudo ./deploy/deploy.sh
```

### Ручной деплой

#### 1. Подготовка окружения

```bash
cd /opt/Tg_sum_V2  # или ваш путь
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. Настройка systemd

Отредактируйте файл `deploy/tg_summarizer.service`:
- Укажите `User=` — имя пользователя Linux
- Укажите `WorkingDirectory=` — путь к проекту
- Укажите `ExecStart=` — путь к Python и main.py

```bash
sudo cp deploy/tg_summarizer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tg_summarizer
sudo systemctl start tg_summarizer
```

#### 3. Управление сервисом

```bash
# Статус
sudo systemctl status tg_summarizer

# Логи (в реальном времени)
sudo journalctl -u tg_summarizer -f

# Перезапуск
sudo systemctl restart tg_summarizer

# Остановка
sudo systemctl stop tg_summarizer
```

---

## 🔧 Управление ботом

После запуска напишите боту `/start` в Telegram. Доступные команды через кнопки меню:

| Кнопка | Действие |
|---|---|
| 📥 За 1 час | Собрать и суммаризировать сообщения за последний час |
| 📥 За 4 часа | Собрать и суммаризировать за 4 часа |
| 📥 За 24 часа | Собрать и суммаризировать за 24 часа |
| 🔄 Собрать новые | Собрать с момента последнего запуска |
| ⚙️ Настройки | Меню настроек (чат, период, модель) |
| 💬 Задать вопрос по чату | Режим Q&A по последнему саммари |

---

## 🤖 Поддерживаемые модели ИИ

Бот использует бесплатные модели через OpenRouter API:

| Модель | Описание |
|---|---|
| `google/gemma-4-31b-it:free` | Google Gemma 4 31B (по умолчанию) |
| `meta-llama/llama-3.3-70b-instruct:free` | Meta Llama 3.3 70B |
| `qwen/qwen3-coder:free` | Qwen3 Coder |
| `nousresearch/hermes-3-llama-3.1-405b:free` | Hermes 3 Llama 405B |
| `qwen/qwen3-next-80b-a3b-instruct:free` | Qwen3 Next 80B |
| `meta-llama/llama-3.2-3b-instruct:free` | Meta Llama 3.2 3B (резервная) |

При недоступности выбранной модели бот автоматически переключается на следующую в списке.

---

## 🛡️ Безопасность

- Файл `.env` содержит секретные ключи — **никогда** не коммитьте его в Git
- Папки `sessions/` и `dumps/` содержат чувствительные данные — добавлены в `.gitignore`
- Доступ к боту ограничен через `AdminMiddleware` — только пользователь с `ADMIN_ID` может управлять ботом

---

## 📝 Лицензия

Этот проект распространяется под лицензией [MIT](https://opensource.org/licenses/MIT).

```
MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
#   t g _ s u m _ v 2  
 