# OPERATOR_CHEATSHEET.md

## Быстрый гайд оператора Trader Bot Polymarket

### Перед началом работы

1.  Проверить конфигурацию

```{=html}
<!-- -->
```
    bot config validate

2.  Проверить систему

```{=html}
<!-- -->
```
    scripts/dev verify-fast

3.  Убедиться что режим:

```{=html}
<!-- -->
```
    mode = semi_auto

------------------------------------------------------------------------

### Основные команды

Запуск UI:

    bot ui serve

Запуск Telegram:

    bot telegram serve

Seed demo данных:

    bot demo seed

Проверка proposals:

    bot proposals list

Просмотр alerts:

    bot alerts list

Просмотр аналитики:

    bot analysis outcomes

------------------------------------------------------------------------

### Telegram команды

    /status
    /inbox
    /review
    /review-next
    /request <id>
    /preview <request_id>
    /approve
    /reject
    /cancel

------------------------------------------------------------------------

### Правило оператора

Proposal --- это **не ордер**, а **предложение**.

Execution Preview в review:

- `preview_ok` / `preview_warn` / `preview_failed` / `preview_missing`
- это всегда non-live dry-run context
- `/preview <request_id>` только обновляет preview audit trail, но не отправляет ордер

Перед approve всегда проверяйте:

-   ликвидность
-   спред
-   время до resolution
-   риск по категории
-   размер позиции
-   текущую экспозицию

------------------------------------------------------------------------

### Когда approve

✔ рынок понятен\
✔ ликвидность достаточная\
✔ риск допустим\
✔ размер позиции разумный

### Когда reject

✘ плохая ликвидность\
✘ слабый сигнал\
✘ конфликт с текущими позициями

------------------------------------------------------------------------

### Минимальный продакшен чеклист

-   `.env` настроен
-   `mode = semi_auto`
-   verify проходит
-   UI за reverse proxy
-   Telegram ограничен chat id
