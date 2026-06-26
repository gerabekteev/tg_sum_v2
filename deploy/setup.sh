#!/usr/bin/env bash
# ============================================================
# Telegram Summarizer V2 — Скрипт первоначальной настройки
# ============================================================
# Использование:
#   chmod +x deploy/setup.sh
#   ./deploy/setup.sh
# ============================================================

set -euo pipefail

# ─── Цвета для вывода ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─── Функции логирования ───
log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "============================================"
echo "  Telegram Summarizer V2 — Настройка"
echo "============================================"
echo ""

# ─── Определяем корневую директорию проекта ───
# Скрипт должен работать из любого места
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
log_info "Директория проекта: $PROJECT_DIR"

# ─── Шаг 1: Проверка версии Python ───
log_info "Проверка версии Python..."

PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    log_error "Python 3 не найден! Установите Python 3.11 или выше."
    log_error "  Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    log_error "  CentOS/RHEL:   sudo dnf install python3.11"
    exit 1
fi

# Проверяем минимальную версию (3.11)
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    log_error "Требуется Python 3.11+, найден: $PYTHON_VERSION"
    log_error "Установите Python 3.11 или выше и повторите попытку."
    exit 1
fi

log_ok "Python $PYTHON_VERSION найден: $(command -v $PYTHON_CMD)"

# ─── Шаг 2: Создание виртуального окружения ───
VENV_DIR="$PROJECT_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    log_warn "Виртуальное окружение уже существует: $VENV_DIR"
    read -p "Пересоздать? (y/N): " RECREATE
    if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
        log_info "Удаление старого окружения..."
        rm -rf "$VENV_DIR"
        log_info "Создание нового виртуального окружения..."
        $PYTHON_CMD -m venv "$VENV_DIR"
        log_ok "Виртуальное окружение пересоздано."
    else
        log_info "Используем существующее окружение."
    fi
else
    log_info "Создание виртуального окружения..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    log_ok "Виртуальное окружение создано: $VENV_DIR"
fi

# ─── Шаг 3: Активация окружения и установка зависимостей ───
log_info "Активация виртуального окружения..."
source "$VENV_DIR/bin/activate"

log_info "Обновление pip..."
pip install --upgrade pip --quiet

if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
    log_error "Файл requirements.txt не найден!"
    exit 1
fi

log_info "Установка зависимостей из requirements.txt..."
pip install -r "$PROJECT_DIR/requirements.txt"
log_ok "Все зависимости установлены."

# ─── Шаг 4: Создание .env из шаблона ───
if [ -f "$PROJECT_DIR/.env" ]; then
    log_warn "Файл .env уже существует. Пропускаем создание."
    log_warn "Если нужно пересоздать, удалите .env и запустите скрипт снова."
else
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        chmod 600 "$PROJECT_DIR/.env"
        log_ok "Файл .env создан из .env.example"
        log_warn "⚠️  Обязательно заполните .env реальными значениями!"
        log_warn "    nano $PROJECT_DIR/.env"
    else
        log_error "Файл .env.example не найден! Создайте .env вручную."
    fi
fi

# ─── Шаг 5: Создание необходимых директорий ───
log_info "Создание рабочих директорий..."

mkdir -p "$PROJECT_DIR/dumps"
mkdir -p "$PROJECT_DIR/sessions"

log_ok "Директория dumps/ создана."
log_ok "Директория sessions/ создана."

# ─── Итог ───
echo ""
echo "============================================"
echo -e "  ${GREEN}✅ Настройка завершена!${NC}"
echo "============================================"
echo ""
echo "  Следующие шаги:"
echo ""
echo "  1. Заполните .env файл:"
echo "     nano $PROJECT_DIR/.env"
echo ""
echo "  2. Выполните первый запуск для авторизации юзербота:"
echo "     source $VENV_DIR/bin/activate"
echo "     python main.py"
echo ""
echo "  3. Для деплоя как systemd-сервис:"
echo "     sudo ./deploy/deploy.sh"
echo ""
