# Single stage on purpose: every dependency (asyncmy, cryptography, greenlet, ...)
# ships prebuilt manylinux wheels, so no compiler toolchain is ever installed and a
# builder stage would not make the final image meaningfully smaller.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini babel.cfg ./
COPY migrations ./migrations
COPY bot ./bot

# Compile translations (.po -> .mo) at build time; .mo files are not in git.
RUN pybabel compile -d bot/locales -D messages \
 && mkdir -p /app/logs \
 && chown -R app:app /app

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The entrypoint starts as root just long enough to fix ./logs ownership, then
# drops to the "app" user (uid 10001) before running migrations and the bot.
ENTRYPOINT ["docker-entrypoint.sh"]
