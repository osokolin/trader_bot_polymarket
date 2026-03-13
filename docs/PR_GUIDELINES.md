# Pull Request Guidelines

Все Pull Requests в этом проекте должны иметь структурированное описание.

Это облегчает архитектурный review, аудит изменений и будущую поддержку системы.

PR description должен быть сгенерирован автоматически при помощи Codex
или написан вручную по следующему шаблону.

---

# Required PR Structure

Каждый PR должен содержать следующие разделы.

## 1. Milestone Title

Укажите milestone или feature.

Example:

Milestone F.2 — Telegram Trigger for Opportunity Scan

---

## 2. Summary of Changes

Краткое описание того, что изменилось.

2–6 предложений.

Опишите:

- какую проблему решает изменение
- что теперь может делать оператор или система

---

## 3. What Changed

Список ключевых изменений.

Example:

- добавлена команда Telegram `/scan-opportunities`
- TelegramRouter поддерживает limit аргумент
- TelegramOperatorService вызывает MarketOpportunityAlertService
- добавлен cooldown для anti-spam

---

## 4. Architecture Note

Кратко опишите архитектурный поток.

Example:

TelegramRouter  
→ TelegramOperatorService  
→ MarketOpportunityAlertService

Важно:

- Telegram слой должен оставаться thin interface
- бизнес-логика должна находиться в сервисах

---

## 5. Safety Boundaries

Подтвердите, что изменения не нарушают trading safety rules.

Example:

semi_auto behavior unchanged  
no automatic proposal creation  
no execution pipeline changes  
no policy configuration changes  

---

## 6. Files Changed

Список основных файлов.

Example:

bot/services/market_opportunity_alerts.py  
bot/telegram/router.py  
bot/services/telegram_operator_service.py  
tests/test_telegram_operator.py  

---

## 7. Risks / Follow-ups

Опишите потенциальные follow-ups.

Example:

- cooldown currently in-memory
- Telegram output intentionally compact

---

## 8. Verification

Команды, которые были запущены.

Example:

scripts/dev verify-fast  
scripts/dev verify  

Results:

tests: 171 passed  
ruff: OK  
mypy: OK  

---

# Important

PR description должен быть:

- concise
- reviewable
- architecture-aware
- explicit about safety boundaries

Не допускается:

- пустые PR описания
- одно предложение
- отсутствие verification результатов