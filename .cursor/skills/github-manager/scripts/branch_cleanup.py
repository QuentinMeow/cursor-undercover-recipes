#!/usr/bin/env python3
"""Clean merged local branches and report PR/remote/local-only status."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class Branch:
    name: str
    upstream: str


@dataclass
class Row:
    branch: str
    status: str
    pr: str = ""
    remote: str = ""
    notes: str = ""


def run(cmd: list[str], cwd: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"{cmd[0]} failed"
        raise RuntimeError(message)
    return proc


def git(cwd: str, args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd, check=check)


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def repo_root() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("not inside a Git repository")
    return proc.stdout.strip()


def ref_exists(cwd: str, ref: str) -> bool:
    return git(cwd, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).returncode == 0


def remote_exists(cwd: str, remote: str) -> bool:
    proc = git(cwd, ["remote"])
    return remote in {line.strip() for line in proc.stdout.splitlines()}


def base_branch_name(base_ref: str, remote: str) -> str:
    if base_ref.startswith("refs/heads/"):
        return base_ref.removeprefix("refs/heads/")
    remote_prefix = f"{remote}/"
    if base_ref.startswith(remote_prefix):
        return base_ref.removeprefix(remote_prefix)
    if "/" not in base_ref:
        return base_ref
    return base_ref.rsplit("/", 1)[1]


def resolve_base(cwd: str, remote: str, explicit_base: str | None) -> tuple[str, str]:
    if explicit_base:
        if not ref_exists(cwd, explicit_base):
            raise RuntimeError(f"base ref does not exist: {explicit_base}")
        return explicit_base, explicit_base

    remote_head = git(cwd, ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"])
    if remote_head.returncode == 0 and remote_head.stdout.strip():
        base = remote_head.stdout.strip()
        if ref_exists(cwd, base):
            return base, base

    for candidate in ("main", "master", f"{remote}/main", f"{remote}/master"):
        if ref_exists(cwd, candidate):
            return candidate, candidate

    raise RuntimeError(f"could not resolve a base branch from {remote}/HEAD, main, or master")


def refresh_default_base(cwd: str, remote: str, explicit_base: str | None, notes: list[str]) -> None:
    if explicit_base:
        return
    if not remote_exists(cwd, remote):
        notes.append(f"remote not found, skipped fetch: {remote}")
        return

    fetch_proc = git(cwd, ["fetch", "--prune", remote])
    if fetch_proc.returncode != 0:
        notes.append(f"fetch failed: {first_line(fetch_proc.stderr) or first_line(fetch_proc.stdout)}")
        return

    try:
        base_ref, _ = resolve_base(cwd, remote, None)
    except RuntimeError as exc:
        notes.append(str(exc))
        return

    local_base = base_branch_name(base_ref, remote)
    if local_base not in {"main", "master"} or not ref_exists(cwd, local_base):
        return

    if current_branch(cwd) == local_base:
        update_proc = git(cwd, ["pull", "--ff-only", remote, local_base])
        action = f"pull {remote} {local_base}"
    else:
        update_proc = git(cwd, ["fetch", remote, f"{local_base}:refs/heads/{local_base}"])
        action = f"fast-forward local {local_base}"

    if update_proc.returncode != 0:
        reason = first_line(update_proc.stderr) or first_line(update_proc.stdout)
        notes.append(f"could not {action}; comparing refreshed {remote}/{local_base}: {reason}")


def local_base_names(base_ref: str) -> set[str]:
    names = {"main", "master"}
    if base_ref.startswith("refs/heads/"):
        names.add(base_ref.removeprefix("refs/heads/"))
    elif "/" in base_ref:
        names.add(base_ref.split("/", 1)[1])
    else:
        names.add(base_ref)
    return names


def list_local_branches(cwd: str) -> list[Branch]:
    proc = git(
        cwd,
        ["for-each-ref", "--format=%(refname:short)%00%(upstream:short)", "refs/heads"],
        check=True,
    )
    branches: list[Branch] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\0")
        branches.append(Branch(name=parts[0], upstream=parts[1] if len(parts) > 1 else ""))
    return branches


def current_branch(cwd: str) -> str:
    proc = git(cwd, ["branch", "--show-current"])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def is_ancestor(cwd: str, branch: str, base_ref: str) -> bool:
    branch_ref = f"refs/heads/{branch}"
    return git(cwd, ["merge-base", "--is-ancestor", branch_ref, base_ref]).returncode == 0


def matching_remote(cwd: str, remote: str, branch: str, upstream: str) -> str:
    if upstream:
        return upstream
    remote_ref = f"refs/remotes/{remote}/{branch}"
    if git(cwd, ["show-ref", "--verify", "--quiet", remote_ref]).returncode == 0:
        return f"{remote}/{branch}"
    return ""


class PrLookup:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.disabled_reason = ""
        self.cache: dict[str, tuple[dict[str, Any] | None, str]] = {}
        if shutil.which("gh") is None:
            self.disabled_reason = "gh is not installed"

    def lookup(self, branch: str) -> tuple[dict[str, Any] | None, str]:
        if self.disabled_reason:
            return None, self.disabled_reason
        if branch in self.cache:
            return self.cache[branch]

        proc = run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--limit",
                "10",
                "--json",
                "number,title,state,url,isDraft,updatedAt",
            ],
            cwd=self.cwd,
        )
        if proc.returncode != 0:
            reason = first_line(proc.stderr) or first_line(proc.stdout) or "gh pr list failed"
            self.disabled_reason = f"PR lookup unavailable: {reason}"
            result = (None, self.disabled_reason)
            self.cache[branch] = result
            return result

        try:
            prs = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            result = (None, "PR lookup unavailable: gh returned invalid JSON")
            self.cache[branch] = result
            return result

        if not prs:
            result = (None, "")
            self.cache[branch] = result
            return result

        def sort_key(pr: dict[str, Any]) -> tuple[int, str]:
            state_rank = {"OPEN": 0, "MERGED": 1, "CLOSED": 2}.get(str(pr.get("state", "")), 9)
            return state_rank, str(pr.get("updatedAt", ""))

        selected = sorted(prs, key=sort_key)[0]
        result = (selected, "")
        self.cache[branch] = result
        return result


def pr_cells(pr: dict[str, Any]) -> tuple[str, str, str]:
    state = str(pr.get("state", "unknown")).lower()
    if pr.get("isDraft") and state == "open":
        state = "draft open"
    number = pr.get("number")
    url = str(pr.get("url", ""))
    title = str(pr.get("title", ""))
    link = f"[#{number} {state}]({url})" if number and url else state
    return f"PR created ({state})", link, title


def clean_branch(cwd: str, branch: str) -> tuple[bool, str]:
    proc = git(cwd, ["branch", "-d", "--", branch])
    if proc.returncode == 0:
        return True, first_line(proc.stdout)
    return False, first_line(proc.stderr) or first_line(proc.stdout) or "git branch -d failed"


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def code_cell(value: str) -> str:
    escaped = value.replace("`", "\\`")
    return f"`{escaped}`"


def print_table(rows: list[Row]) -> None:
    print("| Branch | Status | PR | Remote | Notes |")
    print("|--------|--------|----|--------|-------|")
    for row in rows:
        print(
            "| "
            + " | ".join(
                [
                    code_cell(row.branch),
                    markdown_cell(row.status),
                    markdown_cell(row.pr),
                    markdown_cell(row.remote),
                    markdown_cell(row.notes),
                ]
            )
            + " |"
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean local branches merged into main/master and print a branch status table."
    )
    parser.add_argument("--base", help="Base ref to check for merged branches. Defaults to origin/HEAD, main, or master.")
    parser.add_argument("--remote", default="origin", help="Remote name used for fetch and remote-branch detection.")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--clean", action="store_true", help="Delete safely merged local branches with git branch -d.")
    mode.add_argument("--dry-run", action="store_true", help="Preview cleanup without deleting branches.")

    fetch = parser.add_mutually_exclusive_group()
    fetch.add_argument(
        "--fetch",
        dest="fetch",
        action="store_true",
        help="Refresh the default base before inspecting branches. This is the default.",
    )
    fetch.add_argument("--no-fetch", dest="fetch", action="store_false", help="Skip refreshing the default base.")
    parser.set_defaults(fetch=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    notes: list[str] = []

    try:
        cwd = repo_root()
        if args.fetch:
            refresh_default_base(cwd, args.remote, args.base, notes)

        base_ref, base_label = resolve_base(cwd, args.remote, args.base)
        branches = list_local_branches(cwd)
        current = current_branch(cwd)
        protected = local_base_names(base_ref)
        if current:
            protected.add(current)

        pr_lookup = PrLookup(cwd)
        clean = bool(args.clean)
        rows: list[Row] = []

        for branch in branches:
            branch_notes: list[str] = []
            if branch.name == current:
                branch_notes.append("current branch")

            branch_is_base = branch.name in local_base_names(base_ref)
            merged = is_ancestor(cwd, branch.name, base_ref)
            remote_ref = matching_remote(cwd, args.remote, branch.name, branch.upstream)

            if branch_is_base:
                rows.append(Row(branch.name, "base branch", remote=remote_ref, notes=", ".join(branch_notes)))
                continue

            if merged and branch.name not in protected:
                if clean:
                    deleted, message = clean_branch(cwd, branch.name)
                    if deleted:
                        rows.append(Row(branch.name, "merged and cleaned locally", remote=remote_ref, notes=message))
                    else:
                        rows.append(Row(branch.name, "merged; cleanup failed", remote=remote_ref, notes=message))
                else:
                    rows.append(Row(branch.name, "merged; would clean locally", remote=remote_ref, notes=", ".join(branch_notes)))
                continue

            pr, pr_error = pr_lookup.lookup(branch.name)
            if pr:
                status, link, title = pr_cells(pr)
                rows.append(Row(branch.name, status, pr=link, remote=remote_ref, notes=title))
            elif remote_ref:
                if pr_error:
                    branch_notes.append(pr_error)
                rows.append(Row(branch.name, "pushed to remote", remote=remote_ref, notes=", ".join(branch_notes)))
            else:
                if pr_error:
                    branch_notes.append(pr_error)
                rows.append(Row(branch.name, "local only", notes=", ".join(branch_notes)))

        print(f"Base: `{base_label}`")
        print(f"Mode: `{'clean' if clean else 'dry-run'}`")
        print()
        print_table(rows)

        if notes:
            print()
            print("Notes:")
            for note in notes:
                print(f"- {note}")
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
