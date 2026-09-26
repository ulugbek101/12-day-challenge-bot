# Stylist Challenge — payment verification bot

A Telegram bot that sits between paying clients and the admins of the private
**Stylist Challenge** channel:

1. A client sends a payment screenshot, their full name and phone number.
2. Admins review it in a single-message admin panel and approve or reject it.
3. On approval the bot creates a **personal invite link** that only works for that
   client. Anyone else who uses it, admins included, is declined automatically.

Stack: Python 3.12, aiogram 3 (long polling), MySQL 8 (SQLAlchemy 2.0 async + asyncmy),
Alembic, gettext i18n (Russian / Uzbek Latin), Docker Compose.

---

## 1. Telegram setup

**Create the bot.** In [@BotFather](https://t.me/BotFather) run `/newbot`, pick a name and
username, and copy the token. It goes into `BOT_TOKEN`.

**Add the bot to the channel as an admin.** Open the channel → *Administrators* →
*Add Admin* → pick your bot and enable **“Invite users via link”**. No other right is needed.
At startup the bot checks this and messages every admin if the right is missing.

**Get the channel ID (`CHANNEL_ID`).** It's a negative number starting with `-100`. The
easiest way is to forward any channel post to [@userinfobot](https://t.me/userinfobot) or
[@getidsbot](https://t.me/getidsbot). Another way: open the channel in
[web.telegram.org](https://web.telegram.org), where the URL shows `#-100…`.

**Get admin IDs (`ADMINS`).** Each admin sends `/start` to [@userinfobot](https://t.me/userinfobot)
and copies their numeric ID. Separate multiple IDs with commas: `ADMINS=123456789,987654321`.

Each admin must also press **Start** in your bot once, otherwise Telegram won't let the bot
message them.

---

## 2. Server setup (Ubuntu)

Install Docker Engine and the Compose plugin from Docker's official repository:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start Docker on boot, so the containers come back after a reboot
sudo systemctl enable --now docker
# Optional: run docker without sudo (log out and back in afterwards)
sudo usermod -aG docker $USER
```

Both services use `restart: unless-stopped`, so after a reboot Docker brings the database and
the bot back automatically. In-progress conversations resume because the FSM state is stored in
MySQL.

---

## 3. Configure

```bash
git clone <your-repo-url> stylist-bot && cd stylist-bot
cp .env.example .env
nano .env          # fill in every value
chmod 600 .env     # only your user can read the secrets
```

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | Token from @BotFather |
| `ADMINS` | Comma-separated admin Telegram IDs (spaces are fine). The bot refuses to start if this is empty or malformed |
| `CHANNEL_ID` | The private channel's ID, `-100…` |
| `DB_HOST` / `DB_PORT` | `mysql` / `3306` with the bundled database |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | The bot's MySQL account and database (created automatically on first start) |
| `MYSQL_ROOT_PASSWORD` | Root password of the bundled MySQL (used by MySQL and for backups only) |
| `LOG_LEVEL` | `INFO` (default), `DEBUG`, `WARNING`, `ERROR` |
| `TZ` | Timezone for dates shown to people, e.g. `Asia/Tashkent`. The database always stores UTC |
| `DEFAULT_LANGUAGE` | `ru` or `uz`, used before someone picks a language |
| `PAYMENT_PAGE_URL` | Page with payment instructions, shown to clients |
| `SUPPORT_USERNAME` | Optional `@username` shown to approved clients who need help |
| `INVITE_LINK_TTL_HOURS` | How long a personal link stays valid (default 24) |

`.env` is git-ignored and excluded from the Docker image. It's only passed to the containers
at runtime. Use strong, unique passwords.

---

## 4. Run and operate

```bash
docker compose up -d --build        # build and start (first start creates the DB and runs migrations)
docker compose logs -f bot          # follow the bot's logs
docker compose ps                   # status
docker compose restart bot          # restart only the bot
docker compose down                 # stop (data is kept in the mysql_data volume)
```

Logs go to stdout (`docker compose logs`) and also to a rotating file, `./logs/bot.log`
(5 MB × 5 files). Docker's own logs rotate at 10 MB × 3 files per container.

Run **exactly one** bot container. Two instances polling with the same token conflict.

### Update to a new version

```bash
git pull && docker compose up -d --build
```

Database migrations (`alembic upgrade head`) run automatically every time the bot container
starts.

### Backup and restore

```bash
# Backup (consistent snapshot, no downtime)
docker compose exec -T mysql sh -c \
  'exec mysqldump --single-transaction -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
  > backup-$(date +%F).sql

# Restore into the running database
docker compose exec -T mysql sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' < backup-2026-01-31.sql
```

Keep backups off the server as well (they contain client names and phone numbers).

---

## 5. Using an existing MySQL on the host instead

1. In `docker-compose.yml`, delete the `mysql` service, the `depends_on` block of `bot`,
   and the `mysql_data` volume. Then add this to the `bot` service:
   ```yaml
       extra_hosts:
         - "host.docker.internal:host-gateway"
   ```
2. In `.env`, set `DB_HOST=host.docker.internal` (and `DB_PORT` if it isn't 3306).
   `MYSQL_ROOT_PASSWORD` is no longer used.
3. Make sure MySQL listens on an address the container can reach. In
   `/etc/mysql/mysql.conf.d/mysqld.cnf`, set `bind-address = 0.0.0.0` (or the Docker bridge IP,
   usually `172.17.0.1`), restart MySQL, and firewall port 3306 from the internet.
4. Create the database and a user that may connect from the Docker network:
   ```sql
   CREATE DATABASE stylist CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'stylist'@'172.%' IDENTIFIED BY 'a-strong-password';
   GRANT ALL PRIVILEGES ON stylist.* TO 'stylist'@'172.%';
   ```

The entrypoint waits up to 90 s for the database (`DB_WAIT_TIMEOUT` to change it), then runs
the migrations.

---

## 6. Translations (Russian / Uzbek)

All user- and admin-facing texts are gettext messages. Sources are in
`bot/locales/{ru,uz}/LC_MESSAGES/messages.po`. The Docker build compiles them to `.mo`.

```bash
pip install -r requirements.txt

# 1. Extract strings from the code into the template
pybabel extract -F babel.cfg -k _ -k __ -k N_ --no-location -o bot/locales/messages.pot .

# 2. Merge new/changed strings into the existing translations
pybabel update -i bot/locales/messages.pot -d bot/locales -D messages

# 3. Translate the new entries in the .po files (and remove "fuzzy" flags), then compile
pybabel compile -d bot/locales -D messages
```

Compiling is only needed when running the bot outside Docker.

---

## 7. How it behaves (quick reference)

**Clients**
- The first `/start` asks for the language (🇷🇺 Русский / 🇺🇿 O'zbekcha). Everything after
  that is in the chosen language. It can be changed any time in ⚙️ Settings.
- 💳 *Submit payment*: screenshot (photo or image file) → full name → phone → summary →
  *Send*. Phone numbers are accepted as `+998…`, `998…` or 9 local digits, with or without
  spaces/dashes. They're stored as `+998XXXXXXXXX` and shown as `+998 XX XXX XX XX`.
- Only one submission can be under review at a time. After a rejection, the previous name and
  phone can be reused with one tap. The screenshot is always new.
- Clients are **not** reminded before their link expires. Using it in time is up to them.

**Admins** (*🗂 Admin panel* or `/admin`)
- One panel message that updates in place. Your own inputs and stray messages are deleted to
  keep the chat clean.
- Lists (pending FIFO, approved/rejected newest first), search (name, any phone format,
  @username, Telegram ID), client card with screenshot, history of all attempts.
- **Approve** asks for confirmation, then creates and sends the personal link. If the link
  can't be created, the client is told they're not approved yet and the card offers
  *Retry generating link*.
- **Generate new link** on an approved card runs immediately (no confirmation). It revokes the
  old link and updates the card in place. Use *Resend link to user* to deliver it.
- **Reject** asks for confirmation, then for a reason: text, photo, file (captions allowed) or a
  voice message. The reason is copied to the client **without your name or profile**. Your
  reason message stays in your chat, and the bot replies to it with the delivery status (and a
  retry button if delivery failed).
- Notices (new payment, client joined, link expired unused) have an **Open** button that turns
  the notice into your panel.
- If two admins act on the same submission, the second one sees “Already processed by …”.

---

## 8. Development and tests

The tests run against a **real MySQL database** (not SQLite). They exercise the full handlers
through the real dispatcher, with a fake Telegram API that records every call.

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Disposable MySQL for tests (port 3307 on localhost)
docker run -d --name stylist_test_mysql \
  -e MYSQL_ROOT_PASSWORD=test_root_pw -e MYSQL_DATABASE=stylist_test \
  -e MYSQL_USER=stylist -e MYSQL_PASSWORD=test_pw \
  -p 127.0.0.1:3307:3306 mysql:8 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
# The migration test uses a second database it creates and drops itself:
docker exec stylist_test_mysql mysql -uroot -ptest_root_pw \
  -e "GRANT ALL ON stylist_migr_check.* TO 'stylist'@'%';"

pytest
```

Point `TEST_DATABASE_URL` at a different server if needed. The suite recreates its tables on
every run, so never point it at production.

Project layout:

```
bot/
  __main__.py          entrypoint (python -m bot), dispatcher wiring
  config.py            settings from .env (fail-fast validation)
  db/                  engine, models, repositories
  fsm/mysql_storage.py aiogram FSM storage in MySQL (survives restarts)
  handlers/            common (/start, language), user/, admin/, channel (join requests), errors
  keyboards/           reply + inline keyboards, CallbackData factories
  middlewares/         DB session, client loading, i18n, throttling
  services/            panel engine, screens, invite links, notifications, link expiry, phone
  locales/             ru / uz translations
migrations/            Alembic (async)
tests/                 pytest suite (real MySQL, fake Telegram API)
```

---

## 9. Manual test checklist (with a real bot and channel)

- Submit → approve → the client joins through their link. Admins get “… joined the channel”
  and the card shows the join time.
- An admin (or any other account) opens the client's link → the request is declined.
- Reject with text / photo + caption / file + caption / voice, and with a sticker (refused).
  The client receives the reason without any admin name or profile.
- Cancel at every step: approve confirmation, reject confirmation, reason input, search input.
- Resubmit after a rejection. History shows all attempts newest first; ◀️ / ▶️ flip through them.
- The client blocks the bot → approve → the panel shows the error. Unblock → *Resend* works.
- Two admins approve the same submission at the same time → exactly one link, one message.
- Let a link expire unused → admins get a notice; *Generate new link* on the card works.
- Search by part of a name, a phone with and without spaces / `+998`, `@username`, and the ID.
- Switch the language as a client and as an admin.
- `docker compose up -d --build` on a clean server with only `.env` filled in.
- `grep -r "<token>" .` in the repo and inside the image finds nothing.
- Reboot the server → both containers come back and in-progress forms continue.
