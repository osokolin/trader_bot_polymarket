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

### Если нужен gateway-backed execution preview

Запустить:

    bot proposals execution-preview <proposal_id>

Что ожидать:

- это строго non-live preview artifact
- `dry_run` должен быть `True`
- preview может иметь `ready`, `ready_with_warnings` или `blocked`
- `blocked` означает, что gateway не смог безопасно согласовать market/token/side/price/size
- результат сохраняется в persisted preview audit trail

Важно:

- preview не создает order intent
- preview не отправляет ордер
- preview не меняет `ManualExecutionGuard`
- live submission по-прежнему intentionally disabled

Посмотреть историю и сводку:

    bot proposals execution-preview-history <proposal_id> --limit 20
    bot execution-previews list --scope failed --limit 20
    bot execution-previews list --scope warnings --limit 20
    bot execution-previews summary

------------------------------------------------------------------------

### Если оператор reviewing proposal в Telegram и нужен execution preview

Использовать:

    /review-next
    /request <id>

На proposal review card теперь показывается:

- `preview_ok`
- `preview_warn`
- `preview_failed`
- `preview_missing`

Что это значит:

- `preview_ok` --- последний non-live preview согласовал market/token/side/price/size без warning'ов
- `preview_warn` --- preview подготовился, но есть warning'и, которые оператор должен прочитать до approve
- `preview_failed` --- preview не смог безопасно подготовиться; это soft warning для review, а не execution
- `preview_missing` --- по proposal еще не запускали preview

Чтобы явно обновить preview из review flow:

    /preview <request_id>

Или нажать inline кнопку `Preview`.

Важно:

- это создает новый persisted non-live preview audit record
- это не создает intent
- это не отправляет ордер
- это не меняет `ManualExecutionGuard`
- approve/reject/cancel semantics остаются прежними

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
