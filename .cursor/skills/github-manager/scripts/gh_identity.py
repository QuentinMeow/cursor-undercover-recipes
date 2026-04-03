#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional


Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


class IdentityError(RuntimeError):
    pass


@dataclass
class RepoContext:
    repo_root: Path
    git_dir: Path
    remote_url: Optional[str]


@dataclass
class IdentityState:
    depth: int
    previous_login: str
    target_login: str
    hostname: str


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )


def require_ok(
    result: subprocess.CompletedProcess[str], command: list[str], failure_hint: str
) -> str:
    if result.returncode == 0:
        return result.stdout.strip()
    stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
    raise IdentityError(f"{failure_hint}\nCommand: {' '.join(command)}\nError: {stderr}")


def git_output(cwd: Path, args: list[str], runner: Runner) -> str:
    command = ["git", *args]
    result = runner(command, cwd)
    return require_ok(result, command, "Git command failed.")


def optional_git_output(cwd: Path, args: list[str], runner: Runner) -> Optional[str]:
    command = ["git", *args]
    result = runner(command, cwd)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def resolve_repo_context(cwd: Path, runner: Runner) -> RepoContext:
    repo_root = Path(git_output(cwd, ["rev-parse", "--show-toplevel"], runner)).resolve()
    git_dir_raw = git_output(cwd, ["rev-parse", "--git-dir"], runner)
    git_dir = Path(git_dir_raw)
    if not git_dir.is_absolute():
        git_dir = (cwd / git_dir).resolve()
    remote_url = optional_git_output(cwd, ["remote", "get-url", "origin"], runner)
    return RepoContext(repo_root=repo_root, git_dir=git_dir, remote_url=remote_url)


def default_state_path(context: RepoContext) -> Path:
    return context.git_dir / "github-manager" / "gh_identity_state.json"


def load_state(path: Path) -> Optional[IdentityState]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise IdentityError(f"State file is not valid JSON: {path}") from exc
    try:
        return IdentityState(**data)
    except TypeError as exc:
        raise IdentityError(f"State file has the wrong shape: {path}") from exc


def save_state(path: Path, state: IdentityState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2, sort_keys=True) + "\n")


def get_active_login(hostname: str, cwd: Path, runner: Runner) -> str:
    command = ["gh", "api", "--hostname", hostname, "user", "-q", ".login"]
    result = runner(command, cwd)
    return require_ok(
        result,
        command,
        "Could not determine the active gh login. Run `gh auth login` first if needed.",
    )


def switch_login(hostname: str, login: str, cwd: Path, runner: Runner) -> None:
    command = ["gh", "auth", "switch", "--hostname", hostname, "--user", login]
    result = runner(command, cwd)
    require_ok(
        result,
        command,
        "Could not switch gh to the requested login. "
        "If that account is not logged in yet, run `gh auth login` in Cursor first.",
    )


def build_status(
    cwd: Path,
    hostname: str,
    target_user: Optional[str],
    state_path: Optional[Path],
    runner: Runner,
) -> dict[str, object]:
    context = resolve_repo_context(cwd, runner)
    path = state_path or default_state_path(context)
    state = load_state(path)
    active_login = get_active_login(hostname, cwd, runner)
    payload: dict[str, object] = {
        "repo_root": str(context.repo_root),
        "git_dir": str(context.git_dir),
        "state_file": str(path),
        "origin_remote": context.remote_url,
        "hostname": hostname,
        "active_login": active_login,
        "state": asdict(state) if state else None,
    }
    if target_user:
        payload["target_user"] = target_user
        payload["matches_target"] = active_login == target_user
    return payload


def enter_identity(
    cwd: Path,
    hostname: str,
    target_user: str,
    state_path: Optional[Path],
    dry_run: bool,
    runner: Runner,
) -> dict[str, object]:
    context = resolve_repo_context(cwd, runner)
    path = state_path or default_state_path(context)
    state = load_state(path)
    active_login = get_active_login(hostname, cwd, runner)

    if state:
        if state.hostname != hostname or state.target_login != target_user:
            raise IdentityError(
                "Existing gh identity state targets a different host or user. "
                "Run `leave` first or remove the stale state file manually."
            )
        if active_login != target_user:
            raise IdentityError(
                "Saved gh identity state exists, but the active login is not the target user. "
                "Refusing to guess how to recover."
            )
        state.depth += 1
        if not dry_run:
            save_state(path, state)
        return {
            "action": "incremented-depth",
            "active_login": active_login,
            "target_user": target_user,
            "depth": state.depth,
            "state_file": str(path),
            "dry_run": dry_run,
        }

    if active_login == target_user:
        return {
            "action": "already-target",
            "active_login": active_login,
            "target_user": target_user,
            "depth": 0,
            "state_file": str(path),
            "dry_run": dry_run,
        }

    new_state = IdentityState(
        depth=1,
        previous_login=active_login,
        target_login=target_user,
        hostname=hostname,
    )

    if dry_run:
        return {
            "action": "would-switch",
            "active_login": active_login,
            "target_user": target_user,
            "previous_login": active_login,
            "state_file": str(path),
            "dry_run": True,
        }

    save_state(path, new_state)
    try:
        switch_login(hostname, target_user, cwd, runner)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return {
        "action": "switched",
        "active_login": target_user,
        "target_user": target_user,
        "previous_login": active_login,
        "depth": 1,
        "state_file": str(path),
        "dry_run": False,
    }


def leave_identity(
    cwd: Path,
    hostname: str,
    state_path: Optional[Path],
    dry_run: bool,
    runner: Runner,
) -> dict[str, object]:
    context = resolve_repo_context(cwd, runner)
    path = state_path or default_state_path(context)
    state = load_state(path)
    active_login = get_active_login(hostname, cwd, runner)

    if not state:
        return {
            "action": "no-state",
            "active_login": active_login,
            "state_file": str(path),
            "dry_run": dry_run,
        }

    if state.hostname != hostname:
        raise IdentityError("Saved state belongs to a different host. Refusing to guess.")

    if state.depth > 1:
        state.depth -= 1
        if not dry_run:
            save_state(path, state)
        return {
            "action": "decremented-depth",
            "active_login": active_login,
            "target_user": state.target_login,
            "previous_login": state.previous_login,
            "depth": state.depth,
            "state_file": str(path),
            "dry_run": dry_run,
        }

    if active_login == state.previous_login:
        if not dry_run:
            path.unlink(missing_ok=True)
        return {
            "action": "already-restored",
            "active_login": active_login,
            "previous_login": state.previous_login,
            "state_file": str(path),
            "dry_run": dry_run,
        }

    if active_login != state.target_login:
        raise IdentityError(
            "Active gh login does not match either the saved target or the saved previous login. "
            "Refusing to guess which account to restore."
        )

    if dry_run:
        return {
            "action": "would-restore",
            "active_login": active_login,
            "target_user": state.target_login,
            "previous_login": state.previous_login,
            "state_file": str(path),
            "dry_run": True,
        }

    switch_login(hostname, state.previous_login, cwd, runner)
    path.unlink(missing_ok=True)
    return {
        "action": "restored",
        "active_login": state.previous_login,
        "target_user": state.target_login,
        "previous_login": state.previous_login,
        "state_file": str(path),
        "dry_run": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage repo-local gh identity switching."
    )
    parser.add_argument(
        "--hostname",
        default="github.com",
        help="GitHub host for gh commands (default: github.com).",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Override the default repo-local state file path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show current gh identity state.")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    status_parser.add_argument(
        "--target-user",
        help="Optional target login to compare against the active gh user.",
    )

    enter_parser = subparsers.add_parser(
        "enter", help="Switch gh to the requested login and save restore state."
    )
    enter_parser.add_argument(
        "--target-user",
        required=True,
        help="GitHub login to activate before repo work.",
    )
    enter_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    enter_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without switching or writing state.",
    )

    leave_parser = subparsers.add_parser(
        "leave", help="Restore the previously active gh login."
    )
    leave_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    leave_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without switching or writing state.",
    )
    return parser.parse_args()


def print_human(payload: dict[str, object]) -> None:
    for key, value in payload.items():
        print(f"{key}: {value}")


def main() -> int:
    args = parse_args()
    cwd = Path.cwd()

    try:
        if args.command == "status":
            payload = build_status(
                cwd=cwd,
                hostname=args.hostname,
                target_user=args.target_user,
                state_path=args.state_file,
                runner=run_command,
            )
        elif args.command == "enter":
            payload = enter_identity(
                cwd=cwd,
                hostname=args.hostname,
                target_user=args.target_user,
                state_path=args.state_file,
                dry_run=args.dry_run,
                runner=run_command,
            )
        else:
            payload = leave_identity(
                cwd=cwd,
                hostname=args.hostname,
                state_path=args.state_file,
                dry_run=args.dry_run,
                runner=run_command,
            )
    except IdentityError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
