---
description: Worklog enforcer — require a worklog artifact for every substantive conversation
alwaysApply: true
---
## Worklog Requirement

At the end of every substantive conversation (any work that creates, modifies, or analyzes code/docs), produce a worklog artifact at:

```
.agents/worklog/<YYYYMMDD-HHMM-TZ>-<descriptive-work-item>.md
```

### Naming

- `YYYYMMDD-HHMM-TZ`: timestamp with timezone, e.g. `20260330-1430-PDT`
- `<descriptive-work-item>`: short kebab-case slug describing the work, e.g. `bootstrap-repo-structure`
- Full example: `.agents/worklog/20260330-1430-PDT-bootstrap-repo-structure.md`

### Content

The worklog should include:
- **Summary**: what was done in 2-3 sentences.
- **Files changed**: list of files created, modified, or deleted.
- **Decisions made**: key choices and their rationale.
- **Open items**: anything left unfinished or flagged for follow-up.

### Scope

- Trivial changes (typo fixes, single-line edits with no design impact) do not require a worklog.
- Multi-step work, new features, investigations, and refactors always require one.
- When in doubt, write a worklog.
