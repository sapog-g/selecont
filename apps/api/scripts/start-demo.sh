#!/bin/sh
set -eu

# One-command local launcher for the closed demo.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)
cd "$PROJECT_ROOT"

VENV="$PROJECT_ROOT/apps/api/.venv"
PYTHON="$VENV/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Создаю локальное окружение и устанавливаю зависимости..."
  python3 -m venv "$VENV"
  "$PYTHON" -m pip install -r apps/api/requirements.lock
fi

DB="$PROJECT_ROOT/apps/api/var/selecont.sqlite3"
MEDIA="$PROJECT_ROOT/apps/api/var/media"
mkdir -p "$PROJECT_ROOT/apps/api/var" "$MEDIA"

if [ ! -s "$DB" ]; then
  echo "Первый запуск: придумай один пароль для тестовых аккаунтов."
  PYTHONPATH=apps/api "$PYTHON" -m selecont.cli --db "$DB" seed-demo
fi

export PATH="$VENV/bin:$PATH"
export SELECONT_DATABASE="$DB"
export SELECONT_MEDIA_ROOT="$MEDIA"
export SELECONT_SECRET_KEY="${SELECONT_SECRET_KEY:-$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export SELECONT_BIND_HOST=127.0.0.1
export PORT="${PORT:-8000}"

echo "Сервер selecont запущен: http://127.0.0.1:$PORT/demo-guide"
echo "Чтобы остановить его, нажми Ctrl+C."
exec apps/api/scripts/start-one.sh
