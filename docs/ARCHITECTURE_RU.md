# ARCHITECTURE_RU.md

## Архитектура Trader Bot Polymarket

Система построена по принципу **operator‑driven semi‑auto decision
system**.

Основные принципы:

-   policy‑first
-   configuration‑first
-   semi_auto execution
-   audit‑first architecture

------------------------------------------------------------------------

## Основной pipeline

    scanner
       ↓
    proposal bridge
       ↓
    policy checks
       ↓
    decision inbox
       ↓
    operator review
       ↓
    execution intent (simulation)

------------------------------------------------------------------------

## Основные компоненты

### Scanner

Получает рыночные данные.

### Proposal Engine

Формирует candidate proposals.

### Policy Layer

Проверяет:

-   market filters
-   risk limits
-   entry rules

### Decision Inbox

Хранит requests для оператора.

### Operator Interfaces

1.  CLI
2.  Web UI
3.  Telegram

Все интерфейсы вызывают **одни и те же сервисы**.

------------------------------------------------------------------------

## Storage

База данных:

SQLite

Основные таблицы:

-   proposals
-   intents
-   alerts
-   reviews
-   snapshots
-   audit logs

Схема управляется через **migration system**.

------------------------------------------------------------------------

## Security Boundary

-   режим `semi_auto`
-   нет автоисполнения
-   execution pipeline отделен от UI
-   web auth защищает dashboard
-   audit фиксирует все решения

------------------------------------------------------------------------

## Interfaces

### CLI

Используется для диагностики и анализа.

### Web UI

Показывает:

-   dashboard
-   proposals
-   alerts
-   markets
-   analytics

### Telegram

Используется для быстрого operator review.

------------------------------------------------------------------------

## Конфигурация

Основные файлы:

    config/base.yaml
    config/balanced.yaml
    config/conservative.yaml
    config/aggressive.yaml

Environment переменные:

    BOT_MODE
    BOT_DATABASE_URL
    BOT_UI_HOST
    BOT_UI_PORT
    TELEGRAM_BOT_TOKEN

------------------------------------------------------------------------

## Deployment модель

Рекомендуется:

    systemd
     ├─ trader-web
     ├─ trader-telegram
     └─ trader-scanner

    nginx
      ↓
    web UI

База:

    /var/lib/trader_bot_polymarket/bot.db


## Opportunity Discovery Runtime

Opportunity scanning runs automatically in the Telegram runtime loop.

Flow:

TelegramBotApp.run_cycle()
  → TelegramOperatorService.poll_notifications()
  → background opportunity scan (if interval elapsed)
  → MarketOpportunityAlertService.scan(...)
  → alert persistence
  → Telegram delivery

Manual triggers remain available:
- CLI: bot alerts scan-opportunities
- Telegram: /scan-opportunities

------------------------------------------------------------------------

## Будущие компоненты

Планируемые подсистемы:

-   Strategy Engine
-   Risk Engine
-   Portfolio Console
-   Multi-user auth
