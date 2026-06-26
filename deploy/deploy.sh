#!/usr/bin/env bash
# ============================================================
# Telegram Summarizer V2 — Скрипт развертывания (systemd)
# ============================================================
# Использование:
#   sudo ./deploy/deploy.sh
#
# Что делает этот скрипт:
#   1. Проверяет наличие виртуального окружения и зависимостей
#   2. Устанавливает правильные права доступа
#   3. Копирует systemd unit-файл
#   4. Включает и запускает сервис
#
# ВАЖНО: Перед запуском убедитесь, что:
#   - .env файл заполнен корректно
#   - Юзербот авторизован (файл сессии в sessions/)
#   - В tg_summarizer.service указаны правильные пути
# ============================================================

set -euo pipefail

# ─── Цвета для вывода ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "============================================"
echo "  Telegram Summarizer V2 — Деплой"
echo "============================================"
echo ""

# ─── Проверка прав root ───
if [ "$EUID" -ne 0 ]; then
    log_error "Этот скрипт необходимо запускать с правами root (sudo)."
    echo "  Использование: sudo ./deploy/deploy.sh"
    exit 1
fi

# ─── Определяем директории ───
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_FILE="$SCRIPT_DIR/tg_summarizer.service"
SYSTEMD_DIR="/etc/systemd/system"

log_info "Директория проекта: $PROJECT_DIR"

# ─── Шаг 1: Проверка необходимых файлов ───
log_info "Проверка необходимых файлов..."

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log_error "Файл .env не найден! Сначала выполните ./deploy/setup.sh"
    exit 1
fi
log_ok "Файл .env найден."

if [ ! -f "$PROJECT_DIR/main.py" ]; then
    log_error "Файл main.py не найден! Убедитесь, что проект полный."
    exit 1
fi
log_ok "Файл main.py найден."

if [ ! -f "$SERVICE_FILE" ]; then
    log_error "Файл tg_summarizer.service не найден в deploy/"
    exit 1
fi
log_ok "Файл systemd unit найден."

# ─── Шаг 2: Проверка виртуального окружения ───
log_info "Проверка виртуального окружения..."

if [ ! -d "$VENV_DIR" ]; then
    log_warn "Виртуальное окружение не найдено. Создаем..."

    # Ищем подходящий Python
    PYTHON_CMD=""
    for cmd in python3.13 python3.12 python3.11 python3; do
        if command -v "$cmd" &>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        log_error "Python 3 не найден!"
        exit 1
    fi

    $PYTHON_CMD -m venv "$VENV_DIR"
    log_ok "Виртуальное окружение создано."
fi

# ─── Шаг 3: Установка/обновление зависимостей ───
log_info "Установка зависимостей..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --quiet
log_ok "Зависимости установлены."

# ─── Шаг 4: Установка прав доступа ───
log_info "Установка прав доступа..."

# Определяем реального пользователя (даже при запуске через sudo)
REAL_USER="${SUDO_USER:-$(whoami)}"
REAL_GROUP="$(id -gn "$REAL_USER")"

# Устанавливаем владельца
chown -R "$REAL_USER:$REAL_GROUP" "$PROJECT_DIR"

# Защищаем файл с секретами
chmod 600 "$PROJECT_DIR/.env"

# Права на исполняемые скрипты
chmod +x "$SCRIPT_DIR/setup.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/deploy.sh" 2>/dev/null || true

log_ok "Права доступа установлены. Владелец: $REAL_USER:$REAL_GROUP"

# ─── Шаг 5: Обновление и копирование systemd unit-файла ───
log_info "Настройка systemd сервиса..."

# Создаем временную копию с подставленными значениями
TEMP_SERVICE=$(mktemp)
sed \
    -e "s|YOUR_USERNAME|$REAL_USER|g" \
    -e "s|/opt/Tg_sum_V2|$PROJECT_DIR|g" \
    "$SERVICE_FILE" > "$TEMP_SERVICE"

# Копируем в systemd
cp "$TEMP_SERVICE" "$SYSTEMD_DIR/tg_summarizer.service"
rm -f "$TEMP_SERVICE"

log_ok "Systemd unit-файл установлен."

# ─── Шаг 6: Активация и запуск сервиса ───
log_info "Перезагрузка systemd daemon..."
systemctl daemon-reload

log_info "Включение автозапуска сервиса..."
systemctl enable tg_summarizer

# Проверяем, запущен ли уже сервис
if systemctl is-active --quiet tg_summarizer; then
    log_info "Сервис уже запущен. Перезапуск..."
    systemctl restart tg_summarizer
else
    log_info "Запуск сервиса..."
    systemctl start tg_summarizer
fi

# Ждем пару секунд и проверяем статус
sleep 2

if systemctl is-active --quiet tg_summarizer; then
    log_ok "Сервис tg_summarizer успешно запущен!"
else
    log_error "Сервис не удалось запустить. Проверьте логи:"
    echo "  sudo journalctl -u tg_summarizer -n 30 --no-pager"
    exit 1
fi

# ─── Итог ───
echo ""
echo "============================================"
echo -e "  ${GREEN}✅ Деплой завершен!${NC}"
echo "============================================"
echo ""
echo "  Полезные команды:"
echo ""
echo "  # Статус сервиса"
echo "  sudo systemctl status tg_summarizer"
echo ""
echo "  # Логи в реальном времени"
echo "  sudo journalctl -u tg_summarizer -f"
echo ""
echo "  # Перезапуск"
echo "  sudo systemctl restart tg_summarizer"
echo ""
echo "  # Остановка"
echo "  sudo systemctl stop tg_summarizer"
echo ""
