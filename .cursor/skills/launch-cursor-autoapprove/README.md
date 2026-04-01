# Launch Cursor Auto-Approve

## Summary

`launch-cursor-autoapprove` is the supported auto-approval skill in this repo.
It opens a dedicated Cursor window, injects a DOM-based auto-clicker via the
Chrome DevTools Protocol (CDP), and lets you pause or resume that window with
simple `on` / `off` commands.

Because the dedicated window is its own Cursor process, auto-clicking stays
isolated from your normal editing windows.

## Quick Start

### Prerequisites

- macOS
- Python 3.9+
- Cursor IDE

### Install

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
```

Global installs appear in Cursor as `/global-launch-cursor-autoapprove`. The
runtime helper lives at `~/.cursor/launch-autoapprove/launcher.py`.

Repo-local installs are also supported with `--target /path/to/repo`. That
copies the skill docs plus a launcher entrypoint into that repo's `.cursor/`,
while the dedicated runtime state and profile remain under
`~/.cursor/launch-autoapprove/`.

### Optional Alias

```bash
alias aa='/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py"'
```

### Launch a Dedicated Window

```bash
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" launch ~/code/my-project
```

If you added the alias above, `aa launch ~/code/my-project` works too.

### Toggle the Gate Later

```bash
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" on
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" off
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" status
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" stop
```

## How It Works

1. `launch` starts a new Cursor process with its own `--user-data-dir` and
   `--remote-debugging-port`.
2. The launcher injects `devtools_auto_accept.js` into that window's renderer
   and starts polling for approval buttons like `Run`, `Allow`, `Accept`, and
   `Apply`.
3. Later `on` / `off` / `status` calls talk to the same window over CDP. If the
   installed injector changed since the window was launched, `on` reloads the
   in-window script so the window picks up the latest fixes.

## Deep Dive

- [Implementation details](references/implementation.md)
- [Manual testing guide](references/manual-testing.md)
- [Why older approaches were retired](references/retired-approaches.md)
