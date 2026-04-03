---
description: Guard against external software version drift — validate compatibility proactively
alwaysApply: false
globs:
  - .cursor/skills/**
---

# Version Coupling Guard

## Problem This Solves

Skills that depend on external software (Cursor's DOM structure, CLI tool
versions, API schemas, browser engine behavior) break silently when the external
software updates. The breakage is often subtle: the skill loads successfully,
diagnostics pass, but real-world behavior fails.

## The Rule

Any skill that couples to an external software version must:

1. **Document the known working version(s).**
2. **Check the running version at startup or first use.**
3. **Warn (don't silently fail) when the version is unknown.**
4. **Re-validate after every external update.**

## What Counts as Version Coupling

- DOM selectors that target specific CSS classes or element IDs
- API calls that depend on a specific response schema
- CLI tools that parse output from a specific version
- Browser engine features (WebSocket APIs, CSS selectors, etc.)
- File format assumptions (config file structure, state file schema)

## Documentation Requirements

Every version-coupled skill must maintain a compatibility table in its
reference docs:

```
| External Software | Known Working Version | Date Validated | Notes |
|-------------------|----------------------|----------------|-------|
| Cursor            | 3.0.8                | 2026-04-03     | Chat in auxiliarybar |
| Chrome Engine     | 142.0.7444.265       | 2026-04-03     | CDP WebSocket API |
```

## Startup Validation

When a version-coupled skill activates:

1. **Read the external version** (e.g., `--version`, process metadata, API
   version endpoint).
2. **Compare against known working versions.**
3. **If unknown**: Log a WARNING with the detected version and the last known
   working version. Suggest running the validation suite.
4. **If known broken**: Fail with a clear error and link to the relevant issue.

## Branch Naming Convention

When fixing version-specific issues, use branch names that encode the version:

```
<external-software>-<version>/<fix-description>
```

Examples:
- `cursor-3.0.8/auxiliarybar-subagent-fix`
- `cursor-3.1.0/new-dialog-selectors`

This makes it immediately clear which version a fix targets and enables
version-based bisection in git history.

## Upgrade Checklist

When the external software updates:

1. Record the new version in the skill's version table.
2. Run the skill's validation suite (real usage, not just synthetic tests).
3. If the validation suite doesn't exist, build one before trusting the
   upgrade.
4. Deploy the CDP diagnostic harness (or equivalent) to capture what changed.
5. Update known working versions on success.
6. File an issue on failure with the diagnostic captures.

## Hard Rules

- **Never assume a skill works on a new version because it worked on the
  old version.** External software changes silently.
- **Never skip validation because "it's a minor version bump."** Minor
  bumps frequently rearrange internal structures.
- **Always check the FULL selector/query path, not just the final target.**
  A selector can match on the old version and miss on the new one because
  an ancestor element changed, not the target itself.
- **When a version-coupled skill fails, the version mismatch is the FIRST
  hypothesis to check** — before debugging the skill's internal logic.

## Example: The Auxiliarybar Migration

Cursor 3.0.8 moved the agent chat from a non-excluded workbench part to
`workbench.parts.auxiliarybar`. The auto-click injector:
- Loaded successfully ✓
- Synthetic probes passed ✓
- Real click count: 0 ✗

The injector's logic was correct — it was the DOM structure that changed.
The version wasn't checked because no version guard existed.
