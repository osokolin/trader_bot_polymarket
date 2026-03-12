Act as the Implementer agent for this repository.

Read first:
- AGENTS.md
- .agents/shared-context.md
- .agents/architecture-guardrails.md
- .agents/gates.md
- .agents/implementer.md

Your task:
Implement only the approved milestone.

Requirements:
- stay within scope
- keep UI/CLI thin
- put logic in services
- put external API logic in adapters
- preserve semi_auto strictness
- keep real live execution disabled
- update tests/docs if needed

After implementation, recommend the smallest appropriate verification command:
- scripts/dev verify-fast
- scripts/dev verify
- scripts/dev doctor

Output:
1. Summary of changes
2. Files changed
3. Tests added/updated
4. Known limitations
5. Recommended verification command(s)