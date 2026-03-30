# Auto-Approval Reference

## Fresh Start

Reset an existing global install:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/reset.sh" --target global
```

Reinstall cleanly:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/install.sh" --target global
```

For a repo-local install, replace `global` with `/path/to/repo`. Repo-local installs now keep their runtime files under that repo's `.cursor/auto-approval/`.

## Command Reference

The commands below assume a global install at `~/.cursor/auto-approval/cursor_auto_approval.py`. For a repo-local install, use that repo's `.cursor/auto-approval/cursor_auto_approval.py` instead.

| Command | What it does |
|---------|-------------|
| `activate --workspace $PWD` | Bind to the frontmost Cursor window and start auto-approving |
| `activate --workspace $PWD --launch-dedicated` | Launch a separate Cursor instance and bind to it |
| `activate --workspace $PWD --pid <PID>` | Bind to a specific Cursor process by PID |
| `deactivate` | Stop the session and watcher |
| `status` | Print JSON status (session, hook, watcher) |
| `hook-on` | Re-enable the shell hook |
| `hook-off` | Disable the shell hook and stop the session |

## What Gets Scoped

- Shell approval: active session + workspace path match.
- UI prompt clicking: target Cursor PID + window fingerprint match.
- Idle timeout and TTL stop the session automatically.

## Important Limitation

The shell hook does not know a Cursor chat ID or window ID. Shell auto-approval cannot be restricted to one chat pane. The safest model is:

- Start the session from the agent window you want to own.
- Keep one active agent session per workspace.
- Use `--launch-dedicated` if you want full human/agent isolation.

## Failure Modes

| Condition | Behavior |
|-----------|----------|
| Accessibility cannot see prompt buttons | Shell auto-approval still works; UI prompts remain manual |
| Wrong Cursor window focused during activation | Deactivate and re-activate after focusing the correct window |
| Target window closes or process exits | Session stops; hook returns to manual approval |
| TTL or idle timeout reached | Session stops automatically |
| `--launch-dedicated` opens a new instance | It does not move the current chat there; use it for a new task |

## Safe Fallback

If window-scoped Accessibility proves unreliable for a particular prompt, keep the session for shell auto-approval and handle that prompt manually. Never reintroduce app-wide `Cmd+Return` injection.

## Smoke Tests

Fresh install should report an idle but healthy controller:

```bash
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" status
```

Dedicated-instance activation should report `session_active: true`:

```bash
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" activate --workspace "$PWD" --launch-dedicated
```

With an active session, a command inside the workspace should be auto-allowed; a command outside the workspace should fall back to manual approval and stop the session.

## Files Installed

| File | Purpose |
|------|---------|
| `~/.cursor/auto-approval/cursor_auto_approval.py` | Main controller (hook handler + watcher + CLI) |
| `~/.cursor/auto-approval/open_notification_banner.applescript` | Auto-dismiss macOS notification banners |
| `~/.cursor/auto-approval/click_notification_primary_button.applescript` | Auto-click macOS notification primary buttons |
| `~/.cursor/auto-approval/state.json` | Persistent config (created at runtime) |
| `~/.cursor/auto-approval/session.json` | Active session state (created at runtime) |
| `~/.cursor/hooks.json` | Cursor hook config wiring the shell hook |

## Deprecated: App-Wide Keystroke Injection

Earlier versions used a background daemon that sent `Cmd+Return` to the entire Cursor application. This is **unsafe** because it interferes with manual work (menus, terminal, typing). It has been removed from the controller. Do not reintroduce it.
