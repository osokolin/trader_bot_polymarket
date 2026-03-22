# RUNBOOK.md

## Runbook для продакшена Trader Bot Polymarket

### Если UI не открывается

Проверить процесс:

    ps aux | grep bot

Перезапустить сервис:

    systemctl restart trader-web

Проверить порт:

    ss -ltnp | grep 8080

------------------------------------------------------------------------

### Если verify падает

Запустить:

    scripts/dev verify-fast

Если падает pytest:

    pytest -x

------------------------------------------------------------------------

### Если Telegram бот не отвечает

Проверить:

-   TELEGRAM_BOT_TOKEN
-   TELEGRAM_ALLOWED_CHAT_IDS
-   процесс telegram сервиса

Перезапуск:

    systemctl restart trader-telegram

------------------------------------------------------------------------

### Если включили Polymarket gateway и он не поднимается

Проверить:

- `polymarket_gateway.enable_polymarket_gateway`
- `polymarket_gateway.dry_run`
- env vars из блока gateway (`POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`)

Важно:

- в текущем milestone gateway нужен для controlled metadata / execution plumbing boundary
- live order submission по-прежнему intentionally disabled
- отсутствие credentials должно fail closed и не должно менять основной semi_auto flow

------------------------------------------------------------------------

### Если UI пустой

Скорее всего нет данных.

Запустить:

    bot demo seed

------------------------------------------------------------------------

### Если пропали данные

Проверить:

    BOT_DATABASE_URL

Возможно используется другая SQLite база.

------------------------------------------------------------------------

### Если сломались migrations

Проверить таблицу:

    SELECT * FROM schema_version;

Если версия не соответствует --- перезапустить приложение.

------------------------------------------------------------------------

### Backup базы

    cp bot.db bot.db.backup

Рекомендуется nightly backup.

------------------------------------------------------------------------

### Если подозрение на компрометацию

1.  Отозвать все auth токены
2.  Сменить пароль пользователя
3.  Проверить audit events
4.  Перезапустить сервисы
