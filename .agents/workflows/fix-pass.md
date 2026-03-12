# Workflow: fix-pass

Use when review found issues.

1. Reviewer and/or Security lists blockers and non-blockers.
2. Planner reduces blockers into one small fix pass.
3. Architect checks whether the fix keeps boundaries clean.
4. Implementer fixes only blockers unless explicitly approved.
5. Tester reruns relevant commands.
6. Reviewer rechecks the affected area.
7. Security rechecks affected safety boundaries.
8. Committer commits if green.