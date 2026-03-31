# Auto-Approval Reference

## Fresh Start

Reset an existing global install:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/reset.sh" --target global
```

For global installs, reset removes the current `~/.cursor/skills/global-cursor-autoapprove/` copy plus legacy aliases such as `~/.cursor/skills/cursor-autoapprove/` and `~/.cursor/skills/personal-cursor-autoapprove/`.

Reinstall cleanly:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/cursor-autoapprove/scripts/install.sh" --target global
```

For a repo-local install, replace `global` with `/path/to/repo`. Repo-local installs now keep their runtime files under that repo's `.cursor/auto-approval/`, and keep the original `/cursor-autoapprove` skill name. Global installs appear in Cursor as `/global-cursor-autoapprove`.

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

## How the Accessibility Scanner Works

The watcher uses the native macOS Accessibility C API (via `ctypes`) instead of AppleScript for speed. Key technical details:

- **AXEnhancedUserInterface**: Must be set to `true` on the Cursor application element. Without this, Chromium/Electron apps only expose a sparse accessibility tree. The watcher sets this automatically during activation.
- **Element types scanned**: `AXButton` (standard buttons), `AXGroup` with AXPress action (clickable containers), and `AXStaticText` with a pressable ancestor (Cursor renders some approval controls as text labels, not semantic `<button>` elements).
- **Keyboard hint stripping**: Labels like "Run this time only (⏎)" are normalized by removing the trailing `(⏎)` before matching against the approval label list.
- **Scan time**: Typically 0.05–0.15s for the full window tree (1000–2000 elements).

## Interaction with Cursor's Own Approval

Cursor has multiple layers of command approval:

1. **Cursor sandbox / command allowlist**: Cursor may auto-approve commands the user has previously allowed. When this happens, no UI prompt is shown and the watcher has nothing to click.
2. **`required_permissions: ["all"]`**: When the agent requests elevated permissions, Cursor handles the approval at the IDE level before the shell hook fires.
3. **`beforeShellExecution` hook**: Returns `"permission": "allow"` or `"permission": "ask"`. When the hook says "allow", the command proceeds without any UI prompt.
4. **UI prompt (watcher target)**: When all other layers pass through, Cursor shows an in-window approval prompt with buttons like "Run this time only (⏎)" or "Allow". The watcher attempts to find and click these.

In practice, most commands for an agent session within its workspace are handled by layer 1 or 3, so the watcher rarely needs to act. It is most useful as a fallback for edge cases like commands with empty `cwd`.

## Failure Modes

| Condition | Behavior |
|-----------|----------|
| Cursor's own allowlist auto-approves the command | Hook still logs "allow"; watcher has nothing to click (normal operation) |
| Approval prompt uses an unexpected element type | Watcher scans buttons, clickable groups, and text labels with pressable ancestors; unknown types are missed |
| Approval prompt appears and disappears too quickly | Watcher scans every 0.5–1s; a prompt dismissed in under 0.5s may be missed |
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

With an active session, a command inside the workspace should be auto-allowed; a command outside the workspace should fall back to manual approval without tearing down the active session.

## Files Installed

| File | Purpose |
|------|---------|
| `~/.cursor/auto-approval/cursor_auto_approval.py` | Main controller (hook handler + watcher + CLI) |
| `~/.cursor/auto-approval/open_notification_banner.applescript` | Auto-dismiss macOS notification banners |
| `~/.cursor/auto-approval/click_notification_primary_button.applescript` | Auto-click macOS notification primary buttons |
| `~/.cursor/auto-approval/state.json` | Persistent config (created at runtime) |
| `~/.cursor/auto-approval/session.json` | Active session state (created at runtime) |
| `~/.cursor/hooks.json` | Cursor hook config wiring the shell hook |
| `~/.cursor/skills/global-cursor-autoapprove/SKILL.md` | Global skill entrypoint, renamed to avoid local/global collisions |
| `~/.cursor/skills/global-cursor-autoapprove/reference.md` | Global skill reference |

## Deprecated: App-Wide Keystroke Injection

Earlier versions used a background daemon that sent `Cmd+Return` to the entire Cursor application. This is **unsafe** because it interferes with manual work (menus, terminal, typing). It has been removed from the controller. Do not reintroduce it.
