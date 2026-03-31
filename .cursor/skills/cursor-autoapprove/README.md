# Cursor Auto-Approval

## What It Does

`cursor-autoapprove` sets up safer command auto-approval for Cursor on macOS. It combines a workspace-aware shell hook with a window-scoped approval watcher so long-running agent work usually needs one up-front approval instead of repeated button clicks.

## How to Use It

This skill requires macOS, Cursor, Python 3, and Accessibility permission for Cursor.

```bash
# Optional clean reset
bash .cursor/skills/cursor-autoapprove/scripts/reset.sh --target global

# Install globally
bash .cursor/skills/cursor-autoapprove/scripts/install.sh --target global

# Start a session for the current workspace
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" activate --workspace "$PWD"

# Stop the session when you're done
/usr/bin/python3 "$HOME/.cursor/auto-approval/cursor_auto_approval.py" deactivate
```

Global installs appear in Cursor as `/global-cursor-autoapprove`. Repo-local installs keep the original `/cursor-autoapprove` name:

```bash
bash .cursor/skills/cursor-autoapprove/scripts/install.sh --target /path/to/repo
```

## How It Works

- A `beforeShellExecution` hook auto-allows shell commands only while a session is active and the command belongs to the chosen workspace.
- A macOS Accessibility watcher binds to one Cursor window and clicks known approval buttons when they appear.
- Session TTL, idle timeout, and process checks stop stale sessions automatically.

See [reference.md](reference.md) for the full command reference, limitations, and failure modes.
