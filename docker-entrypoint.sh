#!/bin/sh
set -eu

# Started as root only to make the bind-mounted ./logs writable, then re-executes
# itself as the unprivileged "app" user. The bot itself never runs as root.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/logs
    chown -R app:app /app/logs
    exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

python -m bot.wait_for_db "${DB_WAIT_TIMEOUT:-90}"
alembic upgrade head
exec python -m bot
