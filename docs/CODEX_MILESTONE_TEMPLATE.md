# Codex Milestone Template

This template is used to implement new milestones in the project using Codex.

Every milestone must follow this structure to ensure:

- architecture consistency
- safety boundaries
- reproducible verification
- clean pull request descriptions

---

# Context for the project

<insert PROJECT_CONTEXT.md>

You are assisting as:

- software architect
- milestone implementer
- code reviewer

Follow the existing architecture and safety boundaries of the project.

---

# Milestone Title

Example:

Milestone F.3 — Telegram Alert Delivery

---

# Goal

Describe the purpose of the milestone.

Example:

Deliver newly created alerts to Telegram automatically so the operator
is notified when relevant markets appear.

The milestone must:

- improve operator workflow
- not change trading behavior
- remain fully reviewable

---

# Scope

Describe exactly what should be implemented.

Example:

1. Detect newly created alerts
2. Deliver them to Telegram
3. Keep messages concise
4. Avoid duplicate notifications

---

# Non-Goals

Explicitly state what must NOT change.

Example:

Do NOT implement:

- automatic proposal generation
- execution changes
- policy config mutations
- background schedulers if not required
- AI scoring logic

---

# Architecture Requirements

All new features must respect existing layers.

Example architecture flow:

AlertService  
→ OperatorNotificationsService  
→ TelegramOperatorService  
→ TelegramRouter  

Rules:

- Telegram layer must stay thin
- business logic must remain in services
- no shell execution
- no duplicated logic

---

# Safety Boundaries

These must remain unchanged.

semi_auto must remain strict.

The milestone must NOT introduce:

- automatic order placement
- proposal auto approval
- execution shortcuts
- policy auto modification

All trading decisions remain operator-controlled.

---

# Implementation Guidelines

Follow these principles:

1. reuse existing services
2. avoid duplicating logic
3. keep changes small and reviewable
4. keep Telegram / UI layers thin
5. maintain test coverage

---

# Files to Modify

Codex should list the files it expects to modify.

Example:

bot/services/operator_notifications.py  
bot/telegram/router.py  
bot/telegram/formatter.py  
bot/services/alert_delivery.py  
tests/test_alert_delivery.py  

---

# Testing Requirements

Add or update tests for:

- service logic
- command routing
- edge cases
- regression coverage

Tests must pass using:

scripts/dev verify-fast  
scripts/dev verify

---

# Verification

Codex must run:

scripts/dev verify-fast  
scripts/dev verify

And report results:

tests passed  
ruff passed  
mypy passed  

---

# Pull Request Description

Codex must generate a PR description following:

docs/PR_GUIDELINES.md

Required sections:

1. Milestone Title
2. Summary of changes
3. What changed
4. Architecture note
5. Safety boundaries
6. Files changed
7. Risks / follow-ups
8. Verification results

---

# Expected Output from Codex

Codex must provide:

1. Summary of changes
2. Files changed
3. Architecture explanation
4. Safety confirmation
5. Verification results
6. Pull Request description