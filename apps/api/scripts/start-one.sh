#!/bin/sh
set -eu

: "${SELECONT_DATABASE:?Set SELECONT_DATABASE to the SQLite file on persistent storage}"
: "${SELECONT_MEDIA_ROOT:?Set SELECONT_MEDIA_ROOT to the private media directory on persistent storage}"
: "${SELECONT_SECRET_KEY:?Set SELECONT_SECRET_KEY to at least 32 bytes}"

export PYTHONPATH="apps/api${PYTHONPATH:+:$PYTHONPATH}"
exec python -m uvicorn selecont.web:app --host "${SELECONT_BIND_HOST:-127.0.0.1}" --port "${PORT:-8000}" --workers 1
