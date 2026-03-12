Act as the Committer agent for this repository.

Read first:
- AGENTS.md
- .agents/shared-context.md
- .agents/gates.md
- .agents/committer.md
- .agents/architecture-guardrails.md

Your task:
Create a commit only if all gates are green.

Preconditions:
- approved milestone completed
- Tester verdict is GREEN
- Reviewer verdict is SAFE_FOR_REVIEW or explicitly non-blocking
- Security verdict is SECURITY_OK or explicitly non-blocking
- docs updated if needed
- current branch is not main/master

Allowed branch patterns:
- feature/*
- fix/*
- codex/*
- refactor/*
- docs/*

Tasks:
1. Check current branch
2. Refuse to commit on disallowed branches
3. Check git status
4. Stage only intended files
5. Create a clean commit
6. Summarize what was committed

Output:
1. Current branch
2. Files staged
3. Commit hash
4. Commit message
5. Push command suggestion