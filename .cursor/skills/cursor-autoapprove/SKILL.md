---
name: cursor-autoapprove
description: >-
  Set up safer Cursor command auto-approval for any repo. Installs or resets a
  beforeShellExecution hook, a window-scoped approval watcher, and session
  management so long-running agent work requires only one up-front approval.
  Use when the user wants automatic shell approvals in a dedicated Cursor
  window or instance, or when setting up auto-approval in a new repo.
---

# Cursor Auto-Approval

This skill packages everything needed to auto-approve Cursor agent prompts
safely. It works by combining a `beforeShellExecution` hook (for shell
commands) with a window-scoped Accessibility watcher (for UI prompts),
both bound to a single Cursor window.

## Prerequisites

- macOS (uses Accessibility APIs and AppleScript)
- Python 3.9+ (ships with macOS)
- Cursor IDE
- Accessibility permission granted to Cursor in System Settings > Privacy & Security > Accessibility

## First-Time Setup

If you want a clean slate first, reset any old install:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/reset.sh" --target global
```

Then run the install script to set up everything in your home directory:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/install.sh" --target global
```

This copies the controller, AppleScripts, hooks config, and skill docs into `~/.cursor/auto-approval/`, `~/.cursor/hooks.json`, and `~/.cursor/skills/global-cursor-autoapprove/`.
The installed global skill is renamed to `/global-cursor-autoapprove` so it stays visually distinct from a repo-local `/cursor-autoapprove`.

To install into a specific repo instead:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/install.sh" --target /path/to/repo
```

Repo-local installs keep the original skill name and land under `/path/to/repo/.cursor/skills/cursor-autoapprove/`.

### Verify Installation

```bash
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" status
```

You should see `session_active: false` and `hook_enabled: true`.

## Usage (After Setup)

### Start a session

Focus the Cursor window you want the agent to own, then run:

```bash
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" activate --workspace "$PWD"
```

### Stop a session

```bash
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" deactivate
```

### Dedicated instance (stronger isolation)

```bash
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" activate --workspace "$PWD" --launch-dedicated
```

## How It Works

Three layers provide coverage:

1. **Shell hook** (100% for shell commands): `beforeShellExecution` hook returns `{"permission": "allow"}` while a session is active and the command's cwd matches the workspace.
2. **Window watcher** (UI prompts): scans one bound Cursor window for known approval buttons via Accessibility and clicks them.
3. **Session management**: TTL, idle timeout, and process monitoring automatically stop the session when it becomes stale.

## Safety Model

- The watcher binds to one specific Cursor process and window fingerprint.
- No app-wide keystroke injection. The deprecated `Cmd+Return` loop is gone.
- If the target window closes or the process exits, the session stops.
- One active session per workspace at a time.

## Additional Reference

- See [reference.md](reference.md) for the full command reference, failure modes, and limitations.
